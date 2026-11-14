"""WRITEBACK-RACE-20261114: worker write-back and task-sync importing the same task concurrently.

Every concurrent caller must succeed (no 500), the canvas revision must rise
exactly once and the outcome must equal a single call.  No provider is reached.
"""
import threading

import pytest

import app as application
import canvas_store as store
import canvas_writeback
import tasks as task_db
from tests.test_canvas_writeback import doc_node, env, make_task, node, save_nodes, writeback_rows  # noqa: F401

THREADS = 8
ROUNDS = 10


def _run_parallel(count, target):
    barrier = threading.Barrier(count)
    results, errors = [None] * count, []

    def run(index):
        try:
            barrier.wait()
            results[index] = target(index)
        except BaseException as error:  # noqa: BLE001 - report every failure
            errors.append(repr(error))
        finally:
            task_db.close_db()  # thread-local connection
    threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    return results, errors


def _prepare(wf):
    tid = make_task(wf['id'])
    saved = save_nodes(wf, node('n1', tid))
    task_db.update_task(tid, status='succeeded')
    return tid, saved['revision']


def _assert_single_outcome(wf, tid, revision):
    assert store.workflow(wf['id'])['revision'] == revision + 1
    result = doc_node(wf, 'n1')
    assert result['task'] == {'id': tid, 'status': 'succeeded', 'error': None}
    assert len(result['candidates']) == 2 and result['selectedCandidateId'] == result['candidates'][0]['id']
    assert task_db.get_db().execute('SELECT COUNT(*) FROM canvas_assets WHERE workflow_id=?', (wf['id'],)).fetchone()[0] == 2
    assert writeback_rows(wf) == [{'revision': revision + 1, 'node_id': 'n1', 'task_id': tid}]
    assert task_db.get_task(tid)['status'] == 'succeeded'


@pytest.mark.parametrize('round_', range(ROUNDS))
def test_concurrent_worker_and_sync_import_once(env, round_):
    wf = env['workflow']
    tid, revision = _prepare(wf)

    def call(index):
        if index % 2:
            return canvas_writeback.sync_tasks(wf['id'], [tid])
        return canvas_writeback.apply_task_result(tid)
    results, errors = _run_parallel(THREADS, call)
    assert errors == []
    for index, result in enumerate(results):
        if index % 2:
            assert result['failed'] == [] and result['revision'] == revision + 1
            assert result['nodes']['n1']['task']['status'] == 'succeeded'
    applied = [r for i, r in enumerate(results) if not i % 2 and r]
    assert all(r == {wf['id']: revision + 1} for r in applied)
    _assert_single_outcome(wf, tid, revision)
    assert env['calls'] == []


@pytest.mark.parametrize('round_', range(ROUNDS))
def test_concurrent_task_sync_requests_never_500(env, round_):
    wf = env['workflow']
    tid, revision = _prepare(wf)

    def call(index):
        with application.app.test_client() as client:
            response = client.post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [tid]})
            return response.status_code, response.get_json()
    results, errors = _run_parallel(THREADS, call)
    assert errors == []
    assert [status for status, _ in results] == [200] * THREADS
    bodies = [body for _, body in results]
    assert all(b['revision'] == revision + 1 and b['failed'] == [] for b in bodies)
    assert all(b['nodes'] == bodies[0]['nodes'] for b in bodies)
    _assert_single_outcome(wf, tid, revision)


# Deterministic conflict: the other writer (worker) commits the same import first,
# then this caller's write hits a SQLite conflict (unique constraint / lock).

def _conflict_after_peer_wrote(monkeypatch, error):
    real = canvas_writeback._apply_to_workflow
    state = {'raised': 0}

    def apply(workflow_id, task):
        if not state['raised']:
            state['raised'] += 1
            peer = threading.Thread(target=lambda: (real(workflow_id, task), task_db.close_db()))
            peer.start()
            peer.join(30)
            raise error
        return real(workflow_id, task)
    monkeypatch.setattr(canvas_writeback, '_apply_to_workflow', apply)
    return state


@pytest.mark.parametrize('error', [
    __import__('sqlite3').IntegrityError('UNIQUE constraint failed: canvas_writebacks.workflow_id, canvas_writebacks.revision, canvas_writebacks.node_id'),
    __import__('sqlite3').IntegrityError('UNIQUE constraint failed: canvas_assets.workflow_id, canvas_assets.sha256'),
    __import__('sqlite3').OperationalError('database is locked'),
])
def test_task_sync_conflict_returns_existing_result(env, monkeypatch, error):
    wf = env['workflow']
    tid, revision = _prepare(wf)
    state = _conflict_after_peer_wrote(monkeypatch, error)
    with application.app.test_client() as client:
        response = client.post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [tid]})
    assert state['raised'] == 1
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body['revision'] == revision + 1 and body['failed'] == []
    assert body['nodes']['n1'] == canvas_writeback.node_fields(doc_node(wf, 'n1'))
    _assert_single_outcome(wf, tid, revision)
    assert env['calls'] == []


def test_task_sync_conflict_without_peer_write_reports_failed(env, monkeypatch):
    import sqlite3
    wf = env['workflow']
    tid, revision = _prepare(wf)

    def locked(workflow_id, task):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(canvas_writeback, '_apply_to_workflow', locked)
    with application.app.test_client() as client:
        response = client.post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [tid]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['failed'] == [tid] and body['revision'] == revision
    assert body['nodes']['n1']['task']['status'] == 'pending'
    assert task_db.get_task(tid)['status'] == 'succeeded'
