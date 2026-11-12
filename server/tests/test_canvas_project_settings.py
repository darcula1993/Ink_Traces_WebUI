import pytest
import app as application
import canvas_store as store
from canvas_project_settings import get_settings, update_settings, validate_generation
from provider_profiles import save_profile


def selection(provider='ark', profile_id=None):
    return {'image': {'provider': provider, 'profile_id': profile_id}, 'video': None, 'audio': None}


def project():
    p = store.create_project('test')
    w = store.create_workflow(p['id'], 'workflow')
    return p['id'], w['id']


def test_api_persistence_conflict_and_project_isolation():
    p, w = project()
    other, _ = project()
    client = application.app.test_client()
    url = f'/api/canvas/projects/{p}/generation-settings'
    assert client.get(url).json['settings'] == {'revision': 0, 'providers': {'image': None, 'video': None, 'audio': None}}
    before = store.workflow(w)
    response = client.put(url, json={'revision': 0, 'providers': selection()})
    assert response.status_code == 200
    assert response.json['settings']['revision'] == 1
    assert client.put(url, json={'revision': 0, 'providers': selection('cupsy')}).status_code == 409
    assert client.put(url, json={'revision': 1, 'providers': selection('acme')}).status_code == 400
    assert get_settings(p)['providers'] == selection()
    assert get_settings(other)['revision'] == 0
    assert store.workflow(w) == before
    assert client.get('/api/canvas/projects/missing/generation-settings').status_code == 404


@pytest.mark.parametrize('multipart', [False, True])
def test_generation_request_rejects_stale_node_override_and_other_project(multipart):
    p, w = project()
    other, foreign = project()
    update_settings(p, {'revision': 0, 'providers': selection()})
    client = application.app.test_client()
    def post(data):
        return client.post('/api/generate', data={k: str(v) for k,v in data.items()}, content_type='multipart/form-data') if multipart else client.post('/api/generate', json=data)
    base = {'canvas_workflow_id': w, 'project_settings_revision': 1, 'provider': 'ark', 'prompt': 'test'}
    assert post({**base, 'provider': 'acme'}).status_code == 409
    assert post({**base, 'project_settings_revision': 0}).status_code == 409
    assert post({**base, 'canvas_workflow_id': foreign}).status_code == 409
    assert post({**base, 'profile_id': 'node-override'}).status_code == 409
    validate_generation(base, 'image')
    validate_generation({'provider': 'ark'}, 'image')  # legacy API remains independent


@pytest.mark.parametrize('providers', [{}, {'image': [], 'video': None, 'audio': None}, {'image': {'provider': 'bad'}, 'video': None, 'audio': None}])
def test_invalid_settings(providers):
    p, _ = project()
    with pytest.raises(store.CanvasError):
        update_settings(p, {'revision': 0, 'providers': providers})


def test_profile_validation_and_disable_blocks_generation():
    p, w = project()
    profile = save_profile({'name': 'test', 'kind': 'image', 'adapter': 'ark', 'api_key': 'synthetic-key', 'settings': {'endpoint': 'https://example.invalid'}})
    update_settings(p, {'revision': 0, 'providers': selection('ark', profile['id'])})
    with pytest.raises(store.CanvasError):
        update_settings(p, {'revision': 1, 'providers': selection('acme', profile['id'])})
    save_profile({'revision': profile['revision'], 'enabled': False}, profile['id'])
    with pytest.raises(store.CanvasError):
        validate_generation({'canvas_workflow_id': w, 'project_settings_revision': 1, 'provider': 'ark', 'profile_id': profile['id']}, 'image')
