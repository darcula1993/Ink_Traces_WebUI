"""Billing boundary matrix for video submission (Ark) and Cupsy video/audio submission.

Time points: before POST, during POST, after the provider accepted (external ID known).
"""

import sqlite3

import pytest
import requests

import app as application
import tasks as task_db
import worker
from billing_support import (  # noqa: F401  (fixtures)
    ACCEPTED_ID, Response, assert_known_failure, assert_unknown, billing_env, maybe_sent_errors,
    nothing_claimable, only_video_task_id, poll_task, polled, posts, submit_video, unsent_errors,
)

SENT = maybe_sent_errors()
UNSENT = unsent_errors()


def _retry_blocked(task_id):
    client = application.app.test_client()
    assert client.post(f'/api/tasks/{task_id}/retry').status_code == 409
    assert client.post(f'/api/tasks/{task_id}/retry',
                       json={'confirm_duplicate_billing': True}).status_code == 409


# ---------------------------------------------------------------- before the POST

def test_video_failure_before_post_is_known(billing_env, posts, monkeypatch):
    posts.install(Response(payload={'id': ACCEPTED_ID}))

    def broken(*_args, **_kwargs):
        raise RuntimeError('local timeout config failure')
    monkeypatch.setattr(application, 'resolve_ark_timeouts', broken)

    response = submit_video()
    assert response.status_code == 500
    assert posts.count == 0
    task = assert_known_failure(only_video_task_id())
    assert task['error'] == 'local timeout config failure'
    assert nothing_claimable()


def test_video_validation_failure_creates_no_task(billing_env, posts):
    posts.install(Response(payload={'id': ACCEPTED_ID}))
    response = submit_video(prompt='', ratio='not-a-ratio')
    assert response.status_code == 400
    assert posts.count == 0
    tasks, _ = task_db.list_tasks(summary=True)
    assert [task for task in tasks if task['type'] == 'video'] == []


# ---------------------------------------------------------------- during the POST

_STATUS = {'upstream_timeout': 504, 'upload_timeout': 504, 'request_error_unknown': 502}


@pytest.mark.parametrize(('case', 'error', 'error_type'), SENT + [
    ('runtime', RuntimeError('adapter crashed mid-request'), 'request_error_unknown'),
    ('key_error', KeyError('boom'), 'request_error_unknown'),
], ids=[case for case, _, _ in SENT] + ['runtime', 'key_error'])
def test_video_possibly_sent_error_is_unknown(billing_env, posts, case, error, error_type):
    posts.install(error)
    response = submit_video()
    assert response.status_code == _STATUS[error_type]
    payload = response.get_json()
    assert payload['result_unknown'] is True
    assert payload['retryable'] is False
    assert payload['error_type'] == error_type
    assert posts.count == 1
    task = assert_unknown(payload['db_task_id'], error_type)
    assert task['result'] == {'result_unknown': True, 'error_type': error_type}
    assert nothing_claimable()
    _retry_blocked(payload['db_task_id'])


@pytest.mark.parametrize(('case', 'error'), UNSENT, ids=[case for case, _ in UNSENT])
def test_video_provably_unsent_error_is_known(billing_env, posts, case, error):
    posts.install(error)
    response = submit_video()
    assert response.status_code == (503 if case == 'connect_timeout' else 502)
    payload = response.get_json()
    assert not payload.get('result_unknown')
    assert posts.count == 1
    assert_known_failure(payload['db_task_id'])
    assert nothing_claimable()


# ---------------------------------------------------------------- after the provider accepted

def test_video_accept_normal_path_is_pollable(billing_env, posts):
    posts.install(Response(payload={'id': ACCEPTED_ID}))
    response = submit_video()
    assert response.status_code == 200
    task = task_db.get_task(response.get_json()['db_task_id'])
    assert task['status'] == 'processing' and task['external_task_id'] == ACCEPTED_ID
    assert list(billing_env.iterdir()) == []


@pytest.mark.parametrize('status_code', [400, 500])
def test_video_provider_rejection_is_known(billing_env, posts, status_code):
    posts.install(Response(payload={'message': 'rejected'}, status_code=status_code))
    response = submit_video()
    assert response.status_code == status_code
    assert posts.count == 1
    assert_known_failure(response.get_json()['db_task_id'])


def _capture_logs(monkeypatch):
    lines = []
    original = application.app.logger.error

    def record(message, *args, **kwargs):
        lines.append(message % args if args else message)
        return original(message, *args, **kwargs)
    monkeypatch.setattr(application.app.logger, 'error', record)
    return lines


def test_activation_transient_failure_retries_and_stays_pollable(billing_env, posts, monkeypatch):
    posts.install(Response(payload={'id': ACCEPTED_ID}))
    real = task_db.activate_video_task
    attempts = []

    def flaky(task_id, external_id):
        attempts.append(external_id)
        if len(attempts) == 1:
            raise sqlite3.OperationalError('database is locked')
        return real(task_id, external_id)
    monkeypatch.setattr(task_db, 'activate_video_task', flaky)
    logs = _capture_logs(monkeypatch)

    response = submit_video()
    assert response.status_code == 200
    task_id = response.get_json()['db_task_id']
    assert posts.count == 1 and len(attempts) == 2
    task = task_db.get_task(task_id)
    assert task['status'] == 'processing' and task['external_task_id'] == ACCEPTED_ID
    assert any(ACCEPTED_ID in line for line in logs)
    assert any(ACCEPTED_ID in path.read_text(encoding='utf-8') for path in billing_env.iterdir())
    assert task_db.claim_next_task('poller', task_types=('video',))['id'] == task_id


def test_activation_persistent_failure_keeps_external_id_and_unknown(billing_env, posts, monkeypatch):
    posts.install(Response(payload={'id': ACCEPTED_ID}))

    def broken(*_args):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(task_db, 'activate_video_task', broken)

    response = submit_video()
    assert response.status_code == 502
    payload = response.get_json()
    assert payload['result_unknown'] is True and payload['external_task_id'] == ACCEPTED_ID
    assert posts.count == 1
    task = assert_unknown(payload['db_task_id'], 'post_accept_error', phrase='勿重复提交')
    assert task['external_task_id'] == ACCEPTED_ID
    assert task['result']['external_task_id'] == ACCEPTED_ID
    assert f'Provider已受理（编号{ACCEPTED_ID}）' in task['error'] and '勿重复提交' in task['error']
    assert polled(payload['db_task_id'])['external_task_id'] == ACCEPTED_ID
    assert nothing_claimable()
    _retry_blocked(payload['db_task_id'])


def test_activation_with_unwritable_database_still_logs_external_id(billing_env, posts, monkeypatch):
    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError('attempt to write a readonly database')

    def accept(_url, _kwargs):
        monkeypatch.setattr(task_db, 'update_task', broken)
        monkeypatch.setattr(task_db, 'fail_task', broken)
        monkeypatch.setattr(task_db, 'fail_task_merging_result', broken)
        return Response(payload={'id': ACCEPTED_ID})
    posts.install(accept)
    monkeypatch.setattr(task_db, 'activate_video_task', broken)
    logs = _capture_logs(monkeypatch)

    response = submit_video()
    assert response.status_code == 502
    payload = response.get_json()
    assert payload['external_task_id'] == ACCEPTED_ID and payload['result_unknown'] is True
    assert posts.count == 1
    task_id = payload['db_task_id']
    assert any(ACCEPTED_ID in line and f'task_id={task_id}' in line for line in logs)
    assert any('external_id_not_saved' in line for line in logs)
    assert any('result_not_saved' in line for line in logs)
    assert any(ACCEPTED_ID in path.read_text(encoding='utf-8') for path in billing_env.iterdir())


def test_activation_with_unwritable_error_log_dir_keeps_id_in_app_log(billing_env, posts, monkeypatch, tmp_path):
    posts.install(Response(payload={'id': ACCEPTED_ID}))

    def broken(*_args):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(task_db, 'activate_video_task', broken)
    monkeypatch.setattr(application, 'ERROR_LOGS_DIR', str(tmp_path / 'missing' / 'dir'))
    logs = _capture_logs(monkeypatch)

    response = submit_video()
    assert response.status_code == 502
    assert any(ACCEPTED_ID in line for line in logs)
    assert posts.count == 1


def test_cancel_during_activation_failure_does_not_revive(billing_env, posts, monkeypatch):
    posts.install(Response(payload={'id': ACCEPTED_ID}))
    real = task_db.activate_video_task
    calls = []

    def cancel_then_fail(task_id, external_id):
        calls.append(task_id)
        if len(calls) == 1:
            assert task_db.request_task_cancel(task_id) in {'cancel_requested', 'cancelled'}
            raise sqlite3.OperationalError('database is locked')
        return real(task_id, external_id)
    monkeypatch.setattr(task_db, 'activate_video_task', cancel_then_fail)

    response = submit_video()
    assert response.status_code == 409
    assert posts.count == 1
    assert task_db.get_task(response.get_json()['db_task_id'])['status'] == 'cancelled'
    assert nothing_claimable()


# ---------------------------------------------------------------- Cupsy video / audio (idempotent)

@pytest.mark.parametrize(('task_type', 'key_prefix'), [('video', 'nanobanana-video-'), ('audio', 'nanobanana-audio-')])
@pytest.mark.parametrize(('case', 'error', 'error_type'), SENT[:3], ids=[case for case, _, _ in SENT[:3]])
def test_cupsy_submit_transport_error_replays_same_key(billing_env, posts, task_type, key_prefix, case, error, error_type):
    posts.install(error)
    task_id = poll_task(task_type, 'cupsy')
    runner = worker.Worker()

    for _ in range(3):
        task = task_db.claim_next_task(runner.worker_id, task_types=('video', 'audio'))
        assert task['id'] == task_id
        runner.process(task)
        task_db.update_task(task_id, next_run_at=None)
    assert posts.count == 3
    assert {call['headers'].get('Idempotency-Key') for call in posts.calls} == {f'{key_prefix}{task_id}'}
    task = task_db.get_task(task_id)
    assert task['status'] in {'pending', 'processing'}
    assert not (task.get('result') or {}).get('result_unknown')


@pytest.mark.parametrize(('task_type', 'provider', 'external_id', 'status'), [
    ('video', 'cupsy', None, 'pending'),
    ('audio', 'cupsy', None, 'pending'),
    ('video', 'ark', 'ext-1', 'processing'),
])
def test_polling_worker_exception_reschedules_without_unknown(
        billing_env, monkeypatch, task_type, provider, external_id, status):
    def crash(_task_id):
        raise RuntimeError('local crash')
    monkeypatch.setattr(application, 'poll_video_task_once', crash)
    monkeypatch.setattr(application, 'poll_audio_task_once', crash)
    task_id = poll_task(task_type, provider, external_task_id=external_id)
    runner = worker.Worker()

    runner.process(task_db.claim_next_task(runner.worker_id, task_types=('video', 'audio')))
    task = task_db.get_task(task_id)
    assert task['status'] == status
    assert not (task.get('result') or {}).get('result_unknown')


# ---------------------------------------------------------------- G1: no secret / signed-URL leakage

PROBE_KEY = 'probe-secret-KEY-9f3a71'
PROBE_SIG = 'probe-sig-55c2e0'


@pytest.fixture
def probe_secrets(billing_env, monkeypatch):
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {
        'api_key': PROBE_KEY,
        'endpoint': f'https://provider.invalid/signed?X-Signature={PROBE_SIG}&X-Expires=9',
        'model': 'seedance-20-endpoint', 'seedance_2_5_model': 'ep-test',
    })
    return billing_env


def _assert_no_secret(*texts):
    blob = '\n'.join(str(text) for text in texts)
    for needle in (PROBE_KEY, PROBE_SIG, 'X-Signature'):
        assert needle not in blob


@pytest.mark.parametrize('scenario', ['transient', 'persistent', 'unwritable', 'read_timeout', 'aborted'])
def test_no_secret_or_signed_url_in_logs_payload_or_task(probe_secrets, posts, monkeypatch, caplog, capsys, scenario):
    caplog.set_level('DEBUG')
    real = task_db.activate_video_task
    attempts = []

    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError('database is locked')

    def flaky(task_id, external_id):
        attempts.append(task_id)
        if len(attempts) == 1:
            raise sqlite3.OperationalError('database is locked')
        return real(task_id, external_id)

    def accept_then_readonly(_url, _kwargs):
        monkeypatch.setattr(task_db, 'update_task', broken)
        monkeypatch.setattr(task_db, 'fail_task_merging_result', broken)
        return Response(payload={'id': ACCEPTED_ID})

    if scenario == 'read_timeout':
        posts.install(requests.exceptions.ReadTimeout('read timed out'))
    elif scenario == 'aborted':
        posts.install(SENT[2][1])
    elif scenario == 'unwritable':
        posts.install(accept_then_readonly)
        monkeypatch.setattr(task_db, 'activate_video_task', broken)
    else:
        posts.install(Response(payload={'id': ACCEPTED_ID}))
        monkeypatch.setattr(task_db, 'activate_video_task', flaky if scenario == 'transient' else broken)

    response = submit_video()
    assert posts.count == 1
    payload = response.get_json()
    task = task_db.get_task(payload['db_task_id'])
    files = [path.read_text(encoding='utf-8') for path in probe_secrets.iterdir()]
    if scenario != 'transient':
        assert files, 'an error log was expected'
    if scenario in {'transient', 'persistent', 'unwritable'}:
        # Prove the capture actually sees the app logger lines being checked.
        assert 'video_post_accept_error' in caplog.text and ACCEPTED_ID in caplog.text
    captured = capsys.readouterr()
    _assert_no_secret(response.get_data(as_text=True), task.get('error'), task.get('result'),
                      caplog.text, captured.out, captured.err, *files)


# ---------------------------------------------------------------- G5 / G6: cancellation and duplicate IDs

def test_cancel_then_persistent_activation_failure_stays_cancelled(billing_env, posts, monkeypatch):
    posts.install(Response(payload={'id': ACCEPTED_ID}))
    calls = []

    def cancel_then_always_fail(task_id, _external_id):
        calls.append(task_id)
        if len(calls) == 1:
            assert task_db.request_task_cancel(task_id) in {'cancel_requested', 'cancelled'}
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(task_db, 'activate_video_task', cancel_then_always_fail)

    response = submit_video()
    assert response.status_code == 502
    assert posts.count == 1 and len(calls) == 2
    task = task_db.get_task(response.get_json()['db_task_id'])
    assert task['status'] == 'cancelled'
    assert task['external_task_id'] == ACCEPTED_ID
    assert nothing_claimable()


def test_duplicate_external_id_is_unknown_with_id_in_result(billing_env, posts):
    posts.install(Response(payload={'id': ACCEPTED_ID}))
    first = submit_video()
    assert first.status_code == 200

    second = submit_video()
    assert second.status_code == 502
    assert posts.count == 2
    payload = second.get_json()
    assert payload['external_task_id'] == ACCEPTED_ID and payload['result_unknown'] is True
    task = assert_unknown(payload['db_task_id'], 'post_accept_error', phrase='勿重复提交')
    assert task['result']['external_task_id'] == ACCEPTED_ID
    assert task['external_task_id'] is None  # UNIQUE(provider, external_task_id) kept the first owner
    assert task_db.get_task(first.get_json()['db_task_id'])['status'] == 'processing'
