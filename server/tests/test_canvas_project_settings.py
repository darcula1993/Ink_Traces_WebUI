"""Project default interfaces were removed on 2026-11-13; old rows stay untouched and unused."""
import json

import pytest

import app as application
import canvas_store as store
import tasks
from canvas_project_settings import validate_generation


def project():
    p = store.create_project('test')
    w = store.create_workflow(p['id'], 'workflow')
    return p['id'], w['id']


def test_legacy_rows_are_kept_but_not_exposed():
    p, _ = project()
    providers = {'image': {'provider': 'ark', 'profile_id': None}, 'video': None, 'audio': None}
    tasks.get_db().execute('INSERT INTO canvas_project_generation_settings VALUES (?,?,?)', (p, 3, json.dumps(providers)))
    tasks.get_db().commit()
    client = application.app.test_client()
    assert client.get(f'/api/canvas/projects/{p}/generation-settings').status_code == 404
    row = tasks.get_db().execute('SELECT revision,providers FROM canvas_project_generation_settings WHERE project_id=?', (p,)).fetchone()
    assert (row['revision'], json.loads(row['providers'])) == (3, providers)


@pytest.mark.parametrize('multipart', [False, True])
def test_canvas_request_without_node_is_rejected_before_task_creation(multipart):
    p, w = project()
    client = application.app.test_client()
    before = tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0]
    data = {'canvas_workflow_id': w, 'project_settings_revision': 1, 'provider': 'ark', 'prompt': 'test'}
    response = client.post('/api/generate', data=data, content_type='multipart/form-data') if multipart else client.post('/api/generate', json=data)
    assert response.status_code == 400
    assert tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0] == before


def test_noncanvas_legacy_api_remains_independent():
    validate_generation({'provider': 'ark'}, 'image')
    validate_generation({'provider': 'cupsy', 'project_settings_revision': 9}, 'video')


def test_provider_preferences_workspace_state_round_trip_and_shape():
    client = application.app.test_client()
    url = '/api/workspace/state/canvas_provider_preferences'
    value = {'image': {'provider': 'cupsy', 'profile_id': None}, 'video': {'provider': 'ark', 'profile_id': 'a' * 32}}
    response = client.put(url, json={'value': value})
    assert response.status_code == 200
    assert client.get(url).json['state']['value'] == value
    for bad in [[], {'text': {'provider': 'ark'}}, {'audio': {'provider': 'ark'}}, {'image': {'provider': 'ark', 'profile_id': 'bad'}},
                {'image': {'provider': 'ark', 'extra': 1}}]:
        assert client.put(url, json={'value': bad}).status_code == 400
    assert client.get(url).json['state']['value'] == value
