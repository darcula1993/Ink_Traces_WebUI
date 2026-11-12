import io
import zipfile

import pytest
import tasks
import canvas_store as store
import canvas_library_folders as folders
from test_canvas_library_folders import setup, image_bytes


@pytest.mark.parametrize('rating', [0, 1, 5, 'missing'])
def test_rating_round_trip(rating):
    client, pid, _ = setup()
    wf = store.create_workflow(pid, 'rating')
    document = wf['document']
    node = {'id':'n', 'type':'image', 'x':0, 'y':0, 'params':{}}
    if rating != 'missing':
        node['rating'] = rating
    document['nodes'] = [node]
    response = client.put('/api/canvas/workflows/'+wf['id'], json={'title':'rating', 'document':document, 'revision':1})
    assert response.status_code == 200
    saved = client.get('/api/canvas/workflows/'+wf['id']).json['workflow']['document']['nodes'][0]
    assert saved == node


@pytest.mark.parametrize('rating', [-1, 6, 1.0, True, False, None, '3', [], {}])
def test_rating_rejects_invalid(rating):
    _, pid, _ = setup()
    wf = store.create_workflow(pid, 'rating')
    doc = wf['document']
    doc['nodes'] = [{'id':'n', 'type':'image', 'x':0, 'y':0, 'rating':rating}]
    with pytest.raises(store.CanvasError, match='评级'):
        store.update_workflow(wf['id'], 'rating', doc, 1)


def test_icons_legacy_rows_and_crud():
    client, pid, base = setup()
    db = tasks.get_db()
    db.execute('INSERT INTO canvas_library_folders VALUES (?,?,?,?,?,?)', ('legacy', pid, 'legacy', None, tasks.utcnow(), tasks.utcnow()))
    db.commit()
    assert next(f for f in client.get(base+'/folders').json['folders'] if f['id'] == 'legacy')['icon'] == 'folder'
    for icon in sorted(folders.ICONS):
        response = client.patch(base+'/folders/legacy', json={'icon':icon})
        assert response.status_code == 200 and response.json['folder']['icon'] == icon
    for icon in ['bad', None, [], 1]:
        assert client.patch(base+'/folders/legacy', json={'icon':icon}).status_code == 400
    assert client.delete(base+'/folders/legacy').status_code == 200
    assert tasks.get_db().execute("SELECT * FROM canvas_library_folder_icons WHERE folder_id='legacy'").fetchone() is None


def upload(client, base, folder, name='same.png', color='red'):
    return client.post(base+'/assets', data={'file':(io.BytesIO(image_bytes(color)), name), 'folder_id':folder['id']}).json['asset']


def test_recursive_archive_safe_unique_empty_and_isolation():
    client, pid, base = setup()
    root = folders.save_folder(pid, {'title':'../root\\name'})
    child = folders.save_folder(pid, {'title':'nested', 'parent_id':root['id']})
    folders.save_folder(pid, {'title':'nested', 'parent_id':root['id']})
    upload(client, base, root)
    upload(client, base, root, color='blue')
    upload(client, base, child, name='inner.png', color='green')
    response = client.get(base+'/folders/'+root['id']+'/download')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names)) == 6
        assert all(not n.startswith('/') and '\\' not in n and '..' not in n.split('/') for n in names)
        assert sum(n.endswith('/') for n in names) == 3
        assert sum(n.endswith('.png') for n in names) == 3
        assert archive.testzip() is None
    response.close()
    _, _, other = setup()
    assert client.get(other+'/folders/'+root['id']+'/download').status_code == 404
    empty = folders.save_folder(pid, {'title':'empty'})
    response = client.get(base+'/folders/'+empty['id']+'/download')
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.namelist() == ['empty/']


@pytest.mark.parametrize('damage', ['missing', 'traversal', 'symlink'])
def test_archive_rejects_missing_and_unsafe_files(damage, tmp_path):
    client, pid, base = setup()
    root = folders.save_folder(pid, {'title':'root'})
    asset = upload(client, base, root)
    row = store.get_asset(pid, asset['id'], library=True)
    path = store.asset_path(row)
    if damage == 'missing':
        path.unlink()
    elif damage == 'traversal':
        tasks.get_db().execute('UPDATE canvas_library_assets SET filename=? WHERE id=?', ('../../outside.png', asset['id']))
        tasks.get_db().commit()
    else:
        path.unlink()
        outside = tmp_path/'outside.png'
        outside.write_bytes(image_bytes('red'))
        path.symlink_to(outside)
    response = client.get(base+'/folders/'+root['id']+'/download')
    assert response.status_code == 409 and response.is_json


def test_archive_temp_closed_and_removed_assets_filtered(monkeypatch):
    import canvas_library_download as download
    import canvas_cleanup
    client, pid, base = setup()
    root = folders.save_folder(pid, {'title':'root'})
    asset = upload(client, base, root)
    monkeypatch.setattr(canvas_cleanup, 'is_library_asset_deleted', lambda aid: aid == asset['id'])
    created = []
    original = download.tempfile.SpooledTemporaryFile
    def tracked(*args, **kwargs):
        value = original(*args, **kwargs)
        created.append(value)
        return value
    monkeypatch.setattr(download.tempfile, 'SpooledTemporaryFile', tracked)
    response = client.get(base+'/folders/'+root['id']+'/download')
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.namelist() == ['root/']
    response.close()
    assert created[0].closed
    assert client.get(base+'/folders/missing/download').status_code == 404
    assert created[-1].closed
    monkeypatch.setattr(canvas_cleanup, 'is_deleted', lambda scope, ident: scope == 'project' and ident == pid)
    assert client.get(base+'/folders/'+root['id']+'/download').status_code == 404


def test_archive_rolls_to_disk_and_closes_after_mid_archive_failure(monkeypatch):
    import canvas_library_download as download
    client, pid, base = setup()
    root = folders.save_folder(pid, {'title':'root'})
    first = upload(client, base, root)
    upload(client, base, root, color='blue')
    created = []
    original = download.tempfile.SpooledTemporaryFile
    def tracked(*args, **kwargs):
        kwargs['max_size'] = 1
        value = original(*args, **kwargs)
        created.append(value)
        return value
    monkeypatch.setattr(download.tempfile, 'SpooledTemporaryFile', tracked)
    response = client.get(base+'/folders/'+root['id']+'/download')
    assert response.status_code == 200 and created[-1]._rolled
    response.close()
    assert created[-1].closed
    original_write = download.shutil.copyfileobj
    calls = []
    def failing_write(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError('synthetic read failure')
        return original_write(*args, **kwargs)
    monkeypatch.setattr(download.shutil, 'copyfileobj', failing_write)
    response = client.get(base+'/folders/'+root['id']+'/download')
    assert response.status_code == 409 and response.is_json
    assert created[-1].closed
    assert store.asset_path(store.get_asset(pid, first['id'], library=True)).is_file()
    assert not tasks.get_db().in_transaction


def test_archive_media_io_does_not_block_other_database_writers(monkeypatch):
    import sqlite3
    import canvas_library_download as download
    client, pid, base = setup()
    root = folders.save_folder(pid, {'title':'root'})
    upload(client, base, root)
    original = download.shutil.copyfileobj
    writes = []
    def concurrent_write(*args, **kwargs):
        assert not tasks.get_db().in_transaction
        with sqlite3.connect(tasks.DB_PATH, timeout=0.1) as other:
            other.execute('UPDATE canvas_projects SET title=? WHERE id=?', ('concurrent writer', pid))
        writes.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(download.shutil, 'copyfileobj', concurrent_write)
    response = client.get(base+'/folders/'+root['id']+'/download')
    assert response.status_code == 200 and writes == [True]
    assert store.get_project(pid)['title'] == 'concurrent writer'
    response.close()


def test_archive_open_descriptor_survives_unlink(monkeypatch):
    import canvas_library_download as download
    client, pid, base = setup()
    root = folders.save_folder(pid, {'title':'root'})
    asset = upload(client, base, root)
    path = store.asset_path(store.get_asset(pid, asset['id'], library=True))
    expected = path.read_bytes()
    original = download.shutil.copyfileobj
    def unlink_after_open(*args, **kwargs):
        path.unlink()
        return original(*args, **kwargs)
    monkeypatch.setattr(download.shutil, 'copyfileobj', unlink_after_open)
    response = client.get(base+'/folders/'+root['id']+'/download')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.read('root/same.png') == expected
    response.close()
