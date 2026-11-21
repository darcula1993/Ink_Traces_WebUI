"""V24-W1-LAYER-BRIDGE-20261121: Layer default 12, Ark profile binding & revision freeze,
and canvas project cost-ledger attribution."""
import base64
import io
import json
from PIL import Image
import pytest

import app as application
import canvas_store
import cost_ledger
import layer_options
import media_library
import provider_profiles
import seedream55
import tasks
from test_generation import FakeResponse, _rgba_png_bytes


def _png_bytes(size=(512, 512), color=(40, 120, 200, 255)):
    buf = io.BytesIO()
    Image.new('RGBA', size, color).save(buf, format='PNG')
    return buf.getvalue()


def _upload_image(name='bridge-src.png', color=(40, 120, 200, 255)):
    media, _ = media_library.save_upload(io.BytesIO(_png_bytes(color=color)), name, origin='upload')
    return media


def _create_profile(*, kind='image', adapter='ark', name='Ark 5.5 账号', model=seedream55.MODEL,
                    endpoint='https://ark-a.invalid', api_key='fake-key-a', enabled=True):
    settings = {'endpoint': endpoint, 'model': model}
    if adapter == 'cupsy':
        settings['source_base_url'] = 'https://source.invalid'
    return provider_profiles.save_profile({
        'name': name,
        'kind': kind,
        'adapter': adapter,
        'enabled': enabled,
        'settings': settings,
        'api_key': api_key,
    })


def test_default_max_images_is_12_and_accepts_2_to_100():
    assert layer_options.DEFAULT_MAX_IMAGES == 12
    assert layer_options.options({}, seedream55.MODEL) == {'max_images': 12, 'text_recognition': False}
    assert layer_options.options({'max_images': 2}, seedream55.MODEL)['max_images'] == 2
    assert layer_options.options({'max_images': 30}, seedream55.MODEL)['max_images'] == 30
    assert layer_options.options({'max_images': 100}, seedream55.MODEL)['max_images'] == 100


def test_decompose_freezes_selected_ark_profile_revision_and_isolates_execution(monkeypatch):
    provider_profiles.init_profiles_db()
    # Deliberately point global API_PROVIDERS['ark'] to a different account to prove no cross-account leakage.
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'test-wrong',
        'model': 'seedream-5-0-pro',
        'endpoint': 'https://global-wrong.invalid',
    })
    prof_a = _create_profile(name='Ark-A', model=seedream55.MODEL, endpoint='https://ark-a.invalid', api_key='fake-ark-a')
    _create_profile(name='Ark-B', model='seedream-5-0-pro', endpoint='https://ark-b.invalid', api_key='fake-ark-b')

    client = application.app.test_client()
    media = _upload_image('layer-prof.png', (30, 90, 150, 255))
    created = client.post('/api/layer/projects', json={'source_media_id': media['id'], 'decompose': False})
    assert created.status_code == 201, created.get_json()
    pid = created.get_json()['project_id']

    resp = client.post(f'/api/layer/projects/{pid}/decompose', json={
        'prompt': 'split foreground',
        'size': '1K',
        'profile_id': prof_a['id'],
    })
    assert resp.status_code == 202, resp.get_json()
    tid = resp.get_json()['task_id']
    task = tasks.get_task(tid)
    assert task['params']['profile_id'] == prof_a['id']
    assert task['params']['profile_revision'] == 1
    assert task['params']['model'] == seedream55.MODEL
    assert task['params']['layer_decomposition_options'] == {'max_images': 12, 'text_recognition': False}
    assert 'fake-ark-a' not in json.dumps(task)

    # Mutate and disable prof_a after queueing; execution must still run against frozen revision 1!
    updated = provider_profiles.save_profile({
        'revision': prof_a['revision'],
        'enabled': False,
        'api_key': 'fake-ark-a-v2',
        'settings': {'endpoint': 'https://ark-a-v2.invalid', 'model': 'seedream-5-0-pro'},
    }, prof_a['id'])
    provider_profiles.delete_profile(prof_a['id'], updated['revision'])

    observed = {}
    layer_b64 = base64.b64encode(_rgba_png_bytes((64, 64))).decode()

    def fake_post(url, **kwargs):
        observed['url'] = url
        observed['auth'] = kwargs['headers']['Authorization']
        observed['body'] = kwargs['json']
        return FakeResponse(payload={'data': [
            {'b64_json': layer_b64, 'z_index': 0, 'name': '底图'},
            {'b64_json': layer_b64, 'z_index': 1, 'name': '主体'},
        ]})

    monkeypatch.setattr(application.HTTP, 'post', fake_post)
    with application.app.app_context():
        result, status = application.execute_layer_task(tid)
    assert status == 200, result
    assert observed['url'].startswith('https://ark-a.invalid/')
    assert observed['auth'] == 'Bearer fake-ark-a'
    assert observed['body']['model'] == seedream55.MODEL
    assert observed['body']['layer_decomposition_options'] == {'max_images': 12, 'text_recognition': False}


def test_decompose_rejects_invalid_disabled_deleted_keyless_or_non_ark_profiles_without_fallback(monkeypatch):
    provider_profiles.init_profiles_db()
    # Even when a valid global Ark key AND another enabled Ark profile exist, invalid explicit profile_id MUST fail.
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'fake-global',
        'model': seedream55.MODEL,
        'endpoint': 'https://global.invalid',
    })
    _create_profile(name='Fallback-Valid-Ark', api_key='fake-valid')
    disabled_prof = _create_profile(name='Disabled-Ark', enabled=False, api_key='fake-disabled')
    keyless_prof = _create_profile(name='Keyless-Ark', enabled=True, api_key='')
    deleted_prof = _create_profile(name='Deleted-Ark', enabled=True, api_key='fake-del')
    provider_profiles.delete_profile(deleted_prof['id'], deleted_prof['revision'])
    cupsy_img = _create_profile(kind='image', adapter='cupsy', name='Cupsy-Img', model='seedream-5.0-pro',
                                endpoint='https://cupsy.invalid', api_key='fake-cupsy')
    ark_vid = _create_profile(kind='video', adapter='ark', name='Ark-Video', model='seedance-2.0',
                              endpoint='https://ark-vid.invalid', api_key='fake-vid')

    client = application.app.test_client()
    media = _upload_image('guard-src.png', (60, 70, 80, 255))
    pid = client.post('/api/layer/projects', json={'source_media_id': media['id'], 'decompose': False}).get_json()['project_id']
    before_tasks = tasks.list_task_ids()

    cases = [
        ('not-a-hex-id', 400),
        (12345, 400),
        ('0' * 32, 409),
        (disabled_prof['id'], 409),
        (keyless_prof['id'], 409),
        (deleted_prof['id'], 409),
        (cupsy_img['id'], 400),
        (ark_vid['id'], 400),
    ]
    for bad_id, expected_status in cases:
        r = client.post(f'/api/layer/projects/{pid}/decompose', json={'prompt': 'x', 'size': '1K', 'profile_id': bad_id})
        assert r.status_code == expected_status, (bad_id, r.status_code, r.get_json())
    assert tasks.list_task_ids() == before_tasks


def test_canvas_context_persists_and_attributes_layer_task_to_project_cost_ledger(monkeypatch):
    provider_profiles.init_profiles_db()
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'ledger-test-key',
        'model': seedream55.MODEL,
        'endpoint': 'https://ledger-ark.invalid',
    })
    project = canvas_store.create_project('短剧-图层归属项目')
    workflow = canvas_store.create_workflow(project['id'], '分镜画布')
    media = _upload_image('canvas-origin.png', (110, 140, 170, 255))

    client = application.app.test_client()
    created = client.post('/api/layer/projects', json={
        'source_media_id': media['id'],
        'decompose': False,
        'canvas_project_id': project['id'],
        'canvas_workflow_id': workflow['id'],
        'canvas_node_id': 'node_img_01',
    })
    assert created.status_code == 201, created.get_json()
    layer_proj = created.get_json()['project']
    assert layer_proj['source_metadata']['canvas_project_id'] == project['id']
    assert layer_proj['source_metadata']['canvas_workflow_id'] == workflow['id']
    assert layer_proj['source_metadata']['canvas_node_id'] == 'node_img_01'

    dec = client.post(f"/api/layer/projects/{layer_proj['id']}/decompose", json={'prompt': 'split', 'size': '1K'})
    assert dec.status_code == 202, dec.get_json()
    tid = dec.get_json()['task_id']
    task = tasks.get_task(tid)
    assert task['params']['canvas_workflow_id'] == workflow['id']
    assert task['params']['canvas_node_id'] == 'node_img_01'

    # Complete the layer task with 3 layers (base + 2 foreground layers) at 1024x1024
    layer_b64 = base64.b64encode(_rgba_png_bytes((1024, 1024))).decode()
    monkeypatch.setattr(
        application.HTTP, 'post',
        lambda url, **kwargs: FakeResponse(payload={'data': [
            {'b64_json': layer_b64, 'z_index': 0, 'name': '底图'},
            {'b64_json': layer_b64, 'z_index': 1, 'name': '人物'},
            {'b64_json': layer_b64, 'z_index': 2, 'name': '前景'},
        ]}),
    )
    with application.app.app_context():
        result, status = application.execute_layer_task(tid)
    assert status == 200, result

    ledger = cost_ledger.build_ledger(project_id=project['id'])
    layer_entries = [entry for entry in ledger['tasks'] if entry['id'] == tid]
    assert len(layer_entries) == 1, ledger
    entry = layer_entries[0]
    assert entry['type'] == 'layer'
    assert entry['project_id'] == project['id']
    assert entry['workflow_id'] == workflow['id']
    assert entry['node_id'] == 'node_img_01'
    # Seedream 5.5: 1 source ($0.008) + 3 layers * $0.020 = $0.068
    assert entry['estimate_usd'] == {'min': pytest.approx(0.068), 'max': pytest.approx(0.068)}
    assert ledger['totals']['billable']['known_usd_min'] == pytest.approx(0.068)

    # Also verify a standalone layer project without canvas context stays unassigned.
    standalone = client.post('/api/layer/projects', json={'source_media_id': media['id'], 'decompose': False}).get_json()
    standalone_tid = client.post(f"/api/layer/projects/{standalone['project_id']}/decompose", json={'size': '1K'}).get_json()['task_id']
    assert 'canvas_workflow_id' not in tasks.get_task(standalone_tid)['params']
    unassigned = cost_ledger.build_ledger(project_id=cost_ledger.UNASSIGNED)
    assert any(entry['id'] == standalone_tid for entry in unassigned['tasks'])
