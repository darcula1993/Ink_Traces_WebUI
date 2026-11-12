"""Regression checks for task mutations with malformed numeric identifiers."""
import pytest

import app as application
import tasks as task_db


@pytest.mark.parametrize('invalid_id', [1.9, 1.0, True])
def test_bulk_delete_rejects_ids_without_touching_other_tasks(invalid_id):
    task_id = task_db.create_task('image', 'keep this task', {})
    response = application.app.test_client().post('/api/tasks/bulk-delete', json={'ids': [invalid_id]})
    assert response.status_code == 400
    assert task_db.get_task(task_id)['deleted_at'] is None


@pytest.mark.parametrize('invalid_id', [1.9, 1.0, True])
def test_group_assignments_reject_non_integer_ids(invalid_id):
    task_id = task_db.create_task('image', 'keep groups', {})
    task_db.create_favorite_group('existing')
    client = application.app.test_client()
    for endpoint, method, payload in (
        (f'/api/tasks/{task_id}/favorite-groups', client.patch, {'group_ids': [invalid_id]}),
        ('/api/tasks/bulk-favorite-groups', client.post, {'ids': [task_id], 'group_ids': [invalid_id]}),
    ):
        assert method(endpoint, json=payload).status_code == 400
        assert task_db.get_task(task_id)['favorite_groups'] == []


def test_string_ids_remain_accepted():
    task_id = task_db.create_task('image', 'trash this task', {})
    response = application.app.test_client().post('/api/tasks/bulk-delete', json={'ids': [str(task_id)]})
    assert response.status_code == 200
    assert task_db.get_task(task_id)['deleted_at'] is not None
