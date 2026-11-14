"""IMAGE-COST-20261114: image / layer-decomposition estimates (never actual charges)."""
import base64
import io
import json
from pathlib import Path

import pytest

import app as application
import cost_estimate
import seedream55
import storage
import tasks as task_db
from test_generation import FakeResponse, _rgba_png_bytes

CASES = json.loads((Path(__file__).parent / 'data' / 'cost_estimate_parity.json').read_text())


def _kind(kind):
    return [case for case in CASES if case.get('kind') == kind]


@pytest.mark.parametrize('case', _kind('image'), ids=[case['name'] for case in _kind('image')])
def test_image_estimate_matches_client_formula(case):
    estimate = cost_estimate.estimate_image_cost(case['family'], case['width'], case['height'], case['references'])
    expected = case['expected']
    assert estimate['known'] is expected['known']
    if not expected['known']:
        assert estimate['reason'] == expected['reason']
        assert 'minimum_cost' not in estimate  # unknown is never a zero
        return
    assert estimate['minimum_cost'] == expected['minimumCost']  # exact: same float operations
    assert estimate['maximum_cost'] == expected['maximumCost']
    assert estimate['output_unit_price'] == expected['outputUnitPrice']
    assert estimate['input_cost'] == expected['inputCost']
    assert estimate['tier'] == expected['tier']


@pytest.mark.parametrize('case', _kind('layer_unit'), ids=[case['name'] for case in _kind('layer_unit')])
def test_layer_unit_price_matches_client(case):
    unit = cost_estimate.estimate_layer_unit_price(case['family'], case['size'])
    assert (unit['per_layer_min'], unit['per_layer_max'], unit['input_cost']) == (
        case['expected']['perLayerMin'], case['expected']['perLayerMax'], case['expected']['inputCost'])


@pytest.mark.parametrize('case', _kind('layer_outputs'), ids=[case['name'] for case in _kind('layer_outputs')])
def test_layer_outputs_cost_matches_client(case):
    estimate = cost_estimate.estimate_layer_outputs_cost(case['family'], case['sizes'])
    assert estimate['known'] is case['expected']['known']
    if case['expected']['known']:
        assert estimate['minimum_cost'] == case['expected']['minimumCost']
        assert estimate['output_count'] == case['expected']['outputCount']
        if 'belowFloorLayers' in case['expected']:
            assert estimate['below_floor_layers'] == case['expected']['belowFloorLayers']
            assert estimate.get('assumption') == case['expected']['assumption']
    else:
        assert estimate['reason'] == case['expected']['reason']


def test_parity_fixture_covers_required_boundaries():
    names = {case['name'] for case in _kind('image')}
    pixels = {(case['family'], case['width'] * case['height']) for case in _kind('image')}
    assert ('seedream-5.5', 921_600) in pixels and ('seedream-5.5', 2_601_124) in pixels
    assert ('seedream-5.0-pro', 921_600) in pixels and ('seedream-5.0-pro', 2_601_124) in pixels
    assert {case['references'] for case in _kind('image')} >= {0, 1, 3}
    assert {case['expected'].get('tier') for case in _kind('image') if case['family'] == 'seedream-5.5'} >= {0, 1}
    assert {case['expected'].get('tier') for case in _kind('image') if case['family'] == 'seedream-5.0-pro'} >= {0, 1}
    assert len(names) == len(_kind('image'))


def _ark(monkeypatch, model='test-model'):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'test-key', 'endpoint': 'https://provider.invalid', 'model': model,
    })


def _forbid_provider(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('submission/ledger must not call a Provider')
    monkeypatch.setattr(application.HTTP, 'post', forbidden)
    monkeypatch.setattr(application.HTTP, 'get', forbidden)


def _upload(client):
    return client.post('/api/workspace/assets/img_tabs', data={
        'file': (io.BytesIO(_rgba_png_bytes()), 'ref.png')}).get_json()['asset']['url']


def test_ark_image_submission_stores_snapshot_without_provider_call(monkeypatch):
    _ark(monkeypatch)
    _forbid_provider(monkeypatch)
    client = application.app.test_client()
    refs = [_upload(client) for _ in range(3)]
    response = client.post('/api/generate', json={
        'prompt': 'cat', 'provider': 'ark', 'aspect_ratio': '16:9', 'resolution': '2K', 'image_urls': refs})
    assert response.status_code == 202, response.get_json()
    task = task_db.get_task(response.get_json()['task_id'])
    snapshot = task['params']['cost_estimate']
    assert snapshot['status'] == 'estimate' and snapshot['model'] == 'seedream-5.0-pro'
    assert (snapshot['width'], snapshot['height'], snapshot['reference_count']) == (2816, 1584, 3)
    assert snapshot['minimum_cost'] == pytest.approx(0.096)
    # Request parameters are unchanged apart from the snapshot field.
    assert set(task['params']) - {'cost_estimate'} == {
        'seedream55', 'aspect_ratio', 'provider', 'model', 'resolution', 'output_format', 'watermark', 'size'}
    assert task['status'] == 'pending'


def test_seedream55_custom_size_snapshot(monkeypatch):
    _ark(monkeypatch, seedream55.MODEL)
    client = application.app.test_client()
    response = client.post('/api/generate', json={
        'prompt': 'cat', 'provider': 'ark', 'aspect_ratio': 'custom', 'custom_width': 1280, 'custom_height': 720})
    assert response.status_code == 202, response.get_json()
    snapshot = task_db.get_task(response.get_json()['task_id'])['params']['cost_estimate']
    assert snapshot['model'] == 'seedream-5.5' and snapshot['pixels'] == 921_600
    assert snapshot['minimum_cost'] == pytest.approx(0.020)


def test_auto_ratio_uses_nominal_size_and_flags_assumption(monkeypatch):
    _ark(monkeypatch)
    client = application.app.test_client()
    response = client.post('/api/generate', json={'prompt': 'cat', 'provider': 'ark', 'aspect_ratio': 'auto', 'resolution': '2K'})
    assert response.status_code == 202, response.get_json()
    snapshot = task_db.get_task(response.get_json()['task_id'])['params']['cost_estimate']
    assert snapshot['size_assumed'] is True and snapshot['minimum_cost'] == pytest.approx(0.09)


def test_snapshot_failure_never_blocks_image_submission(monkeypatch):
    _ark(monkeypatch)
    monkeypatch.setattr(cost_estimate, 'compute_task_estimate', lambda *_a: 1 / 0)
    response = application.app.test_client().post('/api/generate', json={
        'prompt': 'cat', 'provider': 'ark', 'aspect_ratio': '1:1', 'resolution': '1K'})
    assert response.status_code == 202
    task = task_db.get_task(response.get_json()['task_id'])
    assert 'cost_estimate' not in task['params'] and task['status'] == 'pending'


def test_historical_image_tasks_are_derived_or_unknown():
    db = task_db.get_db()
    derived = task_db.create_task('image', 'p', {'provider': 'cupsy', 'aspect_ratio': '16:9', 'resolution': '2K',
                                                 'size': '2560x1440'}, provider='cupsy', status='succeeded')
    path = Path(storage.task_output_dir('image', derived)) / 'ref_0.png'
    path.write_bytes(_rgba_png_bytes())
    storage.register_file(derived, 'input_image', str(path), 'image/png')
    old_ark = task_db.create_task('image', 'p', {'aspect_ratio': '1:1', 'resolution': '1K'}, provider='ark', status='succeeded')
    no_size = task_db.create_task('image', 'p', {}, provider='ark', status='succeeded')
    google = task_db.create_task('image', 'p', {'aspect_ratio': '1:1'}, provider='google', status='succeeded')
    tiny = task_db.create_task('image', 'p', {'seedream55': True, 'size': '1280x704'}, provider='ark', status='succeeded')
    result = {tid: cost_estimate.task_estimate(task_db.get_task(tid), db) for tid in (derived, old_ark, no_size, google, tiny)}
    assert result[derived]['basis'] == 'derived' and result[derived]['minimum_cost'] == pytest.approx(0.09)
    assert result[old_ark]['minimum_cost'] == pytest.approx(0.045)
    assert result[no_size] == {'status': 'unknown', 'reason': 'no_estimate_snapshot', 'basis': 'derived'}
    assert result[google]['reason'] == 'no_price_data'
    assert result[tiny]['status'] == 'unknown' and result[tiny]['reason'] == 'below_price_floor'


def test_existing_image_snapshot_is_not_overwritten():
    task_id = task_db.create_task('image', 'p', {'size': '1024x1024', 'cost_estimate': {
        'status': 'estimate', 'minimum_cost': 0.5, 'maximum_cost': 0.5}}, provider='ark', status='succeeded')
    assert cost_estimate.store_snapshot(task_id) is None
    estimate = cost_estimate.task_estimate(task_db.get_task(task_id), task_db.get_db())
    assert estimate['basis'] == 'snapshot' and estimate['minimum_cost'] == 0.5


def _layer_project(client, **form):
    response = client.post('/api/layer/projects', data={
        'image': (io.BytesIO(_rgba_png_bytes((512, 512))), 'src.png'), **form})
    assert response.status_code == 202, response.get_json()
    return response.get_json()['task_id']


def _run_layer(monkeypatch, task_id, sizes):
    images = []
    for width, height in sizes:
        buffer = io.BytesIO()
        from PIL import Image
        Image.new('RGBA', (width, height), (1, 2, 3, 255)).save(buffer, format='PNG')
        images.append(base64.b64encode(buffer.getvalue()).decode())
    monkeypatch.setattr(application.HTTP, 'post', lambda *_a, **_k: FakeResponse(payload={
        'data': [{'b64_json': image, 'z_index': index} for index, image in enumerate(images)]}))
    with application.app.app_context():
        _result, status = application.execute_layer_task(task_id)
    assert status == 200


def _ledger_task(task_id):
    data = application.app.test_client().get('/api/cost-ledger').get_json()
    return next(item for item in data['tasks'] if item['id'] == task_id)


def test_layer_snapshot_then_actual_layer_count(monkeypatch):
    _ark(monkeypatch)
    client = application.app.test_client()
    task_id = _layer_project(client, size='2K')
    snapshot = task_db.get_task(task_id)['params']['cost_estimate']
    assert snapshot['status'] == 'per_layer' and snapshot['model'] == 'seedream-5.0-pro'
    assert (snapshot['per_layer_min'], snapshot['per_layer_max'], snapshot['input_cost']) == (0.0225, 0.045, 0)
    pending = _ledger_task(task_id)
    assert pending['estimate_usd'] is None and pending['unknown_reason'] == 'layer_count_unknown'
    # Base 1700x1700 (2.89M px, high tier) + two small layers (low tier).
    _run_layer(monkeypatch, task_id, [(1700, 1700), (64, 64), (32, 48)])
    done = _ledger_task(task_id)
    assert done['basis'] == 'snapshot' and done['bucket'] == 'billable'
    assert done['estimate_usd']['min'] == pytest.approx(0.045 + 0.0225 * 2)
    assert done['assumptions']['output_count'] == 3


def test_layer_seedream55_small_layers_bill_floor_tier_as_assumed(monkeypatch):
    # User 2026-11-14: 5.5 layers below 921,600 px use the lowest tier ($0.020), tagged 推算.
    _ark(monkeypatch, seedream55.MODEL)
    client = application.app.test_client()
    task_id = _layer_project(client, size='1K', max_images='5')
    assert task_db.get_task(task_id)['params']['cost_estimate']['model'] == 'seedream-5.5'
    _run_layer(monkeypatch, task_id, [(1024, 1024), (64, 64), (32, 48)])
    done = _ledger_task(task_id)
    assert done['bucket'] == 'billable' and done['unknown_reason'] is None
    assert done['estimate_usd']['min'] == pytest.approx(0.008 + 0.020 * 3)
    assert done['basis'] == 'snapshot' and done['assumption'] == 'below_floor_min_tier'
    assert done['assumptions']['below_floor_layers'] == 2 and done['assumptions']['output_count'] == 3


def test_layer_seedream50_pro_has_no_floor_assumption(monkeypatch):
    _ark(monkeypatch)
    task_id = _layer_project(application.app.test_client(), size='1K')
    _run_layer(monkeypatch, task_id, [(1024, 1024), (64, 64)])
    done = _ledger_task(task_id)
    assert done['estimate_usd']['min'] == pytest.approx(0.0225 * 2)
    assert done['assumption'] is None and done['assumptions']['below_floor_layers'] == 0


def test_seedream55_single_image_below_floor_stays_unknown():
    estimate = cost_estimate.estimate_image_cost('seedream-5.5', 960, 959, 0)
    assert estimate['known'] is False and estimate['reason'] == 'below_price_floor'
    assert 'assumption' not in estimate and 'minimum_cost' not in estimate


def test_historical_layer_without_snapshot_is_derived(monkeypatch):
    _ark(monkeypatch)
    client = application.app.test_client()
    task_id = _layer_project(client, size='1K')
    params = task_db.get_task(task_id)['params']
    params.pop('cost_estimate')
    task_db.update_task(task_id, params=params)
    _run_layer(monkeypatch, task_id, [(1024, 1024), (100, 100)])
    done = _ledger_task(task_id)
    assert done['basis'] == 'derived' and done['estimate_usd']['min'] == pytest.approx(0.045)


def test_failed_layer_task_stays_in_failed_bucket(monkeypatch):
    _ark(monkeypatch)
    task_id = _layer_project(application.app.test_client())
    task_db.fail_task(task_id, 'boom')
    entry = _ledger_task(task_id)
    assert entry['bucket'] == 'failed' and entry['estimate_usd'] is None


# ---- ESTIMATE-DEBT-20261115 #1: the price family follows the model of the interface the
# node actually uses (saved profile or original config), never the deployment default alone.
# Shared with client/tests/imageProfileFamily.test.js: both sides must reach these results.
PROFILE_CASES = json.loads((Path(__file__).parent / 'data' / 'image_profile_family_parity.json').read_text())


@pytest.mark.parametrize('case', PROFILE_CASES, ids=[case['name'] for case in PROFILE_CASES])
def test_image_family_follows_the_interface_model(case, monkeypatch):
    import profile_runtime
    from provider_profiles import init_profiles_db, save_profile
    init_profiles_db()
    _forbid_provider(monkeypatch)
    deployment = {'api_key': 'test-key', 'endpoint': 'https://provider.invalid', 'model': case['deployment_model']}
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', profile_runtime.ProfileConfig(deployment, 'ark'))
    monkeypatch.setitem(application.config['generation']['image']['byteplus'], 'model', case['deployment_model'])
    client = application.app.test_client()
    # The fixture's deployment capability model is what /api/provider really reports.
    assert client.get('/api/provider').get_json()['providers']['ark']['capability_model'] == case['deployment_capability_model']
    body = {'prompt': 'cat', 'provider': 'ark', 'aspect_ratio': '1:1', 'resolution': '1K'}
    if case['profile_model'] is not None:
        profile = save_profile({'name': 'debt', 'kind': 'image', 'adapter': 'ark', 'enabled': True, 'api_key': 'fake-debt',
                                'settings': {'endpoint': 'https://debt.invalid', 'model': case['profile_model']}})
        body['profile_id'] = profile['id']
    response = client.post('/api/generate', json=body)
    assert response.status_code == 202, response.get_json()
    task = task_db.get_task(response.get_json()['task_id'])
    snapshot = task['params']['cost_estimate']
    assert snapshot['model'] == case['expected']['model']
    assert snapshot['minimum_cost'] == pytest.approx(case['expected']['minimumCost'])
    # The ledger re-derivation (no snapshot) reaches the same family from the task's own params.
    params = dict(task['params'])
    params.pop('cost_estimate')
    derived = cost_estimate.compute_task_estimate({**task, 'params': params}, task_db.get_db())
    assert derived['model'] == case['expected']['model']
