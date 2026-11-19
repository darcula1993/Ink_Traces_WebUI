"""LIBRARY-GLOBAL-20261116 S3: task center reads library results; deletions never remove library files."""
import io
import json
import os
import zipfile
from pathlib import Path

import app as application
import canvas_cleanup as cleanup
import canvas_store as store
import media_library as media
import storage
import tasks
from test_canvas_library_folders import image_bytes
from test_local_delete import doc_with_reference

SIGNED = 'https://bucket.example/x.png?X-Tos-Signature=secret&X-Tos-Credential=cred'


def client():
    return application.app.test_client()


def generated(color='blue', workflow_id=None, thumbnail=True):
    params = {'canvas_workflow_id': workflow_id} if workflow_id else {}
    tid = tasks.create_task('image', 'prompt', params, status='succeeded')
    directory = Path(storage.OUTPUT_DIR) / 'image' / str(tid)
    directory.mkdir(parents=True)
    path = directory / 'image_0.png'
    path.write_bytes(image_bytes(color))
    tasks.register_asset(tid, 'output_image', str(path), 'image/png')
    result = {'local_images': [f'/api/tasks/{tid}/file/image_0.png'], 'images': [SIGNED], 'local_thumbnails': []}
    if thumbnail:
        thumb = directory / 'thumb_0.webp'
        storage.create_image_thumbnail(str(path), str(thumb))
        tasks.register_asset(tid, 'output_thumbnail', str(thumb), 'image/webp')
        result['local_thumbnails'] = [f'/api/tasks/{tid}/file/thumb_0.webp']
    tasks.update_task(tid, output_dir=str(directory), result=result)
    return tid, path


def in_library(tid, path):
    media_id = media.register_generated(tid, path, 'image')
    return media_id, media.media_path(media.get_media(media_id))


def test_task_center_reads_library_and_falls_back_to_output():
    c = client()
    tid, path = generated()
    media_id, library_file = in_library(tid, path)
    plain_tid, plain_path = generated('green')
    # Library-backed output keeps working even when the task-side link is gone.
    path.unlink()
    r = c.get(f'/api/tasks/{tid}/file/image_0.png')
    assert r.status_code == 200 and r.mimetype == 'image/png'
    assert c.get(f'/api/tasks/{tid}/download/image_0.png?raw=1').data == library_file.read_bytes()
    assert c.get(f'/api/tasks/{plain_tid}/file/image_0.png').status_code == 200
    detail = c.get(f'/api/tasks/{tid}').json['task']['result']
    folder = media.system_folder_id('generated_image')
    assert detail['media'] == [{'output_url': f'/api/tasks/{tid}/file/image_0.png', 'media_id': media_id, 'status': 'ok',
                                'kind': 'image', 'name': 'image_0.png', 'url': f'/api/canvas/media/{media_id}', 'folder_id': folder,
                                'thumbnail_url': f'/api/canvas/media/{media_id}/thumbnail'}]
    assert c.get(detail['media'][0]['url'] + '?download=1').data == library_file.read_bytes()
    assert detail['result_deleted'] is False and detail['deleted_outputs'] == 0
    plain = c.get(f'/api/tasks/{plain_tid}').json['task']['result']
    assert 'media' not in plain and 'result_deleted' not in plain
    listed = {t['id']: t['result'] for t in c.get('/api/tasks').json['tasks']}
    assert listed[tid]['media'][0]['status'] == 'ok' and 'media' not in listed[plain_tid]
    polled = c.get(f'/api/tasks/status?ids={tid}').json['tasks'][0]['result']
    assert polled['media'][0]['media_id'] == media_id
    # No signed Provider address reaches the browser.
    body = c.get(f'/api/tasks/{tid}').get_data(as_text=True)
    assert 'Signature' not in body and 'secret' not in body and 'cred' not in body
    bundle = c.post('/api/tasks/bulk-download', json={'ids': [tid, plain_tid], 'raw': True})
    with zipfile.ZipFile(io.BytesIO(bundle.data)) as archive:
        assert len(archive.namelist()) == 2


def test_deleted_library_result_keeps_task_card_and_shows_result_deleted():
    c = client()
    tid, path = generated()
    media_id, library_file = in_library(tid, path)
    assert c.post('/api/canvas/media/delete', json={'ids': [media_id]}).json['deleted_ids'] == [media_id]
    assert not library_file.exists() and path.exists()  # observation-period output link stays, but is not served
    for url in (f'/api/tasks/{tid}/file/image_0.png', f'/api/tasks/{tid}/download/image_0.png', f'/api/tasks/{tid}/file/thumb_0.webp'):
        r = c.get(url)
        assert r.status_code == 410 and r.json == {'success': False, 'error': '结果已删除', 'code': 'media_deleted'}
    task = c.get(f'/api/tasks/{tid}').json['task']
    assert task['status'] == 'succeeded' and task['result']['result_deleted'] is True
    assert task['result']['media'] == [{'output_url': f'/api/tasks/{tid}/file/image_0.png', 'media_id': media_id,
                                        'status': 'deleted', 'kind': 'image', 'name': 'image_0.png'}]
    assert tid in [t['id'] for t in c.get('/api/tasks').json['tasks']]
    assert c.post('/api/tasks/bulk-download', json={'ids': [tid]}).status_code == 404


def test_task_purge_deletes_generated_history_but_expiry_never_removes_library_files():
    """GEN-RESULT-LIFECYCLE-20261119 replaces "deletion never removes library files" for tasks."""
    c = client()
    tid, path = generated()
    media_id, library_file = in_library(tid, path)
    other, other_path = generated('green')
    other_id, other_file = in_library(other, other_path)
    plain, plain_path = generated('red')
    # Expiry skips library-backed outputs.
    tasks.get_db().execute('UPDATE task_assets SET expires_at=?', ('2000-01-01T00:00:00+00:00',))
    tasks.get_db().commit()
    assert storage.cleanup_expired_assets() == 4  # the plain task's image and the three thumbnails (not library items)
    assert path.exists() and other_path.exists() and not plain_path.exists()
    tasks.get_db().execute('UPDATE task_assets SET expires_at=NULL')
    tasks.get_db().commit()
    # A copy out of 生成历史 survives the task.
    keep = c.post('/api/canvas/media/folders', json={'title': 'keep'}).json['folder']
    copy_id = c.post('/api/canvas/media/move', json={'ids': [other_id], 'folder_id': keep['id']}).json['media'][0]['id']
    # Trash + permanent delete (single and bulk) remove the task and its 生成历史 result.
    assert c.delete(f'/api/tasks/{tid}').json['trashed']
    assert c.delete(f'/api/tasks/{tid}?permanent=1').json['media_deleted'] == 1
    tasks.move_tasks_to_trash([other, plain])
    r = c.post('/api/tasks/bulk-delete', json={'ids': [other, plain], 'permanent': True}).json
    assert r['deleted'] == 2 and r['media_deleted'] == 1
    assert not library_file.exists() and not other_file.exists()
    assert c.get(f'/api/canvas/media/{media_id}').status_code == 410
    assert c.get(f'/api/canvas/media/{other_id}').status_code == 410
    assert c.get(f'/api/canvas/media/{copy_id}').data == image_bytes('green')
    assert tasks.get_task(tid) is None and not Path(storage.OUTPUT_DIR, 'image', str(plain)).exists()
    library_file = media.media_path(media.get_media(copy_id))
    other_file = library_file
    # Orphan maintenance leaves the library untouched as well.
    storage.cleanup_orphans(0)
    assert library_file.exists() and other_file.exists()


def test_remove_task_files_never_touches_paths_inside_the_library():
    tid, path = generated(thumbnail=False)
    media_id, library_file = in_library(tid, path)
    # A task row pointing into the library (e.g. a future direct registration) is not deleted.
    tasks.register_asset(tid, 'output_image', str(library_file), 'image/png')
    import task_media
    task_media.remove_task_files(tasks.get_task(tid))
    assert library_file.exists() and media.get_media(media_id)


def test_project_and_canvas_cleanup_keep_library_files_and_task_cards():
    p = store.create_project('cleanup')['id']
    w = store.create_workflow(p, 'canvas')['id']
    tid, path = generated(workflow_id=w)
    media_id, library_file = in_library(tid, path)
    plain_tid, plain_path = generated('green', workflow_id=w, thumbnail=False)
    copy = store.save_asset(w, io.BytesIO(image_bytes('blue')), 'copy.png')  # an old canvas copy of library content
    copy_path = store.asset_path(store.get_asset(w, copy['id']))
    result = cleanup.delete_scope('project', p, True)
    assert library_file.exists() and path.exists() and copy_path.exists()
    assert not plain_path.exists()
    assert result['retained_library'] >= 2
    assert not tasks.get_task(tid)['params'].get('canvas_outputs_purged')
    assert tasks.get_task(plain_tid)['params']['canvas_outputs_purged']
    assert media.get_media(media_id)
    # Archive-only deletion (no cleanup) keeps everything, as before.
    p2 = store.create_project('archive')['id']
    w2 = store.create_workflow(p2, 'canvas')['id']
    tid2, path2 = generated('red', workflow_id=w2)
    id2, file2 = in_library(tid2, path2)
    cleanup.delete_scope('workflow', w2, False)
    assert file2.exists() and path2.exists()


def test_old_local_delete_routes_use_media_delete_with_placeholders():
    c = client()
    p = store.create_project('proj')['id']
    w = store.create_workflow(p, 'canvas')['id']
    legacy = store.save_asset(w, io.BytesIO(image_bytes('blue')), 'old.png')
    tid, path = generated()
    media_id, library_file = in_library(tid, path)
    with store.write_transaction():
        media.add_alias('workflow', legacy['id'], media_id)
    before = doc_with_reference(w, legacy)
    task_key = 'task:' + str(next(a['id'] for a in tasks.list_assets(tid) if a['kind'] == 'output_image'))
    keys = ['workflow:' + legacy['id'], task_key]
    preview = c.post('/api/canvas/library/items/delete-preview', json={'keys': keys}).json
    assert preview['success'] and preview['items'] == 2 and preview['media_keys'] == {k: media_id for k in keys}
    assert preview['media']['items'][0]['id'] == media_id and preview['placeholder_nodes'] == 1
    assert [a['workflow_id'] for a in preview['affected_workflows']] == [w] and preview['workflow_ids'] == [w]
    assert store.workflow(w)['revision'] == before['revision'] and library_file.exists()
    assert c.post('/api/canvas/library/items/bulk-delete', json={'keys': keys}, headers={'Origin': 'https://evil.example'}).status_code == 403
    result = c.post('/api/canvas/library/items/bulk-delete', json={'keys': keys}).json
    assert result['success'] and sorted(result['deleted_keys']) == sorted(keys) and result['files_removed'] == 1
    assert not library_file.exists()
    src, gen = store.workflow(w)['document']['nodes']
    # placeholder node (old canvas id normalized to the media id via its alias, S1b), stripped input
    assert src['asset']['id'] == media_id and src['asset']['url'] == f'/api/canvas/media/{media_id}'
    assert gen['referenceAssets'] == []
    assert c.get(f'/api/tasks/{tid}/file/image_0.png').status_code == 410
    # A second delete reports the key as missing; single-item DELETE of an unknown key 404s.
    assert c.post('/api/canvas/library/items/bulk-delete', json={'keys': [task_key]}).json['missing'] == [task_key]
    assert c.delete('/api/canvas/library/items/' + task_key).status_code == 404


def test_single_delete_allows_library_backed_generation_result_only():
    c = client()
    tid, path = generated(thumbnail=False)
    plain, _ = generated('green', thumbnail=False)
    plain_key = 'task:' + str(tasks.list_assets(plain)[0]['id'])
    assert c.delete('/api/canvas/library/items/' + plain_key).status_code == 409
    media_id, library_file = in_library(tid, path)
    key = 'task:' + str(tasks.list_assets(tid)[0]['id'])
    r = c.delete('/api/canvas/library/items/' + key)
    assert r.status_code == 200 and r.json['media_keys'] == {key: media_id} and not library_file.exists()
    assert json.dumps(r.json).find('http') == -1
