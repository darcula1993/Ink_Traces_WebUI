"""Project library folders; placement metadata never enters workflow asset snapshots."""
import uuid

import canvas_store as store
import tasks

ICONS = {'folder', 'music', 'character', 'scene', 'prop', 'style'}
DEFAULT_FOLDERS = (('音效', 'music'), ('角色', 'character'), ('场景', 'scene'), ('物品', 'prop'), ('风格', 'style'))


def init_folder_db():
    db = tasks.get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS canvas_library_folder_defaults (
            project_id TEXT PRIMARY KEY, initialized_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES canvas_projects(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS canvas_library_folders (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
            parent_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES canvas_projects(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS canvas_library_folder_icons (
            folder_id TEXT PRIMARY KEY, icon TEXT NOT NULL,
            FOREIGN KEY(folder_id) REFERENCES canvas_library_folders(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_canvas_library_folders_parent ON canvas_library_folders(project_id,parent_id);
        CREATE TABLE IF NOT EXISTS canvas_library_asset_locations (
            asset_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, folder_id TEXT,
            FOREIGN KEY(asset_id) REFERENCES canvas_library_assets(id) ON DELETE RESTRICT,
            FOREIGN KEY(project_id) REFERENCES canvas_projects(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_canvas_library_asset_locations_folder ON canvas_library_asset_locations(project_id,folder_id);
    ''')
    db.commit()


def ensure_default_folders(project_id):
    """Seed once per project; user renames/deletes/moves never recreate defaults."""
    from canvas_cleanup import is_deleted
    with store.write_transaction() as db:
        if is_deleted('project', project_id):
            return
        store.get_project(project_id)
        if db.execute('SELECT 1 FROM canvas_library_folder_defaults WHERE project_id=?', (project_id,)).fetchone():
            return
        for title, icon in DEFAULT_FOLDERS:
            existing = db.execute('SELECT 1 FROM canvas_library_folders WHERE project_id=? AND parent_id IS NULL AND title=? LIMIT 1', (project_id, title)).fetchone()
            if not existing:
                save_folder(project_id, {'title': title, 'icon': icon})
        db.execute('INSERT INTO canvas_library_folder_defaults VALUES (?,?)', (project_id, tasks.utcnow()))


def initialize_existing_defaults():
    # Materialize IDs before independent transactions, so no cursor pins a snapshot.
    ids = [r['id'] for r in tasks.get_db().execute('SELECT id FROM canvas_projects WHERE id NOT IN (SELECT project_id FROM canvas_library_folder_defaults)')]
    for project_id in ids:
        ensure_default_folders(project_id)


def folder(project_id, folder_id):
    store.get_project(project_id)
    if not isinstance(folder_id, str):
        raise store.CanvasError('文件夹编号无效')
    row = tasks.get_db().execute('SELECT * FROM canvas_library_folders WHERE project_id=? AND id=?', (project_id, folder_id)).fetchone()
    if row is None:
        raise store.CanvasError('文件夹不存在', 404)
    return folder_public(row)


def folder_public(row):
    result = dict(row)
    icon = tasks.get_db().execute('SELECT icon FROM canvas_library_folder_icons WHERE folder_id=?', (row['id'],)).fetchone()
    result['icon'] = icon['icon'] if icon else 'folder'
    return result


def validate_parent(project_id, parent_id):
    if parent_id is not None:
        folder(project_id, parent_id)
    return parent_id


def list_folders(project_id):
    store.get_project(project_id)
    return [folder_public(row) for row in tasks.get_db().execute('SELECT * FROM canvas_library_folders WHERE project_id=? ORDER BY created_at,id', (project_id,))]


def save_folder(project_id, data, folder_id=None):
    store.get_project(project_id)
    if not data or set(data) - {'title', 'parent_id', 'icon'}:
        raise store.CanvasError('文件夹字段无效')
    db = tasks.get_db()
    # All moves serialize before checking ancestry, including competing opposite moves.
    with store.write_transaction():
        store.get_project(project_id)
        old = folder(project_id, folder_id) if folder_id else None
        icon = data.get('icon', old['icon'] if old else 'folder')
        if not isinstance(icon, str) or icon not in ICONS:
            raise store.CanvasError('文件夹图标无效')
        title = store.title_value(data.get('title', old['title'] if old else None))
        parent_id = validate_parent(project_id, data.get('parent_id', old['parent_id'] if old else None))
        ancestor, seen = parent_id, set()
        while ancestor is not None:
            if ancestor == folder_id or ancestor in seen:
                raise store.CanvasError('文件夹不能移动到自身或子文件夹中', 409)
            seen.add(ancestor)
            ancestor = folder(project_id, ancestor)['parent_id']
        now = tasks.utcnow()
        if old:
            db.execute('UPDATE canvas_library_folders SET title=?,parent_id=?,updated_at=? WHERE id=? AND project_id=?', (title, parent_id, now, folder_id, project_id))
        else:
            folder_id = uuid.uuid4().hex
            db.execute('INSERT INTO canvas_library_folders VALUES (?,?,?,?,?,?)', (folder_id, project_id, title, parent_id, now, now))
        db.execute('INSERT INTO canvas_library_folder_icons VALUES (?,?) ON CONFLICT(folder_id) DO UPDATE SET icon=excluded.icon', (folder_id, icon))
    return folder(project_id, folder_id)


def delete_folder(project_id, folder_id):
    db = tasks.get_db()
    with store.write_transaction():
        store.get_project(project_id)
        folder(project_id, folder_id)
        children = db.execute('SELECT 1 FROM canvas_library_folders WHERE project_id=? AND parent_id=? LIMIT 1', (project_id, folder_id)).fetchone()
        assets = any(value == folder_id for value in placements(project_id).values())
        if children or assets:
            raise store.CanvasError('文件夹非空，请先移出素材和子文件夹', 409)
        db.execute('DELETE FROM canvas_library_folders WHERE project_id=? AND id=?', (project_id, folder_id))


def placements(project_id):
    store.get_project(project_id)
    from canvas_cleanup import is_library_asset_deleted
    return {row['asset_id']: row['folder_id'] for row in tasks.get_db().execute('SELECT asset_id,folder_id FROM canvas_library_asset_locations WHERE project_id=?', (project_id,)) if not is_library_asset_deleted(row['asset_id'])}


def edit_asset(project_id, asset_id, data):
    if not data or set(data) - {'name', 'folder_id'}:
        raise store.CanvasError('素材管理字段无效')
    db = tasks.get_db()
    with store.write_transaction():
        store.get_project(project_id)
        store.get_asset(project_id, asset_id, library=True)
        if 'name' in data:
            name = data['name']
            if not isinstance(name, str) or not name.strip() or len(name) > 240 or any(c in name for c in ('/', '\\')) or any(ord(c) < 32 for c in name):
                raise store.CanvasError('素材名称须为1至240个字符，且不能包含路径分隔符或控制字符')
            name = name.strip()
            db.execute('UPDATE canvas_library_assets SET name=? WHERE id=? AND project_id=?', (name, asset_id, project_id))
        if 'folder_id' in data:
            parent = validate_parent(project_id, data['folder_id'])
            db.execute('INSERT INTO canvas_library_asset_locations VALUES (?,?,?) ON CONFLICT(asset_id) DO UPDATE SET folder_id=excluded.folder_id', (asset_id, project_id, parent))
    return store.asset_public(store.get_asset(project_id, asset_id, library=True))


def register_folder_routes(blueprint, read_body):
    from flask import jsonify, request

    @blueprint.route('/api/canvas/projects/<project_id>/folders', methods=['GET', 'POST'])
    def folders(project_id):
        if request.method == 'GET':
            return jsonify(success=True, folders=list_folders(project_id))
        return jsonify(success=True, folder=save_folder(project_id, read_body())), 201

    @blueprint.route('/api/canvas/projects/<project_id>/folders/<folder_id>', methods=['PATCH', 'DELETE'])
    def folder_detail(project_id, folder_id):
        if request.method == 'PATCH':
            return jsonify(success=True, folder=save_folder(project_id, read_body(), folder_id))
        delete_folder(project_id, folder_id)
        return jsonify(success=True)

    @blueprint.get('/api/canvas/projects/<project_id>/folders/<folder_id>/download')
    def download_folder(project_id, folder_id):
        from canvas_library_download import folder_archive
        return folder_archive(project_id, folder_id)
