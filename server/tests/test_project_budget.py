"""V24-W3-BUDGET-HISTORY-20261121 AC1: project budget soft-warning threshold API & ledger integration."""
import json

import pytest

import app as application
import canvas_store as store
import cost_ledger
import tasks as task_db


def _client():
    return application.app.test_client()


def _video_params(**extra):
    return {
        'model': 'seedance-2.0',
        'ratio': '16:9',
        'duration': 5,
        'resolution': '720p',
        'fast': False,
        'video_mode': 'reference',
        **extra,
    }


def _canvas_task(workflow_id, node_id, kind='video', params=None, status='succeeded', provider='ark'):
    with application.app.test_request_context('/', method='POST', json={
            'canvas_workflow_id': workflow_id, 'canvas_node_id': node_id}):
        return task_db.create_task(
            kind,
            'budget prompt',
            params if params is not None else _video_params(),
            provider=provider,
            status=status,
        )


def test_budget_crud_validation_and_ledger_payload(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('budget endpoints must never call a Provider')
    monkeypatch.setattr(application.HTTP, 'post', forbidden)
    monkeypatch.setattr(application.HTTP, 'get', forbidden)

    project = store.create_project('预算项目A')
    workflow = store.create_workflow(project['id'], '画布1')
    _canvas_task(workflow['id'], 'v1', kind='video')  # ~$0.756
    _canvas_task(workflow['id'], 'a1', kind='audio', params={'model': 'seed-audio-1.0'}, provider='cupsy')  # unknown

    c = _client()
    # Read-only GET before any budget table exists returns budget_usd=None without writing.
    res = c.get('/api/cost-ledger/budget', query_string={'project_id': project['id']})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['project_id'] == project['id']
    assert data['budget_usd'] is None
    assert data['billable']['known_count'] == 1
    assert data['billable']['unknown_count'] == 1
    assert data['billable']['known_usd_min'] == pytest.approx(0.756)

    # Also supports workflow_id fallback lookup.
    wf_res = c.get('/api/cost-ledger/budget', query_string={'workflow_id': workflow['id']})
    assert wf_res.status_code == 200
    assert wf_res.get_json()['project_id'] == project['id']

    # Set valid positive budget.
    put_res = c.put('/api/cost-ledger/budget', json={'project_id': project['id'], 'budget_usd': 5.0})
    assert put_res.status_code == 200
    put_data = put_res.get_json()
    assert put_data['budget_usd'] == pytest.approx(5.0)
    assert put_data['updated_at']

    # Persists on GET /api/cost-ledger/budget and GET /api/cost-ledger.
    assert c.get('/api/cost-ledger/budget', query_string={'project_id': project['id']}).get_json()['budget_usd'] == pytest.approx(5.0)
    ledger_proj = c.get('/api/cost-ledger', query_string={'project_id': project['id']}).get_json()
    assert ledger_proj['budget_usd'] == pytest.approx(5.0)
    assert ledger_proj['project_billable']['known_count'] == 1
    assert ledger_proj['project_billable']['unknown_count'] == 1
    assert 'actual' not in json.dumps(ledger_proj).lower()

    ledger_wf = c.get('/api/cost-ledger', query_string={'workflow_id': workflow['id']}).get_json()
    assert ledger_wf['budget_usd'] == pytest.approx(5.0)

    # Update to upper boundary 100000.
    max_res = c.put('/api/cost-ledger/budget', json={'project_id': project['id'], 'budget_usd': 100000})
    assert max_res.status_code == 200 and max_res.get_json()['budget_usd'] == pytest.approx(100000.0)

    # Clear via null.
    clear_res = c.put('/api/cost-ledger/budget', json={'project_id': project['id'], 'budget_usd': None})
    assert clear_res.status_code == 200 and clear_res.get_json()['budget_usd'] is None
    assert c.get('/api/cost-ledger/budget', query_string={'project_id': project['id']}).get_json()['budget_usd'] is None
    assert c.get('/api/cost-ledger', query_string={'project_id': project['id']}).get_json()['budget_usd'] is None


@pytest.mark.parametrize('bad_value', [0, -1, -0.01, 100000.01, 999999, True, False, '5.0', [], {}])
def test_budget_rejects_invalid_values(bad_value):
    project = store.create_project('校验项目')
    c = _client()
    res = c.put('/api/cost-ledger/budget', json={'project_id': project['id'], 'budget_usd': bad_value})
    assert res.status_code == 400, res.get_json()
    assert res.get_json()['success'] is False


def test_budget_validation_missing_fields_and_unknown_project():
    c = _client()
    assert c.get('/api/cost-ledger/budget').status_code == 400
    assert c.get('/api/cost-ledger/budget', query_string={'project_id': '__unassigned__'}).status_code == 400
    assert c.put('/api/cost-ledger/budget', json={'project_id': 'no-such-project', 'budget_usd': 5.0}).status_code == 404
    assert c.put('/api/cost-ledger/budget', json={'project_id': 'x'}).status_code == 400
    assert c.put('/api/cost-ledger/budget', json={'budget_usd': 5.0}).status_code == 400


def test_budget_enforces_same_origin_and_auth(monkeypatch):
    project = store.create_project('权限项目')
    c = _client()

    # Cross-site PUT is rejected with 403; non-JSON is rejected with 415.
    cross = c.put(
        '/api/cost-ledger/budget',
        json={'project_id': project['id'], 'budget_usd': 10},
        headers={'Sec-Fetch-Site': 'cross-site'},
    )
    assert cross.status_code == 403

    bad_origin = c.put(
        '/api/cost-ledger/budget',
        json={'project_id': project['id'], 'budget_usd': 10},
        headers={'Origin': 'https://evil.invalid'},
    )
    assert bad_origin.status_code == 403

    not_json = c.put('/api/cost-ledger/budget', data='plain', content_type='text/plain')
    assert not_json.status_code == 415

    # Login auth guard applies to both GET and PUT when AUTH_CONFIG is enabled.
    monkeypatch.setitem(application.AUTH_CONFIG, 'username', 'admin')
    monkeypatch.setitem(application.AUTH_CONFIG, 'password', 'pass')
    assert c.get('/api/cost-ledger/budget', query_string={'project_id': project['id']}).status_code == 401
    assert c.put('/api/cost-ledger/budget', json={'project_id': project['id'], 'budget_usd': 10}).status_code == 401
    with c.session_transaction() as sess:
        sess['logged_in'] = True
    assert c.put('/api/cost-ledger/budget', json={'project_id': project['id'], 'budget_usd': 12.5}).status_code == 200
    assert c.get('/api/cost-ledger/budget', query_string={'project_id': project['id']}).get_json()['budget_usd'] == pytest.approx(12.5)
