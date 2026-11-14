"""Cost estimates (never actual charges) for generation tasks.

The video formula mirrors client/src/lib/byteplusPricing.js
(`estimateBytePlusVideoCost`) so the ledger agrees with the canvas/tool
"预估 $x USD" labels. Keep both files in sync; tests compare fixed cases.

Images and layer decomposition follow the BytePlus per-image price table
(IMAGE-COST-20261114; mirrors `estimateBytePlusImageCost` in the same client
file). Audio has no price data and is reported as unknown — never as zero.
"""
from datetime import datetime, timezone
import json
import os
import subprocess

FPS = 24
UNKNOWN_REFERENCE_VIDEO_SECONDS = 5
FORMULA_VERSION = 1
IMAGE_FORMULA_VERSION = 1

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
    'below_price_floor': '输出像素低于官方定价下限',
    'above_price_ceiling': '输出像素超出官方定价档',
    'layer_count_unknown': '图层数量未知（按实际层数计）',
    'layer_outputs_unknown': '图层输出尺寸不可读',
}

# ---- Images (USD per image; P = output pixels of one image). BytePlus model pricing,
# read 2026-11-14. Cupsy seedream-5.0-pro is billed at the BytePlus 5.0 pro rate (user 2026-11-12).
SEEDREAM_55 = 'seedream-5.5'
SEEDREAM_50_PRO = 'seedream-5.0-pro'
IMAGE_PRICING = {
    # Seedream 5.5 lists one output table; its layer outputs are billed per layer by
    # actual tier ("each layer ... billed based on the actual generated output").
    SEEDREAM_55: {
        'input_unit_price': 0.008, 'free_input_images': 0,
        'single': ((921_600, 2_601_123.84, 0.020), (2_601_123.84, 4_624_220.16, 0.035)),
        'layer': ((921_600, 2_601_123.84, 0.020), (2_601_123.84, 4_624_220.16, 0.035)),
    },
    SEEDREAM_50_PRO: {
        'input_unit_price': 0.003, 'free_input_images': 1,
        'single': ((0, 2_610_000, 0.045), (2_610_000, None, 0.09)),
        'layer': ((0, 2_610_000, 0.0225), (2_610_000, None, 0.045)),
    },
}
# Nominal sizes when the output size is not fixed before generation (ratio=auto).
NOMINAL_IMAGE_SIZE = {'1K': (1024, 1024), '1.5K': (1536, 1536), '2K': (2048, 2048)}
IMAGE_SIZE_MAP = {  # mirrors app.ARK_SEEDREAM_PRO_SIZE_MAP / CUPSY_SEEDREAM_SIZE_MAP / seedream55.SIZES
    'ark': {
        '1K': {'1:1': (1024, 1024), '4:3': (1152, 864), '3:4': (864, 1152), '16:9': (1424, 800),
               '9:16': (800, 1424), '3:2': (1248, 832), '2:3': (832, 1248), '21:9': (1568, 672)},
        '1.5K': {'1:1': (1536, 1536), '4:3': (1792, 1344), '3:4': (1344, 1792), '16:9': (2048, 1152),
                 '9:16': (1152, 2048), '3:2': (1872, 1248), '2:3': (1248, 1872), '21:9': (2352, 1008)},
        '2K': {'1:1': (2048, 2048), '4:3': (2368, 1776), '3:4': (1776, 2368), '16:9': (2816, 1584),
               '9:16': (1584, 2816), '3:2': (2496, 1664), '2:3': (1664, 2496), '21:9': (3136, 1344)},
    },
    'cupsy': {
        '1K': {'1:1': (1024, 1024), '4:3': (1152, 864), '3:4': (864, 1152), '16:9': (1280, 720), '9:16': (720, 1280)},
        '2K': {'1:1': (2048, 2048), '4:3': (2304, 1728), '3:4': (1728, 2304), '16:9': (2560, 1440), '9:16': (1440, 2560)},
    },
}
IMAGE_PROVIDERS = {'ark', 'cupsy'}
# Assumption tag when layers below the lowest tier are billed at that tier (shown as 推算).
LAYER_BELOW_FLOOR_ASSUMPTION = 'below_floor_min_tier'
SEEDREAM_55_ALIASES = {'dola-seedream-5-5-261028', 'seedream-5.5', 'seedream-5-5', 'dola-seedream-5-5'}


def image_output_unit_price(family, pixels, layer=False):
    """(unit_price, tier_index) or (None, reason) for one output image of `pixels`."""
    tiers = IMAGE_PRICING[family]['layer' if layer else 'single']
    if pixels < tiers[0][0]:
        return None, 'below_price_floor'
    for index, (low, high, price) in enumerate(tiers):
        if (index == 0 or pixels > low) and (high is None or pixels <= high):
            return price, index
    return None, 'above_price_ceiling'


def image_input_cost(family, reference_count):
    pricing = IMAGE_PRICING[family]
    billed = max(0, int(reference_count) - pricing['free_input_images'])
    return billed * pricing['input_unit_price']


def estimate_image_cost(family=SEEDREAM_50_PRO, width=1024, height=1024, reference_count=0,
                        size_assumed=False):
    """Port of estimateBytePlusImageCost: one output image plus billed reference images."""
    family = SEEDREAM_55 if family == SEEDREAM_55 else SEEDREAM_50_PRO
    pixels = int(width) * int(height)
    unit, tier = image_output_unit_price(family, pixels)
    base = {'model': family, 'width': int(width), 'height': int(height), 'pixels': pixels,
            'size_assumed': bool(size_assumed), 'reference_count': int(reference_count),
            'input_unit_price': IMAGE_PRICING[family]['input_unit_price'],
            'free_input_images': IMAGE_PRICING[family]['free_input_images'], 'currency': 'USD'}
    if unit is None:
        return {**base, 'known': False, 'reason': tier}
    input_cost = image_input_cost(family, reference_count)
    total = input_cost + unit
    return {**base, 'known': True, 'tier': tier, 'output_unit_price': unit, 'output_count': 1,
            'input_cost': input_cost, 'output_cost': unit, 'minimum_cost': total, 'maximum_cost': total}


def estimate_layer_unit_price(family=SEEDREAM_50_PRO, size='auto'):
    """Per-layer price before submission; 1K/1.5K fix the low tier, 2K/Auto may span both."""
    family = SEEDREAM_55 if family == SEEDREAM_55 else SEEDREAM_50_PRO
    tiers = IMAGE_PRICING[family]['layer']
    low, high = tiers[0][2], tiers[-1][2]
    fixed_low = str(size).upper() in ('1K', '1.5K')
    return {'model': family, 'size': size, 'per_layer_min': low, 'per_layer_max': low if fixed_low else high,
            'input_cost': image_input_cost(family, 1), 'currency': 'USD'}


def estimate_layer_outputs_cost(family, output_sizes, reference_count=1):
    """Actual layer outputs (base image included): Σ per-layer tier price + input."""
    family = SEEDREAM_55 if family == SEEDREAM_55 else SEEDREAM_50_PRO
    floor_price = IMAGE_PRICING[family]['layer'][0][2]
    output_cost, below_floor = 0, 0
    for width, height in output_sizes:
        unit, tier = image_output_unit_price(family, int(width) * int(height), layer=True)
        if unit is None and tier == 'below_price_floor':
            # User 2026-11-14: a layer below the lowest listed tier is billed at that tier (推算).
            unit, below_floor = floor_price, below_floor + 1
        if unit is None:
            return {'known': False, 'reason': tier, 'model': family, 'output_count': len(output_sizes)}
        output_cost += unit
    input_cost = image_input_cost(family, reference_count)
    total = input_cost + output_cost
    result = {'known': True, 'model': family, 'output_count': len(output_sizes), 'input_cost': input_cost,
              'output_cost': output_cost, 'minimum_cost': total, 'maximum_cost': total,
              'below_floor_layers': below_floor}
    if below_floor:
        result['assumption'] = LAYER_BELOW_FLOOR_ASSUMPTION
    return result


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


def _image_family(task, params):
    if task.get('provider') == 'cupsy':
        return SEEDREAM_50_PRO
    if params.get('seedream55') is True or 'layer_decomposition_options' in params:
        return SEEDREAM_55
    if params.get('seedream55') is False:
        return SEEDREAM_50_PRO
    return SEEDREAM_55 if str(params.get('model') or '').lower() in SEEDREAM_55_ALIASES else SEEDREAM_50_PRO


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 and str(number) == str(value).strip() else None


def _image_size(provider, params):
    """(width, height, size_assumed) of the requested output, or None."""
    size = params.get('size')
    if isinstance(size, str) and 'x' in size:
        width, _, height = size.partition('x')
        width, height = _positive_int(width), _positive_int(height)
        if width and height:
            return width, height, False
    if isinstance(size, str) and size.upper() in NOMINAL_IMAGE_SIZE:
        return (*NOMINAL_IMAGE_SIZE[size.upper()], True)
    ratio = str(params.get('aspect_ratio') or '').strip().lower()
    if ratio == 'custom':
        width, height = _positive_int(params.get('custom_width')), _positive_int(params.get('custom_height'))
        return (width, height, False) if width and height else None
    resolution = str(params.get('resolution') or '').upper()
    if ratio == 'auto' and resolution in NOMINAL_IMAGE_SIZE:
        return (*NOMINAL_IMAGE_SIZE[resolution], True)
    dimensions = IMAGE_SIZE_MAP.get(provider, {}).get(resolution, {}).get(ratio)
    return (*dimensions, False) if dimensions else None


def _input_image_count(task, db):
    row = db.execute("SELECT COUNT(*) FROM task_assets WHERE task_id = ? AND kind = 'input_image'",
                     (task['id'],)).fetchone()
    return int(row[0] or 0)


def _image_task_estimate(task, db):
    provider = task.get('provider')
    if not provider:
        return {'status': 'unknown', 'reason': 'unknown_provider'}
    if provider not in IMAGE_PROVIDERS:
        return {'status': 'unknown', 'reason': 'no_price_data'}
    params = task.get('params') or {}
    size = _image_size(provider, params)
    if not size:
        return {'status': 'unknown', 'reason': 'no_estimate_snapshot'}
    estimate = estimate_image_cost(_image_family(task, params), size[0], size[1],
                                   _input_image_count(task, db), size_assumed=size[2])
    known = estimate.pop('known')
    if not known:
        return {'status': 'unknown', **estimate}
    return {'status': 'estimate', 'formula_version': IMAGE_FORMULA_VERSION, **estimate}


def _layer_output_sizes(task, db):
    """Width/height of every output layer (base image included), or None if unreadable."""
    row = db.execute('SELECT document FROM layer_revisions WHERE task_id = ?', (task['id'],)).fetchone()
    try:
        layers = json.loads(row['document'] or '{}').get('layers') if row else None
    except (TypeError, ValueError, AttributeError):
        layers = None
    if not isinstance(layers, list) or not layers:
        return None
    sizes = []
    for layer in layers:
        width = _positive_int(layer.get('width')) if isinstance(layer, dict) else None
        height = _positive_int(layer.get('height')) if isinstance(layer, dict) else None
        if not width or not height:
            return None
        sizes.append((width, height))
    return sizes


def _layer_task_estimate(task, db, family=None):
    params = task.get('params') or {}
    if task.get('provider') not in (None, 'ark'):
        return {'status': 'unknown', 'reason': 'no_price_data'}
    family = family if family in IMAGE_PRICING else _image_family({'provider': 'ark'}, params)
    unit = estimate_layer_unit_price(family, params.get('size') or 'auto')
    if task.get('status') != 'succeeded':
        return {'status': 'unknown', 'reason': 'layer_count_unknown', **unit}
    sizes = _layer_output_sizes(task, db)
    if not sizes:
        return {'status': 'unknown', 'reason': 'layer_outputs_unknown', **unit}
    estimate = estimate_layer_outputs_cost(family, sizes, reference_count=1)
    if not estimate.pop('known'):
        return {'status': 'unknown', **unit, **estimate}
    return {'status': 'estimate', 'formula_version': IMAGE_FORMULA_VERSION, **unit, **estimate}


def compute_task_estimate(task, db):
    """Return {'status': 'estimate', ...} or {'status': 'unknown', 'reason': ...}."""
    task_type = task.get('type')
    if task_type == 'image':
        return _image_task_estimate(task, db)
    if task_type == 'layer':
        return _layer_task_estimate(task, db)
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
        if task.get('type') == 'layer':
            # Layer count is only known after the run: freeze the per-layer price basis.
            params = task.get('params') or {}
            snapshot = {'status': 'per_layer', 'formula_version': IMAGE_FORMULA_VERSION,
                        **estimate_layer_unit_price(_image_family({'provider': 'ark'}, params),
                                                    params.get('size') or 'auto')}
        else:
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
    if task.get('type') == 'layer':
        # Billed per actual output layer: the snapshot fixes the model, outputs give the count.
        frozen = isinstance(snapshot, dict) and snapshot.get('status') == 'per_layer'
        estimate = _layer_task_estimate(task, db, snapshot.get('model') if frozen else None)
        return {**estimate, 'basis': 'snapshot' if frozen else 'derived'}
    if isinstance(snapshot, dict) and snapshot.get('status') in ('estimate', 'unknown'):
        return {**snapshot, 'basis': 'snapshot'}
    derived = compute_task_estimate(task, db)
    return {**derived, 'basis': 'derived'}
