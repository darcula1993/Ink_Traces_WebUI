"""Legacy video options survive canvas save and both submission transports."""
import pytest

import app as application
import canvas_store as store
import tasks
from test_canvas_generate_audio import canvas, configure


@pytest.mark.parametrize('duration', [-1, 0, 4, 12, 3600, '-1', None, ''])
def test_video_duration_save_reload(duration):
    workflow = canvas()
    document = workflow['document']
    params = {'duration':duration, 'resolution':'480p', 'ratio':'4:3'}
    document['nodes'] = [{'id':'v', 'type':'video', 'x':0, 'y':0, 'params':params}]
    client = application.app.test_client()
    url = '/api/canvas/workflows/' + workflow['id']
    assert client.put(url, json={'title':'video', 'document':document, 'revision':1}).status_code == 200
    assert client.get(url).json['workflow']['document']['nodes'][0]['params'] == params


@pytest.mark.parametrize('node_type,duration', [
    ('image', -1), ('audio', -1), ('text', -1),
    ('video', -2), ('video', -0.5), ('video', 3601), ('video', True), ('video', {}),
])
def test_duration_boundaries_unchanged(node_type, duration):
    workflow = canvas()
    document = workflow['document']
    document['nodes'] = [{'id':'n', 'type':node_type, 'x':0, 'y':0, 'params':{'duration':duration}}]
    with pytest.raises(store.CanvasError, match='时长'):
        store.update_workflow(workflow['id'], 'video', document, 1)


@pytest.mark.parametrize('provider,model,remote_model', [
    ('ark','seedance-2.0','endpoint-20'), ('ark','seedance-2.5','endpoint-25'),
    ('cupsy','seedance-2.5','seedance-2.5'),
    ('cupsy','seedance-2.5-moderated','seedance-2.5-moderated'),
])
@pytest.mark.parametrize('form', [False, True])
@pytest.mark.parametrize('ratio', ['adaptive','16:9','4:3','1:1','3:4','9:16','21:9'])
def test_auto_480p_all_ratios_reach_actual_provider(monkeypatch, provider, model, remote_model, form, ratio):
    sent = configure(monkeypatch)
    workflow = canvas(provider)
    body = {'provider':provider, 'model':model, 'video_mode':'reference', 'prompt':'synthetic',
            'canvas_workflow_id':workflow['id'], 'project_settings_revision':1,
            'ratio':ratio, 'duration':-1, 'resolution':'480p'}
    client = application.app.test_client()
    if form:
        response = client.post('/api/video/generate', data={key:str(value) for key,value in body.items()}, content_type='multipart/form-data')
    else:
        response = client.post('/api/video/generate', json=body)
    assert response.status_code == (200 if provider == 'ark' else 202), response.json
    task_id = response.json['db_task_id']
    params = tasks.get_task(task_id)['params']
    assert (params['duration'], params['resolution'], params['ratio']) == (-1, '480p', ratio)
    if provider == 'cupsy':
        assert sent == []
        assert tasks.claim_next_task('video-options-test')['id'] == task_id
        assert application.poll_video_task_once(task_id)['state'] == 'pending'
    payload = sent[-1]
    assert (payload['duration'], payload['resolution'], payload['ratio'], payload['model']) == (-1, '480p', ratio, remote_model)
