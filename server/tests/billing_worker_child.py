"""Child process for the kill -9 billing-boundary test (not collected by pytest).

usage: billing_worker_child.py <db_path> <calls_file> <tmp_dir> <block|record>
Runs the real Worker.run() loop with provider execution replaced by a recorder.
'block' never returns from the provider call (simulates a request in flight);
'record' fails the task immediately after recording (used to observe what gets claimed).
"""

import os
import sys
import time

db_path, calls_path, tmp_dir, mode = sys.argv[1:5]
if os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config.json')):
    sys.exit('[test-isolation] refusing to import app next to a real config.json')
os.environ['NANOBANANA_DB_PATH'] = db_path
os.environ['NANOBANANA_CONFIG_FILE'] = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config.json.example')

import tasks as task_db  # noqa: E402

task_db.configure(db_path)

import storage  # noqa: E402

storage.PROJECT_ROOT = tmp_dir
storage.OUTPUT_DIR = os.path.join(tmp_dir, 'output')
storage.UPLOAD_VIDEO_DIR = os.path.join(tmp_dir, 'upload_video')
storage.WORKSPACE_ASSET_DIR = os.path.join(tmp_dir, 'workspace_assets')

import app as application  # noqa: E402
import worker  # noqa: E402

application.ERROR_LOGS_DIR = tmp_dir


def recorder(kind):
    def run(task_id):
        with open(calls_path, 'a', encoding='utf-8') as handle:
            handle.write(f'{kind}:{task_id}\n')
            handle.flush()
            os.fsync(handle.fileno())
        if mode == 'block':
            time.sleep(3600)
        task_db.fail_task(task_id, 'child recorder')
        return {'success': False, 'retryable': False, 'error': 'child recorder'}, 400
    return run


application.execute_image_task = recorder('image')
application.execute_layer_task = recorder('layer')
application.config = {'server': {'generation_concurrency': 4}}
runner = worker.Worker()
runner._maybe_cleanup = lambda _executor: None
runner.run()
