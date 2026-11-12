"""Billing boundary: dead-worker lease recovery, including a real kill -9 of a Worker process."""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import tasks as task_db
import worker
from billing_support import billing_env, image_task, layer_task, nothing_claimable, poll_task, polled  # noqa: F401

DEAD_PID = 999999999
LOST = 'Worker异常退出，请求可能已发出、结果未知，请先到Provider核实'
SERVER_DIR = Path(__file__).resolve().parents[1]
CHILD = Path(__file__).with_name('billing_worker_child.py')


def _hold(task_id, owner, status='processing', attempts=1):
    task_db.get_db().execute(
        '''UPDATE tasks SET lease_owner = ?, lease_until = ?, status = ?, attempt_count = ?
           WHERE id = ?''',
        (owner, '2999-01-01T00:00:00+00:00', status, attempts, task_id),
    )
    task_db.get_db().commit()


def _dead(owner='dead-worker'):
    task_db.upsert_worker_heartbeat(owner, DEAD_PID, task_db.utcnow())
    return owner


def _assert_lost(task_id):
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert task['error'] == LOST
    assert task['result']['result_unknown'] is True
    assert task['result']['error_type'] == 'worker_lost'
    assert task['completed_at'] is not None and task['next_run_at'] is None
    assert task['lease_owner'] is None
    assert polled(task_id)['result']['result_unknown'] is True
    return task


# ---------------------------------------------------------------- recovery decision matrix

@pytest.mark.parametrize(('kind', 'provider', 'expect'), [
    ('image', 'ark', 'lost'),
    ('image', 'acme', 'pending'),
    ('layer', 'ark', 'lost'),
    ('image', 'cupsy', 'pending'),
    ('image', None, 'pending'),
    ('video', 'ark', 'processing'),
    ('video', 'cupsy', 'processing'),
    ('audio', 'cupsy', 'processing'),
])
def test_dead_worker_recovery_matrix(billing_env, kind, provider, expect):
    owner = _dead()
    if kind == 'layer':
        task_id = layer_task()
    elif kind == 'image':
        task_id = task_db.create_task('image', 'x', {}, provider=provider)
    else:
        task_id = poll_task(kind, provider, external_task_id='ext-1' if provider == 'ark' else None)
    _hold(task_id, owner)

    assert task_db.recover_dead_worker_leases() == 1
    if expect == 'lost':
        _assert_lost(task_id)
        assert nothing_claimable()
        return
    task = task_db.get_task(task_id)
    assert task['status'] == expect
    assert task['lease_owner'] is None
    assert not (task.get('result') or {}).get('result_unknown')


def test_leased_but_never_attempted_task_returns_to_pending(billing_env):
    owner = _dead()
    task_id = task_db.create_task('image', 'x', {}, provider='ark')
    _hold(task_id, owner, status='pending', attempts=0)
    task_db.recover_dead_worker_leases()
    task = task_db.get_task(task_id)
    assert task['status'] == 'pending'
    assert not (task.get('result') or {}).get('result_unknown')


def test_pending_after_one_attempt_is_lost(billing_env):
    owner = _dead()
    task_id = task_db.create_task('image', 'x', {}, provider='ark')
    _hold(task_id, owner, status='pending', attempts=1)
    task_db.recover_dead_worker_leases()
    _assert_lost(task_id)


def test_mixed_dead_worker_holdings(billing_env):
    owner = _dead()
    ark = task_db.create_task('image', 'x', {}, provider='ark')
    cupsy = task_db.create_task('image', 'x', {}, provider='cupsy')
    layer = layer_task()
    cancelling = task_db.create_task('image', 'x', {}, provider='ark')
    done = task_db.create_task('image', 'x', {}, provider='ark')
    for task_id in (ark, cupsy, layer, cancelling, done):
        _hold(task_id, owner)
    assert task_db.request_task_cancel(cancelling) == 'cancel_requested'
    task_db.get_db().execute(
        "UPDATE tasks SET status='succeeded', completed_at=?, result=? WHERE id=?",
        (task_db.utcnow(), '{"local_images": ["/x.png"]}', done))
    task_db.get_db().commit()

    task_db.recover_dead_worker_leases()
    _assert_lost(ark)
    _assert_lost(layer)
    assert task_db.get_task(cupsy)['status'] == 'pending'
    assert task_db.get_task(cancelling)['status'] == 'cancelled'
    assert not (task_db.get_task(cancelling).get('result') or {}).get('result_unknown')
    assert task_db.get_task(done)['status'] == 'succeeded'
    assert task_db.get_task(done)['result'] == {'local_images': ['/x.png']}
    assert task_db.claim_next_task('new', task_types=('image', 'layer'))['id'] == cupsy
    assert task_db.claim_next_task('new', task_types=('image', 'layer')) is None


def test_existing_result_fields_are_preserved_and_invalid_json_replaced(billing_env):
    owner = _dead()
    kept = task_db.create_task('image', 'x', {}, provider='ark')
    task_db.update_task(kept, result={'note': 'kept'})
    broken = task_db.create_task('image', 'x', {}, provider='ark')
    task_db.update_task(broken, result='not json')
    _hold(kept, owner)
    _hold(broken, owner)

    task_db.recover_dead_worker_leases()
    assert _assert_lost(kept)['result']['note'] == 'kept'
    assert _assert_lost(broken)['result'] == {'result_unknown': True, 'error_type': 'worker_lost'}


def test_live_worker_with_fresh_heartbeat_is_untouched(billing_env):
    task_db.upsert_worker_heartbeat('live', os.getpid(), task_db.utcnow())
    task_id = task_db.create_task('image', 'x', {}, provider='ark')
    _hold(task_id, 'live')
    assert task_db.recover_dead_worker_leases() == 0
    task = task_db.get_task(task_id)
    assert task['status'] == 'processing' and task['lease_owner'] == 'live'


def test_live_worker_with_stale_heartbeat_is_treated_as_lost(billing_env):
    task_db.upsert_worker_heartbeat('stale', os.getpid(), task_db.utcnow())
    task_db.get_db().execute(
        "UPDATE worker_heartbeats SET last_seen_at = '2000-01-01T00:00:00+00:00' WHERE worker_id = 'stale'")
    task_db.get_db().commit()
    task_id = task_db.create_task('image', 'x', {}, provider='ark')
    _hold(task_id, 'stale')
    assert task_db.recover_dead_worker_leases() == 1
    _assert_lost(task_id)
    assert task_db.complete_task(task_id, {'local_images': ['/late.png']}) is False


def test_graceful_release_does_not_mark_unknown(billing_env):
    runner = worker.Worker()
    task_db.upsert_worker_heartbeat(runner.worker_id, os.getpid(), task_db.utcnow())
    task_id = task_db.create_task('image', 'x', {}, provider='ark')
    _hold(task_id, runner.worker_id, status='pending', attempts=1)
    task_db.release_worker_leases(runner.worker_id)
    task_db.remove_worker_heartbeat(runner.worker_id)
    assert task_db.recover_dead_worker_leases() == 0
    task = task_db.get_task(task_id)
    assert task['status'] == 'pending'
    assert not (task.get('result') or {}).get('result_unknown')


def test_concurrent_recovery_is_exact(billing_env):
    owner = _dead()
    ids = [task_db.create_task('image', 'x', {}, provider='ark') for _ in range(5)]
    for task_id in ids:
        _hold(task_id, owner)
    task_db.close_db()
    barrier, totals, errors = threading.Barrier(2), [], []

    def recover():
        try:
            barrier.wait(5)
            totals.append(task_db.recover_dead_worker_leases())
        except Exception as error:  # pragma: no cover - surfaced below
            errors.append(error)
        finally:
            task_db.close_db()
    threads = [threading.Thread(target=recover) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert errors == []
    assert sum(totals) == 5
    for task_id in ids:
        _assert_lost(task_id)
    assert nothing_claimable()


# ---------------------------------------------------------------- real process kill -9

def _spawn(tmp_path, mode, calls):
    env = {**os.environ, 'PYTHONPATH': str(SERVER_DIR), 'PYTHONDONTWRITEBYTECODE': '1'}
    env.pop('WORKER_CONCURRENCY', None)
    return subprocess.Popen(
        [sys.executable, str(CHILD), str(task_db.DB_PATH), str(calls), str(tmp_path), mode],
        cwd=str(SERVER_DIR.parent), env=env,
        stdout=subprocess.DEVNULL, stderr=open(tmp_path / f'child-{mode}.log', 'wb'),
    )


def _wait_for_calls(calls, count, proc, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lines = calls.read_text().splitlines() if calls.exists() else []
        if len(lines) >= count:
            return lines
        assert proc.poll() is None, 'worker child exited early'
        time.sleep(0.05)
    raise AssertionError(f'only {lines} recorded')


@pytest.mark.billing_slow
def test_kill_9_mid_request_then_restart_does_not_resubmit(billing_env, tmp_path):
    ark = task_db.create_task('image', 'x', {}, provider='ark')
    layer = layer_task()
    cupsy = task_db.create_task('image', 'x', {}, provider='cupsy')
    task_db.close_db()

    first_calls = tmp_path / 'first.calls'
    child = _spawn(tmp_path, 'block', first_calls)
    try:
        lines = _wait_for_calls(first_calls, 3, child)
    finally:
        os.kill(child.pid, signal.SIGKILL)
        assert child.wait(10) == -signal.SIGKILL
    assert sorted(lines) == sorted([f'image:{ark}', f'layer:{layer}', f'image:{cupsy}'])
    for task_id in (ark, layer, cupsy):
        task = task_db.get_task(task_id)
        assert task['status'] == 'processing' and task['attempt_count'] == 1 and task['lease_owner']
    assert task_db.latest_worker_heartbeat() is not None

    # Restart a real Worker: its startup recovery must run before it claims anything.
    second_calls = tmp_path / 'second.calls'
    restarted = _spawn(tmp_path, 'record', second_calls)
    try:
        assert _wait_for_calls(second_calls, 1, restarted) == [f'image:{cupsy}']
        time.sleep(0.5)
    finally:
        restarted.send_signal(signal.SIGTERM)
        assert restarted.wait(15) == 0
    assert second_calls.read_text().splitlines() == [f'image:{cupsy}']
    task_db.close_db()
    for task_id in (ark, layer):
        _assert_lost(task_id)
    assert task_db.latest_worker_heartbeat() is None
    assert nothing_claimable()


# ---------------------------------------------------------------- G4: helper never overwrites terminal tasks

@pytest.mark.parametrize('status', ['succeeded', 'cancelled', 'failed'])
def test_fail_task_result_unknown_refuses_terminal_tasks(billing_env, status):
    task_id = task_db.create_task('image', 'x', {}, provider='ark')
    original = {'local_images': ['/done.png']}
    task_db.update_task(task_id, status=status, completed_at=task_db.utcnow(), result=original,
                        error='original error')
    assert task_db.fail_task_result_unknown(task_id, 'should not apply', 'worker_exception') is False
    task = task_db.get_task(task_id)
    assert task['status'] == status
    assert task['result'] == original
    assert task['error'] == 'original error'


def test_fail_task_result_unknown_on_missing_task_is_false(billing_env):
    assert task_db.fail_task_result_unknown(987654, 'x', 'worker_exception') is False
    assert task_db.get_task(987654) is None


# ---------------------------------------------------------------- G8: RELIABILITY O1 pinned as known gap

@pytest.mark.xfail(strict=True, reason='RELIABILITY O1: json_set ignores non-object JSON results '
                   '(unreachable via current writers); flip to a normal test once fixed')
@pytest.mark.parametrize('stored', ['[1, 2]', '"text"', 'null'])
def test_recovery_marks_non_object_json_result(billing_env, stored):
    owner = _dead()
    task_id = task_db.create_task('image', 'x', {}, provider='ark')
    task_db.get_db().execute('UPDATE tasks SET result = ? WHERE id = ?', (stored, task_id))
    task_db.get_db().commit()
    _hold(task_id, owner)
    task_db.recover_dead_worker_leases()
    task = task_db.get_task(task_id)
    assert task['status'] == 'failed'
    assert isinstance(task['result'], dict) and task['result'].get('result_unknown') is True
