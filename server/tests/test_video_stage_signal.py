"""VIDEO-SIGNAL-20261115: server-side "下载写回" stage for video/audio tasks.

While the Provider has reported success and the worker downloads the result,
``/api/tasks/status`` and ``/api/tasks/<id>`` report ``status='processing'`` with
``stage='downloading'``.  The stage never survives a terminal state or a worker
restart, never appears on image/layer tasks and carries no Provider URL.
"""

import json
import os
import sqlite3
import threading

import pytest
import requests

import app as application
import tasks as task_db
import worker
from billing_support import billing_env  # noqa: F401  (fixture)

SIGNED = 'https://bucket.invalid/out/video.mp4?X-Tos-Credential=secret&X-Tos-Signature=sig'
SIGNED_FRAME = 'https://bucket.invalid/out/last.png?X-Tos-Signature=sig2'


class Download:
    def __init__(self, status_code=200, payload=None, content=b'media', on_read=None):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.text = json.dumps(payload) if payload is not None else ''
        self.headers = {}
        self._on_read = on_read

    def json(self):
        return self._payload if self._payload is not None else {}

    def iter_content(self, chunk_size=None):
        if self._on_read:
            self._on_read()
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _observe(task_id):
    """Read both public endpoints from another thread (own SQLite connection), as the
    browser would while the worker thread is still downloading."""
    seen = {}

    def run():
        try:
            client = application.app.test_client()
            batch = client.get(f'/api/tasks/status?ids={task_id}').get_json()
            detail = client.get(f'/api/tasks/{task_id}').get_json()
            seen['status'] = batch['tasks'][0]
            seen['detail'] = detail['task']
        finally:
            task_db.close_db()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(10)
    return seen


def _public(task_id):
    client = application.app.test_client()
    return (client.get(f'/api/tasks/status?ids={task_id}').get_json()['tasks'][0],
            client.get(f'/api/tasks/{task_id}').get_json()['task'])


def _ark_video_task():
    return task_db.create_task('video', 'stage', {'provider': 'ark', 'output_format': 'mp4'},
                               provider='ark', external_task_id='cgt-stage-1', status='processing')


def _ark_success(**content):
    return Download(payload={'status': 'succeeded', 'content': {'video_url': SIGNED, **content}})


def _claim(runner_id='stage-worker'):
    task = task_db.claim_next_task(runner_id, task_types=('video', 'audio'))
    assert task is not None
    return task


# ------------------------------------------------------------------ acceptance 1 / 4

def test_ark_video_reports_downloading_stage_during_download(billing_env, monkeypatch):
    task_id = _ark_video_task()
    seen = {}

    def fake_get(url, **_kwargs):
        if url == SIGNED:
            return Download(content=b'video', on_read=lambda: seen.update(_observe(task_id)))
        if url == SIGNED_FRAME:
            return Download(content=b'not-a-png')
        return _ark_success(last_frame_url=SIGNED_FRAME)

    monkeypatch.setattr(application.HTTP, 'get', fake_get)
    runner = worker.Worker()
    runner.process(_claim(runner.worker_id))

    for view in (seen['status'], seen['detail']):
        assert view['status'] == 'processing'
        assert view['stage'] == 'downloading'
        assert 'X-Tos' not in json.dumps(view, ensure_ascii=False)
        assert 'bucket.invalid/out' not in json.dumps(view, ensure_ascii=False)

    task = task_db.get_task(task_id)
    assert task['status'] == 'succeeded' and task['stage'] is None
    for view in _public(task_id):
        assert view['status'] == 'succeeded' and view['stage'] is None


def test_pending_provider_poll_has_no_stage(billing_env, monkeypatch):
    task_id = _ark_video_task()
    monkeypatch.setattr(application.HTTP, 'get',
                        lambda *_a, **_k: Download(payload={'status': 'running', 'content': {}}))
    runner = worker.Worker()
    runner.process(_claim(runner.worker_id))
    task = task_db.get_task(task_id)
    assert task['status'] == 'processing' and task['stage'] is None
    for view in _public(task_id):
        assert view['stage'] is None


@pytest.mark.parametrize('kind', ['video', 'audio'])
def test_cupsy_reports_downloading_stage_during_download(billing_env, monkeypatch, kind):
    params = {'provider': 'cupsy', 'output_format': 'mp3' if kind == 'audio' else 'mp4'}
    task_id = task_db.create_task(kind, 'stage', params, provider='cupsy',
                                  external_task_id=f'{kind}_remote_1', status='processing')
    seen = {}

    def fake_get(url, **_kwargs):
        if url.endswith('/content'):
            return Download(content=b'media', on_read=lambda: seen.update(_observe(task_id)))
        return Download(payload={'id': f'{kind}_remote_1', 'status': 'succeeded'})

    monkeypatch.setattr(application.HTTP, 'get', fake_get)
    runner = worker.Worker()
    runner.process(_claim(runner.worker_id))

    assert seen['status']['stage'] == 'downloading' == seen['detail']['stage']
    assert seen['status']['status'] == 'processing'
    task = task_db.get_task(task_id)
    assert task['status'] == 'succeeded' and task['stage'] is None


# ------------------------------------------------------------------ acceptance 2

def test_download_failure_keeps_stage_while_retrying_then_clears_on_failure(billing_env, monkeypatch):
    task_id = _ark_video_task()

    def fake_get(url, **_kwargs):
        if url == SIGNED:
            return Download(status_code=503)
        return _ark_success()

    monkeypatch.setattr(application.HTTP, 'get', fake_get)
    monkeypatch.setattr(application, 'VIDEO_CONFIG', {**application.VIDEO_CONFIG, 'poll_max_attempts': 2})
    runner = worker.Worker()

    runner.process(_claim(runner.worker_id))
    task = task_db.get_task(task_id)
    # Existing rule: a download error is a retry (no new Provider submission).
    assert task['status'] == 'processing' and task['completed_at'] is None
    assert task['error'] == '视频下载失败 503'
    assert task['stage'] == 'downloading'

    task_db.get_db().execute('UPDATE tasks SET next_run_at = NULL WHERE id = ?', (task_id,))
    task_db.get_db().commit()
    runner.process(_claim(runner.worker_id))
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed' and task['error'] == '视频下载失败 503'
    assert task['stage'] is None
    for view in _public(task_id):
        assert view['status'] == 'failed' and view['stage'] is None


def test_download_exception_is_retry_with_stage(billing_env, monkeypatch):
    task_id = _ark_video_task()

    def fake_get(url, **_kwargs):
        if url == SIGNED:
            raise requests.ConnectionError(f'connection reset for {SIGNED}')
        return _ark_success()

    monkeypatch.setattr(application.HTTP, 'get', fake_get)
    runner = worker.Worker()
    runner.process(_claim(runner.worker_id))
    task = task_db.get_task(task_id)
    assert task['status'] == 'processing' and task['stage'] == 'downloading'
    status, detail = _public(task_id)
    assert status['stage'] == detail['stage'] == 'downloading'
    assert 'X-Tos' not in json.dumps([status, detail], ensure_ascii=False)


def test_provider_failure_after_stage_clears_it(billing_env, monkeypatch):
    task_id = _ark_video_task()
    task_db.set_task_stage(task_id, task_db.TASK_STAGE_DOWNLOADING)
    monkeypatch.setattr(application.HTTP, 'get', lambda *_a, **_k: Download(
        payload={'status': 'failed', 'error': {'message': 'boom'}}))
    runner = worker.Worker()
    runner.process(_claim(runner.worker_id))
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed' and task['stage'] is None


def test_cancel_during_download_drops_stage(billing_env):
    task_id = _ark_video_task()
    task = _claim()
    assert task_db.set_task_stage(task_id, task_db.TASK_STAGE_DOWNLOADING)
    assert task_db.request_task_cancel(task_id) == 'cancel_requested'
    for view in _public(task_id):
        assert view['stage'] is None
    task_db.finalize_task_cancel(task_id)
    assert task_db.get_task(task_id)['stage'] is None


def test_worker_restart_does_not_leave_stage_stuck(billing_env, monkeypatch):
    task_id = _ark_video_task()
    dead = 'dead-host:999999:abc'
    task_db.upsert_worker_heartbeat(dead, 999999999, task_db.utcnow())
    _claim(dead)
    assert task_db.set_task_stage(task_id, task_db.TASK_STAGE_DOWNLOADING)

    assert task_db.recover_dead_worker_leases() >= 1
    task = task_db.get_task(task_id)
    assert task['status'] == 'processing' and task['stage'] is None and task['lease_owner'] is None
    for view in _public(task_id):
        assert view['stage'] is None

    # The next poll re-derives the stage from the Provider and finishes normally.
    monkeypatch.setattr(application.HTTP, 'get',
                        lambda url, **_k: Download(content=b'v') if url == SIGNED else _ark_success())
    runner = worker.Worker()
    runner.process(_claim(runner.worker_id))
    task = task_db.get_task(task_id)
    assert task['status'] == 'succeeded' and task['stage'] is None


def test_graceful_worker_stop_clears_stage(billing_env):
    task_id = _ark_video_task()
    _claim('stopping-worker')
    task_db.set_task_stage(task_id, task_db.TASK_STAGE_DOWNLOADING)
    task_db.release_worker_leases('stopping-worker')
    assert task_db.get_task(task_id)['stage'] is None


# ------------------------------------------------------------------ acceptance 3 / 4

def test_stage_only_published_for_processing_and_known_values():
    task_id = task_db.create_task('image', 'img', {'provider': 'ark'}, provider='ark')
    for status, stage, expected in (
        ('processing', 'downloading', 'downloading'),
        ('failed', 'downloading', None),
        ('succeeded', 'downloading', None),
        ('cancelled', 'downloading', None),
        ('processing', 'https://bucket.invalid/x?X-Tos-Signature=s', None),
        ('processing', None, None),
    ):
        task_db.get_db().execute('UPDATE tasks SET status = ?, stage = ? WHERE id = ?',
                                 (status, stage, task_id))
        task_db.get_db().commit()
        for view in _public(task_id):
            assert view['stage'] == expected, (status, stage)


def test_set_task_stage_rejects_unknown_values_and_non_processing_tasks():
    task_id = task_db.create_task('video', 'v', {'provider': 'ark'}, provider='ark',
                                  external_task_id='cgt-x', status='pending')
    with pytest.raises(ValueError):
        task_db.set_task_stage(task_id, 'uploading')
    assert task_db.set_task_stage(task_id, task_db.TASK_STAGE_DOWNLOADING) is False
    assert task_db.get_task(task_id)['stage'] is None


def test_reschedule_clears_stage_unless_download_retry():
    task_id = _ark_video_task()
    task_db.set_task_stage(task_id, task_db.TASK_STAGE_DOWNLOADING)
    task_db.reschedule_task(task_id, 1, status='processing')
    assert task_db.get_task(task_id)['stage'] is None
    task_db.set_task_stage(task_id, task_db.TASK_STAGE_DOWNLOADING)
    task_db.reschedule_task(task_id, 1, status='processing', stage=task_db.TASK_STAGE_DOWNLOADING)
    assert task_db.get_task(task_id)['stage'] == 'downloading'
    task_db.reschedule_task(task_id, 1, status='pending', stage=task_db.TASK_STAGE_DOWNLOADING)
    assert task_db.get_task(task_id)['stage'] is None


def test_summary_list_includes_stage_and_old_database_gains_column(tmp_path):
    tasks, _ = task_db.list_tasks(summary=True)
    assert tasks == [] or 'stage' in tasks[0]
    task_db.create_task('image', 'img', {}, provider='ark')
    tasks, _ = task_db.list_tasks(summary=True)
    assert tasks[0]['stage'] is None

    old = tmp_path / 'old.db'
    connection = sqlite3.connect(old)
    connection.execute('''CREATE TABLE tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', prompt TEXT, params TEXT, provider TEXT,
        external_task_id TEXT, result TEXT, error TEXT, output_dir TEXT,
        created_at TEXT NOT NULL, completed_at TEXT)''')
    connection.execute("INSERT INTO tasks (type, status, prompt, created_at) "
                       "VALUES ('video', 'succeeded', 'legacy', '2026-01-01T00:00:00+00:00')")
    connection.commit()
    connection.close()
    task_db.configure(old)
    legacy = task_db.get_task(1)
    assert legacy['status'] == 'succeeded' and legacy['stage'] is None
    assert os.path.exists(old)
