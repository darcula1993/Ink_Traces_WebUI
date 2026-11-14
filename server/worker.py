"""Durable SQLite-backed generation worker."""

import logging
import os
import signal
import socket
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import app as application
from logging_config import configure_logging
import storage
import tasks as task_db
import profile_runtime


LOG = logging.getLogger('nanobanana.worker')


class Worker:
    def __init__(self):
        self.worker_id = f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}'
        self.started_at = task_db.utcnow()
        self.stopping = False
        self.last_cleanup = 0.0
        self.last_heartbeat = 0.0
        self.last_memory_trim = 0.0
        self.cleanup_future = None
        server_config = application.config.get('server', {})
        default_concurrency = server_config.get(
            'generation_concurrency', server_config.get('worker_concurrency', 3)
        )
        self.concurrency = max(1, int(os.environ.get('WORKER_CONCURRENCY', default_concurrency)))
        self.generation_concurrency = self.concurrency
        self.polling_concurrency = max(1, int(server_config.get('polling_concurrency', 2)))
        self.asset_concurrency = max(1, int(server_config.get('asset_concurrency', 1)))
        self.lease_seconds = max(60, int(server_config.get('worker_lease_seconds', 900)))
        self.heartbeat_interval = max(5, min(20, int(server_config.get('worker_heartbeat_seconds', 10))))
        self.cleanup_interval = max(60, int(server_config.get('cleanup_interval_seconds', 3600)))
        self.orphan_grace_seconds = max(0, int(server_config.get('orphan_grace_hours', 24))) * 60 * 60

    def request_stop(self, *_):
        self.stopping = True

    def heartbeat(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_heartbeat < self.heartbeat_interval:
            return
        task_db.upsert_worker_heartbeat(self.worker_id, os.getpid(), self.started_at)
        self.last_heartbeat = now

    def run(self):
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        recovered = task_db.recover_dead_worker_leases()
        LOG.info('worker_started id=%s', self.worker_id)
        if recovered:
            LOG.warning('worker_recovered_leases count=%s', recovered)
        self.heartbeat(force=True)

        try:
            with ExitStack() as stack:
                pools = []
                for name, concurrency, task_types in (
                    ('generation', self.generation_concurrency, ('image', 'layer')),
                    ('polling', self.polling_concurrency, ('video', 'audio')),
                    ('assets', self.asset_concurrency, None),
                ):
                    executor = stack.enter_context(ThreadPoolExecutor(
                        max_workers=concurrency, thread_name_prefix=name,
                    ))
                    pools.append((executor, set(), concurrency, task_types))
                maintenance = stack.enter_context(ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix='maintenance',
                ))
                while True:
                    self.heartbeat()
                    completed = set()
                    for _, futures, _, _ in pools:
                        done = {future for future in futures if future.done()}
                        futures.difference_update(done)
                        completed.update(done)
                    if completed and time.monotonic() - self.last_memory_trim >= 30:
                        storage.release_process_memory()
                        self.last_memory_trim = time.monotonic()
                    if not self.stopping:
                        self._maybe_cleanup(maintenance)
                        for executor, futures, concurrency, task_types in pools:
                            self._fill_pool(executor, futures, concurrency, task_types)
                    busy = any(futures for _, futures, _, _ in pools)
                    cleaning = self.cleanup_future is not None and not self.cleanup_future.done()
                    # Keep the lease owner alive until all executor work has drained.
                    if self.stopping and not busy and not cleaning:
                        break
                    time.sleep(0.5 if busy or cleaning else 1)
        finally:
            task_db.release_worker_leases(self.worker_id)
            task_db.remove_worker_heartbeat(self.worker_id)
            task_db.close_db()
            LOG.info('worker_stopped id=%s', self.worker_id)

    def _fill_pool(self, executor, futures, concurrency, task_types):
        # Claim only free slots: the executor's unbounded queue must never build up.
        while len(futures) < concurrency and not self.stopping:
            if task_types is None:
                task = task_db.claim_next_provider_asset(
                    self.worker_id, lease_seconds=min(self.lease_seconds, 300),
                )
                process = self.process_provider_asset
            else:
                task = task_db.claim_next_task(
                    self.worker_id, lease_seconds=self.lease_seconds, task_types=task_types,
                )
                process = self.process
            if task is None:
                break
            futures.add(executor.submit(process, task))

    def process_provider_asset(self, asset):
        LOG.info('provider_asset_claimed id=%s provider=%s', asset['id'], asset['provider'])
        try:
            with application.app.app_context(), profile_runtime.profile_scope(profile_runtime.asset_selection(asset)):
                outcome = application.process_cupsy_asset_once(asset['id'])
            state = outcome.get('state')
            if state in ('active', 'failed', 'deleted'):
                return
            attempts = int(asset.get('attempt_count') or 0)
            profile = profile_runtime.asset_selection(asset)
            retry_budget = profile['settings'].get('poll_max_attempts', 30) if profile else 30
            if attempts >= retry_budget:
                task_db.update_provider_asset(
                    asset['id'], status='failed', error=outcome.get('error') or '素材导入超时',
                    next_run_at=None, lease_owner=None, lease_until=None,
                )
                return
            interval = profile['settings'].get('poll_interval_seconds', 2) if profile else 2
            delay = self._retry_delay(asset, maximum=60) if state == 'retry' else interval
            task_db.reschedule_provider_asset(
                asset['id'], delay, status='processing', error=outcome.get('error')
            )
        except Exception as exc:
            LOG.exception('provider_asset_crashed id=%s', asset['id'])
            task_db.reschedule_provider_asset(asset['id'], 5, status='processing', error=str(exc))
        finally:
            task_db.close_db()

    def process(self, task):
        LOG.info(
            'task_claimed id=%s type=%s attempt=%s',
            task['id'], task['type'], task.get('attempt_count'),
        )
        application.reset_provider_dispatch()
        try:
            if task_db.cancellation_requested(task['id']):
                task_db.finalize_task_cancel(task['id'])
                return
            with application.app.app_context(), profile_runtime.profile_scope(profile_runtime.load_selection(task.get('params'))):
                if task['type'] == 'image':
                    self._process_image(task)
                elif task['type'] == 'layer':
                    self._process_layer(task)
                elif task['type'] == 'video':
                    self._process_video(task)
                elif task['type'] == 'audio':
                    self._process_audio(task)
                else:
                    task_db.fail_task(task['id'], f'未知任务类型: {task["type"]}')
        except Exception as exc:
            LOG.exception('task_crashed id=%s', task['id'])
            if task_db.cancellation_requested(task['id']):
                task_db.finalize_task_cancel(task['id'])
                return
            with profile_runtime.profile_scope(profile_runtime.load_selection(task.get('params'))):
                max_attempts = self._image_crash_max_attempts(task) if task['type'] in {'image', 'layer'} else self._poll_max_attempts(task['type'])
            if int(task.get('attempt_count') or 0) < max_attempts:
                status = 'pending' if task['type'] in {'image', 'layer'} or (
                    task['type'] in {'video', 'audio'} and task.get('provider') == 'cupsy'
                    and not task.get('external_task_id')
                ) else 'processing'
                task_db.reschedule_task(task['id'], self._retry_delay(task), status=status, error=str(exc))
            elif self._request_may_have_been_sent(task):
                LOG.warning('task_result_unknown id=%s type=%s provider=%s',
                            task['id'], task['type'], task.get('provider'))
                task_db.fail_task_result_unknown(
                    task['id'], task_db.worker_exception_error(exc), 'worker_exception',
                )
            else:
                task_db.fail_task(task['id'], str(exc))
        finally:
            if task_db.cancellation_requested(task['id']):
                task_db.finalize_task_cancel(task['id'])
            self._write_back(task['id'])
            task_db.close_db()

    @staticmethod
    def _write_back(task_id):
        # CANVAS-WRITEBACK B: after the task row is final, write its result into the
        # canvas once. No provider call, no retry, no task change; failures only log.
        try:
            import canvas_writeback
            canvas_writeback.apply_task_result_safely(task_id)
        except Exception:
            LOG.exception('canvas_writeback_hook_failed id=%s', task_id)

    def _process_image(self, task):
        payload, status_code = application.execute_image_task(task['id'])
        if payload.get('cancelled') or task_db.cancellation_requested(task['id']):
            task_db.finalize_task_cancel(task['id'])
            LOG.info('task_cancelled id=%s type=image', task['id'])
            return
        if payload.get('pending'):
            limit = int(application.API_PROVIDERS['cupsy'].get('poll_max_attempts', 1800))
            if int(task.get('attempt_count') or 0) >= limit:
                task_db.fail_task(task['id'], payload.get('error') or 'Cupsy 图片任务等待超时')
                return
            task_db.reschedule_task(
                task['id'], payload.get('retry_after', 15), status='processing',
                error=payload.get('error'),
            )
            return
        if payload.get('success'):
            LOG.info('task_succeeded id=%s type=image', task['id'])
            return
        retryable = payload.get('retryable')
        if retryable is None:
            retryable = status_code >= 500 and task.get('provider') != 'ark'
        if payload.get('result_unknown'):
            # Never resubmit a request that may already have reached the provider.
            retryable = False
        if retryable and int(task.get('attempt_count') or 0) < 3:
            task_db.reschedule_task(
                task['id'],
                self._retry_delay(task),
                status='pending',
                error=payload.get('error'),
            )
            LOG.warning('task_rescheduled id=%s type=image status=%s', task['id'], status_code)
            return
        LOG.warning('task_failed id=%s type=image status=%s', task['id'], status_code)

    def _process_layer(self, task):
        payload, status_code = application.execute_layer_task(task['id'])
        if payload.get('cancelled') or task_db.cancellation_requested(task['id']):
            task_db.finalize_task_cancel(task['id'])
            LOG.info('task_cancelled id=%s type=layer', task['id'])
            return
        if payload.get('success'):
            LOG.info('task_succeeded id=%s type=layer', task['id'])
            return
        LOG.warning('task_failed id=%s type=layer status=%s', task['id'], status_code)

    @staticmethod
    def _image_crash_max_attempts(task):
        # An Ark POST may have reached the provider before a local exception was raised.
        return 1 if task.get('provider') in task_db.NON_IDEMPOTENT_PROVIDERS else 3

    @staticmethod
    def _request_may_have_been_sent(task):
        # The dispatch marker is set in this thread right before the provider POST, so an
        # exception with the marker unset (config, input file read, validation) is pre-send.
        return (
            task['type'] in {'image', 'layer'}
            and task.get('provider') in task_db.NON_IDEMPOTENT_PROVIDERS
            and application.provider_dispatch_started()
        )

    def _process_video(self, task):
        outcome = application.poll_video_task_once(task['id'])
        state = outcome.get('state')
        if state in ('succeeded', 'failed', 'cancelled'):
            LOG.info('task_terminal id=%s type=video state=%s', task['id'], state)
            return

        attempts = int(task.get('attempt_count') or 0)
        if attempts >= self._video_max_attempts():
            task_db.fail_task(task['id'], outcome.get('error') or '视频任务轮询超时')
            return

        if state == 'retry':
            delay = self._retry_delay(task, maximum=60)
        else:
            delay = int(application.VIDEO_CONFIG.get('poll_interval_seconds', 4) or 4)
        task_db.reschedule_task(
            task['id'],
            delay,
            status='pending' if state == 'preparing' else 'processing',
            error=outcome.get('error'),
            progress=outcome.get('progress'),
        )

    def _process_audio(self, task):
        outcome = application.poll_audio_task_once(task['id'])
        state = outcome.get('state')
        if state in ('succeeded', 'failed', 'cancelled'):
            LOG.info('task_terminal id=%s type=audio state=%s', task['id'], state)
            return

        attempts = int(task.get('attempt_count') or 0)
        if attempts >= self._poll_max_attempts('audio'):
            task_db.fail_task(task['id'], outcome.get('error') or '音频任务轮询超时')
            return
        delay = self._retry_delay(task, maximum=60) if state == 'retry' else int(
            application.AUDIO_CONFIG.get('poll_interval_seconds', 4) or 4
        )
        task_db.reschedule_task(
            task['id'], delay,
            status='pending' if state == 'preparing' else 'processing',
            error=outcome.get('error'), progress=outcome.get('progress'),
        )

    def _video_max_attempts(self):
        return int(application.VIDEO_CONFIG.get('poll_max_attempts', 1800) or 1800)

    @staticmethod
    def _poll_max_attempts(task_type):
        settings = application.AUDIO_CONFIG if task_type == 'audio' else application.VIDEO_CONFIG
        return int(settings.get('poll_max_attempts', 1800) or 1800)

    @staticmethod
    def _retry_delay(task, maximum=30):
        attempts = max(1, int(task.get('attempt_count') or 1))
        return min(maximum, 2 ** min(attempts, 6))

    def _maybe_cleanup(self, executor):
        if self.cleanup_future is not None and not self.cleanup_future.done():
            return
        now = time.monotonic()
        if now - self.last_cleanup < self.cleanup_interval:
            return
        self.cleanup_future = executor.submit(self._cleanup)
        self.last_cleanup = now

    def _cleanup(self):
        try:
            storage.cleanup_workspace_assets_all()
            expired = storage.cleanup_expired_assets()
            orphaned = storage.cleanup_orphans(self.orphan_grace_seconds)
            task_db.checkpoint()
            if expired or orphaned['files'] or orphaned['directories']:
                LOG.info('storage_cleanup expired=%s orphaned=%s', expired, orphaned)
        except Exception:
            LOG.exception('storage_cleanup_failed')
        finally:
            task_db.close_db()


def main():
    configure_logging()
    Worker().run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
