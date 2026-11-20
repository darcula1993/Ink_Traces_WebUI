import base64
import io
import os
import pytest
from PIL import Image

import app
import media_library
import seedream55
import tasks
from test_generation import FakeResponse, _rgba_png_bytes


def _png_bytes(size=(512, 512), color=(40, 120, 200, 255)):
    buf = io.BytesIO()
    Image.new('RGBA', size, color).save(buf, format='PNG')
    return buf.getvalue()


def _jpeg_bytes(size=(512, 512), color=(180, 90, 40)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='JPEG', quality=92)
    return buf.getvalue()


def _upload_image_to_library(data, name='lib-source.png', folder_id=None):
    media, _ = media_library.save_upload(io.BytesIO(data), name, folder_id=folder_id, origin='upload')
    return media


def test_layer_project_from_library_png_and_jpeg_without_auto_decompose():
    client = app.app.test_client()
    png_data = _png_bytes((512, 512), (20, 140, 80, 255))
    jpg_data = _jpeg_bytes((600, 512), (210, 120, 30))
    png_media = _upload_image_to_library(png_data, 'hero.png')
    jpg_media = _upload_image_to_library(jpg_data, 'scene.jpg')

    res_png = client.post('/api/layer/projects', json={'source_media_id': png_media['id'], 'decompose': False})
    assert res_png.status_code == 201, res_png.get_json()
    body = res_png.get_json()
    assert body['task_id'] is None
    assert body['project']['name'] == 'hero'
    assert body['project']['source_name'] == 'hero.png'
    assert body['project']['source_metadata']['source_media_id'] == png_media['id']
    # PNG is hard-linked (same inode, independent directory entry)
    proj = tasks.get_layer_project(body['project_id'])
    lib_path = media_library.media_path(media_library.get_media(png_media['id']))
    assert os.path.samefile(proj['source_path'], lib_path)
    assert client.get(f"/api/layer/projects/{body['project_id']}/source").status_code == 200

    # JPEG is converted to normalized PNG snapshot; works via media URL too
    res_jpg = client.post('/api/layer/projects', json={
        'source_media_id': f"/api/canvas/media/{jpg_media['id']}",
        'name': '自定义标题',
        'decompose': False,
    })
    assert res_jpg.status_code == 201, res_jpg.get_json()
    jpg_body = res_jpg.get_json()
    assert jpg_body['project']['name'] == '自定义标题'
    assert jpg_body['project']['source_metadata']['source_media_id'] == jpg_media['id']
    assert jpg_body['project']['source_metadata']['original_format'] == 'jpeg'
    assert client.get(f"/api/layer/projects/{jpg_body['project_id']}/source").status_code == 200


def test_layer_source_media_validation_rejects_invalid_non_image_deleted_and_trashed(tmp_path):
    client = app.app.test_client()
    # Invalid format -> 400
    r = client.post('/api/layer/projects', json={'source_media_id': 'bad-id!', 'decompose': False})
    assert r.status_code == 400 and r.get_json()['code'] == 'invalid_id'

    # Unknown 32-hex -> 404
    r = client.post('/api/layer/projects', json={'source_media_id': '0' * 32, 'decompose': False})
    assert r.status_code == 404 and r.get_json()['code'] == 'media_not_found'

    # Non-image (audio WAV) -> 400 unsupported_media
    wav = b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
    audio_media, _ = media_library.save_upload(io.BytesIO(wav), 'clip.wav', origin='upload')
    r = client.post('/api/layer/projects', json={'source_media_id': audio_media['id'], 'decompose': False})
    assert r.status_code == 400 and r.get_json()['code'] == 'unsupported_media'

    # Too small (< 512x512) -> 400 and no orphan layer project created
    small_media = _upload_image_to_library(_png_bytes((64, 64), (10, 20, 30, 255)), 'tiny.png')
    before_count = len(tasks.list_layer_projects())
    r = client.post('/api/layer/projects', json={'source_media_id': small_media['id'], 'decompose': False})
    assert r.status_code == 400
    assert len(tasks.list_layer_projects()) == before_count

    # Deleted media -> 410 media_deleted
    del_media = _upload_image_to_library(_png_bytes((512, 512), (90, 90, 90, 255)), 'gone.png')
    media_library.delete_media([del_media['id']])
    r = client.post('/api/layer/projects', json={'source_media_id': del_media['id'], 'decompose': False})
    assert r.status_code == 410 and r.get_json()['code'] == 'media_deleted'

    # Trashed generation result -> 409 media_trashed; restored -> 201
    tid = tasks.create_task('image', 'gen', {}, status='succeeded')
    gen_file = tmp_path / 'gen.png'
    gen_file.write_bytes(_png_bytes((512, 512), (11, 22, 33, 255)))
    tasks.register_asset(tid, 'output_image', str(gen_file), 'image/png')
    gen_media_id = media_library.register_generated(tid, gen_file, 'image')
    assert client.delete(f'/api/tasks/{tid}').get_json()['trashed'] is True

    r = client.post('/api/layer/projects', json={'source_media_id': gen_media_id, 'decompose': False})
    assert r.status_code == 409 and r.get_json()['code'] == 'media_trashed'

    assert client.post(f'/api/tasks/{tid}/restore').get_json()['success'] is True
    r = client.post('/api/layer/projects', json={'source_media_id': gen_media_id, 'decompose': False})
    assert r.status_code == 201


def test_layer_source_alias_and_atomic_replace_preserves_library_files():
    client = app.app.test_client()
    bytes_a = _png_bytes((512, 512), (200, 10, 10, 255))
    bytes_b = _png_bytes((512, 512), (10, 200, 10, 255))
    media_a = _upload_image_to_library(bytes_a, 'a.png')
    media_b = _upload_image_to_library(bytes_b, 'b.png')
    media_library.add_alias('workflow', 'a' * 32, media_a['id'])

    # Create via legacy workflow URL alias
    r = client.post('/api/layer/projects', json={
        'source_media_id': f"/api/canvas/workflows/wf1/assets/{'a' * 32}",
        'decompose': False,
    })
    assert r.status_code == 201, r.get_json()
    pid = r.get_json()['project_id']
    assert r.get_json()['project']['source_metadata']['source_media_id'] == media_a['id']

    # Replace source with media_b: MUST NOT mutate media_a on disk
    r2 = client.post(f'/api/layer/projects/{pid}/source', json={'source_media_id': media_b['id']})
    assert r2.status_code == 200, r2.get_json()
    assert r2.get_json()['project']['source_metadata']['source_media_id'] == media_b['id']
    assert media_library.media_path(media_library.get_media(media_a['id'])).read_bytes() == bytes_a
    assert media_library.media_path(media_library.get_media(media_b['id'])).read_bytes() == bytes_b


def test_lifecycle_isolation_deleting_project_or_library_never_breaks_the_other(monkeypatch):
    monkeypatch.setitem(app.API_PROVIDERS, 'ark', {
        'api_key': 'test', 'model': seedream55.MODEL, 'endpoint': 'https://provider.invalid',
    })
    client = app.app.test_client()
    img1_bytes = _png_bytes((512, 512), (12, 34, 56, 255))
    img2_bytes = _png_bytes((512, 512), (65, 43, 21, 255))
    media1 = _upload_image_to_library(img1_bytes, 'keep-in-lib.png')
    media2 = _upload_image_to_library(img2_bytes, 'delete-from-lib.png')

    # Case 1: Delete layer project -> library asset remains completely intact
    r1 = client.post('/api/layer/projects', json={'source_media_id': media1['id'], 'decompose': False})
    assert r1.status_code == 201
    pid1 = r1.get_json()['project_id']
    assert client.delete(f'/api/layer/projects/{pid1}').status_code == 200
    lib_resp = client.get(f"/api/canvas/media/{media1['id']}")
    assert lib_resp.status_code == 200 and lib_resp.data == img1_bytes

    # Case 2: Queue decompose task, then delete source from library -> task still executes cleanly!
    r2 = client.post('/api/layer/projects', json={'source_media_id': media2['id'], 'decompose': False})
    assert r2.status_code == 201
    pid2 = r2.get_json()['project_id']
    dec = client.post(f'/api/layer/projects/{pid2}/decompose', json={'prompt': 'split', 'size': '1K'})
    assert dec.status_code == 202
    tid = dec.get_json()['task_id']

    # Delete media2 from global library while task is pending
    media_library.delete_media([media2['id']])
    assert client.get(f"/api/canvas/media/{media2['id']}").status_code == 410
    # Project source and task still work!
    assert client.get(f'/api/layer/projects/{pid2}/source').status_code == 200

    layer_b64 = base64.b64encode(_rgba_png_bytes((64, 64))).decode()
    monkeypatch.setattr(
        app.HTTP, 'post',
        lambda url, **kwargs: FakeResponse(payload={'data': [
            {'b64_json': layer_b64, 'z_index': 0, 'name': '底图'},
            {'b64_json': layer_b64, 'z_index': 1, 'name': '主体'},
        ]}),
    )
    with app.app.app_context():
        result, status = app.execute_layer_task(tid)
    assert status == 200, result


def test_save_layer_and_composite_to_library_with_dedup_system_folder_guard_and_delete_survival(monkeypatch):
    monkeypatch.setitem(app.API_PROVIDERS, 'ark', {
        'api_key': 'test', 'model': seedream55.MODEL, 'endpoint': 'https://provider.invalid',
    })
    client = app.app.test_client()
    src = _upload_image_to_library(_png_bytes((512, 512), (77, 88, 99, 255)), 'poster.png')
    created = client.post('/api/layer/projects', json={'source_media_id': src['id'], 'decompose': True})
    assert created.status_code == 202
    pid, tid = created.get_json()['project_id'], created.get_json()['task_id']

    base_png = _png_bytes((64, 64), (10, 10, 10, 255))
    fg_png = _png_bytes((64, 64), (250, 200, 10, 255))
    monkeypatch.setattr(
        app.HTTP, 'post',
        lambda url, **kwargs: FakeResponse(payload={'data': [
            {'b64_json': base64.b64encode(base_png).decode(), 'z_index': 0, 'name': '底图'},
            {'b64_json': base64.b64encode(fg_png).decode(), 'z_index': 1, 'name': '前景主体'},
        ]}),
    )
    with app.app.app_context():
        _, status = app.execute_layer_task(tid)
    assert status == 200

    project = client.get(f'/api/layer/projects/{pid}').get_json()['project']
    fg_layer = next(item for item in project['document']['layers'] if item['z_index'] == 1)
    folder = media_library.create_folder({'title': '图层导出'})

    # System folder (生成历史 / 生成历史-图片) MUST be rejected with 409
    gen_folder_id = media_library.system_folder_id('generated_image')
    bad = client.post(f'/api/layer/projects/{pid}/save-to-library', json={
        'layer_id': fg_layer['id'], 'folder_id': gen_folder_id,
    })
    assert bad.status_code == 409 and bad.get_json()['code'] == 'folder_generated_only'

    # Save single layer to user folder -> 201, origin='save_as'
    saved = client.post(f'/api/layer/projects/{pid}/save-to-library', json={
        'layer_id': fg_layer['id'], 'folder_id': folder['id'], 'name': '提取主体.png',
    })
    assert saved.status_code == 201, saved.get_json()
    saved_body = saved.get_json()
    assert saved_body['deduplicated'] is False
    assert saved_body['media']['origin'] == 'save_as'
    assert saved_body['media']['folder_id'] == folder['id']
    assert saved_body['media']['name'] == '提取主体.png'
    saved_id = saved_body['media']['id']

    # Saving same layer again deduplicates -> 200, deduplicated=True, same media id
    dup = client.post(f'/api/layer/projects/{pid}/save-to-library', json={
        'layer_id': fg_layer['id'], 'folder_id': None, 'name': '重复.png',
    })
    assert dup.status_code == 200
    assert dup.get_json()['deduplicated'] is True
    assert dup.get_json()['media']['id'] == saved_id

    # Attempting to save duplicate into 生成历史 STILL rejected with 409
    dup_sys = client.post(f'/api/layer/projects/{pid}/save-to-library', json={
        'layer_id': fg_layer['id'], 'folder_id': gen_folder_id,
    })
    assert dup_sys.status_code == 409 and dup_sys.get_json()['code'] == 'folder_generated_only'

    # Save composite multipart upload -> 201, origin='save_as'
    comp_bytes = _png_bytes((64, 64), (120, 40, 220, 255))
    comp = client.post(f'/api/layer/projects/{pid}/save-to-library', data={
        'file': (io.BytesIO(comp_bytes), 'poster-合成.png'),
        'name': 'poster-合成.png',
        'folder_id': folder['id'],
    })
    assert comp.status_code == 201, comp.get_json()
    comp_id = comp.get_json()['media']['id']
    assert comp.get_json()['media']['origin'] == 'save_as'

    # Delete layer project -> BOTH saved layer and saved composite survive in global library!
    assert client.delete(f'/api/layer/projects/{pid}').status_code == 200
    r_fg = client.get(f'/api/canvas/media/{saved_id}')
    assert r_fg.status_code == 200 and r_fg.data == fg_png
    r_comp = client.get(f'/api/canvas/media/{comp_id}')
    assert r_comp.status_code == 200 and r_comp.data == comp_bytes
