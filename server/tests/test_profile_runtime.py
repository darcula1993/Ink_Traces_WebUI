import io
from concurrent.futures import ThreadPoolExecutor
import json
import threading

from PIL import Image
import pytest
import app as application
import tasks
import profile_runtime as runtime
from provider_profiles import init_profiles_db, save_profile, load_profile


@pytest.fixture(autouse=True)
def profiles():
    init_profiles_db()


def make_profile(kind='image', adapter='ark', name='one'):
    return save_profile({'name': name, 'kind': kind, 'adapter': adapter, 'enabled': True,
                         'settings': {'endpoint': f'https://{name}.invalid', 'model': ('seedream-5.0-pro' if adapter == 'cupsy' else 'seedream-5-0-pro') if kind == 'image' else ('seed-audio-1.0' if kind == 'audio' else 'seedance-2.5' if adapter == 'cupsy' else 'seedance-2.0'), **({'source_base_url': 'https://source.invalid'} if adapter == 'cupsy' else {})}, 'api_key': f'fake-{name}'})


def test_contexts_are_thread_local_and_task_records_exclude_credentials():
    a, b = make_profile(name='one'), make_profile(name='two')
    barrier = threading.Barrier(2)
    def read(profile):
        try:
            with runtime.profile_scope(load_profile(profile['id'], profile['revision'])):
                barrier.wait()
                key = application.API_PROVIDERS['ark'].get('api_key')
                task_id = tasks.create_task('image', 'test', {}, provider='ark')
                params = tasks.get_task(task_id)['params']
                return key, params
        finally:
            tasks.close_db()
    with ThreadPoolExecutor(2) as pool:
        x, y = list(pool.map(read, [a, b]))
    assert x[0] == 'fake-one' and y[0] == 'fake-two'
    assert x[1] == {'profile_id': a['id'], 'profile_revision': 1}
    assert y[1] == {'profile_id': b['id'], 'profile_revision': 1}
    assert runtime.current_profile() is None


def test_image_submission_freezes_profile_and_model():
    p = make_profile(adapter='ark')
    client = application.app.test_client()
    result = client.post('/api/generate', json={'profile_id': p['id'], 'provider': 'ark', 'prompt': 'draw', 'aspect_ratio': '1:1', 'resolution': '1K'})
    assert result.status_code == 202
    task = tasks.get_task(result.json['task_id'])
    assert task['params']['profile_revision'] == 1
    assert task['params']['model'] == 'seedream-5-0-pro'
    assert 'fake-one' not in json.dumps(task)
    assert runtime.current_profile() is None


def test_unsupported_adapter_profile_is_refused_for_generation(monkeypatch):
    import provider_profiles
    with monkeypatch.context() as injected:  # a stored row whose adapter is not supported
        injected.setitem(provider_profiles.KINDS, 'image', {'acme', 'ark', 'cupsy'})
        p = make_profile(adapter='acme', name='unsupported-acme')
    client = application.app.test_client()
    before = tasks.list_task_ids()
    result = client.post('/api/generate', json={'profile_id': p['id'], 'provider': 'acme', 'prompt': 'draw', 'aspect_ratio': '1:1', 'resolution': '1K'})
    assert result.status_code == 409 and '不受支持' in result.json['error']
    assert tasks.list_task_ids() == before
    with pytest.raises(provider_profiles.ProfileError, match='不受支持'):
        provider_profiles.load_profile(p['id'], kind='image', require_enabled=True)
    with pytest.raises(provider_profiles.ProfileError):
        make_profile(adapter='acme', name='new-acme')


def test_submission_rejects_kind_and_adapter_mismatch():
    p = make_profile()
    client = application.app.test_client()
    assert client.post('/api/video/generate', json={'profile_id': p['id'], 'provider': 'ark'}).status_code == 400
    assert client.post('/api/generate', json={'profile_id': p['id'], 'provider': 'cupsy'}).status_code == 400


class Response:
    status_code = 200
    text = '{"id":"external","status":"running"}'
    def json(self):
        return json.loads(self.text)


def test_video_poll_uses_original_revision_after_change_and_disable(monkeypatch):
    p = make_profile(kind='video')
    calls = []
    monkeypatch.setattr(application.HTTP, 'post', lambda url, **kwargs: calls.append((url, kwargs)) or Response())
    client = application.app.test_client()
    result = client.post('/api/video/generate', json={'profile_id': p['id'], 'provider': 'ark', 'prompt': 'move', 'model': 'seedance-2.0', 'duration': 5, 'ratio': '16:9', 'resolution': '720p'})
    assert result.status_code in (200, 202), result.json
    task_id = result.json['db_task_id']
    save_profile({'revision': p['revision'], 'enabled': False, 'api_key': 'fake-new', 'settings': {'endpoint': 'https://changed.invalid'}}, p['id'])
    monkeypatch.setattr(application.HTTP, 'get', lambda url, **kwargs: calls.append((url, kwargs)) or Response())
    with application.app.app_context():
        application.poll_video_task_once(task_id)
    assert all(url.startswith('https://one.invalid/') for url, _ in calls)
    assert all(kwargs['headers']['Authorization'] == 'Bearer fake-one' for _, kwargs in calls)
    assert client.post('/api/video/generate', json={'profile_id': p['id'], 'provider': 'ark'}).status_code == 409


def test_cupsy_assets_separate_accounts_and_restore_context(tmp_path, monkeypatch):
    a, b = make_profile(adapter='cupsy', name='one'), make_profile(adapter='cupsy', name='two')
    image = tmp_path / 'image.png'
    Image.new('RGB', (2, 2)).save(image)
    assets = []
    for profile in (a, b):
        with runtime.profile_scope(load_profile(profile['id'], 1)):
            assets.append(application.create_cupsy_asset_from_path(str(image), 'image'))
    assert assets[0]['id'] != assets[1]['id']
    assert assets[0]['local_path'] != assets[1]['local_path']
    assert runtime.asset_selection(assets[0])['api_key'] == 'fake-one'
    assert runtime.asset_selection(assets[1])['api_key'] == 'fake-two'
    assert runtime.current_profile() is None


def test_image_worker_and_explicit_retry_keep_old_account(monkeypatch):
    p = make_profile()
    client = application.app.test_client()
    response = client.post('/api/generate', json={'profile_id': p['id'], 'provider': 'ark', 'prompt': 'test', 'aspect_ratio': '1:1'})
    task_id = response.json['task_id']
    save_profile({'revision': 1, 'api_key': 'fake-replacement', 'enabled': False}, p['id'])  # secret-scan: allow (test fixture)
    observed = []
    def generate(*args, **kwargs):
        observed.append((args[6].get('api_key'), args[6].get('endpoint')))
        return {'success': False, 'error': 'mock failure'}, 400
    monkeypatch.setattr(application, '_generate_ark_image', generate)
    with application.app.app_context():
        application.execute_image_task(task_id)
    retry = client.post(f'/api/tasks/{task_id}/retry')
    assert retry.status_code in (200, 202)
    retried = tasks.get_task(retry.json['task_id'])
    assert retried['params']['profile_revision'] == 1
    with application.app.app_context():
        application.execute_image_task(retried['id'])
    assert observed == [('fake-one', 'https://one.invalid')] * 2


@pytest.mark.parametrize('kind', ['video', 'audio'])
def test_cupsy_submit_and_poll_apply_profile_timeouts(kind, monkeypatch):
    p = make_profile(kind=kind, adapter='cupsy')
    save_profile({'revision': 1, 'settings': {'upload_timeout_seconds': 17, 'request_timeout_seconds': 83, 'poll_timeout_seconds': 29}}, p['id'])
    profile = load_profile(p['id'], 2)
    with runtime.profile_scope(profile):
        task_id = tasks.create_task(kind, 'test', {'model': profile['settings']['model']}, provider='cupsy')
    calls = []
    monkeypatch.setattr(application.HTTP, 'post', lambda url, **kw: calls.append(('post', kw)) or Response())
    monkeypatch.setattr(application.HTTP, 'get', lambda url, **kw: calls.append(('get', kw)) or Response())
    poll = application.poll_video_task_once if kind == 'video' else application.poll_audio_task_once
    with application.app.app_context():
        poll(task_id)
        poll(task_id)
    assert calls[0][1]['timeout'] == (17, 83)
    assert calls[-1][0] == 'get'
    assert calls[-1][1]['timeout'] == (10, 29)


def test_asset_poll_and_media_download_apply_original_profile_timeouts(tmp_path, monkeypatch):
    p = make_profile(adapter='cupsy')
    save_profile({'revision': 1, 'settings': {'upload_timeout_seconds': 19, 'request_timeout_seconds': 71, 'poll_timeout_seconds': 23, 'download_timeout_seconds': 101}}, p['id'])
    profile = load_profile(p['id'], 2)
    source = tmp_path / 'source.png'
    Image.new('RGB', (2, 2)).save(source)
    with runtime.profile_scope(profile):
        asset = application.create_cupsy_asset_from_path(str(source), 'image')
    calls = []
    monkeypatch.setattr(application.HTTP, 'post', lambda url, **kw: calls.append(('post', kw)) or Response())
    monkeypatch.setattr(application.HTTP, 'get', lambda url, **kw: calls.append(('get', kw)) or Response())
    with application.app.app_context():
        application.process_cupsy_asset_once(asset['id'])
        application.process_cupsy_asset_once(asset['id'])
    assert calls[0][1]['timeout'] == (19, 71)
    assert calls[1][1]['timeout'] == (10, 23)
    class Download(Response):
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, **kwargs): yield source.read_bytes()
    monkeypatch.setattr(application.HTTP, 'get', lambda url, **kw: calls.append(('download', kw)) or Download())
    with runtime.profile_scope(profile):
        error = application._download_cupsy_output({}, 'https://one.invalid', 'video', '/output', str(tmp_path / 'download.mp4'))
        assert error is None
        application._save_generated_image({'url': 'https://cdn.invalid/result.png'}, str(tmp_path), 'generated')
    assert all(kw['timeout'] == (10, 101) for method, kw in calls if method == 'download')


def test_worker_exception_keeps_profile_retry_budget(monkeypatch):
    import worker
    p = make_profile(kind='video')
    save_profile({'revision': 1, 'settings': {'poll_max_attempts': 1}}, p['id'])
    with runtime.profile_scope(load_profile(p['id'], 2)):
        task_id = tasks.create_task('video', 'test', {}, provider='ark')
    tasks.update_task(task_id, attempt_count=1)
    instance = worker.Worker()
    monkeypatch.setattr(instance, '_process_video', lambda task: (_ for _ in ()).throw(RuntimeError('mock failure')))
    instance.process(tasks.get_task(task_id))
    assert tasks.get_task(task_id)['status'] == 'failed'


def test_small_profile_timeouts_are_not_clamped_to_legacy_minimum():
    p = make_profile()
    save_profile({'revision': 1, 'settings': {'upload_timeout_seconds': 7, 'request_timeout_seconds': 11}}, p['id'])
    with runtime.profile_scope(load_profile(p['id'], 2)):
        assert application.resolve_ark_timeouts(application.API_PROVIDERS['ark']) == (7, 11)
