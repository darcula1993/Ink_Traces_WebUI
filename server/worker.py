"""Durable SQLite-backed generation worker."""

import logging
import os
import signal
import socket
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait

import app as application
from logging_config import configure_logging
import storage
import tasks as task_db


LOG = logging.getLogger('nanobanana.worker')


class Worker:
    def __init__(self):
        self.worker_id = f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}'
        self.started_at = task_db.utcnow()
        self.stopping = False
        self.last_cleanup = 0.0
        self.last_heartbeat = 0.0
        self.last_memory_trim = 0.0
        server_config = application.config.get('server', {})
        default_concurrency = server_config.get('worker_concurrency', 3)
        self.concurrency = max(1, int(os.environ.get('WORKER_CONCURRENCY', default_concurrency)))
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

        futures = set()
        try:
            with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix='generation') as executor:
                while not self.stopping:
                    self.heartbeat()
                    self._maybe_cleanup()
                    completed = {future for future in futures if future.done()}
                    futures -= completed
                    if completed and time.monotonic() - self.last_memory_trim >= 30:
                        storage.release_process_memory()
                        self.last_memory_trim = time.monotonic()
                    while len(futures) < self.concurrency and not self.stopping:
                        task = task_db.claim_next_task(self.worker_id, lease_seconds=self.lease_seconds)
                        if task is None:
                            break
                        futures.add(executor.submit(self.process, task))
                    time.sleep(0.5 if futures else 1)
                if futures:
                    wait(futures)
        finally:
            task_db.release_worker_leases(self.worker_id)
            task_db.remove_worker_heartbeat(self.worker_id)
            task_db.close_db()
            LOG.info('worker_stopped id=%s', self.worker_id)

    def process(self, task):
        LOG.info(
            'task_claimed id=%s type=%s attempt=%s',
            task['id'], task['type'], task.get('attempt_count'),
        )
        try:
            if task_db.cancellation_requested(task['id']):
                task_db.finalize_task_cancel(task['id'])
                return
            with application.app.app_context():
                if task['type'] == 'image':
                    self._process_image(task)
                elif task['type'] == 'video':
                    self._process_video(task)
                else:
                    task_db.fail_task(task['id'], f'未知任务类型: {task["type"]}')
        except Exception as exc:
            LOG.exception('task_crashed id=%s', task['id'])
            if task_db.cancellation_requested(task['id']):
                task_db.finalize_task_cancel(task['id'])
                return
            max_attempts = self._image_crash_max_attempts(task) if task['type'] == 'image' else self._video_max_attempts()
            if int(task.get('attempt_count') or 0) < max_attempts:
                status = 'pending' if task['type'] == 'image' else 'processing'
                task_db.reschedule_task(task['id'], self._retry_delay(task), status=status, error=str(exc))
            else:
                task_db.fail_task(task['id'], str(exc))
        finally:
            if task_db.cancellation_requested(task['id']):
                task_db.finalize_task_cancel(task['id'])
            task_db.close_db()

    def _process_image(self, task):
        payload, status_code = application.execute_image_task(task['id'])
        if payload.get('cancelled') or task_db.cancellation_requested(task['id']):
            task_db.finalize_task_cancel(task['id'])
            LOG.info('task_cancelled id=%s type=image', task['id'])
            return
        if payload.get('success'):
            LOG.info('task_succeeded id=%s type=image', task['id'])
            return
        retryable = payload.get('retryable')
        if retryable is None:
            retryable = status_code >= 500 and task.get('provider') != 'ark'
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

    @staticmethod
    def _image_crash_max_attempts(task):
        # An Ark POST may have reached the provider before a local exception was raised.
        return 1 if task.get('provider') == 'ark' else 3

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
            status='processing',
            error=outcome.get('error'),
            progress=outcome.get('progress'),
        )

    def _video_max_attempts(self):
        return int(application.VIDEO_CONFIG.get('poll_max_attempts', 1800) or 1800)

    @staticmethod
    def _retry_delay(task, maximum=30):
        attempts = max(1, int(task.get('attempt_count') or 1))
        return min(maximum, 2 ** min(attempts, 6))

    def _maybe_cleanup(self):
        now = time.monotonic()
        if now - self.last_cleanup < self.cleanup_interval:
            return
        expired = storage.cleanup_expired_assets()
        orphaned = storage.cleanup_orphans(self.orphan_grace_seconds)
        task_db.checkpoint()
        self.last_cleanup = now
        if expired or orphaned['files'] or orphaned['directories']:
            LOG.info('storage_cleanup expired=%s orphaned=%s', expired, orphaned)


def main():
    configure_logging()
    Worker().run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
