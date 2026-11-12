"""Permanent deletion of items in the 本地素材 view and the canvas copies made from them.

User decisions 2026-11-13: "删除" in 本地素材 permanently removes the selected item --
an unowned local upload (local:), a project library asset (library:) or a direct
canvas upload (workflow:) -- with its file. Canvas copies derived from it are deleted
too and every workflow document that referenced the deleted assets is rewritten
(revision+1). Generated history (task:) and Cupsy remote assets (cupsy:) are refused.

Copy provenance is the only relation used: ``canvas_asset_copies`` records (canvas
asset, source key) only when a copy actually produced the asset (see
``canvas_store._copy_provenance``): a copy deduplicated onto an independent canvas
asset (direct upload, imported task result) records nothing, and a non-copy save
deduplicated onto a pure copy drops its copy records. Copies of copies are followed
transitively. Copies into the project
library are not canvas copies and are kept unless selected themselves.
"""
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import canvas_store as store
import tasks

MAX_KEYS = 500
GENERATION = ('image', 'video', 'audio')


def init_copy_db():
    db = tasks.get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS canvas_asset_copies (
        asset_id TEXT NOT NULL, source_key TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(asset_id, source_key));
    CREATE INDEX IF NOT EXISTS idx_canvas_asset_copies_source ON canvas_asset_copies(source_key);
    ''')
    db.commit()


def record_copy(asset_id, source_key):
    tasks.get_db().execute('INSERT OR IGNORE INTO canvas_asset_copies VALUES (?,?,?)', (asset_id, source_key, tasks.utcnow()))


def require_same_origin(request, json_body=True):
    """Reject cross-site browser requests; non-browser clients send no Origin."""
    site = request.headers.get('Sec-Fetch-Site')
    if site and site not in ('same-origin', 'none'):
        raise store.CanvasError('拒绝跨站删除请求', 403)
    origin = request.headers.get('Origin')
    if origin is not None and (origin == 'null' or urlsplit(origin).netloc != request.host):
        raise store.CanvasError('拒绝跨站删除请求', 403)
    if json_body and not request.is_json:
        raise store.CanvasError('删除请求必须为JSON', 415)


def parse_keys(value):
    from canvas_catalog import selection_from_key
    if not isinstance(value, list) or not value or len(value) > MAX_KEYS or any(not isinstance(k, str) for k in value):
        raise store.CanvasError(f'keys 须为1至{MAX_KEYS}个素材编号')
    keys = list(dict.fromkeys(value))
    for key in keys:
        selection_from_key(key)  # raises 400 for malformed source or ID
    return keys


def _workflow_asset_path(row):
    root = store.asset_root()
    path = root / row['workflow_id'] / row['filename']
    if path.resolve() != path or not path.is_relative_to(root):
        raise store.CanvasError('素材路径不安全', 409)
    return path


def _local_path(row):
    from local_uploads import root
    directory = root()
    path = directory / row['filename']
    if path.resolve() != path or not path.is_relative_to(directory):
        raise store.CanvasError('本地素材路径不安全', 409)
    return path


def _active_workflows(db):
    return {r['id'] for r in db.execute('''SELECT w.id FROM canvas_workflows w WHERE
        NOT EXISTS (SELECT 1 FROM canvas_deletions d WHERE d.scope='workflow' AND d.id=w.id) AND
        NOT EXISTS (SELECT 1 FROM canvas_deletions d WHERE d.scope='project' AND d.id=w.project_id)''')}


def _derived_copies(db, keys):
    """Canvas assets copied (directly or via other canvas copies) from these source keys.

    A copy with several copy sources (same bytes copied from different sources into one
    canvas, deduplicated) is deleted only when all of its sources are being deleted.
    """
    found, frontier, seen = {}, set(keys), set()
    while frontier - seen:
        batch = frontier - seen
        seen |= batch
        for key in batch:
            for asset in db.execute('SELECT a.* FROM canvas_assets a JOIN canvas_asset_copies c ON c.asset_id=a.id WHERE c.source_key=?', (key,)):
                found[asset['id']] = dict(asset)
                frontier.add('workflow:' + asset['id'])
    sources = {i: {r[0] for r in db.execute('SELECT source_key FROM canvas_asset_copies WHERE asset_id=?', (i,))} for i in found}
    while True:
        deleting = set(keys) | {'workflow:' + i for i in found}
        kept = [i for i in found if not sources[i] <= deleting]
        if not kept:
            return found
        for i in kept:
            found.pop(i)


def strip_document(document, removed):
    """Remove references to deleted asset IDs; returns (document, touched node count)."""
    nodes, touched, dropped = [], 0, set()
    for node in document.get('nodes', []):
        original = json.dumps(node, sort_keys=True)
        node = dict(node)
        candidates = [c for c in node.get('candidates', []) if c.get('id') not in removed]
        if 'candidates' in node:
            node['candidates'] = candidates
        if node.get('asset') and node['asset'].get('id') in removed:
            replacement = candidates[-1] if candidates else None
            if node['type'] == 'asset' and (replacement is None or replacement['kind'] != node['asset']['kind'] or node['asset']['kind'] != 'image'):
                dropped.add(node['id']); touched += 1
                continue
            node['asset'] = replacement
            node['selectedCandidateId'] = replacement['id'] if replacement else None
        elif node.get('selectedCandidateId') in removed:
            node['selectedCandidateId'] = node['asset']['id'] if node.get('asset') else None
        lost_input = False
        if 'referenceAssets' in node:
            kept = [a for a in node['referenceAssets'] if a.get('id') not in removed]
            lost_input = len(kept) != len(node['referenceAssets'])
            node['referenceAssets'] = kept
        if 'referenceGroups' in node:
            groups = []
            for group in node['referenceGroups']:
                ids = [i for i in group.get('asset_ids', []) if i not in removed]
                if ids:
                    groups.append({**group, 'asset_ids': ids})
            node['referenceGroups'] = groups
        if 'referenceOrder' in node:
            node['referenceOrder'] = [i for i in node['referenceOrder'] if i not in removed]
        if 'referenceMentions' in node:
            node['referenceMentions'] = {k: v for k, v in node['referenceMentions'].items() if v not in removed}
        if lost_input and node['type'] in GENERATION and node.get('asset'):
            node['upstreamStale'] = True
        if json.dumps(node, sort_keys=True) != original:
            touched += 1
        nodes.append(node)
    edges = []
    for edge in document.get('edges', []):
        if edge['source'] in dropped or edge['target'] in dropped:
            continue
        edges.append(edge)
    if dropped:
        # Downstream generation nodes lost a connected input: mark existing outputs stale.
        orphaned = {e['target'] for e in document.get('edges', []) if e['source'] in dropped and e['target'] not in dropped}
        for index, node in enumerate(nodes):
            if node['id'] in orphaned and node['type'] in GENERATION and node.get('asset') and not node.get('upstreamStale'):
                nodes[index] = {**node, 'upstreamStale': True}
                touched += 1
    result = {**document, 'nodes': nodes, 'edges': edges}
    if 'groups' in document:
        groups = []
        for group in document['groups']:
            members = [m for m in group['nodeIds'] if m not in dropped]
            if members:
                updated = {**group, 'nodeIds': members}
                if updated.get('keyframeNodeId') in dropped:
                    updated.pop('keyframeNodeId')
                groups.append(updated)
        result['groups'] = groups
    return result, touched, len(dropped)


def _library_path(row):
    root = store.asset_root()
    path = root / 'library' / row['project_id'] / row['filename']
    if path.resolve() != path or not path.is_relative_to(root):
        raise store.CanvasError('素材路径不安全', 409)
    return path


def _plan(db, keys):
    from canvas_catalog import selection_from_key
    from canvas_cleanup import is_deleted, is_library_asset_deleted
    local_rows, library_rows, direct, missing, rejected = [], [], {}, [], []
    active = _active_workflows(db)
    for key in keys:
        source, ident = selection_from_key(key)['source'], key.split(':', 1)[1]
        if source in ('task', 'cupsy'):
            rejected.append({'key': key, 'error': '生成历史与 Cupsy 远端素材不在本地删除范围'})
            continue
        table = {'local': 'canvas_local_uploads', 'library': 'canvas_library_assets', 'workflow': 'canvas_assets'}[source]
        row = db.execute(f'SELECT * FROM {table} WHERE id=?', (ident,)).fetchone()
        # Archived projects/canvases keep their retention obligation: treat as absent.
        if row is None or (source == 'library' and (is_deleted('project', row['project_id']) or is_library_asset_deleted(ident))) \
                or (source == 'workflow' and row['workflow_id'] not in active):
            missing.append(key)
        elif source == 'local':
            local_rows.append(dict(row))
        elif source == 'library':
            library_rows.append(dict(row))
        else:
            direct[ident] = dict(row)
    sources = ['local:' + r['id'] for r in local_rows] + ['library:' + r['id'] for r in library_rows] + ['workflow:' + i for i in direct]
    copies = {i: a for i, a in _derived_copies(db, sources).items() if i not in direct}
    deletable = {i: a for i, a in copies.items() if a['workflow_id'] in active}
    canvas_assets = {**direct, **deletable}
    by_workflow = {}
    for asset in canvas_assets.values():
        by_workflow.setdefault(asset['workflow_id'], set()).add(asset['id'])
    documents, touched_nodes, removed_nodes = {}, 0, 0
    for workflow_id, ids in by_workflow.items():
        row = db.execute('SELECT document FROM canvas_workflows WHERE id=?', (workflow_id,)).fetchone()
        document, touched, dropped = strip_document(json.loads(row['document']), ids)
        documents[workflow_id] = document
        touched_nodes += touched
        removed_nodes += dropped
    return {'local_rows': local_rows, 'library_rows': library_rows, 'direct': direct, 'missing': missing, 'rejected': rejected,
            'copies': deletable, 'canvas_assets': canvas_assets, 'archived_copies': len(copies) - len(deletable),
            'documents': documents, 'affected_nodes': touched_nodes, 'removed_nodes': removed_nodes,
            'deleted_keys': [k for k in sources]}


def _summary(plan):
    return {'items': len(plan['deleted_keys']), 'canvas_copies': len(plan['copies']),
            'workflows': len(plan['documents']), 'workflow_ids': sorted(plan['documents']), 'affected_nodes': plan['affected_nodes'],
            'removed_nodes': plan['removed_nodes'], 'archived_copies_retained': plan['archived_copies'],
            'missing': plan['missing'], 'rejected': plan['rejected']}


def preview(keys):
    db = tasks.get_db()
    owns = not db.in_transaction
    if owns:
        db.execute('BEGIN')
    try:
        return _summary(_plan(db, keys))
    finally:
        if owns:
            db.rollback()


def _paths_in_use(db):
    """Files still owned by a remaining registration (dedup/shared originals)."""
    used = {_local_path(r) for r in db.execute('SELECT * FROM canvas_local_uploads')}
    used |= {_workflow_asset_path(r) for r in db.execute('SELECT * FROM canvas_assets')}
    used |= {_library_path(r) for r in db.execute('SELECT * FROM canvas_library_assets')}
    for table, column in (('task_assets', 'path'), ('provider_assets', 'local_path')):
        used |= {Path(r[0]).absolute() for r in db.execute(f'SELECT {column} FROM {table}') if r[0]}
    return used


def delete_items(keys):
    staged, token = [], uuid.uuid4().hex
    try:
        with store.write_transaction() as db:
            plan = _plan(db, keys)
            removed_keys = plan['deleted_keys'] + ['workflow:' + i for i in plan['copies']]
            for row in plan['local_rows']:
                db.execute('DELETE FROM canvas_local_uploads WHERE id=?', (row['id'],))
            removed_library = {r['id'] for r in plan['library_rows']}
            for asset_id in removed_library:
                db.execute('DELETE FROM canvas_library_asset_locations WHERE asset_id=?', (asset_id,))
                db.execute('DELETE FROM canvas_library_assets WHERE id=?', (asset_id,))
            if removed_library:
                # Project asset groups drop deleted members; a group left empty is removed.
                for group in db.execute('SELECT id,asset_ids FROM canvas_asset_groups').fetchall():
                    ids = json.loads(group['asset_ids'])
                    kept = [i for i in ids if i not in removed_library]
                    if len(kept) == len(ids):
                        continue
                    if kept:
                        db.execute('UPDATE canvas_asset_groups SET asset_ids=?,updated_at=? WHERE id=?', (json.dumps(kept), tasks.utcnow(), group['id']))
                    else:
                        db.execute('DELETE FROM canvas_asset_groups WHERE id=?', (group['id'],))
            for asset_id in plan['canvas_assets']:
                db.execute('DELETE FROM canvas_assets WHERE id=?', (asset_id,))
                db.execute('DELETE FROM canvas_asset_copies WHERE asset_id=?', (asset_id,))
            for key in removed_keys:
                for table in ('canvas_catalog_origins', 'canvas_catalog_hidden', 'canvas_catalog_item_tags'):
                    db.execute(f'DELETE FROM {table} WHERE item_key=?', (key,))
                db.execute('DELETE FROM canvas_asset_copies WHERE source_key=?', (key,))
            now = tasks.utcnow()
            for workflow_id, document in plan['documents'].items():
                encoded = store.validate_document(document, workflow_id)
                db.execute('UPDATE canvas_workflows SET document=?,revision=revision+1,updated_at=? WHERE id=?', (encoded, now, workflow_id))
                db.execute('UPDATE canvas_projects SET updated_at=? WHERE id=(SELECT project_id FROM canvas_workflows WHERE id=?)', (now, workflow_id))
            files, retained, in_use = [], 0, _paths_in_use(db)
            for row in plan['local_rows']:
                path = _local_path(row)
                if path in in_use or db.execute('SELECT 1 FROM canvas_local_uploads WHERE sha256=?', (row['sha256'],)).fetchone():
                    retained += 1
                else:
                    files.append(path)
            for path in [_library_path(r) for r in plan['library_rows']] + [_workflow_asset_path(a) for a in plan['canvas_assets'].values()]:
                if path in in_use:
                    retained += 1
                else:
                    files.append(path)
                    thumbnail = Path(str(path) + '.thumb.webp')
                    if thumbnail.exists():
                        files.append(thumbnail)
            # Stage inside the transaction: any failure renames back and rolls back the rows.
            for path in files:
                if not path.exists():
                    continue
                pending = path.with_name(f'{path.name}.deleting-{token}')
                try:
                    os.rename(path, pending)
                except OSError as error:
                    raise store.CanvasError(f'素材文件无法删除，未做任何更改：{path.name}', 409) from error
                staged.append((path, pending))
            summary = _summary(plan)
    except BaseException:
        for path, pending in reversed(staged):
            try:
                os.rename(pending, path)
            except OSError:
                pass
        raise
    leftovers = 0
    for _, pending in staged:
        try:
            pending.unlink()
        except OSError:
            leftovers += 1  # unregistered and never served; reclaimable by maintenance
    return {'success': not summary['rejected'], **summary, 'deleted_keys': plan['deleted_keys'],
            'deleted_copy_ids': sorted(plan['copies']), 'workflow_ids': sorted(plan['documents']),
            'files_removed': len(staged) - leftovers, 'files_retained_shared': retained, 'files_pending': leftovers}


def register_routes(bp, body):
    from flask import jsonify, request

    @bp.post('/api/canvas/library/items/delete-preview')
    def delete_preview():
        require_same_origin(request)
        return jsonify(success=True, **preview(parse_keys(body().get('keys'))))

    @bp.post('/api/canvas/library/items/bulk-delete')
    def bulk_delete():
        require_same_origin(request)
        result = delete_items(parse_keys(body().get('keys')))
        return jsonify(result), 200
