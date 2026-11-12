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


def test_new_project_api_has_five_defaults_and_persistent_marker():
    client = application.app.test_client()
    response = client.post('/api/canvas/projects', json={'title':'new'})
    assert response.status_code == 201
    pid = response.json['project']['id']
    result = client.get(f'/api/canvas/projects/{pid}/folders').json['folders']
    assert [(f['title'],f['icon']) for f in result] == list(folders.DEFAULT_FOLDERS)
    assert all(f['parent_id'] is None for f in result)
    assert marker(pid)
    store.init_canvas_db()
    assert folders.list_folders(pid) == result


def test_existing_project_only_fills_missing_roots_preserves_metadata():
    pid = legacy_project()
    root = folders.save_folder(pid, {'title':'角色','icon':'style'})
    # Existing duplicates and nested names are user-owned and never rewritten.
    duplicate = folders.save_folder(pid, {'title':'角色','icon':'prop'})
    nested = folders.save_folder(pid, {'title':'音效','parent_id':root['id'],'icon':'scene'})
    parent = folders.save_folder(pid, {'title':'custom'})
    from test_canvas_library_folders import image_bytes
    asset = store.save_asset(pid, io.BytesIO(image_bytes('red')), 'existing.png', library=True)
    folders.edit_asset(pid, asset['id'], {'folder_id':nested['id']})
    asset_before = store.get_asset(pid, asset['id'], library=True)
    before = folders.list_folders(pid)
    store.init_canvas_db()
    assert store.get_asset(pid, asset['id'], library=True) == asset_before
    assert folders.placements(pid)[asset['id']] == nested['id']
    assert store.asset_path(asset_before).read_bytes() == image_bytes('red')
    result = folders.list_folders(pid)
    assert all(folders.folder(pid, item['id']) == item for item in before)
    assert len(result) == len(before) + 4
    assert sum(f['title']=='音效' and f['parent_id'] is None for f in result) == 1
    assert {f['title'] for f in result if f['parent_id'] is None} >= {t for t,_ in folders.DEFAULT_FOLDERS}
    assert marker(pid)
    store.init_canvas_db()
    assert folders.list_folders(pid) == result


def test_deleted_renamed_and_moved_defaults_are_never_recreated():
    pid = store.create_project('new')['id']
    rows = folders.list_folders(pid)
    folders.delete_folder(pid, rows[0]['id'])
    folders.save_folder(pid, {'title':'my people'}, rows[1]['id'])
    folders.save_folder(pid, {'parent_id':rows[1]['id']}, rows[2]['id'])
    before = folders.list_folders(pid)
    store.init_canvas_db()
    folders.ensure_default_folders(pid)
    assert folders.list_folders(pid) == before
    assert marker(pid)


def test_archived_old_project_is_not_initialized():
    pid = legacy_project()
    with tasks.get_db() as db:
        db.execute('INSERT INTO canvas_deletions VALUES (?,?,?,0)', ('project', pid, '{}'))
    store.init_canvas_db()
    assert marker(pid) is None
    assert tasks.get_db().execute('SELECT 1 FROM canvas_library_folders WHERE project_id=?', (pid,)).fetchone() is None


@pytest.mark.parametrize('new_project', [False, True])
def test_seed_failure_rolls_back_and_can_retry(monkeypatch, new_project):
    pid = None if new_project else legacy_project()
    original = folders.save_folder
    calls = []
    def fail_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('synthetic seed failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(folders, 'save_folder', fail_second)
    with pytest.raises(RuntimeError):
        store.create_project('new') if new_project else folders.ensure_default_folders(pid)
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_library_folders').fetchone()[0] == 0
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_library_folder_defaults').fetchone()[0] == 0
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_projects').fetchone()[0] == (0 if new_project else 1)
    monkeypatch.setattr(folders, 'save_folder', original)
    if new_project:
        pid = store.create_project('retry')['id']
    else:
        folders.ensure_default_folders(pid)
    assert len(folders.list_folders(pid)) == 5 and marker(pid)


def test_concurrent_seed_is_once():
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
    assert len(folders.list_folders(pid)) == 5
    assert marker(pid)


def test_new_project_seed_obeys_outer_transaction():
    with pytest.raises(RuntimeError):
        with store.write_transaction():
            pid = store.create_project('rollback')['id']
            assert marker(pid) and len(folders.list_folders(pid)) == 5
            raise RuntimeError('caller rollback')
    for table in ('canvas_projects','canvas_library_folders','canvas_library_folder_icons','canvas_library_folder_defaults'):
        assert tasks.get_db().execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
