import hashlib
from pathlib import Path
import pytest
import tasks
import storage
import canvas_store as store
import app as application
from test_canvas_catalog import setup, listing
from test_canvas_library_folders import image_bytes


def remote(provider='cupsy',status='active'):
    path=Path(storage.WORKSPACE_ASSET_DIR)/'cupsy_assets'/'sample.png'
    path.parent.mkdir(parents=True,exist_ok=True)
    data=image_bytes('red'); path.write_bytes(data)
    asset=tasks.create_provider_asset(provider,'image',hashlib.sha256(data).hexdigest(),'sample.png','image/png',len(data),str(path))
    tasks.update_provider_asset(asset['id'],status=status)
    return tasks.get_provider_asset(asset['id']),path


def test_remote_local_copy_and_save_survive_source_delete(monkeypatch):
    monkeypatch.setattr(application.HTTP,'get',lambda *a,**k:pytest.fail('network'))
    monkeypatch.setattr(application.HTTP,'post',lambda *a,**k:pytest.fail('network'))
    client,p,w=setup(); asset,path=remote()
    selection={'source':'cupsy','id':str(asset['id'])}
    r=client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':[selection,selection]})
    assert r.status_code==200 and len(r.json['assets'])==1
    copied=r.json['mapping']['cupsy:'+str(asset['id'])]
    saved=client.post(f'/api/canvas/projects/{p}/library-items/save',json={'items':[selection]})
    assert saved.status_code==201 and listing(client,p)['items'][0]['origins']==['saved']
    tasks.update_provider_asset(asset['id'],deleted_at=tasks.utcnow(),status='deleted'); path.unlink()
    assert client.get(copied['url']).data==image_bytes('red')
    assert client.get(saved.json['assets'][0]['url']).data==image_bytes('red')
    assert client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':[selection]}).status_code==404


@pytest.mark.parametrize('fault',['provider','processing','failed','deleted','missing','symlink','outside','kind','corrupt'])
def test_remote_unavailable_or_unsafe_refused(fault,tmp_path):
    client,p,w=setup(); asset,path=remote(provider='cupsy:profile:'+'a'*32+':1' if fault=='provider' else 'cupsy')
    if fault in ('processing','failed'): tasks.update_provider_asset(asset['id'],status=fault)
    if fault=='deleted': tasks.update_provider_asset(asset['id'],deleted_at=tasks.utcnow())
    if fault=='missing': path.unlink()
    if fault=='corrupt': path.write_bytes(b'not media')
    if fault=='symlink':
        path.unlink(); outside=tmp_path/'outside.png'; outside.write_bytes(image_bytes('red')); path.symlink_to(outside)
    if fault=='outside':
        outside=tmp_path/'outside.png'; outside.write_bytes(image_bytes('red'))
        tasks.get_db().execute('UPDATE provider_assets SET local_path=? WHERE id=?',(str(outside),asset['id'])); tasks.get_db().commit()
    if fault=='kind':
        tasks.get_db().execute("UPDATE provider_assets SET kind='audio' WHERE id=?",(asset['id'],)); tasks.get_db().commit()
    r=client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':[{'source':'cupsy','id':str(asset['id'])}]})
    assert r.status_code in (400,404,409),r.json
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_assets').fetchone()[0]==0


def test_remote_batch_rollback_and_no_delete_bypass():
    client,p,w=setup(); asset,path=remote()
    r=client.post(f'/api/canvas/projects/{p}/library-items/save',json={'items':[{'source':'cupsy','id':str(asset['id'])},{'source':'cupsy','id':'99999'}]})
    assert r.status_code==404 and listing(client,p)['total']==0
    target=store.asset_root()/'library'/p
    assert not target.exists() or list(target.iterdir())==[]
    assert path.is_file()
    assert client.delete('/api/canvas/library/items/cupsy:'+str(asset['id'])).status_code==409
    assert client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':[{'source':'cupsy','id':str(asset['id']),'url':'https://invalid'}]}).status_code==400


def test_remote_delete_race_rechecked_under_transfer_lock(monkeypatch):
    from contextlib import contextmanager
    client,p,w=setup(); asset,path=remote()
    original=store.write_transaction
    @contextmanager
    def delete_before_lock():
        if not tasks.get_db().in_transaction:
            tasks.update_provider_asset(asset['id'],deleted_at=tasks.utcnow())
        with original() as db:
            yield db
    monkeypatch.setattr(store,'write_transaction',delete_before_lock)
    response=client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':[{'source':'cupsy','id':str(asset['id'])}]})
    assert response.status_code==404
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_assets').fetchone()[0]==0


def test_remote_target_validation():
    client,p,w=setup(); asset,path=remote()
    assert client.post('/api/canvas/workflows/missing/library-references',json={'items':[{'source':'cupsy','id':str(asset['id'])}]}).status_code==404
    assert client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':[{'source':'cupsy','id':'9999999999999999999'}]}).status_code==400


def test_remote_filter_counts_pages_all_and_poll():
    client,p,w=setup()
    ids=[]
    for i,kind in enumerate(['image','image','video','audio']):
        asset=tasks.create_provider_asset('cupsy',kind,str(i)*64,'needle-'+str(i),'image/png',1,'/tmp/synthetic-'+str(i))
        tasks.update_provider_asset(asset['id'],status='active',external_asset_id='remote-'+str(i))
        ids.append(asset['id'])
    response=client.get('/api/cupsy/assets?kind=image&q=needle&limit=1').json
    assert response['total']==2 and len(response['assets'])==1 and response['has_more']
    assert response['kind_counts']=={'image':2,'video':1,'audio':1}
    second=client.get('/api/cupsy/assets?kind=image&q=needle&limit=1&offset=1').json
    assert not second['has_more'] and second['assets'][0]['id']!=response['assets'][0]['id']
    assert len(client.get('/api/cupsy/assets?kind=image&q=needle').json['assets'])==2
    assert client.get('/api/cupsy/assets?q=remote-2').json['total']==1
    assert client.get('/api/cupsy/assets?q=%25').json['total']==0
    poll=client.get('/api/cupsy/assets',query_string={'ids':str(ids[0]),'kind':'video','q':'not-found'}).json
    assert poll['assets'][0]['id']==ids[0] and poll['missing_ids']==[]
    assert client.get('/api/cupsy/assets?kind=invalid').status_code==400
