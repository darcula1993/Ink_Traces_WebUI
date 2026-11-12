"""Canvas persistence, optimistic concurrency and durable-media boundaries."""
import copy
import io
from pathlib import Path

from flask import Flask
from PIL import Image
import pytest

import canvas_store as store
from canvas_api import canvas_api
import storage
import tasks as task_db


@pytest.fixture
def client(isolated_backend, monkeypatch):
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(isolated_backend / 'canvas_assets'))
    store.init_canvas_db()
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(canvas_api)
    return app.test_client()


def create(client):
    parent = client.post('/api/canvas/projects', json={'title': '测试项目'}).json['project']
    response = client.post(f"/api/canvas/projects/{parent['id']}/workflows", json={'title': '测试画布'})
    assert response.status_code == 201
    return response.json['workflow']


def png():
    data = io.BytesIO()
    Image.new('RGB', (2, 2), 'blue').save(data, format='PNG')
    return data.getvalue()


def upload(client, workflow):
    response = client.post(f"/api/canvas/workflows/{workflow['id']}/assets", data={'file': (io.BytesIO(png()), '参考.png')})
    assert response.status_code == 201
    return response.json['asset']


def test_revision_conflict_and_reload(client):
    p = create(client)
    url = f"/api/canvas/workflows/{p['id']}"
    payload = {'title': '修订', 'document': p['document'], 'revision': p['revision']}
    assert client.put(url, json=payload).json['workflow']['revision'] == 2
    assert client.put(url, json=payload).status_code == 409
    assert client.get(url).json['workflow']['title'] == '修订'
    assert 'document' not in client.get(f"/api/canvas/projects/{p['project_id']}/workflows").json['workflows'][0]
    store.init_canvas_db()
    assert client.get(url).json['workflow']['revision'] == 2


def test_asset_workflow_isolation_and_range(client):
    a, b = create(client), create(client)
    asset = upload(client, a)
    assert upload(client, a)['id'] == asset['id']
    assert client.get(asset['url']).data == png()
    assert client.get(asset['url'], headers={'Range': 'bytes=0-7'}).status_code == 206
    assert client.get(asset['url'].replace(a['id'], b['id'])).status_code == 404
    doc = copy.deepcopy(b['document'])
    doc['nodes'] = [{'id': 'n1', 'x': 0, 'y': 0, 'type': 'image', 'asset': asset}]
    assert client.put(f"/api/canvas/workflows/{b['id']}", json={'title': b['title'], 'document': doc, 'revision': 1}).status_code == 400


def test_import_survives_source_deletion_and_is_idempotent(client):
    p = create(client)
    task_id = task_db.create_task('image', 'synthetic', {})
    directory = Path(storage.OUTPUT_DIR) / 'image' / str(task_id)
    directory.mkdir(parents=True)
    path = directory / 'image.png'
    path.write_bytes(png())
    task_db.register_asset(task_id, 'output_image', str(path), 'image/png')
    task_db.update_task(task_id, status='succeeded')
    url = f"/api/canvas/workflows/{p['id']}/task-results"
    first = client.post(url, json={'task_id': task_id})
    assert first.status_code == 200
    assert client.post(url, json={'task_id': task_id}).json['assets'] == first.json['assets']
    path.unlink()
    db = task_db.get_db()
    db.execute('DELETE FROM task_assets WHERE task_id=?', (task_id,))
    db.execute('DELETE FROM tasks WHERE id=?', (task_id,))
    db.commit()
    storage.cleanup_workspace_assets_all()
    storage.cleanup_orphans(0)
    assert client.get(first.json['assets'][0]['url']).data == png()


@pytest.mark.parametrize('filename,content', [('../x.png', b'x'), ('evil.svg', b'<svg onload="alert(1)"/>'), ('x.html', b'<html>evil</html>')])
def test_reject_invalid_upload(client, filename, content):
    p = create(client)
    assert client.post(f"/api/canvas/workflows/{p['id']}/assets", data={'file': (io.BytesIO(content), filename)}).status_code == 400
    assert not list(store.asset_root().rglob('*.tmp'))


@pytest.mark.parametrize('mutation', ['nan', 'external', 'dangling', 'duplicate', 'path', 'version', 'wrong_revision'])
def test_reject_malformed_document(client, mutation):
    p = create(client)
    doc = p['document']
    doc['nodes'] = [{'id': 'n1', 'x': 0, 'y': 0, 'type': 'text', 'text': 'note'}]
    revision = 1
    if mutation == 'nan': doc['viewport']['x'] = float('nan')
    if mutation == 'external': doc['nodes'][0]['url'] = 'http://localhost/private'
    if mutation == 'dangling': doc['edges'] = [{'id': 'e1', 'source': 'n1', 'target': 'missing'}]
    if mutation == 'duplicate': doc['nodes'].append(copy.deepcopy(doc['nodes'][0]))
    if mutation == 'path': doc['nodes'][0]['path'] = '/etc/passwd'
    if mutation == 'version': doc['version'] = True
    if mutation == 'wrong_revision': revision = True
    assert client.put(f"/api/canvas/workflows/{p['id']}", json={'title': p['title'], 'revision': revision, 'document': doc}).status_code == 400


def test_reject_task_path_escape_and_running_task(client, isolated_backend):
    p = create(client)
    task_id = task_db.create_task('image', 'synthetic', {})
    url = f"/api/canvas/workflows/{p['id']}/task-results"
    assert client.post(url, json={'task_id': task_id}).status_code == 409
    path = isolated_backend / 'outside.png'
    path.write_bytes(png())
    task_db.register_asset(task_id, 'output_image', str(path), 'image/png')
    task_db.update_task(task_id, status='succeeded')
    assert client.post(url, json={'task_id': task_id}).status_code == 409


def test_asset_size_limit_and_symlink(client, monkeypatch, isolated_backend):
    p = create(client)
    monkeypatch.setattr(store, 'MAX_ASSET_BYTES', 4)
    assert client.post(f"/api/canvas/workflows/{p['id']}/assets", data={'file': (io.BytesIO(png()), 'x.png')}).status_code == 413
    assert not list(store.asset_root().rglob('*.tmp'))
    monkeypatch.setattr(store, 'MAX_ASSET_BYTES', 100000)
    directory = store.asset_root() / p['id']
    directory.rmdir()
    outside = isolated_backend / 'outside'
    outside.mkdir()
    directory.symlink_to(outside)
    assert client.post(f"/api/canvas/workflows/{p['id']}/assets", data={'file': (io.BytesIO(png()), 'x.png')}).status_code == 400
    assert not list(outside.iterdir())


def test_project_has_multiple_independent_workflows(client):
    parent = client.post('/api/canvas/projects', json={'title': '第一项目'}).json['project']
    assert 'document' not in parent and 'revision' not in parent
    workflows = [client.post(f"/api/canvas/projects/{parent['id']}/workflows", json={'title': title}).json['workflow'] for title in ('分镜', '声音')]
    other = create(client)
    listing = client.get(f"/api/canvas/projects/{parent['id']}/workflows").json['workflows']
    assert {w['id'] for w in listing} == {w['id'] for w in workflows}
    assert other['id'] not in {w['id'] for w in listing}
    asset = upload(client, workflows[0])
    doc = copy.deepcopy(workflows[0]['document'])
    doc['nodes'] = [
        {'id': 'text-1', 'type': 'text', 'title': '对白', 'x': -120, 'y': 20, 'text': '人工编辑文本'},
        {'id': 'image-1', 'type': 'image', 'title': '角色', 'x': 220, 'y': 20, 'text': '测试',
         'params': {'provider': 'ark', 'model': 'test-model', 'ratio': '9:16', 'resolution': '1K'},
         'asset': asset, 'candidates': [asset], 'selectedCandidateId': asset['id'], 'task': {'id': 1, 'status': 'succeeded', 'error': None}},
        {'id': 'video-1', 'type': 'video', 'x': 500, 'y': 20, 'params': {'duration': 5}},
        {'id': 'audio-1', 'type': 'audio', 'x': 500, 'y': 300},
    ]
    doc['edges'] = [{'id': 'edge-1', 'source': 'text-1', 'target': 'image-1'}]
    saved = client.put(f"/api/canvas/workflows/{workflows[0]['id']}", json={'title': '已保存', 'document': doc, 'revision': 1})
    assert saved.status_code == 200
    assert saved.json['workflow']['document'] == doc
    assert client.get(f"/api/canvas/workflows/{workflows[1]['id']}").json['workflow']['document']['nodes'] == []
    assert client.put(f"/api/canvas/workflows/{workflows[1]['id']}", json={'title': '错误引用', 'document': doc, 'revision': 1}).status_code == 400
    assert client.patch(f"/api/canvas/projects/{parent['id']}", json={'title': '改名'}).json['project']['title'] == '改名'
    assert client.post('/api/canvas/projects/missing/workflows', json={'title': '无父项目'}).status_code == 404


def test_wav_container_validation(client):
    import wave
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x00\x00' * 800)
    w = create(client)
    url = f"/api/canvas/workflows/{w['id']}/assets"
    result = client.post(url, data={'file': (io.BytesIO(buffer.getvalue()), 'voice.wav')})
    assert result.status_code == 201
    assert result.json['asset']['kind'] == 'audio'
    assert client.post(url, data={'file': (io.BytesIO(b'RIFF\x00\x00\x00\x00WAVE'), 'fake.wav')}).status_code == 400


def test_oversize_and_invalid_json(client, monkeypatch):
    w = create(client)
    url = f"/api/canvas/workflows/{w['id']}"
    assert client.put(url, data=b'not json', content_type='application/json').status_code == 400
    monkeypatch.setattr(store, 'MAX_DOCUMENT_BYTES', 10)
    assert client.put(url, json={'title': 'x', 'revision': 1, 'document': w['document']}).status_code == 413
    assert client.put(url, data=b'x' * 5000, content_type='application/json').status_code == 413


def test_project_library_and_group_reference_snapshots(client):
    a = create(client)
    project_url = f"/api/canvas/projects/{a['project_id']}"
    b = client.post(project_url + '/workflows', json={'title': '第二画布'}).json['workflow']
    other = create(client)
    asset = client.post(project_url + '/assets', data={'file': (io.BytesIO(png()), '角色.png')}).json['asset']
    assert client.get(asset['url']).data == png()
    assert client.get(project_url + '/assets').json['assets'] == [asset]
    assert client.get(asset['url'].replace(a['project_id'], other['project_id'])).status_code == 404
    group = client.post(project_url + '/asset-groups', json={'title': '角色组', 'asset_ids': [asset['id']]}).json['group']
    results = []
    for workflow in (a, b):
        url = f"/api/canvas/workflows/{workflow['id']}/reference-assets"
        result = client.post(url, json={'asset_ids': [asset['id']], 'group_ids': [group['id']]})
        assert result.status_code == 200
        result = result.json
        assert len(result['assets']) == 1
        assert result['assets'][0]['url'].startswith(f"/api/canvas/workflows/{workflow['id']}/")
        assert result['groups'][0]['asset_ids'] == [result['assets'][0]['id']]
        assert client.post(url, json={'group_ids': [group['id']]}).json['assets'] == result['assets']
        doc = copy.deepcopy(workflow['document'])
        doc['nodes'] = [{'id': 'image1', 'type': 'image', 'x': 0, 'y': 0, 'referenceAssets': result['assets'], 'referenceGroups': result['groups']}]
        saved = client.put(f"/api/canvas/workflows/{workflow['id']}", json={'title': workflow['title'], 'document': doc, 'revision': 1})
        assert saved.status_code == 200
        results.append(result)
    assert results[0]['assets'][0]['id'] != results[1]['assets'][0]['id']
    assert client.post(f"/api/canvas/workflows/{other['id']}/reference-assets", json={'asset_ids': [asset['id']]}).status_code == 404
    assert client.post(f"/api/canvas/workflows/{other['id']}/reference-assets", json={'group_ids': [group['id']]}).status_code == 404
    assert client.post(f"/api/canvas/projects/{other['project_id']}/asset-groups", json={'title': '非法', 'asset_ids': [asset['id']]}).status_code == 404
    assert client.patch(project_url + f"/asset-groups/{group['id']}", json={'title': '新组名'}).status_code == 200
    old_doc = client.get(f"/api/canvas/workflows/{a['id']}").json['workflow']['document']
    assert old_doc['nodes'][0]['referenceGroups'][0]['title'] == '角色组'
    # Source deletion cannot invalidate the workflow snapshot's copied media.
    store.asset_path(store.get_asset(a['project_id'], asset['id'], library=True)).unlink()
    assert client.get(results[0]['assets'][0]['url']).data == png()
    assert client.get(results[1]['assets'][0]['url']).data == png()


def test_save_workflow_result_to_parent_library(client):
    a, other = create(client), create(client)
    asset = upload(client, a)
    payload = {'workflow_id': a['id'], 'asset_id': asset['id']}
    url = f"/api/canvas/projects/{a['project_id']}/assets/from-workflow"
    copied = client.post(url, json=payload)
    assert copied.status_code == 201
    assert client.post(url, json=payload).json['asset'] == copied.json['asset']
    assert client.post(f"/api/canvas/projects/{other['project_id']}/assets/from-workflow", json=payload).status_code == 404
    store.asset_path(store.get_asset(a['id'], asset['id'])).unlink()
    assert client.get(copied.json['asset']['url']).data == png()


def test_reject_invalid_reference_group_and_huge_number(client):
    w = create(client)
    doc = w['document']
    doc['nodes'] = [{'id': 'n', 'type': 'image', 'x': 0, 'y': 0, 'referenceAssets': [], 'referenceGroups': [{'id': 'g', 'title': '错误', 'asset_ids': ['missing']}]}]
    url = f"/api/canvas/workflows/{w['id']}"
    assert client.put(url, json={'title': 'x', 'revision': 1, 'document': doc}).status_code == 400
    doc['nodes'] = []
    doc['viewport']['x'] = 10 ** 400
    assert client.put(url, json={'title': 'x', 'revision': 1, 'document': doc}).status_code == 400


@pytest.mark.parametrize('source_type,target_type,allowed', [
    (source, target, target in {'text': {'image', 'video', 'audio'}, 'image': {'image', 'video', 'audio'}, 'video': {'video'}, 'audio': {'video', 'audio'}}[source])
    for source in ('text', 'image', 'video', 'audio') for target in ('text', 'image', 'video', 'audio')
])
def test_connection_type_matrix(client, source_type, target_type, allowed):
    w = create(client)
    doc = w['document']
    doc['nodes'] = [{'id': 'a', 'type': source_type, 'x': 0, 'y': 0}, {'id': 'b', 'type': target_type, 'x': 1, 'y': 1}]
    doc['edges'] = [{'id': 'edge', 'source': 'a', 'target': 'b'}]
    result = client.put(f"/api/canvas/workflows/{w['id']}", json={'title': '连接', 'revision': 1, 'document': doc})
    assert result.status_code == (200 if allowed else 400)


@pytest.mark.parametrize('pairs', [[('a', 'a')], [('a', 'b'), ('a', 'b')], [('a', 'b'), ('b', 'c'), ('c', 'a')]])
def test_reject_self_duplicate_and_cyclic_edges(client, pairs):
    w = create(client)
    doc = w['document']
    doc['nodes'] = [{'id': n, 'type': 'image', 'x': 0, 'y': 0} for n in ('a', 'b', 'c')]
    doc['edges'] = [{'id': f'e{i}', 'source': source, 'target': target} for i, (source, target) in enumerate(pairs)]
    assert client.put(f"/api/canvas/workflows/{w['id']}", json={'title': '连接', 'revision': 1, 'document': doc}).status_code == 400


@pytest.mark.parametrize('mutation', ['wrong_kind', 'wrong_candidate_kind', 'missing_selected', 'missing_asset', 'not_candidate'])
def test_selected_output_consistency(client, mutation):
    w = create(client)
    asset = upload(client, w)
    node = {'id': 'n', 'type': 'image', 'x': 0, 'y': 0, 'asset': asset, 'candidates': [asset], 'selectedCandidateId': asset['id']}
    if mutation == 'wrong_kind': node['type'] = 'audio'
    if mutation == 'wrong_candidate_kind': node.update(type='video', asset=None, selectedCandidateId=None)
    if mutation == 'missing_selected': node['selectedCandidateId'] = None
    if mutation == 'missing_asset': node['asset'] = None
    if mutation == 'not_candidate': node['candidates'] = []
    doc = w['document']
    doc['nodes'] = [node]
    assert client.put(f"/api/canvas/workflows/{w['id']}", json={'title': '输出', 'revision': 1, 'document': doc}).status_code == 400


def test_application_auth_guards_canvas_and_both_asset_scopes(client, monkeypatch):
    import app as application
    w = create(client)
    asset = upload(client, w)
    library = client.post(f"/api/canvas/projects/{w['project_id']}/assets", data={'file': (io.BytesIO(png()), 'library.png')}).json['asset']
    monkeypatch.setattr(application, 'AUTH_CONFIG', {'username': 'canvas-test'})
    real = application.app.test_client()
    for url in ('/api/canvas/projects', f"/api/canvas/workflows/{w['id']}", asset['url'], library['url']):
        assert real.get(url).status_code == 401
    assert real.post('/api/canvas/projects', json={'title': 'blocked'}).status_code == 401
    with real.session_transaction() as session:
        session['logged_in'] = True
    assert real.get('/api/canvas/projects').status_code == 200
    assert real.get(f"/api/canvas/workflows/{w['id']}").json['workflow']['id'] == w['id']
    assert real.get(asset['url']).data == png()
    assert real.get(library['url']).data == png()
