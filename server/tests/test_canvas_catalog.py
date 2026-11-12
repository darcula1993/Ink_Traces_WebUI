import io
from pathlib import Path
import pytest
import app as application
import canvas_store as store
import canvas_catalog as catalog
import tasks
import storage
from test_canvas_library_folders import image_bytes


def setup():
    p = store.create_project('first')['id']
    w = store.create_workflow(p,'canvas')['id']
    return application.app.test_client(), p, w


def upload(client,p,color='red',workflow=False):
    url = f'/api/canvas/workflows/{p}/assets' if workflow else f'/api/canvas/projects/{p}/assets'
    r = client.post(url,data={'file':(io.BytesIO(image_bytes(color)),'sample.png')})
    assert r.status_code == 201, r.json
    return r.json['asset']


def listing(client,p,source='saved',**kwargs):
    response = client.get('/api/canvas/library/items',query_string={'project_id':p,'scope':'project','source':source,**kwargs})
    assert response.status_code == 200, response.json
    return response.json


def task_outputs(workflow=None,count=2):
    tid = tasks.create_task('image','searchable prompt', {'canvas_workflow_id':workflow} if workflow else {},status='succeeded')
    directory = Path(storage.OUTPUT_DIR)/str(tid)
    directory.mkdir(parents=True)
    tasks.update_task(tid,output_dir=str(directory))
    for i in range(count):
        path = directory/f'image{i}.png'
        path.write_bytes(image_bytes(['red','blue','green'][i]))
        tasks.register_asset(tid,'output_image',str(path),'image/png')
    return tid,[{'source':'task','id':str(a['id'])} for a in tasks.list_assets(tid)]


def test_sources_unknown_dedup_and_direct_workflow_upload():
    client,p,w = setup()
    old = store.save_asset(p,io.BytesIO(image_bytes('green')),'old.png',library=True)
    a = upload(client,p)
    wa = upload(client,w,'blue',workflow=True)
    uploaded = listing(client,p,'uploaded')
    assert {i['key'] for i in uploaded['items']} == {'library:'+a['id'],'workflow:'+wa['id']}
    saved = listing(client,p)
    assert len(saved['items']) == 1 and saved['items'][0]['origin_unknown']
    body = {'items':[{'source':'library','id':a['id']}]}
    response = client.post(f'/api/canvas/projects/{p}/library-items/save',json=body)
    assert response.status_code == 201 and response.json['assets'][0]['id']==a['id']
    assert listing(client,p)['total']==2
    assert listing(client,p,'uploaded')['total']==2
    item = next(i for i in listing(client,p)['items'] if i['asset']['id']==a['id'])
    assert item['origins']==['saved','uploaded'] and not item['origin_unknown']
    assert store.get_asset(p,old['id'],library=True)


def test_generated_multi_output_scope_counts_search_and_pagination():
    client,p,w=setup()
    tid, refs = task_outputs(w)
    task_outputs(None,1)
    result = listing(client,p,'generated',limit=1,q='searchable',kind='image')
    assert result['total']==2 and len(result['items'])==1
    assert result['source_counts']['generated']==2 and result['kind_counts']['image']==2
    assert result['items'][0]['task_id']==tid
    second=listing(client,p,'generated',limit=1,offset=1)
    assert second['items'][0]['key']!=result['items'][0]['key']
    assert listing(client,p,'generated',scope='all')['total']==3
    assert listing(client,p,'generated',kind='video')['total']==0
    assert listing(client,p,'generated',kind='video')['kind_counts']['image']==2
    tasks.move_tasks_to_trash([tid])
    assert listing(client,p,'generated')['total']==0


def test_cross_project_copy_source_remove_and_source_archive_preserves_target():
    client,p,w=setup()
    a=upload(client,p)
    target=store.create_project('target')['id']
    tw=store.create_workflow(target,'target')['id']
    selection={'source':'library','id':a['id']}
    response=client.post(f'/api/canvas/workflows/{tw}/library-references',json={'items':[selection,selection]})
    assert response.status_code==200
    assert len(response.json['assets'])==1
    copied=response.json['mapping']['library:'+a['id']]
    assert copied['id']!=a['id']
    # 2026-11-13: deleting a project asset from 本地素材 also deletes its canvas copies.
    assert client.delete('/api/canvas/library/items/library:'+a['id']).status_code==200
    assert listing(client,p,'uploaded')['total']==0
    assert client.get(copied['url']).status_code==404
    a=upload(client,p,'blue'); selection={'source':'library','id':a['id']}
    copied=client.post(f'/api/canvas/workflows/{tw}/library-references',json={'items':[selection]}).json['assets'][0]
    with tasks.get_db() as db:
        db.execute('INSERT INTO canvas_deletions VALUES (?,?,?,0)',('project',p,'{}'))
    assert client.get(copied['url']).status_code==200
    assert client.post(f'/api/canvas/workflows/{tw}/library-references',json={'items':[selection]}).status_code==404


def test_hidden_reupload_and_explicit_save_restore_catalog():
    client,p,w=setup()
    a=upload(client,p)
    key='library:'+a['id']
    client.delete('/api/canvas/library/items/'+key)
    # Permanent delete: a re-upload is a new asset (the old identity is gone).
    a=upload(client,p); key='library:'+a['id']
    assert listing(client,p,'uploaded')['total']==1
    wa=upload(client,w,workflow=True)
    client.delete('/api/canvas/library/items/'+key)
    response=client.post(f'/api/canvas/projects/{p}/library-items/save',json={'items':[{'source':'workflow','id':wa['id']}]})
    assert response.status_code==201
    assert listing(client,p)['total']==1
    assert client.get(a['url']).status_code==404  # deleted permanently, the save made a new asset


def test_tags_crud_assign_filter_and_isolation_from_folders():
    client,p,w=setup(); a=upload(client,p)
    initial=tasks.get_db().execute('SELECT count(*) FROM canvas_library_folders').fetchone()[0]
    tag=client.post('/api/canvas/library/tags',json={'title':'hero'}).json['tag']
    path='/api/canvas/library/items/library:'+a['id']+'/tags'
    assert client.patch(path,json={'tag_ids':[tag['id']]}).status_code==200
    assert listing(client,p,'uploaded',tag_id=tag['id'])['total']==1
    assert client.patch('/api/canvas/library/tags/'+tag['id'],json={'title':'renamed'}).status_code==200
    assert listing(client,p,'uploaded')['items'][0]['tags'][0]['title']=='renamed'
    assert client.post('/api/canvas/library/tags',json={'title':'renamed'}).status_code==409
    assert client.patch(path,json={'tag_ids':['missing']}).status_code==404
    assert client.delete('/api/canvas/library/tags/'+tag['id']).status_code==200
    assert listing(client,p,'uploaded')['items'][0]['tags']==[]
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_library_folders').fetchone()[0]==initial


def test_batch_failure_rolls_back_new_files_and_metadata():
    client,p,w=setup(); a=upload(client,p)
    target=store.create_project('target')['id']
    response=client.post(f'/api/canvas/projects/{target}/library-items/save',json={'items':[{'source':'library','id':a['id']},{'source':'library','id':'a'*32}]})
    assert response.status_code==404
    assert listing(client,target)['total']==0
    directory=store.asset_root()/'library'/target
    assert not directory.exists() or list(directory.iterdir())==[]


def test_task_single_output_import_download_and_cannot_direct_delete():
    client,p,w=setup(); tid,refs=task_outputs()
    response=client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':[refs[0]]})
    assert response.status_code==200 and len(response.json['assets'])==1
    key='task:'+refs[0]['id']
    assert client.get('/api/canvas/library/items/'+key+'/download').data==image_bytes('red')
    assert client.delete('/api/canvas/library/items/'+key).status_code==409
    assert tasks.get_task(tid)['deleted_at'] is None
    tasks.move_tasks_to_trash([tid])
    assert client.get(response.json['assets'][0]['url']).data==image_bytes('red')


@pytest.mark.parametrize('query',[{'scope':'bad'},{'source':'bad'},{'kind':'bad'},{'limit':101},{'offset':-1},{'scope':'all','folder_id':'x'}])
def test_invalid_filters(query):
    client,p,w=setup()
    assert client.get('/api/canvas/library/items',query_string={'project_id':p,**query}).status_code==400


def test_no_login_or_client_paths_are_authorized(monkeypatch):
    client,p,w=setup()
    assert client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':[{'source':'task','id':'../secret'}]}).status_code==400
    monkeypatch.setattr(application,'AUTH_CONFIG',{'username':'test','password':'test'})
    assert client.get('/api/canvas/library/items?scope=all').status_code==401


def test_legacy_save_origin_and_hidden_list_compatibility():
    client,p,w=setup(); a=upload(client,w,workflow=True)
    response=client.post(f'/api/canvas/projects/{p}/assets/from-workflow',json={'workflow_id':w,'asset_id':a['id']})
    assert response.status_code==201
    asset=response.json['asset']
    assert listing(client,p)['items'][0]['origins']==['saved']
    client.delete('/api/canvas/library/items/library:'+asset['id'])
    assert client.get(f'/api/canvas/projects/{p}/assets').json['assets']==[]
    client.delete('/api/canvas/library/items/workflow:'+a['id'])
    assert client.get(a['url']).status_code==404  # 2026-11-13: direct canvas uploads are deleted too
    assert upload(client,w,workflow=True)['id']!=a['id']
    assert listing(client,p,'uploaded')['total']==1


@pytest.mark.parametrize('damage',['missing','symlink','outside'])
def test_task_file_safety(damage,tmp_path):
    client,p,w=setup(); tid,refs=task_outputs(count=1)
    row=tasks.list_assets(tid)[0]; path=Path(row['path'])
    if damage=='missing': path.unlink()
    elif damage=='symlink':
        path.unlink(); other=tmp_path/'other.png'; other.write_bytes(image_bytes('red')); path.symlink_to(other)
    else:
        other=tmp_path/'outside.png'; other.write_bytes(image_bytes('red'))
        tasks.get_db().execute('UPDATE task_assets SET path=? WHERE id=?',(str(other),row['id'])); tasks.get_db().commit()
    assert client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':refs}).status_code==409
    result=listing(client,p,'generated',scope='all')
    assert result['total']==1 and result['items'][0]['available'] is False


def test_import_rechecks_source_after_archive_before_lock(monkeypatch):
    from contextlib import contextmanager
    client,p,w=setup(); a=upload(client,p)
    target=store.create_project('target')['id']; tw=store.create_workflow(target,'target')['id']
    original=store.write_transaction
    @contextmanager
    def archive_first():
        db=tasks.get_db()
        if not db.in_transaction:
            db.execute('INSERT OR IGNORE INTO canvas_deletions VALUES (?,?,?,0)',('project',p,'{}')); db.commit()
        with original() as locked:
            yield locked
    monkeypatch.setattr(store,'write_transaction',archive_first)
    response=client.post(f'/api/canvas/workflows/{tw}/library-references',json={'items':[{'source':'library','id':a['id']}]})
    assert response.status_code==404
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_assets WHERE workflow_id=?',(tw,)).fetchone()[0]==0


def test_save_invalid_folder_rolls_back_and_preserves_existing_dedup():
    client,p,w=setup(); a=upload(client,p)
    response=client.post(f'/api/canvas/projects/{p}/library-items/save',json={'items':[{'source':'library','id':a['id']}],'folder_id':'missing'})
    assert response.status_code==404
    assert listing(client,p)['total']==0
    assert client.get(a['url']).data==image_bytes('red')


def test_sql_pagination_never_loads_task_details_or_stats_off_page(monkeypatch):
    client,p,w=setup()
    for _ in range(12): task_outputs(w,count=1)
    monkeypatch.setattr(tasks,'get_task',lambda *a,**k: (_ for _ in ()).throw(AssertionError('full task loading forbidden')))
    original=Path.is_file
    checked=[]
    def count(path):
        checked.append(path)
        return original(path)
    monkeypatch.setattr(Path,'is_file',count)
    result=listing(client,p,'generated',limit=2,offset=4)
    assert result['total']==12 and len(result['items'])==2
    assert len(checked)==2


def test_missing_library_asset_can_be_removed_and_thumbnail_is_local():
    client,p,w=setup(); a=upload(client,p)
    item=listing(client,p,'uploaded')['items'][0]
    thumb=client.get(item['thumbnail_url'])
    assert thumb.status_code==200 and thumb.mimetype=='image/webp'
    path=store.asset_path(store.get_asset(p,a['id'],library=True)); path.unlink()
    assert listing(client,p,'uploaded')['items'][0]['available'] is False
    assert client.delete('/api/canvas/library/items/library:'+a['id']).status_code==200
    assert listing(client,p,'uploaded')['total']==0


def test_folder_root_scope_and_archived_task_filter():
    import canvas_library_folders as folders
    client,p,w=setup(); a=upload(client,p); upload(client,w,'blue',workflow=True)
    folder=folders.list_folders(p)[0]
    folders.edit_asset(p,a['id'],{'folder_id':folder['id']})
    assert listing(client,p,'uploaded',folder_id='')['total']==1
    assert listing(client,p,'uploaded',folder_id=folder['id'])['total']==1
    task_outputs(w,count=1)
    with tasks.get_db() as db:
        db.execute('INSERT INTO canvas_deletions VALUES (?,?,?,0)',('project',p,'{}'))
    assert listing(client,p,'generated',scope='all')['total']==0


def test_same_hash_other_project_hide_is_independent():
    client,p,w=setup(); a=upload(client,p)
    other=store.create_project('other')['id']; b=upload(client,other)
    client.delete('/api/canvas/library/items/library:'+a['id'])
    assert listing(client,other,'uploaded')['items'][0]['asset']['id']==b['id']
    assert client.get(b['url']).data==image_bytes('red')


def test_registered_task_thumbnail_returned_without_full_task_details(monkeypatch):
    client,p,w=setup(); tid,refs=task_outputs(w,count=1)
    path=Path(storage.OUTPUT_DIR)/str(tid)/'thumb.webp'
    path.write_bytes(image_bytes('blue'))
    tasks.register_asset(tid,'output_thumbnail',str(path),'image/webp')
    url=f'/api/tasks/{tid}/file/thumb.webp'
    tasks.update_task(tid,result={'local_thumbnails':[url]})
    monkeypatch.setattr(tasks,'get_task',lambda *a,**k: (_ for _ in ()).throw(AssertionError('no details')))
    assert listing(client,p,'generated')['items'][0]['thumbnail_url']==url
    tasks.update_task(tid,result={'local_thumbnails':['https://remote.invalid/private']})
    assert listing(client,p,'generated')['items'][0]['thumbnail_url'].startswith('/api/canvas/library/items/')
