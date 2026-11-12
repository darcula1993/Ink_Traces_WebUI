import os
from pathlib import Path

import pytest

# app.py reads config.json v2 at import time. A test session in a checkout that holds real
# credentials must never load them, so refuse before import: tests run in a task worktree
# without config.json (see doc/development.md, 验证). The app is pointed at the committed
# credential-free example (always overwritten, never inherited from the environment).
REPO_ROOT = Path(__file__).resolve().parents[2]
if (REPO_ROOT / 'config.json').exists():
    raise pytest.UsageError(
        f'[test-isolation] 拒绝运行：{REPO_ROOT / "config.json"} 存在。'
        '测试只能在不含 config.json 的任务 worktree 中运行，避免读取真实配置。'
    )
os.environ['NANOBANANA_CONFIG_FILE'] = str(REPO_ROOT / 'config.json.example')

import app as application  # noqa: E402
import storage  # noqa: E402
import tasks as task_db  # noqa: E402
from canvas_store import init_canvas_db  # noqa: E402
from provider_profiles import init_profiles_db  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_backend(tmp_path, monkeypatch):
    task_db.configure(tmp_path / 'tasks.db')
    init_canvas_db()
    init_profiles_db()
    monkeypatch.setattr(storage, 'PROJECT_ROOT', str(tmp_path))
    monkeypatch.setattr(storage, 'OUTPUT_DIR', str(tmp_path / 'output'))
    monkeypatch.setattr(storage, 'UPLOAD_VIDEO_DIR', str(tmp_path / 'upload_video'))
    monkeypatch.setattr(storage, 'WORKSPACE_ASSET_DIR', str(tmp_path / 'workspace_assets'))
    monkeypatch.setattr(application, 'UPLOAD_VIDEO_DIR', storage.UPLOAD_VIDEO_DIR)
    storage.ensure_storage_dirs()
    application.app.config.update(TESTING=True)
    monkeypatch.setattr(application, 'AUTH_CONFIG', {})
    # save_error_log writes JSON files; keep them out of the repository's error_logs/.
    error_logs = tmp_path / 'error_logs'
    error_logs.mkdir(exist_ok=True)
    monkeypatch.setattr(application, 'ERROR_LOGS_DIR', str(error_logs))
    yield tmp_path
    task_db.close_db()


def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'billing_slow: billing-boundary cases that spawn processes or wait on real sockets '
        '(deselect with -m "not billing_slow")',
    )
