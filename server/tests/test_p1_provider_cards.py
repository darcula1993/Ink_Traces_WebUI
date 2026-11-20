"""P1-PROVIDER-CARDS-20261120 backend unit & API tests:
- list_projects returns workflow_count & effective updated_at (excluding deleted workflows)
- zero-cost provider profile preflight (/api/provider-profiles/<id>/check & /check) with zero network & zero leaks
- extended ep- endpoint ID redaction (_ep-, -ep-, URL-encoded variants) at persistence & read without breaking 5.5/pricing
"""
import json
import socket

from flask import Flask
import pytest
import requests

import app as application
import canvas_cleanup
import canvas_store as store
import canvas_writeback
import cost_estimate
import provider_profiles as profiles
import seedream55
import tasks as task_db
from provider_api import provider_api
from task_public import ENDPOINT_MASK, mask_endpoint_ids, mask_text, public_task

FAKE_EP = 'ep-20990101000000-p1probe'  # secret-scan: allow
FAKE_EP_M = 'ep-m-20990101000000-p1probe'  # secret-scan: allow
FAKE_KEY = 'secret-preflight-never-echo-999'  # secret-scan: allow


@pytest.fixture
def provider_client(isolated_backend):
    profiles.init_profiles_db()
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(provider_api)
    return app.test_client()


# ------------------------------------------------------------------ 1. list_projects

def test_list_projects_returns_workflow_count_and_latest_updated_at(monkeypatch, tmp_path):
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(tmp_path / 'canvas_assets'))
    store.init_canvas_db()
    p_empty = store.create_project('空项目')
    p_multi = store.create_project('多画布项目')
    wf1 = store.create_workflow(p_multi['id'], '画布一')
    wf2 = store.create_workflow(p_multi['id'], '画布二')
    wf_del = store.create_workflow(p_multi['id'], '待删除画布')

    # Force distinct timestamps to verify max(project.updated_at, live workflow.updated_at)
    db = task_db.get_db()
    db.execute('UPDATE canvas_projects SET updated_at=? WHERE id=?', ('2026-11-10T00:00:00+00:00', p_empty['id']))
    db.execute('UPDATE canvas_projects SET updated_at=? WHERE id=?', ('2026-11-11T00:00:00+00:00', p_multi['id']))
    db.execute('UPDATE canvas_workflows SET updated_at=? WHERE id=?', ('2026-11-12T00:00:00+00:00', wf1['id']))
    db.execute('UPDATE canvas_workflows SET updated_at=? WHERE id=?', ('2026-11-19T12:34:56+00:00', wf2['id']))
    db.execute('UPDATE canvas_workflows SET updated_at=? WHERE id=?', ('2026-11-25T00:00:00+00:00', wf_del['id']))
    # Mark wf_del as deleted in canvas_deletions; it must not count or affect updated_at.
    db.execute("INSERT INTO canvas_deletions (scope, id, manifest, completed) VALUES ('workflow', ?, '{}', 1)", (wf_del['id'],))
    db.commit()

    listed = store.list_projects()
    by_id = {p['id']: p for p in listed}
    assert by_id[p_empty['id']]['workflow_count'] == 0
    assert by_id[p_empty['id']]['updated_at'] == '2026-11-10T00:00:00+00:00'
    assert by_id[p_multi['id']]['workflow_count'] == 2
    assert by_id[p_multi['id']]['updated_at'] == '2026-11-19T12:34:56+00:00'
    # Sorted by effective updated_at DESC
    assert [p['id'] for p in listed[:2]] == [p_multi['id'], p_empty['id']]

    # Also verify HTTP endpoint /api/canvas/projects
    res = application.app.test_client().get('/api/canvas/projects')
    assert res.status_code == 200
    http_by_id = {p['id']: p for p in res.get_json()['projects']}
    assert http_by_id[p_multi['id']]['workflow_count'] == 2
    assert http_by_id[p_multi['id']]['updated_at'] == '2026-11-19T12:34:56+00:00'


# ------------------------------------------------------------------ 2. zero-cost preflight

def _block_network(monkeypatch):
    def forbid(*_a, **_kw):
        raise AssertionError('preflight must never perform any external network or provider call')
    monkeypatch.setattr(socket, 'create_connection', forbid)
    monkeypatch.setattr(requests.Session, 'request', forbid)


def test_preflight_zero_cost_no_network_and_never_leaks_key_or_endpoint(provider_client, monkeypatch):
    _block_network(monkeypatch)
    created = provider_client.post('/api/provider-profiles', json={
        'name': 'Ark 视频测试',
        'kind': 'video',
        'adapter': 'ark',
        'enabled': True,
        'settings': {
            'endpoint': 'https://ark.example.test',
            'model': FAKE_EP,
            'seedance_2_5_model': FAKE_EP_M,
        },
        'api_key': FAKE_KEY,
    })
    assert created.status_code == 201
    profile_id = created.json['profile']['id']

    res = provider_client.post(f'/api/provider-profiles/{profile_id}/check', json={})
    assert res.status_code == 200
    assert res.headers['Cache-Control'] == 'no-store'
    raw_text = res.get_data(as_text=True)
    assert FAKE_KEY not in raw_text
    assert 'p1probe' not in raw_text
    body = res.json
    assert body['success'] is True
    assert body['zero_cost'] is True
    assert body['external_calls'] == 0
    assert body['status'] == 'ok'
    checks = {c['key']: c for c in body['checks']}
    assert checks['enabled']['status'] == 'ok'
    assert checks['api_key']['status'] == 'ok'
    assert checks['endpoint']['status'] == 'ok'
    assert checks['model']['status'] == 'ok'
    assert checks['kind_adapter']['status'] == 'ok'


def test_preflight_warns_and_errors_for_incomplete_or_risky_configs(provider_client, monkeypatch):
    _block_network(monkeypatch)
    # 1. Cupsy profile with missing key, HTTP endpoint, localhost source_base_url, disabled, bad TTL (via override)
    created = provider_client.post('/api/provider-profiles', json={
        'name': 'Cupsy 视频检查',
        'kind': 'video',
        'adapter': 'cupsy',
        'enabled': False,
        'settings': {
            'endpoint': 'http://cupsy.example.test',
            'model': 'seedance-2.5',
            'source_base_url': 'http://127.0.0.1:4545',
            'asset_token_ttl_seconds': 7200,
        },
        'api_key': '',
    })
    assert created.status_code == 201
    pid = created.json['profile']['id']

    res = provider_client.post(f'/api/provider-profiles/{pid}/check', json={
        'settings': {'asset_token_ttl_seconds': 300},
    })
    assert res.status_code == 200
    body = res.json
    assert body['status'] == 'error'
    checks = {c['key']: c for c in body['checks']}
    assert checks['enabled']['status'] == 'warn'
    assert checks['api_key']['status'] == 'error'
    assert checks['endpoint']['status'] == 'warn'
    assert checks['cupsy_source']['status'] == 'warn'
    assert checks['cupsy_ttl']['status'] == 'error'

    # 2. Draft preflight (unsaved new profile) with valid Cupsy HTTPS public source -> ok
    ok_res = provider_client.post('/api/provider-profiles/check', json={
        'kind': 'audio',
        'adapter': 'cupsy',
        'enabled': True,
        'api_key': FAKE_KEY,
        'settings': {
            'endpoint': 'https://cupsy.example.test',
            'model': 'seed-audio-1.0',
            'source_base_url': 'https://media.example.test',
            'asset_token_ttl_seconds': 14400,
        },
    })
    assert ok_res.status_code == 200
    assert FAKE_KEY not in ok_res.get_data(as_text=True)
    assert ok_res.json['status'] == 'ok'
    ok_checks = {c['key']: c for c in ok_res.json['checks']}
    assert ok_checks['cupsy_source']['status'] == 'ok'
    assert ok_checks['cupsy_ttl']['status'] == 'ok'

    # 3. Draft with unsupported kind/adapter, placeholder ep-your-..., and credentialed URL -> error
    bad_res = provider_client.post('/api/provider-profiles/check', json={
        'kind': 'audio',
        'adapter': 'ark',
        'enabled': True,
        'api_key': 'your-api-key-here',  # secret-scan: allow (placeholder detection test)
        'settings': {'endpoint': 'https://user:pass@ark.example.test'},
    })
    assert bad_res.status_code == 200
    bad_checks = {c['key']: c for c in bad_res.json['checks']}
    assert bad_checks['kind_adapter']['status'] == 'error'
    assert bad_checks['api_key']['status'] == 'warn'
    assert bad_checks['endpoint']['status'] == 'error'
    assert 'your-api-key-here' not in bad_res.get_data(as_text=True)

    # 4. Same-origin write guard applies to preflight POST, and missing profile returns 404
    assert provider_client.post(f'/api/provider-profiles/{pid}/check', json={}, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert provider_client.post('/api/provider-profiles/' + '0' * 32 + '/check', json={}).status_code == 404


def test_preflight_handles_null_fields_without_500(provider_client, monkeypatch):
    """QA-P1-01 regression: null api_key and optional fields must never trigger HTTP 500."""
    _block_network(monkeypatch)
    created = provider_client.post('/api/provider-profiles', json={
        'name': 'Null 安全回归',
        'kind': 'video',
        'adapter': 'cupsy',
        'enabled': True,
        'settings': {
            'endpoint': 'https://cupsy.example.test',
            'model': 'seedance-2.5',
            'source_base_url': 'https://media.example.test',
            'asset_token_ttl_seconds': 7200,
        },
        'api_key': FAKE_KEY,
    })
    assert created.status_code == 201
    pid = created.json['profile']['id']

    # Saved profile with api_key=null keeps saved key and returns 200 (never 500)
    res_saved = provider_client.post(f'/api/provider-profiles/{pid}/check', json={
        'api_key': None,
        'clear_api_key': None,
        'settings': {'source_base_url': None, 'asset_token_ttl_seconds': None},
    })
    assert res_saved.status_code == 200
    assert FAKE_KEY not in res_saved.get_data(as_text=True)
    saved_checks = {c['key']: c for c in res_saved.json['checks']}
    assert saved_checks['api_key']['status'] == 'ok'
    assert saved_checks['cupsy_source']['status'] == 'warn'
    assert saved_checks['cupsy_ttl']['status'] == 'ok'

    # Draft profile with null api_key, endpoint, model, kind, adapter, enabled returns structured 200 errors (never 500)
    res_draft = provider_client.post('/api/provider-profiles/check', json={
        'kind': None,
        'adapter': None,
        'enabled': None,
        'api_key': None,
        'settings': {'endpoint': None, 'model': None},
    })
    assert res_draft.status_code == 200
    assert res_draft.json['status'] == 'error'
    draft_checks = {c['key']: c for c in res_draft.json['checks']}
    assert draft_checks['enabled']['status'] == 'error'
    assert draft_checks['kind_adapter']['status'] == 'error'
    assert draft_checks['api_key']['status'] == 'error'
    assert draft_checks['endpoint']['status'] == 'error'

    # Draft with api_key=null on valid kind/adapter reports missing key cleanly (200)
    res_draft_ark = provider_client.post('/api/provider-profiles/check', json={
        'kind': 'image',
        'adapter': 'ark',
        'enabled': True,
        'api_key': None,
        'settings': {'endpoint': 'https://ark.example.test', 'model': None},
    })
    assert res_draft_ark.status_code == 200
    ark_checks = {c['key']: c for c in res_draft_ark.json['checks']}
    assert ark_checks['api_key']['status'] == 'error'
    assert ark_checks['model']['status'] == 'warn'


# ------------------------------------------------------------------ 3. Extended ep- redaction & 5.5/pricing compat

@pytest.mark.parametrize(('raw', 'expected_substring'), [
    (f'err {FAKE_EP} done', f'err {ENDPOINT_MASK} done'),
    (f'err _{FAKE_EP} done', f'err _{ENDPOINT_MASK} done'),
    (f'err -{FAKE_EP} done', f'err -{ENDPOINT_MASK} done'),
    (f'prefix_{FAKE_EP}', f'prefix_{ENDPOINT_MASK}'),
    (f'prefix-{FAKE_EP}', f'prefix-{ENDPOINT_MASK}'),
    ('err %65%70-20990101000000-p1probe done', f'err {ENDPOINT_MASK} done'),
    ('err %45%50-20990101000000-p1probe done', f'err {ENDPOINT_MASK} done'),
    ('err ep%2D20990101000000%2Dp1probe done', f'err {ENDPOINT_MASK} done'),
    ('err ep%2d20990101000000-p1probe done', f'err {ENDPOINT_MASK} done'),
    ('err %2Dep-20990101000000-p1probe done', f'err %2D{ENDPOINT_MASK} done'),  # secret-scan: allow
    ('err %5Fep-20990101000000-p1probe done', f'err %5F{ENDPOINT_MASK} done'),  # secret-scan: allow
    ('q=model%3D%65%70%2D%6D%2D20990101000000%2Dp1probe', f'q=model%3D{ENDPOINT_MASK}'),
])
def test_mask_endpoint_ids_covers_prefixed_and_urlencoded_variants(raw, expected_substring):
    masked = mask_endpoint_ids(raw)
    assert masked == expected_substring
    assert 'p1probe' not in masked
    assert '20990101000000' not in masked


def test_mask_endpoint_ids_keeps_false_positives_intact():
    for safe in ('step-by-step', 'ep-1 第一集', 'ep-2026 片段', 'deep-20990101000000-abc',
                 'keep-20990101000000-x', 'EP-12-final', 'ep-test', ''):
        assert mask_endpoint_ids(safe) == safe
        assert mask_text(safe) == safe


def test_task_error_persistence_and_canvas_error_redact_ep_without_breaking_pricing(monkeypatch, tmp_path):
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(tmp_path / 'canvas_assets'))
    store.init_canvas_db()

    # 1. Task persistence masks ep- / _ep- / URL-encoded in fail_task, reschedule_task, update_task
    t1 = task_db.create_task('image', '测试', {'model': FAKE_EP, 'size': '2048x2048'}, provider='ark')
    task_db.fail_task(t1, f'Ark 404: _{FAKE_EP} and ep%2D20990101000000%2Dp1probe')
    row1 = task_db.get_task(t1)
    assert 'p1probe' not in row1['error']
    assert f'_{ENDPOINT_MASK}' in row1['error']
    assert row1['params']['model'] == FAKE_EP  # params.model untouched for pricing/5.5!

    t2 = task_db.create_task('video', '测试2', {'model': 'seedance-2.0'}, provider='ark', status='processing')
    task_db.reschedule_task(t2, 5, status='processing', error=f'retry -{FAKE_EP}')
    assert 'p1probe' not in task_db.get_task(t2)['error']
    task_db.update_task(t2, error='direct %65%70-20990101000000-p1probe')
    assert 'p1probe' not in task_db.get_task(t2)['error']

    # 2. Canvas document save, writeback, and legacy read all mask ep- variants
    proj = store.create_project('脱敏测试项目')
    wf = store.create_workflow(proj['id'], '脱敏画布')
    with application.app.test_request_context('/', method='POST', json={'canvas_workflow_id': wf['id']}):
        t3 = task_db.create_task('video', 'p', {}, status='pending')
    doc = {
        'version': 1,
        'nodes': [
            {'id': 'n1', 'type': 'video', 'title': 'n1', 'x': 0, 'y': 0, 'text': '',
             'task': {'id': t3, 'status': 'pending', 'error': None}},
            {'id': 'n2', 'type': 'image', 'title': 'n2', 'x': 200, 'y': 0, 'text': '',
             'task': {'id': t1, 'status': 'failed', 'error': 'raw %2Dep-20990101000000-p1probe'}},  # secret-scan: allow
        ],
        'edges': [],
        'viewport': {'x': 0, 'y': 0, 'zoom': 1},
    }
    saved = store.update_workflow(wf['id'], wf['title'], doc, wf['revision'])
    assert 'p1probe' not in json.dumps(saved, ensure_ascii=False)
    # Also simulate a legacy raw DB document containing _ep- and verify store.workflow() masks on read
    raw_doc = json.loads(task_db.get_db().execute('SELECT document FROM canvas_workflows WHERE id=?', (wf['id'],)).fetchone()['document'])
    raw_doc['nodes'][1]['task']['error'] = f'legacy _{FAKE_EP}'
    task_db.get_db().execute('UPDATE canvas_workflows SET document=? WHERE id=?', (json.dumps(raw_doc), wf['id']))
    task_db.get_db().commit()
    reread = store.workflow(wf['id'])
    assert 'p1probe' not in reread['document']['nodes'][1]['task']['error']

    # Writeback masks even if a legacy task row had raw URL-encoded ep-
    task_db.get_db().execute('UPDATE tasks SET status=?, error=? WHERE id=?', ('failed', 'wb %65%70%2D20990101000000%2Dp1probe', t3))
    task_db.get_db().commit()
    canvas_writeback.apply_task_result(t3)
    wb_doc = store.workflow(wf['id'])['document']
    assert 'p1probe' not in wb_doc['nodes'][0]['task']['error']

    # 3. Compatibility boundary: Seedream 5.5 capability & cost estimation stay accurate with ep- model
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {'api_key': 'k', 'model': FAKE_EP})
    monkeypatch.setitem(application.config['generation']['image']['byteplus'], 'model', FAKE_EP)
    assert seedream55.enabled(FAKE_EP) is True
    assert seedream55.capability_model(FAKE_EP) == seedream55.MODEL
    est = cost_estimate.compute_task_estimate({
        'id': t1, 'type': 'image', 'provider': 'ark', 'status': 'succeeded',
        'params': {'model': FAKE_EP, 'size': '2048x2048', 'seedream55': True},
        'result': {'local_images': ['/api/tasks/1/file/a.png']},
    }, task_db.get_db())
    assert est is not None and est.get('status') == 'estimate' and est['maximum_cost'] > 0
    assert est.get('model') == cost_estimate.SEEDREAM_55
