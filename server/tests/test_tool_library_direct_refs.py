import io
import json
import os
import subprocess
import wave
from PIL import Image

import app as application
import media_library
import storage
import tasks


def _png_bytes(color=(30, 120, 200), size=(320, 320)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    return buf.getvalue()


def _wav_bytes(samples=3200):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b'\x01\x00' * samples)
    return buf.getvalue()


def _mp4_bytes(tmp_path, name='clip.mp4', color='blue'):
    out = tmp_path / name
    subprocess.run(
        ['ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s=320x240:d=1',
         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(out)],
        check=True,
    )
    return out.read_bytes()


def _configure_ark_video(monkeypatch):
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {
        'api_key': 'test-ark-key',
        'endpoint': 'https://ark.invalid',
        'model': 'ep-video-20',
    })
    monkeypatch.setattr(application, 'PUBLIC_SCHEME', 'https')
    monkeypatch.setattr(application, 'PUBLIC_HOST', 'public.invalid')
    monkeypatch.setattr(application, 'PUBLIC_PORT', 443)
    monkeypatch.setitem(application.config, 'deployment', {
        'public_base_url': 'https://public.invalid',
        'cupsy_source': {'base_url': 'https://public.invalid'},
    })


def _configure_cupsy(monkeypatch, source_ready=True):
    base = 'https://public.invalid' if source_ready else ''
    monkeypatch.setitem(application.config, 'deployment', {
        'public_base_url': base,
        'cupsy_source': {'base_url': base},
    })
    monkeypatch.setattr(application, 'CUPSY_VIDEO_CONFIG', {
        'api_key': 'test-cupsy-key',
        'endpoint': 'https://cupsy.invalid',
        'model': 'seedance-2.5',
        'source_base_url': base,
    })
    monkeypatch.setattr(application, 'CUPSY_AUDIO_CONFIG', {
        'api_key': 'test-cupsy-key',
        'endpoint': 'https://cupsy.invalid',
        'model': 'seed-audio-1.0',
        'source_base_url': base,
    })


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {'id': 'ext-vid-1'}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


def test_ark_video_keyframe_and_reference_accept_direct_library_media_json(monkeypatch, tmp_path):
    _configure_ark_video(monkeypatch)
    sent_bodies = []
    monkeypatch.setattr(application.HTTP, 'post', lambda url, **kw: (sent_bodies.append(kw.get('json')), _FakeResponse(payload={'id': f'ext-vid-{len(sent_bodies)}'}))[1])
    client = application.app.test_client()

    first, _ = media_library.save_upload(io.BytesIO(_png_bytes((20, 40, 60))), 'first.png')
    last, _ = media_library.save_upload(io.BytesIO(_png_bytes((120, 140, 160))), 'last.png')
    vid, _ = media_library.save_upload(io.BytesIO(_mp4_bytes(tmp_path, 'ref.mp4')), 'ref.mp4')
    aud, _ = media_library.save_upload(io.BytesIO(_wav_bytes()), 'ref.wav')

    # Keyframe pure JSON
    r_kf = client.post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.0', 'video_mode': 'keyframe',
        'prompt': 'animate keyframes', 'ratio': '16:9', 'duration': 5, 'resolution': '720p',
        'first_frame_url': first['url'], 'last_frame_url': last['url'],
    })
    assert r_kf.status_code == 200, r_kf.get_json()
    roles_kf = [c.get('role') for c in sent_bodies[-1]['content'] if c.get('type') != 'text']
    assert roles_kf == ['first_frame', 'last_frame']

    # Reference pure JSON (image + video + audio)
    r_ref = client.post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.0', 'video_mode': 'reference',
        'prompt': 'combine @图片1 @视频1 @音频1', 'ratio': '16:9', 'duration': 5, 'resolution': '720p',
        'ref_image_urls': [first['url']],
        'ref_video_urls': [vid['url']],
        'ref_audio_urls': [aud['url']],
    })
    assert r_ref.status_code == 200, r_ref.get_json()
    ref_body = sent_bodies[-1]
    roles_ref = [c.get('role') for c in ref_body['content'] if c.get('type') != 'text']
    assert roles_ref == ['reference_image', 'reference_video', 'reference_audio']
    vid_item = next(c for c in ref_body['content'] if c.get('role') == 'reference_video')
    assert vid_item['video_url']['url'].startswith('https://public.invalid/api/upload_video/')
    # Staged video file is hard-linked to the library video (same inode)
    fname = vid_item['video_url']['url'].rsplit('/api/upload_video/', 1)[-1]
    staged_path = os.path.join(application.UPLOAD_VIDEO_DIR, fname)
    lib_vid_path = media_library.media_path(media_library.get_media(vid['id']))
    assert os.stat(staged_path).st_ino == os.stat(lib_vid_path).st_ino


def test_ark_video_mixed_multipart_and_library_preserves_exact_order(monkeypatch):
    _configure_ark_video(monkeypatch)
    sent_bodies = []
    monkeypatch.setattr(application.HTTP, 'post', lambda url, **kw: (sent_bodies.append(kw.get('json')), _FakeResponse(payload={'id': f'ext-vid-{len(sent_bodies)}'}))[1])
    client = application.app.test_client()

    lib1, _ = media_library.save_upload(io.BytesIO(_png_bytes((10, 10, 10), (320, 320))), 'lib1.png')
    lib2, _ = media_library.save_upload(io.BytesIO(_png_bytes((240, 240, 240), (360, 360))), 'lib2.png')
    upload_bytes = _png_bytes((120, 50, 200), (340, 340))

    resp = client.post('/api/video/generate', data={
        'provider': 'ark', 'model': 'seedance-2.0', 'video_mode': 'reference',
        'prompt': 'order check', 'ratio': '16:9', 'duration': 5, 'resolution': '720p',
        'ref_image_urls': json.dumps([lib1['url'], 'upload:0', lib2['url']]),
        'ref_images': (io.BytesIO(upload_bytes), 'local.png'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 200, resp.get_json()

    image_urls = [c['image_url']['url'] for c in sent_bodies[-1]['content'] if c.get('role') == 'reference_image']
    assert len(image_urls) == 3
    sizes = []
    for data_url in image_urls:
        raw = application.base64.b64decode(data_url.split(',', 1)[1])
        with Image.open(io.BytesIO(raw)) as im:
            sizes.append(im.size)
    assert sizes == [(320, 320), (340, 340), (360, 360)]


def test_ark_video_direct_library_guards_and_staged_cleanup(monkeypatch, tmp_path):
    _configure_ark_video(monkeypatch)
    client = application.app.test_client()

    img, _ = media_library.save_upload(io.BytesIO(_png_bytes((10, 20, 30))), 'a.png')
    vid, _ = media_library.save_upload(io.BytesIO(_mp4_bytes(tmp_path, 'b.mp4', 'red')), 'b.mp4')
    aud, _ = media_library.save_upload(io.BytesIO(_wav_bytes()), 'c.wav')

    # Deleted media -> 410
    gone, _ = media_library.save_upload(io.BytesIO(_png_bytes((99, 88, 77))), 'gone.png')
    media_library.delete_media([gone['id']])
    r_gone = client.post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.0', 'video_mode': 'keyframe',
        'prompt': 'x', 'ratio': '16:9', 'duration': 5, 'resolution': '720p',
        'first_frame_url': gone['url'],
    })
    assert r_gone.status_code == 410

    # Wrong kind in ref_video_urls -> 400
    r_wrong = client.post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.0', 'video_mode': 'reference',
        'prompt': 'x', 'ratio': '16:9', 'duration': 5, 'resolution': '720p',
        'ref_video_urls': [img['url']],
    })
    assert r_wrong.status_code == 400

    # Malformed / padded / query-string /api/canvas/media* in ref_video_urls -> 400 (never passed raw to Ark)
    ark_calls = []
    monkeypatch.setattr(application.HTTP, 'post', lambda url, **kw: (ark_calls.append(kw.get('json')), _FakeResponse())[1])
    for bad_video_url in (
        f"{vid['url']}/thumbnail",
        f" {vid['url']}",
        f"{vid['url']} ",
        '/api/canvas/media?x=1',
        '/api/canvas/media',
    ):
        r_bad_vid = client.post('/api/video/generate', json={
            'provider': 'ark', 'model': 'seedance-2.0', 'video_mode': 'reference',
            'prompt': 'x', 'ratio': '16:9', 'duration': 5, 'resolution': '720p',
            'ref_video_urls': [bad_video_url],
        })
        assert r_bad_vid.status_code == 400, (bad_video_url, r_bad_vid.status_code)
    assert ark_calls == []

    # Keyframe rejects ref_image_urls, reference rejects first_frame_url
    assert client.post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.0', 'video_mode': 'keyframe',
        'prompt': 'x', 'ratio': '16:9', 'duration': 5, 'resolution': '720p',
        'ref_image_urls': [img['url']],
    }).status_code == 400
    assert client.post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.0', 'video_mode': 'reference',
        'prompt': 'x', 'ratio': '16:9', 'duration': 5, 'resolution': '720p',
        'first_frame_url': img['url'],
    }).status_code == 400

    # Validation failure after staging cleans up hard-linked file in UPLOAD_VIDEO_DIR
    before_files = set(os.listdir(application.UPLOAD_VIDEO_DIR)) if os.path.isdir(application.UPLOAD_VIDEO_DIR) else set()
    r_invalid_dur = client.post('/api/video/generate', json={
        'provider': 'ark', 'model': 'seedance-2.0', 'video_mode': 'reference',
        'prompt': 'x', 'ratio': '16:9', 'duration': 999, 'resolution': '720p',
        'ref_video_urls': [vid['url']],
        'ref_audio_urls': [aud['url']],
    })
    assert r_invalid_dur.status_code == 400
    after_files = set(os.listdir(application.UPLOAD_VIDEO_DIR)) if os.path.isdir(application.UPLOAD_VIDEO_DIR) else set()
    assert after_files == before_files


def test_cupsy_video_direct_library_hardlinks_and_zero_orphan_on_error(monkeypatch, tmp_path):
    _configure_cupsy(monkeypatch, source_ready=True)
    client = application.app.test_client()

    img, _ = media_library.save_upload(io.BytesIO(_png_bytes((50, 150, 200))), 'cupsy-img.png')
    vid, _ = media_library.save_upload(io.BytesIO(_mp4_bytes(tmp_path, 'cupsy-vid.mp4', 'green')), 'cupsy-vid.mp4')
    aud, _ = media_library.save_upload(io.BytesIO(_wav_bytes()), 'cupsy-aud.wav')

    # Invalid keyframe (last without first) leaves 0 provider_assets
    before_count = tasks.count_provider_assets('cupsy')
    r_bad = client.post('/api/video/generate', json={
        'provider': 'cupsy', 'model': 'seedance-2.5', 'video_mode': 'keyframe',
        'prompt': 'bad', 'ratio': 'adaptive', 'duration': 5, 'resolution': '720p',
        'last_frame_url': img['url'],
    })
    assert r_bad.status_code == 400
    assert tasks.count_provider_assets('cupsy') == before_count

    # D2 regression: missing upload_video file after a valid library image leaves 0 orphaned provider_assets
    r_missing_vid = client.post('/api/video/generate', json={
        'provider': 'cupsy', 'model': 'seedance-2.5', 'video_mode': 'reference',
        'prompt': 'd2 missing vid', 'ratio': 'adaptive', 'duration': 5, 'resolution': '720p',
        'ref_image_urls': [img['url']],
        'ref_video_urls': ['https://public.invalid/api/upload_video/does-not-exist.mp4'],
    })
    assert r_missing_vid.status_code == 400
    assert tasks.count_provider_assets('cupsy') == before_count

    # D2 regression: bad-MIME multipart upload mixed with a valid library image leaves 0 orphaned provider_assets
    r_bad_mime = client.post('/api/video/generate', data={
        'provider': 'cupsy', 'model': 'seedance-2.5', 'video_mode': 'reference',
        'prompt': 'd2 bad mime', 'ratio': 'adaptive', 'duration': 5, 'resolution': '720p',
        'ref_image_urls': json.dumps([img['url'], 'upload:0']),
        'ref_images': (io.BytesIO(b'not an image'), 'bad.txt', 'text/plain'),
    }, content_type='multipart/form-data')
    assert r_bad_mime.status_code == 400
    assert tasks.count_provider_assets('cupsy') == before_count

    # Valid reference pure JSON
    r_ok = client.post('/api/video/generate', json={
        'provider': 'cupsy', 'model': 'seedance-2.5', 'video_mode': 'reference',
        'prompt': 'cupsy omni', 'ratio': 'adaptive', 'duration': 5, 'resolution': '720p',
        'ref_image_urls': [img['url']],
        'ref_video_urls': [vid['url']],
        'ref_audio_urls': [aud['url']],
    })
    assert r_ok.status_code == 202, r_ok.get_json()
    task_id = r_ok.get_json()['db_task_id']
    linked = tasks.list_task_provider_assets(task_id)
    assert [(a['role'], a['kind']) for a in linked] == [
        ('reference_image', 'image'),
        ('reference_video', 'video'),
        ('reference_audio', 'audio'),
    ]
    # Hard-linked zero-copy onto library files
    img_src = media_library.media_path(media_library.get_media(img['id']))
    vid_src = media_library.media_path(media_library.get_media(vid['id']))
    assert os.stat(linked[0]['local_path']).st_ino == os.stat(img_src).st_ino
    assert os.stat(linked[1]['local_path']).st_ino == os.stat(vid_src).st_ino


def test_cupsy_audio_direct_library_mixed_order_and_guards(monkeypatch):
    _configure_cupsy(monkeypatch, source_ready=True)
    client = application.app.test_client()

    aud1, _ = media_library.save_upload(io.BytesIO(_wav_bytes(1600)), 'voice1.wav')
    aud2, _ = media_library.save_upload(io.BytesIO(_wav_bytes(2400)), 'voice2.wav')
    img1, _ = media_library.save_upload(io.BytesIO(_png_bytes((200, 120, 40))), 'scene.png')

    # Pre-existing Cupsy remote asset in the middle to verify exact ordering
    mid_path = media_library.media_path(media_library.get_media(aud2['id']))
    cupsy_mid = application.create_cupsy_asset_from_path(str(mid_path), 'audio', 'mid.wav')

    r_aud = client.post('/api/audio/generate', json={
        'prompt': 'speak with [Audio1] and [Audio2]',
        'model': 'seed-audio-1.0',
        'output_format': 'mp3',
        'sample_rate': 48000,
        'reference_mode': 'audio',
        'cupsy_assets': [],
        'reference_media_urls': [aud1['url'], f"cupsy:{cupsy_mid['id']}"],
    })
    assert r_aud.status_code == 202, r_aud.get_json()
    linked = tasks.list_task_provider_assets(r_aud.get_json()['task_id'])
    assert len(linked) == 2
    assert [a['position'] for a in linked] == [0, 1]
    assert linked[1]['id'] == cupsy_mid['id']
    assert os.stat(linked[0]['local_path']).st_ino == os.stat(media_library.media_path(media_library.get_media(aud1['id']))).st_ino

    # Image reference mode
    r_img = client.post('/api/audio/generate', json={
        'prompt': 'soundscape for scene',
        'model': 'seed-audio-1.0',
        'output_format': 'mp3',
        'sample_rate': 48000,
        'reference_mode': 'image',
        'cupsy_assets': [],
        'reference_media_urls': [img1['url']],
    })
    assert r_img.status_code == 202, r_img.get_json()

    # Wrong kind (image in audio mode) -> 400
    assert client.post('/api/audio/generate', json={
        'prompt': 'mismatch', 'model': 'seed-audio-1.0', 'reference_mode': 'audio',
        'reference_media_urls': [img1['url']],
    }).status_code == 400

    # Deleted media -> 410
    gone_aud, _ = media_library.save_upload(io.BytesIO(_wav_bytes(1900)), 'gone.wav')
    media_library.delete_media([gone_aud['id']])
    assert client.post('/api/audio/generate', json={
        'prompt': 'gone', 'model': 'seed-audio-1.0', 'reference_mode': 'audio',
        'reference_media_urls': [gone_aud['url']],
    }).status_code == 410

    # Exceeding limit with speaker leaves zero new provider_assets
    extra_aud, _ = media_library.save_upload(io.BytesIO(_wav_bytes(2900)), 'extra.wav')
    before_assets = tasks.count_provider_assets('cupsy')
    r_over = client.post('/api/audio/generate', json={
        'prompt': 'too many', 'model': 'seed-audio-1.0', 'reference_mode': 'audio',
        'speaker': 'zh_female_qingxin',
        'reference_media_urls': [extra_aud['url'], aud1['url'], aud2['url']],
    })
    assert r_over.status_code == 400
    assert tasks.count_provider_assets('cupsy') == before_assets

    # D2 regression: valid reference_media_urls + bad-MIME multipart upload leaves 0 orphaned provider_assets
    r_audio_bad_mime = client.post('/api/audio/generate', data={
        'prompt': 'd2 audio bad mime',
        'model': 'seed-audio-1.0',
        'reference_mode': 'audio',
        'reference_media_urls': json.dumps([extra_aud['url']]),
        'references': (io.BytesIO(b'not audio'), 'bad.txt', 'text/plain'),
    }, content_type='multipart/form-data')
    assert r_audio_bad_mime.status_code == 400
    assert tasks.count_provider_assets('cupsy') == before_assets
