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


def test_logical_delete_frees_name_preserves_history_and_isolates_sync(client):
    first = create(client, name='可删除账号', is_default=True, api_key='test-key-first')
    peer = create(client, name='同适配器留存账号', kind='video', adapter='ark', api_key='test-key-peer')
    rev1_snapshot = profiles.load_profile(first['id'], 1)

    # Extra or missing fields rejected with 400; stale/invalid revision rejected with 409.
    assert client.delete(f"/api/provider-profiles/{first['id']}", json={}).status_code == 400
    assert client.delete(f"/api/provider-profiles/{first['id']}", json={'revision': 1, 'extra': 1}).status_code == 400
    for bad_rev in (0, -1, 2, True, '1'):
        res = client.delete(f"/api/provider-profiles/{first['id']}", json={'revision': bad_rev})
        assert res.status_code == 409 and '重新载入' in res.json['error']

    # Valid logical delete.
    deleted = client.delete(f"/api/provider-profiles/{first['id']}", json={'revision': 1})
    assert deleted.status_code == 200
    body = deleted.json
    assert body['success'] is True and body['deleted'] is True
    assert body['profile']['enabled'] is False
    assert body['profile']['is_default'] is False
    assert body['profile']['deleted'] is True
    assert body['profile']['deleted_at']
    assert body['profile']['name'] == '可删除账号'
    assert body['profile']['has_api_key'] is False
    assert 'test-key-first' not in deleted.get_data(as_text=True)

    # Disappears from list; GET/PATCH/DELETE return 404; require_enabled returns 409.
    listed_ids = [item['id'] for item in client.get('/api/provider-profiles').json['profiles']]
    assert first['id'] not in listed_ids
    assert client.get('/api/provider-profiles?kind=image').json['profiles'] == []
    assert client.get(f"/api/provider-profiles/{first['id']}").status_code == 404
    assert client.patch(f"/api/provider-profiles/{first['id']}", json={'revision': 2, 'name': '复活'}).status_code == 404
    assert client.delete(f"/api/provider-profiles/{first['id']}", json={'revision': 2}).status_code == 404
    with pytest.raises(profiles.ProfileError, match='停用') as exc_info:
        profiles.load_profile(first['id'], kind='image', require_enabled=True)
    assert exc_info.value.status == 409

    # Immutable historical revision still loads for in-flight tasks/retries/Cupsy assets.
    assert profiles.load_profile(first['id'], 1) == rev1_snapshot
    tombstone = profiles.load_profile(first['id'], allow_deleted=True)
    assert tombstone['revision'] == 2 and tombstone['api_key'] == '' and tombstone['deleted_at']

    # Original (kind, name) and default slot are freed immediately.
    recreated = create(client, name='可删除账号', is_default=True, api_key='test-key-recreated')
    assert recreated['id'] != first['id'] and recreated['name'] == '可删除账号' and recreated['is_default'] is True

    # Same-adapter API key sync must skip deleted profiles.
    synced = client.patch(
        f"/api/provider-profiles/{peer['id']}",
        json={'revision': peer['revision'], 'api_key': 'test-key-synced', 'sync_adapter_api_key': True},
    )
    assert synced.status_code == 200
    assert first['id'] not in synced.json['synced_profile_ids']
    assert recreated['id'] in synced.json['synced_profile_ids']
    tombstone_after = profiles.load_profile(first['id'], allow_deleted=True)
    assert tombstone_after['revision'] == 2 and tombstone_after['api_key'] == ''


def test_delete_system_default_profiles_no_reimport_no_fallback_and_custom_default(isolated_backend, monkeypatch):
    import copy
    import app as application
    import canvas_submit
    import config_v2
    import profile_runtime

    cfg = copy.deepcopy(config_v2.DEFAULTS)
    cfg['providers']['byteplus']['api_key'] = 'cfg-ark-secret'
    cfg['providers']['byteplus']['endpoint'] = 'https://ark.cfg.invalid/'
    cfg['providers']['byteplus']['endpoint_ids']['seedance_2_5'] = 'ep-cfg-seedance25'
    cfg['providers']['cupsy']['api_key'] = 'cfg-cupsy-secret'
    cfg['providers']['cupsy']['endpoint'] = 'https://cupsy.cfg.invalid/'
    cfg['generation']['image']['byteplus']['model'] = 'dola-seedream-5-5-261028'
    cfg['generation']['video']['byteplus']['model'] = 'ep-cfg-v20'

    # Give fallback configs real-looking keys to prove deleting config:* NEVER falls back to config.json.
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', profile_runtime.ProfileConfig(
        {'api_key': 'fallback-ark-key', 'endpoint': 'https://fallback-ark.invalid', 'model': 'seedream-5-0-pro'},
        'ark', kind='image',
    ))
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', profile_runtime.ProfileConfig(
        {'api_key': 'fallback-ark-key', 'endpoint': 'https://fallback-ark.invalid',
         'model': 'ep-fallback', 'seedance_2_5_model': 'ep-fallback-25'},
        'ark', kind='video',
    ))
    monkeypatch.setitem(application.config['providers']['byteplus']['endpoint_ids'], 'seedance_2_5', 'ep-fallback-25')

    profiles.sync_config_profiles(cfg)
    app_client = application.app.test_client()
    by_key = {p['source_key']: p for p in profiles.list_profiles() if p.get('source_key')}
    img_ark = by_key['config:image:ark']
    vid_ark = by_key['config:video:ark']

    assert app_client.get('/api/provider').get_json()['providers']['ark']['available'] is True
    assert app_client.get('/api/video/provider').get_json()['providers']['ark']['available'] is True
    assert app_client.get('/api/video/provider').get_json()['providers']['ark']['seedance_2_5_configured'] is True

    # Delete both config:image:ark and config:video:ark.
    for target in (img_ark, vid_ark):
        res = app_client.delete(f"/api/provider-profiles/{target['id']}", json={'revision': target['revision']})
        assert res.status_code == 200
        assert res.json['deleted'] is True and res.json['profile']['deleted'] is True
        # Historical revision remains readable for in-flight tasks/retries.
        assert profiles.load_profile(target['id'], 1)['api_key'] == 'cfg-ark-secret'

    # Restart / sync_config_profiles must NEVER re-import deleted config:* rows.
    assert profiles.sync_config_profiles(cfg) == []
    remaining_keys = {p['source_key'] for p in profiles.list_profiles() if p.get('source_key')}
    assert 'config:image:ark' not in remaining_keys and 'config:video:ark' not in remaining_keys

    # Runtime endpoints must NOT fall back to config.json; both Ark endpoints become unavailable.
    img_info = app_client.get('/api/provider').get_json()
    vid_info = app_client.get('/api/video/provider').get_json()
    assert img_info['providers']['ark']['available'] is False
    assert img_info['providers']['ark']['managed_by_profiles'] is True
    assert vid_info['providers']['ark']['available'] is False
    assert vid_info['providers']['ark']['seedance_2_5_configured'] is False
    assert vid_info['providers']['ark']['managed_by_profiles'] is True
    assert application.deployment_seedance_25_endpoint() == ''
    with application.app.test_request_context():
        caps = canvas_submit.live_capabilities()
        assert all(o['provider'] != 'ark' for o in caps['image'])
        assert all(o['provider'] != 'ark' for o in caps['video'])

    # User can immediately recreate profiles with the exact same names and set them as default.
    new_img = app_client.post('/api/provider-profiles', json={
        'name': img_ark['name'], 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'is_default': True,
        'settings': {'endpoint': 'https://custom-ark.invalid', 'model': 'dola-seedream-5-5-261028'},
        'api_key': 'test-key-custom-img',
    })
    assert new_img.status_code == 201
    new_vid = app_client.post('/api/provider-profiles', json={
        'name': vid_ark['name'], 'kind': 'video', 'adapter': 'ark', 'enabled': True, 'is_default': True,
        'settings': {'endpoint': 'https://custom-ark.invalid', 'model': 'ep-custom-v20', 'seedance_2_5_model': 'ep-custom-25'},
        'api_key': 'test-key-custom-vid',
    })
    assert new_vid.status_code == 201

    assert application.API_PROVIDERS['ark']['api_key'] == 'test-key-custom-img'
    assert app_client.get('/api/provider').get_json()['providers']['ark']['available'] is True
    vid_info2 = app_client.get('/api/video/provider').get_json()
    assert vid_info2['providers']['ark']['available'] is True
    assert vid_info2['providers']['ark']['seedance_2_5_configured'] is True
    assert application.deployment_seedance_25_endpoint() == 'ep-custom-25'
    # Canvas capabilities show ONLY the user's custom profiles and NEVER resurrect "（原配置）".
    with application.app.test_request_context():
        caps2 = canvas_submit.live_capabilities()
        img_arks = [o for o in caps2['image'] if o['provider'] == 'ark']
        vid_arks = [o for o in caps2['video'] if o['provider'] == 'ark']
        assert [o['id'] for o in img_arks] == [f"profile:{new_img.json['profile']['id']}"]
        assert [o['id'] for o in vid_arks] == [f"profile:{new_vid.json['profile']['id']}"]


def test_init_profiles_db_adds_deleted_at_to_legacy_table(client):
    import tasks as task_db
    db = task_db.get_db()
    db.executescript('''
        DROP TABLE IF EXISTS provider_profile_revisions;
        DROP TABLE IF EXISTS provider_profiles;
        CREATE TABLE provider_profiles (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL, kind TEXT NOT NULL,
            adapter TEXT NOT NULL, name TEXT NOT NULL, enabled INTEGER NOT NULL,
            is_default INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            source_key TEXT,
            UNIQUE(kind, name)
        );
        CREATE TABLE provider_profile_revisions (
            profile_id TEXT NOT NULL, revision INTEGER NOT NULL, private_document TEXT NOT NULL,
            PRIMARY KEY(profile_id, revision),
            FOREIGN KEY(profile_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT
        );
    ''')
    db.commit()
    profiles.init_profiles_db()
    cols = {row['name'] for row in db.execute('PRAGMA table_info(provider_profiles)').fetchall()}
    assert 'deleted_at' in cols
    created = create(client, name='旧库迁移测试')
    assert client.delete(f"/api/provider-profiles/{created['id']}", json={'revision': 1}).status_code == 200
    assert profiles.load_profile(created['id'], 1)['name'] == '旧库迁移测试'
