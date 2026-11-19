"""EMPTY-TRASH-20261118: one-click empty trash per task type."""
from pathlib import Path

import pytest

import app as application
import media_library as media
import storage
import tasks
from test_library_global_s3 import generated, in_library, image_bytes


def client():
    return application.app.test_client()


def empty(task_type):
    return client().post('/api/tasks/trash/empty', json={'type': task_type})


def trashed(task_type, **fields):
    tid = tasks.create_task(task_type, f'{task_type} prompt', {}, status='succeeded')
    tasks.move_tasks_to_trash([tid])
    if fields:
        tasks.update_task(tid, **fields)
    return tid


@pytest.mark.parametrize('body', [None, {}, {'type': ''}, {'type': 'layer'}, {'type': 'IMAGE'}, {'type': ['image']}, ['image']])
def test_type_is_required_and_validated(body):
    tid = trashed('image')
    r = client().post('/api/tasks/trash/empty', json=body) if body is not None else client().post('/api/tasks/trash/empty')
    assert r.status_code == 400 and r.json['success'] is False
    assert tasks.get_task(tid) is not None


@pytest.mark.parametrize('task_type', ['image', 'video', 'audio'])
def test_empty_trash_returns_zero(task_type):
    live = tasks.create_task(task_type, 'live', {}, status='succeeded')
    r = empty(task_type)
    assert r.status_code == 200
    assert r.json == {'success': True, 'type': task_type, 'deleted': 0, 'deleted_ids': [], 'skipped': 0,
                      'skipped_ids': [], 'skipped_reasons': {'cancel_requested': 0, 'leased': 0, 'not_in_trash': 0},
                      'media_deleted': 0}
    assert tasks.get_task(live) is not None


def test_types_are_isolated_and_live_tasks_untouched():
    ids = {t: [trashed(t), trashed(t)] for t in ('image', 'video', 'audio')}
    live = {t: tasks.create_task(t, 'live', {}, status='succeeded') for t in ('image', 'video', 'audio')}
    r = empty('video').json
    assert r['deleted'] == 2 and sorted(r['deleted_ids']) == sorted(ids['video'])
    assert all(tasks.get_task(i) is None for i in ids['video'])
    assert all(tasks.get_task(i) is not None for t in ('image', 'audio') for i in ids[t])
    assert all(tasks.get_task(i)['deleted_at'] is None for i in live.values())
    assert empty('image').json['deleted'] == 2 and empty('audio').json['deleted'] == 2
    assert all(tasks.get_task(i) is not None for i in live.values())


def test_skips_cancel_requested_and_leased_tasks():
    ok = trashed('image')
    cancelling = trashed('image', status='cancel_requested', lease_owner='worker-1', lease_until='2999-01-01T00:00:00+00:00')
    leased = trashed('image', lease_owner='worker-2', lease_until='2999-01-01T00:00:00+00:00')
    r = empty('image').json
    assert r['deleted_ids'] == [ok] and r['skipped'] == 2
    assert sorted(r['skipped_ids']) == sorted([cancelling, leased])
    assert r['skipped_reasons'] == {'cancel_requested': 1, 'leased': 1, 'not_in_trash': 0}
    assert tasks.get_task(cancelling) and tasks.get_task(leased)


def test_concurrent_restore_between_listing_and_purge_is_skipped(monkeypatch):
    first, second = trashed('image'), trashed('image')
    import gen_results
    original = gen_results.purge

    def restore_then_purge(task_ids, task_type=None):
        tasks.restore_tasks([second])  # a restore commits before the purge transaction starts
        return original(task_ids, task_type)

    monkeypatch.setattr(gen_results, 'purge', restore_then_purge)
    r = empty('image').json
    assert r['deleted_ids'] == [first] and r['skipped_ids'] == [second]
    assert r['skipped_reasons']['not_in_trash'] == 1
    assert tasks.get_task(second)['deleted_at'] is None


def test_batches_cover_more_than_one_page(monkeypatch):
    monkeypatch.setattr(tasks, 'TRASH_PURGE_BATCH', 3)
    ids = [trashed('audio') for _ in range(7)]
    blocked = trashed('audio', status='cancel_requested')
    r = empty('audio').json
    assert sorted(r['deleted_ids']) == ids and r['skipped_ids'] == [blocked]
    assert tasks.list_trashed_task_ids('audio') == [blocked]


def test_generated_history_results_go_with_the_tasks_and_task_files_are_removed():
    """GEN-RESULT-LIFECYCLE-20261119: emptying the trash deletes the tasks' 生成历史 results."""
    tid, path = generated()
    media_id, library_file = in_library(tid, path)
    plain, plain_path = generated('green')
    tasks.move_tasks_to_trash([tid, plain])
    r = empty('image').json
    assert sorted(r['deleted_ids']) == sorted([tid, plain]) and r['media_deleted'] == 1
    assert not library_file.exists()
    gone = client().get(f'/api/canvas/media/{media_id}')
    assert gone.status_code == 410 and gone.json['code'] == 'media_deleted'
    assert not plain_path.exists() and not Path(storage.OUTPUT_DIR, 'image', str(plain)).exists()
    assert tasks.list_assets(plain) == [] and tasks.list_assets(tid) == []


def test_result_deleted_cards_keep_their_rule():
    c = client()
    # A live task whose library result was deleted keeps showing "结果已删除" after emptying trash.
    live, live_path = generated()
    live_media, _ = in_library(live, live_path)
    assert c.post('/api/canvas/media/delete', json={'ids': [live_media]}).json['deleted_ids'] == [live_media]
    # A trashed task whose library result was deleted is purged like any other.
    gone, gone_path = generated('green')
    gone_media, _ = in_library(gone, gone_path)
    assert c.post('/api/canvas/media/delete', json={'ids': [gone_media]}).json['deleted_ids'] == [gone_media]
    tasks.move_tasks_to_trash([gone])
    assert empty('image').json['deleted_ids'] == [gone]
    task = c.get(f'/api/tasks/{live}').json['task']
    assert task['result']['result_deleted'] is True
    r = c.get(f'/api/tasks/{live}/file/image_0.png')
    assert r.status_code == 410 and r.json['error'] == '结果已删除'
    # The deleted library item stays deleted (no revival through the purged task).
    assert c.get(f'/api/canvas/media/{gone_media}').status_code in (404, 410)


def test_empty_leaves_deleted_placeholders_on_canvas_and_groups():
    import canvas_store as store
    from test_local_delete import doc_with_reference

    c = client()
    project = store.create_project('retained references')['id']
    workflow = store.create_workflow(project, 'canvas')['id']
    tid, path = generated(workflow_id=workflow)
    media_id, library_file = in_library(tid, path)
    asset = {key: value for key, value in media.public(media.get_media(media_id)).items()
             if key in ('id', 'url', 'name', 'kind', 'mime_type', 'size_bytes')}
    saved = doc_with_reference(workflow, asset)
    group = c.post('/api/canvas/media/groups', json={'title': 'reference group', 'media_ids': [media_id]}).json['group']
    tasks.move_tasks_to_trash([tid])
    preview = c.post('/api/tasks/delete-preview', json={'type': 'image'}).json
    assert preview['task_ids'] == [tid] and preview['media']['count'] == 1
    assert [w['workflow_id'] for w in preview['media']['affected_workflows']] == [workflow]
    assert [g['id'] for g in preview['media']['media_groups']] == [group['id']]
    assert empty('image').json['deleted_ids'] == [tid]
    assert not library_file.exists()
    assert c.get(asset['url']).status_code == 410
    after = store.workflow(workflow)
    assert after['revision'] == saved['revision'] + 1
    nodes = {n['id']: n for n in after['document']['nodes']}
    assert nodes['src']['asset']['id'] == media_id  # placeholder kept in place
    assert nodes['gen']['referenceAssets'] == [] and nodes['gen']['referenceMentions'] == {}
    expanded = c.get('/api/canvas/media/groups/' + group['id']).json
    assert expanded['group']['media_ids'] == [media_id] and expanded['group']['deleted_count'] == 1
    assert [(item['media_id'], item['status']) for item in expanded['items']] == [(media_id, 'deleted')]
