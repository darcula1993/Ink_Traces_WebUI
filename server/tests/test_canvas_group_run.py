"""GROUP-RUN-20261115 A2: group run tables, state machine and API.

Submission and estimation are mocks injected through canvas_group_run; the
"worker" is simulated by completing tasks, running the real canvas write-back
and calling on_task_terminal.  No provider is ever reached.
"""
import io
import json
import sqlite3
from pathlib import Path

from PIL import Image
import pytest

import app as application
import canvas_group_run as group_run
import canvas_store as store
import canvas_writeback
import storage
import tasks as task_db


def png(color):
    data = io.BytesIO()
    Image.new('RGB', (2, 2), color).save(data, format='PNG')
    return data.getvalue()


class Env:
    def __init__(self, workflow_id):
        self.wid = workflow_id
        self.calls = []
        self.costs = {}          # node_id -> usd at preview
        self.submit_costs = {}   # node_id -> usd (or None = unknown) at submit
        self.reject = {}
        self.explode = set()
        self.client = application.app.test_client()
        self.url = '/api/canvas/workflows/' + workflow_id

    # --- mocks
    def submitter(self, wid, node_id, ctx):
        self.calls.append(node_id)
        if node_id in self.reject:
            raise group_run.SubmitRejected(self.reject[node_id])
        if node_id in self.explode:
            raise RuntimeError('connection reset after send')
        tid = task_db.create_task('image', 'p', {'canvas_workflow_id': wid, 'canvas_node_id': node_id,
                                                 'group_run_id': ctx['run_id']})
        self.edit(lambda doc: self.node(doc, node_id).update(task={'id': tid, 'status': 'pending', 'error': None}))
        return {'task_id': tid}

    def estimator(self, workflow, node, ctx):
        table = self.submit_costs if ctx['phase'] == 'submit' and node['id'] in self.submit_costs else self.costs
        usd = table.get(node['id'], 1.0)
        return {'known': usd is not None, 'usd': usd, 'reason': None if usd is not None else 'audio_no_price'}

    # --- canvas helpers
    def asset(self, color):
        return store.save_asset(self.wid, io.BytesIO(png(color)), color + '.png')

    @staticmethod
    def node(doc, node_id):
        return next(n for n in doc['nodes'] if n['id'] == node_id)

    def edit(self, change):
        wf = store.workflow(self.wid)
        doc = wf['document']
        change(doc)
        store.update_workflow(self.wid, wf['title'], doc, wf['revision'])

    def setup(self, nodes, edges, members=None, extra_nodes=()):
        def change(doc):
            doc['nodes'] = [{'id': n, 'type': 'image', 'title': n, 'x': 0, 'y': 0, 'text': 'p ' + n, 'params': {}} for n in nodes]
            doc['nodes'] += list(extra_nodes)
            doc['edges'] = [{'id': f'e{i}', 'source': s, 'target': t} for i, (s, t) in enumerate(edges)]
            doc['groups'] = [{'id': 'g', 'title': '节点组1', 'nodeIds': list(members or nodes)}]
        self.edit(change)

    def doc(self):
        return store.workflow(self.wid)['document']

    # --- api helpers
    def preview(self, group='g'):
        revision = store.workflow(self.wid)['revision']
        return self.client.post(f'{self.url}/groups/{group}/run-preview', json={'revision': revision})

    def start(self, group='g'):
        preview = self.preview(group)
        assert preview.status_code == 200, preview.json
        p = preview.json['preview']
        response = self.client.post(self.url + '/group-runs', json={'group_id': group, 'revision': p['revision'], 'preview_token': p['preview_token']})
        assert response.status_code == 201, response.json
        return response.json['run']

    def run(self, run_id):
        return self.client.get(f'{self.url}/group-runs/{run_id}').json['run']

    def task_of(self, run_id, node_id):
        return next(n for n in self.run(run_id)['nodes'] if n['node_id'] == node_id)['task_id']

    def finish(self, task_id, status='succeeded', color='red'):
        if status == 'succeeded':
            directory = Path(storage.OUTPUT_DIR) / 'image' / str(task_id)
            directory.mkdir(parents=True)
            path = directory / 'image_0.png'
            path.write_bytes(png(color))
            task_db.register_asset(task_id, 'output_image', str(path), 'image/png')
            task_db.complete_task(task_id, {'images': [str(path)]})
        elif status == 'unknown':
            task_db.fail_task_result_unknown(task_id, '结果未知', 'post_accept_error')
        elif status == 'cancelled':
            task_db.update_task(task_id, status='cancelled')
        else:
            task_db.fail_task(task_id, '失败')
        canvas_writeback.apply_task_result(task_id)
        return group_run.on_task_terminal(task_id)


def statuses(run):
    return {n['node_id']: (n['status'], n['reason']) for n in run['nodes']}


@pytest.fixture
def env(isolated_backend, monkeypatch):
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(isolated_backend / 'canvas_assets'))

    def guard(*args, **kwargs):
        raise AssertionError('provider must not be called')
    for name in ('get', 'post', 'put', 'delete', 'request'):
        if hasattr(application.HTTP, name):
            monkeypatch.setattr(application.HTTP, name, guard)
    project = store.create_project('p')['id']
    e = Env(store.create_workflow(project, 'c')['id'])
    monkeypatch.setattr(group_run, '_submitter', e.submitter)
    monkeypatch.setattr(group_run, '_estimator', e.estimator)
    return e


# ① tables + partial unique index: one active run per group

def test_schema_partial_unique_index(env):
    db = task_db.get_db()
    insert = "INSERT INTO canvas_group_runs (id, workflow_id, group_id, status, base_revision, created_at, updated_at) VALUES (?,?,?,?,1,'t','t')"
    db.execute(insert, ('r1', env.wid, 'g', 'running'))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(insert, ('r2', env.wid, 'g', 'awaiting_confirm'))
    db.execute(insert, ('r3', env.wid, 'g', 'completed'))
    db.execute(insert, ('r4', env.wid, 'g', 'cancelled'))
    db.execute(insert, ('r5', env.wid, 'other', 'running'))
    db.rollback()


def test_second_active_run_rejected(env):
    env.setup(['a', 'b'], [('a', 'b')])
    first = env.start()
    p = env.preview().json['preview']
    response = env.client.post(env.url + '/group-runs', json={'group_id': 'g', 'revision': p['revision'], 'preview_token': p['preview_token']})
    assert response.status_code == 409
    assert response.json['code'] in ('run_active', 'node_busy')
    # node a is busy (submitted); clear that to hit the index itself
    task_db.get_db().execute("UPDATE canvas_group_run_nodes SET status='waiting'")
    task_db.get_db().commit()
    env.edit(lambda doc: env.node(doc, 'a').pop('task'))
    p = env.preview().json['preview']
    response = env.client.post(env.url + '/group-runs', json={'group_id': 'g', 'revision': p['revision'], 'preview_token': p['preview_token']})
    assert response.status_code == 409 and response.json == {**response.json, 'code': 'run_active', 'run_id': first['id']}
    assert env.client.get(env.url + '/group-runs?active=1').json['runs'][0]['id'] == first['id']


# ② rule 1: independent nodes together, downstream waits for all upstream

def test_same_level_parallel_and_topological_order(env):
    env.setup(['a', 'b', 'c', 'd'], [('a', 'c'), ('b', 'c'), ('c', 'd')])
    run = env.start()
    assert env.calls == ['a', 'b']
    assert [(n['node_id'], n['level'], n['upstream']) for n in run['nodes']] == [
        ('a', 0, []), ('b', 0, []), ('c', 1, ['a', 'b']), ('d', 2, ['c'])]
    env.finish(env.task_of(run['id'], 'a'))
    assert env.calls == ['a', 'b']
    env.finish(env.task_of(run['id'], 'b'), color='blue')
    assert env.calls == ['a', 'b', 'c']
    env.finish(env.task_of(run['id'], 'c'), color='green')
    final = env.finish(env.task_of(run['id'], 'd'), color='white')
    assert env.calls == ['a', 'b', 'c', 'd']
    assert final['status'] == 'completed' and final['finished_at'] and final['progress'] == {'done': 4, 'total': 4}
    assert task_db.get_task(env.task_of(run['id'], 'd'))['params']['group_run_id'] == run['id']


# ② rule 2: ordinary failure blocks only its branch

@pytest.mark.parametrize('outcome,reason', [('failed', 'upstream_failed'), ('cancelled', 'upstream_cancelled')])
def test_failure_blocks_only_downstream(env, outcome, reason):
    env.setup(['a', 'b', 'c', 'x', 'y'], [('a', 'b'), ('b', 'c'), ('x', 'y')])
    run = env.start()
    env.finish(env.task_of(run['id'], 'a'), outcome)
    state = statuses(env.run(run['id']))
    assert state['b'] == ('blocked', reason) and state['c'] == ('blocked', 'upstream_blocked')
    env.finish(env.task_of(run['id'], 'x'))
    final = env.finish(env.task_of(run['id'], 'y'), color='blue')
    assert env.calls == ['a', 'x', 'y'] and final['status'] == 'completed'


def test_submit_rejected_blocks_downstream(env):
    env.setup(['a', 'b', 'x'], [('a', 'b')])
    env.reject['a'] = '模型不支持该尺寸'
    run = env.start()
    state = {n['node_id']: n for n in run['nodes']}
    assert state['a']['status'] == 'failed' and state['a']['reason'] == 'submit_rejected' and state['a']['message'] == '模型不支持该尺寸'
    assert state['b']['status'] == 'blocked' and state['x']['status'] == 'submitted'


# ② rule 2: result_unknown stops the whole run, no retry

def test_task_result_unknown_stops_run(env):
    env.setup(['a', 'b', 'x', 'y'], [('a', 'b'), ('x', 'y')])
    run = env.start()
    stopped = env.finish(env.task_of(run['id'], 'a'), 'unknown')
    assert stopped['status'] == 'stopped' and stopped['stop_reason'] == 'result_unknown'
    assert statuses(stopped)['a'] == ('unknown', 'result_unknown') and statuses(stopped)['b'] == ('blocked', 'run_stopped')
    final = env.finish(env.task_of(run['id'], 'x'))   # submitted sibling still finishes and is recorded
    assert statuses(final)['x'] == ('succeeded', None) and statuses(final)['y'] == ('blocked', 'run_stopped')
    assert final['status'] == 'stopped' and final['finished_at'] and env.calls == ['a', 'x']


def test_submit_exception_is_unknown_and_stops_siblings(env):
    env.setup(['a', 'b', 'c'], [])
    env.explode.add('a')
    run = env.start()
    assert env.calls == ['a'] and run['status'] == 'stopped'
    assert statuses(run) == {'a': ('unknown', 'result_unknown'), 'b': ('blocked', 'run_stopped'), 'c': ('blocked', 'run_stopped')}
    assert group_run.advance(run['id'])['status'] == 'stopped' and env.calls == ['a']


# ② rule 3: re-estimate above confirmed / turned unknown pauses until confirm

@pytest.mark.parametrize('later', [2.5, None])
def test_exceeding_estimate_awaits_confirm(env, later):
    env.setup(['a', 'b'], [('a', 'b')])
    env.costs = {'a': 1.0, 'b': 1.0}
    run = env.start()
    assert run['total'] == {'usd': 2.0, 'known_count': 2, 'unknown_count': 0}
    env.submit_costs['b'] = later
    paused = env.finish(env.task_of(run['id'], 'a'))
    assert paused['status'] == 'awaiting_confirm' and env.calls == ['a']
    assert paused['confirm']['nodes'] == [{'node_id': 'b', 'confirmed': {'known': True, 'usd': 1.0, 'reason': None},
                                           'estimate': group_run._normalize_estimate(env.estimator(None, {'id': 'b'}, {'phase': 'submit'}))}]
    assert group_run.advance(run['id'])['status'] == 'awaiting_confirm' and env.calls == ['a']
    stale = env.client.post(f"{env.url}/group-runs/{run['id']}/confirm", json={'confirm_token': 'x'})
    assert stale.status_code == 409 and stale.json['code'] == 'confirm_stale'
    ok = env.client.post(f"{env.url}/group-runs/{run['id']}/confirm", json={'confirm_token': paused['confirm']['confirm_token']})
    assert ok.status_code == 200 and ok.json['run']['status'] == 'running' and env.calls == ['a', 'b']
    assert env.client.post(f"{env.url}/group-runs/{run['id']}/confirm", json={'confirm_token': 'x'}).json['code'] == 'not_awaiting_confirm'


def test_lower_estimate_or_confirmed_unknown_does_not_pause(env):
    env.setup(['a', 'b', 'c'], [('a', 'b'), ('a', 'c')])
    env.costs = {'a': 1.0, 'b': 1.0, 'c': None}
    run = env.start()
    assert run['total'] == {'usd': 2.0, 'known_count': 2, 'unknown_count': 1}
    env.submit_costs = {'b': 0.5}
    after = env.finish(env.task_of(run['id'], 'a'))
    assert after['status'] == 'running' and env.calls == ['a', 'b', 'c']


def test_cancel_while_awaiting_confirm(env):
    env.setup(['a', 'b'], [('a', 'b')])
    run = env.start()
    env.submit_costs['b'] = 9.0
    env.finish(env.task_of(run['id'], 'a'))
    cancelled = env.client.post(f"{env.url}/group-runs/{run['id']}/cancel").json['run']
    assert cancelled['status'] == 'cancelled' and statuses(cancelled)['b'] == ('cancelled', 'user_cancelled')
    assert cancelled['finished_at'] and env.calls == ['a']


# ② rule 4: nodes with results are rerun, listed in the preview

def test_nodes_with_results_are_rerun(env):
    old = env.asset('red')
    env.setup(['a', 'b'], [('a', 'b')])
    env.edit(lambda doc: env.node(doc, 'a').update(asset=old, candidates=[old], selectedCandidateId=old['id']))
    preview = env.preview().json['preview']
    assert [(n['node_id'], n['has_result']) for n in preview['nodes']] == [('a', True), ('b', False)]
    run = env.start()
    assert env.calls == ['a']
    env.finish(env.task_of(run['id'], 'a'), color='blue')
    assert env.calls == ['a', 'b']
    a = env.node(env.doc(), 'a')
    assert len(a['candidates']) == 2 and a['asset']['id'] != old['id']   # old result kept as candidate


# ② rule 5: cancel stops only unsubmitted nodes

def test_cancel_only_unsubmitted(env):
    env.setup(['a', 'b', 'c'], [('a', 'b')])
    run = env.start()
    cancelled = env.client.post(f"{env.url}/group-runs/{run['id']}/cancel").json['run']
    assert cancelled['status'] == 'cancelled' and not cancelled['finished_at']
    assert statuses(cancelled) == {'a': ('submitted', None), 'c': ('submitted', None), 'b': ('cancelled', 'user_cancelled')}
    assert env.client.post(f"{env.url}/group-runs/{run['id']}/cancel").status_code == 200   # idempotent
    env.finish(env.task_of(run['id'], 'a'))
    final = env.finish(env.task_of(run['id'], 'c'), color='blue')
    assert env.calls == ['a', 'c'] and final['status'] == 'cancelled' and final['finished_at']
    assert statuses(final)['a'] == ('succeeded', None)
    assert env.node(env.doc(), 'a')['task']['status'] == 'succeeded'   # written back normally
    assert env.client.get(env.url + '/group-runs?active=1').json['runs'] == []


def test_cancel_finished_run_rejected(env):
    env.setup(['a'], [])
    run = env.start()
    env.finish(env.task_of(run['id'], 'a'))
    response = env.client.post(f"{env.url}/group-runs/{run['id']}/cancel")
    assert response.status_code == 409 and response.json['code'] == 'run_finished'


# ② rule 6: manual edits block the branch

@pytest.mark.parametrize('edit,reason', [
    (lambda env, doc: env.node(doc, 'b').update(text='改过的提示词'), 'node_modified'),
    (lambda env, doc: env.node(doc, 'b')['params'].update(ratio='16:9'), 'node_modified'),
    (lambda env, doc: env.node(doc, 'a').update(text='上游改了'), 'upstream_modified'),
    (lambda env, doc: doc['groups'][0]['nodeIds'].remove('b'), 'node_removed'),
])
def test_manual_edit_blocks_branch(env, edit, reason):
    env.setup(['a', 'b', 'c', 'x', 'y'], [('a', 'b'), ('b', 'c'), ('x', 'y')])
    run = env.start()
    env.edit(lambda doc: edit(env, doc))
    after = env.finish(env.task_of(run['id'], 'a'))
    assert statuses(after)['b'] == ('blocked', reason) and statuses(after)['c'] == ('blocked', 'upstream_blocked')
    env.finish(env.task_of(run['id'], 'x'), color='blue')
    assert env.calls == ['a', 'x', 'y']


def test_switching_upstream_selection_blocks(env):
    old = env.asset('red')
    env.setup(['a', 'b'], [('a', 'b')])
    env.edit(lambda doc: env.node(doc, 'a').update(asset=old, candidates=[old], selectedCandidateId=old['id']))
    run = env.start()
    task_id = env.task_of(run['id'], 'a')
    # complete without advancing, then the user picks the old candidate before the hook runs
    directory = Path(storage.OUTPUT_DIR) / 'image' / str(task_id)
    directory.mkdir(parents=True)
    (directory / 'image_0.png').write_bytes(png('blue'))
    task_db.register_asset(task_id, 'output_image', str(directory / 'image_0.png'), 'image/png')
    task_db.complete_task(task_id, {})
    canvas_writeback.apply_task_result(task_id)
    group_run._apply_task(run['id'], env.wid, 'a', task_db.get_task(task_id))
    env.edit(lambda doc: env.node(doc, 'a').update(asset=old, selectedCandidateId=old['id']))
    after = group_run.advance(run['id'])
    assert statuses(after)['b'] == ('blocked', 'upstream_modified') and env.calls == ['a']


def test_writeback_reference_rename_is_not_an_edit(env):
    old = env.asset('red')
    env.setup(['a', 'b'], [('a', 'b')])
    env.edit(lambda doc: (env.node(doc, 'a').update(asset=old, candidates=[old], selectedCandidateId=old['id']),
                          env.node(doc, 'b').update(referenceOrder=[old['id']], referenceMentions={'@图片1': old['id']})))
    run = env.start()
    env.finish(env.task_of(run['id'], 'a'), color='blue')
    b = env.node(env.doc(), 'b')
    assert b['referenceOrder'] != [old['id']]   # write-back F11 renamed the reference
    assert env.calls == ['a', 'b']


def test_outside_input_change_blocks(env):
    env.setup(['a', 'b'], [('t', 'b'), ('a', 'b')], members=['a', 'b'],
              extra_nodes=[{'id': 't', 'type': 'text', 'title': 't', 'x': 0, 'y': 0, 'text': '原文本'}])
    run = env.start()
    env.edit(lambda doc: env.node(doc, 't').update(text='新文本'))
    after = env.finish(env.task_of(run['id'], 'a'))
    assert statuses(after)['b'] == ('blocked', 'node_modified')


# ③ preview / create / query / cancel / confirm with revision + preview_token

def test_preview_contract_and_revision_checks(env):
    asset = env.asset('red')
    env.setup(['a', 'b'], [('m', 'a'), ('a', 'b')], members=['m', 'a', 'b'],
              extra_nodes=[{'id': 'm', 'type': 'asset', 'title': 'm', 'x': 0, 'y': 0, 'asset': asset,
                            'candidates': [asset], 'selectedCandidateId': asset['id']}])
    env.costs = {'a': 0.25, 'b': None}
    response = env.preview()
    assert response.status_code == 200
    p = response.json['preview']
    assert p['skipped'] == [{'node_id': 'm', 'type': 'asset', 'reason': 'not_generation'}]
    assert p['total'] == {'usd': 0.25, 'known_count': 1, 'unknown_count': 1, 'node_count': 2}
    assert p['nodes'][1] == {'node_id': 'b', 'type': 'image', 'title': 'b', 'level': 1, 'upstream': ['a'],
                             'has_result': False, 'estimate': {'known': False, 'usd': None, 'reason': 'audio_no_price'}}
    stale = env.client.post(env.url + '/groups/g/run-preview', json={'revision': p['revision'] - 1})
    assert stale.status_code == 409 and stale.json['code'] == 'revision_mismatch' and stale.json['revision'] == p['revision']
    assert env.client.post(env.url + '/groups/g/run-preview', json={'revision': 'x'}).json['code'] == 'invalid_request'
    create = lambda **kw: env.client.post(env.url + '/group-runs', json={'group_id': 'g', 'revision': p['revision'], 'preview_token': p['preview_token'], **kw})
    assert create(revision=p['revision'] + 5).json['code'] == 'revision_mismatch'
    env.costs['a'] = 0.5   # estimate changed after the user saw it
    response = create()
    assert response.status_code == 409 and response.json['code'] == 'preview_stale'
    assert response.json['preview']['total']['usd'] == 0.5 and env.calls == []
    assert create(preview_token='').json['code'] == 'invalid_request'
    env.costs['a'] = 0.25
    assert create().status_code == 201 and env.calls == ['a']
    runs = env.client.get(env.url + '/group-runs?group_id=g').json['runs']
    assert len(runs) == 1 and runs[0]['base_revision'] == p['revision']


def test_not_found_and_unavailable(env, monkeypatch):
    env.setup(['a'], [])
    assert env.preview('nope').status_code == 404 and env.preview('nope').json['code'] == 'group_not_found'
    assert env.client.get(env.url + '/group-runs/missing').json['code'] == 'run_not_found'
    run = env.start()
    other = store.create_workflow(store.create_project('q')['id'], 'd')['id']
    assert env.client.get(f"/api/canvas/workflows/{other}/group-runs/{run['id']}").status_code == 404
    assert env.client.get('/api/canvas/workflows/zzz/group-runs').status_code == 404
    monkeypatch.setattr(group_run, '_submitter', None)
    env.setup(['b'], [])
    p = env.preview().json['preview']
    response = env.client.post(env.url + '/group-runs', json={'group_id': 'g', 'revision': p['revision'], 'preview_token': p['preview_token']})
    assert response.status_code == 503 and response.json['code'] == 'submit_unavailable'


def test_default_estimator_is_unknown_not_zero(env, monkeypatch):
    monkeypatch.setattr(group_run, '_estimator', group_run._default_estimator)
    env.setup(['a'], [])
    p = env.preview().json['preview']
    assert p['total'] == {'usd': 0.0, 'known_count': 0, 'unknown_count': 1, 'node_count': 1}
    assert p['nodes'][0]['estimate']['known'] is False


def test_node_busy_rejected(env):
    env.setup(['a'], [])
    tid = task_db.create_task('image', 'p', {'canvas_workflow_id': env.wid})
    env.edit(lambda doc: env.node(doc, 'a').update(task={'id': tid, 'status': 'processing', 'error': None}))
    p = env.preview().json['preview']
    response = env.client.post(env.url + '/group-runs', json={'group_id': 'g', 'revision': p['revision'], 'preview_token': p['preview_token']})
    assert response.status_code == 409 and response.json['code'] == 'node_busy' and response.json['node_ids'] == ['a']


# ④ cycles and missing outside upstream results

def test_cycle_rejected(env):
    # Saves already reject cycles; the run planner still refuses one in legacy/raw documents.
    env.setup(['a', 'b', 'c'], [('a', 'b'), ('c', 'a')])
    doc = env.doc()
    doc['edges'].append({'id': 'back', 'source': 'b', 'target': 'a'})
    db = task_db.get_db()
    db.execute('UPDATE canvas_workflows SET document=? WHERE id=?', (json.dumps(doc), env.wid))
    db.commit()
    response = env.preview()
    assert response.status_code == 400 and response.json['code'] == 'cycle' and set(response.json['node_ids']) == {'a', 'b'}


def test_outside_upstream_without_result_rejected(env):
    env.setup(['a', 'o'], [('o', 'a')], members=['a'])
    response = env.preview()
    assert response.status_code == 400 and response.json['code'] == 'upstream_missing'
    assert response.json['node_id'] == 'a' and response.json['source_id'] == 'o' and '还没有结果' in response.json['error']
    done = env.asset('red')
    env.edit(lambda doc: env.node(doc, 'o').update(asset=done, candidates=[done], selectedCandidateId=done['id']))
    run = env.start()
    assert env.calls == ['a'] and [n['upstream'] for n in run['nodes']] == [[]]   # outside node is not chained


def test_group_without_generation_nodes(env):
    env.setup([], [], members=['t'], extra_nodes=[{'id': 't', 'type': 'text', 'title': 't', 'x': 0, 'y': 0, 'text': 'x'}])
    assert env.preview().json['code'] == 'group_empty'


def test_active_run_for_node(env):
    env.setup(['a', 'b'], [('a', 'b')])
    run = env.start()
    assert group_run.active_run_for_node(env.wid, 'b') == run['id']
    assert group_run.active_run_for_node(env.wid, 'zz') is None
    env.client.post(f"{env.url}/group-runs/{run['id']}/cancel")
    assert group_run.active_run_for_node(env.wid, 'b') is None
