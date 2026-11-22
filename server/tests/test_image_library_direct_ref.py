import io
import os
import wave
from PIL import Image

import app as application
import media_library
import storage
import tasks


def _png_bytes(color=(30, 120, 200), size=(24, 16), alpha=False):
    buf = io.BytesIO()
    mode = 'RGBA' if alpha else 'RGB'
    pixel = (*color, 128) if alpha else color
    Image.new(mode, size, pixel).save(buf, format='PNG')
    return buf.getvalue()


def _jpeg_bytes(color=(180, 90, 40), size=(32, 20)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='JPEG')
    return buf.getvalue()


def _wav_bytes():
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b'\x00\x00' * 1600)
    return buf.getvalue()


def _configure_ark(monkeypatch, model='seedream-5-0-pro'):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'test-key',
        'endpoint': 'https://provider.invalid',
        'model': model,
    })


def test_media_metadata_endpoint_reports_alpha_dimensions_and_guards():
    client = application.app.test_client()
    opaque, _ = media_library.save_upload(io.BytesIO(_png_bytes(alpha=False)), 'opaque.png')
    alpha, _ = media_library.save_upload(io.BytesIO(_png_bytes(size=(40, 30), alpha=True)), 'alpha.png')
    jpg, _ = media_library.save_upload(io.BytesIO(_jpeg_bytes()), 'photo.jpg')
    audio, _ = media_library.save_upload(io.BytesIO(_wav_bytes()), 'tone.wav')

    r_opaque = client.get(f"/api/canvas/media/{opaque['id']}/metadata")
    assert r_opaque.status_code == 200
    assert r_opaque.get_json()['metadata'] == {
        'width': 24, 'height': 16, 'pixels': 384, 'has_alpha': False, 'mime_type': 'image/png',
    }

    r_alpha = client.get(f"/api/canvas/media/{alpha['id']}/metadata")
    assert r_alpha.status_code == 200
    assert r_alpha.get_json()['metadata'] == {
        'width': 40, 'height': 30, 'pixels': 1200, 'has_alpha': True, 'mime_type': 'image/png',
    }

    r_jpg = client.get(f"/api/canvas/media/{jpg['id']}/metadata")
    assert r_jpg.status_code == 200
    assert r_jpg.get_json()['metadata']['has_alpha'] is False
    assert r_jpg.get_json()['metadata']['mime_type'] == 'image/jpeg'

    r_audio = client.get(f"/api/canvas/media/{audio['id']}/metadata")
    assert r_audio.status_code == 400
    assert r_audio.get_json()['code'] == 'unsupported_media'

    r_missing = client.get('/api/canvas/media/' + ('a' * 32) + '/metadata')
    assert r_missing.status_code == 404

    media_library.delete_media([opaque['id']])
    r_deleted = client.get(f"/api/canvas/media/{opaque['id']}/metadata")
    assert r_deleted.status_code == 410


def test_generate_accepts_direct_library_images_png_hardlink_and_jpeg_conversion(monkeypatch):
    _configure_ark(monkeypatch, model='seedream-5-0-pro')
    client = application.app.test_client()

    png_item, _ = media_library.save_upload(io.BytesIO(_png_bytes((10, 20, 30), (20, 12))), 'lib-ref.png')
    jpg_item, _ = media_library.save_upload(io.BytesIO(_jpeg_bytes((200, 100, 50), (30, 18))), 'lib-ref.jpg')

    # Workspace upload for mixed-order verification
    ws_resp = client.post(
        '/api/workspace/assets/img_tabs',
        data={'file': (io.BytesIO(_png_bytes((5, 5, 5), (16, 16))), 'ws.png')},
        content_type='multipart/form-data',
    )
    assert ws_resp.status_code == 201
    ws_url = ws_resp.get_json()['asset']['url']

    resp = client.post('/api/generate', json={
        'prompt': 'use @图片1 @图片2 @图片3',
        'provider': 'ark',
        'aspect_ratio': '1:1',
        'resolution': '1K',
        'image_urls': [png_item['url'], ws_url, jpg_item['url']],
    })
    assert resp.status_code == 202, resp.get_json()
    task_id = resp.get_json()['task_id']

    inputs = sorted(
        [a for a in tasks.list_assets(task_id) if a['kind'] == 'input_image'],
        key=storage.reference_asset_sort_key,
    )
    assert [os.path.basename(a['path']) for a in inputs] == ['ref_0.png', 'ref_1.png', 'ref_2.png']

    # PNG library reference is hard-linked (zero byte duplication, same inode)
    png_src = media_library.media_path(media_library.get_media(png_item['id']))
    assert os.stat(inputs[0]['path']).st_ino == os.stat(png_src).st_ino

    # JPEG library reference is converted to valid PNG on task creation
    with Image.open(inputs[2]['path']) as converted:
        assert converted.format == 'PNG'
        assert converted.size == (30, 18)


def test_generate_direct_library_alpha_validation(monkeypatch):
    _configure_ark(monkeypatch, model='seedream-5-0-pro')
    client = application.app.test_client()

    opaque, _ = media_library.save_upload(io.BytesIO(_png_bytes(alpha=False)), 'no-alpha.png')
    alpha, _ = media_library.save_upload(io.BytesIO(_png_bytes(alpha=True)), 'has-alpha.png')

    r_fail = client.post('/api/generate', json={
        'prompt': 'transparent bg test',
        'provider': 'ark',
        'aspect_ratio': '1:1',
        'resolution': '1K',
        'background': 'transparent',
        'output_format': 'png',
        'image_urls': [opaque['url']],
    })
    assert r_fail.status_code == 400
    assert 'Alpha' in r_fail.get_json()['error']

    r_ok = client.post('/api/generate', json={
        'prompt': 'transparent bg test',
        'provider': 'ark',
        'aspect_ratio': '1:1',
        'resolution': '1K',
        'background': 'transparent',
        'output_format': 'png',
        'image_urls': [alpha['url']],
    })
    assert r_ok.status_code == 202, r_ok.get_json()


def test_generate_direct_library_rejects_deleted_trashed_non_image_and_malformed_urls(monkeypatch):
    _configure_ark(monkeypatch, model='seedream-5-0-pro')
    client = application.app.test_client()

    # Non-image library media
    audio, _ = media_library.save_upload(io.BytesIO(_wav_bytes()), 'clip.wav')
    r_audio = client.post('/api/generate', json={
        'prompt': 'bad kind', 'provider': 'ark', 'aspect_ratio': '1:1', 'resolution': '1K',
        'image_urls': [audio['url']],
    })
    assert r_audio.status_code == 400
    assert '图片' in r_audio.get_json()['error']

    # Deleted library image -> 410
    deleted_item, _ = media_library.save_upload(io.BytesIO(_png_bytes((90, 90, 90))), 'gone.png')
    media_library.delete_media([deleted_item['id']])
    r_del = client.post('/api/generate', json={
        'prompt': 'deleted ref', 'provider': 'ark', 'aspect_ratio': '1:1', 'resolution': '1K',
        'image_urls': [deleted_item['url']],
    })
    assert r_del.status_code == 410
    assert '删除' in r_del.get_json()['error']

    # Trashed generated history image -> 409
    gen_task_id = tasks.create_task('image', 'seed', {}, provider='ark', status='completed')
    out_dir = storage.task_output_dir('image', gen_task_id)
    os.makedirs(out_dir, exist_ok=True)
    gen_path = os.path.join(out_dir, 'out.png')
    with open(gen_path, 'wb') as handle:
        handle.write(_png_bytes((40, 140, 220)))
    gen_media_id = media_library.register_generated(gen_task_id, gen_path, 'image', name='gen.png')
    assert client.delete(f'/api/tasks/{gen_task_id}').status_code == 200
    r_trashed = client.post('/api/generate', json={
        'prompt': 'trashed ref', 'provider': 'ark', 'aspect_ratio': '1:1', 'resolution': '1K',
        'image_urls': [f'/api/canvas/media/{gen_media_id}'],
    })
    assert r_trashed.status_code == 409
    assert '回收站' in r_trashed.get_json()['error']

    # Missing 32-hex media id -> 404
    r_missing = client.post('/api/generate', json={
        'prompt': 'missing ref', 'provider': 'ark', 'aspect_ratio': '1:1', 'resolution': '1K',
        'image_urls': ['/api/canvas/media/' + ('f' * 32)],
    })
    assert r_missing.status_code == 404

    # Malformed / traversal / thumbnail / non-workspace URLs -> 400
    live, _ = media_library.save_upload(io.BytesIO(_png_bytes((1, 2, 3))), 'live.png')
    for bad_url in (
        f"{live['url']}/thumbnail",
        f" {live['url']} ",
        '/api/canvas/media/../tasks.db',
        '/api/workspace/assets/video_tabs/foo.png',
        'https://example.com/a.png',
    ):
        r_bad = client.post('/api/generate', json={
            'prompt': 'bad url', 'provider': 'ark', 'aspect_ratio': '1:1', 'resolution': '1K',
            'image_urls': [bad_url],
        })
        assert r_bad.status_code == 400, (bad_url, r_bad.status_code)
        assert '不属于当前工作区' in r_bad.get_json()['error']
