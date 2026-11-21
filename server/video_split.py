"""Video splitting for the global local media library (VIDEO-SPLIT-API-20261122).

Supports timeline cut-point splitting (``mode='points'``) and equal-duration
splitting (``mode='equal'``). Every split segment is encoded into an isolated
temporary directory and then registered as an independent media item via
``media_library.save_upload``; the source media row and file are never modified.
"""
import json
import logging
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import canvas_store as store
import media_library as media
import tasks

LOG = logging.getLogger(__name__)

MIN_SEGMENT_SECONDS = 0.2
MAX_SEGMENTS = 20
FFMPEG_TIMEOUT_SECONDS = 120
_FFPROBE_TIMEOUT_SECONDS = 30
_MIN_SOURCE_DURATION = 0.4
_EPS = 1e-9
_MAX_STEM_LEN = 220


def _require_tools():
    ffmpeg_bin = shutil.which('ffmpeg')
    ffprobe_bin = shutil.which('ffprobe')
    if not ffmpeg_bin or not ffprobe_bin:
        raise media.MediaError(
            '服务器未安装 ffmpeg/ffprobe，暂不支持视频分割',
            503,
            'ffmpeg_unavailable',
        )
    return ffmpeg_bin, ffprobe_bin


def probe_video_duration(src_path, ffprobe_bin=None):
    """Probe the positive finite duration (seconds) of a local video file via ffprobe."""
    ffprobe = ffprobe_bin or shutil.which('ffprobe')
    if not ffprobe:
        raise media.MediaError(
            '服务器未安装 ffmpeg/ffprobe，暂不支持视频分割',
            503,
            'ffmpeg_unavailable',
        )
    cmd = [
        ffprobe,
        '-v', 'error',
        '-protocol_whitelist', 'file',
        '-show_entries', 'format=duration:stream=codec_type,duration',
        '-of', 'json',
        str(src_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=_FFPROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        LOG.warning('ffprobe failed for %s: %s', src_path.name, error)
        raise media.MediaError('无法读取视频时长，请检查视频格式', 400, 'invalid_request') from error

    if result.returncode != 0 or not result.stdout:
        raise media.MediaError('无法读取视频时长，请检查视频格式', 400, 'invalid_request')

    try:
        payload = json.loads(result.stdout)
    except ValueError as error:
        raise media.MediaError('无法读取视频时长，请检查视频格式', 400, 'invalid_request') from error

    duration = None
    fmt_dur = (payload.get('format') or {}).get('duration')
    if fmt_dur is not None:
        try:
            val = float(fmt_dur)
            if math.isfinite(val) and val > 0:
                duration = val
        except (TypeError, ValueError):
            pass

    if duration is None:
        for stream in payload.get('streams') or []:
            if not isinstance(stream, dict):
                continue
            if stream.get('duration') is None:
                continue
            try:
                val = float(stream['duration'])
                if math.isfinite(val) and val > 0:
                    duration = val
                    if stream.get('codec_type') == 'video':
                        break
            except (TypeError, ValueError):
                continue

    if duration is None or not math.isfinite(duration) or duration <= _MIN_SOURCE_DURATION:
        raise media.MediaError(
            f'视频时长不足（需大于 {_MIN_SOURCE_DURATION} 秒），无法分割',
            400,
            'invalid_request',
        )
    rounded = round(duration, 3)
    if rounded <= _MIN_SOURCE_DURATION:
        raise media.MediaError(
            f'视频时长不足（需大于 {_MIN_SOURCE_DURATION} 秒），无法分割',
            400,
            'invalid_request',
        )
    return rounded


def _parse_number(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise media.MediaError(f'{field_name} 须为有效数值', 400, 'invalid_request')
    number = float(value)
    if not math.isfinite(number):
        raise media.MediaError(f'{field_name} 须为有限数值', 400, 'invalid_request')
    return number


def compute_segments(duration, data):
    """Validate split parameters against ``duration`` and return ``[(start, end), ...]``."""
    if not isinstance(data, dict):
        raise media.MediaError('请求参数格式无效', 400, 'invalid_request')
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or duration <= _MIN_SOURCE_DURATION:
        raise media.MediaError(
            f'视频时长不足（需大于 {_MIN_SOURCE_DURATION} 秒），无法分割',
            400,
            'invalid_request',
        )

    mode = data.get('mode')
    if mode not in ('points', 'equal'):
        raise media.MediaError('分割模式仅支持 points 或 equal', 400, 'invalid_request')

    if mode == 'points':
        raw_points = data.get('cut_points')
        if not isinstance(raw_points, list) or not raw_points:
            raise media.MediaError('请提供至少一个切点 cut_points', 400, 'invalid_request')
        if len(raw_points) + 1 > MAX_SEGMENTS:
            raise media.MediaError(
                f'最多支持一次分割为 {MAX_SEGMENTS} 个片段',
                400,
                'invalid_request',
            )
        points = []
        prev = None
        for raw_pt in raw_points:
            pt = _parse_number(raw_pt, 'cut_points')
            if pt <= 0.1 or pt >= duration - 0.1:
                raise media.MediaError('切点超出有效时间范围', 400, 'invalid_request')
            if prev is not None and pt <= prev:
                raise media.MediaError('切点必须严格递增且不可重复', 400, 'invalid_request')
            points.append(pt)
            prev = pt

        boundaries = [0.0, *points, float(duration)]
        segments = []
        for idx in range(len(boundaries) - 1):
            start = boundaries[idx]
            end = boundaries[idx + 1]
            if end - start < MIN_SEGMENT_SECONDS - _EPS:
                raise media.MediaError(
                    f'每个分段时长不得小于 {MIN_SEGMENT_SECONDS} 秒',
                    400,
                    'invalid_request',
                )
            start_r = round(start, 3)
            end_r = round(end, 3)
            if end_r - start_r < MIN_SEGMENT_SECONDS - _EPS:
                raise media.MediaError(
                    f'每个分段时长不得小于 {MIN_SEGMENT_SECONDS} 秒',
                    400,
                    'invalid_request',
                )
            segments.append((start_r, end_r))

        if len(segments) < 2 or len(segments) > MAX_SEGMENTS:
            raise media.MediaError(
                f'分段数量须在 2 至 {MAX_SEGMENTS} 之间',
                400,
                'invalid_request',
            )
        return segments

    # mode == 'equal'
    if 'segment_duration' not in data:
        raise media.MediaError('请提供单段时长 segment_duration', 400, 'invalid_request')
    seg_dur = _parse_number(data.get('segment_duration'), 'segment_duration')
    if seg_dur < MIN_SEGMENT_SECONDS:
        raise media.MediaError(
            f'单段时长不得小于 {MIN_SEGMENT_SECONDS} 秒',
            400,
            'invalid_request',
        )
    if seg_dur >= duration:
        raise media.MediaError('单段时长需小于视频总时长', 400, 'invalid_request')

    segments = []
    start = 0.0
    total = float(duration)
    while start < total - _EPS:
        end = min(total, round(start + seg_dur, 3))
        if total - end < MIN_SEGMENT_SECONDS - _EPS:
            end = total
        start_r = round(start, 3)
        end_r = round(end, 3)
        if end_r <= start_r:
            break
        segments.append((start_r, end_r))
        if len(segments) > MAX_SEGMENTS:
            raise media.MediaError(
                f'最多支持一次分割为 {MAX_SEGMENTS} 个片段，请调大单段时长',
                400,
                'invalid_request',
            )
        start = end

    if len(segments) < 2:
        raise media.MediaError('单段时长需小于视频总时长', 400, 'invalid_request')
    return segments


def _resolve_target_folder_id(row):
    folder_id = row.get('folder_id')
    if not folder_id:
        return None
    db = tasks.get_db()
    folder = db.execute(
        'SELECT id, system_key FROM media_folders WHERE id=?',
        (folder_id,),
    ).fetchone()
    if folder is None or folder['system_key'] is not None:
        return None
    return folder['id']


def _safe_stem(name):
    stem = Path(name or 'video').stem.strip()
    stem = ''.join(ch for ch in stem if ch not in '/\\' and ord(ch) >= 32).strip()
    if not stem:
        stem = 'video'
    return stem[:_MAX_STEM_LEN]


def _encode_segment(ffmpeg_bin, src_path, out_path, start, end, media_id, index):
    cmd = [
        ffmpeg_bin,
        '-hide_banner',
        '-v', 'error',
        '-y',
        '-protocol_whitelist', 'file',
        '-ss', f'{start:.3f}',
        '-to', f'{end:.3f}',
        '-i', str(src_path),
        '-map', '0:v:0',
        '-map', '0:a?',
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-crf', '18',
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-movflags', '+faststart',
        '-avoid_negative_ts', 'make_zero',
        str(out_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        LOG.warning('ffmpeg split timeout for media=%s segment=%d', media_id, index)
        raise media.MediaError('视频分割超时，请缩短片段或稍后重试', 500, 'split_failed') from error
    except OSError as error:
        LOG.warning('ffmpeg split os error for media=%s segment=%d: %s', media_id, index, error)
        raise media.MediaError('视频分割失败，请检查视频格式后重试', 500, 'split_failed') from error

    if result.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        err_snippet = (result.stderr or b'').decode('utf-8', errors='replace').strip()[:300]
        LOG.warning(
            'ffmpeg split failed for media=%s segment=%d rc=%s stderr=%s',
            media_id, index, result.returncode, err_snippet,
        )
        raise media.MediaError('视频分割失败，请检查视频格式后重试', 500, 'split_failed')


def _rollback_created_media(created_records):
    """Best-effort rollback for newly created media rows & files on mid-split save failure.

    Only records with ``deduplicated is False`` are passed here; pre-existing items
    matched via deduplication are never touched.
    """
    if not created_records:
        return
    media_root = media.root().resolve()
    files_to_remove = []
    ids_to_remove = [mid for mid, _ in created_records]
    try:
        with store.write_transaction() as db:
            marks = ','.join('?' * len(ids_to_remove))
            db_relpaths = {
                r['id']: r['relpath']
                for r in db.execute(
                    f'SELECT id, relpath FROM media WHERE id IN ({marks})',
                    ids_to_remove,
                ).fetchall()
            }
            for mid, relpath in created_records:
                rp = db_relpaths.get(mid) or relpath
                if rp:
                    files_to_remove.append(media_root / rp)
                files_to_remove.append(media.video_thumbnail_path(mid))
            db.execute(f'DELETE FROM media_metadata WHERE media_id IN ({marks})', ids_to_remove)
            db.execute(f'DELETE FROM media_aliases WHERE media_id IN ({marks})', ids_to_remove)
            db.execute(f'DELETE FROM media WHERE id IN ({marks})', ids_to_remove)
    except Exception:
        LOG.exception('Failed to rollback DB records for aborted video split: %s', ids_to_remove)
        for mid, relpath in created_records:
            if relpath:
                files_to_remove.append(media_root / relpath)
            files_to_remove.append(media.video_thumbnail_path(mid))

    for file_path in files_to_remove:
        try:
            resolved = file_path.resolve()
            if resolved.is_relative_to(media_root):
                resolved.unlink(missing_ok=True)
        except OSError:
            LOG.warning('Failed to remove rolled-back split file: %s', file_path)


def split_video_media(media_id, data):
    """Split a video media item into new library items without modifying the source."""
    row = media.get_media(media_id)
    if row['kind'] != 'video':
        raise media.MediaError('只支持分割视频素材', 400, 'invalid_request')

    src_path = media.media_path(row).resolve()
    media_root = media.root().resolve()
    if not src_path.is_relative_to(media_root) or not src_path.is_file():
        raise media.MediaError('素材文件不可读取', 409, 'file_missing')

    ffmpeg_bin, ffprobe_bin = _require_tools()
    duration = probe_video_duration(src_path, ffprobe_bin=ffprobe_bin)
    segments = compute_segments(duration, data)
    target_folder_id = _resolve_target_folder_id(row)
    stem = _safe_stem(row.get('name'))
    width = 2 if len(segments) >= 10 else 1

    with tempfile.TemporaryDirectory(prefix='ink-video-split-') as tmp_dir:
        tmp_root = Path(tmp_dir)
        rendered = []
        # Cut all segments first so a mid-way ffmpeg failure leaves zero partial DB entries.
        for idx, (start, end) in enumerate(segments, start=1):
            filename = f'{stem}_片段{idx:0{width}d}.mp4'
            out_path = tmp_root / f'seg_{idx:02d}.mp4'
            _encode_segment(ffmpeg_bin, src_path, out_path, start, end, row['id'], idx)
            rendered.append((idx, start, end, filename, out_path))

        # Pre-check every rendered segment size before registering any item in the library.
        for _idx, _start, _end, _filename, out_path in rendered:
            if out_path.stat().st_size > store.MAX_ASSET_BYTES:
                raise media.MediaError('分割片段超过单文件大小限制', 413, 'file_too_large')

        items = []
        seen_item_ids = set()
        segment_results = []
        created_records = []
        try:
            for idx, start, end, filename, out_path in rendered:
                with out_path.open('rb') as fp:
                    item, deduplicated = media.save_upload(
                        fp,
                        filename,
                        folder_id=target_folder_id,
                        origin='save_as',
                    )
                if not deduplicated:
                    saved = tasks.get_db().execute(
                        'SELECT relpath FROM media WHERE id=?',
                        (item['id'],),
                    ).fetchone()
                    created_records.append((item['id'], saved['relpath'] if saved else None))
                if item['id'] not in seen_item_ids:
                    seen_item_ids.add(item['id'])
                    items.append(item)
                segment_results.append({
                    'index': idx,
                    'start': start,
                    'end': end,
                    'duration': round(end - start, 3),
                    'media_id': item['id'],
                    'deduplicated': deduplicated,
                })
        except Exception:
            _rollback_created_media(created_records)
            raise

    return {
        'source_id': row['id'],
        'duration': duration,
        'items': items,
        'segments': segment_results,
    }
