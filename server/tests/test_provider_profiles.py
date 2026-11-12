"""Private provider configuration, immutable revisions and browser write boundaries."""
import json

from flask import Flask
import pytest

import provider_profiles as profiles
from provider_api import provider_api


@pytest.fixture
def client(isolated_backend):
    profiles.init_profiles_db()
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(provider_api)
    return app.test_client()


def payload(name='工作接口', **extra):
    return {'name': name, 'kind': 'image', 'adapter': 'ark', 'enabled': True,
            'settings': {'endpoint': 'https://example.test', 'model': 'test-model', 'request_timeout_seconds': 60},
            'api_key': 'private-test-secret', **extra}


def create(client, **extra):
    result = client.post('/api/provider-profiles', json=payload(**extra))
    assert result.status_code == 201
    assert 'private-test-secret' not in result.get_data(as_text=True)
    return result.json['profile']


def test_crud_redaction_and_immutable_old_revision(client):
    p = create(client)
    assert p['has_api_key'] and p['api_key_mask'] == '••••••••' and 'api_key' not in p
    first = profiles.load_profile(p['id'], 1)
    updated = client.patch(f"/api/provider-profiles/{p['id']}", json={'revision': 1, 'name': '新名称', 'api_key': '   '})
    assert updated.status_code == 200
    second = profiles.load_profile(p['id'])
    assert second['revision'] == 2 and second['api_key'] == first['api_key']
    assert second['asset_scope'] == first['asset_scope']
    assert profiles.load_profile(p['id'], 1) == first
    assert client.patch(f"/api/provider-profiles/{p['id']}", json={'revision': 1, 'name': '过期'}).status_code == 409
    listing = client.get('/api/provider-profiles')
    assert 'private-test-secret' not in listing.get_data(as_text=True)
    assert listing.json['profiles'][0]['name'] == '新名称'
    assert client.delete(f"/api/provider-profiles/{p['id']}", json={'revision': 2}).json['profile']['enabled'] is False
    with pytest.raises(profiles.ProfileError, match='停用'):
        profiles.load_profile(p['id'], kind='image', require_enabled=True)
    assert profiles.load_profile(p['id'], 1)['api_key'] == first['api_key']
    profiles.init_profiles_db()
    assert profiles.load_profile(p['id'], 1) == first


def test_rotate_clear_secret_and_scope(client):
    p = create(client)
    url = f"/api/provider-profiles/{p['id']}"
    rotated = client.patch(url, json={'revision': 1, 'api_key': 'second-private-secret'}).json['profile']  # secret-scan: allow (test fixture)
    assert rotated['asset_scope'] != p['asset_scope']
    assert profiles.load_profile(p['id'], 1)['api_key'] == 'private-test-secret'
    cleared = client.patch(url, json={'revision': 2, 'clear_api_key': True})
    assert cleared.status_code == 200 and not cleared.json['profile']['has_api_key']
    assert 'second-private-secret' not in cleared.get_data(as_text=True)
    with pytest.raises(profiles.ProfileError, match='密钥'):
        profiles.load_profile(p['id'], require_enabled=True)
    assert profiles.load_profile(p['id'], 2)['api_key'] == 'second-private-secret'


def test_multiple_named_profiles_defaults_and_kind(client):
    a = create(client, name='一号', is_default=True)
    b = create(client, name='二号', is_default=True)
    old = profiles.load_profile(a['id'])
    assert old['revision'] == 2 and not old['is_default']
    assert profiles.load_profile(a['id'], 1)['is_default'] is True
    assert profiles.load_profile(b['id'])['is_default'] is True
    assert client.patch(f"/api/provider-profiles/{a['id']}", json={'revision': 1, 'enabled': False}).status_code == 409
    assert client.post('/api/provider-profiles', json=payload(name='二号')).status_code == 409
    with pytest.raises(profiles.ProfileError, match='类型'):
        profiles.load_profile(b['id'], kind='video', require_enabled=True)
    assert len(client.get('/api/provider-profiles?kind=image').json['profiles']) == 2
    assert client.get('/api/provider-profiles?kind=video').json['profiles'] == []


@pytest.mark.parametrize('settings', [
    {'endpoint': 'https://user:secret@example.test'}, {'endpoint': 'https://example.test?key=private-test-secret'},
    {'endpoint': 'https://example.test#secret'}, {'endpoint': 'file:///etc/passwd'}, {'endpoint': 'https://example.test\\@evil.test'},
    {'endpoint': 'https://example.test', 'headers': {'Authorization': 'secret'}},
    {'endpoint': 'https://example.test', 'api_key': 'secret'},
    {'endpoint': 'https://example.test', 'request_timeout_seconds': True},
    {'endpoint': 'https://example.test', 'request_timeout_seconds': 999999},
    {'endpoint': 'https://example.test', 'source_base_url': 'https://source.test'},
])
def test_reject_unsafe_settings_without_leaking_input(client, settings):
    response = client.post('/api/provider-profiles', json=payload(settings=settings))
    assert response.status_code == 400
    assert 'private-test-secret' not in response.get_data(as_text=True)
    assert client.get('/api/provider-profiles').json['profiles'] == []


@pytest.mark.parametrize('change', [{'kind': 'video'}, {'adapter': 'cupsy'}, {'enabled': 'yes'}, {'clear_api_key': True, 'api_key': 'new'}, {'api_key': 'bad\nkey'}])
def test_reject_invalid_updates_without_mutation(client, change):
    p = create(client)
    before = profiles.load_profile(p['id'])
    result = client.patch(f"/api/provider-profiles/{p['id']}", json={'revision': 1, **change})
    assert result.status_code == 400
    assert profiles.load_profile(p['id']) == before


def test_same_origin_and_json_write_protection(client):
    for headers in ({'Origin': 'https://attacker.test'}, {'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': 'same-site'}):
        assert client.post('/api/provider-profiles', json=payload(), headers=headers).status_code == 403
    assert client.post('/api/provider-profiles', data={'name': 'form'}).status_code == 415
    assert client.post('/api/provider-profiles', json=payload(), headers={'Origin': 'http://localhost', 'Sec-Fetch-Site': 'same-origin'}).status_code == 201
    assert client.post('/api/provider-profiles', json=payload(name='代理'), headers={'Origin': 'https://localhost', 'X-Forwarded-Proto': 'https'}).status_code == 201
    assert client.post('/api/provider-profiles', data=b'x' * 33000, content_type='application/json').status_code == 413


def test_legitimate_adapter_combinations_and_scope_changes(client):
    for kind, adapter in [('image', 'ark'), ('image', 'cupsy'), ('video', 'ark'), ('video', 'cupsy'), ('audio', 'cupsy')]:
        settings = {'endpoint': 'https://example.test'}
        if adapter == 'cupsy': settings.update(source_base_url='https://source.test', asset_token_ttl_seconds=7200)
        if kind == 'video' and adapter == 'ark': settings.update(fast_model='ep-fast', seedance_2_5_model='ep-base')
        p = create(client, name=f'{kind}-{adapter}', kind=kind, adapter=adapter, settings=settings)
        assert profiles.load_profile(p['id'], kind=kind, require_enabled=True)['adapter'] == adapter
        changed = client.patch(f"/api/provider-profiles/{p['id']}", json={'revision': 1, 'settings': {'endpoint': 'https://other.test'}}).json['profile']
        assert changed['asset_scope'] != p['asset_scope']
    assert client.post('/api/provider-profiles', json=payload(kind='audio', adapter='ark')).status_code == 400
    unknown = client.post('/api/provider-profiles', json=payload(name='unknown', kind='image', adapter='acme'))
    assert unknown.status_code == 400 and '不受支持' in unknown.json['error']
    placeholder = client.post('/api/provider-profiles', json=payload(name='placeholder', kind='video', settings={
        'endpoint': 'https://example.test', 'seedance_2_5_model': 'ep-your-endpoint-id'}))
    assert placeholder.status_code == 400 and '占位' in placeholder.json['error']


def test_actual_application_auth(client, monkeypatch):
    import app as application
    monkeypatch.setattr(application, 'AUTH_CONFIG', {'username': 'profiles-test'})
    real = application.app.test_client()
    assert real.get('/api/provider-profiles').status_code == 401
    assert real.post('/api/provider-profiles', json=payload()).status_code == 401
    with real.session_transaction() as session:
        session['logged_in'] = True
    response = real.post('/api/provider-profiles', json=payload())
    assert response.status_code == 201
    assert 'private-test-secret' not in response.get_data(as_text=True)
    assert len(real.get('/api/provider-profiles').json['profiles']) == 1


def test_clear_optional_setting_and_safe_storage_error(client, monkeypatch):
    import sqlite3
    p = create(client)
    url = f"/api/provider-profiles/{p['id']}"
    updated = client.patch(url, json={'revision': 1, 'settings': {'request_timeout_seconds': None}})
    assert updated.status_code == 200
    assert 'request_timeout_seconds' not in updated.json['profile']['settings']
    assert client.patch(url, json={'revision': 2, 'settings': {'endpoint': None}}).status_code == 400
    assert client.patch(url, json={'revision': 2, 'settings': {'headers': None}}).status_code == 400
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('raw SQL with private-test-secret')
    monkeypatch.setattr(profiles, 'save_profile', fail)
    response = client.post('/api/provider-profiles', json=payload())
    assert response.status_code == 503
    assert 'private-test-secret' not in response.get_data(as_text=True)
    assert response.headers['Cache-Control'] == 'no-store'


def test_canvas_accepts_only_public_profile_references(client):
    import canvas_store
    p = create(client)
    parent = canvas_store.create_project('配置引用项目')
    workflow = canvas_store.create_workflow(parent['id'], '配置引用画布')
    doc = workflow['document']
    doc['nodes'] = [{'id': 'node', 'type': 'image', 'x': 0, 'y': 0, 'params': {'profile_id': p['id'], 'profile_revision': 1}}]
    saved = canvas_store.update_workflow(workflow['id'], workflow['title'], doc, 1)
    assert saved['document']['nodes'][0]['params'] == {'profile_id': p['id'], 'profile_revision': 1}
    doc['nodes'][0]['params']['api_key'] = 'private-test-secret'
    with pytest.raises(canvas_store.CanvasError):
        canvas_store.update_workflow(workflow['id'], workflow['title'], doc, 2)


@pytest.mark.parametrize('kind,model,stored', [
    ('image', '', ''), ('image', 'seedream-5.0-pro', 'seedream-5.0-pro'),
    ('audio', '', ''), ('audio', 'seed-audio-1.0', 'seed-audio-1.0'),
    ('video', '', ''), ('video', 'seedance-2.5', 'seedance-2.5'),
    ('video', 'seedance-2.5-moderated', 'seedance-2.5-moderated'),
    ('video', 'dreamina-seedance-2.5', 'seedance-2.5'),
])
def test_cupsy_profile_models_match_adapter_capabilities(client, kind, model, stored):
    p = create(client, kind=kind, adapter='cupsy', settings={'endpoint': 'https://example.test', 'model': model})
    assert p['settings']['model'] == stored
    assert profiles.load_profile(p['id'])['settings']['model'] == stored


@pytest.mark.parametrize('kind', ['image', 'video', 'audio'])
def test_cupsy_rejects_unsupported_model_on_create_and_edit(client, kind):
    data = payload(kind=kind, adapter='cupsy', settings={'endpoint': 'https://example.test', 'model': 'unsupported-model'})
    failed = client.post('/api/provider-profiles', json=data)
    assert failed.status_code == 400
    assert '仅支持' in failed.json['error']
    assert client.get('/api/provider-profiles').json['profiles'] == []
    p = create(client, kind=kind, adapter='cupsy', settings={'endpoint': 'https://example.test'})
    before = profiles.load_profile(p['id'])
    failed = client.patch(f"/api/provider-profiles/{p['id']}", json={'revision': 1, 'settings': {'model': 'unsupported-model'}})
    assert failed.status_code == 400
    assert profiles.load_profile(p['id']) == before


@pytest.mark.parametrize('ttl,accepted', [(1, False), (60, False), (7199, False), (7200, True), (86400, True), (86401, False), (True, False)])
def test_cupsy_asset_token_ttl_matches_signing_policy(client, ttl, accepted):
    data = payload(adapter='cupsy', settings={'endpoint': 'https://example.test', 'asset_token_ttl_seconds': ttl})
    response = client.post('/api/provider-profiles', json=data)
    assert response.status_code == (201 if accepted else 400)
    if accepted:
        assert response.json['profile']['settings']['asset_token_ttl_seconds'] == ttl
    else:
        assert '至少7200秒' in response.json['error']
        assert client.get('/api/provider-profiles').json['profiles'] == []
