"""ENGINE-FOLLOWUP-20261112: in-process exceptions and video submit timeouts keep the billing boundary."""

import io
import os

import pytest
import requests
from PIL import Image

import app as application
import storage
import tasks as task_db
import worker


class _Response:
    def __init__(self, payload=None, json_error=None, status_code=200):
        self.status_code = status_code
        self._payload = payload or {}
        self._json_error = json_error
        self.text = 'payload'
        self.headers = {}

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(worker.application, 'config', {'server': {}})
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'test-key', 'endpoint': 'https://provider.invalid', 'model': 'test-model',
    })
    calls = []

    def install_post(behaviour):
        def fake_post(url, **_kwargs):
            calls.append(url)
            return behaviour()
        monkeypatch.setattr(application.HTTP, 'post', fake_post)

    return worker.Worker(), calls, install_post


def _image_task(provider):
    task_id = task_db.create_task(
        'image', 'crash', {'provider': provider, 'aspect_ratio': '1:1', 'resolution': '1K'},
        provider=provider,
    )
    task_db.update_task(task_id, output_dir=storage.task_output_dir('image', task_id))
    return task_id


def _run_until_idle(runner_worker, limit=6):
    processed = 0
    while processed < limit:
        task = task_db.claim_next_task(runner_worker.worker_id, task_types=('image', 'layer'))
        if task is None:
            return processed
        runner_worker.process(task)
        processed += 1
        # Make any backoff immediately due so a resubmission would be observed.
        task_db.get_db().execute('UPDATE tasks SET next_run_at = NULL WHERE completed_at IS NULL')
        task_db.get_db().commit()
    raise AssertionError('task kept being claimed')


def _assert_unknown(task_id, error_type='worker_exception'):
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['result']['result_unknown'] is True
    assert task['result']['error_type'] == error_type
    assert '请求可能已发出、结果未知，请先到Provider核实' in task['error']
    status = application.app.test_client().get(f'/api/tasks/status?ids={task_id}').get_json()
    assert status['tasks'][0]['result']['result_unknown'] is True
    return task


def test_ark_exception_after_dispatch_fails_once_with_unknown(runner):
    runner_worker, calls, install_post = runner
    install_post(lambda: _Response(json_error=ValueError('broken provider body')))
    task_id = _image_task('ark')

    assert _run_until_idle(runner_worker) == 1
    assert len(calls) == 1
    _assert_unknown(task_id)


def test_unknown_provider_task_fails_without_dispatch(runner):
    runner_worker, calls, install_post = runner
    install_post(lambda: _Response())
    task_id = _image_task('acme')

    assert _run_until_idle(runner_worker) == 1
    assert calls == []
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed' and '不支持的图片 provider' in task['error']
    assert not (task.get('result') or {}).get('result_unknown')


def test_exception_escaping_to_worker_after_dispatch_is_unknown(runner, monkeypatch):
    # Provider returned an image, then an unexpected local error reached Worker.process.
    runner_worker, calls, install_post = runner
    install_post(lambda: _Response(payload={
        'data': [{'url': 'https://media.invalid/generated.png', 'output_format': 'png'}],
    }))

    def broken_save(*_args, **_kwargs):
        raise RuntimeError('unexpected save crash')
    monkeypatch.setattr(application, '_save_generated_image', broken_save)
    task_id = _image_task('ark')
    task_db.update_task(task_id, result={'note': 'kept'})

    assert _run_until_idle(runner_worker) == 1
    assert len(calls) == 1
    task = _assert_unknown(task_id)
    assert task['result']['note'] == 'kept'
    assert 'unexpected save crash' in task['error']


def _layer_task():
    task_id = task_db.create_task('layer', 'layers', {
        'project_id': 1, 'size': 'auto', 'output_format': 'png', 'provider': 'ark',
        'layer_decomposition': True,
    }, provider='ark')
    output_dir = storage.task_output_dir('layer', task_id)
    source = os.path.join(output_dir, 'source.png')
    buffer = io.BytesIO()
    Image.new('RGB', (2, 2), (20, 40, 60)).save(buffer, format='PNG')
    with open(source, 'wb') as handle:
        handle.write(buffer.getvalue())
    storage.register_file(task_id, 'input_image', source, 'image/png')
    task_db.update_task(task_id, output_dir=output_dir)
    return task_id


def test_layer_exception_after_dispatch_is_unknown(runner):
    # Exception escapes _generate_ark_image (response body parse) and reaches Worker.process.
    runner_worker, calls, install_post = runner
    install_post(lambda: _Response(json_error=ValueError('broken provider body')))
    task_id = _layer_task()

    assert _run_until_idle(runner_worker) == 1
    assert len(calls) == 1
    _assert_unknown(task_id)


@pytest.mark.parametrize('provider', ['ark'])
def test_pre_dispatch_exception_is_not_marked_unknown(runner, monkeypatch, provider):
    runner_worker, calls, install_post = runner
    install_post(lambda: _Response())

    def broken_config(*_args, **_kwargs):
        raise RuntimeError('local config failure')
    monkeypatch.setattr(application, 'get_image_provider_config', broken_config)
    task_id = _image_task(provider)

    assert _run_until_idle(runner_worker) == 1
    assert calls == []
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['error'] == 'local config failure'
    assert not (task.get('result') or {}).get('result_unknown')


def test_dispatch_marker_does_not_leak_between_tasks(runner, monkeypatch):
    runner_worker, calls, install_post = runner
    install_post(lambda: _Response(json_error=ValueError('broken provider body')))
    first = _image_task('ark')
    assert _run_until_idle(runner_worker) == 1
    _assert_unknown(first)

    def broken_config(*_args, **_kwargs):
        raise RuntimeError('local config failure')
    monkeypatch.setattr(application, 'get_image_provider_config', broken_config)
    second = _image_task('ark')
    assert _run_until_idle(runner_worker) == 1
    assert not (task_db.get_task(second).get('result') or {}).get('result_unknown')


def test_cupsy_exception_keeps_original_retry_budget(runner, monkeypatch):
    runner_worker, calls, _install_post = runner
    attempts = []

    def crash(task_id):
        application.reset_provider_dispatch()
        attempts.append(task_id)
        raise RuntimeError('cupsy local crash')
    monkeypatch.setattr(application, 'execute_image_task', crash)
    task_id = _image_task('cupsy')

    assert _run_until_idle(runner_worker) == 3
    assert attempts == [task_id] * 3
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert not (task.get('result') or {}).get('result_unknown')


@pytest.mark.parametrize(('error', 'error_type', 'status'), [
    (requests.exceptions.ReadTimeout('provider still processing'), 'upstream_timeout', 504),
    (requests.exceptions.ConnectionError(
        "('Connection aborted.', TimeoutError('The write operation timed out'))"), 'upload_timeout', 504),
])
def test_video_submit_unknown_is_persisted_in_task_result(monkeypatch, error, error_type, status):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'upload_timeout_seconds': 135, 'request_timeout_seconds': 360,
    })
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {
        'api_key': 'shared-seedance-key', 'endpoint': 'https://provider.invalid',
        'model': 'seedance-20-endpoint', 'seedance_2_5_model': 'ep-test',
    })
    calls = []

    def fake_post(_url, **_kwargs):
        calls.append(_url)
        raise error
    monkeypatch.setattr(application.HTTP, 'post', fake_post)
    client = application.app.test_client()
    response = client.post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.5', 'prompt': 'A continuous cinematic shot',
        'ratio': 'adaptive', 'duration': 28, 'resolution': '480p',
        'output_format': 'mp4', 'video_mode': 'reference',
    })

    assert response.status_code == status
    payload = response.get_json()
    assert payload['result_unknown'] is True
    task_id = payload['db_task_id']
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['result'] == {'result_unknown': True, 'error_type': error_type}
    polled = client.get(f'/api/tasks/status?ids={task_id}').get_json()['tasks'][0]
    assert polled['result']['result_unknown'] is True
    assert len(calls) == 1
    assert task_db.claim_next_task('new-worker') is None
    assert client.post(f'/api/tasks/{task_id}/retry').status_code == 409


def test_video_connect_timeout_is_not_marked_unknown(monkeypatch):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {})
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {
        'api_key': 'shared-seedance-key', 'endpoint': 'https://provider.invalid',
        'model': 'seedance-20-endpoint', 'seedance_2_5_model': 'ep-test',
    })

    def fake_post(_url, **_kwargs):
        raise requests.exceptions.ConnectTimeout('not connected')
    monkeypatch.setattr(application.HTTP, 'post', fake_post)
    response = application.app.test_client().post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.5', 'prompt': 'shot', 'ratio': 'adaptive',
        'duration': 28, 'resolution': '480p', 'output_format': 'mp4', 'video_mode': 'reference',
    })
    assert response.status_code == 503
    task = task_db.get_task(response.get_json()['db_task_id'])
    assert task['status'] == 'failed'
    assert not (task.get('result') or {}).get('result_unknown')


# Ark request-error classification after the POST has been dispatched

def _raise(error):
    def behaviour():
        raise error
    return behaviour


_ABORTED = requests.exceptions.ConnectionError(
    "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))")
_DNS = requests.exceptions.ConnectionError(
    "HTTPSConnectionPool(host='p.invalid', port=443): Max retries exceeded "
    "(Caused by NameResolutionError(\"Failed to resolve 'p.invalid'\"))")
_REFUSED = requests.exceptions.ConnectionError(
    "HTTPSConnectionPool(host='p.invalid', port=443): Max retries exceeded (Caused by "
    "NewConnectionError('Failed to establish a new connection: [Errno 111] Connection refused'))")


@pytest.mark.parametrize(('provider', 'error', 'error_type'), [
    ('ark', requests.exceptions.ReadTimeout('provider still processing'), 'upstream_timeout'),
    ('ark', requests.exceptions.ConnectionError(
        "('Connection aborted.', TimeoutError('The write operation timed out'))"), 'upload_timeout'),
    ('ark', requests.exceptions.SSLError('EOF occurred in violation of protocol'), 'request_error_unknown'),
    ('ark', _ABORTED, 'request_error_unknown'),
    ('ark', RuntimeError('adapter crashed mid-request'), 'request_error_unknown'),
])
def test_dispatched_request_error_is_unknown_and_never_resubmitted(runner, provider, error, error_type):
    runner_worker, calls, install_post = runner
    install_post(_raise(error))
    task_id = _image_task(provider)

    assert _run_until_idle(runner_worker) == 1
    assert len(calls) == 1
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['result']['result_unknown'] is True
    assert task['result']['error_type'] == error_type
    assert '结果未知' in task['error']
    assert task_db.claim_next_task('another-worker') is None
    status = application.app.test_client().get(f'/api/tasks/status?ids={task_id}').get_json()
    assert status['tasks'][0]['result']['result_unknown'] is True


@pytest.mark.parametrize(('provider', 'error'), [
    ('ark', requests.exceptions.ConnectTimeout('connect timed out')),
    ('ark', _DNS),
    ('ark', _REFUSED),
])
def test_provably_unsent_request_error_is_not_unknown(runner, provider, error):
    runner_worker, calls, install_post = runner
    install_post(_raise(error))
    task_id = _image_task(provider)

    assert _run_until_idle(runner_worker) == 1
    assert len(calls) == 1
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['result']['result_unknown'] is False
    assert task['result']['error_type'] in {'request_error', 'connect_timeout'}


def test_process_image_never_reschedules_result_unknown_payload(runner, monkeypatch):
    runner_worker, _calls, _install_post = runner
    executions = []

    def unknown_without_fail(task_id):
        executions.append(task_id)
        return {'success': False, 'result_unknown': True, 'error': 'unknown'}, 502
    monkeypatch.setattr(application, 'execute_image_task', unknown_without_fail)
    task_id = _image_task('ark')

    assert _run_until_idle(runner_worker) == 1
    assert executions == [task_id]
    assert task_db.get_task(task_id)['status'] == 'processing'
    assert task_db.claim_next_task('another-worker') is None


# D1: errors caught inside _generate_ark_image during a layer POST

@pytest.mark.parametrize(('error', 'error_type'), [
    (RuntimeError('adapter crashed mid-request'), 'request_error_unknown'),
    (requests.exceptions.ConnectionError(
        "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"),
     'request_error_unknown'),
    (requests.exceptions.SSLError('EOF occurred in violation of protocol'), 'request_error_unknown'),
    (requests.exceptions.ReadTimeout('provider still processing'), 'upstream_timeout'),
    (requests.exceptions.ConnectionError(
        "('Connection aborted.', TimeoutError('The write operation timed out'))"), 'upload_timeout'),
])
def test_layer_post_error_is_persisted_as_unknown(runner, error, error_type):
    runner_worker, calls, install_post = runner
    install_post(_raise(error))
    task_id = _layer_task()
    task_db.update_task(task_id, result={'note': 'kept'})

    assert _run_until_idle(runner_worker) == 1
    assert len(calls) == 1
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['result']['result_unknown'] is True
    assert task['result']['error_type'] == error_type
    assert task['result']['note'] == 'kept'
    assert '结果未知' in task['error']
    assert task_db.claim_next_task('another-worker') is None
    client = application.app.test_client()
    assert client.get(f'/api/tasks/status?ids={task_id}').get_json()['tasks'][0]['result']['result_unknown'] is True
    summaries, _ = task_db.list_tasks(summary=True)
    assert next(t for t in summaries if t['id'] == task_id)['result']['result_unknown'] is True


@pytest.mark.parametrize(('error', 'error_type'), [
    (requests.exceptions.ConnectTimeout('connect timed out'), 'connect_timeout'),
    (_DNS, 'request_error'),
    (_REFUSED, 'request_error'),
])
def test_layer_provably_unsent_error_is_not_unknown(runner, error, error_type):
    runner_worker, calls, install_post = runner
    install_post(_raise(error))
    task_id = _layer_task()

    assert _run_until_idle(runner_worker) == 1
    assert len(calls) == 1
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['result']['result_unknown'] is False
    assert task['result']['error_type'] == error_type


# O1: non-timeout video submit request errors

def _video_submit(monkeypatch, error):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {})
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {
        'api_key': 'shared-seedance-key', 'endpoint': 'https://provider.invalid',
        'model': 'seedance-20-endpoint', 'seedance_2_5_model': 'ep-test',
    })
    calls = []

    def fake_post(url, **_kwargs):
        calls.append(url)
        raise error
    monkeypatch.setattr(application.HTTP, 'post', fake_post)
    response = application.app.test_client().post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.5', 'prompt': 'shot', 'ratio': 'adaptive',
        'duration': 28, 'resolution': '480p', 'output_format': 'mp4', 'video_mode': 'reference',
    })
    assert len(calls) == 1
    return response


@pytest.mark.parametrize('error', [
    _ABORTED, requests.exceptions.SSLError('EOF occurred in violation of protocol'),
])
def test_video_dispatched_request_error_is_unknown(monkeypatch, error):
    response = _video_submit(monkeypatch, error)
    assert response.status_code == 502
    payload = response.get_json()
    assert payload['result_unknown'] is True
    assert payload['error_type'] == 'request_error_unknown'
    task_id = payload['db_task_id']
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['result'] == {'result_unknown': True, 'error_type': 'request_error_unknown'}
    polled = application.app.test_client().get(f'/api/tasks/status?ids={task_id}').get_json()
    assert polled['tasks'][0]['result']['result_unknown'] is True
    assert task_db.claim_next_task('new-worker') is None


@pytest.mark.parametrize('error', [_DNS, _REFUSED])
def test_video_provably_unsent_request_error_is_not_unknown(monkeypatch, error):
    response = _video_submit(monkeypatch, error)
    assert response.status_code == 502
    payload = response.get_json()
    assert payload['error_type'] == 'request_error'
    task = task_db.get_task(payload['db_task_id'])
    assert task['status'] == 'failed'
    assert not (task.get('result') or {}).get('result_unknown')


# O2: Ark image ConnectTimeout message matches actual behaviour

def test_ark_connect_timeout_message_does_not_promise_auto_retry(runner):
    runner_worker, calls, install_post = runner
    install_post(_raise(requests.exceptions.ConnectTimeout('connect timed out')))
    task_id = _image_task('ark')

    assert _run_until_idle(runner_worker) == 1
    assert len(calls) == 1
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert '自动重试' not in task['error']
    assert '尚未提交' in task['error']


# P3: non-requests exception inside / before the video POST

def test_video_non_requests_error_inside_post_is_unknown(monkeypatch):
    response = _video_submit(monkeypatch, RuntimeError('adapter crashed mid-request'))
    assert response.status_code == 502
    payload = response.get_json()
    assert payload['result_unknown'] is True
    assert payload['error_type'] == 'request_error_unknown'
    task_id = payload['db_task_id']
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['result'] == {'result_unknown': True, 'error_type': 'request_error_unknown'}
    assert '结果未知' in task['error']
    polled = application.app.test_client().get(f'/api/tasks/status?ids={task_id}').get_json()
    assert polled['tasks'][0]['result']['result_unknown'] is True
    assert task_db.claim_next_task('new-worker') is None


def test_video_error_before_post_is_not_unknown(monkeypatch):
    def broken_timeouts(*_args, **_kwargs):
        raise RuntimeError('local timeout config failure')
    monkeypatch.setattr(application, 'resolve_ark_timeouts', broken_timeouts)
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {})
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {
        'api_key': 'shared-seedance-key', 'endpoint': 'https://provider.invalid',
        'model': 'seedance-20-endpoint', 'seedance_2_5_model': 'ep-test',
    })
    calls = []
    monkeypatch.setattr(application.HTTP, 'post', lambda url, **_kwargs: calls.append(url))
    response = application.app.test_client().post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.5', 'prompt': 'shot', 'ratio': 'adaptive',
        'duration': 28, 'resolution': '480p', 'output_format': 'mp4', 'video_mode': 'reference',
    })
    assert response.status_code == 500
    assert calls == []
    tasks, _ = task_db.list_tasks(summary=True)
    video = [task for task in tasks if task['type'] == 'video']
    assert len(video) == 1
    task = task_db.get_task(video[0]['id'])
    assert task['status'] == 'failed'
    assert task['error'] == 'local timeout config failure'
    assert not (task.get('result') or {}).get('result_unknown')


# P3: provider accepted the video job but local recording failed

def _video_accept(monkeypatch, activate, on_post=None):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {})
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {
        'api_key': 'shared-seedance-key', 'endpoint': 'https://provider.invalid',
        'model': 'seedance-20-endpoint', 'seedance_2_5_model': 'ep-test',
    })
    calls, logs, error_logs = [], [], []

    def fake_post(url, **_kwargs):
        calls.append(url)
        if on_post:
            on_post()
        return _Response(payload={'id': 'cgt-accepted-123'})
    monkeypatch.setattr(application.HTTP, 'post', fake_post)
    monkeypatch.setattr(task_db, 'activate_video_task', activate)
    original_error = application.app.logger.error
    monkeypatch.setattr(application.app.logger, 'error',
                        lambda msg, *args, **kw: (logs.append(msg % args), original_error(msg, *args, **kw)))
    monkeypatch.setattr(application, 'save_error_log',
                        lambda kind, req, resp, msg=None: error_logs.append((kind, resp, msg)))
    response = application.app.test_client().post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.5', 'prompt': 'shot', 'ratio': 'adaptive',
        'duration': 28, 'resolution': '480p', 'output_format': 'mp4', 'video_mode': 'reference',
    })
    return response, calls, logs, error_logs


def test_video_post_accept_transient_error_keeps_job_pollable(monkeypatch):
    import sqlite3
    real_activate = task_db.activate_video_task
    attempts = []

    def flaky(task_id, external_id):
        attempts.append(external_id)
        if len(attempts) == 1:
            raise sqlite3.OperationalError('database is locked')
        return real_activate(task_id, external_id)

    response, calls, logs, error_logs = _video_accept(monkeypatch, flaky)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['task_id'] == 'cgt-accepted-123'
    assert len(calls) == 1 and len(attempts) == 2
    task = task_db.get_task(payload['db_task_id'])
    assert task['status'] == 'processing'
    assert task['external_task_id'] == 'cgt-accepted-123'
    assert any('cgt-accepted-123' in line for line in logs)
    assert error_logs and error_logs[0][1] == {'external_task_id': 'cgt-accepted-123'}
    claimed = task_db.claim_next_task('poller', task_types=('video',))
    assert claimed['id'] == payload['db_task_id']


def test_video_post_accept_persistent_error_fails_with_external_id_and_unknown(monkeypatch):
    import sqlite3

    def broken(_task_id, _external_id):
        raise sqlite3.OperationalError('database is locked')

    response, calls, logs, error_logs = _video_accept(monkeypatch, broken)
    assert response.status_code == 502
    payload = response.get_json()
    assert payload['result_unknown'] is True
    assert payload['error_type'] == 'post_accept_error'
    assert payload['external_task_id'] == 'cgt-accepted-123'
    assert len(calls) == 1
    task_id = payload['db_task_id']
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['external_task_id'] == 'cgt-accepted-123'
    assert task['result'] == {
        'result_unknown': True, 'error_type': 'post_accept_error', 'external_task_id': 'cgt-accepted-123',
    }
    assert 'Provider已受理（编号cgt-accepted-123）' in task['error'] and '勿重复提交' in task['error']
    polled = application.app.test_client().get(f'/api/tasks/status?ids={task_id}').get_json()
    assert polled['tasks'][0]['result']['result_unknown'] is True
    assert polled['tasks'][0]['external_task_id'] == 'cgt-accepted-123'
    assert task_db.claim_next_task('poller') is None
    assert any('cgt-accepted-123' in line for line in logs)


def test_video_post_accept_unwritable_database_still_logs_external_id(monkeypatch):
    import sqlite3

    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError('attempt to write a readonly database')

    def database_goes_readonly():
        # Every later write fails, after the provider has accepted the job.
        monkeypatch.setattr(task_db, 'update_task', broken)
        monkeypatch.setattr(task_db, 'fail_task_merging_result', broken)

    response, calls, logs, error_logs = _video_accept(monkeypatch, broken, on_post=database_goes_readonly)
    assert response.status_code == 502
    payload = response.get_json()
    assert payload['external_task_id'] == 'cgt-accepted-123'
    assert payload['result_unknown'] is True
    assert len(calls) == 1
    task_id = payload['db_task_id']
    assert any('cgt-accepted-123' in line and f'task_id={task_id}' in line for line in logs)
    assert any('external_id_not_saved' in line for line in logs)
    assert error_logs[0][1] == {'external_task_id': 'cgt-accepted-123'}
