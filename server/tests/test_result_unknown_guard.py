"""RELIABILITY-20261112: result_unknown visibility, retry confirmation and crash recovery."""

import pytest

import app as application
import storage
import tasks as task_db
import worker

DEAD_PID = 999999999


def _failed_task(provider='ark', result=None, error='Ark 超时，任务结果未知'):
    task_id = task_db.create_task(
        'image', 'guard', {'provider': provider, 'aspect_ratio': '1:1', 'resolution': '1K'},
        provider=provider, status='pending',
    )
    task_db.update_task(task_id, output_dir=storage.task_output_dir('image', task_id))
    claimed = task_db.claim_next_task('worker-a')
    assert claimed['id'] == task_id
    task_db.fail_task(task_id, error, result)
    return task_id


def _summary(task_id):
    summaries, _ = task_db.list_tasks(summary=True)
    return next(task for task in summaries if task['id'] == task_id)


# ① preview / status / detail expose result_unknown

def test_result_unknown_is_visible_in_summary_status_and_detail():
    unknown_id = _failed_task(result={'error_type': 'upstream_timeout', 'result_unknown': True})
    plain_id = _failed_task(result={'error_type': 'request_error', 'result_unknown': False},
                            error='普通失败')
    legacy_id = _failed_task(result={'error_type': 'request_error'}, error='旧失败')
    client = application.app.test_client()

    assert _summary(unknown_id)['result']['result_unknown'] is True
    assert _summary(plain_id)['result']['result_unknown'] is False
    assert _summary(legacy_id)['result']['result_unknown'] is False

    statuses = {item['id']: item for item in task_db.get_task_statuses([unknown_id, plain_id, legacy_id])}
    assert statuses[unknown_id]['result']['result_unknown'] is True
    assert statuses[plain_id]['result']['result_unknown'] is False
    assert statuses[legacy_id]['result']['result_unknown'] is False

    response = client.get(f'/api/tasks/status?ids={unknown_id},{plain_id}')
    assert response.status_code == 200
    body = response.get_json()
    items = body.get('tasks') if isinstance(body, dict) else body
    by_id = {item['id']: item for item in items}
    assert by_id[unknown_id]['result']['result_unknown'] is True
    assert by_id[plain_id]['result']['result_unknown'] is False

    listing = client.get('/api/tasks').get_json()
    listed = {item['id']: item for item in listing['tasks']}
    assert listed[unknown_id]['result']['result_unknown'] is True

    detail = client.get(f'/api/tasks/{unknown_id}').get_json()
    detail_task = detail.get('task', detail)
    assert detail_task['result']['result_unknown'] is True


# ② retry requires explicit duplicate-billing confirmation

def test_retry_of_result_unknown_task_requires_confirmation():
    task_id = _failed_task(result={'error_type': 'upstream_timeout', 'result_unknown': True})
    client = application.app.test_client()
    before = len(task_db.list_tasks()[0])

    for kwargs in ({}, {'json': {}}, {'json': {'confirm_duplicate_billing': False}},
                   {'json': {'confirm_duplicate_billing': 'true'}}):
        response = client.post(f'/api/tasks/{task_id}/retry', **kwargs)
        assert response.status_code == 409
        payload = response.get_json()
        assert payload['success'] is False
        assert payload['code'] == 'result_unknown_confirm_required'
        assert 'Provider' in payload['error']
    assert len(task_db.list_tasks()[0]) == before

    confirmed = client.post(f'/api/tasks/{task_id}/retry', json={'confirm_duplicate_billing': True})
    assert confirmed.status_code == 202
    retry_id = confirmed.get_json()['task_id']
    retried = task_db.get_task(retry_id)
    assert retried['status'] == 'pending'
    assert retried['retry_of'] == task_id


def test_retry_of_ordinary_failure_is_unchanged():
    task_id = _failed_task(result={'error_type': 'request_error', 'result_unknown': False}, error='普通失败')
    legacy_id = _failed_task(error='无结果的旧失败')
    client = application.app.test_client()

    for source in (task_id, legacy_id):
        response = client.post(f'/api/tasks/{source}/retry')
        assert response.status_code == 202
        assert task_db.get_task(response.get_json()['task_id'])['retry_of'] == source


# ③ dead-worker recovery keeps the billing boundary

@pytest.fixture
def provider_calls(monkeypatch):
    calls = []

    def fake_execute_image(task_id):
        calls.append(('image', task_id))
        return {'success': False, 'error': 'mock provider must not be called again'}, 500

    def fake_execute_layer(task_id):
        calls.append(('layer', task_id))
        return {'success': False, 'error': 'mock provider must not be called again'}, 500

    monkeypatch.setattr(application, 'execute_image_task', fake_execute_image)
    monkeypatch.setattr(application, 'execute_layer_task', fake_execute_layer)
    monkeypatch.setattr(worker.application, 'config', {'server': {}})
    return calls


def _drain(new_worker):
    claimed = []
    while True:
        task = task_db.claim_next_task(new_worker.worker_id, task_types=('image', 'layer'))
        if task is None:
            return claimed
        claimed.append(task['id'])
        new_worker.process(task)
        if len(claimed) > 10:
            raise AssertionError('task claimed repeatedly')


@pytest.mark.parametrize(('task_type', 'provider'), [
    ('image', 'ark'), ('layer', 'ark'),
])
def test_dead_worker_marks_non_idempotent_generation_result_unknown(provider_calls, task_type, provider):
    task_db.upsert_worker_heartbeat('dead-worker', DEAD_PID, task_db.utcnow())
    task_id = task_db.create_task(task_type, 'crash', {'provider': provider}, provider=provider)
    claimed = task_db.claim_next_task('dead-worker')
    assert claimed['id'] == task_id
    # The dead worker had already sent its single provider request before exiting.
    provider_calls.append((task_type, task_id))

    assert task_db.recover_dead_worker_leases() == 1
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['error'] == task_db.WORKER_LOST_ERROR
    assert task['result']['result_unknown'] is True
    assert task['result']['error_type'] == 'worker_lost'
    assert task['completed_at'] is not None
    assert task['lease_owner'] is None and task['next_run_at'] is None
    assert task_db.latest_worker_heartbeat() is None

    assert _drain(worker.Worker()) == []
    assert provider_calls == [(task_type, task_id)]
    assert _summary(task_id)['result']['result_unknown'] is True


def test_dead_worker_recovery_preserves_existing_result_fields(provider_calls):
    task_db.upsert_worker_heartbeat('dead-worker', DEAD_PID, task_db.utcnow())
    task_id = task_db.create_task('image', 'crash', {}, provider='ark')
    task_db.update_task(task_id, result={'note': 'kept'})
    task_db.claim_next_task('dead-worker')

    task_db.recover_dead_worker_leases()
    result = task_db.get_task(task_id)['result']
    assert result == {'note': 'kept', 'result_unknown': True, 'error_type': 'worker_lost'}


def test_dead_worker_cupsy_image_is_requeued(provider_calls):
    task_db.upsert_worker_heartbeat('dead-worker', DEAD_PID, task_db.utcnow())
    task_id = task_db.create_task('image', 'crash', {'provider': 'cupsy'}, provider='cupsy')
    assert task_db.claim_next_task('dead-worker')['id'] == task_id

    assert task_db.recover_dead_worker_leases() == 1
    task = task_db.get_task(task_id)
    assert task['status'] == 'pending'
    assert task['error'] is None
    assert task['result'] is None
    assert task_db.claim_next_task('new-worker')['id'] == task_id


def test_dead_worker_cancel_requested_becomes_cancelled(provider_calls):
    task_db.upsert_worker_heartbeat('dead-worker', DEAD_PID, task_db.utcnow())
    task_id = task_db.create_task('image', 'crash', {}, provider='ark')
    task_db.claim_next_task('dead-worker')
    assert task_db.request_task_cancel(task_id) == 'cancel_requested'

    task_db.recover_dead_worker_leases()
    task = task_db.get_task(task_id)
    assert task['status'] == 'cancelled'
    assert not (task.get('result') or {}).get('result_unknown')


def test_dead_worker_video_polling_is_unchanged(provider_calls):
    task_db.upsert_worker_heartbeat('dead-worker', DEAD_PID, task_db.utcnow())
    task_id = task_db.create_task('video', 'crash', {}, provider='ark', external_task_id='ext-1')
    assert task_db.claim_next_task('dead-worker')['id'] == task_id

    task_db.recover_dead_worker_leases()
    task = task_db.get_task(task_id)
    assert task['status'] == 'processing'
    assert task['result'] is None
    assert task_db.claim_next_task('new-worker')['id'] == task_id


def test_graceful_release_does_not_mark_result_unknown(provider_calls):
    # SIGTERM path: Worker.run drains in-flight work, then releases its leases normally.
    stopping = worker.Worker()
    task_db.upsert_worker_heartbeat(stopping.worker_id, DEAD_PID, task_db.utcnow())
    ark_id = task_db.create_task('image', 'pending', {}, provider='ark')
    task_db.claim_next_task(stopping.worker_id)
    task_db.reschedule_task(ark_id, 0, status='pending')

    task_db.release_worker_leases(stopping.worker_id)
    task_db.remove_worker_heartbeat(stopping.worker_id)
    assert task_db.recover_dead_worker_leases() == 0

    task = task_db.get_task(ark_id)
    assert task['status'] == 'pending'
    assert not (task.get('result') or {}).get('result_unknown')
    assert task_db.claim_next_task('new-worker')['id'] == ark_id
