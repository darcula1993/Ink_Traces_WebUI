import gzip
import io
import json
import os

from PIL import Image

import app as application
import storage
import tasks as task_db
from test_generation import _rgba_png_bytes


def test_task_summaries_and_statuses_do_not_ship_full_inputs():
    prompt = 'test unicode 提示词 ' * 1000
    task_id = task_db.create_task('image', prompt, {
        'model': 'seedream', 'resolution': '2K', 'private_input': 'x' * 50000,
        '_cupsy_request': {'prompt': prompt},
    })
    task_db.complete_task(task_id, {
        'local_images': ['/result.png'], 'local_thumbnails': ['/thumb.webp'],
        'source_urls': ['https://private.invalid/result'], 'thinking': 'x' * 50000,
    })
    client = application.app.test_client()
    response = client.get('/api/tasks?type=image')
    summary = response.get_json()['tasks'][0]
    assert summary['summary'] is True
    assert summary['prompt'] == prompt[:200]
    assert summary['prompt_truncated']
    assert summary['params']['model'] == 'seedream'
    assert '_cupsy_request' not in summary['params']
    assert 'source_urls' not in summary['result']
    assert len(response.data) < 3000
    status = client.get(f'/api/tasks/status?ids={task_id}').get_json()['tasks'][0]
    assert 'thinking' not in status['result']
    assert 'params' not in status
    detail = client.get(f'/api/tasks/{task_id}').get_json()['task']
    assert detail['prompt'] == prompt
    assert detail['params']['private_input'] == 'x' * 50000


def test_gzip_json_negotiation_and_static_cache(monkeypatch, tmp_path):
    task_db.create_task('image', 'compress me ' * 300, {})
    task_db.create_task('image', 'compress me too ' * 300, {})
    client = application.app.test_client()
    plain = client.get('/api/tasks')
    packed = client.get('/api/tasks', headers={'Accept-Encoding': 'gzip'})
    assert packed.headers['Content-Encoding'] == 'gzip'
    assert gzip.decompress(packed.data) == plain.data
    assert len(packed.data) < len(plain.data)
    assert 'Accept-Encoding' in packed.headers['Vary']
    disabled = client.get('/api/tasks', headers={'Accept-Encoding': 'gzip;q=0'})
    assert 'Content-Encoding' not in disabled.headers

    root = tmp_path / 'client'
    (root / 'assets').mkdir(parents=True)
    (root / 'index.html').write_text('index')
    script = 'const answer = 42;\n' * 1000
    (root / 'assets' / 'bundle.js').write_text(script)
    monkeypatch.setattr(application, 'CLIENT_DIST_DIR', str(root))
    packed = client.get('/assets/bundle.js', headers={'Accept-Encoding': 'gzip'})
    assert gzip.decompress(packed.data).decode() == script
    assert packed.headers['ETag'].startswith('W/')
    assert client.get('/assets/bundle.js', headers={
        'Accept-Encoding': 'gzip', 'If-None-Match': packed.headers['ETag'],
    }).status_code == 304
    ranged = client.get('/assets/bundle.js', headers={'Accept-Encoding': 'gzip', 'Range': 'bytes=0-9'})
    assert ranged.status_code == 206
    assert 'Content-Encoding' not in ranged.headers


def test_workspace_upload_returns_original_metadata_and_thumbnail(monkeypatch):
    client = application.app.test_client()
    response = client.post('/api/workspace/assets/img_tabs', data={
        'file': (io.BytesIO(_rgba_png_bytes((640, 480))), 'alpha.png'),
    })
    asset = response.get_json()['asset']
    assert asset['width'] == 640 and asset['height'] == 480 and asset['has_alpha'] is True
    thumb = client.get(asset['thumbnail_url'])
    assert thumb.status_code == 200
    with Image.open(io.BytesIO(thumb.data)) as image:
        assert image.size == (320, 240)
        assert image.format == 'WEBP'
    monkeypatch.setattr(storage, 'cleanup_workspace_assets', lambda *_: (_ for _ in ()).throw(AssertionError('cleanup on request')))
    assert client.put('/api/workspace/state/img_tabs', json={'value': [{'prompt': 'typing'}]}).status_code == 200


def test_asset_pagination_status_and_cached_thumbnails(tmp_path):
    path = tmp_path / 'reference.png'
    path.write_bytes(_rgba_png_bytes((640, 480)))
    ids = []
    for i in range(35):
        asset = task_db.create_provider_asset('cupsy', 'image', f'hash-{i}', 'ref.png',
                                              'image/png', path.stat().st_size, str(path))
        ids.append(asset['id'])
    client = application.app.test_client()
    page = client.get('/api/cupsy/assets?limit=30').get_json()
    assert page['total'] == 35 and page['has_more'] is True
    assert len(page['assets']) == 30
    last = client.get('/api/cupsy/assets?limit=30&offset=30').get_json()
    assert len(last['assets']) == 5 and last['has_more'] is False
    status = client.get(f'/api/cupsy/assets?ids={ids[0]},99999').get_json()
    assert [asset['id'] for asset in status['assets']] == [ids[0]]
    assert status['missing_ids'] == [99999]
    url = page['assets'][0]['thumbnail_url']
    first = client.get(url)
    modified = os.stat(str(path) + '.thumb.webp').st_mtime_ns
    assert client.get(url).data == first.data
    assert os.stat(str(path) + '.thumb.webp').st_mtime_ns == modified


def test_generated_download_is_streamed_and_preserves_original(monkeypatch, tmp_path):
    raw = _rgba_png_bytes((640, 480))
    class Stream:
        status_code = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def raise_for_status(self):
            pass
        @property
        def content(self):
            raise AssertionError('Full response buffering must not be used')
        def iter_content(self, chunk_size):
            yield raw[:100]
            yield raw[100:]
    def get(url, **kwargs):
        assert kwargs['stream'] is True
        assert kwargs['headers'] == {}
        return Stream()
    monkeypatch.setattr(application.HTTP, 'get', get)
    path, mime = application._save_generated_image({'url': 'https://cdn.invalid/image'}, str(tmp_path), 'image_0')
    assert mime == 'image/png'
    with open(path, 'rb') as handle:
        assert handle.read() == raw
    assert not list(tmp_path.glob('*.download'))


def test_claim_pool_filters_only_eligible_types():
    image_id = task_db.create_task('image', 'image', {}, provider='ark')
    video_id = task_db.create_task('video', 'video', {}, provider='cupsy')
    assert task_db.claim_next_task('image-worker', task_types=('image', 'layer'))['id'] == image_id
    assert task_db.claim_next_task('poll-worker', task_types=('video', 'audio'))['id'] == video_id
    assert task_db.claim_next_task('empty', task_types=()) is None


def test_invalid_cupsy_output_fails_instead_of_polling_forever(monkeypatch):
    task_id = task_db.create_task('image', 'test', {}, provider='cupsy')
    monkeypatch.setattr(application, '_generate_cupsy_image', lambda task: ({
        'success': True, 'images': ['data:image/png;base64,bm90LWFuLWltYWdl'],
    }, 200))
    with application.app.app_context():
        payload, status = application.execute_image_task(task_id)
    assert status == 502
    assert payload['retryable'] is False
    assert task_db.get_task(task_id)['status'] == 'failed'
