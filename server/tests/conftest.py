import os

import pytest

import app as application
import storage
import tasks as task_db


@pytest.fixture(autouse=True)
def isolated_backend(tmp_path, monkeypatch):
    task_db.configure(tmp_path / 'tasks.db')
    monkeypatch.setattr(storage, 'PROJECT_ROOT', str(tmp_path))
    monkeypatch.setattr(storage, 'OUTPUT_DIR', str(tmp_path / 'output'))
    monkeypatch.setattr(storage, 'UPLOAD_VIDEO_DIR', str(tmp_path / 'upload_video'))
    monkeypatch.setattr(storage, 'WORKSPACE_ASSET_DIR', str(tmp_path / 'workspace_assets'))
    monkeypatch.setattr(application, 'UPLOAD_VIDEO_DIR', storage.UPLOAD_VIDEO_DIR)
    storage.ensure_storage_dirs()
    application.app.config.update(TESTING=True)
    monkeypatch.setattr(application, 'AUTH_CONFIG', {})
    yield tmp_path
    task_db.close_db()
