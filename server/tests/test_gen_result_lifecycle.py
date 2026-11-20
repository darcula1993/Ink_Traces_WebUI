"""GEN-RESULT-LIFECYCLE-20261119: generation tasks and their 生成历史 results share one life cycle.

User decisions 2026-11-19: trash hides the results (restore brings them back); permanent
deletion / emptying the trash deletes them like a library deletion (placeholders, 410);
moving a result out of 生成历史 copies it; copies are independent of the task.
"""
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import app as application
import canvas_media_refs
import canvas_store as store
import gen_results
import media_library as media
import media_schema
import storage
import tasks
from test_canvas_library_folders import image_bytes
from test_library_global_s3 import generated, in_library
from test_local_delete import doc_with_reference

GEN_IMAGE = media.system_folder_id('generated_image')


def client():
    return application.app.test_client()


def node_asset(media_id):
    return {k: v for k, v in media.public(media.get_media(media_id)).items() if k in ('id', 'url', 'name', 'kind', 'mime_type', 'size_bytes')}


def listed_ids(c, **params):
    return [i['id'] for i in c.get('/api/canvas/media', query_string={'limit': 200, **params}).json['items']]


def folder_count(c, folder_id):
    return next(f['media_count'] for f in c.get('/api/canvas/media/folders').json['folders'] if f['id'] == folder_id)


def copy_to(c, ids, folder_id):
    r = c.post('/api/canvas/media/move', json={'ids': ids, 'folder_id': folder_id})
    assert r.status_code == 200, r.json
    return r.json


# ------------------------------------------------------------------ 1. trash hides, restore returns

def test_trash_hides_results_everywhere_and_restore_brings_them_back():
    c = client()
    tid, path = generated()
    media_id, library_file = in_library(tid, path)
    url = f'/api/canvas/media/{media_id}'
    assert media_id in listed_ids(c) and folder_count(c, GEN_IMAGE) == 1
    assert c.delete(f'/api/tasks/{tid}').json['trashed']
    # Hidden: list (all / folder / search), select-all ids, folder count; rows and files untouched.
    assert media_id not in listed_ids(c) and media_id not in listed_ids(c, folder_id=GEN_IMAGE, q='image')
    assert media_id not in c.get('/api/canvas/media/ids').json['ids'] and folder_count(c, GEN_IMAGE) == 0
    for suffix in ('', '/info', '/thumbnail'):
        r = c.get(url + suffix)
        assert r.status_code == 409 and r.json['code'] == 'media_trashed', suffix
        assert r.json['media']['trashed'] is True and r.json['media']['source_task_id'] == tid
    assert c.patch(url, json={'name': 'x.png'}).json['code'] == 'media_trashed'
    lookup = c.post('/api/canvas/media/lookup', json={'refs': [media_id]}).json['items'][0]
    assert lookup['status'] == 'trashed' and lookup['media']['name'] == 'image_0.png'
    assert library_file.exists() and media.status(media_id, reveal_trashed=True)[0] == 'ok'
    # The task center trash view still shows the task's own result.
    assert c.get(f'/api/tasks/{tid}/file/image_0.png').status_code == 200
    card = c.get('/api/tasks', query_string={'deleted': 1}).json['tasks'][0]
    assert card['result']['media'][0]['status'] == 'ok' and card['result']['result_deleted'] is False
    # Copy / move of a hidden item is refused.
    assert c.post('/api/canvas/media/move', json={'ids': [media_id], 'folder_id': None}).json['code'] == 'media_trashed'
    # Restore: everything is back, unchanged.
    assert c.post(f'/api/tasks/{tid}/restore').json['success']
    assert media_id in listed_ids(c) and folder_count(c, GEN_IMAGE) == 1
    assert c.get(url).data == image_bytes('blue')
    assert c.post('/api/canvas/media/lookup', json={'refs': [media_id]}).json['items'][0]['status'] == 'ok'


def test_trashed_result_cannot_be_used_as_a_reference_until_restored():
    project = store.create_project('p')['id']
    workflow = store.create_workflow(project, 'w')['id']
    tid, path = generated(workflow_id=workflow)
    media_id, _ = in_library(tid, path)
    tasks.move_tasks_to_trash([tid])
    with pytest.raises(store.CanvasError) as error:
        canvas_media_refs.reference(workflow, media_id)
    assert error.value.status == 409 and '回收站' in str(error.value)
    tasks.restore_tasks([tid])
    assert canvas_media_refs.reference(workflow, media_id)[2] == 'image'


def test_copies_and_uploads_are_never_hidden():
    c = client()
    tid, path = generated()
    media_id, _ = in_library(tid, path)
    copy_id = copy_to(c, [media_id], None)['media'][0]['id']
    tasks.move_tasks_to_trash([tid])
    assert copy_id in listed_ids(c) and media_id not in listed_ids(c)
    assert c.get(f'/api/canvas/media/{copy_id}').data == image_bytes('blue')


def test_shared_result_hidden_only_when_every_linked_task_is_trashed():
    c = client()
    first, first_path = generated()
    media_id, library_file = in_library(first, first_path)
    second, second_path = generated()  # same bytes: dedup links the second task to the same item
    assert media.register_generated(second, second_path, 'image') == media_id
    tasks.move_tasks_to_trash([first])
    assert media_id in listed_ids(c)
    tasks.move_tasks_to_trash([second])
    assert media_id not in listed_ids(c)
    # Purging one linked task keeps the item (the other still owns it, hidden in the trash).
    assert c.delete(f'/api/tasks/{first}?permanent=1').json['media_deleted'] == 0
    assert library_file.exists() and media.status(media_id)[0] == 'trashed'
    tasks.restore_tasks([second])
    assert media_id in listed_ids(c)
    tasks.move_tasks_to_trash([second])
    assert c.delete(f'/api/tasks/{second}?permanent=1').json['media_deleted'] == 1
    assert not library_file.exists() and media.status(media_id)[0] == 'deleted'


def test_upload_matching_a_trashed_result_becomes_its_own_item():
    c = client()
    tid, path = generated()
    media_id, _ = in_library(tid, path)
    tasks.move_tasks_to_trash([tid])
    import io
    r = c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('blue')), 'mine.png')})
    assert r.status_code == 201 and r.json['deduplicated'] is False and r.json['media']['id'] != media_id
    upload_id = r.json['media']['id']
    assert c.post('/api/tasks/trash/empty', json={'type': 'image'}).json['media_deleted'] == 1
    assert c.get(f'/api/canvas/media/{upload_id}').data == image_bytes('blue')


# ------------------------------------------------------------------ 2. preview + permanent delete

def test_preview_lists_affected_canvases_groups_and_purge_leaves_placeholders():
    c = client()
    project = store.create_project('预览项目')['id']
    workflow = store.create_workflow(project, '画布A')['id']
    tid, path = generated(workflow_id=workflow)
    media_id, library_file = in_library(tid, path)
    doc_with_reference(workflow, node_asset(media_id))
    group = c.post('/api/canvas/media/groups', json={'title': '组', 'media_ids': [media_id]}).json['group']
    keep = c.post('/api/canvas/media/folders', json={'title': 'keep'}).json['folder']
    copy_id = copy_to(c, [media_id], keep['id'])['media'][0]['id']
    live = tasks.create_task('image', 'live', {}, status='succeeded')
    tasks.move_tasks_to_trash([tid])
    preview = c.post('/api/tasks/delete-preview', json={'ids': [tid, live, 999999]}).json
    assert preview['task_ids'] == [tid] and preview['skipped'] == {str(live): 'not_in_trash'} and preview['missing_ids'] == [999999]
    m = preview['media']
    assert m['count'] == 1 and m['items'][0]['id'] == media_id and m['kinds']['image'] == 1 and m['copies_kept'] == 1
    assert m['affected_workflows'] == [{'workflow_id': workflow, 'workflow_title': '画布A', 'project_id': project,
                                        'project_title': '预览项目', 'placeholder_nodes': 1, 'stripped_nodes': 1}]
    assert m['media_groups'] == [{'id': group['id'], 'title': '组'}] and m['characters'] == []
    # Preview is read only.
    assert tasks.get_task(tid) and library_file.exists()
    before = store.workflow(workflow)['revision']
    r = c.delete(f'/api/tasks/{tid}?permanent=1').json
    assert r['permanent'] and r['media_deleted'] == 1
    assert not library_file.exists() and c.get(f'/api/canvas/media/{media_id}').status_code == 410
    after = store.workflow(workflow)
    nodes = {n['id']: n for n in after['document']['nodes']}
    assert after['revision'] == before + 1 and nodes['src']['asset']['id'] == media_id
    assert nodes['gen']['referenceAssets'] == [] and nodes['gen']['referenceOrder'] == [] and nodes['gen']['referenceGroups'] == []
    assert c.get('/api/canvas/media/groups/' + group['id']).json['group']['deleted_count'] == 1
    # The copy is untouched.
    assert c.get(f'/api/canvas/media/{copy_id}').data == image_bytes('blue')


def test_preview_by_type_covers_the_whole_trash():
    c = client()
    ids = []
    for color in ('blue', 'green', 'red'):
        tid, path = generated(color)
        in_library(tid, path)
        ids.append(tid)
    tasks.move_tasks_to_trash(ids[:2])
    preview = c.post('/api/tasks/delete-preview', json={'type': 'image'}).json
    assert sorted(preview['task_ids']) == ids[:2] and preview['media']['count'] == 2
    assert c.post('/api/tasks/delete-preview', json={'type': 'unknown'}).status_code == 400
    assert c.post('/api/tasks/delete-preview', json={'ids': []}).status_code == 400


def test_deleting_a_copy_never_touches_the_task_or_original():
    c = client()
    tid, path = generated()
    media_id, library_file = in_library(tid, path)
    copy = copy_to(c, [media_id], None)['media'][0]
    preview = c.post('/api/canvas/media/delete-preview', json={'ids': [copy['id']]}).json
    assert preview['task_ids'] == []  # the task card shows the original, not the copy
    assert c.post('/api/canvas/media/delete', json={'ids': [copy['id']]}).json['files_removed'] == 1
    assert library_file.exists() and media.get_media(media_id)['folder_id'] == GEN_IMAGE
    task = c.get(f'/api/tasks/{tid}').json['task']
    assert task['result']['result_deleted'] is False and task['result']['media'][0]['media_id'] == media_id


def test_copy_is_an_independent_hard_linked_item_and_uploads_still_move():
    c = client()
    tid, path = generated()
    media_id, library_file = in_library(tid, path)
    import io
    upload = c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('red')), 'u.png')}).json['media']
    folder = c.post('/api/canvas/media/folders', json={'title': '角色A'}).json['folder']
    r = copy_to(c, [media_id, upload['id']], folder['id'])
    copy, moved = r['media']
    assert r['copied'] == [{'source_id': media_id, 'id': copy['id']}]
    assert moved['id'] == upload['id'] and moved['folder_id'] == folder['id']
    assert copy['folder_id'] == folder['id'] and copy['name'] == 'image_0.png' and copy['origin'] == 'generated'
    copy_file = media.media_path(media.get_media(copy['id']))
    assert copy_file != library_file and os.stat(copy_file).st_ino == os.stat(library_file).st_ino
    assert media.get_media(media_id)['folder_id'] == GEN_IMAGE
    # Copying again creates another item; the same item never moves back into 生成历史.
    assert copy_to(c, [media_id], folder['id'])['media'][0]['id'] not in (media_id, copy['id'])
    assert c.post('/api/canvas/media/move', json={'ids': [copy['id']], 'folder_id': GEN_IMAGE}).json['code'] == 'folder_generated_only'
    # Deleting the task keeps the copies; the task card is unchanged otherwise.
    tasks.move_tasks_to_trash([tid])
    assert c.post('/api/tasks/bulk-delete', json={'ids': [tid], 'permanent': True}).json['media_deleted'] == 1
    assert copy_file.exists() and c.get(f'/api/canvas/media/{copy["id"]}').status_code == 200


# ------------------------------------------------------------------ 5. skip rules, other cleanups

def test_cancelling_and_leased_tasks_are_never_purged():
    c = client()
    tid, path = generated()
    media_id, library_file = in_library(tid, path)
    tasks.move_tasks_to_trash([tid])
    tasks.update_task(tid, lease_owner='w', lease_until='2999-01-01T00:00:00+00:00')
    r = c.delete(f'/api/tasks/{tid}?permanent=1')
    assert r.status_code == 409 and '执行中' in r.json['error']
    assert c.post('/api/tasks/bulk-delete', json={'ids': [tid], 'permanent': True}).json['skipped_ids'] == [tid]
    tasks.update_task(tid, status='cancel_requested')
    assert c.delete(f'/api/tasks/{tid}?permanent=1').status_code == 409
    assert library_file.exists() and tasks.get_task(tid)


def test_expiry_orphans_and_canvas_deletion_do_not_delete_library_files():
    c = client()
    project = store.create_project('p')['id']
    workflow = store.create_workflow(project, 'w')['id']
    tid, path = generated(workflow_id=workflow)
    media_id, library_file = in_library(tid, path)
    from canvas_cleanup import record_task_reference
    with store.write_transaction():
        record_task_reference(workflow, tid)
    tasks.get_db().execute('UPDATE task_assets SET expires_at=?', ('2000-01-01T00:00:00+00:00',))
    tasks.get_db().commit()
    storage.cleanup_expired_assets()
    storage.cleanup_orphans(0)
    assert c.delete(f'/api/canvas/workflows/{workflow}', json={'cleanup_assets': True}).json['deleted']
    assert c.delete(f'/api/canvas/projects/{project}', json={'cleanup_assets': True}).json['deleted']
    assert library_file.exists() and media.status(media_id)[0] == 'ok'
    assert tasks.get_task(tid)['deleted_at'] is None


# ------------------------------------------------------------------ concurrency

def test_registration_after_permanent_delete_is_undone():
    tid, path = generated()
    task = tasks.get_task(tid)
    tasks.move_tasks_to_trash([tid])
    gen_results.purge([tid])
    assert tasks.get_task(tid) is None
    # The Worker's late registration (task row gone) creates nothing lasting.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes('blue'))
    with pytest.raises(media.MediaError):
        media.register_generated(task['id'], path, 'image')
    assert tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0] == 0
    assert not any(media.root().iterdir())


def test_registration_while_trashed_is_hidden_and_purged_by_source_task():
    c = client()
    tid, path = generated()
    tasks.move_tasks_to_trash([tid])
    media_id = media.register_generated(tid, path, 'image')
    assert media_id not in listed_ids(c)
    # Even without the task_assets link the source task owns it.
    tasks.get_db().execute('UPDATE task_assets SET media_id=NULL')
    tasks.get_db().commit()
    assert gen_results.purge([tid])['media_deleted_ids'] == [media_id]


def test_concurrent_purge_and_restore_are_serialized(tmp_path):
    ids = []
    for color in ('blue', 'green', 'red', 'white'):
        tid, path = generated(color)
        in_library(tid, path)
        ids.append(tid)
    tasks.move_tasks_to_trash(ids)
    db_path = tasks.get_db().execute('PRAGMA database_list').fetchone()[2]

    def purge():
        try:
            return set(gen_results.purge(ids)['deleted_ids'])
        finally:
            tasks.close_db()

    def restore():
        try:
            return set(tasks.restore_tasks(ids))
        finally:
            tasks.close_db()

    with ThreadPoolExecutor(2) as pool:
        purged, restored = pool.submit(purge), pool.submit(restore)
        purged, restored = purged.result(), restored.result()
    assert purged | restored == set(ids) and not purged & restored
    db = sqlite3.connect(db_path)
    live_media = db.execute('SELECT COUNT(*) FROM media').fetchone()[0]
    assert live_media == len(restored)  # every purged task took its result, every restored one kept it


def test_media_failure_rolls_back_task_deletion(monkeypatch):
    tid, path = generated()
    media_id, library_file = in_library(tid, path)
    tasks.move_tasks_to_trash([tid])

    def broken(document, workflow_id):
        raise store.CanvasError('boom', 500)

    project = store.create_project('p')['id']
    workflow = store.create_workflow(project, 'w')['id']
    doc_with_reference(workflow, node_asset_unsafe(media_id))
    monkeypatch.setattr(store, 'validate_document', broken)
    with pytest.raises(store.CanvasError):
        gen_results.purge([tid])
    assert tasks.get_task(tid) and library_file.exists() and media.status(media_id, reveal_trashed=True)[0] == 'ok'


def node_asset_unsafe(media_id):
    row = media.status(media_id, reveal_trashed=True)[1]
    return {k: v for k, v in media.public(row).items() if k in ('id', 'url', 'name', 'kind', 'mime_type', 'size_bytes')}


# ------------------------------------------------------------------ schema + point 2

def test_old_unique_sha256_schema_is_rebuilt_once_keeping_rows(tmp_path):
    db = sqlite3.connect(tmp_path / 'old.db')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE media_folders (id TEXT PRIMARY KEY, title TEXT NOT NULL, parent_id TEXT, system_key TEXT UNIQUE, icon TEXT NOT NULL DEFAULT "folder", created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
    db.execute('''CREATE TABLE media (id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, relpath TEXT NOT NULL UNIQUE,
        folder_id TEXT REFERENCES media_folders(id) ON DELETE RESTRICT, name TEXT NOT NULL, mime_type TEXT NOT NULL,
        kind TEXT NOT NULL, size_bytes INTEGER NOT NULL, origin TEXT NOT NULL, source_task_id INTEGER, created_at TEXT NOT NULL)''')
    db.execute("INSERT INTO media VALUES ('a'||hex(randomblob(15)),'s1','r1.png',NULL,'n','image/png','image',1,'upload',NULL,'t')")
    db.execute('CREATE TABLE task_assets (id INTEGER PRIMARY KEY, task_id INTEGER, path TEXT)')
    db.commit()
    media_schema.create(db, tasks._ensure_columns)
    media_schema.create(db, tasks._ensure_columns)  # idempotent
    assert db.execute('SELECT COUNT(*) FROM media').fetchone()[0] == 1
    db.execute("INSERT INTO media VALUES ('b','s1','r2.png',NULL,'n','image/png','image',1,'generated',NULL,'t')")
    assert db.execute("SELECT COUNT(*) FROM media WHERE sha256='s1'").fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO media VALUES ('c','s2','r2.png',NULL,'n','image/png','image',1,'upload',NULL,'t')")


def test_retry_clone_links_reference_images():
    source = tasks.create_task('image', 'p', {}, status='failed')
    directory = Path(storage.task_output_dir('image', source))
    ref = directory / 'ref_0.png'
    ref.write_bytes(image_bytes('blue'))
    tasks.register_asset(source, 'input_image', str(ref), 'image/png')
    target = tasks.create_task('image', 'p', {}, status='pending')
    target_dir, copied = storage.clone_image_inputs(source, target)
    assert copied == 1
    cloned = Path(target_dir) / 'ref_0.png'
    assert os.stat(cloned).st_ino == os.stat(ref).st_ino


def test_media_read_rechecks_tombstone_when_file_disappears_before_open(monkeypatch):
    import media_api

    task_id, output = generated()
    media_id, _ = in_library(task_id, output)
    original = media_api.send_file

    def delete_before_open(*args, **kwargs):
        tasks.move_tasks_to_trash([task_id])
        gen_results.purge([task_id])
        return original(*args, **kwargs)

    monkeypatch.setattr(media_api, 'send_file', delete_before_open)
    response = client().get(f'/api/canvas/media/{media_id}')
    assert response.status_code == 410
    assert response.json['code'] == 'media_deleted'


@pytest.mark.parametrize('committed', [False, True])
def test_interrupted_purge_recovers_on_app_start(isolated_backend, committed):
    import signal
    import subprocess
    import sys
    import textwrap

    task_id, output = generated()
    media_id, path = in_library(task_id, output)
    original = path.read_bytes()
    folder = media.create_folder({'title': '副本'})['id']
    copy_id = copy_to(client(), [media_id], folder)['copied'][0]['id']
    copy_path = media.media_path(media.get_media(copy_id))
    tasks.move_tasks_to_trash([task_id])
    env = {**os.environ, 'NANOBANANA_DB_PATH': tasks.DB_PATH,
           'NANOBANANA_CANVAS_ASSET_DIR': str(store.asset_root()),
           'INK_TRACES_SECRET_KEY': 'private-test'}
    code = textwrap.dedent('''
        import os, signal, sys
        import app, gen_results, media_library

        def stop():
            os.kill(os.getpid(), signal.SIGKILL)

        if sys.argv[2] == 'True':
            media_library.finish_delete = lambda staged: stop()
        else:
            rename = os.rename

            def stop_after_staging(path, pending):
                rename(path, pending)
                stop()

            media_library.os.rename = stop_after_staging
        gen_results.purge([int(sys.argv[1])])
    ''')
    server = Path(__file__).resolve().parents[1]
    crashed = subprocess.run([sys.executable, '-c', code, str(task_id), str(committed)], cwd=server,
                             env=env, capture_output=True, timeout=20)
    assert crashed.returncode == -signal.SIGKILL, crashed.stderr.decode()
    assert not path.exists()
    staged, = path.parent.glob(path.name + '.deleting-*')
    assert staged.read_bytes() == original
    unrelated = path.parent / ('a' * 32 + '.png.deleting-' + 'b' * 32)
    unrelated.write_bytes(b'unrelated')

    # API and Worker both import app on startup. Two initializers must agree.
    args = [sys.executable, '-c', 'import app']
    with subprocess.Popen(args, cwd=server, env=env, stderr=subprocess.PIPE) as peer:
        started = subprocess.run(args, cwd=server, env=env, capture_output=True, timeout=20)
        assert started.returncode == 0, started.stderr.decode()
        _, stderr = peer.communicate(timeout=20)
        assert peer.returncode == 0, stderr.decode()
    tasks.close_db()
    assert not staged.exists()
    assert unrelated.read_bytes() == b'unrelated'
    assert copy_path.read_bytes() == original
    if committed:
        assert not path.exists()
        assert tasks.get_task(task_id) is None
        assert client().get(f'/api/canvas/media/{media_id}').status_code == 410
    else:
        assert path.read_bytes() == original
        tasks.restore_tasks([task_id])
        response = client().get(f'/api/canvas/media/{media_id}')
        assert response.status_code == 200
        assert response.data == original
