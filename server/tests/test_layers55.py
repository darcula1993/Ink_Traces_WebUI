import base64
import io
import json
import zipfile
import pytest
import app
import tasks
import seedream55
from test_generation import _rgba_png_bytes, FakeResponse

@pytest.mark.parametrize('value', [True,1,101,2.5,'2.5',None])
def test_invalid_count_before_project_creation(monkeypatch,value):
    monkeypatch.setitem(app.API_PROVIDERS,'ark',{'api_key':'test','model':seedream55.MODEL})
    from layer_options import options
    with pytest.raises(ValueError):options({'max_images':value},seedream55.MODEL)


def test_hundred_outputs_ocr_survives_save_restore_and_zip(monkeypatch):
    monkeypatch.setitem(app.API_PROVIDERS,'ark',{'api_key':'test','model':seedream55.MODEL,'endpoint':'https://provider.invalid'})
    client=app.app.test_client()
    r=client.post('/api/layer/projects',data={'image':(io.BytesIO(_rgba_png_bytes((512,512))),'test.png'),'max_images':'100','text_recognition':'true','size':'1K'})
    assert r.status_code==202,r.get_json()
    tid,pid=r.get_json()['task_id'],r.get_json()['project_id']
    ocr={'text':'Hello\nWorld','lines':[{'bounding_box':{'absolute':[0,0,30,20],'normalized':[0,0,1000,500]},'runs':[{'text':'Hello','style':{'similar_font_family':'unknown','bold':False,'italic':True,'shadow':False,'foreground_color':'#FF0000'}},{'text':' World','style':{'bold':True}}]}]}
    image=base64.b64encode(_rgba_png_bytes()).decode();observed={}
    def post(url,**kwargs):
        observed.update(kwargs['json'])
        return FakeResponse(payload={'data':[{'b64_json':image,'z_index':i,**({'text_recognition':ocr} if i==1 else {})} for i in range(100)]})
    monkeypatch.setattr(app.HTTP,'post',post)
    # Capability and deployed model are frozen even when configuration later changes.
    monkeypatch.setitem(app.API_PROVIDERS,'ark',{'api_key':'test','model':'old-model','endpoint':'https://provider.invalid'})
    with app.app.app_context():result,status=app.execute_layer_task(tid)
    assert status==200
    assert observed['model']==seedream55.MODEL
    assert observed['layer_decomposition_options']=={'max_images':100,'text_recognition':True}
    project=client.get(f'/api/layer/projects/{pid}').get_json()['project']
    assert len(project['document']['layers'])==100
    assert project['document']['layers'][1]['text_recognition']==ocr
    doc=project['document'];doc['layers'][1]['x']=3
    assert client.put(f'/api/layer/projects/{pid}',json={'document':doc,'revision':project['document_revision']}).status_code==200
    restored=client.post(f"/api/layer/projects/{pid}/revisions/{project['revisions'][0]['id']}/restore").get_json()['project']
    assert restored['document']['layers'][1]['text_recognition']==ocr
    archive=client.get(f'/api/layer/projects/{pid}/layers.zip')
    with zipfile.ZipFile(io.BytesIO(archive.data)) as bundle:
        manifest=json.loads(bundle.read('manifest.json'))
        assert len(manifest['layers'])==100
        assert manifest['layers'][1]['text_recognition']==ocr


def test_options_defaults_old_models_and_boolean_validation(monkeypatch):
    from layer_options import options
    assert options({},seedream55.MODEL)=={'max_images':30,'text_recognition':False}
    assert options({},'dola-seedream-5-0-pro-260628')=={}
    with pytest.raises(ValueError):options({'text_recognition':True},'dola-seedream-5-0-pro-260628')
    with pytest.raises(ValueError):options({'text_recognition':1},seedream55.MODEL)


def test_partial_download_does_not_publish_revision(monkeypatch):
    monkeypatch.setitem(app.API_PROVIDERS,'ark',{'api_key':'test','model':seedream55.MODEL,'endpoint':'https://provider.invalid'})
    client=app.app.test_client()
    created=client.post('/api/layer/projects',data={'image':(io.BytesIO(_rgba_png_bytes((512,512))),'test.png')}).get_json()
    image='data:image/png;base64,'+base64.b64encode(_rgba_png_bytes()).decode()
    monkeypatch.setattr(app,'_generate_ark_image',lambda *a,**k:({'success':True,'items':[{'data_url':image,'z_index':0},{'image_source':{'url':'https://invalid.test/missing'},'z_index':1}]},200))
    original=app._save_generated_image
    def fail_second(source,*args):
        if isinstance(source,dict):raise OSError('synthetic download failure')
        return original(source,*args)
    monkeypatch.setattr(app,'_save_generated_image',fail_second)
    with app.app.app_context(),pytest.raises(OSError):app.execute_layer_task(created['task_id'])
    project=client.get(f"/api/layer/projects/{created['project_id']}").get_json()['project']
    assert not project['revisions']
    assert not (project.get('document') or {}).get('layers')

@pytest.mark.parametrize('value', [
    {'text':'x','lines':[None]}, {'text':'x','lines':[{'runs':'bad'}]},
    {'lines':[{'runs':[None]}]}, {'lines':[{'runs':[{'text':{}}]}]},
    {'lines':[{'runs':[{'style':[]}]}]}, {'lines':[{'bounding_box':None}]},
    {'lines':[{'bounding_box':{'absolute':[1,2]}}]},
    {'lines':[{'runs':[{'style':{'bold':'false'}}]}]},
])
def test_nested_ocr_structure_is_rejected(value):
    from layer_options import recognition
    with pytest.raises(ValueError):recognition(value)


def test_ocr_unknown_fields_and_false_preserved():
    from layer_options import recognition
    value={'text':'A\nB','future':{'any':[False,None]},'lines':[{'runs':[{'text':'A','style':{'bold':False,'similar_font_family':'unknown','future':{'x':1}}},{'text':'B','style':{}}]}]}
    assert recognition(value) is value
