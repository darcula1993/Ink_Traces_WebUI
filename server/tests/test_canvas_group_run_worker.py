"""GROUP-RUN-20261115 B4: worker advance hook, restart recovery and manual-generation guard.

Submission and estimation stay mocks (see test_canvas_group_run.Env); the provider
HTTP client is replaced by a guard, so nothing can reach a provider.
"""
import contextvars
import json
import logging
import sys
import types
from pathlib import Path

import pytest

import app as application
import canvas_group_run as group_run
import canvas_project_settings
import canvas_writeback
import storage
import tasks as task_db
import worker
from test_canvas_group_run import env, png, statuses  # noqa: F401  (fixture)


class Killed(BaseException):
    """Simulates the submitting process dying (not caught by ``except Exception``)."""


def complete_without_hook(task_id, color='red'):
    directory = Path(storage.OUTPUT_DIR) / 'image' / str(task_id)
    directory.mkdir(parents=True)
    path = directory / 'image_0.png'
    path.write_bytes(png(color))
    task_db.register_asset(task_id, 'output_image', str(path), 'image/png')
    task_db.complete_task(task_id, {'images': [str(path)]})
    canvas_writeback.apply_task_result(task_id)


def task_count():
    return task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0]


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(worker.application, 'config', {'server': {}})
    return worker.Worker()


# ① write-back then advance downstream; patrol as fallback

def test_worker_process_advances_downstream(env, runner, monkeypatch):
    env.setup(['a', 'b'], [('a', 'b')])
    run = env.start()
    assert env.calls == ['a']

    def execute(task_id):
        directory = Path(storage.OUTPUT_DIR) / 'image' / str(task_id)
        directory.mkdir(parents=True)
        path = directory / 'image_0.png'
        path.write_bytes(png('red'))
        task_db.register_asset(task_id, 'output_image', str(path), 'image/png')
        task_db.complete_task(task_id, {'images': [str(path)]})
        return {'success': True}, 200
    monkeypatch.setattr(application, 'execute_image_task', execute)
    task = task_db.claim_next_task(runner.worker_id, task_types=('image', 'layer'))
    assert task['id'] == env.task_of(run['id'], 'a')
    runner.process(task)
    state = statuses(env.run(run['id']))
    assert state['a'] == ('succeeded', None) and state['b'] == ('submitted', None)
    assert env.calls == ['a', 'b']
    # the result written back is the one the run recorded for a
    a_asset = env.node(env.doc(), 'a')['asset']['id']
    assert task_db.get_db().execute("SELECT result_asset_id FROM canvas_group_run_nodes WHERE node_id='a'").fetchone()[0] == a_asset


def test_worker_hook_ignores_non_terminal_and_unrelated_tasks(env, runner):
    env.setup(['a', 'b'], [('a', 'b')])
    run = env.start()
    runner._advance_group_run(env.task_of(run['id'], 'a'))   # still pending
    other = task_db.create_task('image', 'p', {})
    runner._advance_group_run(other)
    assert env.calls == ['a'] and statuses(env.run(run['id']))['a'] == ('submitted', None)


def test_worker_hook_failure_only_logs(env, runner, monkeypatch, caplog):
    def broken(_task_id):
        raise RuntimeError('hook exploded')
    monkeypatch.setattr(group_run, 'on_task_terminal', broken)
    with caplog.at_level(logging.ERROR):
        runner._advance_group_run(1)
    assert 'group_run_hook_failed' in caplog.text


def test_patrol_catches_missed_hook(env):
    env.setup(['a', 'b', 'c'], [('a', 'b'), ('b', 'c')])
    run = env.start()
    complete_without_hook(env.task_of(run['id'], 'a'))     # worker died before its hook
    assert env.calls == ['a']
    assert group_run.sweep() == [run['id']]
    assert statuses(env.run(run['id']))['b'] == ('submitted', None) and env.calls == ['a', 'b']
    assert group_run.sweep() == [] and env.calls == ['a', 'b']   # idempotent
    complete_without_hook(env.task_of(run['id'], 'b'), 'blue')
    group_run.sweep()
    complete_without_hook(env.task_of(run['id'], 'c'), 'green')
    group_run.sweep()
    final = env.run(run['id'])
    assert final['status'] == 'completed' and final['finished_at'] and env.calls == ['a', 'b', 'c']


def test_patrol_records_missed_unknown_and_stops(env):
    env.setup(['a', 'b', 'x', 'y'], [('a', 'b'), ('x', 'y')])
    run = env.start()
    task_db.fail_task_result_unknown(env.task_of(run['id'], 'a'), '结果未知', 'post_accept_error')
    group_run.sweep()
    state = env.run(run['id'])
    assert state['status'] == 'stopped' and statuses(state)['a'] == ('unknown', 'result_unknown')
    assert statuses(state)['y'] == ('blocked', 'run_stopped') and env.calls == ['a', 'x']


def test_worker_loop_schedules_patrol(runner):
    submitted = []

    class Executor:
        def submit(self, fn):
            submitted.append(fn)
            future = types.SimpleNamespace(done=lambda: True)
            return future
    executor = Executor()
    runner._maybe_sweep_group_runs(executor)          # immediately at start = restart recovery
    runner._maybe_sweep_group_runs(executor)          # not again inside the interval
    assert len(submitted) == 1
    runner.last_group_run_sweep -= runner.group_run_sweep_interval + 1
    runner._maybe_sweep_group_runs(executor)
    assert len(submitted) == 2 and runner.group_run_sweep_interval == 30


def test_sweep_entry_closes_db_and_logs_failure(env, runner, monkeypatch, caplog):
    def broken(grace=None):
        raise RuntimeError('sweep exploded')
    monkeypatch.setattr(group_run, 'sweep', broken)
    with caplog.at_level(logging.ERROR):
        runner._sweep_group_runs()
    assert 'group_run_sweep_failed' in caplog.text


# ② restart / killed worker: submitting without task_id, never resubmitted

def _kill_on(env, node_id, after_create):
    original = env.submitter

    def submitter(wid, nid, ctx):
        if nid != node_id:
            return original(wid, nid, ctx)
        env.calls.append(nid)
        if after_create:
            task_db.create_task('image', 'p', {'canvas_workflow_id': wid, 'canvas_node_id': nid, 'group_run_id': ctx['run_id']})
        raise Killed()
    group_run.set_submitter(submitter)


def test_restart_binds_task_created_before_kill(env, runner):
    env.setup(['a', 'b', 'x'], [('a', 'b')])
    run = env.start()
    _kill_on(env, 'b', after_create=True)
    complete_without_hook(env.task_of(run['id'], 'a'))
    with pytest.raises(Killed):
        group_run.on_task_terminal(env.task_of(run['id'], 'a'))
    assert statuses(env.run(run['id']))['b'] == ('submitting', None)
    tasks_before = task_count()
    worker.Worker()._sweep_group_runs()                  # restarted worker's first patrol
    state = env.run(run['id'])
    b = next(n for n in state['nodes'] if n['node_id'] == 'b')
    assert b['status'] == 'submitted' and b['task_id'] and task_db.get_task(b['task_id'])['params']['group_run_id'] == run['id']
    assert env.calls == ['a', 'x', 'b'] and task_count() == tasks_before   # not resubmitted
    complete_without_hook(b['task_id'], 'blue')
    group_run.on_task_terminal(b['task_id'])
    # killed before node.task was attached: the result never reaches the canvas, so the hook
    # does not record it (D1); the patrol then records it without a result
    assert statuses(env.run(run['id']))['b'] == ('submitted', None)
    group_run.sweep()
    assert statuses(env.run(run['id']))['b'] == ('succeeded', None)
    assert task_db.get_db().execute("SELECT result_asset_id FROM canvas_group_run_nodes WHERE node_id='b'").fetchone()[0] is None


def test_restart_bound_task_already_terminal_is_applied(env):
    env.setup(['a', 'b', 'c'], [('a', 'b'), ('b', 'c')])
    run = env.start()
    _kill_on(env, 'b', after_create=True)
    complete_without_hook(env.task_of(run['id'], 'a'))
    with pytest.raises(Killed):
        group_run.on_task_terminal(env.task_of(run['id'], 'a'))
    orphan = task_db.get_db().execute('SELECT MAX(id) FROM tasks').fetchone()[0]
    task_db.fail_task(orphan, '失败')
    group_run.sweep()
    state = statuses(env.run(run['id']))
    assert state['b'] == ('failed', 'task_failed') and state['c'] == ('blocked', 'upstream_failed')
    assert env.calls == ['a', 'b']


def test_restart_without_task_waits_grace_then_unknown(env):
    env.setup(['a', 'b', 'x', 'y'], [('a', 'b'), ('x', 'y')])
    run = env.start()
    _kill_on(env, 'b', after_create=False)
    complete_without_hook(env.task_of(run['id'], 'a'))
    with pytest.raises(Killed):
        group_run.on_task_terminal(env.task_of(run['id'], 'a'))
    tasks_before = task_count()
    group_run.sweep()                                    # within grace: may still be in flight
    assert statuses(env.run(run['id']))['b'] == ('submitting', None)
    group_run.sweep(grace=0)
    state = env.run(run['id'])
    b = next(n for n in state['nodes'] if n['node_id'] == 'b')
    assert state['status'] == 'stopped' and state['stop_reason'] == 'result_unknown'
    assert (b['status'], b['reason'], b['task_id']) == ('unknown', 'result_unknown', None) and '不会自动重试' in b['message']
    assert statuses(state)['y'] == ('blocked', 'run_stopped')
    group_run.sweep(grace=0)
    assert env.calls == ['a', 'x', 'b'] and task_count() == tasks_before   # never resubmitted


def test_task_of_other_run_or_node_is_not_bound(env):
    env.setup(['a', 'b'], [('a', 'b')])
    run = env.start()
    _kill_on(env, 'b', after_create=False)
    complete_without_hook(env.task_of(run['id'], 'a'))
    with pytest.raises(Killed):
        group_run.on_task_terminal(env.task_of(run['id'], 'a'))
    task_db.create_task('image', 'p', {'canvas_workflow_id': env.wid, 'canvas_node_id': 'b', 'group_run_id': 'other' + run['id']})
    task_db.create_task('image', 'p', {'canvas_workflow_id': env.wid, 'canvas_node_id': 'a', 'group_run_id': run['id']})
    task_db.create_task('image', 'p', {'canvas_workflow_id': env.wid, 'canvas_node_id': 'b'})
    group_run.sweep(grace=0)
    assert statuses(env.run(run['id']))['b'] == ('unknown', 'result_unknown')


def test_submitted_task_missing_is_unknown(env):
    env.setup(['a', 'b'], [])
    run = env.start()
    tid = env.task_of(run['id'], 'a')
    task_db.get_db().execute('DELETE FROM tasks WHERE id=?', (tid,))
    task_db.get_db().commit()
    group_run.sweep()
    state = env.run(run['id'])
    assert statuses(state)['a'] == ('unknown', 'result_unknown') and state['status'] == 'stopped'


# ③ manual generation guard: 409 for members of an active run; the run's own submission passes

ROUTES = {'image': '/api/generate', 'video': '/api/video/generate', 'audio': '/api/audio/generate'}


@pytest.fixture
def submission_ctx(monkeypatch):
    var = contextvars.ContextVar('group_run_submission', default=None)
    module = types.ModuleType('canvas_group_submit')
    module.current_submission = var.get
    monkeypatch.setitem(sys.modules, 'canvas_group_submit', module)
    monkeypatch.setattr(canvas_project_settings, 'validate_generation', lambda data, kind: None)
    return var


def manual(env, node_id, kind='image', multipart=False, **extra):
    body = {'canvas_workflow_id': env.wid, 'canvas_node_id': node_id, 'prompt': 'p',
            'canvas_workflow_revision': 1, **extra}
    if multipart:
        return env.client.post(ROUTES[kind], data={k: str(v) for k, v in body.items()}, content_type='multipart/form-data')
    return env.client.post(ROUTES[kind], json=body)


@pytest.mark.parametrize('kind', ['image', 'video', 'audio'])
@pytest.mark.parametrize('multipart', [False, True])
def test_manual_generation_of_run_member_is_409(env, submission_ctx, kind, multipart):
    env.setup(['a', 'b'], [('a', 'b')])
    run = env.start()
    tasks_before = task_count()
    for node_id in ('a', 'b'):          # submitted and waiting members
        response = manual(env, node_id, kind, multipart)
        assert response.status_code == 409, response.json
        assert response.json['code'] == 'group_run_active' and response.json['run_id'] == run['id']
        assert '运行组内全部' in response.json['error'] and response.json['success'] is False
    # a forged body field never opens the guard
    response = manual(env, 'b', kind, multipart, group_run_id=run['id'])
    assert response.status_code == 409
    assert task_count() == tasks_before


@pytest.mark.parametrize('kind', ['image', 'video', 'audio'])
def test_guard_lets_other_requests_through(env, submission_ctx, kind):
    env.setup(['a', 'b'], [('a', 'b')], extra_nodes=[{'id': 'z', 'type': 'image', 'title': 'z', 'x': 0, 'y': 0, 'text': 'p', 'params': {}}])
    run = env.start()
    assert manual(env, 'z', kind).json.get('code') != 'group_run_active'        # not a member
    assert env.client.post(ROUTES[kind], json={'prompt': 'p'}).json.get('code') != 'group_run_active'   # legacy tool
    env.client.post(f"{env.url}/group-runs/{run['id']}/cancel", json={})
    assert manual(env, 'b', kind).json.get('code') != 'group_run_active'        # cancelled, b not submitted
    finished = env.finish(env.task_of(run['id'], 'a'))
    assert finished['status'] == 'cancelled'
    assert manual(env, 'a', kind).json.get('code') != 'group_run_active'        # finished node


def test_run_own_submission_passes_guard(env, submission_ctx):
    seen = []
    original = env.submitter

    def submitter(wid, node_id, ctx):
        token = submission_ctx.set({'run_id': ctx['run_id'], 'node_id': node_id})
        try:
            seen.append((node_id, manual(env, node_id).json.get('code')))
            # the context names this node only: a sibling member is still refused
            other = 'b' if node_id == 'a' else 'a'
            seen.append((other, manual(env, other).status_code))
        finally:
            submission_ctx.reset(token)
        return original(wid, node_id, ctx)
    group_run.set_submitter(submitter)
    env.setup(['a', 'b'], [('a', 'b')])
    run = env.start()
    assert seen == [('a', None), ('b', 409)]       # own node passes (then fails later checks: no key), sibling 409
    env.finish(env.task_of(run['id'], 'a'))
    assert seen[2] == ('b', None) and seen[3][0] == 'a' and seen[3][1] != 409   # a finished: no longer guarded
    assert statuses(env.run(run['id']))['b'] == ('submitted', None)


def test_wrong_run_context_is_refused(env, submission_ctx):
    env.setup(['a', 'b'], [('a', 'b')])
    run = env.start()
    group_run.set_submitter(env.submitter)
    token = submission_ctx.set({'run_id': 'f' * 32, 'node_id': 'b'})
    try:
        assert manual(env, 'b').status_code == 409
    finally:
        submission_ctx.reset(token)
    token = submission_ctx.set({'run_id': run['id'], 'node_id': 'b'})   # right run, but b not claimed
    try:
        assert manual(env, 'b').status_code == 409
    finally:
        submission_ctx.reset(token)


# fingerprint: the browser re-binding @mentions after an upstream result arrives is not an edit

RECONCILE = Path(__file__).resolve().parents[2] / 'client' / 'src' / 'lib' / 'canvasReferenceOrder.js'


def browser_reconcile(tmp_path, before, after, node_id):
    """Run the real client reconcileReferenceMentions(before, after); return the node's rebinding fields."""
    import shutil
    import subprocess
    if shutil.which('node') is None:
        pytest.skip('node not available')
    script = tmp_path / 'reconcile.mjs'
    script.write_text(
        "import {reconcileReferenceMentions} from %s\n"
        "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{const {before,after}=JSON.parse(raw);"
        "process.stdout.write(JSON.stringify(reconcileReferenceMentions(before,after)))})\n"
        % json.dumps(RECONCILE.as_uri()), encoding='utf-8')
    out = subprocess.run(['node', str(script)], input=json.dumps({'before': before, 'after': after}),
                         capture_output=True, text=True, check=True, timeout=60)
    node = next(n for n in json.loads(out.stdout)['nodes'] if n['id'] == node_id)
    return {key: node[key] for key in ('text', 'referenceMentions', 'referenceOrder') if key in node}


def save_browser_rebind(env, tmp_path, before, node_id):
    fields = browser_reconcile(tmp_path, before, env.doc(), node_id)
    env.edit(lambda doc: env.node(doc, node_id).update(fields))
    return fields


def mention_setup(env, nodes, edges, texts):
    ext = env.asset('white')
    env.setup(nodes, edges, members=nodes,
              extra_nodes=[{'id': 'ext', 'type': 'asset', 'title': 'ext', 'x': 0, 'y': 0, 'asset': ext,
                            'candidates': [ext], 'selectedCandidateId': ext['id']}])
    env.edit(lambda doc: [env.node(doc, n).update(text=t) for n, t in texts.items()])
    return ext


def test_browser_renumbering_of_submitted_upstream_is_not_an_edit(env, tmp_path):
    # b: "@图片1" = ext; a's first result is inserted before ext, the browser renumbers to "@图片2"
    ext = mention_setup(env, ['a', 'b', 'c'], [('a', 'b'), ('ext', 'b'), ('b', 'c')], {'b': '@图片1 的风格'})
    run = env.start()
    before = env.doc()
    env.finish(env.task_of(run['id'], 'a'))
    assert env.calls == ['a', 'b']
    fields = save_browser_rebind(env, tmp_path, before, 'b')
    assert fields['text'] == '@图片2 的风格' and fields['referenceMentions'] == {'@图片2': ext['id']}
    after = env.finish(env.task_of(run['id'], 'b'), color='blue')
    assert statuses(after)['c'] == ('submitted', None) and env.calls == ['a', 'b', 'c']


def test_browser_rebind_before_submission_is_not_an_edit(env, tmp_path):
    # d waits on a and e; a's result arrives first and the browser rebinds d before d is submitted
    mention_setup(env, ['a', 'e', 'd'], [('a', 'd'), ('ext', 'd'), ('e', 'd')], {'d': '@图片1 的风格'})
    run = env.start()
    before = env.doc()
    env.finish(env.task_of(run['id'], 'a'))
    fields = save_browser_rebind(env, tmp_path, before, 'd')
    assert fields['text'] == '@图片2 的风格'          # tokens really were renumbered
    after = env.finish(env.task_of(run['id'], 'e'), color='blue')
    assert statuses(after)['d'] == ('submitted', None) and env.calls == ['a', 'e', 'd']


def test_browser_rebind_on_rerun_upstream_is_not_an_edit(env, tmp_path):
    old = env.asset('red')
    mention_setup(env, ['a', 'e', 'd'], [('a', 'd'), ('ext', 'd'), ('e', 'd')], {'d': '@图片1 和 @图片2'})
    env.edit(lambda doc: env.node(doc, 'a').update(asset=old, candidates=[old], selectedCandidateId=old['id']))
    run = env.start()
    before = env.doc()
    env.finish(env.task_of(run['id'], 'a'), color='green')
    fields = save_browser_rebind(env, tmp_path, before, 'd')
    assert fields['referenceMentions']['@图片1'] != old['id']   # binding followed a's new result
    after = env.finish(env.task_of(run['id'], 'e'), color='blue')
    assert statuses(after)['d'] == ('submitted', None) and env.calls == ['a', 'e', 'd']


@pytest.mark.parametrize('change,reason', [
    (lambda env, ext: env.node_edit('d', text='@图片2 换一个风格'), 'node_modified'),
    (lambda env, ext: env.node_edit('d', params={'ratio': '16:9'}), 'node_modified'),
    # re-point the mention from ext to a's result: same text, different meaning
    (lambda env, ext: env.node_edit('d', referenceMentions={'@图片2': env.node(env.doc(), 'a')['asset']['id']}), 'node_modified'),
])
def test_manual_edit_after_browser_rebind_still_blocks(env, tmp_path, change, reason):
    ext = mention_setup(env, ['a', 'e', 'd'], [('a', 'd'), ('ext', 'd'), ('e', 'd')], {'d': '@图片1 的风格'})
    env.node_edit = lambda node_id, **fields: env.edit(lambda doc: env.node(doc, node_id).update(fields))
    run = env.start()
    before = env.doc()
    env.finish(env.task_of(run['id'], 'a'))
    save_browser_rebind(env, tmp_path, before, 'd')
    change(env, ext)
    after = env.finish(env.task_of(run['id'], 'e'), color='blue')
    assert statuses(after)['d'] == ('blocked', reason) and env.calls == ['a', 'e']


def test_manual_prompt_edit_of_submitted_upstream_blocks_downstream(env, tmp_path):
    mention_setup(env, ['a', 'b', 'c'], [('a', 'b'), ('ext', 'b'), ('b', 'c')], {'b': '@图片1 的风格'})
    run = env.start()
    before = env.doc()
    env.finish(env.task_of(run['id'], 'a'))
    save_browser_rebind(env, tmp_path, before, 'b')
    env.edit(lambda doc: env.node(doc, 'b').update(text='@图片2 的风格，更亮'))
    after = env.finish(env.task_of(run['id'], 'b'), color='blue')
    assert statuses(after)['c'] == ('blocked', 'upstream_modified') and env.calls == ['a', 'b']


# D3 (panam): an unbound token written against an in-group upstream that has no result yet

def _dangling_setup(env):
    env.setup(['a', 'e', 'd'], [('a', 'd'), ('e', 'd')])
    env.edit(lambda doc: env.node(doc, 'd').update(text='参考 @图片1 画同一只猫'))


def test_unbound_mention_of_upstream_without_result_server_bind(env):
    _dangling_setup(env)
    run = env.start()
    env.finish(env.task_of(run['id'], 'a'))
    # write-back (server port / browser) binds the token to a's new result
    new_id = env.node(env.doc(), 'a')['asset']['id']
    env.edit(lambda doc: env.node(doc, 'd').update(referenceMentions={'@图片1': new_id}))
    after = env.finish(env.task_of(run['id'], 'e'), color='blue')
    assert statuses(after)['d'] == ('submitted', None) and env.calls == ['a', 'e', 'd']


def test_unbound_mention_of_upstream_without_result_browser_bind(env, tmp_path):
    _dangling_setup(env)
    run = env.start()
    before = env.doc()
    env.finish(env.task_of(run['id'], 'a'))
    fields = save_browser_rebind(env, tmp_path, before, 'd')
    assert fields['referenceMentions'] == {'@图片1': env.node(env.doc(), 'a')['asset']['id']}
    after = env.finish(env.task_of(run['id'], 'e'), color='blue')
    assert statuses(after)['d'] == ('submitted', None)


def test_unbound_mention_then_manual_prompt_edit_blocks(env):
    _dangling_setup(env)
    run = env.start()
    env.finish(env.task_of(run['id'], 'a'))
    new_id = env.node(env.doc(), 'a')['asset']['id']
    env.edit(lambda doc: env.node(doc, 'd').update(referenceMentions={'@图片1': new_id}, text='参考 @图片1 画一只狗'))
    after = env.finish(env.task_of(run['id'], 'e'), color='blue')
    assert statuses(after)['d'] == ('blocked', 'node_modified') and env.calls == ['a', 'e']

