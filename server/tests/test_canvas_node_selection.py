import copy
import io
import pytest

import app as application
import canvas_store as store
import tasks
from canvas_project_settings import validate_generation
from provider_profiles import save_profile
from test_canvas_generate_audio import configure


def make(kind='video', selected='explicit'):
    project = store.create_project('nodes')
    workflow = store.create_workflow(project['id'], 'canvas')
    node = {'id':'n', 'type':kind, 'x':0, 'y':0, 'params':{}}
    if selected == 'explicit':
        node['providerSelection'] = {'provider':'cupsy' if kind == 'audio' else 'ark', 'profile_id':None}
    elif selected is not None:
        node['providerSelection'] = selected
    document = workflow['document']
    document['nodes'] = [node]
    store.update_workflow(workflow['id'], 'canvas', document, 1)
    return project, store.workflow(workflow['id']), node


def request_for(workflow, node):
    selection = node.get('providerSelection') or {'provider':'ark', 'profile_id':None}
    return {'canvas_workflow_id':workflow['id'], 'canvas_node_id':node['id'],
            'canvas_workflow_revision':workflow['revision'], 'provider':selection['provider'],
            **({'profile_id':selection['profile_id']} if selection.get('profile_id') else {})}


def test_reference_order_and_selection_round_trip_with_stale_ids():
    _, workflow, node = make()
    node['referenceOrder'] = [f'{i:032x}' for i in range(600)]
    workflow['document']['nodes'] = [node]
    client = application.app.test_client()
    url = '/api/canvas/workflows/'+workflow['id']
    response = client.put(url, json={'title':'saved', 'document':workflow['document'], 'revision':2})
    assert response.status_code == 200
    assert client.get(url).json['workflow']['document']['nodes'][0] == node


@pytest.mark.parametrize('order', [None, 'a', ['a'], ['a'*32]*2, [True], ['G'*32], [f'{i:032x}' for i in range(601)]])
def test_invalid_reference_orders(order):
    _, workflow, node = make()
    node['referenceOrder'] = order
    workflow['document']['nodes'] = [node]
    with pytest.raises(store.CanvasError, match='排序'):
        store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)


@pytest.mark.parametrize('kind,selection', [
    ('video', []), ('video', {}), ('video', {'provider':'acme'}),
    ('video', {'provider':'ark', 'profile_id':'bad'}),
    ('video', {'provider':'ark', 'profile_revision':1}),
    ('image', {'provider':'unknown'}), ('audio', {'provider':'ark'}),
    ('text', {'provider':'ark'}), ('asset', {'provider':'ark'}),
])
def test_invalid_provider_selection_shape(kind, selection):
    with pytest.raises(store.CanvasError):
        make(kind, selection)


def test_asset_node_rejects_reference_order_before_asset_validation():
    _, workflow, node = make()
    node.update(type='asset', providerSelection=None, referenceOrder=['a'*32])
    workflow['document']['nodes'] = [node]
    with pytest.raises(store.CanvasError, match='排序'):
        store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)


def legacy_project_default(project_id, kind, provider):
    """Write a pre-2026-11-13 project default row directly; it must no longer be read."""
    providers = dict.fromkeys(('image', 'video', 'audio'))
    providers[kind] = {'provider':provider, 'profile_id':None}
    tasks.get_db().execute('INSERT OR REPLACE INTO canvas_project_generation_settings VALUES (?,?,?)',
                           (project_id, 1, __import__('json').dumps(providers)))
    tasks.get_db().commit()


@pytest.mark.parametrize('kind', ['image', 'video', 'audio'])
def test_node_without_selection_is_rejected_even_with_legacy_project_default(kind):
    project, workflow, node = make(kind, selected=None)
    node['params'] = {'provider':'cupsy', 'profile_id':'a'*32} if kind != 'image' else {}
    workflow['document']['nodes'] = [node]
    store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    workflow = store.workflow(workflow['id'])
    legacy_project_default(project['id'], kind, 'cupsy')
    provider = 'cupsy'
    for extra in [{}, {'project_settings_revision':1}, {'profile_id':'a'*32}]:
        with pytest.raises(store.CanvasError) as error:
            validate_generation({**request_for(workflow, node), 'provider':provider, **extra}, kind)
        assert error.value.status == 400
        assert str(error.value) == '请先为节点选择接口'


def test_explicit_selection_wins_over_legacy_project_default_and_ignores_its_revision():
    project, workflow, node = make('video')
    legacy_project_default(project['id'], 'video', 'cupsy')
    body = request_for(workflow, node)
    assert body['provider'] == 'ark'
    validate_generation(body, 'video')
    validate_generation({**body, 'project_settings_revision':0}, 'video')
    with pytest.raises(store.CanvasError) as error:
        validate_generation({**body, 'provider':'cupsy'}, 'video')
    assert error.value.status == 409


def test_project_generation_settings_routes_are_removed():
    project, _, _ = make()
    client = application.app.test_client()
    url = f"/api/canvas/projects/{project['id']}/generation-settings"
    assert client.get(url).status_code == 404
    assert client.put(url, json={'revision':0, 'providers':{'image':None,'video':None,'audio':None}}).status_code in (404, 405)


@pytest.mark.parametrize('form', [False, True])
def test_real_submission_without_selection_creates_no_task(monkeypatch, form):
    configure(monkeypatch)
    project, workflow, node = make('video', selected=None)
    legacy_project_default(project['id'], 'video', 'ark')
    body = {**request_for(workflow, node), 'project_settings_revision':1, 'prompt':'synthetic', 'video_mode':'reference'}
    client = application.app.test_client()
    before = tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0]
    if form:
        response = client.post('/api/video/generate', data={k:str(v) for k,v in body.items()}, content_type='multipart/form-data')
    else:
        response = client.post('/api/video/generate', json=body)
    assert response.status_code == 400
    assert response.json['error'] == '请先为节点选择接口'
    assert tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0] == before


@pytest.mark.parametrize('mutation,status', [
    ({'canvas_workflow_revision':1},409), ({'canvas_workflow_revision':True},409),
    ({'canvas_workflow_revision':None},409), ({'canvas_node_id':'missing'},404),
    ({'canvas_node_id':''},400), ({'provider':'cupsy'},409),
    ({'profile_id':'a'*32},409), ({'canvas_workflow_id':None},400),
])
def test_saved_node_context_required(mutation, status):
    _, workflow, node = make()
    with pytest.raises(store.CanvasError) as error:
        validate_generation({**request_for(workflow, node), **mutation}, 'video')
    assert error.value.status == status


def test_cross_workflow_and_type_do_not_select_foreign_node():
    _, workflow, node = make()
    project = store.create_project('other')
    other = store.create_workflow(project['id'], 'empty')
    with pytest.raises(store.CanvasError) as error:
        validate_generation({**request_for(workflow,node), 'canvas_workflow_id':other['id'], 'canvas_workflow_revision':1}, 'video')
    assert error.value.status == 404
    with pytest.raises(store.CanvasError) as error:
        validate_generation(request_for(workflow,node), 'image')
    assert error.value.status == 400


@pytest.mark.parametrize('state', ['disabled', 'missing', 'kind', 'adapter', 'no_key'])
def test_unavailable_profile_does_not_block_save_but_blocks_generation(state):
    profile = save_profile({'name':'synthetic', 'kind':'image' if state == 'kind' else 'video',
                            'adapter':'cupsy' if state == 'adapter' else 'ark',
                            'api_key':'' if state == 'no_key' else 'synthetic', 'settings':{'endpoint':'https://synthetic.invalid'}})
    if state == 'disabled':
        save_profile({'revision':profile['revision'], 'enabled':False}, profile['id'])
    profile_id = 'a'*32 if state == 'missing' else profile['id']
    _, workflow, node = make(selected={'provider':'ark', 'profile_id':profile_id})
    assert store.workflow(workflow['id'])['document']['nodes'][0] == node
    with pytest.raises(store.CanvasError):
        validate_generation(request_for(workflow,node), 'video')


@pytest.mark.parametrize('kind', ['image', 'video', 'audio'])
@pytest.mark.parametrize('form', [False, True])
def test_node_selection_real_submission_and_conflicts(monkeypatch, kind, form):
    configure(monkeypatch)
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {'api_key':'synthetic', 'endpoint':'https://ark.invalid', 'model':'synthetic'})
    monkeypatch.setattr(application, 'CUPSY_AUDIO_CONFIG', {'endpoint':'https://cupsy.invalid', 'model':'seed-audio-1.0'})
    project, workflow, node = make(kind)
    # Independent node remains valid whatever a legacy project default row says.
    legacy_project_default(project['id'], kind, 'cupsy')
    body = {**request_for(workflow,node), 'prompt':'synthetic', 'video_mode':'reference'}
    url = {'image':'/api/generate', 'video':'/api/video/generate', 'audio':'/api/audio/generate'}[kind]
    client = application.app.test_client()
    def post(data):
        if not form:
            return client.post(url, json=data)
        payload = {k:str(v) for k,v in data.items()}
        if kind == 'audio':
            from test_canvas_library_folders import image_bytes
            payload.update(reference_mode='image', references=(io.BytesIO(image_bytes('red')), 'reference.png'))
        return client.post(url, data=payload, content_type='multipart/form-data')
    before = tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0]
    assert post({**body, 'canvas_workflow_revision':0}).status_code == 409
    assert tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0] == before
    response = post(body)
    assert response.status_code == (200 if kind == 'video' else 202), response.json


def test_explicit_profile_task_revision_stays_frozen(monkeypatch):
    configure(monkeypatch)
    profile = save_profile({'name':'synthetic', 'kind':'video', 'adapter':'ark', 'api_key':'synthetic',
                            'settings':{'endpoint':'https://ark.invalid', 'model':'endpoint-20'}})
    _, workflow, node = make(selected={'provider':'ark', 'profile_id':profile['id']})
    client = application.app.test_client()
    response = client.post('/api/video/generate',json={**request_for(workflow,node),'prompt':'synthetic','video_mode':'reference'})
    assert response.status_code == 200, response.json
    task_id = response.json['db_task_id']
    params = copy.deepcopy(tasks.get_task(task_id)['params'])
    assert params['profile_id'] == profile['id'] and params['profile_revision'] == 1
    save_profile({'revision':1, 'enabled':False}, profile['id'])
    assert tasks.get_task(task_id)['params'] == params
    assert client.post('/api/video/generate',json={**request_for(workflow,node),'prompt':'synthetic'}).status_code == 409


def test_node_fields_do_not_bypass_global_login(monkeypatch):
    _, workflow, node = make()
    monkeypatch.setattr(application, 'AUTH_CONFIG', {'username':'synthetic','password':'synthetic'})
    response = application.app.test_client().post('/api/video/generate',json=request_for(workflow,node))
    assert response.status_code == 401


def test_two_nodes_choose_independently_and_requests_without_node_are_rejected():
    project, workflow, node = make()
    second = {**node, 'id':'second', 'providerSelection':{'provider':'cupsy','profile_id':None}}
    workflow['document']['nodes'] = [node, second]
    store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    saved = store.workflow(workflow['id'])
    validate_generation(request_for(saved,node), 'video')
    validate_generation(request_for(saved,second), 'video')
    with pytest.raises(store.CanvasError):
        validate_generation({**request_for(saved,second), 'provider':'ark'}, 'video')
    # Canvas requests without node context are rejected; there is no project fallback.
    legacy = {'canvas_workflow_id':workflow['id'],'provider':'ark','project_settings_revision':0}
    with pytest.raises(store.CanvasError) as error:
        validate_generation(legacy, 'video')
    assert error.value.status == 400
    # Noncanvas legacy API still works, but orphan context is rejected.
    validate_generation({'provider':'ark'}, 'video')
    with pytest.raises(store.CanvasError):
        validate_generation({'canvas_workflow_revision':saved['revision']}, 'video')


@pytest.mark.parametrize('mentions', [{}, {'[Image1]':'a'*32,'[Video2]':'b'*32,'[Audio999]':'c'*32},
                                     {f'[Image{i+1}]':f'{i:032x}' for i in range(600)}])
def test_reference_mentions_round_trip_stale_ids(mentions):
    _, workflow, node = make()
    node['referenceMentions'] = mentions
    workflow['document']['nodes'] = [node]
    store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    assert store.workflow(workflow['id'])['document']['nodes'][0]['referenceMentions'] == mentions


@pytest.mark.parametrize('mentions', [None, [], {'Image1':'a'*32}, {'[image1]':'a'*32},
    {'[Image0]':'a'*32}, {'[Video01]':'a'*32}, {'[Audio-1]':'a'*32}, {'[Image1]':'bad'},
    {'[Image1]':None}, {'[Image1]':'A'*32}, {f'[Image{i+1}]':f'{i:032x}' for i in range(601)}])
def test_reference_mentions_reject_invalid(mentions):
    _, workflow, node = make()
    node['referenceMentions'] = mentions
    workflow['document']['nodes'] = [node]
    with pytest.raises(store.CanvasError, match='提及'):
        store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)


def test_asset_node_cannot_have_mentions():
    _, workflow, node = make()
    node.update(type='asset', providerSelection=None, referenceMentions={'[Image1]':'a'*32})
    workflow['document']['nodes'] = [node]
    with pytest.raises(store.CanvasError, match='提及'):
        store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
