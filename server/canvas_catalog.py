"""Authenticated local media catalog; selections are identities, never client URLs."""
import io
import re
import uuid
from pathlib import Path

from flask import jsonify, request, send_file
import canvas_store as store
import tasks
import storage

SOURCES = {'generated', 'saved', 'uploaded', 'local'}
KINDS = {'image', 'video', 'audio'}


def init_catalog_db():
    tasks.get_db().executescript('''
    CREATE TABLE IF NOT EXISTS canvas_catalog_origins (
        item_key TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(item_key,origin));
    CREATE TABLE IF NOT EXISTS canvas_catalog_hidden (item_key TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS canvas_catalog_tags (id TEXT PRIMARY KEY, title TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS canvas_catalog_item_tags (
        item_key TEXT NOT NULL, tag_id TEXT NOT NULL REFERENCES canvas_catalog_tags(id) ON DELETE CASCADE,
        PRIMARY KEY(item_key,tag_id));
    ''')
    tasks.get_db().commit()
    from local_uploads import init_local_uploads_db
    init_local_uploads_db()
    from local_delete import init_copy_db
    init_copy_db()


def record_origin(source, asset_id, origin):
    key = f'{source}:{asset_id}'
    db = tasks.get_db()
    db.execute('INSERT OR IGNORE INTO canvas_catalog_origins VALUES (?,?,?)', (key, origin, tasks.utcnow()))
    db.execute('DELETE FROM canvas_catalog_hidden WHERE item_key=?', (key,))


def parse_selection(value):
    if not isinstance(value, dict) or set(value) != {'source','id'}:
        raise store.CanvasError('素材选择格式无效')
    source, ident = value['source'], value['id']
    if source not in ('library','workflow','task','cupsy','local') or not isinstance(ident, str):
        raise store.CanvasError('素材选择编号无效')
    if not re.fullmatch(r'[1-9][0-9]{0,18}' if source in ('task','cupsy') else r'[0-9a-f]{32}', ident):
        raise store.CanvasError('素材选择编号无效')
    if source in ('task','cupsy') and int(ident) > 9223372036854775807:
        raise store.CanvasError('素材选择编号无效')
    return source, ident, f'{source}:{ident}'


def selection_from_key(key):
    source, separator, ident = key.partition(':')
    if not separator:
        raise store.CanvasError('素材编号无效')
    value = {'source':source,'id':ident}
    parse_selection(value)
    return value


def task_projects(task):
    from canvas_cleanup import is_deleted
    ids = {r['workflow_id'] for r in tasks.get_db().execute('SELECT workflow_id FROM canvas_workflow_tasks WHERE task_id=?',(task['id'],))}
    params = task.get('params') or {}
    if params.get('canvas_workflow_id'):
        ids.add(params['canvas_workflow_id'])
    projects = []
    for wid in sorted(ids):
        try:
            wf = store.workflow(wid)
            if wf['project_id'] not in projects:
                projects.append(wf['project_id'])
        except store.CanvasError:
            pass
    return projects, bool(ids)


def resolve(value, check_file=True):
    source, ident, key = parse_selection(value)
    if tasks.get_db().execute('SELECT 1 FROM canvas_catalog_hidden WHERE item_key=?',(key,)).fetchone():
        raise store.CanvasError('素材已移出素材库',404)
    if source == 'local':
        row=tasks.get_db().execute('SELECT * FROM canvas_local_uploads WHERE id=?',(ident,)).fetchone()
        if row is None: raise store.CanvasError('本地上传素材不存在',404)
        from local_uploads import path_for
        return dict(row), path_for(row) if check_file else None, []
    if source == 'cupsy':
        row = tasks.get_provider_asset(int(ident))
        if not row or row.get('deleted_at') or row.get('provider') != 'cupsy':
            raise store.CanvasError('Cupsy素材不存在或不属于当前素材库',404)
        if row.get('status') != 'active' or row.get('kind') not in KINDS:
            raise store.CanvasError('Cupsy素材尚未就绪或媒体类型无效',409)
        path = Path(row['local_path']).absolute()
        root = Path(storage.WORKSPACE_ASSET_DIR).absolute()
        if path.resolve() != path or root.resolve() != root or not path.is_relative_to(root) or not path.is_file():
            raise store.CanvasError('Cupsy本地素材文件不可读取',409)
        mime, _ = store._detect_media(path)
        if mime.split('/')[0] != row['kind']:
            raise store.CanvasError('Cupsy本地素材类型与登记不符',409)
        return {**row, 'name':row.get('original_name') or path.name}, path, []
    if source != 'task':
        table = 'canvas_library_assets' if source == 'library' else 'canvas_assets'
        row = tasks.get_db().execute(f'SELECT * FROM {table} WHERE id=?',(ident,)).fetchone()
        if row is None:
            raise store.CanvasError('素材不存在',404)
        owner = row['project_id'] if source == 'library' else row['workflow_id']
        row = store.get_asset(owner, ident, library=source=='library')
        pid = owner if source == 'library' else store.workflow(owner)['project_id']
        try:
            path = store.asset_path(row) if check_file else None
        except store.CanvasError as error:
            raise store.CanvasError('素材文件不可读取',409) from error
        return row, path, [pid]
    row = tasks.get_db().execute('SELECT * FROM task_assets WHERE id=?',(ident,)).fetchone()
    if row is None or row['kind'] not in ('output_image','output_video','output_audio'):
        raise store.CanvasError('任务产物不存在',404)
    task = tasks.get_task(row['task_id'])
    from canvas_cleanup import task_restore_blocked
    if not task or task.get('deleted_at') or task['status'] != 'succeeded' or task_restore_blocked(task['id']):
        raise store.CanvasError('任务产物不可用',409)
    projects, was_owned = task_projects(task)
    if was_owned and not projects:
        raise store.CanvasError('任务所属画布已归档',404)
    path, root = Path(row['path']).absolute(), Path(storage.OUTPUT_DIR).absolute()
    if path.resolve() != path or root.resolve() != root or not path.is_relative_to(root) or not path.is_file():
        raise store.CanvasError('任务产物文件不可读取',409)
    return dict(row), path, projects


def tags_for(key):
    return [dict(r) for r in tasks.get_db().execute('SELECT t.* FROM canvas_catalog_tags t JOIN canvas_catalog_item_tags a ON a.tag_id=t.id WHERE a.item_key=? ORDER BY t.title,t.id',(key,))]


def query_items(args):
    from canvas_catalog_query import query
    return query(args)


def transfer(target, data, library=False):
    items = data.get('items')
    if not isinstance(items,list) or not items or len(items)>100:
        raise store.CanvasError('请选择1至100个素材')
    mapping = {}
    with store.write_transaction():
        store.get_project(target) if library else store.workflow(target)
        for selection in items:
            source, ident, key = parse_selection(selection)
            if key in mapping:
                continue
            row, path, _ = resolve(selection)
            try:
                with path.open('rb') as handle:
                    asset = store.save_asset(target,handle,row.get('name',path.name),library=library,copy_source=None if library else key)
            except OSError as error:
                raise store.CanvasError('素材文件已改变，请重试',409) from error
            mapping[key] = asset
            if library:
                record_origin('library',asset['id'],'saved')
                if 'folder_id' in data:
                    from canvas_library_folders import edit_asset
                    edit_asset(target,asset['id'],{'folder_id':data['folder_id']})
            else:
                # Copy provenance is recorded by save_asset(copy_source=key); see local_delete.
                if source=='task':
                    from canvas_cleanup import record_task_reference
                    record_task_reference(target,row['task_id'])
    return {'success':True,'assets':list({a['id']:a for a in mapping.values()}.values()),'mapping':mapping,'groups':[]}


def register_routes(bp, body):
    @bp.get('/api/canvas/library/items')
    def items():
        return jsonify(query_items(request.args))

    @bp.post('/api/canvas/workflows/<workflow_id>/library-references')
    def references(workflow_id):
        return jsonify(transfer(workflow_id,body()))

    @bp.post('/api/canvas/projects/<project_id>/library-items/save')
    def save(project_id):
        return jsonify(transfer(project_id,body(),library=True)),201

    @bp.get('/api/canvas/library/items/<key>/download')
    def download(key):
        row,path,_ = resolve(selection_from_key(key))
        response = send_file(path,as_attachment=request.args.get('inline') != '1',download_name=row.get('name',path.name),mimetype=row['mime_type'],conditional=True)
        response.headers['Cache-Control'] = 'private, no-cache'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @bp.get('/api/canvas/library/items/<key>/thumbnail')
    def thumbnail(key):
        from PIL import Image, ImageOps
        row, path, _ = resolve(selection_from_key(key))
        if row['kind'] not in ('image', 'output_image'):
            raise store.CanvasError('此素材没有图片缩略图',404)
        output = io.BytesIO()
        try:
            with Image.open(path) as original:
                original.draft('RGB', (320,320))
                picture = ImageOps.exif_transpose(original)
                picture.thumbnail((320,320))
                picture.convert('RGB').save(output,format='WEBP',quality=75)
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            output.close()
            raise store.CanvasError('缩略图不可用',409) from error
        output.seek(0)
        response = send_file(output,mimetype='image/webp')
        response.headers['Cache-Control'] = 'private, max-age=60'
        response.call_on_close(output.close)
        return response

    @bp.get('/api/canvas/library/item-selection')
    def select_all():
        from canvas_catalog_query import select_all as matching
        return jsonify(matching(request.args))

    import local_delete
    local_delete.register_routes(bp, body)

    @bp.delete('/api/canvas/library/items/<key>')
    def remove(key):
        selection = selection_from_key(key)
        if selection['source']=='cupsy':
            raise store.CanvasError('Cupsy素材请通过原远端素材管理入口删除',409)
        if selection['source']=='task':
            raise store.CanvasError('生成产物请通过任务回收站移除，操作会影响整个任务',409)
        # 2026-11-13: deleting from 本地素材 (local/library/workflow) is permanent, same path as bulk delete.
        local_delete.require_same_origin(request, json_body=False)
        result = local_delete.delete_items([key])
        if result['missing']:
            raise store.CanvasError('素材不存在',404)
        return jsonify(result)

    @bp.route('/api/canvas/library/tags',methods=['GET','POST'])
    def tags():
        if request.method=='GET':
            return jsonify(success=True,tags=[dict(r) for r in tasks.get_db().execute('SELECT * FROM canvas_catalog_tags ORDER BY title,id')])
        title = store.title_value(body().get('title'))
        ident = uuid.uuid4().hex
        with store.write_transaction() as db:
            if db.execute('SELECT 1 FROM canvas_catalog_tags WHERE title=?',(title,)).fetchone():
                raise store.CanvasError('标签名称已存在',409)
            db.execute('INSERT INTO canvas_catalog_tags VALUES (?,?)',(ident,title))
        return jsonify(success=True,tag={'id':ident,'title':title}),201

    @bp.route('/api/canvas/library/tags/<tag_id>',methods=['PATCH','DELETE'])
    def tag_detail(tag_id):
        with store.write_transaction() as db:
            if not db.execute('SELECT 1 FROM canvas_catalog_tags WHERE id=?',(tag_id,)).fetchone():
                raise store.CanvasError('标签不存在',404)
            if request.method=='DELETE':
                db.execute('DELETE FROM canvas_catalog_tags WHERE id=?',(tag_id,))
                return jsonify(success=True)
            title = store.title_value(body().get('title'))
            if db.execute('SELECT 1 FROM canvas_catalog_tags WHERE title=? AND id!=?',(title,tag_id)).fetchone():
                raise store.CanvasError('标签名称已存在',409)
            db.execute('UPDATE canvas_catalog_tags SET title=? WHERE id=?',(title,tag_id))
        return jsonify(success=True,tag={'id':tag_id,'title':title})

    @bp.patch('/api/canvas/library/items/<key>/tags')
    def assign_tags(key):
        ids = body().get('tag_ids')
        if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(i,str) for i in ids):
            raise store.CanvasError('标签编号须为最多100项的数组')
        with store.write_transaction() as db:
            resolve(selection_from_key(key))
            for ident in ids:
                if not db.execute('SELECT 1 FROM canvas_catalog_tags WHERE id=?',(ident,)).fetchone():
                    raise store.CanvasError('标签不存在',404)
            db.execute('DELETE FROM canvas_catalog_item_tags WHERE item_key=?',(key,))
            db.executemany('INSERT INTO canvas_catalog_item_tags VALUES (?,?)',[(key,i) for i in dict.fromkeys(ids)])
        return jsonify(success=True,tags=tags_for(key))
