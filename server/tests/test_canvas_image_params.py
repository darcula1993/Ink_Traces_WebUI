import base64
import io
import pytest
from PIL import Image
import app as application
import canvas_store as store
import canvas_image_params as options
import tasks
import profile_runtime
from provider_profiles import save_profile
from test_generation import FakeResponse, _png_bytes


def setup(monkeypatch, provider='ark', params=None, profile=False):
    for adapter in ('ark','cupsy'):
        monkeypatch.setitem(application.API_PROVIDERS,adapter,profile_runtime.ProfileConfig({'api_key':'synthetic','endpoint':'https://mock.invalid','model':'configured-model'},adapter))
    monkeypatch.setattr(application,'CUPSY_VIDEO_CONFIG',profile_runtime.ProfileConfig({'api_key':'synthetic','endpoint':'https://mock.invalid','source_base_url':'https://mock.invalid'},'cupsy'))
    p=store.create_project('images')['id']; wf=store.create_workflow(p,'images')
    selected={'provider':provider,'profile_id':None}
    if profile:
        item=save_profile({'name':'image-profile','kind':'image','adapter':provider,'api_key':'synthetic','settings':{'endpoint':'https://mock.invalid','model':'configured-model'} if provider!='cupsy' else {'endpoint':'https://mock.invalid','model':'seedream-5.0-pro','source_base_url':'https://mock.invalid'}})
        selected['profile_id']=item['id']
    doc=wf['document']; doc['nodes']=[{'id':'image','type':'image','x':0,'y':0,'params':params or {},'providerSelection':selected}]
    store.update_workflow(wf['id'],'images',doc,1)
    body={'canvas_workflow_id':wf['id'],'canvas_node_id':'image','canvas_workflow_revision':2,'provider':provider,'prompt':'test',
          'aspect_ratio':(params or {}).get('ratio','1:1'),'resolution':(params or {}).get('resolution','1K')}
    body.update({k:v for k,v in (params or {}).items() if k not in ('ratio','lock_aspect_ratio')})
    if selected['profile_id']: body['profile_id']=selected['profile_id']
    return application.app.test_client(),wf['id'],body


@pytest.mark.parametrize('provider',['ark','cupsy'])
@pytest.mark.parametrize('form',[False,True])
@pytest.mark.parametrize('profile',[False,True])
def test_options_reach_real_task_and_provider_request(monkeypatch,provider,form,profile):
    params={'ratio':'custom','custom_width':1024,'custom_height':1024,'output_format':'jpeg','watermark':True,'lock_aspect_ratio':True}
    client,wid,body=setup(monkeypatch,provider,params,profile)
    captured=[]
    def post(url,**kwargs):
        captured.append(kwargs['json'])
        payload={'data':[{'b64_json':base64.b64encode(_png_bytes()).decode()}]}
        return FakeResponse(status_code=202 if provider=='cupsy' else 200,payload=payload)
    monkeypatch.setattr(application.HTTP,'post',post)
    if form:
        payload={k:str(v).lower() if type(v) is bool else str(v) for k,v in body.items()}
        response=client.post('/api/generate',data=payload,content_type='multipart/form-data')
    else: response=client.post('/api/generate',json=body)
    assert response.status_code==202,response.json
    tid=response.json['task_id']; frozen=tasks.get_task(tid)['params']
    assert frozen['output_format']=='jpeg'
    assert not captured
    with application.app.test_request_context(): application.execute_image_task(tid)
    assert len(captured)==1
    sent=captured[0]
    assert sent['size']=='1024x1024' and sent['watermark'] is True and sent['output_format']=='jpeg'
    assert 'lock_aspect_ratio' not in frozen
    if profile: assert frozen['profile_revision']==1


@pytest.mark.parametrize('params',[{'custom_width':True},{'custom_height':0},{'custom_width':'1024'},{'custom_height':None},
    {'output_format':'webp'},{'background':'white'},{'watermark':1},{'unknown_option':True},{'lock_aspect_ratio':None}])
def test_structural_schema_rejects_invalid(monkeypatch,params):
    with pytest.raises(store.CanvasError): setup(monkeypatch,params=params)


@pytest.mark.parametrize('provider,params',[
    ('cupsy',{'background':'opaque'}),
    ('ark',{'ratio':'custom','custom_width':1001,'custom_height':1008}),('ark',{'ratio':'custom','custom_width':16,'custom_height':16})])
def test_invalid_provider_combination_saves_but_rejects_before_task(monkeypatch,provider,params):
    client,wid,body=setup(monkeypatch,provider,params)
    assert store.workflow(wid)['document']['nodes'][0]['params']==params
    response=client.post('/api/generate',json=body)
    assert response.status_code==400,response.json
    assert tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0]==0


@pytest.mark.parametrize('override',[{'watermark':True},{'aspect_ratio':'16:9'},{'resolution':'2K'}, {'model':'not-profile-model'}])
def test_tampered_request_fails_before_task(monkeypatch,override):
    client,wid,body=setup(monkeypatch)
    response=client.post('/api/generate',json={**body,**override})
    assert response.status_code in (400,409),response.json
    assert tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0]==0


def test_unknown_provider_node_is_rejected_as_unsupported(monkeypatch):
    with pytest.raises(store.CanvasError, match='不支持所选接口'):
        setup(monkeypatch,'acme',{'output_format':'jpeg'})
    assert tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0]==0


def test_metadata_real_alpha_opaque_pixels_cache_scope_and_legacy_guard(monkeypatch):
    client,wid,body=setup(monkeypatch)
    stream=io.BytesIO(); Image.new('RGBA',(32,48),(1,2,3,255)).save(stream,format='PNG'); stream.seek(0)
    asset=store.save_asset(wid,stream,'opaque-alpha.png')
    url=f"/api/canvas/workflows/{wid}/assets/{asset['id']}/metadata"
    first=client.get(url)
    assert first.status_code==200 and first.json['metadata']=={'width':32,'height':48,'pixels':1536,'has_alpha':True,'mime_type':'image/png'}
    before=options._metadata.cache_info().hits
    assert client.get(url).json==first.json and options._metadata.cache_info().hits==before+1
    other=store.create_workflow(store.workflow(wid)['project_id'],'other')['id']
    assert client.get(url.replace(wid,other)).status_code==404
    assert options._metadata.cache_info().maxsize==128
    # Legacy noncanvas calls keep prior behavior; no saved-node parameter comparison.
    response=client.post('/api/generate',json={'provider':'ark','prompt':'legacy','aspect_ratio':'1:1','watermark':True})
    assert response.status_code==202


def test_ark_background_requires_actual_alpha_reference(monkeypatch):
    client,wid,body=setup(monkeypatch,params={'background':'transparent','output_format':'png'})
    assert client.post('/api/generate',json=body).status_code==400
    rgb=io.BytesIO(); Image.new('RGB',(32,32)).save(rgb,format='PNG'); rgb.seek(0)
    response=client.post('/api/generate',data={**{k:str(v) for k,v in body.items()},'images':(rgb,'rgb.png')})
    assert response.status_code==400
    alpha=io.BytesIO(); Image.new('RGBA',(32,32),(0,0,0,255)).save(alpha,format='PNG'); alpha.seek(0)
    response=client.post('/api/generate',data={**{k:str(v) for k,v in body.items()},'images':(alpha,'rgba.png')})
    assert response.status_code==202,response.json
    assert tasks.get_task(response.json['task_id'])['params']['background']=='transparent'


def test_custom_ignores_resolution_and_preserves_saved_shape(monkeypatch):
    params={'ratio':'custom','resolution':'4K','custom_width':1024,'custom_height':1024,'output_format':'png','lock_aspect_ratio':True}
    client,wid,body=setup(monkeypatch,params=params)
    assert store.workflow(wid)['document']['nodes'][0]['params']==params
    response=client.post('/api/generate',json={**body,'resolution':'unneeded'})
    assert response.status_code==202,response.json
    assert tasks.get_task(response.json['task_id'])['params']['size']=='1024x1024'
    assert 'resolution' not in tasks.get_task(response.json['task_id'])['params']


def test_canvas_missing_aspect_uses_saved_default_not_legacy_transport_defaults(monkeypatch):
    client,wid,body=setup(monkeypatch)
    del body['aspect_ratio']
    response=client.post('/api/generate',json=body)
    assert response.status_code==202
    assert tasks.get_task(response.json['task_id'])['params']['aspect_ratio']=='1:1'


def test_metadata_cache_does_not_bypass_deleted_owner(monkeypatch):
    client,wid,body=setup(monkeypatch)
    asset=store.save_asset(wid,io.BytesIO(_png_bytes()),'rgb.png')
    url=f"/api/canvas/workflows/{wid}/assets/{asset['id']}/metadata"
    assert client.get(url).json['metadata']['has_alpha'] is False
    with tasks.get_db() as db:
        db.execute('INSERT INTO canvas_deletions VALUES (?,?,?,0)',('workflow',wid,'{}'))
    assert client.get(url).status_code==404


def test_capabilities_are_adapter_specific_and_single_shot(monkeypatch):
    client,wid,body=setup(monkeypatch)
    caps=client.get('/api/canvas/image-capabilities').json['providers']
    assert set(caps)=={'ark','cupsy'}
    assert 'auto' in caps['ark']['ratios'] and 'auto' not in caps['cupsy']['ratios']
    assert caps['ark']['size_map']['1K']['16:9']!=caps['cupsy']['size_map']['1K']['16:9']
    assert caps['ark']['custom']['multiple']==16
