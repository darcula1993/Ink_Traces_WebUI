import io

import pytest
import requests

import app as application
import storage
import tasks as task_db
import worker
from test_generation import _png_bytes


@pytest.fixture
def cupsy(monkeypatch):
    monkeypatch.setattr(application, 'CUPSY_VIDEO_CONFIG', {
        'api_key': 'test-key', 'endpoint': 'https://cupsy.invalid',
        'source_base_url': 'https://source.invalid',
    })
    return application.app.test_client()


class Response:
    def __init__(self, code=200, payload=None, content=b'', headers=None):
        self.status_code = code
        self.payload = payload
        self.content = content
        self.headers = headers or {}
        self.text = 'response'

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError('download failed')

    def iter_content(self, chunk_size=1024 * 1024):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def submit(client, **extra):
    return client.post('/api/generate', json={
        'provider': 'cupsy', 'prompt': 'a flower', 'aspect_ratio': '16:9',
        'resolution': '2K', **extra,
    })


def test_provider_reuses_shared_key(cupsy):
    providers = cupsy.get('/api/provider').get_json()['providers']
    assert providers['cupsy']['available'] is True
    assert providers['cupsy']['model'] == 'seedream-5.0-pro'
    assert 'test-key' not in str(providers)
    assert cupsy.post('/api/provider', json={'provider': 'cupsy'}).status_code == 200


@pytest.mark.parametrize(('resolution', 'ratio', 'size'), [
    ('1K', '16:9', '1280x720'), ('2K', '4:3', '2304x1728'),
    ('2K', '9:16', '1440x2560'),
])
def test_presets(cupsy, resolution, ratio, size):
    response = submit(cupsy, resolution=resolution, aspect_ratio=ratio)
    assert response.status_code == 202
    task = task_db.get_task(response.get_json()['task_id'])
    assert task['params']['size'] == size
    assert task['params']['model'] == 'seedream-5.0-pro'


def test_custom_size_and_unsupported_options(cupsy):
    response = submit(cupsy, aspect_ratio='custom', custom_width=1536, custom_height=1024,
                      resolution=None)
    assert response.status_code == 202
    params = task_db.get_task(response.get_json()['task_id'])['params']
    assert params['size'] == '1536x1024'
    assert params['custom_width'] == 1536
    assert 'resolution' not in params
    for options in [
        {'aspect_ratio': 'auto'}, {'resolution': '4K'}, {'output_format': 'webp'},
        {'background': 'transparent'},
        {'aspect_ratio': 'custom', 'custom_width': 1537, 'custom_height': 1024},
        {'aspect_ratio': 'custom', 'custom_width': 512, 'custom_height': 512},
        {'aspect_ratio': 'custom', 'custom_width': 4096, 'custom_height': 4096},
        {'aspect_ratio': 'custom', 'custom_width': 8192, 'custom_height': 128},
    ]:
        assert submit(cupsy, **options).status_code == 400


def test_replay_after_202_preserves_request_and_original_bytes(cupsy, monkeypatch):
    task_id = submit(cupsy).get_json()['task_id']
    calls = []
    raw = _png_bytes()

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return Response(202, {'id': 'task_remote', 'status': 'processing'}, headers={'Retry-After': '20'})
        return Response(payload={'data': [{'url': 'https://cdn.invalid/original.png'}]})

    def get(url, **kwargs):
        assert kwargs['headers'] == {}
        return Response(content=raw)

    monkeypatch.setattr(application.HTTP, 'post', post)
    monkeypatch.setattr(application.HTTP, 'get', get)
    claimed = task_db.claim_next_task('test')
    with application.app.app_context():
        worker.Worker()._process_image(claimed)
    task = task_db.get_task(task_id)
    assert task['status'] == 'processing'
    assert task['external_task_id'] == 'task_remote'
    assert task['params']['_cupsy_request']['size'] == '2560x1440'
    task_db.update_task(task_id, next_run_at=task_db.utcnow())
    claimed = task_db.claim_next_task('test')
    with application.app.app_context():
        worker.Worker()._process_image(claimed)
    assert calls[0] == calls[1]
    assert calls[0][1]['headers']['Idempotency-Key'].startswith(f'nanobanana-image-{task_id}-')
    task = task_db.get_task(task_id)
    assert task['status'] == 'succeeded'
    outputs = [a for a in task_db.list_assets(task_id) if a['kind'] == 'output_image']
    with open(outputs[0]['path'], 'rb') as handle:
        assert handle.read() == raw
    assert task_db.list_provider_assets('cupsy') == []


def test_references_imported_as_assets_wait_until_ready(cupsy, monkeypatch):
    uploaded = cupsy.post('/api/workspace/assets/img_tabs', data={
        'file': (io.BytesIO(_png_bytes()), 'ref.png'),
    }).get_json()['asset']
    task_id = submit(cupsy, image_urls=[uploaded['url']]).get_json()['task_id']
    links = task_db.list_task_provider_assets(task_id)
    assert len(links) == 1
    with application.app.app_context():
        payload, code = application.execute_image_task(task_id)
    assert code == 202 and payload['pending']
    task_db.update_provider_asset(links[0]['id'], status='active', asset_uri='asset://asset_image')

    def post(url, **kwargs):
        assert kwargs['json']['image'] == ['asset://asset_image']
        assert 'inlineData' not in str(kwargs['json'])
        return Response(202, {'id': 'task_remote'})

    monkeypatch.setattr(application.HTTP, 'post', post)
    with application.app.app_context():
        assert application.execute_image_task(task_id)[1] == 202
    detail = cupsy.get(f'/api/tasks/{task_id}').get_json()['task']
    assert len(detail['result']['local_refs']) == 1


def test_transport_timeout_is_rescheduled_with_same_key(cupsy, monkeypatch):
    task_id = submit(cupsy).get_json()['task_id']
    monkeypatch.setattr(application.HTTP, 'post', lambda *a, **k: (_ for _ in ()).throw(requests.ReadTimeout('timeout')))
    with application.app.app_context():
        worker.Worker()._process_image(task_db.claim_next_task('test'))
    task = task_db.get_task(task_id)
    assert task['status'] == 'processing'
    assert task['params']['_cupsy_request']


def test_failed_asset_does_not_submit(cupsy, monkeypatch):
    response = cupsy.post('/api/generate', data={
        'provider': 'cupsy', 'prompt': 'flower', 'images': (io.BytesIO(_png_bytes()), 'ref.png'),
    })
    task_id = response.get_json()['task_id']
    asset = task_db.list_task_provider_assets(task_id)[0]
    task_db.update_provider_asset(asset['id'], status='failed', error='import failed')
    with application.app.app_context():
        payload, _ = application.execute_image_task(task_id)
    assert not payload['success']
    assert task_db.get_task(task_id)['status'] == 'failed'


def test_cancel_between_polls_finishes_locally_without_video_delete(cupsy, monkeypatch):
    task_id = submit(cupsy).get_json()['task_id']
    task_db.update_task(task_id, status='processing', external_task_id='task_remote')
    def unexpected_delete(*args, **kwargs):
        pytest.fail('Image cancellation must not call the video deletion endpoint')
    monkeypatch.setattr(application.HTTP, 'delete', unexpected_delete)
    assert cupsy.post(f'/api/tasks/{task_id}/cancel').status_code == 200
    assert task_db.get_task(task_id)['status'] == 'cancelled'


def test_retry_reimports_references_and_uses_a_new_request(cupsy):
    response = cupsy.post('/api/generate', data={
        'provider': 'cupsy', 'prompt': 'flower', 'images': (io.BytesIO(_png_bytes()), 'ref.png'),
    })
    original_id = response.get_json()['task_id']
    params = task_db.get_task(original_id)['params']
    params.update(_cupsy_request={'image': ['asset://old']}, _cupsy_idempotency_key='old-key')
    task_db.update_task(original_id, params=params)
    task_db.fail_task(original_id, 'test failure')
    retried = cupsy.post(f'/api/tasks/{original_id}/retry')
    assert retried.status_code == 202
    retry_id = retried.get_json()['task_id']
    assert '_cupsy_request' not in task_db.get_task(retry_id)['params']
    assert '_cupsy_idempotency_key' not in task_db.get_task(retry_id)['params']
    assert len(task_db.list_task_provider_assets(retry_id)) == 1
