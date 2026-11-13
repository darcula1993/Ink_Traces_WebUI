"""Canvas audio node options: saved-document whitelist and the Cupsy request they produce."""
import io

import pytest

import app as application
import canvas_store as store
import tasks
from test_generation import FakeResponse


def audio_canvas(params=None):
    project = store.create_project('audio params')
    workflow = store.create_workflow(project['id'], 'audio')
    document = workflow['document']
    document['nodes'] = [{'id':'a','type':'audio','title':'audio','x':0,'y':0,'params':params or {},
                          'providerSelection':{'provider':'cupsy','profile_id':None}}]
    store.update_workflow(workflow['id'], 'audio', document, workflow['revision'])
    return store.workflow(workflow['id'])


def put(workflow, kind, params):
    document = workflow['document']
    document['nodes'] = [{'id':'a','type':kind,'title':kind,'x':0,'y':0,'params':params}]
    return application.app.test_client().put(f"/api/canvas/workflows/{workflow['id']}",
                                             json={'title':'audio','document':document,'revision':workflow['revision']})


def test_store_values_match_provider_constants():
    assert set(store.AUDIO_SPEAKERS) == application.CUPSY_AUDIO_SPEAKERS
    assert set(store.AUDIO_FORMATS) == set(application.CUPSY_AUDIO_FORMATS)
    assert set(store.AUDIO_SAMPLE_RATES) == application.CUPSY_AUDIO_SAMPLE_RATES


@pytest.mark.parametrize('params', [
    {},
    {'speaker':'', 'output_format':'mp3', 'sample_rate':48000, 'enable_subtitle':True},
    {'speaker':'vivi', 'output_format':'wav', 'sample_rate':8000, 'enable_subtitle':False},
    {'speaker':'opal', 'output_format':'ogg_opus', 'sample_rate':44100},
    {'speaker':None},
])
def test_audio_params_save_and_reload(params):
    workflow = audio_canvas()
    response = put(workflow, 'audio', params)
    assert response.status_code == 200, response.json
    saved = application.app.test_client().get(f"/api/canvas/workflows/{workflow['id']}").json['workflow']['document']['nodes'][0]['params']
    assert saved == params


@pytest.mark.parametrize('params, message', [
    ({'speaker':'nobody'}, '预设声线'),
    ({'speaker':'VIVI'}, '预设声线'),
    ({'speaker':1}, '预设声线'),
    ({'output_format':'flac'}, '音频格式'),
    ({'output_format':'png'}, '音频格式'),
    ({'sample_rate':22050}, '采样率'),
    ({'sample_rate':'48000'}, '采样率'),
    ({'sample_rate':True}, '采样率'),
    ({'enable_subtitle':'true'}, '字幕开关'),
    ({'enable_subtitle':1}, '字幕开关'),
])
def test_audio_params_reject_invalid_values(params, message):
    workflow = audio_canvas()
    response = put(workflow, 'audio', params)
    assert response.status_code == 400
    assert message in response.json['error']


@pytest.mark.parametrize('kind', ['image', 'video'])
@pytest.mark.parametrize('key, value', [('speaker','vivi'), ('sample_rate',48000), ('enable_subtitle',True)])
def test_audio_only_params_rejected_on_other_nodes(kind, key, value):
    workflow = audio_canvas()
    response = put(workflow, kind, {key:value})
    assert response.status_code == 400
    assert '音频生成节点' in response.json['error']


def test_image_output_format_unchanged():
    workflow = audio_canvas()
    assert put(workflow, 'image', {'output_format':'png'}).status_code == 200
    workflow = store.workflow(workflow['id'])
    assert put(workflow, 'image', {'output_format':'mp3'}).status_code == 400


def configure(monkeypatch):
    monkeypatch.setattr(application, 'CUPSY_VIDEO_CONFIG', {
        'api_key':'synthetic', 'endpoint':'https://cupsy.invalid', 'source_base_url':'https://studio.invalid'})
    monkeypatch.setattr(application, 'CUPSY_AUDIO_CONFIG', {'endpoint':'https://cupsy.invalid', 'model':'seed-audio-1.0'})
    sent = []
    def post(url, **kwargs):
        sent.append({'url':url, 'headers':kwargs['headers'], 'json':kwargs['json']})
        return FakeResponse(status_code=202, payload={'id':'synthetic-audio', 'status':'queued'})
    monkeypatch.setattr(application.HTTP, 'post', post)
    return sent


def submit_form(workflow, fields):
    # Same request shapes as client/src/lib/canvasApi.js for audio nodes.
    data = {'prompt':'synthetic voice line', 'canvas_workflow_id':workflow['id'], 'canvas_node_id':'a',
            'canvas_workflow_revision':str(workflow['revision']), 'provider':'cupsy', 'model':'seed-audio-1.0', **fields}
    client = application.app.test_client()
    if 'references' not in fields:
        # Without reference files canvasApi.js posts typed JSON.
        return client.post('/api/audio/generate', json={**data, 'canvas_workflow_revision':workflow['revision']})
    return client.post('/api/audio/generate', data=data, content_type='multipart/form-data')


def poll(task_id):
    assert tasks.claim_next_task('audio-worker')['id'] == task_id
    return application.poll_audio_task_once(task_id)


@pytest.mark.parametrize('speaker, fmt, rate, subtitle', [
    ('vivi', 'wav', 8000, False),
    ('jess', 'ogg_opus', 24000, True),
    ('', 'mp3', 48000, True),
])
def test_canvas_audio_params_reach_cupsy_request(monkeypatch, speaker, fmt, rate, subtitle):
    sent = configure(monkeypatch)
    workflow = audio_canvas({'speaker':speaker, 'output_format':fmt, 'sample_rate':rate, 'enable_subtitle':subtitle})
    response = submit_form(workflow, {'speaker':speaker, 'output_format':fmt, 'sample_rate':rate,
                                      'enable_subtitle':subtitle, 'reference_mode':'none'})
    assert response.status_code == 202, response.json
    task_id = response.json['task_id']
    assert poll(task_id)['state'] == 'pending'
    assert len(sent) == 1
    request = sent[0]
    assert request['url'] == 'https://cupsy.invalid/v1/audio/generations'
    assert request['headers']['Idempotency-Key'] == f'nanobanana-audio-{task_id}'
    assert request['json']['audio_config'] == {'format':fmt, 'sample_rate':rate, 'enable_subtitle':subtitle}
    if speaker:
        assert request['json']['references'] == [{'speaker':speaker}]
    else:
        assert 'references' not in request['json']


def test_canvas_audio_defaults_unchanged(monkeypatch):
    sent = configure(monkeypatch)
    workflow = audio_canvas()
    # canvasApi.js defaults when the node leaves options unset.
    response = submit_form(workflow, {'output_format':'mp3', 'sample_rate':48000, 'enable_subtitle':True, 'reference_mode':'none'})
    assert response.status_code == 202, response.json
    assert poll(response.json['task_id'])['state'] == 'pending'
    body = sent[0]['json']
    assert body['audio_config'] == {'format':'mp3', 'sample_rate':48000, 'enable_subtitle':True}
    assert 'references' not in body


def wav_upload(name):
    return (io.BytesIO(b'RIFF$\x00\x00\x00WAVEfmt ' + name.encode()), f'{name}.wav')


def test_speaker_counts_toward_three_reference_limit(monkeypatch):
    sent = configure(monkeypatch)
    workflow = audio_canvas({'speaker':'kian'})
    before = tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0]
    response = submit_form(workflow, {'speaker':'kian', 'reference_mode':'audio',
                                      'references':[wav_upload('one'), wav_upload('two'), wav_upload('three')]})
    assert response.status_code == 400
    assert '最多支持 3 个' in response.json['error']
    assert tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0] == before
    assert sent == []


def test_speaker_with_image_reference_rejected(monkeypatch):
    sent = configure(monkeypatch)
    workflow = audio_canvas({'speaker':'mindy'})
    from test_canvas_library_folders import image_bytes
    before = tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0]
    response = submit_form(workflow, {'speaker':'mindy', 'reference_mode':'image',
                                      'references':(io.BytesIO(image_bytes('red')), 'reference.png')})
    assert response.status_code == 400
    assert '图片参考' in response.json['error']
    assert tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0] == before
    assert sent == []


def test_invalid_speaker_rejected_at_submission(monkeypatch):
    sent = configure(monkeypatch)
    workflow = audio_canvas()
    response = submit_form(workflow, {'speaker':'nobody', 'reference_mode':'none'})
    assert response.status_code == 400
    assert sent == []


def test_speaker_with_audio_files_uses_multipart_strings(monkeypatch):
    sent = configure(monkeypatch)
    workflow = audio_canvas({'speaker':'vivi', 'output_format':'wav', 'sample_rate':16000, 'enable_subtitle':False})
    response = submit_form(workflow, {'speaker':'vivi', 'output_format':'wav', 'sample_rate':'16000', 'enable_subtitle':'false',
                                      'reference_mode':'audio', 'references':[wav_upload('one'), wav_upload('two')]})
    assert response.status_code == 202, response.json
    task_id = response.json['task_id']
    params = tasks.get_task(task_id)['params']
    assert (params['speaker'], params['output_format'], params['sample_rate'], params['enable_subtitle']) == ('vivi', 'wav', 16000, False)
    # Uploaded references must finish importing before the Cupsy generation request is sent.
    assert poll(task_id)['state'] == 'preparing'
    assert all(item['url'] != 'https://cupsy.invalid/v1/audio/generations' for item in sent)
    for index, asset in enumerate(tasks.list_task_provider_assets(task_id), 1):
        tasks.update_provider_asset(asset['id'], external_asset_id=f'asset_{index}', asset_uri=f'asset://asset_{index}',
                                    status='active', next_run_at=None)
    sent.clear()
    assert application.poll_audio_task_once(task_id)['state'] == 'pending'
    assert [item['url'] for item in sent] == ['https://cupsy.invalid/v1/audio/generations']
    body = sent[0]['json']
    assert body['references'] == [{'speaker':'vivi'}, {'audio_url':'asset://asset_1'}, {'audio_url':'asset://asset_2'}]
    assert body['audio_config'] == {'format':'wav', 'sample_rate':16000, 'enable_subtitle':False}
