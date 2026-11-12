import copy
import io

from PIL import Image
import pytest
import app as application
import canvas_store as store


def image_bytes(color):
    b = io.BytesIO(); Image.new('RGB', (20, 20), color).save(b, format='PNG'); return b.getvalue()


def setup():
    client = application.app.test_client()
    project = store.create_project('project')
    return client, project['id'], f"/api/canvas/projects/{project['id']}"


def test_folder_tree_moves_nonempty_and_project_isolation():
    client, pid, base = setup()
    a = client.post(base+'/folders', json={'title': 'A'}).json['folder']
    b = client.post(base+'/folders', json={'title': 'B', 'parent_id': a['id']}).json['folder']
    c = client.post(base+'/folders', json={'title': 'C', 'parent_id': b['id']}).json['folder']
    assert client.patch(base+'/folders/'+a['id'], json={'parent_id': c['id']}).status_code == 409
    assert client.delete(base+'/folders/'+a['id']).status_code == 409
    _, _, foreign = setup()
    assert client.post(foreign+'/folders', json={'title': 'bad', 'parent_id': a['id']}).status_code == 404
    assert client.patch(foreign+'/folders/'+a['id'], json={'title': 'bad'}).status_code == 404
    assert client.delete(foreign+'/folders/'+a['id']).status_code == 404
    moved = client.patch(base+'/folders/'+c['id'], json={'parent_id': None, 'title': 'C-root'}).json['folder']
    assert moved['parent_id'] is None and moved['title'] == 'C-root'
    assert client.delete(base+'/folders/'+b['id']).status_code == 200
    assert {f['id'] for f in client.get(base+'/folders').json['folders'] if f['title'] in {'A', 'B', 'C-root'}} == {a['id'], c['id']}


def test_asset_upload_rename_move_and_snapshot_preserved():
    client, pid, base = setup()
    folder = client.post(base+'/folders', json={'title': 'Images'}).json['folder']
    response = client.post(base+'/assets', data={'file': (io.BytesIO(image_bytes('red')), 'original.png'), 'folder_id': folder['id']})
    assert response.status_code == 201
    asset = response.json['asset']
    assert set(asset) == {'id','name','mime_type','kind','size_bytes','url'}
    assert client.delete(base+'/folders/'+folder['id']).status_code == 409
    wf = store.create_workflow(pid, 'workflow')
    snapshot = client.post(f"/api/canvas/workflows/{wf['id']}/reference-assets", json={'asset_ids':[asset['id']]}).json['assets'][0]
    response = client.patch(base+'/assets/'+asset['id'], json={'name': 'renamed.png', 'folder_id': None})
    assert response.status_code == 200 and response.json['asset']['name'] == 'renamed.png'
    assert set(response.json['asset']) == set(asset)
    assert store.get_asset(wf['id'], snapshot['id'])['name'] == 'original.png'
    assert client.get(base+'/assets?folder_id=').json['assets'][0]['id'] == asset['id']
    assert client.get(base+'/assets?folder_id='+folder['id']).json['assets'] == []
    assert client.get(base+'/assets').json['placements'][asset['id']] is None
    assert client.delete(base+'/folders/'+folder['id']).status_code == 200
    _, _, foreign = setup()
    assert client.patch(foreign+'/assets/'+asset['id'], json={'name':'wrong'}).status_code == 404


def test_image_asset_history_and_invalid_candidates():
    _, pid, _ = setup()
    wf = store.create_workflow(pid, 'history')
    a,b = [store.save_asset(wf['id'], io.BytesIO(image_bytes(c)), c+'.png') for c in ('red','blue')]
    doc = copy.deepcopy(wf['document'])
    doc['nodes'] = [{'id':'a','type':'asset','title':'history','x':0,'y':0,'asset':b,'selectedCandidateId':b['id'],'candidates':[a,b],'params':{},'task':None}]
    saved = store.update_workflow(wf['id'], 'history', doc, 1)
    assert saved['document'] == doc
    doc['nodes'][0].update(asset=a, selectedCandidateId=a['id'])
    store.update_workflow(wf['id'], 'history', doc, 2)
    for invalid in ([a,a], [a]*101, []):
        doc['nodes'][0]['candidates'] = invalid
        with pytest.raises(store.CanvasError): store.validate_document(doc, wf['id'])


def test_archived_project_hides_tree_and_blocks_folder_writes():
    import tasks
    client, pid, base = setup()
    folder = client.post(base+'/folders', json={'title':'kept'}).json['folder']
    wf = store.create_workflow(pid, 'archived')
    db = tasks.get_db()
    db.execute('INSERT INTO canvas_deletions VALUES (?,?,?,0)', ('project',pid,'{}'))
    db.commit()
    assert client.get(base+'/folders').status_code == 404
    assert client.post(base+'/folders', json={'title':'new'}).status_code == 404
    assert client.patch(base+'/folders/'+folder['id'], json={'title':'change'}).status_code == 404
    assert client.delete(base+'/folders/'+folder['id']).status_code == 404
    assert client.get(f"/api/canvas/workflows/{wf['id']}").status_code == 404
    assert all(p['id'] != pid for p in store.list_projects())


@pytest.mark.parametrize('operation', ['workflow_create', 'workflow_update', 'upload', 'folder_create', 'group_create'])
def test_write_rechecks_archive_after_initial_lookup(monkeypatch, operation):
    from contextlib import contextmanager
    import tasks
    import canvas_library
    import canvas_library_folders
    _, pid, _ = setup()
    initial_folders = canvas_library_folders.list_folders(pid)
    wf = store.create_workflow(pid, 'before')
    asset = store.save_asset(pid, io.BytesIO(image_bytes('green')), 'green.png', library=True)
    real_transaction = store.write_transaction
    @contextmanager
    def archive_before_lock():
        db = tasks.get_db()
        db.execute('INSERT OR IGNORE INTO canvas_deletions VALUES (?,?,?,0)', ('project',pid,'{}'))
        db.commit()
        with real_transaction() as locked:
            yield locked
    monkeypatch.setattr(store, 'write_transaction', archive_before_lock)
    operations = {
        'workflow_create': lambda: store.create_workflow(pid, 'too late'),
        'workflow_update': lambda: store.update_workflow(wf['id'], 'too late', wf['document'], 1),
        'upload': lambda: store.save_asset(wf['id'], io.BytesIO(image_bytes('red')), 'red.png'),
        'folder_create': lambda: canvas_library_folders.save_folder(pid, {'title':'too late'}),
        'group_create': lambda: canvas_library.save_group(pid, 'too late', [asset['id']]),
    }
    with pytest.raises(store.CanvasError): operations[operation]()
    db = tasks.get_db()
    assert db.execute('SELECT revision FROM canvas_workflows WHERE id=?',(wf['id'],)).fetchone()[0] == 1
    assert db.execute('SELECT COUNT(*) FROM canvas_assets WHERE workflow_id=?',(wf['id'],)).fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM canvas_library_folders WHERE project_id=?',(pid,)).fetchone()[0] == len(initial_folders)
    assert db.execute('SELECT COUNT(*) FROM canvas_asset_groups WHERE project_id=?',(pid,)).fetchone()[0] == 0


def test_nested_folder_write_does_not_commit_outer_transaction():
    import tasks
    import canvas_library_folders
    _, pid, _ = setup()
    initial_folders = canvas_library_folders.list_folders(pid)
    with pytest.raises(RuntimeError):
        with store.write_transaction():
            canvas_library_folders.save_folder(pid, {'title':'rolled back'})
            assert tasks.get_db().in_transaction
            raise RuntimeError('abort outer operation')
    assert canvas_library_folders.list_folders(pid) == initial_folders


def test_pending_cleaned_library_asset_hidden_but_retained_media_stays_readable():
    import json
    import tasks
    client, pid, base = setup()
    asset = store.save_asset(pid, io.BytesIO(image_bytes('red')), 'red.png', library=True)
    db = tasks.get_db()
    db.execute('INSERT INTO canvas_deletions VALUES (?,?,?,0)', ('workflow','old-workflow',json.dumps({'removed_library_ids':[asset['id']]})))
    db.commit()
    assert client.get(base+'/assets').json['assets'] == []
    assert client.get(asset['url']).status_code == 404
    assert client.patch(base+'/assets/'+asset['id'], json={'name':'late.png'}).status_code == 404
    other = store.save_asset(pid, io.BytesIO(image_bytes('blue')), 'blue.png', library=True)
    db = tasks.get_db()
    db.execute('INSERT INTO canvas_deletions VALUES (?,?,?,0)', ('project',pid,'{}')); db.commit()
    assert client.get(other['url']).status_code == 200
    with pytest.raises(store.CanvasError): store.get_asset(pid,other['id'],library=True)


def test_upload_placement_failure_rolls_back_new_file_only(monkeypatch):
    import tasks
    import canvas_library_folders
    client, pid, base = setup()
    kept = store.save_asset(pid, io.BytesIO(image_bytes('blue')), 'kept.png', library=True)
    kept_path = store.asset_path(store.get_asset(pid, kept['id'], library=True))
    before = set(store.asset_root().rglob('*'))
    def failure(*args, **kwargs):
        raise store.CanvasError('synthetic placement failure')
    monkeypatch.setattr(canvas_library_folders, 'edit_asset', failure)
    for color in ('red', 'blue'):
        response = client.post(base+'/assets', data={'file':(io.BytesIO(image_bytes(color)),color+'.png'),'folder_id':''})
        assert response.status_code == 400
        assert kept_path.read_bytes() == image_bytes('blue')
        assert tasks.get_db().execute('SELECT COUNT(*) FROM canvas_library_assets WHERE project_id=?',(pid,)).fetchone()[0] == 1
        assert set(store.asset_root().rglob('*')) == before


def test_outer_copy_failure_removes_only_new_destination_files():
    import tasks
    import canvas_library
    _, pid, _ = setup()
    wf = store.create_workflow(pid, 'destination')
    first = store.save_asset(pid, io.BytesIO(image_bytes('red')), 'red.png', library=True)
    source = store.get_asset(pid, first['id'], library=True)
    with pytest.raises(RuntimeError):
        with store.write_transaction():
            copied = canvas_library.copy_asset(source, wf['id'])
            assert store.asset_path(store.get_asset(wf['id'], copied['id'])).is_file()
            raise RuntimeError('next copy failed')
    assert tasks.get_db().execute('SELECT COUNT(*) FROM canvas_assets WHERE workflow_id=?',(wf['id'],)).fetchone()[0] == 0
    assert list((store.asset_root()/wf['id']).glob('*')) == []
    assert store.asset_path(source).read_bytes() == image_bytes('red')
