"""LIBRARY-GLOBAL-20261116 S1a: global media library data layer and API (new tables, old ones untouched)."""
import io
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
import app as application
import canvas_store as store
import media_library as media
import media_schema
import tasks
import storage
from test_canvas_library_folders import image_bytes
from test_canvas_asset_nodes import media as media_files  # noqa: F401  (fixture)
from test_local_delete import doc_with_reference

SYSTEM = {k: media.system_folder_id(k) for k in ('generated', 'generated_image', 'generated_video', 'generated_audio')}


def client():
    return application.app.test_client()


def up(c, data=None, name='a.png', **form):
    r = c.post('/api/canvas/media', data={'file': (io.BytesIO(data or image_bytes('red')), name), **form})
    assert r.status_code in (200, 201), r.json
    return r.json


def output(task_kind='image', data=None, name='out.png'):
    tid = tasks.create_task(task_kind, 'p', {}, status='succeeded')
    directory = Path(storage.OUTPUT_DIR) / str(tid)
    directory.mkdir(parents=True)
    path = directory / name
    path.write_bytes(data or image_bytes('blue'))
    tasks.register_asset(tid, 'output_' + task_kind, str(path), 'image/png')
    return tid, path


def test_schema_system_and_default_folders_idempotent():
    folders = {f['title']: f for f in client().get('/api/canvas/media/folders').json['folders']}
    assert folders['生成历史']['system_key'] == 'generated' and folders['生成历史']['parent_id'] is None
    for key, title in (('generated_image', '图片'), ('generated_video', '视频'), ('generated_audio', '音频')):
        assert folders[title]['id'] == SYSTEM[key] and folders[title]['parent_id'] == SYSTEM['generated']
    assert folders['角色卡']['system_key'] == 'characters' and folders['角色卡']['parent_id'] is None
    assert folders['角色卡']['id'] == media.system_folder_id('characters') and folders['角色卡']['icon'] == 'character'
    for title in ('音效', '角色', '场景', '物品', '风格'):
        assert folders[title]['parent_id'] is None and folders[title]['system_key'] is None
    # A deleted default is never recreated; re-running init (API + Worker) is harmless.
    assert client().delete('/api/canvas/media/folders/' + folders['风格']['id']).status_code == 200
    tasks.init_db()
    media_schema.create(tasks.get_db(), tasks._ensure_columns)
    titles = [f['title'] for f in client().get('/api/canvas/media/folders').json['folders']]
    assert '风格' not in titles and titles.count('生成历史') == 1 and titles.count('角色卡') == 1
    assert 'media_id' in {r['name'] for r in tasks.get_db().execute('PRAGMA table_info(task_assets)')}


def test_upload_read_info_thumbnail_and_dedup(media_files):
    c = client()
    first = up(c)
    item = first['media']
    assert not first['deduplicated'] and item['folder_id'] is None and item['origin'] == 'upload' and item['kind'] == 'image'
    assert item['url'] == '/api/canvas/media/' + item['id']
    assert c.get(item['url']).data == image_bytes('red')
    assert c.get(item['url'] + '/info').json['media'] == item
    assert c.get(item['thumbnail_url']).mimetype == 'image/webp'
    again = c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('red')), 'b.png')})
    assert again.status_code == 200 and again.json['deduplicated'] and again.json['media']['id'] == item['id']
    name, raw = media_files['audio']
    audio = up(c, raw, name)['media']
    assert audio['kind'] == 'audio' and audio['thumbnail_url'] is None
    assert c.get(audio['url'] + '/thumbnail').json['code'] == 'no_thumbnail'
    # Old library tables are untouched by the new API.
    assert tasks.get_db().execute('SELECT COUNT(*) FROM canvas_local_uploads').fetchone()[0] == 0


def test_upload_errors_and_folder_targets():
    c = client()
    bad = c.post('/api/canvas/media', data={'file': (io.BytesIO(b'not media'), 'x.txt')})
    assert bad.status_code == 400 and bad.json['code'] == 'unsupported_media'
    empty = c.post('/api/canvas/media', data={'file': (io.BytesIO(b''), 'x.png')})
    assert empty.status_code == 400 and empty.json['code'] in ('empty_file', 'unsupported_media')
    system = c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('red')), 'a.png'), 'folder_id': SYSTEM['generated_image']})
    assert system.status_code == 409 and system.json['code'] == 'folder_generated_only'
    char_root = c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('red')), 'a.png'),
                                                  'folder_id': media.system_folder_id('characters')})
    assert char_root.status_code == 409 and char_root.json['code'] == 'folder_character_managed'
    missing = c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('red')), 'a.png'), 'folder_id': '0' * 32})
    assert missing.status_code == 404 and missing.json['code'] == 'folder_not_found'
    folder = c.post('/api/canvas/media/folders', json={'title': '分镜'}).json['folder']
    placed = up(c, folder_id=folder['id'], origin='paste')['media']
    assert placed['folder_id'] == folder['id'] and placed['origin'] == 'paste'
    assert c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('blue')), 'a.png'), 'origin': 'generated'}).json['code'] == 'invalid_request'
    assert list(media.root().glob('*.tmp')) == []
    assert c.get('/api/canvas/media/' + 'f' * 32).json['code'] == 'media_not_found'
    assert c.get('/api/canvas/media/nothex').json['code'] == 'invalid_id'


def test_listing_filters_pagination_and_ids(media_files):
    c = client()
    folder = c.post('/api/canvas/media/folders', json={'title': '角色A'}).json['folder']
    child = c.post('/api/canvas/media/folders', json={'title': '子', 'parent_id': folder['id']}).json['folder']
    a = up(c, image_bytes('red'), '100%_hero.png', folder_id=folder['id'])['media']
    b = up(c, image_bytes('green'), 'villain.png', folder_id=child['id'])['media']
    r = up(c, image_bytes('blue'), 'root.png')['media']
    name, raw = media_files['video']
    v = up(c, raw, name)['media']
    get = lambda **q: c.get('/api/canvas/media', query_string=q).json
    assert get()['total'] == 4 and [i['id'] for i in get()['items']][0] == v['id']
    assert [i['id'] for i in get(folder_id='root')['items']] == [v['id'], r['id']]
    assert [i['id'] for i in get(folder_id=folder['id'])['items']] == [a['id']]
    assert {i['id'] for i in get(folder_id=folder['id'], include_subfolders='1')['items']} == {a['id'], b['id']}
    assert [i['id'] for i in get(kind='video')['items']] == [v['id']]
    assert [i['id'] for i in get(q='100%')['items']] == [a['id']] and get(q='_')['total'] == 1
    page = get(limit='2', page='2')
    assert page['total'] == 4 and len(page['items']) == 2 and page['page'] == 2
    assert c.get('/api/canvas/media?limit=999').json['code'] == 'invalid_request'
    assert c.get('/api/canvas/media/ids', query_string={'kind': 'image'}).json['total'] == 3
    assert {f['id']: f['media_count'] for f in c.get('/api/canvas/media/folders').json['folders']}[folder['id']] == 1


def test_folder_rules():
    c = client()
    a = c.post('/api/canvas/media/folders', json={'title': 'A', 'icon': 'scene'}).json['folder']
    b = c.post('/api/canvas/media/folders', json={'title': 'B', 'parent_id': a['id']}).json['folder']
    renamed = c.patch('/api/canvas/media/folders/' + b['id'], json={'title': 'B2'})
    assert renamed.status_code == 200 and renamed.json['folder']['title'] == 'B2'
    assert c.patch('/api/canvas/media/folders/' + a['id'], json={'parent_id': b['id']}).json['code'] == 'folder_cycle'
    for key in SYSTEM.values():
        assert c.patch('/api/canvas/media/folders/' + key, json={'title': 'x'}).json['code'] == 'folder_system'
        assert c.delete('/api/canvas/media/folders/' + key).json['code'] == 'folder_system'
    char_root_id = media.system_folder_id('characters')
    assert c.patch('/api/canvas/media/folders/' + char_root_id, json={'title': 'x'}).json['code'] == 'folder_character_managed'
    assert c.delete('/api/canvas/media/folders/' + char_root_id).json['code'] == 'folder_character_managed'
    assert c.post('/api/canvas/media/folders', json={'title': 'x', 'parent_id': char_root_id}).json['code'] == 'folder_character_managed'
    assert c.post('/api/canvas/media/folders', json={'title': 'x', 'parent_id': SYSTEM['generated']}).json['code'] == 'folder_target_invalid'
    assert c.post('/api/canvas/media/folders', json={'title': ' '}).json['code'] == 'invalid_name'
    assert c.delete('/api/canvas/media/folders/' + a['id']).json['code'] == 'folder_not_empty'
    up(c, folder_id=b['id'])
    assert c.delete('/api/canvas/media/folders/' + b['id']).json['code'] == 'folder_not_empty'


def test_register_generated_hardlink_idempotent_move_and_q6():
    tid, path = output()
    media_id = media.register_generated(tid, path, 'output_image', name='结果1.png')
    row = media.get_media(media_id)
    assert row['folder_id'] == SYSTEM['generated_image'] and row['origin'] == 'generated' and row['source_task_id'] == tid
    assert os.stat(media.media_path(row)).st_ino == os.stat(path).st_ino  # hard link, no copy
    asset_id = tasks.list_assets(tid)[0]['id']
    assert media.task_media(asset_id) == ('ok', row)
    assert media.register_generated(tid, path, 'image') == media_id
    assert tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0] == 1
    assert media.resolve(f'task:{asset_id}') == media_id
    with pytest.raises(media.MediaError):
        media.register_generated(tid, path, 'video')
    c = client()
    move = lambda folder: c.post('/api/canvas/media/move', json={'ids': [media_id], 'folder_id': folder})
    assert move(SYSTEM['generated']).json['code'] == 'folder_generated_only'
    assert move(SYSTEM['generated_video']).json['code'] == 'folder_generated_only'
    # GEN-RESULT-LIFECYCLE-20261119: moving a 生成历史 item out copies it (new id, same file).
    folder = c.post('/api/canvas/media/folders', json={'title': 'keep'}).json['folder']
    moved = move(folder['id']).json
    copy_id = moved['media'][0]['id']
    assert copy_id != media_id and moved['media'][0]['folder_id'] == folder['id']
    assert moved['copied'] == [{'source_id': media_id, 'id': copy_id}]
    assert move(SYSTEM['generated_image']).json['media'][0]['id'] == media_id  # already there: no-op
    assert c.post('/api/canvas/media/move', json={'ids': [media_id, 'e' * 32], 'folder_id': None}).json['code'] == 'media_not_found'
    assert media.get_media(media_id)['folder_id'] == SYSTEM['generated_image']
    assert c.post('/api/canvas/media/delete', json={'ids': [copy_id]}).json['deleted_ids'] == [copy_id]
    assert media.get_media(media_id)['folder_id'] == SYSTEM['generated_image']
    # User decision 2026-11-17 (S9): uploading the same bytes at runtime returns the existing result
    # unchanged (still in 生成历史, origin generated); Q6 "move to the root" only applies to migration.
    hit = up(c, image_bytes('blue'), 'mine.png')
    assert hit['deduplicated'] and hit['media']['id'] == media_id
    assert hit['media']['folder_id'] == SYSTEM['generated_image'] and hit['media']['origin'] == 'generated'
    assert media.get_media(media_id)['name'] != 'mine.png'
    # Not in the library: the task center falls back to output.
    other_tid, _ = output(data=image_bytes('green'))
    assert media.task_media(tasks.list_assets(other_tid)[0]['id']) == ('none', None)


def test_generated_history_only_takes_generated_results():
    """User decision 2026-11-17 (E4): uploads cannot enter 生成历史 or its type subfolders."""
    c = client()
    uploaded = up(c, image_bytes('red'), 'up.png')['media']
    move = lambda ids, folder: c.post('/api/canvas/media/move', json={'ids': ids, 'folder_id': folder})
    for key in ('generated', 'generated_image', 'generated_video'):
        r = move([uploaded['id']], SYSTEM[key])
        assert r.status_code == 409 and r.json['code'] == 'folder_generated_only' and '生成历史' in r.json['error']
        assert c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('green')), 'b.png'), 'folder_id': SYSTEM[key]}).json['code'] == 'folder_generated_only'
    tid, path = output()
    generated = media.register_generated(tid, path, 'image')
    # All-or-nothing: a mixed selection is refused and nothing moves.
    assert move([generated, uploaded['id']], SYSTEM['generated_image']).json['code'] == 'folder_generated_only'
    assert media.get_media(uploaded['id'])['folder_id'] is None
    assert move([generated], SYSTEM['generated_video']).json['code'] == 'folder_generated_only'
    copied = move([generated], None).json['media'][0]  # results leave as copies
    assert copied['folder_id'] is None and copied['id'] != generated
    # Nothing (not even a copy of a result) moves back into 生成历史.
    assert move([copied['id']], SYSTEM['generated_image']).json['code'] == 'folder_generated_only'
    assert media.get_media(generated)['folder_id'] == SYSTEM['generated_image']
    with pytest.raises(media.MediaError) as error:
        fresh = path.with_name('fresh.png')
        fresh.write_bytes(image_bytes('white'))
        media.import_file(fresh, name='x.png', origin='upload', folder_id=SYSTEM['generated_image'])
    assert error.value.code == 'folder_generated_only'


def test_folder_names_no_slash_and_unique_among_siblings():
    """User decision 2026-11-17 (E3): checked on create/rename/move only; existing data unchanged."""
    c = client()
    create = lambda **data: c.post('/api/canvas/media/folders', json=data)
    patch = lambda folder, **data: c.patch('/api/canvas/media/folders/' + folder, json=data)
    slash = create(title='a/b')
    assert slash.status_code == 400 and slash.json['code'] == 'invalid_name' and '/' in slash.json['error']
    a = create(title='A').json['folder']
    b = create(title='B').json['folder']
    for title in ('A', ' a ', '生成历史', '角色'):
        r = create(title=title)
        assert r.status_code == 409 and r.json['code'] == 'folder_name_conflict', title
    child = create(title='A', parent_id=b['id'])
    assert child.status_code == 201 or child.status_code == 200
    assert patch(b['id'], title='a').json['code'] == 'folder_name_conflict'
    assert patch(b['id'], title='x/y').json['code'] == 'invalid_name'
    assert patch(a['id'], title=' A ').json['folder']['title'] == 'A'  # own name is not a conflict
    assert patch(a['id'], title='a').json['folder']['title'] == 'a'
    moved = patch(child.json['folder']['id'], parent_id=None)
    assert moved.status_code == 409 and moved.json['code'] == 'folder_name_conflict'
    # Existing duplicates and slashes stay valid; only icon changes are not re-checked.
    with store.write_transaction() as db:
        db.execute("INSERT INTO media_folders VALUES ('f'||hex(randomblob(15)), 'a', NULL, NULL, 'folder', 't', 't')")
        db.execute("INSERT INTO media_folders VALUES (?, 'old/name', NULL, NULL, 'folder', 't', 't')", ('e' * 32,))
    assert patch('e' * 32, icon='scene').json['folder']['title'] == 'old/name'
    assert patch(a['id'], icon='scene').json['folder']['icon'] == 'scene'
    titles = [f['title'] for f in c.get('/api/canvas/media/folders').json['folders'] if f['parent_id'] is None]
    assert titles.count('a') == 2 and 'old/name' in titles


def test_register_generated_copies_when_link_unavailable(monkeypatch):
    tid, path = output()
    monkeypatch.setattr(media.os, 'link', lambda *a: (_ for _ in ()).throw(OSError(18, 'EXDEV')))
    row = media.get_media(media.register_generated(tid, path, 'image'))
    assert media.media_path(row).read_bytes() == path.read_bytes()
    assert os.stat(media.media_path(row)).st_ino != os.stat(path).st_ino


def test_resolve_aliases_and_urls():
    item = up(client())['media']
    old = 'a' * 32
    with store.write_transaction():
        media.add_alias('workflow', old, item['id'])
        media.add_alias('local', 'b' * 32, item['id'])
    assert media.resolve(item['id']) == item['id']
    assert media.resolve(old) == item['id'] and media.resolve('workflow:' + old) == item['id']
    assert media.resolve(f'/api/canvas/workflows/w1/assets/{old}') == item['id']
    assert media.resolve('/api/canvas/library/items/local:' + 'b' * 32 + '/download?inline=1') == item['id']
    assert media.resolve(item['url'] + '/thumbnail') == item['id']
    assert media.resolve('library:' + old) is None and media.resolve('c' * 32) is None and media.resolve('/etc/passwd') is None
    found = client().post('/api/canvas/media/lookup', json={'refs': [old, 'c' * 32]}).json['items']
    assert found[0]['status'] == 'ok' and found[0]['media']['id'] == item['id'] and found[1] == {'ref': 'c' * 32, 'status': 'missing', 'media_id': None}


def test_delete_preview_and_delete_keep_placeholders():
    c = client()
    p = store.create_project('proj')['id']
    w = store.create_workflow(p, 'canvas')['id']
    legacy = store.save_asset(w, io.BytesIO(image_bytes('red')), 'old.png')
    tid, path = output()
    media_id = media.register_generated(tid, path, 'image')
    with store.write_transaction():
        media.add_alias('workflow', legacy['id'], media_id)
    before = doc_with_reference(w, legacy)
    file_path = media.media_path(media.get_media(media_id))
    cross = c.post('/api/canvas/media/delete', json={'ids': [media_id]}, headers={'Sec-Fetch-Site': 'cross-site'})
    assert cross.status_code == 403
    preview = c.post('/api/canvas/media/delete-preview', json={'ids': [media_id, 'd' * 32]}).json
    assert preview['missing'] == ['d' * 32] and preview['task_ids'] == [tid]
    assert preview['affected_workflows'] == [{'workflow_id': w, 'workflow_title': 'canvas', 'project_id': p, 'project_title': 'proj',
                                              'placeholder_nodes': 1, 'stripped_nodes': 1}]
    assert media.get_media(media_id) and store.workflow(w)['revision'] == before['revision']
    result = c.post('/api/canvas/media/delete', json={'ids': [media_id]})
    assert result.status_code == 200 and result.json['deleted_ids'] == [media_id] and result.json['files_removed'] == 1
    assert not file_path.exists() and path.exists()  # the task output link is not the library's to remove (S3)
    after = store.workflow(w)
    assert after['revision'] == before['revision'] + 1
    src, gen = after['document']['nodes']
    # Placeholder kept; S1b normalizes the aliased old id to the (deleted) media id on save.
    assert src['asset']['id'] == media_id and src['asset']['url'] == '/api/canvas/media/' + media_id
    assert gen['referenceAssets'] == [] and gen['referenceOrder'] == [] and gen['referenceMentions'] == {} and gen['referenceGroups'] == []
    gone = c.get('/api/canvas/media/' + media_id)
    assert gone.status_code == 410 and gone.json['code'] == 'media_deleted'
    info = c.get(f'/api/canvas/media/{media_id}/info').json
    assert info['media']['deleted'] and info['media']['kind'] == 'image'
    assert media.task_media(tasks.list_assets(tid)[0]['id'])[0] == 'deleted'
    assert c.post('/api/canvas/media/lookup', json={'refs': ['workflow:' + legacy['id']]}).json['items'][0]['status'] == 'deleted'
    assert c.post('/api/canvas/media/delete', json={'ids': [media_id]}).json['deleted_ids'] == []
    # Old canvas asset rows remain until migration (S1b).
    assert store.get_asset(w, legacy['id'])


def test_concurrent_uploads_of_same_content_register_once():
    barrier = Barrier(4)

    def run(_):
        barrier.wait()
        try:
            return media.save_upload(io.BytesIO(image_bytes('red')), 'same.png')[0]['id']
        finally:
            tasks.close_db()
    with ThreadPoolExecutor(4) as pool:
        ids = set(pool.map(run, range(4)))
    assert len(ids) == 1
    assert tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0] == 1
    assert len([p for p in media.root().iterdir()]) == 1


def test_global_groups_crud_expand_and_deleted_placeholders():
    c = client()
    a = up(c, image_bytes('red'), 'a.png')['media']
    b = up(c, image_bytes('green'), 'b.png')['media']
    d = up(c, image_bytes('blue'), 'd.png')['media']
    assert c.post('/api/canvas/media/groups', json={'title': 'g', 'media_ids': []}).json['code'] == 'invalid_request'
    assert c.post('/api/canvas/media/groups', json={'title': 'g', 'media_ids': ['e' * 32]}).json['code'] == 'media_not_found'
    created = c.post('/api/canvas/media/groups', json={'title': '主角', 'media_ids': [b['id'], a['id'], b['id']]})
    assert created.status_code == 201
    group = created.json['group']
    assert group['media_ids'] == [b['id'], a['id']] and group['member_count'] == 2 and group['deleted_count'] == 0
    path = '/api/canvas/media/groups/' + group['id']
    patched = c.patch(path, json={'title': '主角2', 'add': [d['id'], a['id']], 'remove': [b['id']]}).json['group']
    assert patched['title'] == '主角2' and patched['media_ids'] == [a['id'], d['id']]
    assert c.patch(path, json={'media_ids': [d['id'], a['id']]}).json['group']['media_ids'] == [d['id'], a['id']]
    assert c.patch(path, json={'media_ids': [a['id']], 'add': [d['id']]}).json['code'] == 'invalid_request'
    assert [g['id'] for g in c.get('/api/canvas/media/groups').json['groups']] == [group['id']]
    # Deleting a member keeps it as a placeholder; groups never own files.
    preview = c.post('/api/canvas/media/delete-preview', json={'ids': [d['id']]}).json
    assert preview['media_groups'] == [{'id': group['id'], 'title': '主角2'}]
    c.post('/api/canvas/media/delete', json={'ids': [d['id']]})
    expanded = c.get(path).json
    assert [(i['media_id'], i['status']) for i in expanded['items']] == [(d['id'], 'deleted'), (a['id'], 'ok')]
    assert expanded['group']['deleted_count'] == 1 and expanded['items'][0]['media']['deleted']
    assert [i['media_id'] for i in c.get(path + '?include_deleted=0').json['items']] == [a['id']]
    # Re-saving the order with the placeholder is allowed; adding a deleted id is not.
    assert c.patch(path, json={'media_ids': [a['id'], d['id']]}).status_code == 200
    assert c.patch(path, json={'add': [d['id']]}).status_code == 200
    other = c.post('/api/canvas/media/groups', json={'title': 'x', 'media_ids': [a['id']]}).json['group']
    assert c.patch('/api/canvas/media/groups/' + other['id'], json={'add': [d['id']]}).json['code'] == 'media_not_found'
    assert c.patch(path, json={'remove': [d['id']]}).json['group']['media_ids'] == [a['id']]
    assert c.patch(path, json={'remove': [a['id']]}).json['code'] == 'invalid_request'
    assert c.delete(path).status_code == 200 and c.get(path).json['code'] == 'group_not_found'
    assert media.get_media(a['id'])
    # S1b keeps old group ids.
    kept = media.create_group('迁移组', [a['id']], group_id='f' * 32)
    assert kept['id'] == 'f' * 32


def test_rename_media_api(media_files):
    """S6b: PATCH /api/canvas/media/<id> {name} changes only the display/download name."""
    c = client()
    item = up(c, name='old.png')['media']
    path = media.media_path(media.get_media(item['id']))
    r = c.patch('/api/canvas/media/' + item['id'], json={'name': '  主角 正面.png '})
    assert r.status_code == 200 and r.json['media']['name'] == '主角 正面.png'
    assert {k: v for k, v in r.json['media'].items() if k != 'name'} == {k: v for k, v in item.items() if k != 'name'}
    assert c.get('/api/canvas/media/' + item['id'] + '/info').json['media']['name'] == '主角 正面.png'
    assert media.media_path(media.get_media(item['id'])) == path
    download = c.get('/api/canvas/media/' + item['id'] + '?download=1')
    assert '.png' in download.headers['Content-Disposition'] and download.data == image_bytes('red')
    assert c.get('/api/canvas/media', query_string={'q': '主角'}).json['total'] == 1
    for payload, code in (({'name': ''}, 'invalid_name'), ({'name': 'a/b'}, 'invalid_name'), ({'name': 'x' * 241}, 'invalid_name'),
                          ({'name': 'a\nb'}, 'invalid_name'), ({'name': 3}, 'invalid_name'),
                          ({'name': 'a', 'folder_id': None}, 'invalid_request'), ({}, 'invalid_request')):
        bad = c.patch('/api/canvas/media/' + item['id'], json=payload)
        assert bad.status_code == 400 and bad.json['code'] == code, payload
    assert c.patch('/api/canvas/media/' + item['id'], data='[]', content_type='application/json').status_code == 400
    assert c.patch('/api/canvas/media/zz', json={'name': 'a'}).json['code'] == 'invalid_id'
    missing = c.patch('/api/canvas/media/' + '0' * 32, json={'name': 'a'})
    assert missing.status_code == 404 and missing.json['code'] == 'media_not_found'
    media.delete_media([item['id']])
    gone = c.patch('/api/canvas/media/' + item['id'], json={'name': 'a'})
    assert gone.status_code == 410 and gone.json['code'] == 'media_deleted'


def test_video_thumbnail_generation_cache_and_fallback(media_files, monkeypatch):
    """BACKLOG-LIBRARY-SIDEBAR: video media serves a cached 320px WebP first-frame thumbnail and falls back to 404."""
    c = client()
    name, raw = media_files['video']
    video = up(c, raw, name)['media']
    assert video['kind'] == 'video' and video['thumbnail_url'] == video['url'] + '/thumbnail'
    thumb_path = media.video_thumbnail_path(video['id'])
    assert not thumb_path.exists()
    # Graceful fallback when ffmpeg is unavailable.
    monkeypatch.setattr(media.shutil, 'which', lambda cmd: None)
    miss = c.get(video['thumbnail_url'])
    assert miss.status_code == 404 and miss.json['code'] == 'no_thumbnail'
    assert not thumb_path.exists()
    # With ffmpeg available, first frame is extracted and cached as .thumb.webp.
    monkeypatch.undo()
    resp = c.get(video['thumbnail_url'])
    assert resp.status_code == 200 and resp.mimetype == 'image/webp'
    assert thumb_path.is_file() and thumb_path.stat().st_size > 0
    # Cached hit works even if ffmpeg is later unavailable.
    monkeypatch.setattr(media.shutil, 'which', lambda cmd: None)
    cached = c.get(video['thumbnail_url'])
    assert cached.status_code == 200 and cached.mimetype == 'image/webp'
    # Deleting the video cleans up its cached thumbnail.
    media.delete_media([video['id']])
    assert not thumb_path.exists()
