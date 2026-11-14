"""Cost estimates (never actual charges) for generation tasks.

The video formula mirrors client/src/lib/byteplusPricing.js
(`estimateBytePlusVideoCost`) so the ledger agrees with the canvas/tool
"预估 $x USD" labels. Keep both files in sync; tests compare fixed cases.

Image, audio and layer tasks have no price data in doc/price.md for the
providers we use, so they are reported as unknown — never as zero.
"""
from datetime import datetime, timezone
import json
import os
import subprocess

FPS = 24
UNKNOWN_REFERENCE_VIDEO_SECONDS = 5
FORMULA_VERSION = 1

OUTPUT_DIMENSIONS = {
    'seedance-2.0': {
        '480p': {'16:9': (864, 496), '4:3': (752, 560), '1:1': (640, 640),
                 '3:4': (560, 752), '9:16': (496, 864), '21:9': (992, 432)},
        '720p': {'16:9': (1280, 720), '4:3': (1112, 834), '1:1': (960, 960),
                 '3:4': (834, 1112), '9:16': (720, 1280), '21:9': (1470, 630)},
        '1080p': {'16:9': (1920, 1080), '4:3': (1664, 1248), '1:1': (1440, 1440),
                  '3:4': (1248, 1664), '9:16': (1080, 1920), '21:9': (2206, 946)},
    },
    'seedance-2.5': {
        '480p': {'16:9': (854, 480), '4:3': (752, 560), '1:1': (640, 640),
                 '3:4': (560, 752), '9:16': (480, 854), '21:9': (992, 432)},
        '720p': {'16:9': (1280, 720), '4:3': (1112, 834), '1:1': (960, 960),
                 '3:4': (834, 1112), '9:16': (720, 1280), '21:9': (1470, 630)},
        '1080p': {'16:9': (1920, 1080), '4:3': (1664, 1248), '1:1': (1440, 1440),
                  '3:4': (1248, 1664), '9:16': (1080, 1920), '21:9': (2206, 946)},
    },
}

STANDARD_UNIT_PRICE_USD = {
    '480p': (7.0, 4.3), '720p': (7.0, 4.3), '1080p': (7.7, 4.7),
}
FAST_UNIT_PRICE_USD = {
    '480p': (5.6, 3.3), '720p': (5.6, 3.3),
}
SEEDANCE_25_UNIT_PRICE_USD = {
    '480p': (10.70, 6.40), '720p': (10.70, 6.40), '1080p': (11.70, 7.00),
}
SEEDANCE_25_1080P_PROMOTION_FACTOR = 0.72
SEEDANCE_25_1080P_PROMOTION_START = datetime(2026, 8, 14, 6, tzinfo=timezone.utc)
SEEDANCE_25_1080P_PROMOTION_END = datetime(2026, 9, 17, 6, tzinfo=timezone.utc)

VIDEO_PROVIDERS = {'ark', 'cupsy'}  # Cupsy is billed at BytePlus rates (user 2026-11-12).
VIDEO_MODELS = {'seedance-2.0', 'seedance-2.5', 'seedance-2.5-moderated'}

UNKNOWN_REASONS = {
    'no_price_data': '无价格资料',
    'no_estimate_snapshot': '历史任务未存估算，且参数不足以推算',
    'unknown_provider': 'Provider 未知',
}


def _number(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def _output_duration_range(model, duration):
    if _number(duration) != -1:
        seconds = _number(duration, 0)
        return seconds, seconds
    return (4, 30) if model == 'seedance-2.5' else (4, 15)


def _reference_video_seconds(model, durations):
    if not durations:
        return 0, False
    assumed = False
    total = 0
    for duration in durations:
        value = _number(duration)
        if value is not None and value > 0:
            total += value
        else:
            assumed = True
            total += UNKNOWN_REFERENCE_VIDEO_SECONDS
    max_seconds = 30 if model == 'seedance-2.5' else 15
    return min(max_seconds, max(4, total)), assumed


def _tokens(seconds, width, height):
    return seconds * width * height * FPS / 1024


def estimate_video_cost(model='seedance-2.0', provider='ark', resolution='720p', ratio='adaptive',
                        duration=5, fast=False, reference_video_durations=(), now=None):
    """Port of estimateBytePlusVideoCost. `reference_video_durations` is a list of
    seconds (None for unknown, counted as 5s like the client)."""
    model = 'seedance-2.5' if model in ('seedance-2.5', 'seedance-2.5-moderated') else 'seedance-2.0'
    by_ratio = OUTPUT_DIMENSIONS[model].get(resolution) or OUTPUT_DIMENSIONS[model]['720p']
    ratio_assumed = ratio not in by_ratio
    billed_ratio = '16:9' if ratio_assumed else ratio
    width, height = by_ratio[billed_ratio]
    durations = list(reference_video_durations or [])
    input_seconds, input_assumed = _reference_video_seconds(model, durations)
    has_video = bool(durations)
    use_fast = model == 'seedance-2.0' and bool(fast)
    table = SEEDANCE_25_UNIT_PRICE_USD if model == 'seedance-2.5' else (
        FAST_UNIT_PRICE_USD if use_fast else STANDARD_UNIT_PRICE_USD)
    row = table.get(resolution) or table['720p']
    list_unit_price = row[1] if has_video else row[0]
    now = now or datetime.now(timezone.utc)
    promotion = (model == 'seedance-2.5' and provider == 'ark' and resolution == '1080p'
                 and SEEDANCE_25_1080P_PROMOTION_START <= now < SEEDANCE_25_1080P_PROMOTION_END)
    factor = SEEDANCE_25_1080P_PROMOTION_FACTOR if promotion else 1
    unit_price = list_unit_price * factor
    min_out, max_out = _output_duration_range(model, duration)
    min_tokens = _tokens(input_seconds + min_out, width, height)
    max_tokens = _tokens(input_seconds + max_out, width, height)
    return {
        'model': model, 'width': width, 'height': height, 'fps': FPS,
        'billed_ratio': billed_ratio, 'ratio_assumed': ratio_assumed,
        'has_video': has_video, 'reference_video_count': len(durations),
        'input_video_seconds': input_seconds, 'input_duration_assumed': input_assumed,
        'minimum_output_seconds': min_out, 'maximum_output_seconds': max_out,
        'minimum_tokens': min_tokens, 'maximum_tokens': max_tokens,
        'currency': 'USD', 'list_unit_price': list_unit_price, 'unit_price': unit_price,
        'discount_factor': factor, 'promotion_active': promotion,
        'minimum_cost': min_tokens / 1_000_000 * unit_price,
        'maximum_cost': max_tokens / 1_000_000 * unit_price,
    }


_duration_cache = {}


def probe_duration(path):
    """Local-file container duration via ffprobe (no network protocols); None if unknown."""
    if not path or not isinstance(path, str) or not os.path.isfile(path):
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key in _duration_cache:
        return _duration_cache[key]
    value = None
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-protocol_whitelist', 'file',
             '-show_entries', 'format=duration', '-of', 'json', path],
            capture_output=True, timeout=5, check=False)
        value = _number(json.loads(result.stdout or '{}').get('format', {}).get('duration'))
        if value is not None and value <= 0:
            value = None
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        value = None
    if len(_duration_cache) > 2048:
        _duration_cache.clear()
    _duration_cache[key] = value
    return value


def _upload_video_path(url):
    if not isinstance(url, str) or '/api/upload_video/' not in url:
        return None
    import storage
    return os.path.join(storage.UPLOAD_VIDEO_DIR, os.path.basename(url.rsplit('/api/upload_video/', 1)[-1]))


def reference_video_durations(task, db):
    """Durations of the reference videos the task actually sent (None = unknown)."""
    params = task.get('params') or {}
    if params.get('video_mode') == 'keyframe':
        return []
    if task.get('provider') == 'cupsy':
        rows = db.execute(
            '''SELECT pa.local_path FROM task_provider_assets tpa
               JOIN provider_assets pa ON pa.id = tpa.provider_asset_id
               WHERE tpa.task_id = ? AND tpa.role = 'reference_video'
               ORDER BY tpa.position''', (task['id'],)).fetchall()
        return [probe_duration(row['local_path']) for row in rows]
    urls = params.get('ref_video_urls') or []
    paths = [p for p in (params.get('ref_video_paths') or []) if isinstance(p, str)]
    if not isinstance(urls, list):
        urls = []
    durations = []
    used = set()
    for index, url in enumerate(urls):
        path = _upload_video_path(url)
        if path is None and index < len(paths) and paths[index] not in used:
            path = paths[index]
        if path:
            used.add(path)
        durations.append(probe_duration(path))
    # Uploaded files are always echoed in ref_video_urls; count stray paths only if urls are missing.
    if not urls:
        durations.extend(probe_duration(p) for p in paths)
    return durations


def _parse_time(value):
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def compute_task_estimate(task, db):
    """Return {'status': 'estimate', ...} or {'status': 'unknown', 'reason': ...}."""
    task_type = task.get('type')
    if task_type != 'video':
        return {'status': 'unknown', 'reason': 'no_price_data'}
    provider = task.get('provider')
    if provider not in VIDEO_PROVIDERS:
        return {'status': 'unknown', 'reason': 'unknown_provider'}
    params = task.get('params') or {}
    model = params.get('model')
    resolution = params.get('resolution')
    duration = _number(params.get('duration'))
    if model not in VIDEO_MODELS or resolution not in ('480p', '720p', '1080p') or duration is None \
            or (duration != -1 and duration <= 0):
        return {'status': 'unknown', 'reason': 'no_estimate_snapshot'}
    estimate = estimate_video_cost(
        model=model, provider=provider, resolution=resolution, ratio=params.get('ratio') or 'adaptive',
        duration=duration, fast=bool(params.get('fast')),
        reference_video_durations=reference_video_durations(task, db),
        now=_parse_time(task.get('created_at')) or datetime.now(timezone.utc),
    )
    return {'status': 'estimate', 'formula_version': FORMULA_VERSION, **estimate}


def store_snapshot(task_id):
    """Persist the submission-time estimate into params.cost_estimate if not set.

    Best effort: never raises, never blocks a submission. Writes atomically with
    json_set so concurrent params updates are not clobbered.
    """
    import tasks as task_db
    try:
        task = task_db.get_task(task_id)
        if not task or (task.get('params') or {}).get('cost_estimate'):
            return None
        db = task_db.get_db()
        snapshot = compute_task_estimate(task, db)
        snapshot['computed_at'] = task_db.utcnow()
        db.execute(
            '''UPDATE tasks SET params = json_set(COALESCE(params, '{}'), '$.cost_estimate', json(?))
               WHERE id = ? AND json_valid(COALESCE(params, '{}'))
                 AND json_extract(COALESCE(params, '{}'), '$.cost_estimate') IS NULL''',
            (json.dumps(snapshot, ensure_ascii=False), task_id))
        db.commit()
        return snapshot
    except Exception:
        try:
            task_db.get_db().rollback()
        except Exception:
            pass
        return None


def task_estimate(task, db):
    """Snapshot if stored (basis=snapshot), else derived from params (basis=derived)."""
    snapshot = (task.get('params') or {}).get('cost_estimate')
    if isinstance(snapshot, dict) and snapshot.get('status') in ('estimate', 'unknown'):
        return {**snapshot, 'basis': 'snapshot'}
    derived = compute_task_estimate(task, db)
    return {**derived, 'basis': 'derived'}
