"""CANVAS-WRITEBACK-20261114: server-side task result write-back, task-sync and PUT merge.

Acceptance 1-6 (backend part). Two windows are simulated with two test clients.
No provider is ever reached: HTTP is replaced by a guard that fails the test.
"""
import io
import logging
from pathlib import Path

from PIL import Image
import pytest

import app as application
import canvas_store as store
import canvas_writeback
import storage
import tasks as task_db
import worker


def png(color):
    data = io.BytesIO()
    Image.new('RGB', (2, 2), color).save(data, format='PNG')
    return data.getvalue()


@pytest.fixture
def env(isolated_backend, monkeypatch):
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(isolated_backend / 'canvas_assets'))
    calls = []

    def guard(*args, **kwargs):
        calls.append(args)
        raise AssertionError('provider must not be called by write-back')
    for name in ('get', 'post', 'put', 'delete', 'request'):
        if hasattr(application.HTTP, name):
            monkeypatch.setattr(application.HTTP, name, guard)
    project = store.create_project('p')['id']
    wf = store.create_workflow(project, 'c')
    return {'workflow': wf, 'calls': calls}


def make_task(workflow_id, status='pending', colors=('red', 'blue'), name='铁门'):
    with application.app.test_request_context('/', method='POST', json={'canvas_workflow_id': workflow_id, 'result_name': name}):
        tid = task_db.create_task('image', 'p', {}, status=status)
    directory = Path(storage.OUTPUT_DIR) / 'image' / str(tid)
    directory.mkdir(parents=True)
    for index, color in enumerate(colors):
        path = directory / f'image_{index}.png'
        path.write_bytes(png(color))
        task_db.register_asset(tid, 'output_image', str(path), 'image/png')
    return tid


def node(node_id, task_id=None, status='pending', **extra):
    item = {'id': node_id, 'type': 'image', 'title': node_id, 'x': 0, 'y': 0, 'text': ''}
    if task_id:
        item['task'] = {'id': task_id, 'status': status, 'error': None}
    item.update(extra)
    return item


def put(client, wf, document, revision):
    return client.put(f"/api/canvas/workflows/{wf['id']}", json={'title': wf['title'], 'document': document, 'revision': revision})


def save_nodes(wf, *nodes):
    current = store.workflow(wf['id'])
    return store.update_workflow(wf['id'], current['title'], {**current['document'], 'nodes': list(nodes)}, current['revision'])


def doc_node(wf, node_id):
    return next((n for n in store.workflow(wf['id'])['document']['nodes'] if n['id'] == node_id), None)


def writeback_rows(wf):
    return [dict(r) for r in task_db.get_db().execute('SELECT revision,node_id,task_id FROM canvas_writebacks WHERE workflow_id=? ORDER BY revision', (wf['id'],))]


def task_snapshot(tid):
    row = task_db.get_db().execute('SELECT status,error,result,attempt_count,updated_at,completed_at,next_run_at FROM tasks WHERE id=?', (tid,)).fetchone()
    return dict(row)


# 1. single window -------------------------------------------------------------

def test_success_writes_result_once_like_client(env):
    wf = env['workflow']
    tid = make_task(wf['id'])
    saved = save_nodes(wf, node('n1', tid, upstreamStale=True), node('n2', text='keep'))
    task_db.update_task(tid, status='succeeded')
    assert canvas_writeback.apply_task_result(tid) == {wf['id']: saved['revision'] + 1}
    result = doc_node(wf, 'n1')
    assert result['task'] == {'id': tid, 'status': 'succeeded', 'error': None}
    assert [a['name'] for a in result['candidates']] == [f'铁门_{tid}.png', f'铁门_{tid}_2.png']
    assert result['asset'] == result['candidates'][0] and result['selectedCandidateId'] == result['asset']['id']
    assert 'upstreamStale' not in result
    assert doc_node(wf, 'n2')['text'] == 'keep'
    assert writeback_rows(wf) == [{'revision': saved['revision'] + 1, 'node_id': 'n1', 'task_id': tid}]
    # idempotent: no second import, no revision bump
    assets_before = task_db.get_db().execute('SELECT COUNT(*) FROM canvas_assets').fetchone()[0]
    assert canvas_writeback.apply_task_result(tid) == {}
    assert store.workflow(wf['id'])['revision'] == saved['revision'] + 1
    assert task_db.get_db().execute('SELECT COUNT(*) FROM canvas_assets').fetchone()[0] == assets_before == 2


def test_existing_candidates_are_kept_and_regeneration_appends(env):
    wf = env['workflow']
    first = make_task(wf['id'], colors=('red',))
    save_nodes(wf, node('n1', first))
    task_db.update_task(first, status='succeeded')
    canvas_writeback.apply_task_result(first)
    old = doc_node(wf, 'n1')
    second = make_task(wf['id'], colors=('red', 'green'))
    save_nodes(wf, {**old, 'task': {'id': second, 'status': 'processing', 'error': None}})
    task_db.update_task(second, status='succeeded')
    canvas_writeback.apply_task_result(second)
    result = doc_node(wf, 'n1')
    # red is deduplicated (already a candidate), only green is new -> selected
    assert [a['id'] for a in result['candidates']][0] == old['asset']['id'] and len(result['candidates']) == 2
    assert result['asset']['id'] == result['candidates'][1]['id'] == result['selectedCandidateId']


@pytest.mark.parametrize('status,error', [('failed', '生成失败：x'), ('cancelled', None)])
def test_failure_and_cancel_update_task_only(env, status, error):
    wf = env['workflow']
    tid = make_task(wf['id'])
    saved = save_nodes(wf, node('n1', tid, status='cancel_requested' if status == 'cancelled' else 'processing', upstreamStale=True))
    task_db.update_task(tid, status=status, error=error)
    canvas_writeback.apply_task_result(tid)
    result = doc_node(wf, 'n1')
    assert result['task'] == {'id': tid, 'status': status, 'error': error}
    assert 'candidates' in result and result['candidates'] == [] and 'asset' not in result
    assert result['upstreamStale'] is True
    assert store.workflow(wf['id'])['revision'] == saved['revision'] + 1
    assert task_db.get_db().execute('SELECT COUNT(*) FROM canvas_assets').fetchone()[0] == 0


def test_terminal_node_and_active_task_are_not_touched(env):
    wf = env['workflow']
    tid = make_task(wf['id'])
    saved = save_nodes(wf, node('n1', tid, status='pending'))
    assert canvas_writeback.apply_task_result(tid) == {}  # task not terminal
    save_nodes(wf, node('n1', tid, status='failed'))
    task_db.update_task(tid, status='succeeded')
    assert canvas_writeback.apply_task_result(tid) == {}  # node already terminal (client rule)
    assert store.workflow(wf['id'])['revision'] == saved['revision'] + 1


# 2. two windows -------------------------------------------------------------

def test_two_windows_receive_result_without_conflict(env):
    wf = env['workflow']
    a, b = application.app.test_client(), application.app.test_client()
    tid = make_task(wf['id'])
    saved = save_nodes(wf, node('n1', tid))
    task_db.update_task(tid, status='succeeded')
    canvas_writeback.apply_task_result(tid)  # worker
    url = f"/api/canvas/workflows/{wf['id']}/task-sync"
    first = a.post(url, json={'task_ids': [tid]})
    second = b.post(url, json={'task_ids': [tid, tid]})
    assert first.status_code == second.status_code == 200
    assert first.json == second.json
    assert first.json['revision'] == saved['revision'] + 1 and first.json['failed'] == []
    fields = first.json['nodes']['n1']
    assert set(fields) == {'task', 'candidates', 'asset', 'selectedCandidateId', 'upstreamStale'}
    assert fields['task']['status'] == 'succeeded' and len(fields['candidates']) == 2
    # both windows adopt the server revision and keep saving normally
    doc = a.get(f"/api/canvas/workflows/{wf['id']}").json['workflow']
    response = put(b, wf, doc['document'], doc['revision'])
    assert response.status_code == 200 and response.json['merged'] is False


def test_task_sync_writes_when_worker_did_not(env):
    wf = env['workflow']
    tid = make_task(wf['id'])
    saved = save_nodes(wf, node('n1', tid))
    task_db.update_task(tid, status='succeeded')
    client = application.app.test_client()
    url = f"/api/canvas/workflows/{wf['id']}/task-sync"
    first = client.post(url, json={'task_ids': [tid]}).json
    again = client.post(url, json={'task_ids': [tid]}).json
    assert first['revision'] == again['revision'] == saved['revision'] + 1
    assert first['nodes'] == again['nodes']
    assert len(writeback_rows(wf)) == 1


def test_task_sync_validation_and_foreign_tasks(env):
    wf = env['workflow']
    client = application.app.test_client()
    url = f"/api/canvas/workflows/{wf['id']}/task-sync"
    for bad in ([], [0], ['1'], list(range(1, 102)), None):
        assert client.post(url, json={'task_ids': bad}).status_code == 400
    other = store.create_workflow(store.create_project('q')['id'], 'x')
    foreign = make_task(other['id'])
    save_nodes(wf, node('n1', foreign))  # a node naming a task of another canvas
    task_db.update_task(foreign, status='succeeded')
    result = client.post(url, json={'task_ids': [foreign, 999999]}).json
    assert result['nodes'] == {} and result['failed'] == []
    assert doc_node(wf, 'n1')['task']['status'] == 'pending'
    assert client.post('/api/canvas/workflows/missing/task-sync', json={'task_ids': [1]}).status_code == 404


def test_task_sync_reports_unimportable_outputs(env):
    wf = env['workflow']
    tid = make_task(wf['id'])
    saved = save_nodes(wf, node('n1', tid))
    task_db.update_task(tid, status='succeeded')
    for path in (Path(storage.OUTPUT_DIR) / 'image' / str(tid)).iterdir():
        path.unlink()
    result = application.app.test_client().post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [tid]}).json
    assert result['failed'] == [tid] and result['revision'] == saved['revision']
    assert result['nodes']['n1']['task']['status'] == 'pending'


# 3/4. PUT merge -------------------------------------------------------------

def test_unsaved_edit_merges_over_writeback(env):
    wf = env['workflow']
    a = application.app.test_client()
    tid = make_task(wf['id'])
    base = save_nodes(wf, node('n1', tid, upstreamStale=True, text='old'), node('n2', text='before'))
    task_db.update_task(tid, status='succeeded')
    canvas_writeback.apply_task_result(tid)
    stale = base['document']
    stale['nodes'][1]['text'] = 'edited in window A'
    stale['nodes'][0]['text'] = 'prompt edited too'
    response = put(a, wf, stale, base['revision'])
    assert response.status_code == 200 and response.json['merged'] is True
    assert response.json['revision'] == base['revision'] + 2 == response.json['workflow']['revision']
    nodes = {n['id']: n for n in response.json['document']['nodes']}
    assert nodes['n2']['text'] == 'edited in window A' and nodes['n1']['text'] == 'prompt edited too'
    assert nodes['n1']['task']['status'] == 'succeeded' and len(nodes['n1']['candidates']) == 2
    assert nodes['n1']['selectedCandidateId'] == nodes['n1']['asset']['id'] and 'upstreamStale' not in nodes['n1']
    assert store.workflow(wf['id'])['document'] == response.json['document']
    # the merged save is a client save, not a write-back
    assert [r['revision'] for r in writeback_rows(wf)] == [base['revision'] + 1]


def test_merge_does_not_revive_deleted_node(env):
    wf = env['workflow']
    tid = make_task(wf['id'])
    base = save_nodes(wf, node('n1', tid), node('n2'))
    task_db.update_task(tid, status='failed', error='x')
    canvas_writeback.apply_task_result(tid)
    stale = {**base['document'], 'nodes': [n for n in base['document']['nodes'] if n['id'] != 'n1']}
    response = put(application.app.test_client(), wf, stale, base['revision'])
    assert response.json['merged'] is True and [n['id'] for n in response.json['document']['nodes']] == ['n2']


def test_merge_keeps_client_rebound_task(env):
    wf = env['workflow']
    old, new = make_task(wf['id']), make_task(wf['id'])
    base = save_nodes(wf, node('n1', old))
    task_db.update_task(old, status='failed', error='x')
    canvas_writeback.apply_task_result(old)
    stale = base['document']
    stale['nodes'][0]['task'] = {'id': new, 'status': 'pending', 'error': None}
    response = put(application.app.test_client(), wf, stale, base['revision'])
    assert response.json['merged'] is True and response.json['document']['nodes'][0]['task']['id'] == new


def test_two_real_edits_still_conflict(env):
    wf = env['workflow']
    a, b = application.app.test_client(), application.app.test_client()
    base = save_nodes(wf, node('n1', text='x'))
    doc_a, doc_b = store.workflow(wf['id'])['document'], store.workflow(wf['id'])['document']
    doc_a['nodes'][0]['text'] = 'A'
    doc_b['nodes'][0]['text'] = 'B'
    assert put(a, wf, doc_a, base['revision']).status_code == 200
    assert put(b, wf, doc_b, base['revision']).status_code == 409
    assert doc_node(wf, 'n1')['text'] == 'A'


def test_writeback_then_real_edit_then_stale_conflicts(env):
    wf = env['workflow']
    tid = make_task(wf['id'])
    base = save_nodes(wf, node('n1', tid), node('n2'))
    task_db.update_task(tid, status='cancelled')
    canvas_writeback.apply_task_result(tid)           # base+1 write-back
    current = store.workflow(wf['id'])
    edited = current['document']
    edited['nodes'][1]['text'] = 'real edit'
    assert put(application.app.test_client(), wf, edited, current['revision']).status_code == 200  # base+2 real
    stale = base['document']
    stale['nodes'][1]['text'] = 'other window'
    assert put(application.app.test_client(), wf, stale, base['revision']).status_code == 409
    assert doc_node(wf, 'n2')['text'] == 'real edit'
    # a future revision is never merged
    assert put(application.app.test_client(), wf, edited, current['revision'] + 5).status_code == 409


# 5. billing boundary --------------------------------------------------------

def test_writeback_and_sync_never_touch_task_or_provider(env):
    wf = env['workflow']
    tid = make_task(wf['id'])
    save_nodes(wf, node('n1', tid))
    task_db.fail_task_result_unknown(tid, '请求可能已发出、结果未知，请先到Provider核实', 'worker_exception')
    before = task_snapshot(tid)
    canvas_writeback.apply_task_result(tid)
    client = application.app.test_client()
    client.post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [tid]})
    assert task_snapshot(tid) == before
    assert env['calls'] == []
    result = doc_node(wf, 'n1')
    assert result['task']['status'] == 'failed' and 'candidates' in result and not result['candidates']
    # result_unknown stays server state, still exposed by the status endpoint
    status = client.get(f'/api/tasks/status?ids={tid}').get_json()['tasks'][0]
    assert status['status'] == 'failed' and status['result']['result_unknown'] is True


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(worker.application, 'config', {'server': {}})
    return worker.Worker()


def _claim_and_process(runner_worker):
    task = task_db.claim_next_task(runner_worker.worker_id, task_types=('image', 'layer'))
    assert task is not None
    runner_worker.process(task)


def _mock_success(monkeypatch):
    def execute(task_id):
        task_db.complete_task(task_id, {'mock': True})
        return {'success': True}, 200
    monkeypatch.setattr(application, 'execute_image_task', execute)


def test_worker_writes_back_on_terminal(env, runner, monkeypatch):
    wf = env['workflow']
    tid = make_task(wf['id'])
    saved = save_nodes(wf, node('n1', tid))
    _mock_success(monkeypatch)
    _claim_and_process(runner)
    assert task_db.get_task(tid)['status'] == 'succeeded'
    assert doc_node(wf, 'n1')['task']['status'] == 'succeeded'
    assert store.workflow(wf['id'])['revision'] == saved['revision'] + 1
    assert env['calls'] == []


def test_worker_writeback_failure_only_logs(env, runner, monkeypatch, caplog):
    wf = env['workflow']
    tid = make_task(wf['id'])
    saved = save_nodes(wf, node('n1', tid))
    _mock_success(monkeypatch)

    def broken(*_args, **_kwargs):
        raise RuntimeError('write-back exploded')
    monkeypatch.setattr(canvas_writeback, 'apply_task_result', broken)
    with caplog.at_level(logging.ERROR):
        _claim_and_process(runner)
    task = task_db.get_task(tid)
    assert task['status'] == 'succeeded' and task['attempt_count'] == 1 and task['next_run_at'] is None
    assert task_db.claim_next_task(runner.worker_id, task_types=('image', 'layer')) is None  # never retried
    assert 'canvas_writeback_failed' in caplog.text
    assert store.workflow(wf['id'])['revision'] == saved['revision']


def test_worker_unimportable_output_keeps_task_succeeded(env, runner, monkeypatch):
    wf = env['workflow']
    tid = make_task(wf['id'])
    saved = save_nodes(wf, node('n1', tid))
    for path in (Path(storage.OUTPUT_DIR) / 'image' / str(tid)).iterdir():
        path.unlink()
    _mock_success(monkeypatch)
    _claim_and_process(runner)
    assert task_db.get_task(tid)['status'] == 'succeeded'
    assert store.workflow(wf['id'])['revision'] == saved['revision']


# 6. old canvases --------------------------------------------------------------

def test_old_canvas_is_completed_by_sync_and_deleted_node_stays_deleted(env):
    wf = env['workflow']
    done, gone = make_task(wf['id']), make_task(wf['id'], colors=('green',))
    save_nodes(wf, node('n1', done), node('n2'))
    task_db.update_task(done, status='succeeded')
    task_db.update_task(gone, status='succeeded')  # its node was deleted before completion
    client = application.app.test_client()
    result = client.post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [done, gone]}).json
    assert set(result['nodes']) == {'n1'} and result['nodes']['n1']['task']['status'] == 'succeeded'
    assert [n['id'] for n in store.workflow(wf['id'])['document']['nodes']] == ['n1', 'n2']
    assert canvas_writeback.apply_task_result(gone) == {}
    names = {r['name'] for r in task_db.get_db().execute('SELECT name FROM canvas_assets')}
    assert names == {f'铁门_{done}.png', f'铁门_{done}_2.png'}  # nothing imported for the deleted node


def test_table_is_migrated_on_existing_database(env):
    db = task_db.get_db()
    db.execute('DROP TABLE canvas_writebacks')
    db.commit()
    store.init_canvas_db()
    columns = [r['name'] for r in db.execute('PRAGMA table_info(canvas_writebacks)')]
    assert columns == ['workflow_id', 'revision', 'node_id', 'task_id', 'created_at']


def test_task_results_endpoint_unchanged(env):
    wf = env['workflow']
    tid = make_task(wf['id'], status='succeeded')
    client = application.app.test_client()
    url = f"/api/canvas/workflows/{wf['id']}/task-results"
    first = client.post(url, json={'task_id': tid})
    assert first.status_code == 200 and client.post(url, json={'task_id': tid}).json['assets'] == first.json['assets']
    running = make_task(wf['id'])
    assert client.post(url, json={'task_id': running}).status_code == 409
    assert store.workflow(wf['id'])['revision'] == 1


# F10/F11 downstream (coordinator follow-up) ---------------------------------

def _downstream_setup(env, **down_extra):
    """n1 (generating, old result) -> n2 (image with a result, references n1's old asset)."""
    wf = env['workflow']
    first = make_task(wf['id'], colors=('red',))
    save_nodes(wf, node('n1', first), node('n2'))
    task_db.update_task(first, status='succeeded')
    canvas_writeback.apply_task_result(first)
    n1 = doc_node(wf, 'n1')
    old_id = n1['asset']['id']
    # n2 already has its own result so it can become stale
    own = make_task(wf['id'], colors=('white',))
    save_nodes(wf, n1, node('n2', own))
    task_db.update_task(own, status='succeeded')
    canvas_writeback.apply_task_result(own)
    n2 = doc_node(wf, 'n2')
    n2.update({'text': '用 @图片1 做背景', 'referenceOrder': [old_id], 'referenceMentions': {'@图片1': old_id}, **down_extra})
    second = make_task(wf['id'], colors=('green',))
    current = store.workflow(wf['id'])
    doc = {**current['document'], 'nodes': [{**n1, 'task': {'id': second, 'status': 'processing', 'error': None}}, n2],
           'edges': [{'id': 'e1', 'source': 'n1', 'target': 'n2'}]}
    base = store.update_workflow(wf['id'], current['title'], doc, current['revision'])
    task_db.update_task(second, status='succeeded')
    return wf, second, old_id, base


def test_writeback_marks_downstream_stale_and_replaces_reference_ids(env):
    wf, second, old_id, base = _downstream_setup(env)
    assert canvas_writeback.apply_task_result(second) == {wf['id']: base['revision'] + 1}
    new_id = doc_node(wf, 'n1')['asset']['id']
    assert new_id != old_id
    n2 = doc_node(wf, 'n2')
    assert n2['upstreamStale'] is True
    assert n2['referenceOrder'] == [new_id] and n2['referenceMentions'] == {'@图片1': new_id}
    assert n2['text'] == '用 @图片1 做背景' and n2['task']['status'] == 'succeeded'
    rows = [r for r in writeback_rows(wf) if r['revision'] == base['revision'] + 1]
    assert sorted(r['node_id'] for r in rows) == ['n1', 'n2'] and {r['task_id'] for r in rows} == {second}
    # idempotent: nothing more to do
    assert canvas_writeback.apply_task_result(second) == {}
    sync = application.app.test_client().post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [second]}).json
    assert set(sync['nodes']) == {'n1'} and sync['revision'] == base['revision'] + 1


def test_downstream_without_result_or_failure_is_untouched(env):
    wf = env['workflow']
    tid = make_task(wf['id'])
    current = store.workflow(wf['id'])
    doc = {**current['document'], 'nodes': [node('n1', tid), node('n2'), node('n3', type='video')],
           'edges': [{'id': 'e1', 'source': 'n1', 'target': 'n2'}, {'id': 'e2', 'source': 'n1', 'target': 'n3'}]}
    store.update_workflow(wf['id'], current['title'], doc, current['revision'])
    task_db.update_task(tid, status='succeeded')
    canvas_writeback.apply_task_result(tid)
    # downstream nodes without a result never become stale (client rule: node.asset required)
    assert 'upstreamStale' not in doc_node(wf, 'n2') and 'upstreamStale' not in doc_node(wf, 'n3')
    assert {r['node_id'] for r in writeback_rows(wf)} == {'n1'}


def test_failed_writeback_does_not_touch_downstream(env):
    wf, second, old_id, base = _downstream_setup(env)
    task_db.update_task(second, status='failed', error='x')
    canvas_writeback.apply_task_result(second)
    n2 = doc_node(wf, 'n2')
    assert 'upstreamStale' not in n2 and n2['referenceOrder'] == [old_id]
    assert {r['node_id'] for r in writeback_rows(wf) if r['revision'] == base['revision'] + 1} == {'n1'}


def test_ambiguous_reference_is_not_replaced_but_still_stale(env):
    wf, second, old_id, base = _downstream_setup(env)
    # n2 also holds the old asset directly as a reference asset: the old id stays an input
    current = store.workflow(wf['id'])
    n1 = doc_node(wf, 'n1')
    n2 = doc_node(wf, 'n2')
    n2['referenceAssets'] = [n1['asset']]
    base = store.update_workflow(wf['id'], current['title'], {**current['document'], 'nodes': [n1, n2]}, current['revision'])
    canvas_writeback.apply_task_result(second)
    n2 = doc_node(wf, 'n2')
    assert n2['upstreamStale'] is True and n2['referenceOrder'] == [old_id] and n2['referenceMentions'] == {'@图片1': old_id}


def test_merge_rederives_downstream_on_client_document(env):
    wf, second, old_id, base = _downstream_setup(env)
    canvas_writeback.apply_task_result(second)
    new_id = doc_node(wf, 'n1')['asset']['id']
    stale = base['document']
    for item in stale['nodes']:
        if item['id'] == 'n2':
            item['text'] = '窗口A改的 @图片1'
    response = put(application.app.test_client(), wf, stale, base['revision'])
    assert response.status_code == 200 and response.json['merged'] is True
    nodes = {n['id']: n for n in response.json['document']['nodes']}
    assert nodes['n1']['asset']['id'] == new_id
    assert nodes['n2']['text'] == '窗口A改的 @图片1' and nodes['n2']['upstreamStale'] is True
    assert nodes['n2']['referenceOrder'] == [new_id] and nodes['n2']['referenceMentions'] == {'@图片1': new_id}


def test_merge_keeps_client_downstream_decisions(env):
    wf, second, old_id, base = _downstream_setup(env)
    canvas_writeback.apply_task_result(second)
    server = store.workflow(wf['id'])['document']
    # window A already merged the write-back locally (task-sync) and the user dismissed the marker
    stale = {**server, 'nodes': [n if n['id'] != 'n2' else {k: v for k, v in n.items() if k != 'upstreamStale'} for n in server['nodes']]}
    response = put(application.app.test_client(), wf, stale, base['revision'])
    assert response.json['merged'] is True
    assert 'upstreamStale' not in {n['id']: n for n in response.json['document']['nodes']}['n2']


def test_merge_does_not_touch_disconnected_downstream(env):
    # window A deleted the edge: downstream keeps the client's state, old ids are not rewritten
    wf, second, old_id, base = _downstream_setup(env)
    canvas_writeback.apply_task_result(second)
    stale = {**base['document'], 'edges': []}
    response = put(application.app.test_client(), wf, stale, base['revision'])
    assert response.json['merged'] is True
    n2 = {n['id']: n for n in response.json['document']['nodes']}['n2']
    assert 'upstreamStale' not in n2 and n2['referenceOrder'] == [old_id]
