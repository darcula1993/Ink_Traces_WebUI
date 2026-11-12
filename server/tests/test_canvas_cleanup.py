import io
from PIL import Image
import pytest
import canvas_store as store
import canvas_cleanup as cleanup


def fixture():
    project = store.create_project('cleanup')
    workflow = store.create_workflow(project['id'], 'workflow')
    data = io.BytesIO(); Image.new('RGB',(16,16),'red').save(data,'PNG'); data.seek(0)
    asset = store.save_asset(workflow['id'],data,'red.png')
    path = store.asset_path(store.get_asset(workflow['id'],asset['id']))
    return project, workflow, asset, path


def test_archive_keeps_files_and_manifest():
    _, workflow, _, path = fixture()
    result = cleanup.delete_scope('workflow',workflow['id'])
    assert result['deleted'] and path.exists()
    assert cleanup.is_deleted('workflow',workflow['id'])
    assert cleanup.delete_scope('workflow',workflow['id']) == result


def test_cleanup_removes_only_associated_file():
    _, workflow, _, path = fixture()
    _, _, _, other = fixture()
    # A shared content copy must remain protected even across projects.
    result = cleanup.delete_scope('workflow',workflow['id'],True)
    assert path.exists() and other.exists() and result['retained_shared'] == 1


def test_cleanup_option_validation():
    _, workflow, _, path = fixture()
    with pytest.raises(store.CanvasError): cleanup.delete_scope('workflow',workflow['id'],'true')
    assert path.exists()


def test_unique_file_is_removed_and_retry_is_idempotent():
    _, workflow, _, path = fixture()
    result=cleanup.delete_scope('workflow',workflow['id'],True)
    assert not path.exists() and result['removed_files']==1
    assert cleanup.delete_scope('workflow',workflow['id'],True)==result


def test_retained_archive_protects_shared_copy():
    _, first, _, path=fixture()
    cleanup.delete_scope('workflow',first['id'],False)
    _, second, _, second_path=fixture()
    assert cleanup.delete_scope('workflow',second['id'],True)['retained_shared']==1
    assert path.exists() and second_path.exists()


def test_workspace_reference_protects_file():
    import tasks
    _, workflow, _, path=fixture()
    tasks.get_db().execute("INSERT INTO workspace_state(key,value,updated_at) VALUES('test',?,'now')", ('{"url":"'+str(path)+'"}',)); tasks.get_db().commit()
    assert cleanup.delete_scope('workflow',workflow['id'],True)['retained_shared']==1
    assert path.exists()


def test_failed_unlink_has_retry_manifest(monkeypatch):
    from pathlib import Path
    _, workflow, _, path=fixture()
    original=Path.unlink
    monkeypatch.setattr(Path,'unlink',lambda *a,**k: (_ for _ in ()).throw(OSError('test')))
    with pytest.raises(store.CanvasError):cleanup.delete_scope('workflow',workflow['id'],True)
    assert path.exists() and cleanup.is_deleted('workflow',workflow['id'])
    monkeypatch.setattr(Path,'unlink',original)
    assert cleanup.delete_scope('workflow',workflow['id'],True)['removed_files']==1
    assert not path.exists()


def test_active_task_refuses_without_tombstone():
    import tasks
    _, workflow, _, path=fixture()
    tasks.create_task('image','test',{'canvas_workflow_id':workflow['id']})
    with pytest.raises(store.CanvasError):cleanup.delete_scope('workflow',workflow['id'],True)
    assert path.exists() and not cleanup.is_deleted('workflow',workflow['id'])


def test_output_cleanup_marks_task_unrestorable(tmp_path):
    import tasks, storage
    from pathlib import Path
    _, workflow, _, _=fixture()
    tid=tasks.create_task('image','test',{'canvas_workflow_id':workflow['id']},status='succeeded')
    path=Path(storage.OUTPUT_DIR)/'result.png';path.write_bytes(b'generated-output')
    tasks.register_asset(tid,'output_image',str(path))
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert not path.exists()
    assert tasks.get_task(tid)['params']['canvas_outputs_purged']
    assert tasks.restore_tasks([tid])==[]


def test_layer_reference_protects_output():
    import tasks, storage
    from pathlib import Path
    _, workflow, _, _=fixture()
    tid=tasks.create_task('image','test',{'canvas_workflow_id':workflow['id']},status='succeeded')
    path=Path(storage.OUTPUT_DIR)/'result.png';path.write_bytes(b'generated-output')
    tasks.register_asset(tid,'output_image',str(path))
    tasks.get_db().execute("INSERT INTO layer_projects(name,source_path,created_at,updated_at) VALUES('layer',?,'now','now')",(str(path),));tasks.get_db().commit()
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert path.exists() and tasks.get_task(tid)['deleted_at'] is None


def test_cross_project_library_protects_same_content():
    _, workflow, _, path=fixture()
    project=store.create_project('other')
    with path.open('rb') as handle:store.save_asset(project['id'],handle,'shared.png',library=True)
    assert cleanup.delete_scope('workflow',workflow['id'],True)['retained_shared']==1
    assert path.exists()


def test_workflow_cleanup_marks_library_copy_removed():
    project, workflow, _, path=fixture()
    with path.open('rb') as handle:asset=store.save_asset(project['id'],handle,'library.png',library=True)
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert cleanup.is_library_asset_deleted(asset['id'])


def test_outside_output_path_never_read_or_deleted(tmp_path):
    import tasks
    _, workflow, _, _=fixture()
    tid=tasks.create_task('image','test',{'canvas_workflow_id':workflow['id']},status='succeeded')
    path=tmp_path/'outside.bin';path.write_bytes(b'secret')
    tasks.register_asset(tid,'output_image',str(path))
    with pytest.raises(store.CanvasError):cleanup.delete_scope('workflow',workflow['id'],True)
    assert path.read_bytes()==b'secret'


def test_pending_deletion_api_is_discoverable(monkeypatch):
    import app
    from pathlib import Path
    _, workflow, _, _=fixture()
    monkeypatch.setattr(Path,'unlink',lambda *a,**k: (_ for _ in ()).throw(OSError('test')))
    client=app.app.test_client()
    response=client.delete('/api/canvas/workflows/'+workflow['id'],json={'cleanup_assets':True})
    assert response.status_code==409 and response.json['cleanup_pending'] is True
    pending=client.get('/api/canvas/deletions').json['deletions']
    assert pending[0]['id']==workflow['id'] and pending[0]['cleanup_assets'] is True


def test_known_thumbnail_removed_with_source():
    from pathlib import Path
    _, workflow, _, path=fixture()
    thumb=Path(str(path)+'.thumb.webp');thumb.write_bytes(b'thumbnail')
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert not path.exists() and not thumb.exists()


def test_invalid_option_http_is_400_not_pending():
    import app
    _, workflow, _, path=fixture()
    response=app.app.test_client().delete('/api/canvas/workflows/'+workflow['id'],json={'cleanup_assets':'yes'})
    assert response.status_code==400 and response.json['cleanup_pending'] is False
    assert path.exists()


def test_project_archive_preserves_explicitly_retained_workflow():
    project, workflow, _, path=fixture()
    cleanup.delete_scope('workflow',workflow['id'],False)
    result=cleanup.delete_scope('project',project['id'],True)
    assert path.exists() and result['retained_shared']>=1


def test_provider_hash_protects_copy():
    import tasks
    _, workflow, asset, path=fixture()
    row=store.get_asset(workflow['id'],asset['id'])
    tasks.create_provider_asset('cupsy','image',row['sha256'],'a.png','image/png',path.stat().st_size,str(path))
    assert cleanup.delete_scope('workflow',workflow['id'],True)['retained_shared']==1
    assert path.exists()


def test_cleaned_library_content_can_be_uploaded_again():
    project, workflow, _, path=fixture()
    original=path.read_bytes()
    with path.open('rb') as handle:old=store.save_asset(project['id'],handle,'old.png',library=True)
    cleanup.delete_scope('workflow',workflow['id'],True)
    new=store.save_asset(project['id'],io.BytesIO(original),'new.png',library=True)
    assert new['id']!=old['id']


def test_group_reference_preserves_library_asset():
    from canvas_library import save_group
    project, workflow, _, path=fixture()
    with path.open('rb') as handle:asset=store.save_asset(project['id'],handle,'group.png',library=True)
    save_group(project['id'],'shared',[asset['id']])
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert not cleanup.is_library_asset_deleted(asset['id'])
    assert store.asset_path(store.get_asset(project['id'],asset['id'],library=True)).exists()


def test_retained_media_url_stays_readable_but_owner_writes_stop():
    import app
    _, workflow, asset, path=fixture()
    original=path.read_bytes()
    cleanup.delete_scope('workflow',workflow['id'],False)
    client=app.app.test_client()
    assert client.get(asset['url']).data==original
    assert client.get('/api/canvas/workflows/'+workflow['id']).status_code==404
    assert client.post('/api/canvas/workflows/'+workflow['id']+'/assets',data={'file':(io.BytesIO(original),'again.png')}).status_code==404


def test_pending_cleanup_rejects_late_task_and_upload(monkeypatch):
    import tasks
    from pathlib import Path
    _, workflow, _, path=fixture()
    original=Path.unlink
    checked=[]
    def unlink(p,*args,**kwargs):
        with pytest.raises(store.CanvasError): tasks.create_task('image','late',{'canvas_workflow_id':workflow['id']})
        with pytest.raises(store.CanvasError): store.save_asset(workflow['id'],io.BytesIO(path.read_bytes()),'late.png')
        checked.append(True)
        return original(p,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',unlink)
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert checked and tasks.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==0


def test_distinct_task_urls_with_same_basename_do_not_protect_private_output():
    import tasks,storage
    from pathlib import Path
    _, workflow, _, _=fixture()
    owned=tasks.create_task('video','owned',{'canvas_workflow_id':workflow['id']},status='succeeded')
    unrelated=tasks.create_task('video','unrelated',{},status='succeeded')
    paths=[]
    for tid in (owned,unrelated):
        folder=Path(storage.OUTPUT_DIR)/'video'/str(tid);folder.mkdir(parents=True)
        path=folder/'video.mp4';path.write_bytes(str(tid).encode())
        tasks.update_task(tid,output_dir=str(folder),result={'url':f'/api/tasks/{tid}/file/video.mp4'})
        tasks.register_asset(tid,'output_video',str(path));paths.append(path)
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert not paths[0].exists() and paths[1].exists()


def test_exact_task_url_reference_protects_output():
    import tasks,storage
    from pathlib import Path
    _, workflow, _, _=fixture()
    tid=tasks.create_task('video','owned',{'canvas_workflow_id':workflow['id']},status='succeeded')
    folder=Path(storage.OUTPUT_DIR)/'video'/str(tid);folder.mkdir(parents=True)
    path=folder/'video.mp4';path.write_bytes(b'video')
    tasks.update_task(tid,output_dir=str(folder));tasks.register_asset(tid,'output_video',str(path))
    tasks.create_task('video','other',{'ref_video_urls':[f'/api/tasks/{tid}/file/video.mp4']},status='succeeded')
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert path.exists()


def test_bare_reference_is_reported_as_ambiguous():
    import tasks,json
    _, workflow, _, path=fixture()
    tasks.get_db().execute("INSERT INTO workspace_state(key,value,updated_at) VALUES('bare',?,'now')",(json.dumps({'url':path.name}),));tasks.get_db().commit()
    result=cleanup.delete_scope('workflow',workflow['id'],True)
    assert result['retained_ambiguous']==1 and path.exists()


def test_imported_task_relation_survives_unsaved_node_document():
    import app,tasks,storage
    from pathlib import Path
    _, workflow, _, source=fixture()
    tid=tasks.create_task('image','legacy import',{},status='succeeded')
    folder=Path(storage.OUTPUT_DIR)/'image'/str(tid);folder.mkdir(parents=True)
    path=folder/'result.png';path.write_bytes(source.read_bytes())
    tasks.update_task(tid,output_dir=str(folder));tasks.register_asset(tid,'output_image',str(path))
    response=app.app.test_client().post('/api/canvas/workflows/'+workflow['id']+'/task-results',json={'task_id':tid})
    assert response.status_code==200
    assert tasks.get_db().execute('SELECT task_id FROM canvas_workflow_tasks WHERE workflow_id=?',(workflow['id'],)).fetchone()['task_id']==tid
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert not path.exists()


def test_partial_output_cleanup_never_restores_damaged_task(monkeypatch):
    import tasks,storage
    from pathlib import Path
    _, workflow, _, _=fixture()
    tid=tasks.create_task('image','two outputs',{'canvas_workflow_id':workflow['id']},status='succeeded')
    files=[]
    for name in ('first.png','second.png'):
        path=Path(storage.OUTPUT_DIR)/name;path.write_bytes(name.encode());files.append(path)
        tasks.register_asset(tid,'output_image',str(path))
    tasks.move_tasks_to_trash([tid])
    original=Path.unlink
    def fail_second(path,*a,**kw):
        if path==files[1]: raise OSError('injected')
        return original(path,*a,**kw)
    monkeypatch.setattr(Path,'unlink',fail_second)
    with pytest.raises(store.CanvasError):cleanup.delete_scope('workflow',workflow['id'],True)
    assert not files[0].exists() and files[1].exists()
    assert tasks.restore_tasks([tid])==[]
    monkeypatch.setattr(Path,'unlink',original)
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert not files[1].exists() and tasks.restore_tasks([tid])==[]


def test_public_canvas_url_reference_remains_readable_after_archive():
    import app,tasks,json
    _, workflow, asset, path=fixture()
    tasks.get_db().execute("INSERT INTO workspace_state(key,value,updated_at) VALUES('public',?,'now')",(json.dumps({'image_url':asset['url']}),));tasks.get_db().commit()
    original=path.read_bytes()
    assert cleanup.delete_scope('workflow',workflow['id'],True)['retained_shared']==1
    assert app.app.test_client().get(asset['url']).data==original


def test_one_shared_output_does_not_allow_restoring_other_deleted_output():
    import tasks,storage,json
    from pathlib import Path
    _, workflow, _, _=fixture()
    tid=tasks.create_task('image','partial shared',{'canvas_workflow_id':workflow['id']},status='succeeded')
    files=[]
    for name in ('private.png','shared.png'):
        path=Path(storage.OUTPUT_DIR)/name;path.write_bytes(name.encode());files.append(path)
        tasks.register_asset(tid,'output_image',str(path))
    tasks.move_tasks_to_trash([tid])
    tasks.get_db().execute("INSERT INTO workspace_state(key,value,updated_at) VALUES('shared-output',?,'now')",(json.dumps({'image_url':str(files[1])}),));tasks.get_db().commit()
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert not files[0].exists() and files[1].exists()
    assert tasks.restore_tasks([tid])==[]


def test_public_library_url_reference_remains_readable_after_project_archive():
    import app,tasks,json
    project, _, _, path=fixture()
    with path.open('rb') as handle:
        asset=store.save_asset(project['id'],handle,'shared.png',library=True)
    tasks.get_db().execute("INSERT INTO workspace_state(key,value,updated_at) VALUES('library-public',?,'now')",(json.dumps({'references':[{'url':asset['url']}]}),));tasks.get_db().commit()
    original=path.read_bytes()
    result=cleanup.delete_scope('project',project['id'],True)
    assert result['retained_shared']>=1
    assert app.app.test_client().get(asset['url']).data==original


def test_all_shared_task_outputs_remain_restorable():
    import tasks,storage,json
    from pathlib import Path
    _, workflow, _, _=fixture()
    tid=tasks.create_task('image','shared',{'canvas_workflow_id':workflow['id']},status='succeeded')
    path=Path(storage.OUTPUT_DIR)/'shared.png';path.write_bytes(b'shared')
    tasks.register_asset(tid,'output_image',str(path));tasks.move_tasks_to_trash([tid])
    tasks.get_db().execute("INSERT INTO workspace_state(key,value,updated_at) VALUES('shared',?,'now')",(json.dumps({'image_url':str(path)}),));tasks.get_db().commit()
    cleanup.delete_scope('workflow',workflow['id'],True)
    assert path.exists() and tasks.restore_tasks([tid])==[tid]
