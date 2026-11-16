"""Tool / Cupsy original uploads (LIBRARY-GLOBAL-20261116 S6c): registered in the global media library root."""
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage
import app as application
import canvas_store as store
import local_uploads
import media_library
import storage
import tasks
from test_canvas_catalog import setup
from test_canvas_library_folders import image_bytes
from test_canvas_asset_nodes import media


def all_media(client):
    r=client.get('/api/canvas/media',query_string={'limit':200})
    assert r.status_code==200,r.json
    return r.json['items']


def media_files():
    return sorted(p.name for p in media_library.root().iterdir())


def local_count():
    return tasks.get_db().execute('SELECT count(*) FROM canvas_local_uploads').fetchone()[0]


def test_workspace_original_jpeg_is_preserved_before_png_normalization():
    client,p,w=setup()
    data=io.BytesIO(); Image.new('RGB',(41,29),'red').save(data,format='JPEG'); raw=data.getvalue()
    r=client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),'original.jpg')})
    assert r.status_code==201,r.json
    assert client.get(r.json['asset']['url']).data.startswith(b'\x89PNG')
    [item]=all_media(client)
    assert item['folder_id'] is None and item['origin']=='upload' and item['source_task_id'] is None
    assert item['name']=='original.jpg' and item['mime_type']=='image/jpeg' and local_count()==0
    assert client.get(item['url']).data==raw
    assert client.get(item['thumbnail_url']).status_code==200
    assert media_files()==[item['id']+'.jpg']  # no staging leftovers
    # independent of the workspace cache
    Path(storage.resolve_workspace_asset_url('img_tabs',r.json['asset']['url'])).unlink()
    assert client.get(item['url']).data==raw
    # library delete is permanent; a re-upload registers a fresh item
    assert client.post('/api/canvas/media/delete',json={'ids':[item['id']]}).status_code==200
    assert all_media(client)==[]
    assert client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),'again.jpg')}).status_code==201
    [again]=all_media(client)
    assert again['id']!=item['id'] and again['name']=='again.jpg'


@pytest.mark.parametrize('kind',['image','video','audio'])
def test_cupsy_upload_registers_original_without_remote_calls(monkeypatch,media,kind):
    client,p,w=setup()
    monkeypatch.setattr(application,'CUPSY_VIDEO_CONFIG',{'api_key':'synthetic','source_base_url':'https://mock.invalid','endpoint':'https://mock.invalid'})
    monkeypatch.setattr(application.HTTP,'post',lambda *a,**k:pytest.fail('network'))
    name,raw=media[kind]
    r=client.post('/api/cupsy/assets',data={'file':(io.BytesIO(raw),name),'kind':kind})
    assert r.status_code==202,r.json
    [item]=all_media(client)
    assert item['kind']==kind and item['folder_id'] is None and item['origin']=='upload'
    assert client.get(item['url']).data==raw and local_count()==0
    asset=tasks.get_provider_asset(r.json['asset']['id'])
    tasks.update_provider_asset(asset['id'],deleted_at=tasks.utcnow())
    Path(asset['local_path']).unlink()
    assert client.get(item['url']).data==raw


def test_video_upload_deletion_and_project_cleanup_keep_media(monkeypatch,media):
    from canvas_cleanup import delete_scope
    client,p,w=setup(); name,raw=media['video']
    monkeypatch.setattr(application,'PUBLIC_HOST','mock.invalid')
    r=client.post('/api/upload_video',data={'file':(io.BytesIO(raw),name)})
    assert r.status_code==200,r.json
    [item]=all_media(client)
    assert client.delete('/api/upload_video',json={'url':r.json['url']}).status_code==200
    delete_scope('project',p,cleanup=True)
    assert client.get(item['url']).data==raw
    assert len(all_media(client))==1


def test_capture_failure_rollback_and_dedup_first_name(monkeypatch):
    client,p,w=setup(); raw=image_bytes('red')
    def upload(name): return client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),name)})
    assert upload('first.png').status_code==201
    assert upload('second.png').status_code==201
    [first]=all_media(client)
    assert first['name']=='first.png'
    def fail(*a,**k): raise ValueError('synthetic helper failure')
    monkeypatch.setattr(storage,'persist_workspace_upload',fail)
    assert client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(image_bytes('blue')),'new.png')}).status_code==400
    assert len(all_media(client))==1 and media_files()==[first['id']+'.png']


def test_upload_of_generated_content_stays_in_generation_history():
    """User decision 2026-11-17 (S9): a runtime upload of content already in 生成历史 is not moved,
    renamed or re-sourced (Q6 only applies to migration)."""
    client,p,w=setup(); raw=image_bytes('green')
    generated=media_library.root().parent/'gen.png'; generated.write_bytes(raw)
    media_id,_=media_library.import_file(generated,name='gen.png',origin='generated',
                                         folder_id=media_library.system_folder_id('generated_image'))
    assert client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),'mine.png')}).status_code==201
    [item]=all_media(client)
    assert item['id']==media_id and item['folder_id']==media_library.system_folder_id('generated_image')
    assert item['origin']=='generated' and item['name']=='gen.png'


def test_catalog_registration_failure_is_not_http_success():
    client,p,w=setup()
    tasks.get_db().execute("CREATE TRIGGER fail_media BEFORE INSERT ON media BEGIN SELECT RAISE(ABORT,'synthetic registration failure'); END")
    tasks.get_db().commit()
    r=client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(image_bytes('red')),'new.png')})
    assert r.status_code==500 and '登记失败' in r.json['error']
    assert tasks.get_db().execute('SELECT count(*) FROM media').fetchone()[0]==0
    assert media_files()==[]


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
    before=all_media(client)
    assert len(before)==1 and len(media_files())==1 and local_count()==0
    store.init_canvas_db()
    assert all_media(client)==before


def test_task_derived_cupsy_path_is_not_registered(monkeypatch,tmp_path):
    client,p,w=setup()
    path=tmp_path/'derived.png'; path.write_bytes(image_bytes('red'))
    application.create_cupsy_asset_from_path(str(path),'image')
    assert all_media(client)==[]


@pytest.mark.parametrize('kind,key',[('video','vid_tabs'),('audio','audio_form')])
def test_workspace_media_uploads_enter_library_root(media,kind,key):
    client,p,w=setup(); name,raw=media[kind]
    response=client.post('/api/workspace/assets/'+key,data={'file':(io.BytesIO(raw),name)})
    assert response.status_code==201,response.json
    [item]=all_media(client)
    assert item['kind']==kind and item['folder_id'] is None and client.get(item['url']).data==raw


def test_cupsy_registration_failure_warns_about_already_queued(monkeypatch):
    client,p,w=setup()
    monkeypatch.setattr(application,'CUPSY_VIDEO_CONFIG',{'api_key':'synthetic','source_base_url':'https://mock.invalid','endpoint':'https://mock.invalid'})
    tasks.get_db().execute("CREATE TRIGGER fail_media BEFORE INSERT ON media BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    tasks.get_db().commit()
    response=client.post('/api/cupsy/assets',data={'file':(io.BytesIO(image_bytes('red')),'original.png')})
    assert response.status_code==400 and '可能已排队' in response.json['error']
    assert tasks.get_db().execute('SELECT count(*) FROM provider_assets').fetchone()[0]==1
    assert tasks.get_db().execute('SELECT count(*) FROM media').fetchone()[0]==0
    assert media_files()==[]


def test_unsupported_upload_rejected_before_tool_runs(monkeypatch):
    client,p,w=setup()
    called=[]
    monkeypatch.setattr(storage,'persist_workspace_upload',lambda *a,**k:called.append(1))
    r=client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(b'not media at all'),'x.png')})
    assert r.status_code==400 and called==[] and all_media(client)==[] and media_files()==[]


def legacy_image(image_format,color='red',mode='RGB'):
    output=io.BytesIO(); Image.new(mode,(24,18),color).save(output,format=image_format); return output.getvalue()


@pytest.mark.parametrize('image_format,extension',[('BMP','bmp'),('TIFF','tiff')])
def test_legacy_pil_formats_register_tool_converted_png(image_format,extension):
    """S7 (user 2026-11-17): BMP/TIFF in the image tool register the converted PNG, original name with .png."""
    client,p,w=setup()
    raw=legacy_image(image_format)
    response=client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),'photo.final.'+extension.upper())})
    assert response.status_code==201,response.json
    tool_png=client.get(response.json['asset']['url']).data
    assert tool_png.startswith(b'\x89PNG')
    [item]=all_media(client)
    assert item['name']=='photo.final.png' and item['mime_type']=='image/png' and item['kind']=='image'
    assert item['folder_id'] is None and item['origin']=='upload' and item['source_task_id'] is None
    assert client.get(item['url']).data==tool_png  # identical to what the tool stored
    assert client.get(item['thumbnail_url']).status_code==200
    assert media_files()==[item['id']+'.png'] and local_count()==0  # no staging/conversion leftovers
    Path(storage.resolve_workspace_asset_url('img_tabs',response.json['asset']['url'])).unlink()
    assert client.get(item['url']).data==tool_png  # independent copy


def test_legacy_converted_png_deduplicates_by_content():
    client,p,w=setup()
    raw=legacy_image('BMP')
    first=client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),'a.bmp')})
    assert first.status_code==201,first.json
    assert client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),'b.bmp')}).status_code==201
    tool_png=client.get(first.json['asset']['url']).data
    # the same PNG uploaded directly is the same content
    assert client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(tool_png),'c.png')}).status_code==201
    [item]=all_media(client)
    assert item['name']=='a.png' and len(media_files())==1
    # different pixels -> a separate item
    assert client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(legacy_image('BMP','blue')),'d.bmp')}).status_code==201
    assert sorted(i['name'] for i in all_media(client))==['a.png','d.png']


def test_legacy_tiff_alpha_kept_in_converted_png():
    client,p,w=setup()
    raw=legacy_image('TIFF',(255,0,0,128),'RGBA')
    assert client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(raw),'alpha.tif')}).status_code==201
    [item]=all_media(client)
    with Image.open(io.BytesIO(client.get(item['url']).data)) as picture:
        assert picture.format=='PNG' and picture.mode=='RGBA'


def test_legacy_format_tool_failure_registers_nothing(monkeypatch):
    client,p,w=setup()
    def broken(*a,**k): raise OSError('synthetic tool failure')
    monkeypatch.setattr(storage,'persist_workspace_upload',broken)
    r=client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(legacy_image('BMP')),'x.bmp')})
    assert r.status_code==400 and all_media(client)==[] and media_files()==[]


def test_legacy_converted_registration_failure_is_reported():
    client,p,w=setup()
    tasks.get_db().execute("CREATE TRIGGER fail_media BEFORE INSERT ON media BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    tasks.get_db().commit()
    r=client.post('/api/workspace/assets/img_tabs',data={'file':(io.BytesIO(legacy_image('TIFF')),'x.tiff')})
    assert r.status_code==500 and '登记失败' in r.json['error']
    assert media_files()==[]


def test_legacy_formats_not_converted_elsewhere_are_not_registered():
    """Paths that keep BMP/TIFF as-is (no tool conversion) still register nothing."""
    client,p,w=setup()
    raw=legacy_image('BMP')
    response=client.post('/api/workspace/assets/vid_tabs',data={'file':(io.BytesIO(raw),'frame.bmp')})
    assert response.status_code==201,response.json
    assert client.get(response.json['asset']['url']).data==raw
    assert all_media(client)==[] and media_files()==[] and local_count()==0


def test_generation_upload_helper_does_not_register_derivative(monkeypatch):
    client,p,w=setup()
    monkeypatch.setattr(application,'CUPSY_VIDEO_CONFIG',{'api_key':'synthetic','source_base_url':'https://mock.invalid','endpoint':'https://mock.invalid'})
    file=FileStorage(stream=io.BytesIO(image_bytes('red')),filename='derived.png',content_type='image/png')
    application.create_cupsy_asset_from_upload(file,'image')
    assert all_media(client)==[]
