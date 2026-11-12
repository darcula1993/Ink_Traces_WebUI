"""Shared fixtures/helpers for the billing-boundary regression suite (test_billing_boundary_*.py).

Everything is mocked or bound to 127.0.0.1; no request ever leaves the host.
"""

import io
import os
import socket
import struct
import threading

import pytest
import requests
from PIL import Image

import app as application
import storage
import tasks as task_db
import worker

UNKNOWN_PHRASE = '结果未知'
ACCEPTED_ID = 'cgt-accepted-123'

# --- synthetic requests errors, grouped by what the classifier must conclude -------------

ABORTED = requests.exceptions.ConnectionError(
    "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))")
RESET = requests.exceptions.ConnectionError(
    "('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))")
WRITE_TIMEOUT = requests.exceptions.ConnectionError(
    "('Connection aborted.', TimeoutError('The write operation timed out'))")
DNS = requests.exceptions.ConnectionError(
    "HTTPSConnectionPool(host='p.invalid', port=443): Max retries exceeded "
    "(Caused by NameResolutionError(\"Failed to resolve 'p.invalid'\"))")
REFUSED = requests.exceptions.ConnectionError(
    "HTTPSConnectionPool(host='p.invalid', port=443): Max retries exceeded (Caused by "
    "NewConnectionError('Failed to establish a new connection: [Errno 111] Connection refused'))")


def maybe_sent_errors():
    """(id, error, expected error_type) for errors that may have reached the provider."""
    return [
        ('read_timeout', requests.exceptions.ReadTimeout('provider still processing'), 'upstream_timeout'),
        ('write_timeout', WRITE_TIMEOUT, 'upload_timeout'),
        ('aborted', ABORTED, 'request_error_unknown'),
        ('reset', RESET, 'request_error_unknown'),
        ('ssl', requests.exceptions.SSLError('EOF occurred in violation of protocol'), 'request_error_unknown'),
        ('chunked', requests.exceptions.ChunkedEncodingError('incomplete chunk'), 'request_error_unknown'),
    ]


def unsent_errors():
    """(id, error) for errors that prove no request bytes left the process."""
    return [
        ('connect_timeout', requests.exceptions.ConnectTimeout('connect timed out')),
        ('dns', DNS),
        ('refused', REFUSED),
    ]


# --- fixtures -----------------------------------------------------------------------------

class Response:
    def __init__(self, payload=None, json_error=None, status_code=200, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._json_error = json_error
        self.text = 'payload'
        self.headers = headers or {}

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class PostRecorder:
    def __init__(self, monkeypatch):
        self.calls = []
        self._monkeypatch = monkeypatch

    def install(self, behaviour):
        """behaviour: exception instance, Response, or callable(url, kwargs)."""
        def fake_post(url, **kwargs):
            self.calls.append({'url': url, 'headers': dict(kwargs.get('headers') or {})})
            if isinstance(behaviour, BaseException):
                raise behaviour
            if callable(behaviour):
                return behaviour(url, kwargs)
            return behaviour
        self._monkeypatch.setattr(application.HTTP, 'post', fake_post)
        return self

    @property
    def count(self):
        return len(self.calls)


@pytest.fixture
def billing_env(monkeypatch, tmp_path):
    error_logs = tmp_path / 'error_logs'
    error_logs.mkdir(exist_ok=True)
    monkeypatch.setattr(application, 'ERROR_LOGS_DIR', str(error_logs))
    monkeypatch.setattr(worker.application, 'config', {**application.config, 'server': {}})
    monkeypatch.delenv('WORKER_CONCURRENCY', raising=False)
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'test-key', 'endpoint': 'https://provider.invalid', 'model': 'test-model',
    })
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {
        'api_key': 'test-key', 'endpoint': 'https://provider.invalid',
        'model': 'seedance-20-endpoint', 'seedance_2_5_model': 'ep-test',
    })
    monkeypatch.setattr(application, 'CUPSY_VIDEO_CONFIG', {
        'api_key': 'test-key', 'endpoint': 'https://cupsy.invalid',
        'source_base_url': 'https://source.invalid',
    })
    return error_logs


@pytest.fixture
def posts(monkeypatch):
    return PostRecorder(monkeypatch)


# --- task builders and drivers -----------------------------------------------------------

def image_task(provider):
    params = {'provider': provider, 'aspect_ratio': '1:1', 'resolution': '1K'}
    if provider == 'cupsy':
        params.update({'size': '1280x720', 'output_format': 'png'})
    task_id = task_db.create_task('image', 'billing', params, provider=provider)
    task_db.update_task(task_id, output_dir=storage.task_output_dir('image', task_id))
    return task_id


def png_bytes():
    buffer = io.BytesIO()
    Image.new('RGB', (2, 2), (20, 40, 60)).save(buffer, format='PNG')
    return buffer.getvalue()


def layer_task(with_source=True):
    task_id = task_db.create_task('layer', 'layers', {
        'project_id': 1, 'size': 'auto', 'output_format': 'png', 'provider': 'ark',
        'layer_decomposition': True,
    }, provider='ark')
    output_dir = storage.task_output_dir('layer', task_id)
    if with_source:
        source = os.path.join(output_dir, 'source.png')
        with open(source, 'wb') as handle:
            handle.write(png_bytes())
        storage.register_file(task_id, 'input_image', source, 'image/png')
    task_db.update_task(task_id, output_dir=output_dir)
    return task_id


def poll_task(task_type, provider, external_task_id=None):
    params = {'provider': provider}
    if task_type == 'audio':
        params.update({'output_format': 'mp3'})
    return task_db.create_task(task_type, 'billing', params, provider=provider,
                               external_task_id=external_task_id)


def run_until_idle(runner, task_types=('image', 'layer'), limit=8):
    """Claim/process until nothing is claimable; backoff is collapsed so resubmits show up."""
    processed = 0
    while processed < limit:
        task = task_db.claim_next_task(runner.worker_id, task_types=task_types)
        if task is None:
            return processed
        runner.process(task)
        processed += 1
        task_db.get_db().execute('UPDATE tasks SET next_run_at = NULL WHERE completed_at IS NULL')
        task_db.get_db().commit()
    return processed


def nothing_claimable():
    return all(
        task_db.claim_next_task('probe-worker', task_types=types) is None
        for types in (('image', 'layer'), ('video', 'audio'), None)
    )


def polled(task_id):
    body = application.app.test_client().get(f'/api/tasks/status?ids={task_id}').get_json()
    return body['tasks'][0]


def summary(task_id):
    tasks, _ = task_db.list_tasks(summary=True)
    return next(task for task in tasks if task['id'] == task_id)


def assert_unknown(task_id, error_type, phrase=UNKNOWN_PHRASE):
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['result']['result_unknown'] is True
    assert task['result']['error_type'] == error_type
    assert phrase in task['error']
    assert polled(task_id)['result']['result_unknown'] is True
    assert summary(task_id)['result']['result_unknown'] is True
    return task


def assert_known_failure(task_id):
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert not (task.get('result') or {}).get('result_unknown')
    status_result = polled(task_id)['result']
    assert status_result is None or status_result['result_unknown'] is False
    return task


def video_body(**extra):
    return {
        'provider': 'ark', 'model': 'seedance-2.5', 'prompt': 'shot', 'ratio': 'adaptive',
        'duration': 28, 'resolution': '480p', 'output_format': 'mp4', 'video_mode': 'reference',
        **extra,
    }


def submit_video(**extra):
    return application.app.test_client().post('/api/video/generate', json=video_body(**extra))


def only_video_task_id():
    tasks, _ = task_db.list_tasks(summary=True)
    videos = [task for task in tasks if task['type'] == 'video']
    assert len(videos) == 1
    return videos[0]['id']


# --- real local sockets -------------------------------------------------------------------

class LocalServer:
    """Minimal 127.0.0.1 TCP server that reads one HTTP request per connection, then misbehaves.

    modes: 'close' (read then close), 'hang' (read, never answer), 'reset' (read then RST),
    'garbage' (read whatever arrives, e.g. a TLS ClientHello, answer plaintext and close).
    """

    def __init__(self, mode):
        self.mode = mode
        self.posts = 0
        self.connections = 0
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('127.0.0.1', 0))
        self._sock.listen(8)
        self._sock.settimeout(0.1)
        self.port = self._sock.getsockname()[1]
        self._clients = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _read_request(self, conn):
        data = b''
        conn.settimeout(5)
        while b'\r\n\r\n' not in data:
            chunk = conn.recv(65536)
            if not chunk:
                return data
            data += chunk
            if self.mode == 'garbage':
                return data
        head, _, body = data.partition(b'\r\n\r\n')
        length = 0
        for line in head.split(b'\r\n'):
            if line.lower().startswith(b'content-length:'):
                length = int(line.split(b':', 1)[1].strip())
        while len(body) < length:
            chunk = conn.recv(65536)
            if not chunk:
                break
            body += chunk
        if head.startswith(b'POST '):
            self.posts += 1
        return data

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            self.connections += 1
            self._clients.append(conn)
            try:
                self._read_request(conn)
                if self.mode == 'close':
                    conn.close()
                elif self.mode == 'reset':
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
                    conn.close()
                elif self.mode == 'garbage':
                    conn.sendall(b'HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n')
                    conn.close()
                # 'hang': keep the socket open until stop()
            except OSError:
                pass

    def url(self, scheme='http'):
        return f'{scheme}://127.0.0.1:{self.port}'

    def stop(self):
        self._stop.set()
        for conn in self._clients:
            try:
                conn.close()
            except OSError:
                pass
        self._sock.close()
        self._thread.join(timeout=2)


def closed_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def local_server():
    servers = []

    def start(mode):
        server = LocalServer(mode)
        servers.append(server)
        return server
    yield start
    for server in servers:
        server.stop()
