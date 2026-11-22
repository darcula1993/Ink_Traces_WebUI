"""Server-side write-back of terminal task results into canvas documents.

CANVAS-WRITEBACK-20261114: instead of every open window saving the same task
result (the later save then hits 409), the worker -- or the idempotent
task-sync endpoint -- writes the result into the canvas once.  The node update
mirrors the client rules in client/src/lib/canvasTaskPolling.js
(collectTaskUpdates + applyTaskUpdates):

* only nodes whose ``task.id`` equals the task and whose stored task status is
  still active (pending/preparing/processing/cancel_requested) are touched;
* ``task`` becomes ``{id, status, error}`` (error ``or None``);
* succeeded tasks import their outputs exactly like POST task-results (with
  media references on: the task's global library items, no copy); assets
  not yet in ``candidates`` are appended, the first one becomes ``asset`` and
  ``selectedCandidateId``, and ``upstreamStale`` is removed;
* nothing changes (no revision bump) when the task state and candidates
  already match.

Write-back never calls a provider, never retries and never changes a task row.
"""
import copy
import json
import logging
import sqlite3
from pathlib import Path

import canvas_store as store
import storage
import tasks as task_db
from task_public import (
    is_invalid_snapshot_model,
    mask_endpoint_ids,
    mask_text,
    public_document,
    sanitize_snapshot_text,
)

LOG = logging.getLogger('nanobanana.canvas_writeback')

ACTIVE_STATUSES = ('pending', 'preparing', 'processing', 'cancel_requested')
TERMINAL_STATUSES = ('succeeded', 'failed', 'cancelled')
SYNC_LIMIT = 100


def init_writeback_db():
    db = task_db.get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS canvas_writebacks (
            workflow_id TEXT NOT NULL, revision INTEGER NOT NULL, node_id TEXT NOT NULL,
            task_id INTEGER NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(workflow_id, revision, node_id)
        );
        CREATE INDEX IF NOT EXISTS idx_canvas_writebacks_task ON canvas_writebacks(task_id);
    ''')
    db.commit()


def import_task_assets(workflow_id, task_id):
    """Node assets for a succeeded task's local outputs.

    LIBRARY-GLOBAL-20261116 S2: once media references are on (canvas_media_refs.enabled),
    the outputs are referenced from the global library (生成历史) without copying; before
    that, they are imported as durable canvas assets (dedup by hash) as before.
    """
    import canvas_media_refs
    if canvas_media_refs.enabled():
        return canvas_media_refs.import_task_media(workflow_id, task_id)
    store.workflow(workflow_id)
    task = task_db.get_task(task_id)
    if not task or task.get('deleted_at'):
        raise store.CanvasError('任务不存在', 404)
    if task['status'] != 'succeeded':
        raise store.CanvasError('只能导入成功任务的结果', 409)
    output_root = Path(storage.OUTPUT_DIR).absolute()
    sources = []
    for asset in task_db.list_assets(task_id):
        if asset['kind'] not in ('output_image', 'output_video', 'output_audio'):
            continue
        path = Path(asset['path']).absolute()
        if path.resolve() != path or not path.is_relative_to(output_root) or not path.is_file():
            raise store.CanvasError('任务输出文件不可读取', 409)
        sources.append(path)
    if not sources:
        raise store.CanvasError('任务没有可导入的本地输出', 409)
    from result_names import result_display_name, task_result_name
    assets = []
    for path in sources:
        try:
            with path.open('rb') as handle:
                assets.append(store.save_asset(workflow_id, handle, result_display_name(task_result_name(task.get('params')), task_id, path.name) or path.name))
        except OSError:
            raise store.CanvasError('任务输出文件已改变，请重新检查', 409)
    from canvas_cleanup import record_task_reference
    with store.write_transaction():
        record_task_reference(workflow_id, task_id)
    return assets


def _matching(node, task_id):
    task = node.get('task')
    return isinstance(task, dict) and task.get('id') == task_id


GENERATION_TYPES = ('image', 'video', 'audio')
# client canConnect (canvasReferences.js): target type -> accepted source media kinds; text feeds all.
ACCEPTS = {'image': ('image',), 'video': ('image', 'video', 'audio'), 'audio': ('image', 'audio')}


def _is_endpoint_id(value):
    return is_invalid_snapshot_model(value)


def _allowed_snapshot_param_keys(node_type):
    from canvas_image_params import IMAGE_FIELDS
    if node_type == 'image':
        return IMAGE_FIELDS | {'model', 'ratio', 'resolution'}
    if node_type == 'video':
        return {'model', 'ratio', 'resolution', 'duration', 'video_mode', 'omni_reference_task_type', 'generate_audio'}
    if node_type == 'audio':
        return store.AUDIO_FIELDS | {'model'}
    return frozenset()


def _sanitize_params(node_type, raw_params):
    """Return a clean generation-param dict validated for ``node_type`` (no legacy keys, URLs, secrets or ep- IDs)."""
    if node_type not in GENERATION_TYPES or not isinstance(raw_params, dict):
        return {}
    allowed = _allowed_snapshot_param_keys(node_type)
    cleaned = {}
    for key, value in raw_params.items():
        if key not in allowed:
            continue
        if key == 'model':
            if not isinstance(value, str) or not value.strip() or _is_endpoint_id(value):
                continue
            value = value.strip()
        elif key == 'speaker' and node_type == 'audio' and value is None:
            value = ''
        elif value is None:
            continue
        if isinstance(value, str):
            value = sanitize_snapshot_text(value)
        try:
            store._validate_node_params(node_type, {key: value}, allow_legacy=False)
        except store.CanvasError:
            continue
        cleaned[key] = value
    return cleaned


def _sanitize_provider_selection(node_type, raw_selection):
    """Return validated ``{'provider': ..., 'profile_id': ...}`` or None."""
    if node_type not in GENERATION_TYPES or raw_selection is None:
        return None
    from canvas_project_settings import validate_node_selection
    try:
        return validate_node_selection(node_type, raw_selection)
    except store.CanvasError:
        return None


def extract_node_snapshot(node):
    """VERSION-SNAPSHOT-20261123: capture clean {text, params, providerSelection?} from a generation node."""
    if not isinstance(node, dict):
        return None
    node_type = node.get('type')
    if node_type not in GENERATION_TYPES:
        return None
    raw_text = node.get('text')
    text = sanitize_snapshot_text(raw_text)[:50000] if isinstance(raw_text, str) else ''
    snap = {
        'text': text,
        'params': _sanitize_params(node_type, node.get('params')),
    }
    selection = _sanitize_provider_selection(node_type, node.get('providerSelection'))
    if selection is not None:
        snap['providerSelection'] = selection
    return snap


def _coerce_bool(value):
    if type(value) is bool:
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == 'true':
            return True
        if lowered == 'false':
            return False
    return None


def _coerce_positive_int(value):
    if type(value) is int and value >= 1:
        return value
    if isinstance(value, str) and value.strip().isdecimal():
        parsed = int(value.strip())
        if parsed >= 1:
            return parsed
    return None


def _coerce_duration(value):
    if type(value) is bool or value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return stripped if len(stripped) <= 16 else None
    return None


def _reconstruct_legacy_params(task_type, task_params):
    """Reconstruct clean canvas node ``params`` from a legacy task row's ``params``."""
    if task_type not in GENERATION_TYPES or not isinstance(task_params, dict):
        return {}
    raw = {}
    model = task_params.get('model')
    if isinstance(model, str) and model.strip() and not _is_endpoint_id(model):
        raw['model'] = model.strip()
    if task_type == 'image':
        ratio = task_params.get('aspect_ratio') or task_params.get('ratio')
        if isinstance(ratio, str) and ratio.strip():
            raw['ratio'] = ratio.strip().lower()
        resolution = task_params.get('resolution')
        if isinstance(resolution, str) and resolution.strip() and raw.get('ratio') != 'custom':
            raw['resolution'] = resolution.strip().upper()
        for dim_key in ('custom_width', 'custom_height'):
            parsed = _coerce_positive_int(task_params.get(dim_key))
            if parsed is not None:
                raw[dim_key] = parsed
        output_format = task_params.get('output_format')
        if isinstance(output_format, str) and output_format.strip():
            raw['output_format'] = output_format.strip().lower()
        background = task_params.get('background')
        if isinstance(background, str) and background.strip():
            raw['background'] = background.strip().lower()
        for bool_key in ('watermark', 'lock_aspect_ratio'):
            if bool_key in task_params:
                coerced = _coerce_bool(task_params.get(bool_key))
                if coerced is not None:
                    raw[bool_key] = coerced
    elif task_type == 'video':
        ratio = task_params.get('ratio') or task_params.get('aspect_ratio')
        if isinstance(ratio, str) and ratio.strip():
            raw['ratio'] = ratio.strip().lower()
        resolution = task_params.get('resolution')
        if isinstance(resolution, str) and resolution.strip():
            raw['resolution'] = resolution.strip().lower()
        duration = _coerce_duration(task_params.get('duration'))
        if duration is not None:
            raw['duration'] = duration
        video_mode = task_params.get('video_mode')
        if isinstance(video_mode, str) and video_mode in ('reference', 'keyframe'):
            raw['video_mode'] = video_mode
        omni_type = task_params.get('omni_reference_task_type')
        if isinstance(omni_type, str) and omni_type in ('auto', 'reference', 'edit', 'extend'):
            raw['omni_reference_task_type'] = omni_type
        if 'generate_audio' in task_params:
            coerced = _coerce_bool(task_params.get('generate_audio'))
            if coerced is not None:
                raw['generate_audio'] = coerced
    elif task_type == 'audio':
        if 'speaker' in task_params:
            speaker = task_params.get('speaker')
            raw['speaker'] = '' if speaker is None else speaker
        output_format = task_params.get('output_format')
        if isinstance(output_format, str) and output_format.strip():
            raw['output_format'] = output_format.strip().lower()
        sample_rate = _coerce_positive_int(task_params.get('sample_rate'))
        if sample_rate is not None:
            raw['sample_rate'] = sample_rate
        if 'enable_subtitle' in task_params:
            coerced = _coerce_bool(task_params.get('enable_subtitle'))
            if coerced is not None:
                raw['enable_subtitle'] = coerced
    return _sanitize_params(task_type, raw)


def _reconstruct_legacy_selection(task_type, task):
    """Reconstruct validated ``providerSelection`` from a task row."""
    from canvas_project_settings import ADAPTERS
    if task_type not in ADAPTERS:
        return None
    task_params = task.get('params') if isinstance(task.get('params'), dict) else {}
    provider = task.get('provider') or task_params.get('provider')
    if not isinstance(provider, str) or provider not in ADAPTERS[task_type]:
        return None
    profile_id = task_params.get('profile_id')
    if not (isinstance(profile_id, str) and store.HEX32.fullmatch(profile_id)):
        profile_id = None
    return _sanitize_provider_selection(task_type, {'provider': provider, 'profile_id': profile_id})


def snapshot_from_task(task, fallback_node=None):
    """Build a sanitized version snapshot from a task row.

    Prefers ``task['params']['canvas_node_snapshot']`` (captured at submission time, immune
    to edits made while generating). Falls back to reconstructing from the task's prompt and
    params for pre-upgrade / legacy tasks; ``fallback_node`` is only used during live
    write-back of an in-flight task that has no submission snapshot.
    """
    if not isinstance(task, dict):
        return None
    task_type = task.get('type')
    if task_type not in GENERATION_TYPES:
        return None
    task_params = task.get('params') if isinstance(task.get('params'), dict) else {}
    stored = task_params.get('canvas_node_snapshot')
    if isinstance(stored, dict):
        raw_text = stored.get('text')
        text = sanitize_snapshot_text(raw_text)[:50000] if isinstance(raw_text, str) else ''
        params = _sanitize_params(task_type, stored.get('params'))
        selection = _sanitize_provider_selection(task_type, stored.get('providerSelection'))
        if selection is None and 'providerSelection' not in stored:
            selection = _reconstruct_legacy_selection(task_type, task)
    else:
        fallback_text = fallback_node.get('text') if isinstance(fallback_node, dict) and isinstance(fallback_node.get('text'), str) else ''
        raw_text = (fallback_text or task.get('prompt') or '') if fallback_node is not None else (task.get('prompt') or '')
        text = sanitize_snapshot_text(raw_text)[:50000] if isinstance(raw_text, str) else ''
        params = _reconstruct_legacy_params(task_type, task_params)
        if not params and isinstance(fallback_node, dict):
            params = _sanitize_params(task_type, fallback_node.get('params'))
        selection = _reconstruct_legacy_selection(task_type, task)
        if selection is None and isinstance(fallback_node, dict):
            selection = _sanitize_provider_selection(task_type, fallback_node.get('providerSelection'))
    snap = {'text': text, 'params': params}
    if selection is not None:
        snap['providerSelection'] = selection
    task_id = task.get('id')
    if type(task_id) is int and task_id >= 1:
        snap['taskId'] = task_id
    created_at = task.get('created_at')
    if isinstance(created_at, str) and 1 <= len(created_at) <= 40:
        snap['createdAt'] = created_at
    return snap


def _merge_version_snapshots(existing, new_entries, candidates):
    merged = dict(existing) if isinstance(existing, dict) else {}
    for asset_id, snap in new_entries.items():
        merged[asset_id] = copy.deepcopy(snap)
    if len(merged) > store.MAX_VERSION_SNAPSHOTS:
        cand_ids = {c.get('id') for c in (candidates or []) if isinstance(c, dict)}
        for key in list(merged):
            if len(merged) <= store.MAX_VERSION_SNAPSHOTS:
                break
            if key not in cand_ids:
                merged.pop(key, None)
        while len(merged) > store.MAX_VERSION_SNAPSHOTS:
            merged.pop(next(iter(merged)))
    return merged


def _media_source_task_id(db, media_id):
    row = db.execute('SELECT source_task_id FROM media WHERE id=?', (media_id,)).fetchone()
    if row and row['source_task_id']:
        return row['source_task_id']
    row = db.execute('SELECT source_task_id FROM media_tombstones WHERE id=?', (media_id,)).fetchone()
    if row and row['source_task_id']:
        return row['source_task_id']
    row = db.execute(
        'SELECT task_id FROM task_assets WHERE media_id=? AND task_id IS NOT NULL ORDER BY id DESC LIMIT 1',
        (media_id,),
    ).fetchone()
    return row['task_id'] if row and row['task_id'] else None


def lookup_version_snapshots(workflow_id, media_ids):
    """VERSION-SNAPSHOT-20261123: fallback snapshot lookup for historical candidates."""
    wf = store.workflow(workflow_id)
    if not isinstance(media_ids, list) or not 1 <= len(media_ids) <= 100:
        raise store.CanvasError('media_ids 须为1至100个素材编号')
    if any(not isinstance(item, str) or not store.HEX32.fullmatch(item) for item in media_ids):
        raise store.CanvasError('media_ids 包含无效素材编号')
    unique_ids = list(dict.fromkeys(media_ids))
    inline_by_id = {}
    for node in (wf.get('document') or {}).get('nodes', []):
        if isinstance(node, dict) and node.get('type') in GENERATION_TYPES and isinstance(node.get('versionSnapshots'), dict):
            for key, value in node['versionSnapshots'].items():
                if key not in inline_by_id and isinstance(value, dict):
                    inline_by_id[key] = (node['type'], value)
    db = task_db.get_db()
    snapshots = {}
    task_cache = {}
    for mid in unique_ids:
        task_id = _media_source_task_id(db, mid)
        if task_id is None:
            alias_row = db.execute(
                "SELECT media_id FROM media_aliases WHERE scope='workflow' AND old_id=?",
                (mid,),
            ).fetchone()
            if alias_row and alias_row['media_id']:
                task_id = _media_source_task_id(db, alias_row['media_id'])
        snap = None
        if task_id is not None:
            if task_id not in task_cache:
                task_cache[task_id] = task_db.get_task(task_id)
            task = task_cache[task_id]
            if task and task.get('type') in GENERATION_TYPES:
                snap = snapshot_from_task(task)
        if snap is None and mid in inline_by_id:
            node_type, stored = inline_by_id[mid]
            sanitized = {
                'text': sanitize_snapshot_text(stored.get('text'))[:50000] if isinstance(stored.get('text'), str) else '',
                'params': _sanitize_params(node_type, stored.get('params')),
            }
            selection = _sanitize_provider_selection(node_type, stored.get('providerSelection'))
            if selection is not None:
                sanitized['providerSelection'] = selection
            if type(stored.get('taskId')) is int and stored['taskId'] >= 1:
                sanitized['taskId'] = stored['taskId']
            if isinstance(stored.get('createdAt'), str) and 1 <= len(stored['createdAt']) <= 40:
                sanitized['createdAt'] = stored['createdAt']
            snap = sanitized
        if snap is not None:
            snapshots[mid] = snap
    return snapshots


def _updated_node(node, task, assets):
    """applyTaskUpdates for one node; None when nothing would change."""
    current = node.get('task') or {}
    if current.get('status') not in ACTIVE_STATUSES:
        return None
    # FIX-B1 D1: the canvas document is sent to the browser; never store signed URLs in it.
    next_task = {'id': task['id'], 'status': task['status'], 'error': mask_text(task.get('error')) or None}
    known = {candidate.get('id') for candidate in node.get('candidates') or []}
    additions = [asset for asset in assets if asset['id'] not in known]
    if not additions and current.get('status') == next_task['status'] and (current.get('error') or None) == next_task['error']:
        return None
    updated = dict(node)
    updated['task'] = next_task
    updated['candidates'] = list(node.get('candidates') or []) + additions
    if additions:
        updated.pop('upstreamStale', None)
        updated['asset'] = additions[0]
        updated['selectedCandidateId'] = additions[0]['id']
        snap = snapshot_from_task(task, fallback_node=node)
        if snap is not None:
            updated['versionSnapshots'] = _merge_version_snapshots(
                node.get('versionSnapshots'),
                {asset['id']: snap for asset in additions},
                updated['candidates'],
            )
    return updated


def _asset_id(node):
    asset = node.get('asset') if isinstance(node, dict) else None
    return asset.get('id') if isinstance(asset, dict) else None


def _input_ids(target, by_id, edges):
    """Asset ids the client resolveNodeInputs would give ``target``."""
    ids = set()
    for edge in edges:
        if not isinstance(edge, dict) or edge.get('target') != target['id']:
            continue
        source = by_id.get(edge.get('source'))
        if not isinstance(source, dict) or source.get('id') == target['id'] or target.get('type') not in GENERATION_TYPES:
            continue
        kind = source['asset'].get('kind') if source.get('type') == 'asset' and isinstance(source.get('asset'), dict) else source.get('type')
        if kind == 'text' or kind not in ACCEPTS[target['type']] or not _asset_id(source):
            continue
        ids.add(_asset_id(source))
    ids.update(asset.get('id') for asset in target.get('referenceAssets') or [] if isinstance(asset, dict))
    return ids


def derive_downstream(before_nodes, after_nodes, edges, changed_ids):
    """F10 + F11 of the client edit pipeline after write-back changed some nodes.

    ``before_nodes``/``after_nodes`` are lists, ``changed_ids`` the written nodes.
    F11 reconcileReferenceMentions (full port, QA D3): references, bindings and the
    @图片N/@视频N/@音频N numbering of every generation node follow the new results
    exactly as an open page would (canvas_reference_rebind).  F10
    markStaleDownstream: a direct downstream generation node that has a result and
    is not stale yet gets ``upstreamStale: true`` when the upstream asset id changed.
    Returns (nodes, ids of other nodes that changed).
    """
    from canvas_reference_rebind import reconcile_reference_mentions
    before = {node.get('id'): node for node in before_nodes if isinstance(node, dict)}
    after = {node.get('id'): node for node in after_nodes if isinstance(node, dict)}
    edge_list = [edge for edge in edges if isinstance(edge, dict)]
    reconciled = {node.get('id'): node for node in reconcile_reference_mentions(
        {'nodes': before_nodes, 'edges': edge_list}, {'nodes': after_nodes, 'edges': edge_list})}
    moved = {node_id for node_id in changed_ids
             if node_id in before and node_id in after and _asset_id(before[node_id]) != _asset_id(after[node_id])}
    for edge in edge_list:
        target_id = edge.get('target')
        target = reconciled.get(target_id)
        if edge.get('source') not in moved or not isinstance(target, dict) or target.get('type') not in GENERATION_TYPES \
                or target_id not in before or target_id in moved:
            continue
        if target.get('asset') and not target.get('upstreamStale'):
            reconciled[target_id] = {**target, 'upstreamStale': True}
    touched = {node_id for node_id, node in reconciled.items() if node != after.get(node_id) and node_id not in changed_ids}
    if not touched:
        return after_nodes, set()
    return [reconciled.get(node.get('id'), node) if isinstance(node, dict) else node for node in after_nodes], touched


def node_fields(node):
    """Server write-back fields of a node; absent fields are null / [] / false / {}."""
    return {'task': node.get('task'), 'candidates': node.get('candidates') or [],
            'asset': node.get('asset'), 'selectedCandidateId': node.get('selectedCandidateId'),
            'upstreamStale': node.get('upstreamStale') is True,
            'versionSnapshots': node.get('versionSnapshots') or {}}


def _apply_to_workflow(workflow_id, task):
    """Write one terminal task into one canvas. Returns the new revision or None."""
    try:
        document = store.workflow(workflow_id)['document']
    except store.CanvasError:
        return None  # archived or missing canvas
    if not any(_matching(node, task['id']) and (node.get('task') or {}).get('status') in ACTIVE_STATUSES
               for node in document.get('nodes', [])):
        return None  # no node waits for this task (deleted, relinked or already written)
    assets = import_task_assets(workflow_id, task['id']) if task['status'] == 'succeeded' else []
    db = task_db.get_db()
    with store.write_transaction():
        row = store.workflow(workflow_id)
        document, revision = row['document'], row['revision']
        changed = []
        nodes = []
        for node in document.get('nodes', []):
            updated = _updated_node(node, task, assets) if _matching(node, task['id']) else None
            if updated is not None:
                changed.append(node['id'])
            nodes.append(updated if updated is not None else node)
        if not changed:
            return None
        nodes, downstream = derive_downstream(document.get('nodes', []), nodes, document.get('edges', []), changed)
        changed += sorted(downstream - set(changed))
        document = {**document, 'nodes': nodes}
        encoded = store.validate_document(document, workflow_id)
        now = task_db.utcnow()
        updated_rows = db.execute('UPDATE canvas_workflows SET document=?, revision=revision+1, updated_at=? WHERE id=? AND revision=?',
                                  (encoded, now, workflow_id, revision)).rowcount
        if not updated_rows:
            return None
        db.execute('UPDATE canvas_projects SET updated_at=? WHERE id=?', (now, row['project_id']))
        db.executemany('INSERT INTO canvas_writebacks VALUES (?,?,?,?,?)',
                       [(workflow_id, revision + 1, node_id, task['id'], now) for node_id in changed])
    LOG.info('canvas_writeback workflow=%s task=%s revision=%s nodes=%s', workflow_id, task['id'], revision + 1, len(changed))
    return revision + 1


def _task_workflows(task_id):
    return [row['workflow_id'] for row in task_db.get_db().execute(
        'SELECT workflow_id FROM canvas_workflow_tasks WHERE task_id=? ORDER BY workflow_id', (task_id,))]


def apply_task_result(task_id, workflow_id=None):
    """Interface A. Write a terminal task into its canvases (or only ``workflow_id``).

    Idempotent. Returns {workflow_id: new revision} for canvases that changed.
    Raises CanvasError when a succeeded task's outputs cannot be imported.
    """
    task = task_db.get_task(task_id)
    if not task or task['status'] not in TERMINAL_STATUSES:
        return {}
    owners = _task_workflows(task_id)
    if workflow_id is not None:
        owners = [owner for owner in owners if owner == workflow_id]
    applied = {}
    for owner in owners:
        revision = _apply_to_workflow(owner, task)
        if revision is not None:
            applied[owner] = revision
    return applied


def apply_task_result_safely(task_id):
    """Worker hook: failures are logged only; the task row is never touched."""
    try:
        return apply_task_result(task_id)
    except Exception:
        LOG.exception('canvas_writeback_failed task=%s', task_id)
        return {}


def _still_waiting(workflow_id, task_id):
    """After a write conflict: does a node of this canvas still wait for the task?"""
    db = task_db.get_db()
    if db.in_transaction:
        db.rollback()  # never keep a half-open transaction from the failed attempt
    return any(_matching(node, task_id) and (node.get('task') or {}).get('status') in ACTIVE_STATUSES
               for node in store.workflow(workflow_id)['document'].get('nodes', []))


def sync_tasks(workflow_id, task_ids):
    """Interface B compensation: apply A for the given tasks owned by this canvas."""
    if not isinstance(task_ids, list) or not task_ids or len(task_ids) > SYNC_LIMIT:
        raise store.CanvasError(f'task_ids 必须为1至{SYNC_LIMIT}个任务编号')
    if any(type(item) is not int or item < 1 for item in task_ids):
        raise store.CanvasError('task_ids 必须为正整数')
    store.workflow(workflow_id)
    wanted = list(dict.fromkeys(task_ids))
    owned = {row['task_id'] for row in task_db.get_db().execute(
        f"SELECT task_id FROM canvas_workflow_tasks WHERE workflow_id=? AND task_id IN ({','.join('?' * len(wanted))})",
        (workflow_id, *wanted))}
    failed = []
    for task_id in wanted:
        if task_id not in owned:
            continue
        try:
            apply_task_result(task_id, workflow_id)
        except store.CanvasError as error:
            LOG.warning('canvas_task_sync_failed workflow=%s task=%s error=%s', workflow_id, task_id, error)
            failed.append(task_id)
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as error:
            # WRITEBACK-RACE-20261114: the worker (or another sync) imported the same
            # result concurrently.  Its write is serialized and already committed, so
            # read the stored document instead of retrying; only a node that still
            # waits for the task counts as failed (the client syncs again later).
            if _still_waiting(workflow_id, task_id):
                LOG.warning('canvas_task_sync_conflict workflow=%s task=%s error=%s', workflow_id, task_id, error)
                failed.append(task_id)
            else:
                LOG.info('canvas_task_sync_conflict_resolved workflow=%s task=%s error=%s', workflow_id, task_id, error)
    row = store.workflow(workflow_id)
    nodes = {node['id']: node_fields(node) for node in public_document(row['document']).get('nodes', [])
             if isinstance(node.get('task'), dict) and node['task'].get('id') in owned}
    return {'revision': row['revision'], 'nodes': nodes, 'failed': failed}


def _older_than_group_task(db, node, task_id):
    """GROUP-RUN B3: the server bound ``node.task`` to a group-run task at submission.

    A stale client still holding an older task (or none) gets the server's task;
    a client bound to a newer task keeps its own.  Only tasks a group run created
    (params.group_run_id) qualify; ordinary write-backs keep the matching rule.
    """
    current = node.get('task') if isinstance(node.get('task'), dict) else {}
    client_id = current.get('id')
    if client_id is not None and (type(client_id) is not int or client_id >= task_id):
        return False
    row = db.execute("SELECT json_extract(params,'$.group_run_id') AS run FROM tasks WHERE id=?", (task_id,)).fetchone()
    return bool(row and row['run'])


def merge_stale_save(db, workflow_id, base_revision, current_revision, document):
    """Interface C. Overlay write-back fields onto a stale client document.

    Returns the merged document, or None when any revision after the client's
    base was not a write-back (then the caller keeps the 409 flow).
    """
    if base_revision >= current_revision:
        return None
    rows = db.execute('SELECT revision, node_id, task_id FROM canvas_writebacks WHERE workflow_id=? AND revision>? AND revision<=?',
                      (workflow_id, base_revision, current_revision)).fetchall()
    if {row['revision'] for row in rows} != set(range(base_revision + 1, current_revision + 1)):
        return None
    if not isinstance(document, dict) or not isinstance(document.get('nodes'), list):
        return None  # let validation report the malformed document
    server = json.loads(db.execute('SELECT document FROM canvas_workflows WHERE id=?', (workflow_id,)).fetchone()['document'])
    server_nodes = {node.get('id'): node for node in server.get('nodes', [])}
    written = {}
    for row in rows:
        written.setdefault(row['node_id'], set()).add(row['task_id'])
    nodes, results = [], []
    for node in document['nodes']:
        source = server_nodes.get(node.get('id')) if isinstance(node, dict) else None
        task_ids = written.get(node.get('id'), set()) if isinstance(node, dict) else set()
        task_id = next((item for item in task_ids if source is not None and _matching(source, item)), None)
        # A deleted node stays deleted; a node the client re-bound to another task keeps the
        # client's state; downstream rows (F10/F11) are re-derived below from the client document.
        if source is None or task_id is None or not (_matching(node, task_id) or _older_than_group_task(db, node, task_id)):
            nodes.append(node)
            continue
        results.append(node['id'])
        merged = dict(node)
        src_task = source['task']
        if isinstance(src_task, dict) and isinstance(src_task.get('error'), str) and src_task['error']:
            src_task = {**src_task, 'error': mask_text(src_task['error']) or None}
        merged['task'] = src_task
        known = {candidate.get('id') for candidate in node.get('candidates') or [] if isinstance(candidate, dict)}
        added = [candidate for candidate in source.get('candidates') or [] if candidate.get('id') not in known]
        if source['task'].get('status') == 'succeeded' and source.get('asset') and added:
            # The write-back produced new results: same rule as applyTaskUpdates on the client node.
            merged['candidates'] = list(node.get('candidates') or []) + added
            merged['asset'] = source['asset']
            merged['selectedCandidateId'] = source.get('selectedCandidateId')
            merged.pop('upstreamStale', None)
            src_snaps = source.get('versionSnapshots')
            if isinstance(src_snaps, dict):
                added_snaps = {
                    candidate['id']: src_snaps[candidate['id']]
                    for candidate in added
                    if isinstance(candidate, dict) and candidate.get('id') in src_snaps
                }
                if added_snaps:
                    merged['versionSnapshots'] = _merge_version_snapshots(
                        node.get('versionSnapshots'),
                        added_snaps,
                        merged['candidates'],
                    )
        nodes.append(merged)
    edges = document.get('edges') if isinstance(document.get('edges'), list) else []
    nodes, _ = derive_downstream(document['nodes'], nodes, edges, results)
    return {**document, 'nodes': nodes}
