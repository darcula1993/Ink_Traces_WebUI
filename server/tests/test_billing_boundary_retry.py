"""Billing boundary: POST /api/tasks/<id>/retry requires explicit duplicate-billing confirmation."""

import json

import pytest

import app as application
import storage
import tasks as task_db
from billing_support import billing_env  # noqa: F401


def _failed(provider='ark', result=None, status='failed', task_type='image'):
    task_id = task_db.create_task(task_type, 'retry', {'provider': provider}, provider=provider,
                                  status='pending')
    task_db.update_task(task_id, output_dir=storage.task_output_dir(task_type, task_id))
    task_db.update_task(task_id, status=status, completed_at=task_db.utcnow(),
                        result=result if result is None or isinstance(result, str) else json.dumps(result))
    return task_id


def _count():
    return len(task_db.list_tasks(limit=100)[0])


UNKNOWN = {'result_unknown': True, 'error_type': 'upstream_timeout'}

REJECTED_BODIES = [
    ('no_body', {}),
    ('empty_json', {'json': {}}),
    ('invalid_json', {'data': '{not json', 'content_type': 'application/json'}),
    ('form', {'data': {'confirm_duplicate_billing': 'true'}}),
    ('json_array', {'json': [True]}),
    ('json_string', {'json': 'true'}),
    ('json_number', {'json': 1}),
    ('json_null', {'data': 'null', 'content_type': 'application/json'}),
    ('false', {'json': {'confirm_duplicate_billing': False}}),
    ('string_true', {'json': {'confirm_duplicate_billing': 'true'}}),
    ('one', {'json': {'confirm_duplicate_billing': 1}}),
    ('null', {'json': {'confirm_duplicate_billing': None}}),
    ('wrong_key', {'json': {'confirm': True}}),
]


@pytest.mark.parametrize('error_type', ['upstream_timeout', 'worker_lost', 'worker_exception',
                                        'request_error_unknown'])
@pytest.mark.parametrize(('case', 'kwargs'), REJECTED_BODIES, ids=[case for case, _ in REJECTED_BODIES])
def test_unknown_retry_without_explicit_true_is_409(billing_env, error_type, case, kwargs):
    task_id = _failed(result={'result_unknown': True, 'error_type': error_type})
    before = _count()
    response = application.app.test_client().post(f'/api/tasks/{task_id}/retry', **kwargs)
    assert response.status_code == 409
    payload = response.get_json()
    assert payload['success'] is False
    assert payload['code'] == 'result_unknown_confirm_required'
    assert 'Provider' in payload['error']
    assert _count() == before


@pytest.mark.parametrize('status', ['failed', 'cancelled'])
def test_unknown_retry_with_confirmation_is_accepted(billing_env, status):
    task_id = _failed(result=UNKNOWN, status=status)
    response = application.app.test_client().post(
        f'/api/tasks/{task_id}/retry', json={'confirm_duplicate_billing': True})
    assert response.status_code == 202
    retried = task_db.get_task(response.get_json()['task_id'])
    assert retried['retry_of'] == task_id and retried['status'] == 'pending'
    assert not (retried.get('result') or {}).get('result_unknown')


def test_cancelled_unknown_task_is_also_guarded(billing_env):
    task_id = _failed(result=UNKNOWN, status='cancelled')
    response = application.app.test_client().post(f'/api/tasks/{task_id}/retry')
    assert response.status_code == 409
    assert response.get_json()['code'] == 'result_unknown_confirm_required'


@pytest.mark.parametrize(('case', 'result'), [
    ('known_failure', {'error_type': 'request_error', 'result_unknown': False}),
    ('legacy_no_result', None),
    ('legacy_no_flag', {'error_type': 'api_error'}),
    ('legacy_invalid_json', 'not json'),
])
def test_ordinary_failure_retry_is_unchanged(billing_env, case, result):
    task_id = _failed(result=result)
    response = application.app.test_client().post(f'/api/tasks/{task_id}/retry')
    assert response.status_code == 202
    assert task_db.get_task(response.get_json()['task_id'])['retry_of'] == task_id


def test_trashed_unknown_task_reports_trash_first(billing_env):
    task_id = _failed(result=UNKNOWN)
    task_db.move_tasks_to_trash([task_id])
    before = _count()
    response = application.app.test_client().post(
        f'/api/tasks/{task_id}/retry', json={'confirm_duplicate_billing': True})
    assert response.status_code == 409
    assert '回收站' in response.get_json()['error']
    assert _count() == before


def test_deleted_task_retry_is_404(billing_env):
    task_id = _failed(result=UNKNOWN)
    task_db.delete_task(task_id)
    assert application.app.test_client().post(f'/api/tasks/{task_id}/retry').status_code == 404


@pytest.mark.parametrize('task_type', ['video', 'layer'])
def test_non_image_unknown_tasks_are_never_retryable(billing_env, task_type):
    task_id = _failed(result=UNKNOWN, task_type=task_type)
    client = application.app.test_client()
    for kwargs in ({}, {'json': {'confirm_duplicate_billing': True}}):
        assert client.post(f'/api/tasks/{task_id}/retry', **kwargs).status_code == 409


@pytest.mark.parametrize(('stored', 'expected'), [
    (None, None), ('not json', None), ('[1, 2]', False), ('"str"', False),
    ('{"result_unknown": null}', False), ('{"result_unknown": 0}', False),
    ('{"result_unknown": false}', False), ('{"result_unknown": 1}', True),
    ('{"result_unknown": true}', True),
])
def test_preview_flag_is_boolean_for_any_stored_result(billing_env, stored, expected):
    task_id = _failed(result=stored)
    client = application.app.test_client()
    status = client.get(f'/api/tasks/status?ids={task_id}').get_json()['tasks'][0]['result']
    listed = next(t for t in client.get('/api/tasks').get_json()['tasks'] if t['id'] == task_id)['result']
    for preview in (status, listed):
        if expected is None:
            assert preview is None
        else:
            assert preview['result_unknown'] is expected


@pytest.mark.parametrize('status', ['failed', 'cancelled'])
@pytest.mark.parametrize('result', [None, UNKNOWN])
def test_unknown_provider_task_retry_is_400_and_creates_nothing(billing_env, status, result):
    task_id = _failed('acme', result=result, status=status)
    before = _count()
    for kwargs in ({}, {'json': {'confirm_duplicate_billing': True}}):
        response = application.app.test_client().post(f'/api/tasks/{task_id}/retry', **kwargs)
        assert response.status_code == 400
        payload = response.get_json()
        assert payload['code'] == 'provider_unsupported'
        assert payload['error'] == application.UNSUPPORTED_RETRY_ERROR
    assert _count() == before
    assert task_db.get_task(task_id)['status'] == status
