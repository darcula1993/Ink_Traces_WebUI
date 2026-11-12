"""Explicit archival and retryable, reference-aware local media cleanup."""
import json
import hashlib
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
        if plan['cleanup_assets'] and task_id not in plan.get('shared_task_ids',[]) and any(c.get('task_id')==task_id and c.get('output') for c in plan['candidates']):
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
        if not prior['cleanup_assets']:
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
            if plan['cleanup_assets'] != cleanup:
                raise store.CanvasError('删除重试必须保留原清理选项', 409)
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
                if not archive['cleanup_assets']: other_tasks.update(archive.get('task_ids',[]))
            for tid in own_tasks:
                task = tasks.get_task(tid)
                if task and (task['status'] not in ('succeeded','failed','cancelled') or task.get('lease_owner')):
                    raise store.CanvasError('画布存在活动任务，请先取消并等待任务结束', 409)
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
                    plan['removed_paths'].append(raw)
                    if item['library_id']: plan['removed_library_ids'].append(item['library_id'])
                plan['done'].append(raw)
                db.execute('UPDATE canvas_deletions SET manifest=? WHERE scope=? AND id=?',(json.dumps(plan),scope,identifier));db.commit()
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
        return {'deleted':True,'cleanup_assets':cleanup,'removed_files':len(plan['done'])-plan['retained_shared'],'retained_shared':plan['retained_shared'],'retained_ambiguous':plan.get('retained_ambiguous',0)}
    except OSError:
        db.rollback()
        raise store.CanvasError('部分文件尚未清理，删除记录已保留，请重试',409)
    except Exception:
        db.rollback()
        raise


def register_cleanup_routes(blueprint, body):
    from flask import jsonify
    @blueprint.route('/api/canvas/deletions', methods=['GET'])
    def pending_deletions():
        init_cleanup_db()
        result=[]
        for row in tasks.get_db().execute('SELECT * FROM canvas_deletions WHERE completed=0'):
            plan=json.loads(row['manifest'])
            result.append({'scope':row['scope'],'id':row['id'],'title':plan.get('title',row['id']),'cleanup_assets':plan['cleanup_assets'],'cleanup_pending':True})
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
    @blueprint.route('/api/canvas/workflows/<identifier>', methods=['DELETE'])
    def delete_workflow(identifier):
        return respond('workflow',identifier)
