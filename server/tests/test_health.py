import os

import app as application
import tasks as task_db


def test_operational_health_is_open_when_auth_is_enabled(monkeypatch):
    monkeypatch.setattr(application, 'AUTH_CONFIG', {'username': 'admin', 'password': 'secret'})
    task_db.upsert_worker_heartbeat('test-worker', os.getpid(), task_db.utcnow())
    client = application.app.test_client()

    assert client.get('/api/live').status_code == 200
    ready = client.get('/api/ready')
    assert ready.status_code == 200
    assert ready.get_json()['worker_ok'] is True
    assert client.get('/api/tasks').status_code == 401


def test_video_validation_returns_400(monkeypatch):
    monkeypatch.setattr(application, 'AUTH_CONFIG', {})
    client = application.app.test_client()
    response = client.post('/api/video/generate', json={
        'prompt': 'test',
        'provider': 'ark',
        'duration': 'invalid',
    })
    assert response.status_code == 400
    assert response.get_json()['error'] == 'duration 必须是整数'
