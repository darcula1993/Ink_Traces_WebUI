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
import json
import logging
import sqlite3
from pathlib import Path

import canvas_store as store
import storage
import tasks as task_db
from task_public import mask_text, public_document

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
    return updated


GENERATION_TYPES = ('image', 'video', 'audio')
# client canConnect (canvasReferences.js): target type -> accepted source media kinds; text feeds all.
ACCEPTS = {'image': ('image',), 'video': ('image', 'video', 'audio'), 'audio': ('image', 'audio')}


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
    """Server write-back fields of a node; absent fields are null / [] / false."""
    return {'task': node.get('task'), 'candidates': node.get('candidates') or [],
            'asset': node.get('asset'), 'selectedCandidateId': node.get('selectedCandidateId'),
            'upstreamStale': node.get('upstreamStale') is True}


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
        nodes.append(merged)
    edges = document.get('edges') if isinstance(document.get('edges'), list) else []
    nodes, _ = derive_downstream(document['nodes'], nodes, edges, results)
    return {**document, 'nodes': nodes}
