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
