"""Project media library and explicit, durable workflow reference snapshots."""
import json
import uuid

from flask import jsonify, request, send_file

import canvas_store as store
import tasks as task_db


def init_library_db():
    db = task_db.get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS canvas_library_assets (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL,
            mime_type TEXT NOT NULL, kind TEXT NOT NULL, sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL, filename TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(project_id, sha256),
            FOREIGN KEY(project_id) REFERENCES canvas_projects(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS canvas_asset_groups (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
            asset_ids TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES canvas_projects(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_canvas_asset_groups_project ON canvas_asset_groups(project_id);
    ''')
    db.commit()
    from canvas_library_folders import init_folder_db
    init_folder_db()


def _ids(value, maximum=100):
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(i, str) or not store.ID.fullmatch(i) for i in value):
        raise store.CanvasError('素材或组ID数组无效')
    return list(dict.fromkeys(value))


def group_result(row):
    row = dict(row)
    row['asset_ids'] = json.loads(row['asset_ids'])
    return row


def get_group(project_id, group_id):
    store.get_project(project_id)
    row = task_db.get_db().execute('SELECT * FROM canvas_asset_groups WHERE project_id=? AND id=?', (project_id, group_id)).fetchone()
    if row is None:
        raise store.CanvasError('素材组不存在', 404)
    return group_result(row)


def save_group(project_id, title, asset_ids, group_id=None):
    store.get_project(project_id)
    title = store.title_value(title)
    asset_ids = _ids(asset_ids)
    if not asset_ids:
        raise store.CanvasError('素材组至少需要一个素材')
    for asset_id in asset_ids:
        store.get_asset(project_id, asset_id, library=True)
    now = task_db.utcnow()
    db = task_db.get_db()
    with store.write_transaction():
        store.get_project(project_id)
        for asset_id in asset_ids:
            store.get_asset(project_id, asset_id, library=True)
        if group_id:
            get_group(project_id, group_id)
            db.execute('UPDATE canvas_asset_groups SET title=?,asset_ids=?,updated_at=? WHERE project_id=? AND id=?',
                       (title, json.dumps(asset_ids), now, project_id, group_id))
        else:
            group_id = uuid.uuid4().hex
            db.execute('INSERT INTO canvas_asset_groups VALUES (?,?,?,?,?,?)',
                       (group_id, project_id, title, json.dumps(asset_ids), now, now))
        return get_group(project_id, group_id)


def copy_asset(source, target_id, library=False, copy_source=None):
    try:
        with store.write_transaction():
            source_library = 'project_id' in source
            owner = source['project_id'] if source_library else source['workflow_id']
            source = store.get_asset(owner, source['id'], library=source_library)
            with store.asset_path(source).open('rb') as handle:
                return store.save_asset(target_id, handle, source['name'], library=library, copy_source=copy_source)
    except OSError:
        raise store.CanvasError('素材文件无法读取', 409)


def register_library_routes(blueprint, read_body):
    import canvas_library_folders as folders
    from canvas_cleanup import is_library_asset_deleted
    folders.register_folder_routes(blueprint, read_body)
    @blueprint.route('/api/canvas/projects/<project_id>/assets', methods=['GET', 'POST'])
    def library_assets(project_id):
        store.get_project(project_id)
        if request.method == 'GET':
            rows = task_db.get_db().execute('SELECT * FROM canvas_library_assets WHERE project_id=? ORDER BY created_at DESC,id', (project_id,))
            hidden = {r['item_key'] for r in task_db.get_db().execute('SELECT item_key FROM canvas_catalog_hidden')}
            assets = [store.asset_public(dict(row)) for row in rows if not is_library_asset_deleted(row['id']) and 'library:'+row['id'] not in hidden]
            placement = {asset['id']: None for asset in assets}
            placement.update(folders.placements(project_id))
            if 'folder_id' in request.args:
                selected = request.args['folder_id'] or None
                folders.validate_parent(project_id, selected)
                assets = [asset for asset in assets if placement[asset['id']] == selected]
            return jsonify(success=True, assets=assets, placements=placement)
        upload = request.files.get('file')
        if upload is None:
            raise store.CanvasError('请选择素材文件')
        folder_id = request.form.get('folder_id') or None
        with store.write_transaction():
            store.get_project(project_id)
            folders.validate_parent(project_id, folder_id)
            asset = store.save_asset(project_id, upload.stream, upload.filename, library=True)
            from canvas_catalog import record_origin
            record_origin('library', asset['id'], 'uploaded')
            if 'folder_id' in request.form:
                folders.edit_asset(project_id, asset['id'], {'folder_id': folder_id})
        return jsonify(success=True, asset=asset, folder_id=folders.placements(project_id).get(asset['id'])), 201

    @blueprint.route('/api/canvas/projects/<project_id>/assets/<asset_id>', methods=['GET', 'PATCH'])
    def library_asset(project_id, asset_id):
        if request.method == 'PATCH':
            asset = folders.edit_asset(project_id, asset_id, read_body())
            return jsonify(success=True, asset=asset, folder_id=folders.placements(project_id).get(asset_id))
        asset = store.get_asset(project_id, asset_id, library=True, allow_archived=True)
        response = send_file(store.asset_path(asset), mimetype=asset['mime_type'], download_name=asset['name'], conditional=True)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'private, no-cache'
        return response

    @blueprint.route('/api/canvas/projects/<project_id>/asset-groups', methods=['GET', 'POST'])
    def library_groups(project_id):
        store.get_project(project_id)
        if request.method == 'GET':
            rows = task_db.get_db().execute('SELECT * FROM canvas_asset_groups WHERE project_id=? ORDER BY updated_at DESC,id', (project_id,))
            return jsonify(success=True, groups=[group_result(row) for row in rows])
        data = read_body()
        return jsonify(success=True, group=save_group(project_id, data.get('title'), data.get('asset_ids'))), 201

    @blueprint.route('/api/canvas/projects/<project_id>/asset-groups/<group_id>', methods=['PATCH'])
    def update_library_group(project_id, group_id):
        existing, data = get_group(project_id, group_id), read_body()
        return jsonify(success=True, group=save_group(project_id, data.get('title', existing['title']), data.get('asset_ids', existing['asset_ids']), group_id))

    @blueprint.route('/api/canvas/workflows/<workflow_id>/reference-assets', methods=['POST'])
    def reference_assets(workflow_id):
        workflow = store.workflow(workflow_id)
        data = read_body()
        asset_ids, group_ids = _ids(data.get('asset_ids', [])), _ids(data.get('group_ids', []), 30)
        groups = [get_group(workflow['project_id'], group_id) for group_id in group_ids]
        for group in groups:
            asset_ids.extend(group['asset_ids'])
        asset_ids = list(dict.fromkeys(asset_ids))
        if len(asset_ids) > 100:
            raise store.CanvasError('单次引用最多100个素材')
        sources = [store.get_asset(workflow['project_id'], asset_id, library=True) for asset_id in asset_ids]
        # Copy provenance (library:<id>) is recorded by save_asset; see local_delete.
        copied = {source['id']: copy_asset(source, workflow_id, copy_source='library:' + source['id']) for source in sources}
        snapshots = [{'id': group['id'], 'title': group['title'],
                      'asset_ids': [copied[asset_id]['id'] for asset_id in group['asset_ids']]} for group in groups]
        return jsonify(success=True, assets=list(copied.values()), groups=snapshots)

    @blueprint.route('/api/canvas/projects/<project_id>/assets/from-workflow', methods=['POST'])
    def library_from_workflow(project_id):
        store.get_project(project_id)
        data = read_body()
        workflow_id, asset_id = data.get('workflow_id'), data.get('asset_id')
        if not isinstance(workflow_id, str) or not isinstance(asset_id, str):
            raise store.CanvasError('workflow_id 和 asset_id 必须为字符串')
        workflow = store.workflow(workflow_id)
        if workflow['project_id'] != project_id:
            raise store.CanvasError('不能引用其他项目的画布', 404)
        source = store.get_asset(workflow_id, asset_id)
        from canvas_catalog import record_origin
        with store.write_transaction():
            asset = copy_asset(source, project_id, library=True)
            record_origin('library', asset['id'], 'saved')
        return jsonify(success=True, asset=asset), 201
