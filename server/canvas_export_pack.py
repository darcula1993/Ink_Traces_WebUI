"""One-click canvas scene asset pack export (V24-W3-EXPORT-PACK-20261121).

Read-only preview and streaming ZIP_STORED pack export for a canvas workflow:
- POST /api/canvas/workflows/<workflow_id>/export-pack/preview
- POST /api/canvas/workflows/<workflow_id>/export-pack

Security and scope boundaries:
- Resolves files strictly through global media_library / canvas_media_refs /
  canvas_store within verified asset directories; never reads outside paths or
  follows symlinks; skips deleted, trashed, missing, or unsafe entries.
- Strips/masks all credentials, Bearer tokens, signed URLs / signature query
  parameters, raw Ark endpoint IDs (ep-...), and local filesystem paths from
  HTTP responses, headers, filenames, shotlist.csv, and shotlist.json.
- Uses ZIP_STORED (no recompression of audio/video) with a spooled temporary
  file cleaned up on close/error and a strict max pack byte limit.
- Never transcodes, concatenates, or renders final video.
"""
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import unicodedata
import zipfile

from flask import jsonify, request, send_file

import canvas_media_refs as media_refs
import canvas_store as store
import cost_estimate
import cost_ledger
from local_delete import require_same_origin
import media_library as media
import storage
import task_public
import tasks as task_db

SCOPES = ('finalized', 'selected', 'all')
MEDIA_NODE_TYPES = ('image', 'video', 'audio', 'asset')
MAX_PACK_ITEMS = 500
MAX_PACK_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB safety cap against disk exhaustion
SPOOL_MAX_BYTES = 8 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024
PROMPT_SUMMARY_MAX = 240
SAFE_TITLE_MAX = 60
SAFE_SLUG_MAX = 48

ALLOWED_REQUEST_KEYS = frozenset({'scope', 'node_ids', 'ordered_node_ids'})

WINDOWS_RESERVED_NAMES = frozenset({
    'con', 'prn', 'aux', 'nul',
    *(f'com{i}' for i in range(1, 10)),
    *(f'lpt{i}' for i in range(1, 10)),
})

MIME_EXTENSIONS = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/webp': '.webp',
    'image/gif': '.gif',
    'video/mp4': '.mp4',
    'video/webm': '.webm',
    'audio/mpeg': '.mp3',
    'audio/mp3': '.mp3',
    'audio/wav': '.wav',
    'audio/x-wav': '.wav',
    'audio/ogg': '.ogg',
}
SAFE_EXT = re.compile(r'^\.[a-z0-9]{1,8}$')

# Sensitive pattern scrubbing (layered on top of task_public.mask_text / mask_endpoint_ids)
_PRIVATE_KEY_BLOCK = re.compile(
    r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----',
    re.IGNORECASE,
)
_PRIVATE_KEY_HEADER = re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----', re.IGNORECASE)
_BEARER_TOKEN = re.compile(r'(?i)(?<![A-Za-z0-9])Bearer\s+[A-Za-z0-9._~+/=\-]{6,}')
_KNOWN_SECRET_TOKEN = re.compile(
    r'(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_\-]{12,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z\-_]{20,}|'
    r'gh[pousr]_[A-Za-z0-9]{20,}|xoxb-[A-Za-z0-9\-]{10,}|'
    r'eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}(?:\.[A-Za-z0-9_\-]*)?)'
)
_REDACTED_PLACEHOLDERS = frozenset({
    '[REDACTED]',
    '[REDACTED_KEY]',
    '[PATH_REDACTED]',
    'Bearer [REDACTED]',
})
_SENSITIVE_KV = re.compile(
    r'(?i)(?<![A-Za-z0-9])'
    r'(?P<prefix>'
    r'(?P<kq>(?:\\*["\'])?)'
    r'(?:'
    r'x-tos-signature|x-tos-credential|x-tos-security-token|'
    r'x-amz-signature|x-amz-credential|x-amz-security-token|'
    r'x-goog-signature|x-goog-credential|x-signature|signature|'
    r'awsaccesskeyid|ossaccesskeyid|sig|'
    r'x-api-key|api[_-]?key|apikey|secret[_-]?key|access[_-]?key|'
    r'access[_-]?token|refresh[_-]?token|auth[_-]?token|token|'
    r'authorization|password|passwd|credentials?|secret'
    r')'
    r'(?P=kq)\s*[:=]\s*)'
    r'(?:'
    r'(?P<redacted>(?:Bearer\s+)?\[(?:REDACTED(?:_KEY)?|PATH_REDACTED)\])'
    r'|(?P<evq>\\+["\'])(?P<eqval>[^\r\n]*?)(?P=evq)'
    r'|(?P<vq>["\'])(?P<qval>[^\r\n]*?)(?P=vq)'
    r'|(?P<uval>[^\s&"\',;)}\]\\]+)'
    r')'
)
_ENDPOINT_FALLBACK = re.compile(r'(?i)(?<![A-Za-z0-9])ep-(?:m-)?[0-9]{6,}-[A-Za-z0-9_-]+')
_FILE_URI = re.compile(r'(?i)(?<![A-Za-z0-9])file:/{1,3}[^\s\'"<>|;,)\]}\\]+')
_POSIX_ABS_PATH = re.compile(
    r'(?<!:/)(?<![A-Za-z0-9])/(?:data|home|root|var|tmp|etc|opt|usr|srv|mnt|Users|private|Volumes|proc|sys|dev)'
    r'(?:/[^\s\'"<>|;,)\]}\\]*)+'
)
_WINDOWS_ABS_PATH = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:\\[^\s\'"<>|;,)\]}]+')


def _replace_sensitive_kv(match):
    if match.group('redacted') is not None:
        return match.group(0)
    prefix = match.group('prefix')
    evq = match.group('evq')
    if evq is not None:
        val = match.group('eqval')
        if not val or val.strip() in _REDACTED_PLACEHOLDERS:
            return match.group(0)
        return f'{prefix}{evq}[REDACTED]{evq}'
    vq = match.group('vq')
    if vq is not None:
        val = match.group('qval')
        if not val or val.strip() in _REDACTED_PLACEHOLDERS:
            return match.group(0)
        return f'{prefix}{vq}[REDACTED]{vq}'
    uval = match.group('uval') or ''
    if not uval or uval in _REDACTED_PLACEHOLDERS:
        return match.group(0)
    return f'{prefix}[REDACTED]'
_BIDI_CHARS = frozenset({
    '\u061c', '\u200e', '\u200f',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
    '\u2066', '\u2067', '\u2068', '\u2069',
    '\ufeff',
})
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')


def _runtime_sensitive_roots():
    """Collect absolute local directories to scrub even outside standard root prefixes."""
    candidates = []
    for getter in (
        lambda: Path(storage.OUTPUT_DIR).absolute(),
        lambda: Path(task_db.DB_PATH).absolute().parent,
        lambda: Path(os.getcwd()).absolute(),
    ):
        try:
            p = getter()
            candidates.append(str(p))
            candidates.append(str(p.resolve()))
        except Exception:
            pass
    try:
        root = store.asset_root()
        candidates.append(str(root))
        candidates.append(str(root.resolve()))
    except Exception:
        pass
    try:
        mroot = media.root()
        candidates.append(str(mroot))
        candidates.append(str(mroot.resolve()))
    except Exception:
        pass
    seen = set()
    ordered = []
    for item in sorted(candidates, key=len, reverse=True):
        if item and len(item) > 1 and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _strip_control_and_bidi(text):
    out = []
    for ch in text:
        if ch in _BIDI_CHARS:
            continue
        cat = unicodedata.category(ch)
        if cat in ('Cc', 'Cf') and ch not in ('\n', '\r', '\t'):
            continue
        out.append(ch)
    return ''.join(out)


def sanitize_text(value, max_len=None, collapse_whitespace=False):
    """Scrub secrets, Bearer tokens, signed URLs, endpoint IDs, and local paths."""
    if value is None:
        return ''
    text = str(value)
    if not text:
        return ''
    text = _strip_control_and_bidi(text)
    text = _PRIVATE_KEY_BLOCK.sub('[REDACTED_KEY]', text)
    text = _PRIVATE_KEY_HEADER.sub('[REDACTED_KEY]', text)
    text = task_public.mask_text(text)
    text = _BEARER_TOKEN.sub('Bearer [REDACTED]', text)
    text = _SENSITIVE_KV.sub(_replace_sensitive_kv, text)
    text = _KNOWN_SECRET_TOKEN.sub('[REDACTED]', text)
    text = task_public.mask_endpoint_ids(text)
    text = _ENDPOINT_FALLBACK.sub(task_public.ENDPOINT_MASK, text)
    text = _FILE_URI.sub('[PATH_REDACTED]', text)
    for prefix in _runtime_sensitive_roots():
        if prefix in text:
            text = re.sub(re.escape(prefix) + r'[^\s\'"<>|;,)\]}]*', '[PATH_REDACTED]', text)
    text = _POSIX_ABS_PATH.sub('[PATH_REDACTED]', text)
    text = _WINDOWS_ABS_PATH.sub('[PATH_REDACTED]', text)
    if collapse_whitespace:
        text = re.sub(r'\s+', ' ', text).strip()
    if max_len is not None and len(text) > max_len:
        text = text[: max(1, max_len - 1)].rstrip() + '…'
    return text


def sanitize_filename_segment(value, fallback='shot', max_len=SAFE_TITLE_MAX):
    """Strictly clean a filename segment: no traversal, controls, bidi, or Windows reserved names."""
    cleaned = sanitize_text(value or '', collapse_whitespace=True)
    cleaned = ''.join(
        ch for ch in cleaned
        if ch not in _BIDI_CHARS and unicodedata.category(ch) not in ('Cc', 'Cf')
    )
    cleaned = _UNSAFE_FILENAME_CHARS.sub('_', cleaned)
    while '..' in cleaned:
        cleaned = cleaned.replace('..', '_')
    cleaned = re.sub(r'[\s_]+', '_', cleaned)
    cleaned = cleaned.strip(' ._-')
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].strip(' ._-')
    if not cleaned:
        return fallback
    stem = cleaned.split('.', 1)[0].casefold()
    if stem in WINDOWS_RESERVED_NAMES:
        cleaned = f'{fallback}_{cleaned}'
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].strip(' ._-')
    return cleaned or fallback


def _safe_extension(file_path, mime_type):
    ext = Path(file_path).suffix.lower() if file_path is not None else ''
    if ext and SAFE_EXT.fullmatch(ext):
        return ext
    mapped = MIME_EXTENSIONS.get((mime_type or '').lower())
    if mapped:
        return mapped
    return '.bin'


def _download_zip_name(workflow_title):
    slug = sanitize_filename_segment(workflow_title, fallback='canvas', max_len=SAFE_SLUG_MAX)
    return f'ink-traces-{slug}-pack.zip'


def _parse_request(data):
    if not isinstance(data, dict):
        raise store.CanvasError('请求必须为JSON对象')
    unknown = set(data) - ALLOWED_REQUEST_KEYS
    if unknown:
        raise store.CanvasError('请求包含未知字段')
    scope = data.get('scope', 'all')
    if not isinstance(scope, str) or scope not in SCOPES:
        raise store.CanvasError('导出范围仅支持 finalized、selected 或 all')

    node_ids = None
    if 'node_ids' in data and data['node_ids'] is not None:
        raw_ids = data['node_ids']
        if not isinstance(raw_ids, list) or len(raw_ids) > MAX_PACK_ITEMS or any(
            not isinstance(item, str) or not store.ID.fullmatch(item) for item in raw_ids
        ):
            raise store.CanvasError(f'node_ids 须为最多 {MAX_PACK_ITEMS} 个有效节点编号')
        node_ids = list(dict.fromkeys(raw_ids))
    elif scope == 'selected':
        node_ids = []

    ordered_node_ids = None
    if 'ordered_node_ids' in data and data['ordered_node_ids'] is not None:
        raw_order = data['ordered_node_ids']
        if not isinstance(raw_order, list) or len(raw_order) > MAX_PACK_ITEMS or any(
            not isinstance(item, str) or not store.ID.fullmatch(item) for item in raw_order
        ):
            raise store.CanvasError(f'ordered_node_ids 须为最多 {MAX_PACK_ITEMS} 个有效节点编号')
        ordered_node_ids = list(dict.fromkeys(raw_order))

    return scope, node_ids, ordered_node_ids


def _select_candidate_nodes(nodes, scope, node_ids, ordered_node_ids):
    """Select nodes matching scope and order them deterministically."""
    valid_nodes = [node for node in nodes if isinstance(node, dict) and isinstance(node.get('id'), str)]
    by_id = {node['id']: node for node in valid_nodes}
    skipped_missing = []

    if scope == 'selected':
        selected = []
        for nid in (node_ids or []):
            node = by_id.get(nid)
            if node is None:
                skipped_missing.append({
                    'node_id': nid,
                    'title': nid,
                    'node_type': 'unknown',
                    'reason': 'node_not_found',
                    'message': '画布中未找到该节点',
                })
            else:
                selected.append(node)
    elif scope == 'finalized':
        selected = [node for node in valid_nodes if node.get('finalized') is True]
    else:
        selected = [node for node in valid_nodes if node.get('type') in MEDIA_NODE_TYPES]

    if ordered_node_ids:
        rank = {nid: idx for idx, nid in enumerate(ordered_node_ids)}
        fallback_rank = len(rank)
        selected = [
            node for _, node in sorted(
                enumerate(selected),
                key=lambda pair: (rank.get(pair[1]['id'], fallback_rank), pair[0]),
            )
        ]
    return selected, skipped_missing


def _verify_media_file(row):
    """Resolve a live media_library row to a safe, verified, non-symlink file inside media.root()."""
    relpath = row.get('relpath')
    if not isinstance(relpath, str) or not relpath or relpath.startswith('/') or '\\' in relpath or '..' in PurePosixPath(relpath).parts:
        return None, 'unsafe_path', '素材路径不安全，已跳过'
    try:
        directory = media.root()
        raw_path = directory / relpath
        if raw_path.is_symlink():
            return None, 'unsafe_path', '素材路径不安全，已跳过'
        resolved_dir = directory.resolve()
        resolved_file = raw_path.resolve()
        if resolved_file != raw_path or not resolved_file.is_relative_to(resolved_dir):
            return None, 'unsafe_path', '素材路径不安全，已跳过'
        path = media.media_path(row)
        if path.is_symlink() or not path.resolve().is_relative_to(resolved_dir) or not path.is_file():
            return None, 'unsafe_path', '素材路径不安全，已跳过'
        return path, None, None
    except media.MediaError as exc:
        if exc.code == 'media_deleted':
            return None, 'deleted', '素材已从素材库删除'
        if exc.code == 'media_trashed':
            return None, 'trashed', '素材所在生成任务在回收站'
        return None, 'file_missing', '素材文件缺失或不可读取'
    except (OSError, ValueError, store.CanvasError):
        return None, 'file_missing', '素材文件缺失或不可读取'


def _verify_legacy_canvas_file(workflow_id, asset_id):
    """Resolve a legacy canvas_assets row safely inside store.asset_root()."""
    try:
        row = store.get_asset(workflow_id, asset_id, allow_archived=False)
    except store.CanvasError:
        return None, None, 'file_missing', '素材文件不存在'
    filename = row.get('filename')
    if not isinstance(filename, str) or not filename or '/' in filename or '\\' in filename or '..' in filename:
        return None, None, 'unsafe_path', '素材路径不安全，已跳过'
    try:
        root = store.asset_root()
        raw_path = root / row['workflow_id'] / filename
        if raw_path.is_symlink():
            return None, None, 'unsafe_path', '素材路径不安全，已跳过'
        resolved_root = root.resolve()
        resolved_file = raw_path.resolve()
        if resolved_file != raw_path or not resolved_file.is_relative_to(resolved_root):
            return None, None, 'unsafe_path', '素材路径不安全，已跳过'
        path = store.asset_path(row)
        if path.is_symlink() or not path.resolve().is_relative_to(resolved_root) or not path.is_file():
            return None, None, 'unsafe_path', '素材路径不安全，已跳过'
        return row, path, None, None
    except (OSError, ValueError, store.CanvasError):
        return None, None, 'file_missing', '素材文件缺失或不可读取'


def _resolve_node_media(workflow_id, node):
    """Resolve node.asset strictly through media_library / canvas_media_refs / canvas_store.

    Returns (resolved_dict, skip_reason, skip_message).
    """
    node_type = node.get('type')
    if node_type == 'text':
        return None, 'no_media', '文本节点无可导出媒体'
    asset = node.get('asset')
    if not isinstance(asset, dict) or not asset:
        return None, 'no_result', '暂无生成结果'

    asset_id = asset.get('id')
    url = asset.get('url')
    if (
        not isinstance(asset_id, str)
        or not media.MEDIA_ID.fullmatch(asset_id)
        or not isinstance(url, str)
        or not media_refs.is_reference_url(workflow_id, url)
        or url.rsplit('/', 1)[-1] != asset_id
    ):
        return None, 'unsafe_path', '素材引用无效或路径不安全，已跳过'

    state, row = media.status(asset_id)
    if state == 'missing':
        alias = media.resolve('workflow:' + asset_id)
        if alias:
            state, row = media.status(alias)

    if state == 'deleted':
        return None, 'deleted', '素材已从素材库删除'
    if state == 'trashed':
        return None, 'trashed', '素材所在生成任务在回收站'
    if state == 'ok':
        path, err_code, err_msg = _verify_media_file(row)
        if err_code:
            return None, err_code, err_msg
        try:
            size_bytes = path.stat().st_size
        except OSError:
            return None, 'file_missing', '素材文件不可读取'
        return {
            'asset_id': row['id'],
            'path': path,
            'mime_type': row.get('mime_type') or asset.get('mime_type') or 'application/octet-stream',
            'kind': row.get('kind') or asset.get('kind') or node_type,
            'size_bytes': int(size_bytes),
            'source_task_id': row.get('source_task_id'),
            'media_id': row['id'],
        }, None, None

    legacy_row, path, err_code, err_msg = _verify_legacy_canvas_file(workflow_id, asset_id)
    if err_code:
        return None, err_code, err_msg
    try:
        size_bytes = path.stat().st_size
    except OSError:
        return None, 'file_missing', '素材文件不可读取'
    return {
        'asset_id': legacy_row['id'],
        'path': path,
        'mime_type': legacy_row.get('mime_type') or asset.get('mime_type') or 'application/octet-stream',
        'kind': legacy_row.get('kind') or asset.get('kind') or node_type,
        'size_bytes': int(size_bytes),
        'source_task_id': None,
        'media_id': None,
    }, None, None


def _media_metadata_map(db, media_ids):
    ids = [mid for mid in dict.fromkeys(media_ids) if isinstance(mid, str) and media.MEDIA_ID.fullmatch(mid)]
    if not ids:
        return {}
    marks = ','.join('?' * len(ids))
    rows = db.execute(
        f'SELECT media_id, width, height, duration_seconds FROM media_metadata WHERE media_id IN ({marks})',
        ids,
    ).fetchall()
    return {r['media_id']: (r['width'], r['height'], r['duration_seconds']) for r in rows}


def _resolve_task_for_node(node, resolved):
    task_id = resolved.get('source_task_id')
    if isinstance(task_id, int) and task_id > 0:
        task = task_db.get_task(task_id)
        if task is not None:
            return task
    node_task = node.get('task')
    if isinstance(node_task, dict) and isinstance(node_task.get('id'), int) and node_task['id'] > 0:
        return task_db.get_task(node_task['id'])
    return None


def _format_cost(estimate):
    """Return (estimated_cost_usd_str, estimate_display, estimate_status, min_val, max_val)."""
    if not isinstance(estimate, dict) or estimate.get('status') != 'estimate':
        return 'unknown', '未知', 'unknown', None, None
    min_val = float(estimate['minimum_cost'])
    max_val = float(estimate['maximum_cost'])
    if abs(min_val - max_val) < 1e-9:
        formatted = f'{min_val:.3f}'
        return formatted, f'${formatted}', 'estimate', min_val, max_val
    formatted = f'{min_val:.3f}-{max_val:.3f}'
    return formatted, f'${min_val:.3f}-${max_val:.3f}', 'estimate', min_val, max_val


def _readable_model_name(node, task, estimate, db):
    if task is not None:
        params = task.get('params') or {}
        label = cost_ledger._model_label(task, params, estimate, db)
        if label:
            return sanitize_text(label, collapse_whitespace=True)
    if node.get('type') == 'asset':
        return '本地素材'
    node_params = node.get('params') or {}
    raw_model = node_params.get('model')
    if isinstance(raw_model, str) and raw_model.strip():
        cleaned = raw_model.strip()
        if cleaned in cost_ledger.VIDEO_MODEL_LABELS:
            return cost_ledger.VIDEO_MODEL_LABELS[cleaned]
        if cleaned in cost_ledger.AUDIO_MODEL_LABELS:
            return cost_ledger.AUDIO_MODEL_LABELS[cleaned]
        if cleaned.lower() in cost_estimate.SEEDREAM_55_ALIASES:
            return 'Seedream 5.5'
        if 'seedream-5' in cleaned.lower():
            return 'Seedream 5.0 Pro'
        safe = cost_ledger._safe_ledger_model(cleaned)
        if safe and safe != task_public.ENDPOINT_MASK:
            return sanitize_text(safe, collapse_whitespace=True)
    return '未知模型'


def _format_spec(kind, meta, node, task):
    width, height, duration = meta if meta else (None, None, None)
    params = (task.get('params') if isinstance(task, dict) else None) or node.get('params') or {}
    parts = []
    if width and height:
        parts.append(f'{int(width)}x{int(height)}')
    else:
        resolution = params.get('resolution')
        ratio = params.get('ratio') or params.get('aspect_ratio')
        if resolution and ratio and ratio != 'auto':
            parts.append(f'{resolution} ({ratio})')
        elif resolution:
            parts.append(str(resolution))
        elif ratio and ratio != 'auto':
            parts.append(str(ratio))
    if kind in ('video', 'audio'):
        if duration is not None and duration > 0:
            parts.append(f'{float(duration):.1f}s')
        else:
            param_dur = params.get('duration')
            if isinstance(param_dur, (int, float)) and param_dur > 0:
                parts.append(f'{float(param_dur):g}s')
            elif isinstance(param_dur, str) and param_dur.strip() and param_dur.strip() != '-1':
                parts.append(param_dur.strip())
    if kind == 'audio' and not parts:
        fmt = params.get('output_format')
        rate = params.get('sample_rate')
        if fmt:
            parts.append(str(fmt).upper())
        if rate:
            parts.append(f'{rate}Hz')
    return sanitize_text(' / '.join(parts), collapse_whitespace=True) if parts else '-'


def _prompt_summary(node, task):
    raw = node.get('text')
    if not isinstance(raw, str) or not raw.strip():
        params = (task.get('params') if isinstance(task, dict) else None) or {}
        raw = params.get('prompt') or ''
    return sanitize_text(raw, max_len=PROMPT_SUMMARY_MAX, collapse_whitespace=True)


def _build_pack_plan(workflow_id, data):
    scope, node_ids, ordered_node_ids = _parse_request(data)
    wf = store.workflow(workflow_id)
    document = wf.get('document') if isinstance(wf.get('document'), dict) else {}
    nodes = document.get('nodes') if isinstance(document.get('nodes'), list) else []
    selected, skipped = _select_candidate_nodes(nodes, scope, node_ids, ordered_node_ids)

    resolved_entries = []
    for node in selected:
        nid = node['id']
        safe_title = sanitize_text(node.get('title') or nid, max_len=120, collapse_whitespace=True) or nid
        resolved, skip_reason, skip_message = _resolve_node_media(workflow_id, node)
        if skip_reason is not None:
            skipped.append({
                'node_id': nid,
                'title': safe_title,
                'node_type': str(node.get('type') or 'unknown'),
                'reason': skip_reason,
                'message': skip_message,
            })
            continue
        resolved_entries.append((node, safe_title, resolved))

    db = task_db.get_db()
    meta_map = _media_metadata_map(db, [entry[2]['media_id'] for entry in resolved_entries if entry[2].get('media_id')])

    total_items = len(resolved_entries)
    pad_width = max(2, len(str(max(total_items, 1))))
    used_names = set()
    items = []
    total_bytes = 0
    known_cost_min = 0.0
    known_cost_max = 0.0
    unknown_cost_count = 0

    for idx, (node, safe_title, resolved) in enumerate(resolved_entries, start=1):
        task = _resolve_task_for_node(node, resolved)
        estimate = cost_estimate.task_estimate(task, db) if task is not None else {'status': 'unknown', 'reason': 'no_price_data'}
        cost_str, cost_display, estimate_status, min_val, max_val = _format_cost(estimate)
        if estimate_status == 'estimate':
            known_cost_min += min_val
            known_cost_max += max_val
        else:
            unknown_cost_count += 1

        model_label = _readable_model_name(node, task, estimate, db)
        meta = meta_map.get(resolved.get('media_id'))
        spec = _format_spec(resolved['kind'], meta, node, task)
        prompt_summary = _prompt_summary(node, task)

        seq = str(idx).zfill(pad_width)
        title_seg = sanitize_filename_segment(node.get('title') or node['id'], fallback='shot')
        id_tag = f"t{task['id']}" if task is not None and isinstance(task.get('id'), int) else resolved['asset_id'][:8]
        ext = _safe_extension(resolved['path'], resolved['mime_type'])
        base_name = f'{seq}_{title_seg}_{id_tag}'
        candidate = f'{base_name}{ext}'
        suffix_num = 1
        while candidate.casefold() in used_names:
            suffix_num += 1
            candidate = f'{base_name}_{suffix_num}{ext}'
        used_names.add(candidate.casefold())
        arcname = f'media/{candidate}'

        size_bytes = int(resolved['size_bytes'])
        total_bytes += size_bytes
        items.append({
            'shot_no': idx,
            'node_id': node['id'],
            'title': safe_title,
            'media_type': resolved['kind'],
            'filename': arcname,
            'size_bytes': size_bytes,
            'finalized': node.get('finalized') is True,
            'model': model_label,
            'spec': spec,
            'estimated_cost_usd': cost_str,
            'estimate_display': cost_display,
            'estimate_status': estimate_status,
            'prompt_summary': prompt_summary,
            '_path': resolved['path'],
            '_cost_min': min_val,
            '_cost_max': max_val,
        })

    return {
        'workflow_id': wf['id'],
        'workflow_title': sanitize_text(wf.get('title') or '未命名画布', max_len=120, collapse_whitespace=True) or '未命名画布',
        'scope': scope,
        'items': items,
        'skipped': skipped,
        'total_bytes': total_bytes,
        'known_cost_usd_min': round(known_cost_min, 6),
        'known_cost_usd_max': round(known_cost_max, 6),
        'unknown_cost_count': unknown_cost_count,
    }


def _public_preview_item(item):
    return {
        'shot_no': item['shot_no'],
        'node_id': item['node_id'],
        'title': item['title'],
        'media_type': item['media_type'],
        'filename': item['filename'],
        'size_bytes': item['size_bytes'],
        'finalized': item['finalized'],
        'model': item['model'],
        'spec': item['spec'],
        'estimated_cost_usd': item['estimated_cost_usd'],
        'estimate_display': item['estimate_display'],
        'estimate_status': item['estimate_status'],
        'prompt_summary': item['prompt_summary'],
    }


def _public_skipped_item(item):
    return {
        'node_id': item['node_id'],
        'title': item['title'],
        'node_type': item['node_type'],
        'reason': item['reason'],
        'message': item['message'],
    }


def preview_export_pack(workflow_id, data):
    """Build read-only preview payload for exporting a workflow asset pack."""
    plan = _build_pack_plan(workflow_id, data)
    items = [_public_preview_item(item) for item in plan['items']]
    skipped = [_public_skipped_item(item) for item in plan['skipped']]
    return {
        'workflow_id': plan['workflow_id'],
        'workflow_title': plan['workflow_title'],
        'scope': plan['scope'],
        'max_pack_bytes': MAX_PACK_BYTES,
        'over_limit': plan['total_bytes'] > MAX_PACK_BYTES,
        'total_bytes': plan['total_bytes'],
        'items': items,
        'skipped': skipped,
        'summary': {
            'total_items': len(items),
            'skipped_count': len(skipped),
            'total_bytes': plan['total_bytes'],
            'known_cost_usd_min': plan['known_cost_usd_min'],
            'known_cost_usd_max': plan['known_cost_usd_max'],
            'unknown_cost_count': plan['unknown_cost_count'],
        },
    }


def _csv_cell(value):
    text = sanitize_text(value, collapse_whitespace=True)
    if text.startswith('='):
        return "'" + text
    return text


def _build_shotlist_csv(items):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\r\n')
    writer.writerow([
        'shot_no',
        'filename',
        'node_id',
        'node_title',
        'media_type',
        'finalized',
        'model',
        'spec',
        'estimated_cost_usd',
        'file_size_bytes',
        'prompt_summary',
    ])
    for item in items:
        writer.writerow([
            item['shot_no'],
            _csv_cell(item['filename']),
            _csv_cell(item['node_id']),
            _csv_cell(item['title']),
            _csv_cell(item['media_type']),
            'true' if item['finalized'] else 'false',
            _csv_cell(item['model']),
            _csv_cell(item['spec']),
            _csv_cell(item['estimated_cost_usd']),
            int(item['size_bytes']),
            _csv_cell(item['prompt_summary']),
        ])
    return ('\ufeff' + buf.getvalue()).encode('utf-8')


def _build_shotlist_json(plan, written_items, skipped_items, total_bytes, cost_min, cost_max, unknown_count):
    payload = {
        'schema_version': 1,
        'workflow_id': plan['workflow_id'],
        'workflow_title': plan['workflow_title'],
        'exported_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'scope': plan['scope'],
        'summary': {
            'total_items': len(written_items),
            'skipped_count': len(skipped_items),
            'total_bytes': total_bytes,
            'known_cost_usd_min': round(cost_min, 6),
            'known_cost_usd_max': round(cost_max, 6),
            'unknown_cost_count': unknown_count,
        },
        'items': [
            {
                'shot_no': item['shot_no'],
                'filename': item['filename'],
                'node_id': item['node_id'],
                'node_title': item['title'],
                'media_type': item['media_type'],
                'finalized': item['finalized'],
                'model': item['model'],
                'spec': item['spec'],
                'estimated_cost_usd': item['estimated_cost_usd'],
                'estimate_status': item['estimate_status'],
                'file_size_bytes': int(item['size_bytes']),
                'prompt_summary': item['prompt_summary'],
            }
            for item in written_items
        ],
        'skipped': [
            {
                'node_id': entry['node_id'],
                'node_title': entry['title'],
                'node_type': entry['node_type'],
                'reason': entry['reason'],
                'message': entry['message'],
            }
            for entry in skipped_items
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')


def export_pack_response(workflow_id, data):
    """Stream a ZIP_STORED scene asset pack containing media/, shotlist.csv, and shotlist.json."""
    plan = _build_pack_plan(workflow_id, data)
    if not plan['items']:
        raise store.CanvasError('当前筛选范围内没有可导出的素材文件', 400)
    if plan['total_bytes'] > MAX_PACK_BYTES:
        raise store.CanvasError('导出包体积超过安全上限，请缩小筛选范围分批导出', 413)

    archive = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES, mode='w+b')
    try:
        written_items = []
        skipped_items = list(plan['skipped'])
        written_bytes = 0
        cost_min = 0.0
        cost_max = 0.0
        unknown_count = 0

        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for item in plan['items']:
                src_path = item['_path']
                arcname = item['filename']
                if not arcname.startswith('media/') or '..' in PurePosixPath(arcname).parts or '\\' in arcname:
                    skipped_items.append({
                        'node_id': item['node_id'],
                        'title': item['title'],
                        'node_type': item['media_type'],
                        'reason': 'unsafe_path',
                        'message': '素材路径不安全，已跳过',
                    })
                    continue
                try:
                    if src_path.is_symlink() or not src_path.is_file():
                        raise FileNotFoundError(arcname)
                    copied = 0
                    with src_path.open('rb') as source, zf.open(arcname, 'w', force_zip64=True) as target:
                        while True:
                            chunk = source.read(COPY_CHUNK_BYTES)
                            if not chunk:
                                break
                            copied += len(chunk)
                            if written_bytes + copied > MAX_PACK_BYTES:
                                raise store.CanvasError('导出包体积超过安全上限，请缩小筛选范围分批导出', 413)
                            target.write(chunk)
                    written_bytes += copied
                    item_copy = dict(item)
                    item_copy['size_bytes'] = copied
                    written_items.append(item_copy)
                    if item['estimate_status'] == 'estimate':
                        cost_min += item['_cost_min']
                        cost_max += item['_cost_max']
                    else:
                        unknown_count += 1
                except store.CanvasError:
                    raise
                except OSError:
                    skipped_items.append({
                        'node_id': item['node_id'],
                        'title': item['title'],
                        'node_type': item['media_type'],
                        'reason': 'file_missing',
                        'message': '素材文件在打包时不可读取，已跳过',
                    })

            if not written_items:
                raise store.CanvasError('当前筛选范围内没有可导出的素材文件', 409)

            csv_bytes = _build_shotlist_csv(written_items)
            json_bytes = _build_shotlist_json(
                plan, written_items, skipped_items, written_bytes, cost_min, cost_max, unknown_count
            )
            if written_bytes + len(csv_bytes) + len(json_bytes) > MAX_PACK_BYTES:
                raise store.CanvasError('导出包体积超过安全上限，请缩小筛选范围分批导出', 413)
            zf.writestr('shotlist.csv', csv_bytes)
            zf.writestr('shotlist.json', json_bytes)

        archive.seek(0)
        download_name = _download_zip_name(plan['workflow_title'])
        response = send_file(
            archive,
            mimetype='application/zip',
            as_attachment=True,
            download_name=download_name,
            conditional=False,
        )
        response.call_on_close(archive.close)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Export-Pack-Count'] = str(len(written_items))
        response.headers['X-Export-Pack-Skipped'] = str(len(skipped_items))
        return response
    except BaseException:
        archive.close()
        raise


def register_routes(blueprint, body):
    prefix = '/api/canvas/workflows/<workflow_id>/export-pack'

    @blueprint.route(prefix + '/preview', methods=['POST'])
    def canvas_export_pack_preview(workflow_id):
        require_same_origin(request, json_body=True)
        return jsonify(success=True, **preview_export_pack(workflow_id, body()))

    @blueprint.route(prefix, methods=['POST'])
    def canvas_export_pack_download(workflow_id):
        require_same_origin(request, json_body=True)
        return export_pack_response(workflow_id, body())
