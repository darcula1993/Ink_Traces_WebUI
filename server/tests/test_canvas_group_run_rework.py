"""GROUP-RUN-20261115 rework (chunli special QA D1/D2), with the real B3 submitter.

D1: an upstream result that never reached the canvas (write-back raised, or the worker
died between finishing the task and writing it back) must never let downstream submit
with the upstream's OLD result.  D2: retrying a member node's task is a manual generation.
Probes converted from the special-QA probe suite (not in repo).
Providers are mocked (HTTP guard of test_canvas_group_submit.env).
"""
import hashlib
from pathlib import Path

import canvas_group_run as group_run
import canvas_store as store
import canvas_writeback
import storage
import tasks as task_db
import worker
from test_canvas_group_submit import Wire, env, generation, png  # noqa: F401  (fixture)


def count():
    return task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0]


def complete(task_id, color='blue', writeback=True):
    directory = Path(storage.OUTPUT_DIR) / 'image' / str(task_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'image_0.png'
    path.write_bytes(png(color))
    task_db.register_asset(task_id, 'output_image', str(path), 'image/png')
    task_db.complete_task(task_id, {'images': [str(path)]})
    if writeback:
        canvas_writeback.apply_task_result(task_id)
    return hashlib.sha256(png(color)).hexdigest()


def rerun_chain(env):
    """a (with an OLD result) -> b, both in group g."""
    old = env.asset(png('red'), 'old.png')
    a = generation('a', 'image', '画一只猫')
    a.update(asset=old, candidates=[old], selectedCandidateId=old['id'])
    b = generation('b', 'image', '参考 @图片1 画同一只猫')
    env.save([a, b], [('a', 'b')], ['a', 'b'])
    return old


def sent_image_hashes(wire):
    return [f[3] for c in wire.calls for f in c['files'] if f[0] == 'images']


def broken_import(monkeypatch):
    def broken(*args, **kwargs):
        raise store.CanvasError('任务输出文件不可读取', 409)
    monkeypatch.setattr(canvas_writeback, 'import_task_assets', broken)


# D1 (probe test_defect_missed_writeback_*): worker killed after complete_task, before write-back

def test_missed_writeback_patrol_writes_back_and_uses_new_result(env, monkeypatch):
    old = rerun_chain(env)
    wire = Wire(monkeypatch)
    run = env.start()
    a_task = env.entry(run, 'a')['task_id']
    new_hash = complete(a_task, 'blue', writeback=False)
    group_run.sweep()                       # restarted worker's patrol
    run = env.run(run['id'])
    a_node = env.node(env.doc(), 'a')
    assert a_node['asset']['id'] != old['id'] and a_node['task']['status'] == 'succeeded'   # write-back completed
    assert env.entry(run, 'a')['status'] == 'succeeded' and env.entry(run, 'b')['status'] == 'submitted'
    assert sent_image_hashes(wire)[-1] == new_hash      # b got the NEW upstream result, not the old one


# D1 (probe test_defect_writeback_error_then_hook_*): write-back raises, the hook must not advance

def test_writeback_error_hook_does_not_advance_then_blocks(env, monkeypatch):
    rerun_chain(env)
    wire = Wire(monkeypatch)
    run = env.start()
    a_task = env.entry(run, 'a')['task_id']
    complete(a_task, 'blue', writeback=False)
    broken_import(monkeypatch)
    worker.Worker._write_back(a_task)          # logged and swallowed
    worker.Worker._advance_group_run(a_task)
    state = env.run(run['id'])
    assert env.entry(state, 'a')['status'] == 'submitted' and env.entry(state, 'b')['status'] == 'waiting'
    calls, tasks = len(wire.calls), count()
    group_run.sweep()                          # patrol retries the write-back once more, still failing
    state = env.run(run['id'])
    assert env.entry(state, 'a')['status'] == 'succeeded'
    assert (env.entry(state, 'b')['status'], env.entry(state, 'b')['reason']) == ('blocked', 'upstream_no_result')
    assert len(wire.calls) == calls and count() == tasks and state['status'] == 'completed'


def test_writeback_error_then_recovered_by_patrol(env, monkeypatch):
    rerun_chain(env)
    wire = Wire(monkeypatch)
    run = env.start()
    a_task = env.entry(run, 'a')['task_id']
    new_hash = complete(a_task, 'blue', writeback=False)
    with monkeypatch.context() as patch:
        broken_import(patch)
        worker.Worker._write_back(a_task)
        worker.Worker._advance_group_run(a_task)
    assert env.entry(env.run(run['id']), 'b')['status'] == 'waiting'
    group_run.sweep()                          # file readable again: the patrol's write-back lands
    state = env.run(run['id'])
    assert env.entry(state, 'b')['status'] == 'submitted' and sent_image_hashes(wire)[-1] == new_hash


def test_stale_asset_with_matching_task_id_is_not_a_result(env, monkeypatch):
    # node.task already points at the new task (B3 attach) but node.asset is still the old one
    old = rerun_chain(env)
    Wire(monkeypatch)
    run = env.start()
    a_task = env.entry(run, 'a')['task_id']
    complete(a_task, 'blue', writeback=False)
    assert env.node(env.doc(), 'a')['task']['id'] == a_task and env.node(env.doc(), 'a')['asset']['id'] == old['id']
    broken_import(monkeypatch)
    assert group_run._result_asset(env.wid, 'a', a_task) is None


# D2 (probe test_defect_retry_of_member_task_bypasses_guard)

def _old_failed_task(env, node_id):
    old = task_db.create_task('image', 'p', {'provider': 'ark', 'canvas_workflow_id': env.wid, 'canvas_node_id': node_id,
                                             'size': '1024x1024'}, provider='ark')
    task_db.fail_task(old, 'x')
    (Path(storage.OUTPUT_DIR) / 'image' / str(old)).mkdir(parents=True)
    task_db.update_task(old, output_dir=str(Path(storage.OUTPUT_DIR) / 'image' / str(old)))
    return old


def test_retry_of_member_task_is_409(env):
    env.save([generation('a', 'image', 'p'), generation('b', 'image', '@图片1'), generation('z', 'image', 'z')],
             [('a', 'b')], ['a', 'b'])
    old_b, old_z = _old_failed_task(env, 'b'), _old_failed_task(env, 'z')
    legacy = task_db.create_task('image', 'p', {'provider': 'ark', 'size': '1024x1024'}, provider='ark')
    task_db.fail_task(legacy, 'x')
    run = env.start()
    assert env.entry(run, 'b')['status'] == 'waiting'
    tasks = count()
    response = env.client.post(f'/api/tasks/{old_b}/retry', json={})
    assert response.status_code == 409, response.json
    assert response.json['code'] == 'group_run_active' and response.json['run_id'] == run['id']
    assert '运行组内全部' in response.json['error'] and count() == tasks
    # a non-member canvas node and a legacy-tool task are not affected by the guard
    for task_id in (old_z, legacy):
        assert (env.client.post(f'/api/tasks/{task_id}/retry', json={}).json or {}).get('code') != 'group_run_active'
    # after cancelling the run, b (never submitted) can be retried again
    env.client.post(f"{env.url}/group-runs/{run['id']}/cancel", json={})
    assert (env.client.post(f'/api/tasks/{old_b}/retry', json={}).json or {}).get('code') != 'group_run_active'
