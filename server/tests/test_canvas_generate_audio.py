"""Canvas output audio is independent from reference audio and retains false."""
import pytest

import app as application
import canvas_store as store
import tasks
from canvas_project_settings import update_settings
from test_generation import FakeResponse


def canvas(provider='ark'):
    project = store.create_project('output audio')
    workflow = store.create_workflow(project['id'], 'video')
    update_settings(project['id'], {'revision': 0, 'providers': {
        'image': None, 'video': {'provider': provider, 'profile_id': None}, 'audio': None,
    }})
    return workflow


@pytest.mark.parametrize('value', [False, True, 'missing'])
def test_canvas_audio_flag_save_reload(value):
    workflow = canvas()
    params = {} if value == 'missing' else {'generate_audio': value}
    document = workflow['document']
    document['nodes'] = [{'id':'v','type':'video','title':'video','x':0,'y':0,'params':params}]
    client = application.app.test_client()
    response = client.put(f"/api/canvas/workflows/{workflow['id']}", json={'title':'video','document':document,'revision':1})
    assert response.status_code == 200
    saved = client.get(f"/api/canvas/workflows/{workflow['id']}").json['workflow']['document']['nodes'][0]['params']
    assert saved == params


@pytest.mark.parametrize('value', [None, 0, 1, 'false', 'true', [], {}])
def test_canvas_audio_flag_rejects_non_boolean(value):
    workflow = canvas()
    document = workflow['document']
    document['nodes'] = [{'id':'v','type':'video','title':'video','x':0,'y':0,'params':{'generate_audio':value}}]
    with pytest.raises(store.CanvasError, match='布尔值'):
        store.update_workflow(workflow['id'], 'video', document, 1)


def configure(monkeypatch):
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {
        'api_key':'synthetic', 'endpoint':'https://ark.invalid', 'model':'endpoint-20', 'seedance_2_5_model':'endpoint-25',
    })
    monkeypatch.setattr(application, 'CUPSY_VIDEO_CONFIG', {
        'api_key':'synthetic', 'endpoint':'https://cupsy.invalid', 'model':'seedance-2.5', 'source_base_url':'https://studio.invalid',
    })
    sent = []
    def post(url, **kwargs):
        sent.append(kwargs['json'])
        return FakeResponse(status_code=200, payload={'id':'synthetic-video', 'status':'queued'})
    monkeypatch.setattr(application.HTTP, 'post', post)
    return sent


@pytest.mark.parametrize('provider', ['ark','cupsy'])
@pytest.mark.parametrize('form', [False, True])
@pytest.mark.parametrize('value', [False, True, 'missing'])
def test_canvas_submission_preserves_output_audio_to_provider(monkeypatch, provider, form, value):
    sent = configure(monkeypatch)
    workflow = canvas(provider)
    body = {'provider':provider,'model':'seedance-2.5','video_mode':'reference','prompt':'synthetic',
            'canvas_workflow_id':workflow['id'],'project_settings_revision':1}
    if value != 'missing': body['generate_audio'] = value
    client = application.app.test_client()
    if form:
        response = client.post('/api/video/generate', data={key:str(val).lower() if type(val) is bool else str(val) for key,val in body.items()}, content_type='multipart/form-data')
    else:
        response = client.post('/api/video/generate', json=body)
    assert response.status_code == (200 if provider == 'ark' else 202), response.json
    task_id = response.json['db_task_id']
    expected = True if value == 'missing' else value
    assert tasks.get_task(task_id)['params']['generate_audio'] is expected
    if provider == 'cupsy':
        assert sent == []  # Cupsy submission is performed by the worker poll step.
        assert tasks.claim_next_task('audio-flag-test')['id'] == task_id
        assert application.poll_video_task_once(task_id)['state'] == 'pending'
    assert sent[-1]['generate_audio'] is expected


def test_cupsy_legacy_task_defaults_audio_on(monkeypatch):
    sent = configure(monkeypatch)
    task_id = tasks.create_task('video','legacy',{'model':'seedance-2.5','video_mode':'reference'},provider='cupsy')
    assert application.poll_video_task_once(task_id)['state'] == 'pending'
    assert sent[-1]['generate_audio'] is True


def test_output_audio_off_preserves_reference_audio(monkeypatch, tmp_path):
    sent = configure(monkeypatch)
    workflow = canvas('cupsy')
    path = tmp_path/'reference.wav'; path.write_bytes(b'controlled registered reference')
    asset = tasks.create_provider_asset('cupsy','audio','synthetic-hash','reference.wav','audio/wav',path.stat().st_size,str(path))
    tasks.update_provider_asset(asset['id'],external_asset_id='remote-audio',asset_uri='asset://remote-audio',status='active',next_run_at=None)
    response = application.app.test_client().post('/api/video/generate',json={
        'provider':'cupsy','model':'seedance-2.5','video_mode':'reference','prompt':'synthetic','generate_audio':False,
        'canvas_workflow_id':workflow['id'],'project_settings_revision':1,
        'cupsy_assets':[{'id':asset['id'],'role':'reference_audio'}],
    })
    assert response.status_code == 202, response.json
    assert application.poll_video_task_once(response.json['db_task_id'])['state'] == 'pending'
    assert sent[-1]['generate_audio'] is False
    assert any(item.get('role') == 'reference_audio' for item in sent[-1]['content'])
