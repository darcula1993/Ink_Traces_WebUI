"""LIBRARY-GLOBAL-20261116 S9: QA rework.

* D1: old read/reference routes go through media aliases/tombstones (春丽 probes
  probe_copy_delete / probe_copy_legacy / probe_copy_resurrect turned into tests).
* O1: default folders keep their declared order.
* O2: rollback export (--new-since) copies new media files and lists later changes.
* 2026-11-17 user decision: a runtime upload of a 生成历史 result is not moved or re-sourced.
"""
import io
import json
import subprocess
import sys

import pytest
import canvas_store as store
import media_library as media
import media_migrate as migrate
import tasks
from test_canvas_library_folders import image_bytes
from test_media_migrate import SCRIPT, run, world  # noqa: F401  (fixture)
from test_canvas_asset_nodes import media as media_files  # noqa: F401  (fixture)
import app as application

H = {'Origin': 'http://localhost', 'Host': 'localhost'}
DEFAULTS = ['音效', '角色', '场景', '物品', '风格']


def client():
    return application.app.test_client()


def canvas_rows():
    return tasks.get_db().execute('SELECT COUNT(*) FROM canvas_assets').fetchone()[0]


def delete(c, ids):
    r = c.post('/api/canvas/media/delete', json={'ids': ids}, headers=H)
    assert r.status_code == 200, r.json
    return r.json


def keys(c, **query):
    r = c.get('/api/canvas/library/items', query_string={'scope': 'all', **query})
    assert r.status_code == 200, r.json
    return [i['key'] for i in r.json['items']]


# ---------------------------------------------------------------- D1

def test_old_routes_serve_library_items_from_media_without_new_copies(world, tmp_path):
    run(tmp_path)
    ids, c = world.ids, client()
    # Old canvas URL of a copy that entered the library (A1 -> B1) reads the media file.
    r = c.get(f"/api/canvas/workflows/w1/assets/{ids['A1']}")
    assert r.status_code == 200 and r.data == media.media_path(media.get_media(ids['B1'])).read_bytes()
    assert r.headers['X-Content-Type-Options'] == 'nosniff'
    assert c.get(f"/api/canvas/projects/p1/assets/{ids['B1']}").status_code == 200
    assert c.get(f"/api/canvas/library/items/local:{ids['L1']}/download").status_code == 200
    assert c.get(f"/api/canvas/library/items/local:{ids['L1']}/thumbnail").mimetype == 'image/webp'
    # Already ingested old items are not listed by the old catalog (the library lists them).
    listed = keys(c) + keys(c, source='generated')
    assert f"local:{ids['L1']}" not in listed and f'task:{world.ta3}' not in listed
    assert ids['B1'] not in [a['id'] for a in c.get('/api/canvas/projects/p1/assets').json['assets']]
    # Referencing them returns media references; no canvas copy is created.
    before = canvas_rows()
    r = c.post('/api/canvas/workflows/w1/library-references',
               json={'items': [{'source': 'local', 'id': ids['L1']}, {'source': 'task', 'id': str(world.ta3)}]}, headers=H)
    assert r.status_code == 200, r.json
    assert [a['url'] for a in r.json['assets']] == [f"/api/canvas/media/{ids['L1']}", f"/api/canvas/media/{ids['A3']}"]
    r = c.post('/api/canvas/workflows/w1/reference-assets', json={'asset_ids': [ids['B1']], 'group_ids': [ids['G1']]})
    assert r.status_code == 200 and r.json['assets'][0]['id'] == ids['B1'] and r.json['groups'][0]['asset_ids'] == [ids['B1']]
    r = c.post('/api/canvas/projects/p1/assets/from-workflow', json={'workflow_id': 'w1', 'asset_id': ids['A4']})
    assert r.status_code == 200 and r.json['asset']['url'] == f"/api/canvas/media/{ids['A4']}"
    r = c.post('/api/canvas/projects/p1/library-items/save', json={'items': [{'source': 'local', 'id': ids['L1']}]}, headers=H)
    assert r.status_code == 201 and r.json['assets'][0]['id'] == ids['L1']
    assert canvas_rows() == before
    assert tasks.get_db().execute('SELECT COUNT(*) FROM canvas_library_assets').fetchone()[0] == 2


def test_deleted_library_items_answer_410_on_every_old_route(world, tmp_path):
    """probe_copy_delete + probe_copy_legacy + probe_copy_resurrect."""
    run(tmp_path)
    ids, c, db = world.ids, client(), world.db
    # An archived canvas copy that only got an alias (same content as the local upload L1).
    db.execute("INSERT INTO canvas_assets VALUES (?, 'w2', 'kept.png', 'image/png', 'image', 'x', 1, ?, ?)",
               ('f' * 32, 'f' * 32 + '.png', tasks.utcnow()))
    media.add_alias('workflow', 'f' * 32, ids['L1'])
    db.commit()
    gen, local, library = ids['A3'], ids['L1'], ids['B1']
    result = delete(c, [gen, local, library])
    assert sorted(result['deleted_ids']) == sorted([gen, local, library])
    gone = [f'/api/canvas/workflows/w1/assets/{gen}', f"/api/canvas/workflows/w1/assets/{ids['A1']}",
            f"/api/canvas/workflows/w2/assets/{'f' * 32}", f'/api/canvas/projects/p1/assets/{library}',
            f'/api/canvas/library/items/local:{local}/download', f'/api/canvas/library/items/local:{local}/thumbnail',
            f'/api/canvas/library/items/task:{world.ta3}/download', f'/api/canvas/library/items/library:{library}/download',
            f'/api/canvas/media/{gen}']
    for url in gone:
        r = c.get(url)
        assert r.status_code == 410, (url, r.status_code)
        if url.startswith('/api/canvas/'):
            assert r.json['code'] == 'media_deleted' and '删除' in r.json['error'], url
    # The old catalog no longer lists them.
    listed = keys(c) + keys(c, source='generated') + keys(c, source='saved')
    assert not {f'local:{local}', f'task:{world.ta3}', f'library:{library}'} & set(listed)
    selection = c.get('/api/canvas/library/item-selection', query_string={'scope': 'all'}).json['items']
    assert f'local:{local}' not in [i['key'] for i in selection]
    # Nothing re-creates a copy of a deleted item (no resurrection).
    before = canvas_rows()
    for items in ([{'source': 'local', 'id': local}], [{'source': 'task', 'id': str(world.ta3)}],
                  [{'source': 'workflow', 'id': gen}], [{'source': 'library', 'id': library}]):
        r = c.post('/api/canvas/workflows/w1/library-references', json={'items': items}, headers=H)
        assert r.status_code == 410 and r.json['code'] == 'media_deleted', (items, r.json)
        r = c.post('/api/canvas/projects/p1/library-items/save', json={'items': items}, headers=H)
        assert r.status_code == 410, items
    assert c.post('/api/canvas/workflows/w1/reference-assets', json={'asset_ids': [library]}).status_code == 410
    assert c.post('/api/canvas/projects/p1/assets/from-workflow', json={'workflow_id': 'w1', 'asset_id': gen}).status_code == 410
    assert canvas_rows() == before
    assert all(media.status(i)[0] == 'deleted' for i in (gen, local, library))
    # Re-uploading the same bytes registers a new item; the deleted id stays deleted.
    data = (store.asset_root() / 'local_uploads' / f'{local}.png').read_bytes()
    r = c.post('/api/canvas/media', data={'file': (io.BytesIO(data), 'again.png')})
    assert r.status_code == 201 and r.json['media']['id'] != local
    assert c.get(f'/api/canvas/library/items/local:{local}/download').status_code == 410


def test_old_items_outside_the_library_keep_the_legacy_behaviour():
    """Before migration (no alias) the old routes are unchanged, e.g. a canvas copy still works."""
    c = client()
    pid = c.post('/api/canvas/projects', json={'title': 'p'}).json['project']['id']
    wid = c.post(f'/api/canvas/projects/{pid}/workflows', json={'title': 'w'}).json['workflow']['id']
    asset = c.post(f'/api/canvas/workflows/{wid}/assets', data={'file': (io.BytesIO(image_bytes('red')), 'a.png')}).json['asset']
    assert c.get(asset['url']).status_code == 200
    assert media.legacy_media('workflow', asset['id']) is None


# ---------------------------------------------------------------- O1

def test_default_folders_keep_declared_order(world, tmp_path):
    def roots():
        return [f['title'] for f in client().get('/api/canvas/media/folders').json['folders']
                if f['parent_id'] is None and f['system_key'] is None]
    system = [f['system_key'] for f in client().get('/api/canvas/media/folders').json['folders'] if f['system_key']]
    assert system == ['generated', 'generated_image', 'generated_video', 'generated_audio']
    assert roots()[:5] == DEFAULTS
    run(tmp_path)  # migrated library: same order
    assert roots()[:5] == DEFAULTS
    client().post('/api/canvas/media/folders', json={'title': '新建'})
    assert roots() == DEFAULTS + ['新建']


# ---------------------------------------------------------------- O2

def test_rollback_export_copies_new_files_and_lists_changes(world, tmp_path):
    run(tmp_path)
    ids, c, db = world.ids, client(), tasks.get_db()
    finished = json.loads(db.execute("SELECT value FROM media_meta WHERE key=?", (migrate.STATE_KEY,)).fetchone()[0])['finished_at']
    folder = c.post('/api/canvas/media/folders', json={'title': '迁移后'}).json['folder']
    new = c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('orange')), '新图.png'), 'folder_id': folder['id']}).json['media']
    assert c.post('/api/canvas/media/move', json={'ids': [ids['L1']], 'folder_id': folder['id']}).status_code == 200
    assert c.patch(f"/api/canvas/media/{ids['A4']}", json={'name': '改名.png'}).status_code == 200
    delete(c, [ids['B1']])
    group = c.post('/api/canvas/media/groups', json={'title': '新组', 'media_ids': [new['id'], ids['L1']]}).json['group']
    assert c.patch(f"/api/canvas/media/groups/{ids['G1']}", json={'title': '主角组2'}).status_code == 200
    out = tmp_path / 'export'
    db = tasks.get_db()
    report = migrate.changes_since(db, finished, out, store.asset_root())
    assert report['baseline'] and [m['id'] for m in report['new_media']] == [new['id']]
    exported = out / 'files' / report['new_media'][0]['relpath']
    assert report['exported_files'] == 1 and exported.read_bytes() == image_bytes('orange')
    assert json.loads((out / 'changes.json').read_text())['new_media'][0]['id'] == new['id']
    assert [(m['id'], m['to'], m['to_title']) for m in report['moved']] == [(ids['L1'], folder['id'], '迁移后')]
    assert report['renamed'] == [{'id': ids['A4'], 'from': 'A4.png', 'to': '改名.png'}]
    assert [d['id'] for d in report['deleted_media']] == [ids['B1']] and report['deleted_media'][0]['deleted_at']
    assert [f['id'] for f in report['folders']['created']] == [folder['id']]
    assert [g['id'] for g in report['groups']['created']] == [group['id']]
    changed = {g['id']: g for g in report['groups']['changed']}
    # The deleted member B1 stays as a placeholder (groups keep deleted members); only the title changed.
    assert changed[ids['G1']]['title'] == {'from': '主角组', 'to': '主角组2'} and 'media_ids' not in changed[ids['G1']]
    assert c.patch(f"/api/canvas/media/groups/{ids['G1']}", json={'remove': [ids['B1']], 'add': [ids['L1']]}).status_code == 200
    report = migrate.changes_since(tasks.get_db(), finished)
    changed = {g['id']: g for g in report['groups']['changed']}
    assert changed[ids['G1']]['media_ids'] == {'from': [ids['B1']], 'to': [ids['L1']]} and report['exported_files'] == 0
    # Refusals: non-empty target, target inside the asset root; nothing in the library changed.
    with pytest.raises(migrate.MigrationError):
        migrate.changes_since(db, finished, out, store.asset_root())
    with pytest.raises(migrate.MigrationError):
        migrate.changes_since(db, finished, store.asset_root() / 'export', store.asset_root())
    assert media.get_media(new['id'])['folder_id'] == folder['id']


def test_rollback_export_cli(world, tmp_path):
    run(tmp_path)
    finished = json.loads(tasks.get_db().execute("SELECT value FROM media_meta WHERE key=?", (migrate.STATE_KEY,)).fetchone()[0])['finished_at']
    assert client().post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('orange')), 'n.png')}).status_code == 201
    tasks.close_db()
    out = tmp_path / 'cli-export'
    proc = subprocess.run([sys.executable, str(SCRIPT), '--db', str(tasks.DB_PATH), '--asset-root', str(store.asset_root()),
                           '--new-since', finished, '--export-dir', str(out)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout[proc.stdout.index('{'):])
    assert report['exported_files'] == 1 and len(list((out / 'files').iterdir())) == 1
    proc = subprocess.run([sys.executable, str(SCRIPT), '--db', str(tasks.DB_PATH), '--export-dir', str(out)],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0


# ---------------------------------------------------------------- user decision 2026-11-17

def test_runtime_upload_of_generated_result_is_not_moved():
    c = client()
    tid = tasks.create_task('image', 'p', {}, status='succeeded')
    path = store.asset_root().parent / f'gen-{tid}.png'
    path.write_bytes(image_bytes('purple'))
    generated = media.import_file(path, name='结果.png', origin='generated', folder_id=media.system_folder_id('generated_image'),
                                  source_task_id=tid)[0]
    target = c.post('/api/canvas/media/folders', json={'title': '当前'}).json['folder']
    for origin_form in ({'folder_id': target['id']}, {}):
        r = c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('purple')), '我的.png'), **origin_form})
        assert r.status_code == 200 and r.json['deduplicated']
        item = r.json['media']
        assert item['id'] == generated and item['folder_id'] == media.system_folder_id('generated_image')
        assert item['origin'] == 'generated' and item['name'] == '结果.png' and item['source_task_id'] == tid
    row = media.get_media(generated)
    assert row['folder_id'] == media.system_folder_id('generated_image') and row['origin'] == 'generated'
