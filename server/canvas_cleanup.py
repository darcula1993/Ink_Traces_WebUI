"""Explicit archival and retryable, reference-aware local media cleanup.

LIBRARY-GLOBAL-20261116 S3: project/canvas deletion with cleanup never deletes library
files (``_library_protected``); such candidates are counted in ``retained_library``.
"""
import json
import hashlib
import os
from urllib.parse import unquote, urlsplit
from pathlib import Path
import tasks
import storage
import canvas_store as store


def init_cleanup_db():
    tasks.get_db().execute('CREATE TABLE IF NOT EXISTS canvas_deletions (scope TEXT, id TEXT, manifest TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scope,id))')
    tasks.get_db().execute('CREATE TABLE IF NOT EXISTS canvas_workflow_tasks (workflow_id TEXT NOT NULL, task_id INTEGER NOT NULL, PRIMARY KEY(workflow_id,task_id))')
    tasks.get_db().commit()


def record_task_reference(workflow_id, task_id):
    store.workflow(workflow_id)
    tasks.get_db().execute('INSERT OR IGNORE INTO canvas_workflow_tasks VALUES (?,?)',(workflow_id,task_id))


def is_deleted(scope, identifier):
    if not tasks.get_db().execute("SELECT 1 FROM sqlite_master WHERE name='canvas_deletions'").fetchone():
        return False
    return tasks.get_db().execute('SELECT 1 FROM canvas_deletions WHERE scope=? AND id=?', (scope, identifier)).fetchone() is not None


def _doc_tasks(document):
    return {n.get('task', {}).get('id') for n in document.get('nodes', []) if isinstance(n.get('task'), dict) and n['task'].get('id')}


def is_library_asset_deleted(asset_id):
    db = tasks.get_db()
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_deletions'").fetchone():
        return False
    return any(asset_id in json.loads(row['manifest']).get('removed_library_ids', [])
               for row in db.execute('SELECT manifest FROM canvas_deletions'))


def task_restore_blocked(task_id):
    db=tasks.get_db()
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_deletions'").fetchone(): return False
    for row in db.execute('SELECT manifest FROM canvas_deletions WHERE completed=0'):
        plan=json.loads(row['manifest'])
        if plan.get('cleanup_assets') and task_id not in plan.get('shared_task_ids',[]) and any(c.get('task_id')==task_id and c.get('output') for c in plan.get('candidates',[])):
            return True
    return False


def _references(db, owners, task_ids, project, scope):
    """Conservative protection, including archived scopes whose files were retained."""
    protected_hashes = {r['sha256'] for r in db.execute('SELECT * FROM canvas_assets') if r['workflow_id'] not in owners}
    protected_paths, texts = set(), []
    for row in db.execute('SELECT * FROM canvas_library_assets'):
        if row['project_id'] != project:
            protected_hashes.add(row['sha256'])
    group_ids = set()
    for row in db.execute('SELECT asset_ids FROM canvas_asset_groups'):
        group_ids.update(json.loads(row['asset_ids']))
    for row in db.execute('SELECT * FROM canvas_library_assets'):
        if row['id'] in group_ids and scope != 'project':
            protected_hashes.add(row['sha256'])
    for row in db.execute('SELECT * FROM provider_assets'):
        protected_paths.add(row['local_path']); protected_hashes.add(row['sha256'])
    live_shared = {r['current_task_id'] for r in db.execute('SELECT current_task_id FROM layer_projects') if r['current_task_id']}
    live_shared.update(r['task_id'] for r in db.execute('SELECT task_id FROM layer_revisions'))
    live_shared.update(r['task_id'] for r in db.execute('SELECT * FROM canvas_workflow_tasks') if r['workflow_id'] not in owners)
    live_shared.update(r['retry_of'] for r in db.execute('SELECT id,retry_of FROM tasks') if r['id'] not in task_ids and r['retry_of'])
    for row in db.execute('SELECT * FROM canvas_workflows'):
        if row['id'] not in owners: live_shared.update(_doc_tasks(json.loads(row['document'])))
    for row in db.execute('SELECT * FROM task_assets'):
        if row['task_id'] not in task_ids or row['task_id'] in live_shared:
            protected_paths.add(row['path'])
    for row in db.execute('SELECT * FROM tasks'):
        if row['id'] not in task_ids:
            texts.extend(str(row[k] or '') for k in ('params', 'result'))
    for table in ('workspace_state', 'layer_projects', 'layer_revisions'):
        texts.extend(json.dumps(dict(row), ensure_ascii=False) for row in db.execute('SELECT * FROM '+table))
    # A previous non-cleaning archive creates an explicit retention obligation.
    for row in db.execute('SELECT manifest FROM canvas_deletions'):
        prior = json.loads(row['manifest'])
        if not prior.get('cleanup_assets', False):
            protected_paths.update(prior.get('retained_paths', []))
    return protected_hashes, protected_paths, texts


def _reference_values(value, key=''):
    if isinstance(value, str):
        if value.startswith(('{','[')):
            try:
                yield from _reference_values(json.loads(value), key)
                return
            except ValueError:
                pass
        if '/' in value or any(hint in key.lower() for hint in ('url','path','src','reference')):
            yield unquote(urlsplit(value).path)
    elif isinstance(value, dict):
        for name, item in value.items(): yield from _reference_values(item, name)
    elif isinstance(value, list):
        for item in value: yield from _reference_values(item, key)


def _asset_path(row):
    root=store.asset_root().absolute()
    directory=root/'library'/row['project_id'] if 'project_id' in row else root/row['workflow_id']
    path=directory/row['filename']
    if path.resolve()!=path or not path.is_relative_to(root):
        raise store.CanvasError('素材清理路径不安全',409)
    return path


def _aliases(path):
    db=tasks.get_db(); result={str(path)}
    for row in db.execute('SELECT a.task_id,t.output_dir FROM task_assets a LEFT JOIN tasks t ON t.id=a.task_id WHERE a.path=?',(str(path),)):
        if row['task_id'] and row['output_dir']:
            root=Path(row['output_dir']).absolute()
            if path.is_relative_to(root):
                relative=path.relative_to(root).as_posix()
                result.update(f"/api/tasks/{row['task_id']}/{action}/{relative}" for action in ('file','download'))
    for table in ('canvas_assets','canvas_library_assets'):
        for row in db.execute('SELECT * FROM '+table):
            if _asset_path(dict(row)) == path:
                result.add(store.asset_public(dict(row))['url'])
    for root,prefix in ((Path(storage.WORKSPACE_ASSET_DIR).absolute(),'/api/workspace/assets/'),(Path(storage.UPLOAD_VIDEO_DIR).absolute(),'/api/upload_video/')):
        if path.is_relative_to(root):result.add(prefix+path.relative_to(root).as_posix())
    return result


def _library_protected(db, path, digest):
    """LIBRARY-GLOBAL S3: project/canvas deletion and cleanup never delete library files.

    Protected: anything inside ``<asset_root>/media``, a task output registered in the
    library (``task_assets.media_id``) and any file whose content is a library item.
    """
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='media'").fetchone():
        return False
    if path.is_relative_to(store.asset_root().absolute() / 'media'):
        return True
    # Outputs (and their thumbnails) of a task with a result in the library: the task card stays.
    if db.execute("""SELECT 1 FROM task_assets a WHERE a.path=? AND (COALESCE(a.media_id,'')!='' OR (a.kind LIKE 'output_%'
                     AND EXISTS (SELECT 1 FROM task_assets b WHERE b.task_id=a.task_id AND COALESCE(b.media_id,'')!='')))""",
                  (str(path),)).fetchone():
        return True
    return digest is not None and db.execute('SELECT 1 FROM media WHERE sha256=?', (digest,)).fetchone() is not None


def _protected(path, digest, protection):
    hashes, paths, texts = protection
    if digest in hashes or str(path) in paths:
        return 'shared'
    aliases=_aliases(path)
    for text in texts:
        for reference in _reference_values(text):
            if reference in aliases:
                return 'shared'
            # Only genuinely unresolved bare reference fields are conservative.
            if reference == path.name:
                return 'ambiguous'
    return False


BULK_DELETE_MAX = 200


def _active_group_run_count(db, owners):
    if not owners or not db.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_group_runs'").fetchone():
        return 0
    marks = ','.join('?' * len(owners))
    return db.execute(
        f"SELECT COUNT(*) FROM canvas_group_runs WHERE workflow_id IN ({marks}) AND status IN ('running', 'awaiting_confirm')",
        tuple(owners),
    ).fetchone()[0]


def _validate_bulk_project_ids(raw_ids):
    if not isinstance(raw_ids, list) or not raw_ids:
        raise store.CanvasError('请选择要删除的项目')
    if len(raw_ids) > 1000:
        raise store.CanvasError(f'单次最多批量处理 {BULK_DELETE_MAX} 个项目')
    seen, ids = set(), []
    for item in raw_ids:
        if not isinstance(item, str) or not item.strip():
            raise store.CanvasError('项目编号无效')
        pid = item.strip()
        if pid not in seen:
            seen.add(pid)
            ids.append(pid)
    if len(ids) > BULK_DELETE_MAX:
        raise store.CanvasError(f'单次最多批量处理 {BULK_DELETE_MAX} 个项目')
    return ids


def preview_bulk_delete_projects(raw_ids):
    ids = _validate_bulk_project_ids(raw_ids)
    init_cleanup_db()
    db = tasks.get_db()
    deleted_projects = {r['id'] for r in db.execute("SELECT id FROM canvas_deletions WHERE scope='project'")}
    deleted_workflows = {r['id'] for r in db.execute("SELECT id FROM canvas_deletions WHERE scope='workflow'")}
    projects_by_id = {
        r['id']: dict(r)
        for r in db.execute('SELECT id, title FROM canvas_projects')
        if r['id'] not in deleted_projects
    }
    project_workflows, live_workflow_counts, workflow_tasks = {}, {}, {}
    for row in db.execute('SELECT id, project_id, document FROM canvas_workflows'):
        pid, wid = row['project_id'], row['id']
        project_workflows.setdefault(pid, set()).add(wid)
        if wid not in deleted_workflows:
            live_workflow_counts[pid] = live_workflow_counts.get(pid, 0) + 1
        workflow_tasks.setdefault(wid, set()).update(_doc_tasks(json.loads(row['document'])))
    for relation in db.execute('SELECT workflow_id, task_id FROM canvas_workflow_tasks'):
        workflow_tasks.setdefault(relation['workflow_id'], set()).add(relation['task_id'])
    for task in db.execute('SELECT id, params FROM tasks'):
        wid = json.loads(task['params'] or '{}').get('canvas_workflow_id')
        if wid:
            workflow_tasks.setdefault(wid, set()).add(task['id'])
    active_task_ids = {
        r['id']
        for r in db.execute(
            "SELECT id FROM tasks WHERE status NOT IN ('succeeded','failed','cancelled') OR (lease_owner IS NOT NULL AND lease_owner != '')"
        )
    }
    active_runs_by_wf = {}
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_group_runs'").fetchone():
        for row in db.execute(
            "SELECT workflow_id, COUNT(*) AS cnt FROM canvas_group_runs WHERE status IN ('running','awaiting_confirm') GROUP BY workflow_id"
        ):
            active_runs_by_wf[row['workflow_id']] = row['cnt']

    results = []
    for pid in ids:
        project = projects_by_id.get(pid)
        if project is None:
            results.append({
                'id': pid,
                'title': '',
                'workflow_count': 0,
                'has_active_tasks': False,
                'active_task_count': 0,
                'can_delete': False,
                'reason': '项目不存在',
            })
            continue
        owners = project_workflows.get(pid, set())
        own_tasks = set().union(*(workflow_tasks.get(wid, ()) for wid in owners)) if owners else set()
        active_count = len(own_tasks & active_task_ids)
        active_runs = sum(active_runs_by_wf.get(wid, 0) for wid in owners)
        has_active = bool(active_count or active_runs)
        if active_count:
            reason = '画布存在活动任务，请先取消并等待任务结束'
        elif active_runs:
            reason = '画布存在运行中的节点组，请先取消并等待结束'
        else:
            reason = None
        results.append({
            'id': pid,
            'title': project['title'],
            'workflow_count': live_workflow_counts.get(pid, 0),
            'has_active_tasks': has_active,
            'active_task_count': active_count,
            'can_delete': not has_active,
            'reason': reason,
        })
    return results


def bulk_delete_projects(raw_ids, cleanup=False):
    ids = _validate_bulk_project_ids(raw_ids)
    if type(cleanup) is not bool:
        raise store.CanvasError('cleanup_assets必须是布尔值')
    init_cleanup_db()
    db = tasks.get_db()
    deleted, skipped = [], []
    for pid in ids:
        existing = db.execute(
            'SELECT completed, manifest FROM canvas_deletions WHERE scope=? AND id=?',
            ('project', pid),
        ).fetchone()
        if existing:
            plan = json.loads(existing['manifest'])
            pending = not bool(existing['completed'])
            skipped.append({
                'id': pid,
                'title': plan.get('title', ''),
                'error': '该项目已有待完成的删除清理，请到待完成删除中重试' if pending else '项目不存在',
                'cleanup_pending': pending,
            })
            continue
        proj_row = db.execute('SELECT title FROM canvas_projects WHERE id=?', (pid,)).fetchone()
        title = proj_row['title'] if proj_row else ''
        try:
            result = delete_scope('project', pid, cleanup)
            deleted.append({'id': pid, 'title': title, **result})
        except store.CanvasError as error:
            row = db.execute(
                'SELECT completed FROM canvas_deletions WHERE scope=? AND id=?',
                ('project', pid),
            ).fetchone()
            skipped.append({
                'id': pid,
                'title': title,
                'error': str(error),
                'cleanup_pending': bool(row and not row['completed']),
            })
    return {'deleted': deleted, 'skipped': skipped}


def _prune_empty_legacy_canvas_dir(path):
    """Remove an empty legacy canvas_assets/<wf_id> or canvas_assets/library/<proj_id> directory."""
    try:
        asset_root = store.asset_root().absolute()
        if asset_root.resolve() != asset_root:
            return False
        current = Path(path).absolute()
        if current.is_symlink():
            return False
        if not current.is_dir():
            current = current.parent
        removed = False
        while current != asset_root and current.is_relative_to(asset_root):
            if current.is_symlink() or current.resolve() != current:
                break
            rel_parts = current.relative_to(asset_root).parts
            if not rel_parts:
                break
            if rel_parts[0] in ('media', 'local_uploads'):
                break
            if rel_parts[0] == 'library' and len(rel_parts) < 2:
                break
            try:
                current.rmdir()
                removed = True
            except OSError:
                break
            current = current.parent
        return removed
    except (OSError, store.CanvasError):
        return False


def _compact_workflow_document(raw_document):
    """Compact a deleted workflow document into a provenance-preserving stub."""
    try:
        document = json.loads(raw_document or '{}')
    except (TypeError, ValueError):
        document = {}
    if isinstance(document, dict) and document.get('compacted') is True:
        return False, None
    nodes = []
    raw_nodes = document.get('nodes') if isinstance(document, dict) else None
    if isinstance(raw_nodes, list):
        for node in raw_nodes:
            if not isinstance(node, dict) or not node.get('id'):
                continue
            stub = {'id': node['id']}
            if 'type' in node and node['type'] is not None:
                stub['type'] = node['type']
            if node.get('title'):
                stub['title'] = node['title']
            task_obj = node.get('task')
            if isinstance(task_obj, dict):
                tid = task_obj.get('id')
                if isinstance(tid, int) and not isinstance(tid, bool):
                    stub['task'] = {'id': tid}
            nodes.append(stub)
    version = document.get('version', 1) if isinstance(document, dict) else 1
    if not isinstance(version, int) or isinstance(version, bool):
        version = 1
    compacted = {
        'version': version,
        'compacted': True,
        'nodes': nodes,
        'edges': [],
        'groups': [],
    }
    return True, json.dumps(compacted, ensure_ascii=False, separators=(',', ':'))


def _safe_nonneg_int(value, default=0):
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _compact_manifest(raw_manifest, existing_task_ids_fn):
    """Compact a completed deletion manifest while preserving retention obligations."""
    try:
        plan = json.loads(raw_manifest or '{}')
    except (TypeError, ValueError):
        plan = {}
    if not isinstance(plan, dict):
        plan = {}
    if plan.get('compacted') is True:
        return False, None
    cleanup_assets = bool(plan.get('cleanup_assets', False))
    workflow_ids = plan.get('workflow_ids') if isinstance(plan.get('workflow_ids'), list) else []
    removed_library_ids = plan.get('removed_library_ids') if isinstance(plan.get('removed_library_ids'), list) else []
    done = plan.get('done') if isinstance(plan.get('done'), list) else []
    retained_shared = _safe_nonneg_int(plan.get('retained_shared'))
    retained_ambiguous = _safe_nonneg_int(plan.get('retained_ambiguous'))
    retained_library = _safe_nonneg_int(plan.get('retained_library'))
    raw_removed = plan.get('removed_files')
    if isinstance(raw_removed, int) and not isinstance(raw_removed, bool) and raw_removed >= 0:
        removed_files = raw_removed
    else:
        removed_files = max(0, len(done) - retained_shared)
    compacted = {
        'title': plan.get('title', ''),
        'cleanup_assets': cleanup_assets,
        'project_id': plan.get('project_id'),
        'workflow_ids': workflow_ids,
        'removed_library_ids': removed_library_ids,
        'removed_files': removed_files,
        'retained_shared': retained_shared,
        'retained_ambiguous': retained_ambiguous,
        'retained_library': retained_library,
        'compacted': True,
    }
    if not cleanup_assets:
        existing_task_ids = existing_task_ids_fn()
        raw_task_ids = plan.get('task_ids') if isinstance(plan.get('task_ids'), list) else []
        compacted['task_ids'] = [
            tid for tid in raw_task_ids
            if isinstance(tid, int) and not isinstance(tid, bool) and tid in existing_task_ids
        ]
        raw_retained = plan.get('retained_paths') if isinstance(plan.get('retained_paths'), list) else []
        compacted['retained_paths'] = [
            path for path in raw_retained
            if isinstance(path, str) and path and os.path.exists(path)
        ]
    return True, json.dumps(compacted, ensure_ascii=False, separators=(',', ':'))


def compact_deleted_layer_projects(db=None, project_id=None):
    """Strip bloated document JSON and orphan revisions from soft-deleted layer projects.

    Preserves layer_revisions (and layer_projects.document) whenever any linked task still
    exists in ``tasks`` (needed by cost_estimate._layer_output_sizes).
    """
    db = db or tasks.get_db()
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='layer_projects'").fetchone():
        return 0
    has_revisions = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='layer_revisions'"
    ).fetchone() is not None
    query = '''SELECT lp.id, lp.document FROM layer_projects lp
               WHERE lp.deleted_at IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.id = lp.current_task_id)'''
    params = []
    if has_revisions:
        query += '''
                 AND NOT EXISTS (
                     SELECT 1 FROM layer_revisions lr
                     JOIN tasks t ON t.id = lr.task_id
                     WHERE lr.project_id = lp.id
                 )
                 AND (lp.document IS NOT NULL OR EXISTS (SELECT 1 FROM layer_revisions lr WHERE lr.project_id = lp.id))'''
    else:
        query += ' AND lp.document IS NOT NULL'
    if project_id is not None:
        query += ' AND lp.id = ?'
        params.append(int(project_id))

    owns_tx = not db.in_transaction
    compacted = 0
    try:
        if owns_tx:
            db.execute('BEGIN IMMEDIATE')
        rows = db.execute(query, params).fetchall()
        for row in rows:
            pid = row['id']
            changed = False
            if has_revisions:
                cur = db.execute(
                    'DELETE FROM layer_revisions WHERE project_id = ? AND task_id NOT IN (SELECT id FROM tasks)',
                    (pid,),
                )
                if cur.rowcount:
                    changed = True
            if row['document'] is not None:
                db.execute('UPDATE layer_projects SET document = NULL WHERE id = ?', (pid,))
                changed = True
            if changed:
                compacted += 1
        if owns_tx:
            db.commit()
    except Exception:
        if owns_tx:
            db.rollback()
        raise
    return compacted


def compact_completed_deletions(db=None):
    """Idempotently shrink completed canvas_deletions manifests and deleted workflow documents."""
    db = db or tasks.get_db()
    has_deletions = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='canvas_deletions'"
    ).fetchone() is not None
    has_workflows = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='canvas_workflows'"
    ).fetchone() is not None
    owns_tx = not db.in_transaction
    manifests_compacted = 0
    workflows_compacted = 0
    layer_projects_compacted = 0
    existing_task_ids_cache = None

    def get_existing_task_ids():
        nonlocal existing_task_ids_cache
        if existing_task_ids_cache is None:
            existing_task_ids_cache = {r['id'] for r in db.execute('SELECT id FROM tasks').fetchall()}
        return existing_task_ids_cache

    try:
        if owns_tx:
            db.execute('BEGIN IMMEDIATE')
        if has_deletions:
            pending_workflow_ids = {
                r['id'] for r in db.execute("SELECT id FROM canvas_deletions WHERE scope='workflow' AND completed=0")
            }
            if has_workflows:
                pending_project_ids = {
                    r['id'] for r in db.execute("SELECT id FROM canvas_deletions WHERE scope='project' AND completed=0")
                }
                if pending_project_ids:
                    marks = ','.join('?' * len(pending_project_ids))
                    pending_workflow_ids.update(
                        r['id'] for r in db.execute(
                            f'SELECT id FROM canvas_workflows WHERE project_id IN ({marks})',
                            tuple(pending_project_ids),
                        )
                    )

            completed_rows = db.execute(
                'SELECT scope, id, manifest FROM canvas_deletions WHERE completed=1'
            ).fetchall()
            target_workflow_ids = set()
            for row in completed_rows:
                scope, identifier, raw_manifest = row['scope'], row['id'], row['manifest']
                if has_workflows:
                    if scope == 'workflow':
                        target_workflow_ids.add(identifier)
                    elif scope == 'project':
                        target_workflow_ids.update(
                            wf['id'] for wf in db.execute(
                                'SELECT id FROM canvas_workflows WHERE project_id=?', (identifier,)
                            ).fetchall()
                        )
                changed, compacted_json = _compact_manifest(raw_manifest, get_existing_task_ids)
                if changed:
                    db.execute(
                        'UPDATE canvas_deletions SET manifest=? WHERE scope=? AND id=?',
                        (compacted_json, scope, identifier),
                    )
                    manifests_compacted += 1

            target_workflow_ids -= pending_workflow_ids
            if has_workflows and target_workflow_ids:
                for wid in sorted(target_workflow_ids):
                    wf_row = db.execute(
                        'SELECT document FROM canvas_workflows WHERE id=?', (wid,)
                    ).fetchone()
                    if wf_row is None:
                        continue
                    changed, compacted_doc = _compact_workflow_document(wf_row['document'])
                    if changed:
                        db.execute(
                            'UPDATE canvas_workflows SET document=? WHERE id=?',
                            (compacted_doc, wid),
                        )
                        workflows_compacted += 1

        layer_projects_compacted = compact_deleted_layer_projects(db)
        if owns_tx:
            db.commit()
    except Exception:
        if owns_tx:
            db.rollback()
        raise
    return {
        'manifests': manifests_compacted,
        'workflows': workflows_compacted,
        'layer_projects': layer_projects_compacted,
    }


def delete_scope(scope, identifier, cleanup=False):
    if type(cleanup) is not bool:
        raise store.CanvasError('cleanup_assets必须是布尔值')
    init_cleanup_db()
    db = tasks.get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT * FROM canvas_deletions WHERE scope=? AND id=?', (scope, identifier)).fetchone()
        if existing:
            plan = json.loads(existing['manifest'])
            if bool(plan.get('cleanup_assets', False)) != cleanup:
                raise store.CanvasError('删除重试必须保留原清理选项', 409)
            if existing['completed']:
                db.commit()
                done = plan.get('done') if isinstance(plan.get('done'), list) else []
                retained_shared = _safe_nonneg_int(plan.get('retained_shared'))
                raw_removed = plan.get('removed_files')
                if isinstance(raw_removed, int) and not isinstance(raw_removed, bool) and raw_removed >= 0:
                    removed_files = raw_removed
                else:
                    removed_files = max(0, len(done) - retained_shared)
                return {
                    'deleted': True,
                    'cleanup_assets': cleanup,
                    'removed_files': removed_files,
                    'retained_shared': retained_shared,
                    'retained_ambiguous': _safe_nonneg_int(plan.get('retained_ambiguous')),
                    'retained_library': _safe_nonneg_int(plan.get('retained_library')),
                }
        else:
            if scope == 'project':
                store.get_project(identifier)
                rows = db.execute('SELECT * FROM canvas_workflows WHERE project_id=?', (identifier,)).fetchall()
            else:
                rows = [store.workflow(identifier)]
            owners = {r['id'] for r in rows}
            project = identifier if scope == 'project' else rows[0]['project_id']
            own_tasks, other_tasks = set(), set()
            for row in db.execute('SELECT * FROM canvas_workflows'):
                document = json.loads(row['document'])
                (own_tasks if row['id'] in owners else other_tasks).update(_doc_tasks(document))
            for relation in db.execute('SELECT * FROM canvas_workflow_tasks'):
                (own_tasks if relation['workflow_id'] in owners else other_tasks).add(relation['task_id'])
            for task in db.execute('SELECT id,params FROM tasks'):
                if json.loads(task['params'] or '{}').get('canvas_workflow_id') in owners:
                    own_tasks.add(task['id'])
            other_tasks.update(r['current_task_id'] for r in db.execute('SELECT current_task_id FROM layer_projects') if r['current_task_id'])
            other_tasks.update(r['task_id'] for r in db.execute('SELECT task_id FROM layer_revisions'))
            other_tasks.update(r['retry_of'] for r in db.execute('SELECT id,retry_of FROM tasks') if r['id'] not in own_tasks and r['retry_of'])
            for prior in db.execute('SELECT manifest FROM canvas_deletions'):
                archive=json.loads(prior['manifest'])
                if not archive.get('cleanup_assets', False): other_tasks.update(archive.get('task_ids',[]))
            for tid in own_tasks:
                task = tasks.get_task(tid)
                if task and (task['status'] not in ('succeeded','failed','cancelled') or task.get('lease_owner')):
                    raise store.CanvasError('画布存在活动任务，请先取消并等待任务结束', 409)
            if _active_group_run_count(db, owners):
                raise store.CanvasError('画布存在运行中的节点组，请先取消并等待结束', 409)
            own_assets = [dict(r) for r in db.execute('SELECT * FROM canvas_assets') if r['workflow_id'] in owners]
            hashes = {r['sha256'] for r in own_assets}
            library = [dict(r) for r in db.execute('SELECT * FROM canvas_library_assets WHERE project_id=?', (project,)) if scope == 'project' or r['sha256'] in hashes]
            candidates = [{'path':str(_asset_path(a)), 'sha256':a['sha256'], 'library_id':a['id'] if 'project_id' in a else None} for a in own_assets+library]
            for tid in own_tasks-other_tasks:
                for asset in tasks.list_assets(tid):
                    if asset['kind'].startswith(('output_', 'input_')):
                        candidates.append({'path':asset['path'], 'sha256':None, 'library_id':None, 'task_id':tid, 'output':asset['kind'].startswith('output_')})
            for item in list(candidates):
                thumbnail=Path(item['path']+'.thumb.webp')
                if thumbnail.exists():
                    candidates.append({**item,'path':str(thumbnail),'source_path':item['path'],'library_id':None})
            plan = {'title': (store.get_project(identifier)['title'] if scope=='project' else rows[0]['title']), 'library_snapshot':library, 'cleanup_assets':cleanup, 'candidates':candidates, 'done':[], 'removed_paths':[], 'removed_library_ids':[], 'retained_shared':0, 'retained_ambiguous':0, 'workflow_ids':sorted(owners), 'task_ids':sorted(own_tasks), 'shared_task_ids':sorted(other_tasks), 'project_id':project, 'retained_paths':[c['path'] for c in candidates] if not cleanup else []}
            db.execute('INSERT INTO canvas_deletions(scope,id,manifest) VALUES(?,?,?)', (scope,identifier,json.dumps(plan)))
        db.commit()
        if cleanup:
            for item in plan['candidates']:
                raw=item['path']
                if raw in plan['done']: continue
                db.execute('BEGIN IMMEDIATE')
                protection=_references(db,set(plan['workflow_ids']),set(plan['task_ids'])-set(plan['shared_task_ids']),plan['project_id'],scope)
                path=Path(raw).absolute()
                roots=[store.asset_root().absolute(),Path(storage.OUTPUT_DIR).absolute(),Path(storage.WORKSPACE_ASSET_DIR).absolute(),Path(storage.UPLOAD_VIDEO_DIR).absolute()]
                if path.resolve()!=path or not any(root.resolve()==root and path.is_relative_to(root) for root in roots):
                    raise store.CanvasError('清理路径不安全，文件保留，请检查删除记录',409)
                digest=item['sha256']
                hash_path=Path(item.get('source_path',raw)).absolute()
                if hash_path.resolve()!=hash_path or not any(hash_path.is_relative_to(root) for root in roots):
                    raise store.CanvasError('清理来源路径不安全',409)
                if digest is None and hash_path.is_file():
                    with hash_path.open('rb') as handle: digest=hashlib.file_digest(handle,'sha256').hexdigest()
                reason=_protected(Path(item.get('source_path',raw)),digest,protection)
                if not reason and (_library_protected(db,path,None) or _library_protected(db,hash_path,digest)):
                    reason='library'; plan['retained_library']=plan.get('retained_library',0)+1
                if reason:
                    plan['retained_shared']+=1
                    if reason=='ambiguous': plan['retained_ambiguous']=plan.get('retained_ambiguous',0)+1
                else:
                    if item.get('task_id') and item.get('output'):
                        tid=item['task_id']
                        row=db.execute('SELECT params FROM tasks WHERE id=?',(tid,)).fetchone()
                        params=json.loads(row['params'] or '{}');params['canvas_outputs_purged']=True
                        db.execute('UPDATE tasks SET deleted_at=?,params=? WHERE id=?',(tasks.utcnow(),json.dumps(params),tid))
                    path.unlink(missing_ok=True)
                    _prune_empty_legacy_canvas_dir(path)
                    plan['removed_paths'].append(raw)
                    if item['library_id']: plan['removed_library_ids'].append(item['library_id'])
                plan['done'].append(raw)
                db.execute('UPDATE canvas_deletions SET manifest=? WHERE scope=? AND id=?',(json.dumps(plan),scope,identifier));db.commit()
            asset_root = store.asset_root().absolute()
            for wid in plan.get('workflow_ids', []):
                _prune_empty_legacy_canvas_dir(asset_root / wid)
            if scope == 'project' and plan.get('project_id'):
                _prune_empty_legacy_canvas_dir(asset_root / 'library' / plan['project_id'])
        result = {
            'deleted': True,
            'cleanup_assets': cleanup,
            'removed_files': len(plan['done']) - plan['retained_shared'],
            'retained_shared': plan['retained_shared'],
            'retained_ambiguous': plan.get('retained_ambiguous', 0),
            'retained_library': plan.get('retained_library', 0),
        }
        with db:
            for asset_id in plan['removed_library_ids']:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_library_asset_locations'").fetchone():
                    db.execute('DELETE FROM canvas_library_asset_locations WHERE asset_id=?',(asset_id,))
                db.execute('DELETE FROM canvas_library_assets WHERE id=?',(asset_id,))
            for tid in set(plan['task_ids'])-set(plan['shared_task_ids']):
                outputs=[c['path'] for c in plan['candidates'] if c.get('task_id')==tid and c.get('output')]
                if cleanup and outputs and all(p in plan['removed_paths'] for p in outputs):
                    row=db.execute('SELECT params FROM tasks WHERE id=?',(tid,)).fetchone()
                    params=json.loads(row['params'] or '{}');params['canvas_outputs_purged']=True
                    db.execute('UPDATE tasks SET deleted_at=?,params=? WHERE id=?',(tasks.utcnow(),json.dumps(params),tid))
            db.execute('UPDATE canvas_deletions SET completed=1 WHERE scope=? AND id=?',(scope,identifier))
            compact_completed_deletions(db)
        return result
    except OSError:
        db.rollback()
        raise store.CanvasError('部分文件尚未清理，删除记录已保留，请重试',409)
    except Exception:
        db.rollback()
        raise


def register_cleanup_routes(blueprint, body):
    from flask import jsonify, request
    from local_delete import require_same_origin
    @blueprint.route('/api/canvas/deletions', methods=['GET'])
    def pending_deletions():
        init_cleanup_db()
        result=[]
        for row in tasks.get_db().execute('SELECT * FROM canvas_deletions WHERE completed=0'):
            plan=json.loads(row['manifest'])
            result.append({'scope':row['scope'],'id':row['id'],'title':plan.get('title',row['id']),'cleanup_assets':bool(plan.get('cleanup_assets',False)),'cleanup_pending':True})
        return jsonify(success=True,deletions=result)
    def respond(scope, identifier):
        init_cleanup_db()
        try:
            return jsonify(success=True, **delete_scope(scope, identifier, body().get('cleanup_assets', False)))
        except store.CanvasError as error:
            row=tasks.get_db().execute('SELECT completed FROM canvas_deletions WHERE scope=? AND id=?',(scope,identifier)).fetchone()
            return jsonify(success=False,error=str(error),cleanup_pending=bool(row and not row['completed'])),error.status
    @blueprint.route('/api/canvas/projects/<identifier>', methods=['DELETE'])
    def delete_project(identifier):
        return respond('project',identifier)
    @blueprint.route('/api/canvas/projects/bulk-delete-preview', methods=['POST'])
    def bulk_delete_projects_preview():
        require_same_origin(request)
        init_cleanup_db()
        return jsonify(success=True, projects=preview_bulk_delete_projects(body().get('ids')))
    @blueprint.route('/api/canvas/projects/bulk-delete', methods=['POST'])
    def bulk_delete_projects_route():
        require_same_origin(request)
        init_cleanup_db()
        data = body()
        return jsonify(success=True, **bulk_delete_projects(data.get('ids'), data.get('cleanup_assets', False)))
    @blueprint.route('/api/canvas/workflows/<identifier>', methods=['DELETE'])
    def delete_workflow(identifier):
        return respond('workflow',identifier)
