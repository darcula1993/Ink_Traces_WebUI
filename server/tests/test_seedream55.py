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


def test_profile_seedream55_vs_50_consistency_and_canvas_validation(monkeypatch):
    import json
    import canvas_store
    import canvas_submit
    import profile_runtime
    from provider_profiles import init_profiles_db, save_profile

    init_profiles_db()
    # Deployment default is 5.0 Pro; individual profiles override independently.
    monkeypatch.setitem(app.config['generation']['image']['byteplus'], 'model', 'seedream-5-0-pro')
    monkeypatch.setitem(
        app.API_PROVIDERS, 'ark',
        profile_runtime.ProfileConfig({'api_key': 'dep-key', 'endpoint': 'https://dep.invalid', 'model': 'seedream-5-0-pro'}, 'ark', kind='image'),
    )
    p55 = save_profile({
        'name': '独立55账号', 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'api_key': 'secret-55',
        'settings': {'endpoint': 'https://p55.invalid', 'model': 'Seedream-5.5'},
    })
    p50 = save_profile({
        'name': '独立50账号', 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'api_key': 'secret-50',
        'settings': {'endpoint': 'https://p50.invalid', 'model': 'seedream-5-0-pro'},
    })
    p_empty = save_profile({
        'name': '独立空模型账号', 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'api_key': 'secret-empty',
        'settings': {'endpoint': 'https://pempty.invalid'},
    })

    # Public profile capability_model agrees with backend 5.5 classification (case-insensitive).
    assert p55['capability_model'] == seedream55.MODEL
    assert p50['capability_model'] == 'seedream-5-0-pro'
    assert p_empty['capability_model'] == 'seedream-5-0-pro'
    assert canvas_submit.is_seedream55('Seedream-5.5') is True

    client = app.app.test_client()
    # 5.5 profile accepts 1.5K + native transparent background with 0 refs and freezes seedream55=True.
    r55 = client.post('/api/generate', json={
        'provider': 'ark', 'profile_id': p55['id'], 'prompt': '5.5 transparent',
        'aspect_ratio': '16:9', 'resolution': '1.5K', 'background': 'transparent', 'output_format': 'png',
    })
    assert r55.status_code == 202, r55.get_json()
    t55 = tasks.get_task(r55.get_json()['task_id'])
    assert t55['params']['seedream55'] is True
    assert t55['params']['profile_id'] == p55['id'] and t55['params']['profile_revision'] == 1
    assert t55['params']['size'] == '2048x1152'
    assert t55['params']['cost_estimate']['model'] == 'seedream-5.5'
    assert 'secret-55' not in json.dumps(t55)

    # 5.0 profile and empty-model profile reject 1.5K and reject transparent without alpha ref.
    for prof in (p50, p_empty):
        r_res = client.post('/api/generate', json={
            'provider': 'ark', 'profile_id': prof['id'], 'prompt': 'old 1.5K',
            'aspect_ratio': '16:9', 'resolution': '1.5K',
        })
        assert r_res.status_code == 400
        r_bg = client.post('/api/generate', json={
            'provider': 'ark', 'profile_id': prof['id'], 'prompt': 'old bg',
            'aspect_ratio': '1:1', 'resolution': '1K', 'background': 'transparent', 'output_format': 'png',
        })
        assert r_bg.status_code == 400
        r_ok = client.post('/api/generate', json={
            'provider': 'ark', 'profile_id': prof['id'], 'prompt': 'old ok',
            'aspect_ratio': '1:1', 'resolution': '1K',
        })
        assert r_ok.status_code == 202, r_ok.get_json()
        task = tasks.get_task(r_ok.get_json()['task_id'])
        assert task['params']['seedream55'] is False
        assert task['params']['cost_estimate']['model'] == 'seedream-5.0-pro'

    # Canvas node bound to 5.5 profile over 5.0 deployment passes canvas_image_params.validate_submission.
    project = canvas_store.create_project('5.5一致')
    wf = canvas_store.create_workflow(project['id'], '画布')
    doc = {
        **wf['document'],
        'nodes': [{
            'id': 'n55', 'type': 'image', 'title': '5.5节点', 'x': 0, 'y': 0, 'text': 'hello',
            'providerSelection': {'provider': 'ark', 'profile_id': p55['id']},
            'params': {'ratio': '16:9', 'resolution': '1.5K', 'output_format': 'png', 'background': 'auto', 'watermark': False},
        }],
    }
    saved = canvas_store.update_workflow(wf['id'], wf['title'], doc, wf['revision'])
    with app.app.test_request_context('/'):
        caps = canvas_submit.live_capabilities()
        req = canvas_submit.build_request(saved, 'n55', caps)
    rc = client.post(req['path'], json=req['fields'])
    assert rc.status_code == 202, rc.get_json()
    assert tasks.get_task(rc.get_json()['task_id'])['params']['seedream55'] is True


def test_profile_ep_matches_deployment_even_after_system_default_changed(monkeypatch):
    import copy
    import config_v2
    import profile_runtime
    from provider_profiles import init_profiles_db, save_profile, sync_config_profiles, list_profiles

    init_profiles_db()
    monkeypatch.setitem(app.config['generation']['image']['byteplus'], 'model', 'ep-confirmed55')
    monkeypatch.setitem(
        app.API_PROVIDERS, 'ark',
        profile_runtime.ProfileConfig({'api_key': 'dep-key', 'endpoint': 'https://dep.invalid', 'model': 'ep-confirmed55'}, 'ark', kind='image'),
    )
    cfg = copy.deepcopy(config_v2.DEFAULTS)
    cfg['providers']['byteplus']['api_key'] = 'dep-key'
    cfg['generation']['image']['byteplus']['model'] = 'ep-confirmed55'
    sync_config_profiles(cfg)
    sys_ark = next(p for p in list_profiles('image') if p.get('source_key') == 'config:image:ark')
    # Edit system default away from ep-confirmed55 to 5.0 Pro.
    save_profile({'revision': sys_ark['revision'], 'settings': {'model': 'seedream-5-0-pro'}}, sys_ark['id'])

    # Custom profile using the exact deployment ep-confirmed55 is STILL recognized as 5.5;
    # another unconfirmed ep- stays conservatively 5.0 Pro.
    p_match = save_profile({
        'name': '匹配EP', 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'api_key': 'secret-match',
        'settings': {'endpoint': 'https://match.invalid', 'model': 'ep-confirmed55'},
    })
    p_other = save_profile({
        'name': '未知EP', 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'api_key': 'secret-other',
        'settings': {'endpoint': 'https://other.invalid', 'model': 'ep-unconfirmed-99'},
    })
    assert p_match['capability_model'] == seedream55.MODEL
    assert p_other['capability_model'] == 'ep-unconfirmed-99'

    client = app.app.test_client()
    r1 = client.post('/api/generate', json={
        'provider': 'ark', 'profile_id': p_match['id'], 'prompt': 'ep 55', 'aspect_ratio': '1:1', 'resolution': '1.5K',
    })
    assert r1.status_code == 202, r1.get_json()
    assert tasks.get_task(r1.get_json()['task_id'])['params']['seedream55'] is True

    r2 = client.post('/api/generate', json={
        'provider': 'ark', 'profile_id': p_other['id'], 'prompt': 'ep unknown', 'aspect_ratio': '1:1', 'resolution': '1.5K',
    })
    assert r2.status_code == 400


def test_independent_tool_custom_profile_audio_upload_and_disable_block(monkeypatch):
    import json
    from provider_profiles import init_profiles_db, save_profile, delete_profile

    init_profiles_db()
    aud1 = save_profile({
        'name': '自定义音频A', 'kind': 'audio', 'adapter': 'cupsy', 'enabled': True, 'api_key': 'secret-aud-a',
        'settings': {'endpoint': 'https://aud-a.invalid', 'model': 'seed-audio-1.0', 'source_base_url': 'https://src-a.invalid'},
    })
    aud2 = save_profile({
        'name': '自定义音频B', 'kind': 'audio', 'adapter': 'cupsy', 'enabled': True, 'api_key': 'secret-aud-b',
        'settings': {'endpoint': 'https://aud-b.invalid', 'model': 'seed-audio-1.0', 'source_base_url': 'https://src-b.invalid'},
    })

    client = app.app.test_client()
    buf = io.BytesIO()
    Image.new('RGB', (16, 16), 'green').save(buf, format='PNG')
    buf.seek(0)
    up = client.post(
        '/api/cupsy/assets',
        data={'file': (buf, 'scene.png'), 'kind': 'image', 'profile_id': aud1['id']},
        content_type='multipart/form-data',
    )
    assert up.status_code == 202, up.get_json()
    asset_id = up.get_json()['asset']['id']

    # Submitting with aud2 must reject aud1's asset (cross-account isolation).
    cross = client.post('/api/audio/generate', json={
        'provider': 'cupsy', 'profile_id': aud2['id'], 'prompt': 'scene audio',
        'reference_mode': 'image', 'cupsy_assets': [{'id': asset_id}],
    })
    assert cross.status_code == 400

    # Submitting with aud1 succeeds and freezes (profile_id, profile_revision) without secret leakage.
    ok = client.post('/api/audio/generate', json={
        'provider': 'cupsy', 'profile_id': aud1['id'], 'prompt': 'scene audio',
        'reference_mode': 'image', 'cupsy_assets': [{'id': asset_id}],
    })
    assert ok.status_code == 202, ok.get_json()
    task = tasks.get_task(ok.get_json()['task_id'])
    assert task['params']['profile_id'] == aud1['id']
    assert task['params']['profile_revision'] == aud1['revision']
    assert 'secret-aud-a' not in json.dumps(task)

    # Deleting aud1 blocks further generation with 409 (never silently falls back to aud2).
    delete_profile(aud1['id'], aud1['revision'])
    blocked = client.post('/api/audio/generate', json={
        'provider': 'cupsy', 'profile_id': aud1['id'], 'prompt': 'after delete',
    })
    assert blocked.status_code == 409


def test_ark_explicit_capability_model_declares_55_for_custom_ep_and_preflight(monkeypatch):
    import json
    import cost_estimate
    import profile_runtime
    from provider_profiles import ProfileError, check_profile, init_profiles_db, save_profile

    init_profiles_db()
    custom_ep = 'ep-20990101000000-v24cap'  # secret-scan: allow
    monkeypatch.setitem(app.config['generation']['image']['byteplus'], 'model', 'ep-confirmed55')
    monkeypatch.setitem(
        app.API_PROVIDERS, 'ark',
        profile_runtime.ProfileConfig({'api_key': 'dep-key', 'endpoint': 'https://dep.invalid', 'model': 'ep-confirmed55'}, 'ark', kind='image'),
    )

    # Whitelist enforcement: reject invalid capability_model & reject on non-Ark-image profiles.
    with pytest.raises(ProfileError) as exc_bad:
        save_profile({
            'name': '非法能力版本', 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'api_key': 'k',
            'settings': {'endpoint': 'https://bad.invalid', 'model': custom_ep, 'capability_model': 'seedream-9-9'},
        })
    assert exc_bad.value.status == 400
    with pytest.raises(ProfileError) as exc_cupsy:
        save_profile({
            'name': 'Cupsy不支持能力版本', 'kind': 'image', 'adapter': 'cupsy', 'enabled': True, 'api_key': 'k',
            'settings': {'endpoint': 'https://cupsy.invalid', 'capability_model': seedream55.MODEL},
        })
    assert exc_cupsy.value.status == 400

    # 1. Custom ep- WITHOUT capability_model -> preflight warns about 5.0 Pro $0.045 fallback (no raw ep- leak).
    p_undeclared = save_profile({
        'name': '未声明EP', 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'api_key': 'test-key-undeclared',
        'settings': {'endpoint': 'https://ep1.invalid', 'model': custom_ep},
    })
    assert p_undeclared['capability_model'] == custom_ep
    pre_warn = check_profile(p_undeclared['id'])
    assert custom_ep not in json.dumps(pre_warn, ensure_ascii=False)
    assert 'test-key-undeclared' not in json.dumps(pre_warn, ensure_ascii=False)
    cap_warn = next(c for c in pre_warn['checks'] if c['key'] == 'capability_model')
    assert cap_warn['status'] == 'warn'
    assert '$0.045' in cap_warn['message']

    # 2. Custom ep- WITH explicit capability_model=dola-seedream-5-5-261028 -> full 5.5 capability + $0.020/1K!
    p_declared_55 = save_profile({
        'name': '声明55的EP', 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'api_key': 'test-key-ep-55',
        'settings': {'endpoint': 'https://ep55.invalid', 'model': custom_ep, 'capability_model': seedream55.MODEL},
    })
    assert p_declared_55['capability_model'] == seedream55.MODEL
    pre_ok = check_profile(p_declared_55['id'])
    assert custom_ep not in json.dumps(pre_ok, ensure_ascii=False)
    assert pre_ok['status'] == 'ok'
    cap_ok = next(c for c in pre_ok['checks'] if c['key'] == 'capability_model')
    assert cap_ok['status'] == 'ok'
    assert 'Seedream 5.5' in cap_ok['message'] and '$0.020' in cap_ok['message']

    client = app.app.test_client()
    r55 = client.post('/api/generate', json={
        'provider': 'ark', 'profile_id': p_declared_55['id'], 'prompt': 'declared 55',
        'aspect_ratio': '1:1', 'resolution': '1.5K', 'background': 'transparent', 'output_format': 'png',
    })
    assert r55.status_code == 202, r55.get_json()
    t55 = tasks.get_task(r55.get_json()['task_id'])
    assert t55['params']['seedream55'] is True
    assert t55['params']['cost_estimate']['model'] == 'seedream-5.5'
    assert t55['params']['cost_estimate']['minimum_cost'] == pytest.approx(0.020)

    # Even without seedream55 flag, cost_estimate recognizes explicit capability_model / profile declaration.
    derived_from_profile = cost_estimate.compute_task_estimate({
        'id': t55['id'], 'type': 'image', 'provider': 'ark', 'status': 'succeeded',
        'params': {'model': custom_ep, 'size': '1024x1024', 'profile_id': p_declared_55['id'], 'profile_revision': 1},
    }, tasks.get_db())
    assert derived_from_profile['model'] == 'seedream-5.5'
    assert derived_from_profile['minimum_cost'] == pytest.approx(0.020)

    derived_from_param = cost_estimate.compute_task_estimate({
        'id': t55['id'], 'type': 'image', 'provider': 'ark', 'status': 'succeeded',
        'params': {'model': custom_ep, 'size': '1024x1024', 'capability_model': seedream55.MODEL},
    }, tasks.get_db())
    assert derived_from_param['model'] == 'seedream-5.5'
    assert derived_from_param['minimum_cost'] == pytest.approx(0.020)

    # 3. Explicit seedream-5-0-pro overrides even deployment-matched ep-confirmed55.
    p_force_50 = save_profile({
        'name': '显式50覆盖', 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'api_key': 'secret-ep-50',
        'settings': {'endpoint': 'https://ep50.invalid', 'model': 'ep-confirmed55', 'capability_model': 'seedream-5-0-pro'},
    })
    assert p_force_50['capability_model'] == 'seedream-5-0-pro'
    r_bad_res = client.post('/api/generate', json={
        'provider': 'ark', 'profile_id': p_force_50['id'], 'prompt': 'force 50',
        'aspect_ratio': '1:1', 'resolution': '1.5K',
    })
    assert r_bad_res.status_code == 400
    r_50_ok = client.post('/api/generate', json={
        'provider': 'ark', 'profile_id': p_force_50['id'], 'prompt': 'force 50 1k',
        'aspect_ratio': '1:1', 'resolution': '1K',
    })
    assert r_50_ok.status_code == 202, r_50_ok.get_json()
    t50 = tasks.get_task(r_50_ok.get_json()['task_id'])
    assert t50['params']['seedream55'] is False
    assert t50['params']['cost_estimate']['model'] == 'seedream-5.0-pro'
    assert t50['params']['cost_estimate']['minimum_cost'] == pytest.approx(0.045)
