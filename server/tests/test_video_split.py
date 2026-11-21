"""Tests for video splitting API and logic (VIDEO-SPLIT-API-20261122)."""
import hashlib
import io
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

import app as application
import canvas_store as store
import media_library as media
import storage
import tasks
import video_split
from test_canvas_library_folders import image_bytes

GEN_VIDEO = media.system_folder_id('generated_video')


def client():
    return application.app.test_client()


def _make_mp4(path: Path, duration: float, with_audio: bool = True) -> Path:
    """Synthesize a small fast test MP4 with visually varying frames (testsrc2)."""
    ffmpeg = shutil.which('ffmpeg')
    assert ffmpeg, 'ffmpeg is required to run test_video_split'
    cmd = [
        ffmpeg,
        '-hide_banner',
        '-v', 'error',
        '-y',
        '-f', 'lavfi',
        '-i', f'testsrc2=size=320x180:rate=25:duration={duration:.3f}',
    ]
    if with_audio:
        cmd += [
            '-f', 'lavfi',
            '-i', f'sine=frequency=440:sample_rate=44100:duration={duration:.3f}',
            '-c:a', 'aac',
            '-b:a', '64k',
        ]
    cmd += [
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
    assert res.returncode == 0, res.stderr.decode('utf-8', errors='replace')
    return path


def _ffprobe_duration(path: Path) -> float:
    ffprobe = shutil.which('ffprobe')
    assert ffprobe
    res = subprocess.run(
        [
            ffprobe,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'json',
            str(path),
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert res.returncode == 0, res.stderr.decode('utf-8', errors='replace')
    return float(json.loads(res.stdout)['format']['duration'])


def _upload_video(c, path: Path, name='clip.mp4', folder_id=None):
    form = {'file': (io.BytesIO(path.read_bytes()), name)}
    if folder_id is not None:
        form['folder_id'] = folder_id
    res = c.post('/api/canvas/media', data=form)
    assert res.status_code in (200, 201), res.json
    return res.json['media']


def _register_generated_video(path: Path, name='gen_clip.mp4'):
    tid = tasks.create_task('video', 'test video', {}, status='succeeded')
    out_dir = Path(storage.OUTPUT_DIR) / str(tid)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / name
    shutil.copyfile(path, out_file)
    tasks.register_asset(tid, 'output_video', str(out_file), 'video/mp4')
    media_id = media.register_generated(tid, out_file, 'output_video', name=name)
    return tid, media_id


def _make_black_mp4(path: Path, duration: float) -> Path:
    """Synthesize a pure-black silent MP4 so equal-duration segments have identical bytes."""
    ffmpeg = shutil.which('ffmpeg')
    assert ffmpeg, 'ffmpeg is required to run test_video_split'
    cmd = [
        ffmpeg,
        '-hide_banner',
        '-v', 'error',
        '-y',
        '-f', 'lavfi',
        '-i', f'color=c=black:s=320x180:r=25:d={duration:.3f}',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
    assert res.returncode == 0, res.stderr.decode('utf-8', errors='replace')
    return path


@pytest.fixture(scope='module')
def sample_videos(tmp_path_factory):
    base = tmp_path_factory.mktemp('split_samples')
    return {
        'av_4s': _make_mp4(base / 'av_4s.mp4', 4.0, with_audio=True),
        'noaudio_3s': _make_mp4(base / 'noaudio_3s.mp4', 3.0, with_audio=False),
        'short_035s': _make_mp4(base / 'short_035s.mp4', 0.35, with_audio=False),
        'black_4s': _make_black_mp4(base / 'black_4s.mp4', 4.0),
    }


def test_split_points_mode_creates_segments_and_preserves_source(sample_videos):
    c = client()
    src = _upload_video(c, sample_videos['av_4s'], name='scene_demo.mp4')
    src_row_before = media.get_media(src['id'])
    src_file = media.media_path(src_row_before)
    src_sha_before = hashlib.sha256(src_file.read_bytes()).hexdigest()

    res = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'points', 'cut_points': [1.2, 2.7]},
    )
    assert res.status_code == 201, res.json
    payload = res.json
    assert payload['success'] is True
    assert payload['source_id'] == src['id']
    assert abs(payload['duration'] - 4.0) <= 0.15
    assert len(payload['items']) == 3
    assert len(payload['segments']) == 3

    expected_bounds = [(0.0, 1.2), (1.2, 2.7), (2.7, payload['duration'])]
    for idx, (seg, item, (exp_s, exp_e)) in enumerate(
        zip(payload['segments'], payload['items'], expected_bounds), start=1
    ):
        assert seg['index'] == idx
        assert seg['start'] == pytest.approx(exp_s, abs=0.01)
        assert seg['end'] == pytest.approx(exp_e, abs=0.01)
        assert seg['duration'] == pytest.approx(exp_e - exp_s, abs=0.01)
        assert seg['media_id'] == item['id']
        assert seg['deduplicated'] is False
        assert item['name'] == f'scene_demo_片段{idx}.mp4'
        assert item['kind'] == 'video'
        assert item['origin'] == 'save_as'
        assert item['folder_id'] is None

        # Segment is readable over HTTP and has accurate probed duration
        dl = c.get(f"/api/canvas/media/{item['id']}")
        assert dl.status_code == 200
        assert len(dl.data) > 0
        seg_path = media.media_path(media.get_media(item['id']))
        probed = _ffprobe_duration(seg_path)
        assert abs(probed - (exp_e - exp_s)) <= 0.25, f'seg {idx}: probed={probed}, expected={exp_e - exp_s}'

    # Source file & metadata untouched
    src_row_after = media.get_media(src['id'])
    assert src_row_after == src_row_before
    assert hashlib.sha256(media.media_path(src_row_after).read_bytes()).hexdigest() == src_sha_before


def test_split_equal_mode_normal_and_tail_merge(sample_videos):
    c = client()
    src = _upload_video(c, sample_videos['av_4s'], name='equal_test.mp4')

    # 4.0s by 1.5s -> [0-1.5, 1.5-3.0, 3.0-4.0]
    res = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.5},
    )
    assert res.status_code == 201, res.json
    segs = res.json['segments']
    assert len(segs) == 3
    assert (segs[0]['start'], segs[0]['end']) == (0.0, 1.5)
    assert (segs[1]['start'], segs[1]['end']) == (1.5, 3.0)
    assert segs[2]['start'] == 3.0
    assert abs(segs[2]['end'] - res.json['duration']) <= 0.01
    for seg in segs:
        probed = _ffprobe_duration(media.media_path(media.get_media(seg['media_id'])))
        assert abs(probed - seg['duration']) <= 0.25

    # Tail < 0.2s merged: 4.0s by 1.95s -> [0-1.95, 1.95-4.0] (tail 0.1s merged)
    res2 = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.95},
    )
    assert res2.status_code == 201, res2.json
    segs2 = res2.json['segments']
    assert len(segs2) == 2
    assert (segs2[0]['start'], segs2[0]['end']) == (0.0, 1.95)
    assert segs2[1]['start'] == 1.95
    assert abs(segs2[1]['end'] - res2.json['duration']) <= 0.01
    for seg in segs2:
        probed = _ffprobe_duration(media.media_path(media.get_media(seg['media_id'])))
        assert abs(probed - seg['duration']) <= 0.25


def test_split_ten_segments_uses_two_digit_numbering(sample_videos):
    c = client()
    src = _upload_video(c, sample_videos['av_4s'], name='ten_parts.mp4')
    res = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 0.4},
    )
    assert res.status_code == 201, res.json
    items = res.json['items']
    assert len(items) == 10
    assert items[0]['name'] == 'ten_parts_片段01.mp4'
    assert items[9]['name'] == 'ten_parts_片段10.mp4'


def test_split_video_without_audio_stream(sample_videos):
    c = client()
    src = _upload_video(c, sample_videos['noaudio_3s'], name='silent.mp4')
    res = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'points', 'cut_points': [1.5]},
    )
    assert res.status_code == 201, res.json
    assert len(res.json['items']) == 2
    for seg in res.json['segments']:
        probed = _ffprobe_duration(media.media_path(media.get_media(seg['media_id'])))
        assert abs(probed - seg['duration']) <= 0.25


def test_split_folder_placement_user_vs_system(sample_videos):
    c = client()
    folder = c.post('/api/canvas/media/folders', json={'title': '自定义分镜'}).json['folder']

    # Source in user folder -> segments land in same user folder
    user_src = _upload_video(c, sample_videos['noaudio_3s'], name='u_clip.mp4', folder_id=folder['id'])
    r_user = c.post(
        f"/api/canvas/media/{user_src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.5},
    )
    assert r_user.status_code == 201, r_user.json
    assert all(item['folder_id'] == folder['id'] for item in r_user.json['items'])

    # Source in system folder (生成历史/视频) -> segments land in root (folder_id=None)
    _, gen_media_id = _register_generated_video(sample_videos['av_4s'], name='gen_video.mp4')
    assert media.get_media(gen_media_id)['folder_id'] == GEN_VIDEO
    r_sys = c.post(
        f'/api/canvas/media/{gen_media_id}/split',
        json={'mode': 'points', 'cut_points': [2.0]},
    )
    assert r_sys.status_code == 201, r_sys.json
    assert len(r_sys.json['items']) == 2
    assert all(item['folder_id'] is None for item in r_sys.json['items'])


def test_split_security_and_source_validation(sample_videos):
    c = client()
    src = _upload_video(c, sample_videos['noaudio_3s'], name='sec.mp4')

    # Cross-origin blocked (403)
    cross = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.5},
        headers={'Origin': 'https://evil.example'},
    )
    assert cross.status_code == 403 and cross.json['code'] == 'cross_site'

    cross_sfs = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.5},
        headers={'Sec-Fetch-Site': 'cross-site'},
    )
    assert cross_sfs.status_code == 403 and cross_sfs.json['code'] == 'cross_site'

    # Non-JSON content type -> 415
    not_json = c.post(
        f"/api/canvas/media/{src['id']}/split",
        data='mode=equal',
        content_type='text/plain',
    )
    assert not_json.status_code == 415

    # Missing / invalid media IDs
    assert c.post('/api/canvas/media/not-a-hex-id/split', json={'mode': 'equal', 'segment_duration': 1.0}).status_code == 400
    missing = c.post('/api/canvas/media/' + 'a' * 32 + '/split', json={'mode': 'equal', 'segment_duration': 1.0})
    assert missing.status_code == 404 and missing.json['code'] == 'media_not_found'

    # Non-video media (PNG image) -> 400
    img = c.post(
        '/api/canvas/media',
        data={'file': (io.BytesIO(image_bytes('red')), 'pic.png')},
    ).json['media']
    bad_kind = c.post(
        f"/api/canvas/media/{img['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.0},
    )
    assert bad_kind.status_code == 400 and bad_kind.json['code'] == 'invalid_request'

    # Deleted media -> 410
    del_src = _upload_video(c, sample_videos['av_4s'], name='to_del.mp4')
    assert c.post('/api/canvas/media/delete', json={'ids': [del_src['id']]}).status_code == 200
    deleted = c.post(
        f"/api/canvas/media/{del_src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.5},
    )
    assert deleted.status_code == 410 and deleted.json['code'] == 'media_deleted'

    # Trashed generated media -> 409 media_trashed
    tid, gen_id = _register_generated_video(sample_videos['av_4s'], name='trashed_vid.mp4')
    assert c.delete(f'/api/tasks/{tid}').json['trashed']
    trashed = c.post(
        f'/api/canvas/media/{gen_id}/split',
        json={'mode': 'equal', 'segment_duration': 1.5},
    )
    assert trashed.status_code == 409 and trashed.json['code'] == 'media_trashed'

    # Source file missing on disk -> 409 file_missing
    media.media_path(media.get_media(src['id'])).unlink()
    file_missing = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.5},
    )
    assert file_missing.status_code == 409 and file_missing.json['code'] == 'file_missing'

    # Video too short (<= 0.4s) -> 400
    short_src = _upload_video(c, sample_videos['short_035s'], name='tiny.mp4')
    too_short = c.post(
        f"/api/canvas/media/{short_src['id']}/split",
        json={'mode': 'points', 'cut_points': [0.2]},
    )
    assert too_short.status_code == 400 and too_short.json['code'] == 'invalid_request'


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {'mode': 'unknown'},
        {'mode': 'points'},
        {'mode': 'points', 'cut_points': []},
        {'mode': 'points', 'cut_points': '1.0'},
        {'mode': 'points', 'cut_points': [True]},
        {'mode': 'points', 'cut_points': ['1.0']},
        {'mode': 'points', 'cut_points': [0.0]},
        {'mode': 'points', 'cut_points': [-1.0]},
        {'mode': 'points', 'cut_points': [0.1]},
        {'mode': 'points', 'cut_points': [0.15]},  # first segment < 0.2s
        {'mode': 'points', 'cut_points': [3.85]},  # last segment < 0.2s
        {'mode': 'points', 'cut_points': [4.0]},
        {'mode': 'points', 'cut_points': [5.0]},
        {'mode': 'points', 'cut_points': [2.0, 1.0]},  # not increasing
        {'mode': 'points', 'cut_points': [2.0, 2.0]},  # duplicate
        {'mode': 'points', 'cut_points': [1.0, 1.15]},  # middle segment < 0.2s
        {'mode': 'points', 'cut_points': [round(0.2 * i, 2) for i in range(1, 21)]},  # 21 segments > 20
        {'mode': 'equal'},
        {'mode': 'equal', 'segment_duration': True},
        {'mode': 'equal', 'segment_duration': '1.0'},
        {'mode': 'equal', 'segment_duration': 0},
        {'mode': 'equal', 'segment_duration': -1.0},
        {'mode': 'equal', 'segment_duration': 0.19},
        {'mode': 'equal', 'segment_duration': 4.0},
        {'mode': 'equal', 'segment_duration': 5.0},
        {'mode': 'equal', 'segment_duration': 3.85},  # tail < 0.2s merges into 1 segment
    ],
)
def test_split_parameter_validation_400(sample_videos, payload):
    c = client()
    src = _upload_video(c, sample_videos['av_4s'], name='params.mp4')
    res = c.post(f"/api/canvas/media/{src['id']}/split", json=payload)
    assert res.status_code == 400 and res.json['code'] == 'invalid_request', (payload, res.json)


def test_compute_segments_nan_inf_and_max_segments():
    for bad in (float('nan'), float('inf'), float('-inf')):
        with pytest.raises(media.MediaError) as exc1:
            video_split.compute_segments(4.0, {'mode': 'points', 'cut_points': [bad]})
        assert exc1.value.status == 400 and exc1.value.code == 'invalid_request'

        with pytest.raises(media.MediaError) as exc2:
            video_split.compute_segments(4.0, {'mode': 'equal', 'segment_duration': bad})
        assert exc2.value.status == 400 and exc2.value.code == 'invalid_request'

    # Equal mode exceeding MAX_SEGMENTS (20)
    with pytest.raises(media.MediaError) as exc_many:
        video_split.compute_segments(10.0, {'mode': 'equal', 'segment_duration': 0.2})
    assert exc_many.value.status == 400 and exc_many.value.code == 'invalid_request'

    # IEEE-754 float boundary: 0.6 / 0.2 -> 3 clean segments
    assert video_split.compute_segments(0.6, {'mode': 'equal', 'segment_duration': 0.2}) == [
        (0.0, 0.2), (0.2, 0.4), (0.4, 0.6)
    ]
    # Exact boundary: 4.0 / 0.2 -> 20 segments allowed
    segs_20 = video_split.compute_segments(4.0, {'mode': 'equal', 'segment_duration': 0.2})
    assert len(segs_20) == 20


def test_split_missing_ffmpeg_returns_503(sample_videos, monkeypatch):
    c = client()
    src = _upload_video(c, sample_videos['noaudio_3s'], name='no_ffmpeg.mp4')

    monkeypatch.setattr(video_split.shutil, 'which', lambda name: None)
    res = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.5},
    )
    assert res.status_code == 503 and res.json['code'] == 'ffmpeg_unavailable'


def test_split_temp_dir_cleaned_on_success_and_failure(sample_videos, monkeypatch, tmp_path):
    c = client()
    src = _upload_video(c, sample_videos['noaudio_3s'], name='cleanup.mp4')
    temp_root = tmp_path / 'split_tmp'
    temp_root.mkdir()
    orig_tempdir = tempfile.TemporaryDirectory

    created_dirs = []

    def tracked_tempdir(*args, **kwargs):
        kwargs['dir'] = str(temp_root)
        td = orig_tempdir(*args, **kwargs)
        created_dirs.append(Path(td.name))
        return td

    monkeypatch.setattr(video_split.tempfile, 'TemporaryDirectory', tracked_tempdir)

    # 1) Normal success cleans temp dir
    ok = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.5},
    )
    assert ok.status_code == 201
    assert len(created_dirs) == 1
    assert not created_dirs[0].exists()
    assert list(temp_root.iterdir()) == []

    count_before_fail = tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0]

    # 2) Failure on 2nd segment cleans temp dir and writes zero partial DB entries
    real_run = subprocess.run
    ffmpeg_calls = {'n': 0}

    def failing_run(cmd, *args, **kwargs):
        if Path(cmd[0]).name == 'ffmpeg':
            ffmpeg_calls['n'] += 1
            if ffmpeg_calls['n'] == 2:
                return subprocess.CompletedProcess(cmd, 1, b'', b'simulated encode failure')
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(video_split.subprocess, 'run', failing_run)
    fail = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'points', 'cut_points': [1.0, 2.0]},
    )
    assert fail.status_code == 500 and fail.json['code'] == 'split_failed'
    assert len(created_dirs) == 2
    assert not created_dirs[1].exists()
    assert list(temp_root.iterdir()) == []
    # No partial DB entries committed
    assert tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0] == count_before_fail
    # Source media still intact
    assert media.media_path(media.get_media(src['id'])).is_file()


def test_split_precheck_segment_size_limit_returns_413_with_zero_inserts(sample_videos, monkeypatch):
    c = client()
    src = _upload_video(c, sample_videos['noaudio_3s'], name='oversize.mp4')
    count_before = tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0]
    files_before = set(media.root().iterdir())

    # Set MAX_ASSET_BYTES tiny so the pre-check triggers before any save_upload call
    monkeypatch.setattr(store, 'MAX_ASSET_BYTES', 128)
    save_called = {'n': 0}
    real_save = media.save_upload

    def spy_save(*args, **kwargs):
        save_called['n'] += 1
        return real_save(*args, **kwargs)

    monkeypatch.setattr(video_split.media, 'save_upload', spy_save)

    res = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 1.5},
    )
    assert res.status_code == 413 and res.json['code'] == 'file_too_large'
    assert save_called['n'] == 0
    assert tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0] == count_before
    assert set(media.root().iterdir()) == files_before


def test_split_rollback_on_mid_save_failure_preserves_deduplicated_items(sample_videos, monkeypatch):
    c = client()
    src = _upload_video(c, sample_videos['av_4s'], name='atomic.mp4')

    # Case A: 1st segment newly created (deduplicated=False), 2nd segment save_upload fails
    # -> 1st segment DB row (media + media_metadata) and disk file must be rolled back completely.
    count_before = tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0]
    meta_before = tasks.get_db().execute('SELECT COUNT(*) FROM media_metadata').fetchone()[0]
    files_before = set(media.root().iterdir())

    real_save = media.save_upload
    calls_a = {'n': 0, 'created_id': None}

    def fail_on_second_a(*args, **kwargs):
        calls_a['n'] += 1
        if calls_a['n'] == 2:
            raise media.MediaError('模拟入库失败', 500, 'save_failed')
        item, dedup = real_save(*args, **kwargs)
        assert dedup is False
        calls_a['created_id'] = item['id']
        return item, dedup

    monkeypatch.setattr(video_split.media, 'save_upload', fail_on_second_a)
    res_a = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'points', 'cut_points': [1.5, 3.0]},
    )
    assert res_a.status_code == 500 and res_a.json['code'] == 'save_failed'
    assert calls_a['created_id'] is not None
    assert tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0] == count_before
    assert tasks.get_db().execute('SELECT COUNT(*) FROM media_metadata').fetchone()[0] == meta_before
    assert tasks.get_db().execute('SELECT 1 FROM media WHERE id=?', (calls_a['created_id'],)).fetchone() is None
    assert set(media.root().iterdir()) == files_before

    # Case B: pre-populate 1st segment so 1st hits deduplicated=True, 2nd creates new (deduplicated=False),
    # 3rd fails -> rollback removes ONLY 2nd segment; pre-existing 1st segment MUST remain untouched!
    monkeypatch.setattr(video_split.media, 'save_upload', real_save)
    seed = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'points', 'cut_points': [1.5]},
    )
    assert seed.status_code == 201
    existing_first_id = seed.json['segments'][0]['media_id']
    existing_first_file = media.media_path(media.get_media(existing_first_id))
    assert existing_first_file.is_file()

    count_before_b = tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0]
    files_before_b = set(media.root().iterdir())
    calls_b = {'n': 0, 'second_id': None}

    def fail_on_third_b(*args, **kwargs):
        calls_b['n'] += 1
        if calls_b['n'] == 3:
            raise media.MediaError('模拟第3段入库失败', 500, 'save_failed')
        item, dedup = real_save(*args, **kwargs)
        if calls_b['n'] == 1:
            assert dedup is True and item['id'] == existing_first_id
        elif calls_b['n'] == 2:
            assert dedup is False
            calls_b['second_id'] = item['id']
        return item, dedup

    monkeypatch.setattr(video_split.media, 'save_upload', fail_on_third_b)
    res_b = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'points', 'cut_points': [1.5, 2.7]},
    )
    assert res_b.status_code == 500 and res_b.json['code'] == 'save_failed'
    assert calls_b['second_id'] is not None
    # 2nd newly created item was rolled back
    assert tasks.get_db().execute('SELECT 1 FROM media WHERE id=?', (calls_b['second_id'],)).fetchone() is None
    assert tasks.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0] == count_before_b
    assert set(media.root().iterdir()) == files_before_b
    # Pre-existing deduplicated 1st item and its file are completely intact
    assert media.get_media(existing_first_id)['id'] == existing_first_id
    assert existing_first_file.is_file()


def test_split_deduplicated_items_unique_while_segments_keep_all(sample_videos):
    c = client()
    src = _upload_video(c, sample_videos['black_4s'], name='pure_black.mp4')
    res = c.post(
        f"/api/canvas/media/{src['id']}/split",
        json={'mode': 'equal', 'segment_duration': 2.0},
    )
    assert res.status_code == 201, res.json
    payload = res.json
    assert len(payload['segments']) == 2
    assert payload['segments'][0]['deduplicated'] is False
    assert payload['segments'][1]['deduplicated'] is True
    assert len(payload['items']) == 1
    assert payload['items'][0]['id'] == payload['segments'][0]['media_id'] == payload['segments'][1]['media_id']
