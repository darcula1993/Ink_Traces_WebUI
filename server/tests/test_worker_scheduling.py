from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

import worker


@pytest.fixture
def scheduler(monkeypatch):
    monkeypatch.setattr(worker.application, 'config', {'server': {}})
    monkeypatch.delenv('WORKER_CONCURRENCY', raising=False)
    return worker.Worker()


@pytest.mark.parametrize(('config', 'env', 'expected'), [
    ({}, None, (3, 2, 1)),
    ({'worker_concurrency': 4}, None, (4, 2, 1)),
    ({'worker_concurrency': 4, 'generation_concurrency': 2,
      'polling_concurrency': 3, 'asset_concurrency': 2}, None, (2, 3, 2)),
    ({'generation_concurrency': 2}, '1', (1, 2, 1)),
    ({'generation_concurrency': 0, 'polling_concurrency': 0,
      'asset_concurrency': -1}, None, (1, 1, 1)),
])
def test_pool_configuration(scheduler, monkeypatch, config, env, expected):
    monkeypatch.setattr(worker.application, 'config', {'server': config})
    if env is not None:
        monkeypatch.setenv('WORKER_CONCURRENCY', env)
    configured = worker.Worker()
    assert (configured.generation_concurrency, configured.polling_concurrency,
            configured.asset_concurrency) == expected
    assert configured.concurrency == configured.generation_concurrency


def test_blocked_generation_does_not_starve_polling_or_assets(scheduler, monkeypatch):
    release = Event()
    started = {kind: Event() for kind in ('image', 'layer', 'video', 'audio', 'asset')}
    queues = {
        ('image', 'layer'): [
            {'id': 1, 'type': 'image', 'provider': 'cupsy'},
            {'id': 2, 'type': 'layer'},
            {'id': 3, 'type': 'image'},
        ],
        ('video', 'audio'): [{'id': 4, 'type': 'video'}, {'id': 5, 'type': 'audio'}],
    }
    assets = [{'id': 6, 'type': 'asset'}, {'id': 7, 'type': 'asset'}]
    claims = []

    def claim(worker_id, lease_seconds=900, task_types=None):
        assert worker_id == scheduler.worker_id
        assert lease_seconds == scheduler.lease_seconds
        claims.append(task_types)
        return queues[task_types].pop(0) if queues[task_types] else None

    def claim_asset(worker_id, lease_seconds):
        assert worker_id == scheduler.worker_id
        assert lease_seconds == min(scheduler.lease_seconds, 300)
        return assets.pop(0) if assets else None

    def process(task):
        started[task['type']].set()
        if task['type'] in ('image', 'layer', 'asset'):
            assert release.wait(5)

    monkeypatch.setattr(worker.task_db, 'claim_next_task', claim)
    monkeypatch.setattr(worker.task_db, 'claim_next_provider_asset', claim_asset)
    monkeypatch.setattr(scheduler, 'process', process)
    monkeypatch.setattr(scheduler, 'process_provider_asset', process)
    with ExitStack() as stack:
        generation = stack.enter_context(ThreadPoolExecutor(max_workers=2))
        polling = stack.enter_context(ThreadPoolExecutor(max_workers=2))
        asset_pool = stack.enter_context(ThreadPoolExecutor(max_workers=1))
        generation_futures, polling_futures, asset_futures = set(), set(), set()
        try:
            scheduler._fill_pool(generation, generation_futures, 2, ('image', 'layer'))
            assert started['image'].wait(2)
            assert started['layer'].wait(2)
            scheduler._fill_pool(polling, polling_futures, 2, ('video', 'audio'))
            scheduler._fill_pool(asset_pool, asset_futures, 1, None)
            assert started['video'].wait(2)
            assert started['audio'].wait(2)
            assert started['asset'].wait(2)
            assert not any(future.done() for future in generation_futures)
            for future in polling_futures:
                future.result(timeout=2)
            scheduler._fill_pool(generation, generation_futures, 2, ('image', 'layer'))
            scheduler._fill_pool(asset_pool, asset_futures, 1, None)
            assert len(queues[('image', 'layer')]) == 1
            assert len(assets) == 1
            assert claims == [('image', 'layer')] * 2 + [('video', 'audio')] * 2
            scheduler.request_stop()
            scheduler._fill_pool(polling, set(), 2, ('video', 'audio'))
            assert len(claims) == 4
        finally:
            release.set()
        for future in generation_futures | asset_futures:
            future.result(timeout=2)


def test_cleanup_is_background_single_flight_and_interval_limited(scheduler, monkeypatch):
    entered, release = Event(), Event()
    calls = []
    closed = []
    clock = SimpleNamespace(now=10000)
    monkeypatch.setattr(worker, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    original_close = worker.task_db.close_db

    def scheduled():
        worker.task_db.get_db()
        calls.append(('scheduled', get_ident()))
        entered.set()
        assert release.wait(5)

    def close():
        closed.append(get_ident())
        original_close()

    monkeypatch.setattr(worker.storage, 'cleanup_workspace_assets_all', scheduled)
    monkeypatch.setattr(worker.storage, 'cleanup_expired_assets', lambda: calls.append('expired') or 0)
    monkeypatch.setattr(worker.storage, 'cleanup_orphans',
                        lambda grace: calls.append(('orphans', grace)) or {'files': 0, 'directories': 0})
    monkeypatch.setattr(worker.task_db, 'checkpoint', lambda: calls.append('checkpoint'))
    monkeypatch.setattr(worker.task_db, 'close_db', close)
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            scheduler._maybe_cleanup(executor)
            assert entered.wait(2)
            first = scheduler.cleanup_future
            assert not first.done()
            clock.now += scheduler.cleanup_interval
            scheduler._maybe_cleanup(executor)
            assert scheduler.cleanup_future is first
            assert len(calls) == 1
        finally:
            release.set()
        first.result(timeout=2)
        assert calls == [('scheduled', closed[0]), 'expired',
                         ('orphans', scheduler.orphan_grace_seconds), 'checkpoint']
        assert closed[0] != get_ident()
        assert executor.submit(lambda: getattr(worker.task_db._local, 'conn', None)).result() is None
        scheduler._maybe_cleanup(executor)
        second = scheduler.cleanup_future
        assert second is not first
        second.result(timeout=2)
        scheduler._maybe_cleanup(executor)
        assert scheduler.cleanup_future is second
        assert len(closed) == 2


@pytest.mark.parametrize('failure', ['scheduled', 'expired', 'orphans', 'checkpoint'])
def test_cleanup_failure_closes_connection(scheduler, monkeypatch, caplog, failure):
    calls = []

    def step(name, result=None):
        def run(*args):
            calls.append(name)
            worker.task_db.get_db()
            if name == failure:
                raise RuntimeError('cleanup test failure')
            return result
        return run

    monkeypatch.setattr(worker.storage, 'cleanup_workspace_assets_all', step('scheduled'))
    monkeypatch.setattr(worker.storage, 'cleanup_expired_assets', step('expired', 0))
    monkeypatch.setattr(worker.storage, 'cleanup_orphans', step('orphans', {'files': 0, 'directories': 0}))
    monkeypatch.setattr(worker.task_db, 'checkpoint', step('checkpoint'))
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(scheduler._cleanup).result(timeout=2)
        assert executor.submit(lambda: getattr(worker.task_db._local, 'conn', None)).result() is None
    assert calls[-1] == failure
    assert 'storage_cleanup_failed' in caplog.text


def test_scheduler_drains_all_pools_before_releasing_leases(scheduler, monkeypatch):
    # Drive only the scheduler: no real worker threads, DB claims, or provider calls.
    executors = {}
    events = []
    clock = SimpleNamespace(now=10000, sleeps=0)

    class Executor:
        def __init__(self, max_workers, thread_name_prefix):
            self.limit = max_workers
            self.name = thread_name_prefix
            self.jobs = []
            executors[self.name] = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            assert all(future.done() for _, _, future in self.jobs)
            events.append(('shutdown', self.name))

        def submit(self, function, *args):
            future = Future()
            self.jobs.append((function, args, future))
            return future

    def claim(worker_id, lease_seconds=900, task_types=None):
        assert not scheduler.stopping
        return {'type': task_types[0]}

    def claim_asset(*args, **kwargs):
        assert not scheduler.stopping
        return {'type': 'asset'}

    def heartbeat(*args):
        events.append(('heartbeat', clock.sleeps))

    def sleep(delay):
        clock.sleeps += 1
        clock.now += scheduler.heartbeat_interval
        assert clock.sleeps <= 3
        assert not any(event[0] == 'release' for event in events)
        if clock.sleeps == 1:
            assert {name: len(pool.jobs) for name, pool in executors.items()} == {
                'generation': 3, 'polling': 2, 'assets': 1, 'maintenance': 1,
            }
            for name, pool in executors.items():
                assert len(pool.jobs) == pool.limit
                for function, args, _ in pool.jobs:
                    if name in ('generation', 'polling'):
                        assert function == scheduler.process
                        assert args[0]['type'] == ('image' if name == 'generation' else 'video')
                    elif name == 'assets':
                        assert function == scheduler.process_provider_asset
                    else:
                        assert function == scheduler._cleanup
            scheduler.request_stop()
        elif clock.sleeps == 2:
            for name in ('generation', 'polling', 'assets'):
                for _, _, future in executors[name].jobs:
                    future.set_result(None)
        else:
            executors['maintenance'].jobs[0][2].set_result(None)

    monkeypatch.setattr(worker, 'ThreadPoolExecutor', Executor)
    monkeypatch.setattr(worker, 'time', SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))
    monkeypatch.setattr(worker.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(worker.task_db, 'recover_dead_worker_leases', lambda: 0)
    monkeypatch.setattr(worker.task_db, 'upsert_worker_heartbeat', heartbeat)
    monkeypatch.setattr(worker.task_db, 'claim_next_task', claim)
    monkeypatch.setattr(worker.task_db, 'claim_next_provider_asset', claim_asset)
    monkeypatch.setattr(worker.task_db, 'release_worker_leases', lambda owner: events.append(('release', owner)))
    monkeypatch.setattr(worker.task_db, 'remove_worker_heartbeat', lambda owner: events.append(('remove', owner)))
    monkeypatch.setattr(worker.task_db, 'close_db', lambda: events.append(('close', None)))
    monkeypatch.setattr(worker.storage, 'release_process_memory', lambda: None)
    scheduler.run()
    assert [event[1] for event in events if event[0] == 'heartbeat'] == [0, 1, 2, 3]
    assert [event[0] for event in events[-7:]] == ['shutdown'] * 4 + ['release', 'remove', 'close']
    assert events[-3][1] == events[-2][1] == scheduler.worker_id
