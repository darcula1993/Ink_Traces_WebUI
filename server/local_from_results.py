"""Add generated results to 本地素材 (LOCAL-FROM-RESULT-20261116).

User decisions 2026-11-16: a generated result (generation history, canvas node
result/version, task card/detail) can be explicitly added to 本地素材 as an
independent durable copy without project ownership. Task outputs and canvas copies
stay where they are; the local copy lives in canvas_assets/local_uploads/ as a hard
link when possible (same filesystem) or a plain copy. Every removal path in this code
base unlinks by path (task cleanup, project cleanup, local delete), so deleting one
link never removes the other.

Duplicate adds resolve by source: ``canvas_local_sources`` maps a source key
(``task:<task_assets.id>``; for canvas assets ``workflow:<id>`` and the root of its
copy chain) to the local item. The pre-existing content uniqueness of
``canvas_local_uploads.sha256`` still applies. Folders belong to projects only, so a
local item has none (``folder_id`` must be absent or null).
"""
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path

import canvas_store as store
import storage
import tasks

MAX_ITEMS = 100
HEX = re.compile(r'[0-9a-f]{32}')
INT = re.compile(r'[1-9][0-9]{0,18}')


def init_db():
    db = tasks.get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS canvas_local_sources (
        source_key TEXT PRIMARY KEY, local_id TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_canvas_local_sources_local ON canvas_local_sources(local_id);
    ''')
    db.commit()


class Skip(Exception):
    pass


def _int(value):
    text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    if not isinstance(text, str) or not INT.fullmatch(text) or int(text) > 9223372036854775807:
        raise store.CanvasError('生成结果编号无效')
    return int(text)


def parse_items(value):
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise store.CanvasError(f'请选择1至{MAX_ITEMS}个生成结果')
    items = []
    for item in value:
        if not isinstance(item, dict):
            raise store.CanvasError('生成结果格式无效')
        source = item.get('source')
        if source == 'task' and set(item) <= {'source', 'task_id', 'output'} and 'task_id' in item:
            ref = {'source': 'task', 'task_id': _int(item['task_id'])}
            if item.get('output') is not None:
                ref['output'] = str(_int(item['output']))
        elif source == 'canvas_asset' and set(item) == {'source', 'workflow_id', 'asset_id'}:
            if not all(isinstance(item[k], str) and HEX.fullmatch(item[k]) for k in ('workflow_id', 'asset_id')):
                raise store.CanvasError('画布素材编号无效')
            ref = dict(item)
        else:
            raise store.CanvasError('生成结果格式无效')
        items.append(ref)
    return items


def parse_tags(db, value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(i, str) for i in value):
        raise store.CanvasError('标签编号须为最多100项的数组')
    ids = list(dict.fromkeys(value))
    for ident in ids:
        if not db.execute('SELECT 1 FROM canvas_catalog_tags WHERE id=?', (ident,)).fetchone():
            raise store.CanvasError('标签不存在', 404)
    return ids


def _task_sources(ref):
    """One entry per local output of a task: (ref, path, name, source keys)."""
    from canvas_catalog import task_projects
    from canvas_cleanup import task_restore_blocked
    from result_names import result_display_name, task_result_name
    task = tasks.get_task(ref['task_id'])
    if not task:
        raise Skip('任务不存在')
    if task.get('deleted_at'):
        raise Skip('任务已删除或在回收站')
    if task['status'] != 'succeeded':
        raise Skip('任务未成功，没有可加入的结果')
    if task_restore_blocked(task['id']):
        raise Skip('任务所属项目正在清理')
    projects, was_owned = task_projects(task)
    if was_owned and not projects:
        raise Skip('任务所属画布已删除')
    outputs = [a for a in tasks.list_assets(task['id']) if a['kind'] in ('output_image', 'output_video', 'output_audio')]
    if 'output' in ref:
        outputs = [a for a in outputs if str(a['id']) == ref['output']]
        if not outputs:
            raise Skip('结果不存在')
    if not outputs:
        raise Skip('生成结果尚未下载到本地，暂不能加入')
    root = Path(storage.OUTPUT_DIR).absolute()
    entries = []
    for asset in sorted(outputs, key=lambda a: a['id']):
        item_ref = {**ref, 'output': str(asset['id'])}
        path = Path(asset['path']).absolute()
        if root.resolve() != root or path.resolve() != path or not path.is_relative_to(root) or not path.is_file():
            entries.append((item_ref, Skip('结果文件不存在或已清理')))
            continue
        name = result_display_name(task_result_name(task.get('params')), task['id'], path.name) or path.name
        key = 'task:' + str(asset['id'])
        entries.append((item_ref, (path, name, [key], [key])))
    return entries


def _copy_root(db, asset_id):
    """Follow canvas copy provenance to its origin key (task:, local:, library: or workflow:)."""
    key, seen = 'workflow:' + asset_id, set()
    while key.startswith('workflow:') and key not in seen:
        seen.add(key)
        sources = sorted(r[0] for r in db.execute(
            "SELECT source_key FROM canvas_asset_copies WHERE asset_id=? AND source_key NOT LIKE 'character:%'", (key.split(':', 1)[1],)))
        if not sources:
            break
        # Prefer a generated origin, then a local item, for deduplication.
        key = next((s for s in sources if s.startswith('task:')), None) or next((s for s in sources if s.startswith('local:')), None) or sources[0]
    return key


def _canvas_source(ref):
    db = tasks.get_db()
    try:
        store.workflow(ref['workflow_id'])
    except store.CanvasError:
        raise Skip('画布不存在或已删除')
    from local_delete import _active_workflows
    if ref['workflow_id'] not in _active_workflows(db):
        raise Skip('画布不存在或已删除')
    row = db.execute('SELECT * FROM canvas_assets WHERE id=? AND workflow_id=?', (ref['asset_id'], ref['workflow_id'])).fetchone()
    if row is None:
        raise Skip('画布素材不存在')
    try:
        path = store.asset_path(dict(row))
    except store.CanvasError:
        raise Skip('结果文件不存在或已清理')
    if not path.is_file():
        raise Skip('结果文件不存在或已清理')
    own = 'workflow:' + row['id']
    origin = _copy_root(db, row['id'])
    keys = list(dict.fromkeys([own, origin]))
    return [(ref, (path, row['name'], keys, keys))]


def _mapped_local(db, keys):
    """Live local item already registered for any of these source keys."""
    for key in keys:
        if key.startswith('local:'):
            row = db.execute('SELECT * FROM canvas_local_uploads WHERE id=?', (key[6:],)).fetchone()
            if row:
                return dict(row)
        mapped = db.execute('SELECT local_id FROM canvas_local_sources WHERE source_key=?', (key,)).fetchone()
        if mapped:
            row = db.execute('SELECT * FROM canvas_local_uploads WHERE id=?', (mapped[0],)).fetchone()
            if row:
                return dict(row)
    return None


def _stage(path, name):
    """Hard link (or copy) the source into the local directory; never moves the source."""
    from local_uploads import root
    ident = uuid.uuid4().hex
    staging = root() / (ident + '.tmp')
    try:
        try:
            os.link(path, staging)
        except OSError:
            staging.unlink(missing_ok=True)
            with path.open('rb') as source, staging.open('xb') as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
        digest, size = hashlib.sha256(), 0
        with staging.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
                size += len(chunk)
        if not size:
            raise Skip('结果文件不存在或已清理')
        try:
            mime, extension = store._detect_media(staging)
        except store.CanvasError:
            raise Skip('媒体类型无法识别')
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return {'id': ident, 'path': staging, 'name': name, 'mime_type': mime, 'extension': extension,
            'sha256': digest.hexdigest(), 'size_bytes': size}


def _attach(db, local_id, keys, tag_keys, tag_ids):
    now = tasks.utcnow()
    for key in keys:
        if key.startswith('local:'):
            continue
        db.execute('INSERT INTO canvas_local_sources VALUES (?,?,?) ON CONFLICT(source_key) DO UPDATE SET local_id=excluded.local_id,created_at=excluded.created_at',
                   (key, local_id, now))
    carried = [r[0] for key in tag_keys for r in db.execute('SELECT tag_id FROM canvas_catalog_item_tags WHERE item_key=?', (key,))]
    for tag in dict.fromkeys(tag_ids + carried):
        if db.execute('SELECT 1 FROM canvas_catalog_tags WHERE id=?', (tag,)).fetchone():
            db.execute('INSERT OR IGNORE INTO canvas_catalog_item_tags VALUES (?,?)', ('local:' + local_id, tag))


def _result(ref, row, status):
    return {'ref': ref, 'local_id': row['id'], 'key': 'local:' + row['id'], 'status': status, 'name': row['name'], 'kind': row['kind']}


def add_results(data):
    if not isinstance(data, dict) or set(data) - {'items', 'tag_ids', 'folder_id'}:
        raise store.CanvasError('请求字段无效')
    if data.get('folder_id') is not None:
        raise store.CanvasError('本地素材没有文件夹（文件夹只属于项目）')
    refs = parse_items(data.get('items'))
    tag_ids = parse_tags(tasks.get_db(), data.get('tag_ids'))
    from local_uploads import publish_staged
    results, skipped, done = [], [], {}
    for ref in refs:
        try:
            entries = _task_sources(ref) if ref['source'] == 'task' else _canvas_source(ref)
        except Skip as reason:
            skipped.append({'ref': ref, 'reason': str(reason)})
            continue
        for item_ref, entry in entries:
            if isinstance(entry, Skip):
                skipped.append({'ref': item_ref, 'reason': str(entry)})
                continue
            path, name, keys, tag_keys = entry
            if keys[0] in done:  # same output listed twice in one request
                results.append({**done[keys[0]], 'ref': item_ref, 'status': 'existing'})
                continue
            db = tasks.get_db()
            existing = _mapped_local(db, keys)
            staged = None
            if existing is None:
                try:
                    staged = _stage(path, name)
                except Skip as reason:
                    skipped.append({'ref': item_ref, 'reason': str(reason)})
                    continue
                except OSError:
                    skipped.append({'ref': item_ref, 'reason': '结果文件不存在或已清理'})
                    continue
            try:
                with store.write_transaction() as db:
                    row = _mapped_local(db, keys)  # re-check under the write lock
                    if row is None:
                        row = publish_staged(db, staged)
                        status = 'created' if row['id'] == staged['id'] else 'existing'
                    else:
                        status = 'existing'
                        db.execute('DELETE FROM canvas_catalog_hidden WHERE item_key=?', ('local:' + row['id'],))
                    _attach(db, row['id'], keys, tag_keys, tag_ids)
            finally:
                if staged is not None:
                    staged['path'].unlink(missing_ok=True)
            done[keys[0]] = _result(item_ref, row, status)
            results.append(done[keys[0]])
    return {'success': True, 'items': results, 'skipped': skipped}


def register_routes(bp, body):
    from flask import jsonify

    @bp.post('/api/canvas/library/local/from-results')
    def local_from_results():
        return jsonify(add_results(body()))
