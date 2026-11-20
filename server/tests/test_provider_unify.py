"""PROVIDER-UNIFY-20261120: config.json auto-import, live DB runtime config, key sync and dedup."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import app as application
import canvas_project_settings
import canvas_store
import canvas_submit
import config_v2
import profile_runtime
import provider_profiles as profiles
import tasks as task_db


def sample_config(**overrides):
    cfg = copy.deepcopy(config_v2.DEFAULTS)
    cfg['providers']['byteplus']['api_key'] = 'cfg-ark-secret'
    cfg['providers']['byteplus']['endpoint'] = 'https://ark.cfg.invalid/'
    cfg['providers']['byteplus']['endpoint_ids']['seedance_2_5'] = 'ep-cfg-seedance25'
    cfg['providers']['byteplus']['request_timeout_seconds'] = 420
    cfg['providers']['byteplus']['upload_timeout_seconds'] = 90
    cfg['providers']['cupsy']['api_key'] = 'cfg-cupsy-secret'
    cfg['providers']['cupsy']['endpoint'] = 'https://cupsy.cfg.invalid/'
    cfg['providers']['cupsy']['request_timeout_seconds'] = 110
    cfg['generation']['image']['byteplus']['model'] = 'dola-seedream-5-5-261028'
    cfg['generation']['image']['cupsy']['poll_max_attempts'] = 900
    cfg['generation']['video']['byteplus']['model'] = 'ep-cfg-v20'
    cfg['generation']['video']['byteplus']['fast_model'] = 'ep-cfg-v20-fast'
    cfg['generation']['video']['cupsy']['model'] = 'seedance-2.5'
    cfg['generation']['video']['poll_interval_seconds'] = 6
    cfg['generation']['video']['poll_max_attempts'] = 1200
    cfg['generation']['audio']['cupsy']['model'] = 'seed-audio-1.0'
    cfg['generation']['audio']['poll_interval_seconds'] = 5
    cfg['generation']['audio']['poll_max_attempts'] = 800
    cfg['deployment']['cupsy_source']['base_url'] = 'https://source.cfg.invalid/'
    cfg['deployment']['cupsy_source']['asset_token_ttl_seconds'] = 14400
    for key, value in overrides.items():
        cfg[key] = value
    return cfg


def by_source_key():
    return {p['source_key']: p for p in profiles.list_profiles() if p.get('source_key')}


def test_sync_config_profiles_imports_all_five_idempotently_without_overwriting_edits():
    cfg = sample_config()
    created = profiles.sync_config_profiles(cfg)
    assert len(created) == 5
    assert 'cfg-ark-secret' not in json.dumps(created)
    assert 'cfg-cupsy-secret' not in json.dumps(created)

    mapped = by_source_key()
    assert set(mapped) == {
        'config:image:ark', 'config:image:cupsy',
        'config:video:ark', 'config:video:cupsy', 'config:audio:cupsy',
    }
    assert all(p['is_system_default'] is True and p['enabled'] is True and p['has_api_key'] is True for p in mapped.values())
    assert all(p['api_key_mask'] == '••••••••' and 'api_key' not in p for p in mapped.values())

    assert mapped['config:image:ark']['settings']['endpoint'] == 'https://ark.cfg.invalid'
    assert mapped['config:image:ark']['settings']['model'] == 'dola-seedream-5-5-261028'
    assert mapped['config:image:ark']['settings']['request_timeout_seconds'] == 420
    assert mapped['config:image:ark']['settings']['upload_timeout_seconds'] == 90

    assert mapped['config:image:cupsy']['settings']['endpoint'] == 'https://cupsy.cfg.invalid'
    assert mapped['config:image:cupsy']['settings']['model'] == 'seedream-5.0-pro'
    assert mapped['config:image:cupsy']['settings']['source_base_url'] == 'https://source.cfg.invalid'
    assert mapped['config:image:cupsy']['settings']['asset_token_ttl_seconds'] == 14400
    assert mapped['config:image:cupsy']['settings']['poll_max_attempts'] == 900

    assert mapped['config:video:ark']['settings']['model'] == 'ep-cfg-v20'
    assert mapped['config:video:ark']['settings']['fast_model'] == 'ep-cfg-v20-fast'
    assert mapped['config:video:ark']['settings']['seedance_2_5_model'] == 'ep-cfg-seedance25'
    assert mapped['config:video:ark']['settings']['poll_interval_seconds'] == 6
    assert mapped['config:video:ark']['settings']['poll_max_attempts'] == 1200

    assert mapped['config:video:cupsy']['settings']['model'] == 'seedance-2.5'
    assert mapped['config:video:cupsy']['settings']['source_base_url'] == 'https://source.cfg.invalid'
    assert mapped['config:audio:cupsy']['settings']['model'] == 'seed-audio-1.0'
    assert mapped['config:audio:cupsy']['settings']['poll_interval_seconds'] == 5

    # User edits one imported profile; a subsequent sync with modified config must NEVER overwrite it.
    img_ark = mapped['config:image:ark']
    updated = profiles.save_profile(
        {'revision': img_ark['revision'], 'name': '我的主图像账号', 'api_key': 'fake-override',
         'settings': {'model': 'seedream-5-0-pro'}},
        img_ark['id'],
    )
    assert updated['revision'] == 2 and updated['source_key'] == 'config:image:ark'

    cfg2 = sample_config()
    cfg2['providers']['byteplus']['api_key'] = 'fake-other'
    cfg2['generation']['image']['byteplus']['model'] = 'dola-seedream-5-5-261028'
    assert profiles.sync_config_profiles(cfg2) == []

    loaded = profiles.load_profile(img_ark['id'])
    assert loaded['name'] == '我的主图像账号'
    assert loaded['api_key'] == 'fake-override'
    assert loaded['settings']['model'] == 'seedream-5-0-pro'
    assert loaded['revision'] == 2


def test_sync_omits_placeholder_seedance_25_and_handles_name_collision_and_schema_migration():
    # Simulate legacy provider_profiles table lacking source_key column + pre-existing conflicting name.
    db = task_db.get_db()
    db.executescript('''
        DROP TABLE IF EXISTS provider_profile_revisions;
        DROP TABLE IF EXISTS provider_profiles;
        CREATE TABLE provider_profiles (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL, kind TEXT NOT NULL,
            adapter TEXT NOT NULL, name TEXT NOT NULL, enabled INTEGER NOT NULL,
            is_default INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
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
    existing = profiles.save_profile({
        'name': 'BytePlus 图像（默认）', 'kind': 'image', 'adapter': 'ark',
        'settings': {'endpoint': 'https://custom.invalid'}, 'api_key': 'custom-key',
    })
    assert existing['source_key'] is None and existing['is_system_default'] is False

    cfg = sample_config()
    cfg['providers']['byteplus']['endpoint_ids']['seedance_2_5'] = 'ep-your-endpoint-id'
    cfg['providers']['byteplus']['request_timeout_seconds'] = 99999  # out of bounds -> omitted safely
    cfg['deployment']['cupsy_source']['asset_token_ttl_seconds'] = 999999  # out of bounds -> omitted safely
    profiles.sync_config_profiles(cfg)

    mapped = by_source_key()
    assert len(mapped) == 5
    assert mapped['config:image:ark']['name'] != existing['name']
    assert 'seedance_2_5_model' not in mapped['config:video:ark']['settings']
    assert 'request_timeout_seconds' not in mapped['config:image:ark']['settings']
    assert 'asset_token_ttl_seconds' not in mapped['config:video:cupsy']['settings']


def test_concurrent_sync_config_profiles_is_safe():
    cfg = sample_config()

    def run(_index):
        try:
            return profiles.sync_config_profiles(cfg)
        finally:
            task_db.close_db()

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(run, range(4)))
    assert sum(len(item) for item in results) == 5
    assert len(by_source_key()) == 5


def test_runtime_reads_latest_db_without_restart_and_never_falls_back_when_disabled_or_cleared(monkeypatch):
    # Give fallback configs real-looking keys to prove disabled/cleared DB profiles NEVER leak fallback keys.
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', profile_runtime.ProfileConfig(
        {'api_key': 'fallback-ark-key', 'endpoint': 'https://fallback-ark.invalid', 'model': 'seedream-5-0-pro'},
        'ark', kind='image',
    ))
    monkeypatch.setitem(application.API_PROVIDERS, 'cupsy', profile_runtime.ProfileConfig(
        {'api_key': 'fallback-cupsy-key', 'endpoint': 'https://fallback-cupsy.invalid', 'model': 'seedream-5.0-pro'},
        'cupsy', kind='image',
    ))
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', profile_runtime.ProfileConfig(
        {'api_key': 'fallback-ark-key', 'endpoint': 'https://fallback-ark.invalid',
         'model': 'ep-fallback', 'seedance_2_5_model': 'ep-fallback-25'},
        'ark', kind='video',
    ))
    monkeypatch.setattr(application, 'CUPSY_VIDEO_CONFIG', profile_runtime.ProfileConfig(
        {'api_key': 'fallback-cupsy-key', 'endpoint': 'https://fallback-cupsy.invalid',
         'source_base_url': 'https://fallback-src.invalid', 'model': 'seedance-2.5'},
        'cupsy', kind='video',
    ))
    monkeypatch.setattr(application, 'CUPSY_AUDIO_CONFIG', profile_runtime.ProfileConfig(
        {'api_key': 'fallback-cupsy-key', 'endpoint': 'https://fallback-cupsy.invalid',
         'source_base_url': 'https://fallback-src.invalid', 'model': 'seed-audio-1.0'},
        'cupsy', kind='audio',
    ))
    monkeypatch.setitem(application.config['providers']['byteplus']['endpoint_ids'], 'seedance_2_5', 'ep-fallback-25')

    profiles.sync_config_profiles(sample_config())
    mapped = by_source_key()
    client = application.app.test_client()

    # Live provider endpoints reflect imported DB config immediately.
    img_info = client.get('/api/provider').get_json()
    assert img_info['providers']['ark']['available'] is True
    assert img_info['providers']['ark']['model'] == 'dola-seedream-5-5-261028'
    assert img_info['providers']['cupsy']['available'] is True
    vid_info = client.get('/api/video/provider').get_json()
    assert vid_info['providers']['ark']['available'] is True
    assert vid_info['providers']['ark']['seedance_2_5_configured'] is True
    assert vid_info['providers']['cupsy']['available'] is True
    aud_info = client.get('/api/audio/provider').get_json()
    assert aud_info['providers']['cupsy']['available'] is True

    # Edit image ark model and video ark seedance_2_5_model in DB -> live without restart.
    r = client.patch(f"/api/provider-profiles/{mapped['config:image:ark']['id']}", json={
        'revision': 1, 'settings': {'model': 'seedream-5-0-pro'}, 'api_key': 'live-ark-key-v2',
    })
    assert r.status_code == 200
    assert 'live-ark-key-v2' not in r.get_data(as_text=True)
    assert application.API_PROVIDERS['ark']['api_key'] == 'live-ark-key-v2'
    assert client.get('/api/provider').get_json()['providers']['ark']['model'] == 'seedream-5-0-pro'

    # Disabling config:video:ark (without clearing seedance_2_5_model) must report available=False AND seedance_2_5_configured=False.
    r = client.patch(f"/api/provider-profiles/{mapped['config:video:ark']['id']}", json={
        'revision': 1, 'enabled': False,
    })
    assert r.status_code == 200
    vid_disabled = client.get('/api/video/provider').get_json()['providers']['ark']
    assert vid_disabled['available'] is False
    assert vid_disabled['seedance_2_5_configured'] is False

    # Re-enabling restores seedance_2_5_configured=True; clearing seedance_2_5_model clears it (no fallback to config.json!).
    r = client.patch(f"/api/provider-profiles/{mapped['config:video:ark']['id']}", json={
        'revision': 2, 'enabled': True,
    })
    assert r.status_code == 200
    assert client.get('/api/video/provider').get_json()['providers']['ark']['seedance_2_5_configured'] is True
    r = client.patch(f"/api/provider-profiles/{mapped['config:video:ark']['id']}", json={
        'revision': 3, 'settings': {'seedance_2_5_model': ''},
    })
    assert r.status_code == 200
    assert client.get('/api/video/provider').get_json()['providers']['ark']['seedance_2_5_configured'] is False

    # Disabling config:image:ark blocks /api/provider and /api/generate (must NOT fall back to fallback-ark-key).
    r = client.patch(f"/api/provider-profiles/{mapped['config:image:ark']['id']}", json={
        'revision': 2, 'enabled': False,
    })
    assert r.status_code == 200
    assert application.API_PROVIDERS['ark']['api_key'] == ''
    assert client.get('/api/provider').get_json()['providers']['ark']['available'] is False
    gen = client.post('/api/generate', json={'provider': 'ark', 'prompt': 'cat', 'aspect_ratio': '1:1', 'resolution': '1K'})
    assert gen.status_code == 400 and 'API Key' in gen.get_json()['error']

    # Clearing config:image:cupsy key blocks Cupsy image even while config:video:cupsy still has a key.
    r = client.patch(f"/api/provider-profiles/{mapped['config:image:cupsy']['id']}", json={
        'revision': 1, 'clear_api_key': True,
    })
    assert r.status_code == 200
    assert client.get('/api/provider').get_json()['providers']['cupsy']['available'] is False
    assert client.get('/api/video/provider').get_json()['providers']['cupsy']['available'] is True
    gen_cupsy = client.post('/api/generate', json={'provider': 'cupsy', 'prompt': 'cat', 'aspect_ratio': '1:1', 'resolution': '1K'})
    assert gen_cupsy.status_code == 400 and 'API Key' in gen_cupsy.get_json()['error']

    # Clearing config:audio:cupsy key blocks /api/audio/provider and /api/audio/generate independently of video.
    r = client.patch(f"/api/provider-profiles/{mapped['config:audio:cupsy']['id']}", json={
        'revision': 1, 'clear_api_key': True,
    })
    assert r.status_code == 200
    assert client.get('/api/audio/provider').get_json()['providers']['cupsy']['available'] is False
    gen_audio = client.post('/api/audio/generate', json={'prompt': 'hello'})
    assert gen_audio.status_code == 400 and 'API Key' in gen_audio.get_json()['error']


def test_sync_adapter_api_key_rotates_and_clears_all_same_adapter_atomically():
    profiles.sync_config_profiles(sample_config())
    extra_ark = profiles.save_profile({
        'name': 'Ark 备用图', 'kind': 'image', 'adapter': 'ark',
        'settings': {'endpoint': 'https://ark2.invalid'}, 'api_key': 'old-extra-ark',
    })
    mapped = by_source_key()
    client = application.app.test_client()

    # Invalid type rejected cleanly.
    bad = client.patch(f"/api/provider-profiles/{mapped['config:image:ark']['id']}", json={
        'revision': 1, 'api_key': 'new-ark-synced', 'sync_adapter_api_key': 'yes',
    })
    assert bad.status_code == 400

    # Rotate Ark key with sync_adapter_api_key=True.
    vid_before = profiles.load_profile(mapped['config:video:ark']['id'])
    cupsy_before = profiles.load_profile(mapped['config:video:cupsy']['id'])
    res = client.patch(f"/api/provider-profiles/{mapped['config:image:ark']['id']}", json={
        'revision': 1, 'api_key': 'fake-ark-synced', 'sync_adapter_api_key': True,
    })
    assert res.status_code == 200
    raw_text = res.get_data(as_text=True)
    assert 'fake-ark-synced' not in raw_text
    assert 'cfg-ark-secret' not in raw_text
    body = res.get_json()
    assert set(body['synced_profile_ids']) == {mapped['config:video:ark']['id'], extra_ark['id']}

    vid_after = profiles.load_profile(mapped['config:video:ark']['id'])
    extra_after = profiles.load_profile(extra_ark['id'])
    assert vid_after['api_key'] == 'fake-ark-synced'
    assert vid_after['revision'] == vid_before['revision'] + 1
    assert vid_after['asset_scope'] != vid_before['asset_scope']
    # Old revision stays immutable.
    assert profiles.load_profile(mapped['config:video:ark']['id'], vid_before['revision'])['api_key'] == 'cfg-ark-secret'
    assert extra_after['api_key'] == 'fake-ark-synced' and extra_after['revision'] == 2
    # Cupsy is untouched.
    assert profiles.load_profile(mapped['config:video:cupsy']['id']) == cupsy_before

    # Clear Cupsy key with sync_adapter_api_key=True -> clears all 3 Cupsy profiles, leaves Ark untouched.
    res_clear = client.patch(f"/api/provider-profiles/{mapped['config:video:cupsy']['id']}", json={
        'revision': 1, 'clear_api_key': True, 'sync_adapter_api_key': True,
    })
    assert res_clear.status_code == 200
    assert set(res_clear.get_json()['synced_profile_ids']) == {
        mapped['config:image:cupsy']['id'], mapped['config:audio:cupsy']['id'],
    }
    for key in ('config:image:cupsy', 'config:video:cupsy', 'config:audio:cupsy'):
        loaded = profiles.load_profile(mapped[key]['id'])
        assert loaded['api_key'] == '' and loaded['revision'] == 2
    assert profiles.load_profile(mapped['config:image:ark']['id'])['api_key'] == 'fake-ark-synced'


def test_task_freezes_source_profile_revision_and_canvas_dedup_supports_legacy_null_profile(monkeypatch):
    profiles.sync_config_profiles(sample_config())
    mapped = by_source_key()
    client = application.app.test_client()

    # 1. Capabilities deduplication: no legacy fallback duplicates when config:* profiles are active.
    with application.app.test_request_context('/'):
        caps = canvas_submit.live_capabilities()
    assert [o['provider'] for o in caps['image']] == ['ark', 'cupsy']
    assert all(o.get('profile_id') for o in caps['image'])
    assert [o['provider'] for o in caps['video']] == ['ark', 'cupsy']
    assert all(o.get('profile_id') for o in caps['video'])
    assert [o['provider'] for o in caps['audio']] == ['cupsy']
    assert all(o.get('profile_id') for o in caps['audio'])

    # 2. Historical canvas node with profile_id: None resolves to config:image:ark and submits cleanly.
    project = canvas_store.create_project('旧画布兼容')
    wf = canvas_store.create_workflow(project['id'], '画布')
    doc = wf['document']
    doc['nodes'] = [{
        'id': 'legacy_img', 'type': 'image', 'title': '历史图像', 'x': 0, 'y': 0, 'text': '画一棵树',
        'providerSelection': {'provider': 'ark', 'profile_id': None},
        'params': {'ratio': '1:1', 'resolution': '1K'},
    }]
    saved_wf = canvas_store.update_workflow(wf['id'], '画布', doc, wf['revision'])
    assembled = canvas_submit.build_request(saved_wf, 'legacy_img', caps)
    assert assembled['path'] == '/api/generate'
    assert assembled['fields']['provider'] == 'ark'
    assert 'profile_id' not in assembled['fields']

    # Validate against server canvas_project_settings and actually create task.
    canvas_project_settings.validate_generation(assembled['fields'], 'image')
    resp = client.post(assembled['path'], json=assembled['fields'])
    assert resp.status_code == 202, resp.get_json()
    task_id = resp.get_json()['task_id']
    task = task_db.get_task(task_id)
    assert task['params']['profile_id'] == mapped['config:image:ark']['id']
    assert task['params']['profile_revision'] == 1

    # Rotate key + disable config:image:ark; already-submitted task still runs with revision 1 key!
    profiles.save_profile(
        {'revision': 1, 'enabled': False, 'api_key': 'fake-rotated'},
        mapped['config:image:ark']['id'],
    )
    observed = []

    def fake_generate(*args, **kwargs):
        observed.append((args[6].get('api_key'), args[6].get('endpoint')))
        return {'success': False, 'error': 'controlled-stop'}, 400

    monkeypatch.setattr(application, '_generate_ark_image', fake_generate)
    with application.app.app_context():
        application.execute_image_task(task_id)
    assert observed == [('cfg-ark-secret', 'https://ark.cfg.invalid')]

    # New submission from that legacy node is now blocked.
    resp2 = client.post(assembled['path'], json=assembled['fields'])
    assert resp2.status_code == 400 and 'API Key' in resp2.get_json()['error']


def test_cupsy_image_and_audio_references_freeze_own_source_profile_when_video_disabled(monkeypatch):
    import io
    from PIL import Image

    profiles.sync_config_profiles(sample_config())
    mapped = by_source_key()

    # Give image & audio distinct Cupsy endpoints/keys/source URLs, then DISABLE config:video:cupsy!
    img_cupsy = profiles.save_profile(
        {'revision': 1, 'api_key': 'fake-img-key',
         'settings': {'endpoint': 'https://img-cupsy.invalid', 'source_base_url': 'https://img-src.invalid'}},
        mapped['config:image:cupsy']['id'],
    )
    aud_cupsy = profiles.save_profile(
        {'revision': 1, 'api_key': 'fake-aud-key',
         'settings': {'endpoint': 'https://aud-cupsy.invalid', 'source_base_url': 'https://aud-src.invalid'}},
        mapped['config:audio:cupsy']['id'],
    )
    profiles.save_profile({'revision': 1, 'enabled': False}, mapped['config:video:cupsy']['id'])

    def make_png():
        buf = io.BytesIO()
        Image.new('RGB', (16, 16), (10, 20, 30)).save(buf, format='PNG')
        buf.seek(0)
        return buf

    client = application.app.test_client()

    # 1. Submit Cupsy image with reference image (no profile_id).
    img_resp = client.post(
        '/api/generate',
        data={
            'provider': 'cupsy', 'prompt': 'remix ref', 'aspect_ratio': '1:1', 'resolution': '1K',
            'images': (make_png(), 'ref-img.png'),
        },
        content_type='multipart/form-data',
    )
    assert img_resp.status_code == 202, img_resp.get_json()
    img_task_id = img_resp.get_json()['task_id']
    img_task = task_db.get_task(img_task_id)
    assert img_task['params']['profile_id'] == img_cupsy['id']
    assert img_task['params']['profile_revision'] == img_cupsy['revision']
    img_assets = task_db.list_task_provider_assets(img_task_id)
    assert len(img_assets) == 1
    assert img_assets[0]['provider'] == f"cupsy:profile:{img_cupsy['id']}:{img_cupsy['revision']}"

    # 2. Submit Cupsy audio with reference image (no profile_id).
    aud_resp = client.post(
        '/api/audio/generate',
        data={
            'prompt': 'sound from image', 'reference_mode': 'image',
            'references': (make_png(), 'ref-aud.png'),
        },
        content_type='multipart/form-data',
    )
    assert aud_resp.status_code == 202, aud_resp.get_json()
    aud_body = aud_resp.get_json()
    aud_task_id = aud_body.get('db_task_id') or aud_body['task_id']
    aud_task = task_db.get_task(aud_task_id)
    assert aud_task['params']['profile_id'] == aud_cupsy['id']
    assert aud_task['params']['profile_revision'] == aud_cupsy['revision']
    aud_assets = task_db.list_task_provider_assets(aud_task_id)
    assert len(aud_assets) == 1
    assert aud_assets[0]['provider'] == f"cupsy:profile:{aud_cupsy['id']}:{aud_cupsy['revision']}"

    # Rotate & disable both config:image:cupsy and config:audio:cupsy AFTER submission.
    profiles.save_profile({'revision': img_cupsy['revision'], 'enabled': False, 'api_key': 'fake-after'}, img_cupsy['id'])
    profiles.save_profile({'revision': aud_cupsy['revision'], 'enabled': False, 'api_key': 'fake-after'}, aud_cupsy['id'])

    # Both provider assets must still upload using their own frozen revision (endpoint, key, source_base_url).
    calls = []

    class FakeResp:
        status_code = 200
        text = '{"id":"ext-asset-1","status":"active","asset_uri":"cupsy://asset/1"}'

        def json(self):
            return json.loads(self.text)

    monkeypatch.setattr(application.HTTP, 'post', lambda url, **kw: calls.append(('post', url, kw)) or FakeResp())
    monkeypatch.setattr(application.HTTP, 'get', lambda url, **kw: calls.append(('get', url, kw)) or FakeResp())
    with application.app.app_context():
        img_create = application.process_cupsy_asset_once(img_assets[0]['id'])
        img_poll = application.process_cupsy_asset_once(img_assets[0]['id'])
        aud_create = application.process_cupsy_asset_once(aud_assets[0]['id'])
        aud_poll = application.process_cupsy_asset_once(aud_assets[0]['id'])

    assert img_create['state'] == 'pending' and img_poll['state'] == 'active', (img_create, img_poll)
    assert aud_create['state'] == 'pending' and aud_poll['state'] == 'active', (aud_create, aud_poll)
    assert len(calls) == 4
    assert calls[0][0] == 'post' and calls[0][1] == 'https://img-cupsy.invalid/v1/assets'
    assert calls[0][2]['headers']['Authorization'] == 'Bearer fake-img-key'
    assert calls[0][2]['json']['source_url'].startswith('https://img-src.invalid/api/cupsy/source/')
    assert calls[1][0] == 'get' and calls[1][1] == 'https://img-cupsy.invalid/v1/assets/ext-asset-1'
    assert calls[1][2]['headers']['Authorization'] == 'Bearer fake-img-key'
    assert calls[2][0] == 'post' and calls[2][1] == 'https://aud-cupsy.invalid/v1/assets'
    assert calls[2][2]['headers']['Authorization'] == 'Bearer fake-aud-key'
    assert calls[2][2]['json']['source_url'].startswith('https://aud-src.invalid/api/cupsy/source/')
    assert calls[3][0] == 'get' and calls[3][1] == 'https://aud-cupsy.invalid/v1/assets/ext-asset-1'
    assert calls[3][2]['headers']['Authorization'] == 'Bearer fake-aud-key'
