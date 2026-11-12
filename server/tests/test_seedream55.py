import io
import pytest
from PIL import Image
import app
import tasks
import seedream55

@pytest.mark.parametrize('background', ['auto','transparent','opaque'])
@pytest.mark.parametrize('count', [0,1,10])
def test_seedream55_native_backgrounds(monkeypatch, background, count):
    monkeypatch.setitem(app.API_PROVIDERS,'ark',{'api_key':'mock','model':seedream55.MODEL,'endpoint':'https://mock.invalid'})
    b=io.BytesIO();Image.new('RGB',(32,32),'red').save(b,format='JPEG')
    data={'provider':'ark','prompt':'synthetic','aspect_ratio':'16:9','resolution':'1.5K','background':background,'output_format':'png'}
    if count:data['images']=[(io.BytesIO(b.getvalue()),f'{i}.jpg') for i in range(count)]
    r=app.app.test_client().post('/api/generate',data=data,content_type='multipart/form-data')
    assert r.status_code==202,r.get_json()
    task=tasks.get_task(r.get_json()['task_id'])
    assert task['params']['seedream55'] is True
    assert task['params']['size']=='2048x1152'
    assert task['params']['background']==background

def test_ep_classification_is_exact_and_profiles_keep_old_models(monkeypatch):
    monkeypatch.setitem(app.config['generation']['image']['byteplus'],'model','ep-confirmed55')
    assert seedream55.enabled('ep-confirmed55')
    assert not seedream55.enabled('ep-unknown')
    assert not seedream55.enabled('dola-seedream-5-0-pro-260628')

@pytest.mark.parametrize('model', ['dola-seedream-5-0-pro-260628','ep-unknown'])
def test_old_model_rejects_new_parameters(monkeypatch, model):
    monkeypatch.setitem(app.API_PROVIDERS,'ark',{'api_key':'mock','model':model})
    r=app.app.test_client().post('/api/generate',json={'provider':'ark','prompt':'test','resolution':'1.5K'})
    assert r.status_code==400

def test_worker_freezes_model_and_capability(monkeypatch):
    from test_generation import FakeResponse, _png_bytes
    monkeypatch.setitem(app.API_PROVIDERS,'ark',{'api_key':'mock','model':seedream55.MODEL,'endpoint':'https://mock.invalid'})
    r=app.app.test_client().post('/api/generate',json={'provider':'ark','prompt':'test','aspect_ratio':'16:9','resolution':'1.5K','background':'auto'})
    tid=r.get_json()['task_id']
    monkeypatch.setattr(FakeResponse,'raise_for_status',lambda self:None,raising=False)
    observed={}
    def post(url,**kwargs):
        observed.update(kwargs['json'])
        return FakeResponse(payload={'data':[{'url':'https://mock.invalid/output.png'}]})
    monkeypatch.setattr(app.HTTP,'post',post)
    monkeypatch.setattr(app.HTTP,'get',lambda *a,**k:FakeResponse(content=_png_bytes(),headers={'Content-Type':'image/png'}))
    monkeypatch.setitem(app.API_PROVIDERS,'ark',{'api_key':'mock','model':'old-model','endpoint':'https://mock.invalid'})
    with app.app.app_context():app.execute_image_task(tid)
    assert observed['model']==seedream55.MODEL
    assert observed['background']=='auto'
    assert observed['size']=='2048x1152'

@pytest.mark.parametrize('case', ['jpeg','eleven'])
def test_seedream55_rejects_invalid_transparent_request(monkeypatch, case):
    monkeypatch.setitem(app.API_PROVIDERS,'ark',{'api_key':'mock','model':seedream55.MODEL})
    b=io.BytesIO();Image.new('RGB',(16,16),'blue').save(b,format='PNG')
    data={'provider':'ark','prompt':'test','background':'transparent','output_format':'jpeg' if case=='jpeg' else 'png'}
    if case=='eleven':data['images']=[(io.BytesIO(b.getvalue()),f'{i}.png') for i in range(11)]
    r=app.app.test_client().post('/api/generate',data=data,content_type='multipart/form-data')
    assert r.status_code==400
