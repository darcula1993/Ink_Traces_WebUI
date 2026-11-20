"""P0-CANVAS-CANCEL-20261120: POST /api/tasks/<id>/cancel boundaries, canvas write-back & group run."""
import io
from pathlib import Path

from PIL import Image
import pytest

import app as application
import canvas_group_run as group_run
import canvas_store as store
import canvas_writeback
import storage
import tasks as task_db


def _png_bytes(color='red'):
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), color).save(buf, format='PNG')
    return buf.getvalue()


def _create_canvas_task(wid, node_id, *, status='pending', stage=None, lease_owner=None,
                        provider='ark', task_type='image', external_task_id=None, extra_params=None):
    params = {'canvas_workflow_id': wid, 'canvas_node_id': node_id, **(extra_params or {})}
    tid = task_db.create_task(task_type, 'prompt ' + node_id, params, provider=provider, status=status)
    updates = {}
    if stage is not None:
        updates['stage'] = stage
    if external_task_id is not None:
        updates['external_task_id'] = external_task_id
    if updates:
        task_db.update_task(tid, **updates)
    if lease_owner is not None:
        db = task_db.get_db()
        db.execute(
            "UPDATE tasks SET lease_owner = ?, lease_until = '2999-01-01T00:00:00+00:00' WHERE id = ?",
            (lease_owner, tid),
        )
        db.commit()
    return tid


@pytest.fixture
def canvas_env(isolated_backend, monkeypatch):
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(isolated_backend / 'canvas_assets'))

    def guard(*args, **kwargs):
        raise AssertionError('external provider HTTP must not be called')

    for name in ('get', 'post', 'put', 'delete', 'request'):
        if hasattr(application.HTTP, name):
            monkeypatch.setattr(application.HTTP, name, guard)

    project = store.create_project('cancel-test')['id']
    workflow = store.create_workflow(project, 'cancel-canvas')
    return {
        'wid': workflow['id'],
        'client': application.app.test_client(),
        'url': '/api/canvas/workflows/' + workflow['id'],
    }


def _save_nodes(wid, nodes, edges=(), groups=()):
    wf = store.workflow(wid)
    doc = {**wf['document'], 'nodes': nodes, 'edges': list(edges), 'groups': list(groups)}
    return store.update_workflow(wid, wf['title'], doc, wf['revision'])


def _gen_node(node_id, task=None, *, node_type='image'):
    return {
        'id': node_id, 'type': node_type, 'title': node_id, 'x': 0, 'y': 0,
        'text': 'prompt ' + node_id, 'params': {}, 'task': task,
    }


def test_cancel_pending_canvas_task_writes_back_and_clears_stage(canvas_env):
    wid, client = canvas_env['wid'], canvas_env['client']
    tid = _create_canvas_task(wid, 'n1', status='pending', stage='downloading')
    saved = _save_nodes(wid, [_gen_node('n1', {'id': tid, 'status': 'pending', 'error': None})])

    resp = client.post(f'/api/tasks/{tid}/cancel')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['status'] == 'cancelled'
    assert body['task']['status'] == 'cancelled'
    assert body['task']['stage'] is None

    db_task = task_db.get_task(tid)
    assert db_task['status'] == 'cancelled'
    assert db_task['stage'] is None
    assert db_task['completed_at'] is not None
    assert task_db.claim_next_task('worker-1') is None

    # Immediate canvas write-back happened without waiting for a worker.
    wf = store.workflow(wid)
    assert wf['revision'] == saved['revision'] + 1
    assert wf['document']['nodes'][0]['task'] == {'id': tid, 'status': 'cancelled', 'error': None}


def test_cancel_leased_processing_task_sets_cancel_requested_and_clears_stage(canvas_env):
    wid, client = canvas_env['wid'], canvas_env['client']
    tid = _create_canvas_task(
        wid, 'n1', status='processing', stage='downloading',
        lease_owner='worker-1', task_type='video',
    )
    saved = _save_nodes(wid, [_gen_node('n1', {'id': tid, 'status': 'processing', 'error': None}, node_type='video')])

    resp = client.post(f'/api/tasks/{tid}/cancel')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['status'] == 'cancel_requested'
    assert body['task']['status'] == 'cancel_requested'
    assert body['task']['stage'] is None
    assert task_db.get_task(tid)['lease_owner'] == 'worker-1'
    # Still active until worker finalizes; no premature write-back yet.
    assert store.workflow(wid)['revision'] == saved['revision']

    # Idempotent second call while cancel_requested returns 200 cancel_requested.
    again = client.post(f'/api/tasks/{tid}/cancel')
    assert again.status_code == 200
    assert again.get_json()['status'] == 'cancel_requested'


@pytest.mark.parametrize('kind,expected_status,expected_substr', [
    ('succeeded', 'succeeded', '已完成'),
    ('failed', 'failed', '已失败'),
    ('result_unknown', 'failed', '结果未知'),
    ('cancelled', 'cancelled', '已取消'),
])
def test_cancel_terminal_task_returns_409_without_mutating_or_calling_upstream(
    canvas_env, monkeypatch, kind, expected_status, expected_substr,
):
    wid, client = canvas_env['wid'], canvas_env['client']
    tid = _create_canvas_task(
        wid, 'n1', status='processing', provider='cupsy', task_type='video', external_task_id='ext_vid_1',
    )
    if kind == 'succeeded':
        task_db.complete_task(tid, {'video_url': '/outputs/v.mp4'})
    elif kind == 'failed':
        task_db.fail_task(tid, 'provider rejected')
    elif kind == 'result_unknown':
        task_db.fail_task_result_unknown(tid, '上游超时，结果未知', 'timeout')
    elif kind == 'cancelled':
        task_db.request_task_cancel(tid)

    before = task_db.get_task(tid)
    resp = client.post(f'/api/tasks/{tid}/cancel')
    assert resp.status_code == 409
    body = resp.get_json()
    assert body['success'] is False
    assert body['code'] == 'task_terminal'
    assert body['status'] == expected_status
    assert expected_substr in body['error']
    assert body['task']['status'] == expected_status

    after = task_db.get_task(tid)
    assert after['status'] == before['status']
    assert after['result'] == before['result']
    assert after['error'] == before['error']
    if kind == 'result_unknown':
        assert after['result']['result_unknown'] is True


def test_cancel_nonexistent_returns_404_and_auth_blocks_anonymous(canvas_env, monkeypatch):
    client = canvas_env['client']
    assert client.post('/api/tasks/999999/cancel').status_code == 404

    monkeypatch.setitem(application.AUTH_CONFIG, 'username', 'admin')
    monkeypatch.setitem(application.AUTH_CONFIG, 'password', 'secret')
    unauth = application.app.test_client()
    assert unauth.post('/api/tasks/1/cancel').status_code == 401


def test_cancel_group_run_member_via_api_blocks_downstream_and_advances_cleanly(canvas_env, monkeypatch):
    wid, client, url = canvas_env['wid'], canvas_env['client'], canvas_env['url']
    calls = []

    def submitter(workflow_id, node_id, ctx):
        calls.append(node_id)
        tid = _create_canvas_task(
            workflow_id, node_id, status='pending', extra_params={'group_run_id': ctx['run_id']},
        )
        wf = store.workflow(workflow_id)
        doc = wf['document']
        for n in doc['nodes']:
            if n['id'] == node_id:
                n['task'] = {'id': tid, 'status': 'pending', 'error': None}
        store.update_workflow(workflow_id, wf['title'], doc, wf['revision'])
        return {'task_id': tid}

    monkeypatch.setattr(group_run, '_submitter', submitter)
    monkeypatch.setattr(group_run, '_estimator', lambda *a, **k: {'known': True, 'usd': 0.1, 'reason': None})

    # Two branches inside one group: a -> b -> c, and independent x -> y.
    nodes = [_gen_node(nid) for nid in ('a', 'b', 'c', 'x', 'y')]
    edges = [
        {'id': 'e1', 'source': 'a', 'target': 'b'},
        {'id': 'e2', 'source': 'b', 'target': 'c'},
        {'id': 'e3', 'source': 'x', 'target': 'y'},
    ]
    groups = [{'id': 'g1', 'title': '节点组1', 'nodeIds': ['a', 'b', 'c', 'x', 'y']}]
    saved = _save_nodes(wid, nodes, edges, groups)

    preview = client.post(f'{url}/groups/g1/run-preview', json={'revision': saved['revision']}).get_json()['preview']
    run = client.post(
        f'{url}/group-runs',
        json={'group_id': 'g1', 'revision': preview['revision'], 'preview_token': preview['preview_token']},
    ).get_json()['run']
    assert calls == ['a', 'x']

    by_node = {n['node_id']: n for n in run['nodes']}
    a_task, x_task = by_node['a']['task_id'], by_node['x']['task_id']

    # Cancel member node `a` directly via the single-task cancel HTTP endpoint.
    cancel_resp = client.post(f'/api/tasks/{a_task}/cancel')
    assert cancel_resp.status_code == 200
    assert cancel_resp.get_json()['status'] == 'cancelled'

    # Group run state machine advanced immediately: a cancelled, b & c blocked, x & y unaffected.
    mid = client.get(f'{url}/group-runs/{run["id"]}').get_json()['run']
    mid_states = {n['node_id']: (n['status'], n['reason']) for n in mid['nodes']}
    assert mid['status'] == 'running'
    assert mid_states['a'] == ('cancelled', 'task_cancelled')
    assert mid_states['b'] == ('blocked', 'upstream_cancelled')
    assert mid_states['c'] == ('blocked', 'upstream_blocked')
    assert mid_states['x'] == ('submitted', None)
    assert mid_states['y'] == ('waiting', None)

    # Complete x -> submits y -> complete y -> group run finalizes cleanly.
    def succeed(tid, color):
        out_dir = Path(storage.OUTPUT_DIR) / 'image' / str(tid)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / 'image_0.png'
        path.write_bytes(_png_bytes(color))
        task_db.register_asset(tid, 'output_image', str(path), 'image/png')
        task_db.complete_task(tid, {'images': [str(path)]})
        canvas_writeback.apply_task_result(tid)
        group_run.on_task_terminal(tid)

    succeed(x_task, 'blue')
    assert calls == ['a', 'x', 'y']
    y_task = next(n['task_id'] for n in client.get(f'{url}/group-runs/{run["id"]}').get_json()['run']['nodes'] if n['node_id'] == 'y')
    succeed(y_task, 'green')

    final = client.get(f'{url}/group-runs/{run["id"]}').get_json()['run']
    assert final['status'] == 'completed'
    assert final['finished_at'] is not None


def test_cancel_sole_live_member_in_group_run_finalizes_run_immediately(canvas_env, monkeypatch):
    wid, client, url = canvas_env['wid'], canvas_env['client'], canvas_env['url']

    def submitter(workflow_id, node_id, ctx):
        tid = _create_canvas_task(
            workflow_id, node_id, status='pending', extra_params={'group_run_id': ctx['run_id']},
        )
        wf = store.workflow(workflow_id)
        doc = wf['document']
        for n in doc['nodes']:
            if n['id'] == node_id:
                n['task'] = {'id': tid, 'status': 'pending', 'error': None}
        store.update_workflow(workflow_id, wf['title'], doc, wf['revision'])
        return {'task_id': tid}

    monkeypatch.setattr(group_run, '_submitter', submitter)
    monkeypatch.setattr(group_run, '_estimator', lambda *a, **k: {'known': True, 'usd': 0.1, 'reason': None})

    saved = _save_nodes(
        wid,
        [_gen_node('a'), _gen_node('b')],
        [{'id': 'e1', 'source': 'a', 'target': 'b'}],
        [{'id': 'g1', 'title': '节点组1', 'nodeIds': ['a', 'b']}],
    )
    preview = client.post(f'{url}/groups/g1/run-preview', json={'revision': saved['revision']}).get_json()['preview']
    run = client.post(
        f'{url}/group-runs',
        json={'group_id': 'g1', 'revision': preview['revision'], 'preview_token': preview['preview_token']},
    ).get_json()['run']
    a_task = next(n['task_id'] for n in run['nodes'] if n['node_id'] == 'a')

    resp = client.post(f'/api/tasks/{a_task}/cancel')
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'cancelled'

    final = client.get(f'{url}/group-runs/{run["id"]}').get_json()['run']
    assert final['status'] == 'completed'
    assert final['finished_at'] is not None
    assert {n['node_id']: (n['status'], n['reason']) for n in final['nodes']} == {
        'a': ('cancelled', 'task_cancelled'),
        'b': ('blocked', 'upstream_cancelled'),
    }
    assert client.get(f'{url}/group-runs?active=1').get_json()['runs'] == []
