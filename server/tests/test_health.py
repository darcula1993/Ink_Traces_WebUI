import os
import io
import json
import zipfile

from PIL import Image

import app as application
import storage
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


def test_removed_video_prompt_tools_are_not_routable(monkeypatch):
    monkeypatch.setattr(application, 'AUTH_CONFIG', {})
    routes = {rule.rule for rule in application.app.url_map.iter_rules()}

    assert '/api/video/optimize-prompt' not in routes
    assert '/api/video/prompt-agent/session' not in routes
    assert '/api/video/prompt-agent/message' not in routes


def test_task_favorite_api():
    task_id = task_db.create_task('image', 'favorite me', {})
    client = application.app.test_client()

    response = client.patch(f'/api/tasks/{task_id}/favorite', json={'favorite': True})
    assert response.status_code == 200
    assert response.get_json()['favorite'] is True
    assert task_db.get_task(task_id)['favorite'] is True


def test_task_bulk_delete_api():
    first = task_db.create_task('image', 'first', {})
    second = task_db.create_task('video', 'second', {})
    client = application.app.test_client()

    task_db.complete_task(second, {'local_video': '/api/tasks/2/file/video.mp4'})
    active = client.get('/api/tasks?active=true').get_json()
    assert active['total'] == 1
    assert [task['id'] for task in active['tasks']] == [first]
    searched = client.get('/api/tasks?active=true&q=first').get_json()
    assert searched['total'] == 1
    selection = client.get('/api/tasks/selection?view=active').get_json()
    assert selection['ids'] == [first]
    searched_selection = client.get('/api/tasks/selection?view=all&q=second').get_json()
    assert searched_selection['ids'] == [second]

    response = client.post('/api/tasks/bulk-delete', json={'ids': [first, second, first]})
    assert response.status_code == 200
    assert response.get_json()['deleted'] == 2
    assert response.get_json()['deleted_ids'] == [first, second]
    assert task_db.get_task(first)['deleted_at'] is not None
    assert task_db.get_task(second)['deleted_at'] is not None
    assert client.get('/api/tasks').get_json()['total'] == 0
    trash = client.get('/api/tasks?deleted=true').get_json()
    assert trash['total'] == 2

    restored = client.post('/api/tasks/bulk-restore', json={'ids': [second]})
    assert restored.status_code == 200
    assert restored.get_json()['restored_ids'] == [second]
    assert task_db.get_task(second)['deleted_at'] is None

    permanent = client.post('/api/tasks/bulk-delete', json={'ids': [first], 'permanent': True})
    assert permanent.status_code == 200
    assert permanent.get_json()['deleted_ids'] == [first]
    assert task_db.get_task(first) is None

    invalid = client.post('/api/tasks/bulk-delete', json={'ids': []})
    assert invalid.status_code == 400


def test_task_status_batch_and_filtered_navigation():
    first = task_db.create_task('image', 'alpha landscape', {}, provider='ark')
    second = task_db.create_task('image', 'beta portrait', {}, provider='vertex')
    third = task_db.create_task('image', 'gamma portrait', {}, provider='ark')
    task_db.update_task(second, status='processing', progress=37)
    client = application.app.test_client()

    statuses = client.get(f'/api/tasks/status?ids={third},{second},{third},999999').get_json()
    assert [task['id'] for task in statuses['tasks']] == [third, second]
    assert statuses['tasks'][1]['progress'] == 37
    assert 'params' not in statuses['tasks'][1]
    assert statuses['missing_ids'] == [999999]

    navigation = client.get(
        f'/api/tasks/{second}/navigation?view=all&q=portrait&sort=newest'
    ).get_json()['navigation']
    assert navigation == {
        'position': 2,
        'total': 2,
        'previous_id': third,
        'next_id': None,
        'first_id': third,
        'last_id': second,
    }
    assert first not in navigation.values()


def test_task_advanced_filters_are_consistent_across_gallery_actions():
    old_ark = task_db.create_task('video', 'old ark task', {'model': 'seedance-a'}, provider='ark')
    recent_ark = task_db.create_task('video', 'recent ark task', {'model': 'seedance-a'}, provider='ark')
    task_db.create_task('video', 'cupsy task', {'model': 'seedance-b'}, provider='cupsy')
    task_db.create_task('image', 'image task', {'model': 'seedream-a'}, provider='ark')
    task_db.update_task(old_ark, status='succeeded')
    task_db.update_task(recent_ark, status='succeeded')
    task_db.get_db().execute(
        "UPDATE tasks SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
        (old_ark,),
    )
    task_db.get_db().commit()
    client = application.app.test_client()
    params = (
        'type=video&provider=ark&model=seedance-a&status=succeeded'
        '&created_after=2025-01-01T00:00:00Z'
    )

    listed = client.get(f'/api/tasks?{params}').get_json()
    assert listed['total'] == 1
    assert [task['id'] for task in listed['tasks']] == [recent_ark]
    selected = client.get(f'/api/tasks/selection?view=all&{params}').get_json()
    assert selected['ids'] == [recent_ark]
    navigation = client.get(f'/api/tasks/{recent_ark}/navigation?view=all&{params}').get_json()['navigation']
    assert navigation['total'] == 1
    assert navigation['position'] == 1

    options = client.get('/api/tasks/filter-options?type=video').get_json()
    assert options['providers'] == ['ark', 'cupsy']
    assert options['models'] == ['seedance-a', 'seedance-b']
    assert client.get('/api/tasks?created_after=not-a-date').status_code == 400


def test_favorite_group_api_filters_and_keeps_ungrouped_favorites():
    client = application.app.test_client()
    grouped = task_db.create_task('image', 'grouped task', {})
    ungrouped = task_db.create_task('image', 'ungrouped task', {})
    task_db.set_task_favorite(ungrouped, True)

    created = client.post('/api/favorite-groups', json={'name': 'Concept art', 'color': 'cyan'})
    assert created.status_code == 201
    group = created.get_json()['group']

    assigned = client.patch(
        f'/api/tasks/{grouped}/favorite-groups',
        json={'group_ids': [group['id']]},
    )
    assert assigned.status_code == 200
    assert assigned.get_json()['task']['favorite'] is True
    assert assigned.get_json()['task']['favorite_groups'][0]['name'] == 'Concept art'

    filtered = client.get(f'/api/tasks?favorite=true&favorite_group={group["id"]}').get_json()
    assert filtered['total'] == 1
    assert filtered['tasks'][0]['id'] == grouped
    selection = client.get(
        f'/api/tasks/selection?view=favorite&favorite_group={group["id"]}'
    ).get_json()
    assert selection['ids'] == [grouped]
    assert client.get('/api/tasks?favorite=true&ungrouped=true').get_json()['total'] == 1

    deleted = client.delete(f'/api/favorite-groups/{group["id"]}')
    assert deleted.status_code == 200
    assert task_db.get_task(grouped)['favorite'] is True
    assert task_db.get_task(grouped)['favorite_groups'] == []


def test_bulk_download_builds_unique_task_paths():
    first = task_db.create_task('image', 'first', {})
    second = task_db.create_task('image', 'second', {})
    originals = {}
    for task_id in (first, second):
        output_dir = storage.task_output_dir('image', task_id)
        path = os.path.join(output_dir, 'image_0.png')
        Image.new('RGB', (2, 2), (task_id, 20, 30)).save(path, format='PNG')
        with open(path, 'rb') as source:
            originals[task_id] = source.read()
        storage.register_file(task_id, 'output_image', path, 'image/png')
        task_db.complete_task(task_id, {'local_images': [f'/api/tasks/{task_id}/file/image_0.png']}, output_dir)

    response = application.app.test_client().post(
        '/api/tasks/bulk-download', json={'ids': [first, second]},
    )
    assert response.status_code == 200
    assert response.mimetype == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        names = archive.namelist()
        assert len(names) == 2
        for task_id, prompt in ((first, 'first'), (second, 'second')):
            name = next(name for name in names if name.startswith(
                f'image-task-{task_id}/ink-traces-image-task-{task_id}-'
            ))
            assert name.endswith('-output-01.png')
            with Image.open(io.BytesIO(archive.read(name))) as image:
                metadata = json.loads(image.text['ink_traces'])
            assert metadata['prompt'] == prompt
            assert 'provider' not in metadata
            assert 'model' not in metadata

    raw_response = application.app.test_client().post(
        '/api/tasks/bulk-download', json={'ids': [first, second], 'raw': True},
    )
    assert raw_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(raw_response.data)) as archive:
        names = archive.namelist()
        assert len(names) == 2
        for task_id in (first, second):
            name = next(name for name in names if name.startswith(f'image-task-{task_id}/'))
            assert name.endswith('-output-01-original.png')
            assert archive.read(name) == originals[task_id]


def test_workspace_state_externalizes_data_urls():
    client = application.app.test_client()
    data_url = (
        'data:image/png;base64,'
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
    )
    response = client.put('/api/workspace/state/img_tabs', json={
        'value': [{'id': 1, 'uploadedImages': [{'preview': data_url}]}],
    })
    assert response.status_code == 200
    preview = response.get_json()['state']['value'][0]['uploadedImages'][0]['preview']
    assert preview.startswith('/api/workspace/assets/img_tabs/')

    restored = client.get('/api/workspace/state/img_tabs').get_json()['state']['value']
    assert restored[0]['uploadedImages'][0]['preview'] == preview

    preferences = client.put('/api/workspace/state/gallery_preferences', json={
        'value': {'cardSize': 'large', 'cardDetails': 'clean'},
    })
    assert preferences.status_code == 200
    assert preferences.get_json()['state']['value']['cardSize'] == 'large'
