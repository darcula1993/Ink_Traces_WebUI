import base64
import hashlib
import io
import json
import os

from flask import jsonify
from PIL import Image
import requests

import app as application
import storage
import tasks as task_db
import worker as generation_worker


def _png_data_url():
    buffer = io.BytesIO()
    Image.new('RGB', (2, 2), (20, 40, 60)).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def _png_bytes():
    return base64.b64decode(_png_data_url().split(',', 1)[1])


def test_image_generation_is_queued_and_result_is_lightweight(monkeypatch):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'test-key',
        'endpoint': 'https://provider.invalid',
        'model': 'test-model',
    })

    def fake_generate(*_args, **_kwargs):
        return jsonify({'success': True, 'images': [_png_data_url()], 'thinking': 'done'})

    monkeypatch.setattr(application, '_generate_ark_image', fake_generate)
    client = application.app.test_client()
    response = client.post('/api/generate', json={
        'prompt': 'test',
        'provider': 'ark',
        'aspect_ratio': '1:1',
        'resolution': '1K',
    })
    assert response.status_code == 202
    task_id = response.get_json()['task_id']

    claimed = task_db.claim_next_task('test-worker')
    assert claimed['id'] == task_id
    with application.app.app_context():
        payload, status_code = application.execute_image_task(task_id)

    assert status_code == 200
    assert payload['images'] == [f'/api/tasks/{task_id}/file/image_0.png']
    task = task_db.get_task(task_id)
    assert task['status'] == 'succeeded'
    assert 'prompt_optimization' not in task['params']
    assert 'images' not in task['result']
    assert task['result']['local_images'] == payload['images']
    assert task['result']['local_thumbnails'] == [f'/api/tasks/{task_id}/file/thumb_0.webp']
    assert os.path.isfile(os.path.join(task['output_dir'], 'image_0.png'))
    thumbnail_path = os.path.join(task['output_dir'], 'thumb_0.webp')
    assert os.path.isfile(thumbnail_path)
    with Image.open(thumbnail_path) as thumbnail:
        assert thumbnail.format == 'WEBP'
        assert max(thumbnail.size) <= 512
    assets = task_db.list_assets(task_id)
    assert [asset['kind'] for asset in assets] == ['output_image', 'output_thumbnail']

    media = client.get(task['result']['local_images'][0])
    assert media.status_code == 200
    assert media.cache_control.public is True
    assert media.cache_control.immutable is True
    assert media.cache_control.max_age == 31536000


def test_workspace_upload_is_reused_by_image_task(monkeypatch):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'test-key',
        'endpoint': 'https://provider.invalid',
        'model': 'test-model',
    })
    client = application.app.test_client()

    upload = client.post('/api/workspace/assets/img_tabs', data={
        'file': (io.BytesIO(_png_bytes()), 'reference.png'),
    })
    assert upload.status_code == 201
    asset = upload.get_json()['asset']
    assert asset['url'].startswith('/api/workspace/assets/img_tabs/')
    assert asset['mime_type'] == 'image/png'
    stored_workspace_path = storage.resolve_workspace_asset_url('img_tabs', asset['url'])
    with Image.open(io.BytesIO(client.get(asset['url']).data)) as image:
        assert image.size == (2, 2)

    response = client.post('/api/generate', json={
        'prompt': 'reuse workspace reference',
        'provider': 'ark',
        'aspect_ratio': '1:1',
        'resolution': '1K',
        'image_urls': [asset['url']],
    })
    assert response.status_code == 202
    task_id = response.get_json()['task_id']
    input_assets = [asset for asset in task_db.list_assets(task_id) if asset['kind'] == 'input_image']
    assert len(input_assets) == 1
    assert os.stat(input_assets[0]['path']).st_ino == os.stat(stored_workspace_path).st_ino
    with Image.open(input_assets[0]['path']) as image:
        assert image.size == (2, 2)


def test_png_download_embeds_only_reusable_generation_metadata():
    task_id = task_db.create_task(
        'image', '带有细节的测试 Prompt', {
            'aspect_ratio': '9:16',
            'resolution': '2K',
            'output_format': 'png',
            'watermark': False,
            'use_search': True,
            'think_level': 'high',
            'provider': 'ark',
            'model': 'private-model-name',
            'session_id': 'private-session',
            'api_key': 'private-key',
        },
        provider='ark',
    )
    output_dir = storage.task_output_dir('image', task_id)
    path = os.path.join(output_dir, 'image_0.png')
    with open(path, 'wb') as handle:
        handle.write(_png_bytes())
    original_digest = hashlib.sha256(_png_bytes()).hexdigest()
    storage.register_file(task_id, 'output_image', path, 'image/png')
    task_db.complete_task(task_id, {'local_images': [f'/api/tasks/{task_id}/file/image_0.png']}, output_dir)

    client = application.app.test_client()
    response = client.get(f'/api/tasks/{task_id}/download/image_0.png')

    assert response.status_code == 200
    assert response.headers['Content-Disposition'].startswith(
        f'attachment; filename="ink-traces-image-task-{task_id}-'
    )
    assert response.headers['Content-Disposition'].endswith('-output-01.png"')
    with Image.open(io.BytesIO(response.data)) as image:
        embedded = json.loads(image.text['ink_traces'])
        readable = image.text['parameters']
        assert image.size == (2, 2)
    assert embedded == {
        'schema': 'ink-traces/png-info/v1',
        'prompt': '带有细节的测试 Prompt',
        'params': {
            'aspect_ratio': '9:16',
            'resolution': '2K',
            'output_format': 'png',
            'watermark': False,
            'use_search': True,
            'think_level': 'high',
        },
    }
    assert 'provider' not in readable
    assert 'private-model-name' not in readable
    with open(path, 'rb') as handle:
        assert hashlib.sha256(handle.read()).hexdigest() == original_digest

    info = client.post('/api/png-info', data={
        'file': (io.BytesIO(response.data), 'metadata-image.png'),
    })
    assert info.status_code == 200
    payload = info.get_json()
    assert payload['metadata']['source'] == 'ink_traces'
    assert payload['metadata']['prompt'] == '带有细节的测试 Prompt'
    assert payload['metadata']['params']['aspect_ratio'] == '9:16'
    assert payload['image']['width'] == 2
    assert payload['image']['height'] == 2

def test_image_task_rejects_non_workspace_reference_url(monkeypatch):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'test-key',
        'endpoint': 'https://provider.invalid',
        'model': 'test-model',
    })
    response = application.app.test_client().post('/api/generate', json={
        'prompt': 'invalid reference',
        'provider': 'ark',
        'aspect_ratio': '1:1',
        'resolution': '1K',
        'image_urls': ['https://example.com/reference.png'],
    })

    assert response.status_code == 400
    assert '不属于当前工作区' in response.get_json()['error']


def test_running_image_cancellation_discards_provider_result(monkeypatch):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'test-key',
        'endpoint': 'https://provider.invalid',
        'model': 'test-model',
    })
    task_id = task_db.create_task(
        'image', 'cancel me',
        {'provider': 'ark', 'aspect_ratio': '1:1', 'resolution': '1K'},
        provider='ark',
    )
    task_db.update_task(task_id, output_dir=storage.task_output_dir('image', task_id))
    task_db.claim_next_task('worker-a')

    def fake_generate(*_args, **_kwargs):
        assert task_db.request_task_cancel(task_id) == 'cancel_requested'
        return jsonify({'success': True, 'images': [_png_data_url()]})

    monkeypatch.setattr(application, '_generate_ark_image', fake_generate)
    with application.app.app_context():
        payload, status_code = application.execute_image_task(task_id)

    assert status_code == 409
    assert payload['cancelled'] is True
    task = task_db.get_task(task_id)
    assert task['status'] == 'cancelled'
    assert task['result'] is None
    assert task_db.list_assets(task_id) == []


def test_failed_image_retry_clones_reference_inputs():
    source_id = task_db.create_task(
        'image', 'retry me',
        {'provider': 'ark', 'aspect_ratio': '1:1', 'resolution': '1K'},
        provider='ark', status='failed',
    )
    source_dir = storage.task_output_dir('image', source_id)
    reference = os.path.join(source_dir, 'ref_0.png')
    with open(reference, 'wb') as handle:
        handle.write(base64.b64decode(_png_data_url().split(',', 1)[1]))
    storage.register_file(source_id, 'input_image', reference, 'image/png')

    response = application.app.test_client().post(f'/api/tasks/{source_id}/retry')
    assert response.status_code == 202
    retry_id = response.get_json()['task_id']
    retried = task_db.get_task(retry_id)
    assert retried['status'] == 'pending'
    assert retried['retry_of'] == source_id
    assets = task_db.list_assets(retry_id)
    assert len(assets) == 1
    assert assets[0]['kind'] == 'input_image'
    assert os.path.isfile(assets[0]['path'])


def test_ark_read_timeout_is_longer_and_not_retryable(monkeypatch):
    observed = {}

    def fake_post(_url, **kwargs):
        observed['timeout'] = kwargs['timeout']
        raise requests.exceptions.ReadTimeout('provider still processing')

    monkeypatch.setattr(application.HTTP, 'post', fake_post)
    provider = {
        'api_key': 'test-key',
        'endpoint': 'https://provider.invalid',
        'model': 'test-model',
        'upload_timeout_seconds': 123,
        'request_timeout_seconds': 321,
    }

    with application.app.app_context():
        response = application._generate_ark_image(
            'test', '1:1', '1K', [{'text': 'test'}], provider_config=provider
        )
        payload, status_code = application._response_payload(response)

    assert observed['timeout'] == (123, 321)
    assert status_code == 504
    assert payload['error_type'] == 'upstream_timeout'
    assert payload['retryable'] is False
    assert payload['result_unknown'] is True


def test_ark_write_timeout_is_reported_as_ambiguous_and_not_retryable(monkeypatch):
    observed = {}

    def fake_post(_url, **kwargs):
        observed['timeout'] = kwargs['timeout']
        raise requests.exceptions.ConnectionError(
            "('Connection aborted.', TimeoutError('The write operation timed out'))"
        )

    monkeypatch.setattr(application.HTTP, 'post', fake_post)
    provider = {
        'api_key': 'test-key',
        'endpoint': 'https://provider.invalid',
        'model': 'test-model',
        'upload_timeout_seconds': 135,
        'request_timeout_seconds': 360,
    }

    with application.app.app_context():
        response = application._generate_ark_image(
            'test', '1:1', '1K', [{'text': 'test'}], provider_config=provider
        )
        payload, status_code = application._response_payload(response)

    assert observed['timeout'] == (135, 360)
    assert status_code == 504
    assert payload['error_type'] == 'upload_timeout'
    assert payload['retryable'] is False
    assert payload['result_unknown'] is True


def test_ark_request_omits_prompt_optimization(monkeypatch):
    observed = {}

    def fake_post(_url, **kwargs):
        observed['body'] = kwargs['json']
        encoded = _png_data_url().split(',', 1)[1]
        return FakeResponse(payload={'data': [{'b64_json': encoded, 'output_format': 'png'}]})

    monkeypatch.setattr(application.HTTP, 'post', fake_post)
    provider = {
        'api_key': 'test-key',
        'endpoint': 'https://provider.invalid',
        'model': 'test-model',
    }

    with application.app.app_context():
        response = application._generate_ark_image(
            'test', '1:1', '1K', [{'text': 'test'}], provider_config=provider
        )
        payload, status_code = application._response_payload(response)

    assert status_code == 200
    assert payload['success'] is True
    assert 'optimize_prompt_options' not in observed['body']


def test_worker_does_not_replay_ambiguous_ark_timeout(monkeypatch):
    rescheduled = []
    monkeypatch.setattr(
        application,
        'execute_image_task',
        lambda _task_id: ({'success': False, 'retryable': False, 'error': 'unknown'}, 504),
    )
    monkeypatch.setattr(task_db, 'reschedule_task', lambda *args, **kwargs: rescheduled.append((args, kwargs)))

    generation_worker.Worker()._process_image({
        'id': 99,
        'type': 'image',
        'provider': 'ark',
        'attempt_count': 1,
    })

    assert rescheduled == []


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b''):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = 'payload' if payload is not None else ''

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=None):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_video_poll_downloads_once_and_completes(monkeypatch):
    monkeypatch.setitem(application.VIDEO_PROVIDERS, 'ark', {
        'api_key': 'test-key',
        'endpoint': 'https://provider.invalid',
    })
    task_id = task_db.create_task(
        'video', 'prompt', {}, provider='ark', external_task_id='external-1', status='processing'
    )
    output_dir = storage.task_output_dir('video', task_id)
    task_db.update_task(task_id, output_dir=output_dir)

    status_payload = {
        'status': 'succeeded',
        'content': {
            'video_url': 'https://media.invalid/video.mp4',
            'last_frame_url': 'https://media.invalid/frame.png',
        },
    }

    def fake_get(url, **_kwargs):
        if '/tasks/' in url:
            return FakeResponse(payload=status_payload)
        if url.endswith('.mp4'):
            return FakeResponse(content=b'video-bytes')
        return FakeResponse(content=_png_bytes())

    monkeypatch.setattr(application.HTTP, 'get', fake_get)
    outcome = application.poll_video_task_once(task_id)

    assert outcome['state'] == 'succeeded'
    task = task_db.get_task(task_id)
    assert task['status'] == 'succeeded'
    assert task['result']['local_video'] == f'/api/tasks/{task_id}/file/video.mp4'
    assert task['result']['local_last_frame'] == f'/api/tasks/{task_id}/file/last_frame.png'
    assert task['result']['local_thumbnail'] == f'/api/tasks/{task_id}/file/thumbnail.webp'
    assert os.path.isfile(os.path.join(output_dir, 'thumbnail.webp'))
    assert os.path.getsize(os.path.join(output_dir, 'video.mp4')) == len(b'video-bytes')
