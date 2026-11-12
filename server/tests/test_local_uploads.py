import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage
import app as application
import canvas_store as store
import canvas_catalog as catalog
import local_uploads
import storage
import tasks
from test_canvas_catalog import setup,listing
from test_canvas_library_folders import image_bytes
from test_canvas_asset_nodes import media


def all_local(client):
    r=client.get('/api/canvas/library/items?scope=all&source=local')
    assert r.status_code==200,r.json
    return r.json['items']


def test_workspace_original_jpeg_is_preserved_before_png_normalization():
    client,p,w=setup()
    data=io.BytesIO(); Image.new('RGB',(41,29),'red').save(data,format='JPEG'); raw=data.getvalue()
    r=client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),'original.jpg')})
    assert r.status_code==201,r.json
    assert client.get(r.json['asset']['url']).data.startswith(b'\x89PNG')
    item=all_local(client)[0]
    assert item['selection']['source']=='local' and item['project_id'] is None and item['project_ids']==[]
    assert item['asset']['name']=='original.jpg' and item['asset']['mime_type']=='image/jpeg'
    assert client.get(item['asset']['url']).data==raw
    assert listing(client,p,'local')['total']==0
    copied=client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':[item['selection']]})
    assert copied.status_code==200 and client.get(copied.json['assets'][0]['url']).data==raw
    tag=client.post('/api/canvas/library/tags',json={'title':'raw'}).json['tag']
    assert client.patch('/api/canvas/library/items/'+item['key']+'/tags',json={'tag_ids':[tag['id']]}).status_code==200
    assert client.get(item['thumbnail_url']).status_code==200
    source=storage.resolve_workspace_asset_url('img_tabs',r.json['asset']['url'])
    from pathlib import Path
    Path(source).unlink()
    assert client.get(item['asset']['url']).data==raw
    # 2026-11-13: local delete is permanent and removes canvas copies made from it.
    assert client.delete('/api/canvas/library/items/'+item['key']).status_code==200
    assert all_local(client)==[]
    assert client.get(copied.json['assets'][0]['url']).status_code==404


@pytest.mark.parametrize('kind',['image','video','audio'])
def test_cupsy_upload_registers_original_without_remote_calls(monkeypatch,media,kind):
    client,p,w=setup()
    monkeypatch.setattr(application,'CUPSY_VIDEO_CONFIG',{'api_key':'synthetic','source_base_url':'https://mock.invalid','endpoint':'https://mock.invalid'})
    monkeypatch.setattr(application.HTTP,'post',lambda *a,**k:pytest.fail('network'))
    name,raw=media[kind]
    r=client.post('/api/cupsy/assets',data={'file':(io.BytesIO(raw),name),'kind':kind})
    assert r.status_code==202,r.json
    item=all_local(client)[0]
    assert item['asset']['kind']==kind and client.get(item['asset']['url']).data==raw
    asset=tasks.get_provider_asset(r.json['asset']['id'])
    from pathlib import Path
    tasks.update_provider_asset(asset['id'],deleted_at=tasks.utcnow())
    Path(asset['local_path']).unlink()
    assert client.get(item['asset']['url']).data==raw


def test_video_upload_deletion_and_project_cleanup_keep_local(monkeypatch,media):
    from canvas_cleanup import delete_scope
    client,p,w=setup(); name,raw=media['video']
    monkeypatch.setattr(application,'PUBLIC_HOST','mock.invalid')
    r=client.post('/api/upload_video',data={'file':(io.BytesIO(raw),name)})
    assert r.status_code==200,r.json
    item=all_local(client)[0]
    assert client.delete('/api/upload_video',json={'url':r.json['url']}).status_code==200
    delete_scope('project',p,cleanup=True)
    assert client.get(item['asset']['url']).data==raw
    assert len(all_local(client))==1


def test_capture_failure_rollback_and_dedup_first_name(monkeypatch):
    client,p,w=setup(); raw=image_bytes('red')
    def upload(name): return client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),name)})
    assert upload('first.png').status_code==201
    first=all_local(client)[0]
    assert upload('second.png').status_code==201
    assert all_local(client)[0]['asset']['name']=='first.png' and len(all_local(client))==1
    client.delete('/api/canvas/library/items/'+first['key'])
    assert all_local(client)==[]
    # Permanent delete: re-uploading the same bytes registers a fresh local item.
    assert upload('third.png').status_code==201
    again=all_local(client)
    assert len(again)==1 and again[0]['key']!=first['key'] and again[0]['asset']['name']=='third.png'
    def fail(*a,**k): raise ValueError('synthetic helper failure')
    monkeypatch.setattr(storage,'persist_workspace_upload',fail)
    assert client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(image_bytes('blue')),'new.png')}).status_code==400
    assert len(all_local(client))==1 and len(list(local_uploads.root().iterdir()))==1


def test_catalog_registration_failure_is_not_http_success(monkeypatch):
    client,p,w=setup()
    tasks.get_db().execute("CREATE TRIGGER fail_local BEFORE INSERT ON canvas_local_uploads BEGIN SELECT RAISE(ABORT,'synthetic registration failure'); END")
    tasks.get_db().commit()
    r=client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(image_bytes('red')),'new.png')})
    assert r.status_code==500 and '登记失败' in r.json['error']
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_local_uploads').fetchone()[0]==0
    assert list(local_uploads.root().iterdir())==[]


def test_parallel_dedup_and_initialization_no_backfill():
    client,p,w=setup(); barrier=Barrier(2)
    raw=image_bytes('red')
    def run():
        try:
            upload=FileStorage(stream=io.BytesIO(raw),filename='same.png')
            with local_uploads.capture_user_upload(upload): barrier.wait(timeout=5)
        finally: tasks.close_db()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run) for _ in range(2)]
        for future in futures: future.result(timeout=10)
    before=all_local(client)
    assert len(before)==1 and len(list(local_uploads.root().iterdir()))==1
    store.init_canvas_db()
    assert all_local(client)==before


def test_task_derived_cupsy_path_is_not_registered(monkeypatch,tmp_path):
    client,p,w=setup()
    path=tmp_path/'derived.png'; path.write_bytes(image_bytes('red'))
    application.create_cupsy_asset_from_path(str(path),'image')
    assert all_local(client)==[]


@pytest.mark.parametrize('kind,key',[('video','vid_tabs'),('audio','audio_form')])
def test_workspace_media_uploads_enter_unowned_catalog(media,kind,key):
    client,p,w=setup(); name,raw=media[kind]
    response=client.post('/api/workspace/assets/'+key,data={'file':(io.BytesIO(raw),name)})
    assert response.status_code==201,response.json
    item=all_local(client)[0]
    assert item['asset']['kind']==kind and client.get(item['asset']['url']).data==raw


def test_cupsy_registration_failure_warns_about_already_queued(monkeypatch):
    client,p,w=setup()
    monkeypatch.setattr(application,'CUPSY_VIDEO_CONFIG',{'api_key':'synthetic','source_base_url':'https://mock.invalid','endpoint':'https://mock.invalid'})
    tasks.get_db().execute("CREATE TRIGGER fail_local BEFORE INSERT ON canvas_local_uploads BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    tasks.get_db().commit()
    response=client.post('/api/cupsy/assets',data={'file':(io.BytesIO(image_bytes('red')),'original.png')})
    assert response.status_code==400 and '可能已排队' in response.json['error']
    assert tasks.get_db().execute('SELECT count(*) FROM provider_assets').fetchone()[0]==1
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_local_uploads').fetchone()[0]==0
    assert list(local_uploads.root().iterdir())==[]


def test_local_path_and_root_symlinks_rejected(tmp_path):
    client,p,w=setup()
    assert client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(image_bytes('red')),'a.png')}).status_code==201
    item=all_local(client)[0]
    row=tasks.get_db().execute('SELECT * FROM canvas_local_uploads').fetchone()
    path=local_uploads.path_for(row); outside=tmp_path/'outside.png'; outside.write_bytes(image_bytes('blue'))
    path.unlink(); path.symlink_to(outside)
    assert client.get(item['asset']['url']).status_code==409
    assert all_local(client)[0]['available'] is False
    path.unlink(); local_uploads.root().rmdir()
    external=tmp_path/'external'; external.mkdir()
    (store.asset_root()/'local_uploads').symlink_to(external,target_is_directory=True)
    with pytest.raises(store.CanvasError): local_uploads.root()


@pytest.mark.parametrize('image_format,mime,extension',[('BMP','image/bmp','bmp'),('TIFF','image/tiff','tiff')])
def test_legacy_pil_formats_keep_raw_original_and_workspace_png(image_format,mime,extension):
    client,p,w=setup()
    output=io.BytesIO(); Image.new('RGB',(24,18),'red').save(output,format=image_format); raw=output.getvalue()
    response=client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),'original.'+extension)})
    assert response.status_code==201,response.json
    assert client.get(response.json['asset']['url']).data.startswith(b'\x89PNG')
    item=all_local(client)[0]
    assert item['asset']['mime_type']==mime
    assert client.get(item['asset']['url']).data==raw
    assert client.get(item['thumbnail_url']).status_code==200
    copied=client.post(f'/api/canvas/workflows/{w}/library-references',json={'items':[item['selection']]})
    assert copied.status_code==400  # Existing canvas formats were not silently expanded.
    assert client.get(item['asset']['url']).data==raw


def test_generation_upload_helper_does_not_register_derivative(monkeypatch):
    client,p,w=setup()
    monkeypatch.setattr(application,'CUPSY_VIDEO_CONFIG',{'api_key':'synthetic','source_base_url':'https://mock.invalid','endpoint':'https://mock.invalid'})
    file=FileStorage(stream=io.BytesIO(image_bytes('red')),filename='derived.png',content_type='image/png')
    application.create_cupsy_asset_from_upload(file,'image')
    assert all_local(client)==[]
