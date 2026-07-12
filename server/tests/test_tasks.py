import base64

import maintenance
import tasks as task_db


def test_task_lease_is_atomic_and_reschedulable():
    task_id = task_db.create_task('image', 'prompt', {}, provider='ark', status='preparing')
    assert task_db.claim_next_task('worker-a') is None

    task_db.update_task(task_id, status='pending', next_run_at=task_db.utcnow())
    claimed = task_db.claim_next_task('worker-a')
    assert claimed['id'] == task_id
    assert claimed['status'] == 'processing'
    assert claimed['attempt_count'] == 1
    assert task_db.claim_next_task('worker-b') is None

    task_db.reschedule_task(task_id, 0, status='pending')
    claimed_again = task_db.claim_next_task('worker-b')
    assert claimed_again['id'] == task_id
    assert claimed_again['attempt_count'] == 2


def test_dead_worker_lease_is_recovered():
    task_db.upsert_worker_heartbeat('dead-worker', 999999999, task_db.utcnow())
    task_id = task_db.create_task('image', 'prompt', {})
    assert task_db.claim_next_task('dead-worker')['id'] == task_id

    assert task_db.recover_dead_worker_leases() == 1
    assert task_db.claim_next_task('new-worker')['id'] == task_id


def test_compact_removes_legacy_base64_only():
    encoded = base64.b64encode(b'large-image').decode()
    task_id = task_db.create_task('image', 'prompt', {})
    task_db.update_task(
        task_id,
        result={
            'images': [f'data:image/png;base64,{encoded}'],
            'local_images': ['/api/tasks/1/file/image_0.png'],
            'thinking': 'ok',
        },
    )

    summaries, _ = task_db.list_tasks(summary=True)
    assert 'images' not in summaries[0]['result']
    assert summaries[0]['result']['local_images'] == ['/api/tasks/1/file/image_0.png']

    assert maintenance.compact_task_results() == 1
    result = task_db.get_task(task_id)['result']
    assert 'images' not in result
    assert result['local_images'] == ['/api/tasks/1/file/image_0.png']


def test_prompt_crud_uses_sqlite():
    prompt = task_db.create_prompt('first', prompt_id=123, created_at='2026-01-01T00:00:00+00:00')
    assert prompt['id'] == 123
    assert task_db.list_prompts()[0]['text'] == 'first'
    assert task_db.update_prompt(123, 'updated')
    assert task_db.list_prompts()[0]['text'] == 'updated'
    assert task_db.delete_prompt(123)
    assert task_db.list_prompts() == []


def test_task_favorite_is_persisted_and_filterable():
    first = task_db.create_task('image', 'first', {})
    task_db.create_task('image', 'second', {})

    assert task_db.set_task_favorite(first, True)
    assert task_db.get_task(first)['favorite'] is True
    favorites, total = task_db.list_tasks(favorite=True)
    assert total == 1
    assert [task['id'] for task in favorites] == [first]


def test_cancelled_task_cannot_be_completed_or_rescheduled():
    task_id = task_db.create_task('image', 'prompt', {})
    claimed = task_db.claim_next_task('worker-a')
    assert claimed['id'] == task_id

    assert task_db.request_task_cancel(task_id) == 'cancel_requested'
    assert task_db.complete_task(task_id, {'local_images': ['should-not-win']}) is False
    assert task_db.reschedule_task(task_id, 0, status='pending') is False
    assert task_db.fail_task(task_id, 'should-not-win') is False
    assert task_db.finalize_task_cancel(task_id) is True

    task = task_db.get_task(task_id)
    assert task['status'] == 'cancelled'
    assert task['result'] is None
    assert task['error'] is None


def test_pending_cancel_is_terminal_without_worker():
    task_id = task_db.create_task('image', 'prompt', {}, status='pending')
    assert task_db.request_task_cancel(task_id) == 'cancelled'
    task = task_db.get_task(task_id)
    assert task['status'] == 'cancelled'
    assert task['completed_at'] is not None
    assert task_db.claim_next_task('worker-a') is None


def test_task_filters_share_group_search_and_sort_semantics():
    first = task_db.create_task('image', 'alpha', {})
    second = task_db.create_task('image', 'beta', {})
    group = task_db.create_favorite_group('Portrait work', 'rose')
    task_db.replace_task_favorite_groups(first, [group['id']])
    task_db.set_task_favorite(second, True)

    searched, total = task_db.list_tasks(favorite=True, search='portrait')
    assert total == 1
    assert searched[0]['id'] == first
    assert task_db.list_task_ids(favorite=True, search='portrait') == [first]
    assert task_db.list_task_ids(sort='oldest') == [first, second]
    assert task_db.list_task_ids(sort='newest') == [second, first]


def test_full_text_search_tracks_provider_updates_and_deletes():
    task_id = task_db.create_task('image', 'neon city', {}, provider='ark')
    assert task_db.list_task_ids(search='neon') == [task_id]
    assert task_db.list_task_ids(search='ark') == [task_id]

    assert task_db.update_task(task_id, provider='vertex')
    assert task_db.list_task_ids(search='ark') == []
    assert task_db.list_task_ids(search='vertex') == [task_id]

    task_db.delete_task(task_id)
    assert task_db.list_task_ids(search='neon') == []
    assert task_db.list_task_ids(search='vertex') == []


def test_workspace_state_round_trip():
    stored = task_db.set_workspace_state('appMode', 'video')
    assert stored['value'] == 'video'
    assert stored['revision'] == 1

    updated = task_db.set_workspace_state('appMode', 'image')
    assert updated['value'] == 'image'
    assert updated['revision'] == 2
