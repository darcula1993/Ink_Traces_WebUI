"""LIBRARY-GLOBAL-20261116 S6b: new projects no longer get project folders (the global media
library seeds its own defaults once); existing project folders are never touched."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid
import io

import pytest
import app as application
import canvas_store as store
import canvas_library_folders as folders
import tasks


def legacy_project():
    ident, now = uuid.uuid4().hex, tasks.utcnow()
    with tasks.get_db() as db:
        db.execute('INSERT INTO canvas_projects VALUES (?,?,?,?)', (ident, 'legacy', now, now))
    return ident


def marker(pid):
    return tasks.get_db().execute('SELECT * FROM canvas_library_folder_defaults WHERE project_id=?', (pid,)).fetchone()


def test_new_project_api_creates_no_project_folders_and_stays_empty_after_restart():
    client = application.app.test_client()
    response = client.post('/api/canvas/projects', json={'title': 'new'})
    assert response.status_code == 201
    pid = response.json['project']['id']
    assert client.get(f'/api/canvas/projects/{pid}/folders').json['folders'] == []
    assert marker(pid)
    store.init_canvas_db()  # startup backfill must not seed the new project either
    assert folders.list_folders(pid) == []
    # Global media library defaults are unaffected (seeded once by media_schema).
    titles = {f['title'] for f in client.get('/api/canvas/media/folders').json['folders'] if f['parent_id'] is None}
    assert {'音效', '角色', '场景', '物品', '风格'} <= titles
    # Users may still create folders in old project libraries until S3/S4 retire them.
    assert client.post(f'/api/canvas/projects/{pid}/folders', json={'title': 'mine'}).status_code == 201


def test_existing_project_folders_and_placements_are_untouched():
    pid = legacy_project()
    root = folders.save_folder(pid, {'title': '角色', 'icon': 'style'})
    duplicate = folders.save_folder(pid, {'title': '角色', 'icon': 'prop'})
    nested = folders.save_folder(pid, {'title': '音效', 'parent_id': root['id'], 'icon': 'scene'})
    from test_canvas_library_folders import image_bytes
    asset = store.save_asset(pid, io.BytesIO(image_bytes('red')), 'existing.png', library=True)
    folders.edit_asset(pid, asset['id'], {'folder_id': nested['id']})
    asset_before = store.get_asset(pid, asset['id'], library=True)
    before = folders.list_folders(pid)
    assert {f['id'] for f in before} == {root['id'], duplicate['id'], nested['id']}
    store.init_canvas_db()
    assert store.get_asset(pid, asset['id'], library=True) == asset_before
    assert folders.placements(pid)[asset['id']] == nested['id']
    assert store.asset_path(asset_before).read_bytes() == image_bytes('red')
    assert folders.list_folders(pid) == before
    assert marker(pid)


def test_seeded_old_project_keeps_its_folders():
    pid = legacy_project()
    with tasks.get_db() as db:
        db.execute('INSERT INTO canvas_library_folder_defaults VALUES (?,?)', (pid, tasks.utcnow()))
    made = folders.save_folder(pid, {'title': '场景', 'icon': 'scene'})
    store.init_canvas_db()
    folders.ensure_default_folders(pid)
    assert [f['id'] for f in folders.list_folders(pid)] == [made['id']]


def test_archived_old_project_is_not_initialized():
    pid = legacy_project()
    with tasks.get_db() as db:
        db.execute('INSERT INTO canvas_deletions VALUES (?,?,?,0)', ('project', pid, '{}'))
    store.init_canvas_db()
    assert marker(pid) is None
    assert tasks.get_db().execute('SELECT 1 FROM canvas_library_folders WHERE project_id=?', (pid,)).fetchone() is None


def test_concurrent_marking_is_once_and_creates_nothing():
    pid, barrier = legacy_project(), Barrier(2)

    def run():
        try:
            barrier.wait(timeout=3)
            folders.ensure_default_folders(pid)
        finally:
            tasks.close_db()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run) for _ in range(2)]
        for future in futures:
            future.result(timeout=5)
    assert folders.list_folders(pid) == []
    assert marker(pid)


def test_new_project_marker_obeys_outer_transaction():
    with pytest.raises(RuntimeError):
        with store.write_transaction():
            pid = store.create_project('rollback')['id']
            assert marker(pid) and folders.list_folders(pid) == []
            raise RuntimeError('caller rollback')
    for table in ('canvas_projects', 'canvas_library_folders', 'canvas_library_folder_defaults'):
        assert tasks.get_db().execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
