"""Global local media library (LIBRARY-GLOBAL-20261116 S1a): one library for all projects.

Every item is a ``media`` row whose file lives under ``<asset_root>/media``; folders are
global (``media_folders``), with fixed system folders 生成历史/图片|视频|音频. Old library
tables and APIs are untouched in this stage; ``media_aliases`` maps old identities.
No Flask imports:
the Worker (S2) calls ``register_generated`` directly.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import canvas_store as store
import media_schema
import tasks

LOG = logging.getLogger(__name__)
MEDIA_ID = re.compile(r'^[0-9a-f]{32}$')
STAGED_DELETE = re.compile(
    r'(?P<filename>[0-9a-f]{32}\.[a-z0-9]+)\.deleting-[0-9a-f]{32}'
)
KINDS = ('image', 'video', 'audio')
ORIGINS = {'upload', 'canvas_upload', 'paste', 'frame', 'save_as', 'generated',
           'legacy_local', 'legacy_library', 'legacy_workflow'}
UPLOAD_ORIGINS = ('upload', 'canvas_upload', 'paste', 'frame', 'save_as')
ALIAS_SCOPES = ('local', 'library', 'workflow', 'task')
ICONS = {'folder', 'music', 'character', 'scene', 'prop', 'style'}
MAX_IDS = 500
MAX_SELECT = 5000
GENERATION = ('image', 'video', 'audio')


class MediaError(store.CanvasError):
    def __init__(self, message, status=400, code='invalid_request'):
        super().__init__(message, status)
        self.code = code


def _ids(value, field='ids'):
    if not isinstance(value, list) or not value or len(value) > MAX_IDS or any(not isinstance(i, str) or not MEDIA_ID.fullmatch(i) for i in value):
        raise MediaError(f'{field} 须为1至{MAX_IDS}个素材编号', 400, 'invalid_id')
    return list(dict.fromkeys(value))


def _check_id(media_id):
    if not isinstance(media_id, str) or not MEDIA_ID.fullmatch(media_id):
        raise MediaError('素材编号无效', 400, 'invalid_id')
    return media_id


def _name(name):
    if not isinstance(name, str) or not name.strip() or len(name) > 240 or any(c in name for c in '/\\') or any(ord(c) < 32 for c in name):
        raise MediaError('无效素材文件名', 400, 'invalid_name')
    return name.strip()


def root():
    path = store.asset_root() / 'media'
    if path.resolve() != path:
        raise MediaError('素材库目录不安全', 409, 'file_missing')
    path.mkdir(parents=True, exist_ok=True)
    return path


def system_folder_id(key):
    if key not in {k for k, _, _ in media_schema.SYSTEM_FOLDERS}:
        raise ValueError(key)
    return media_schema.stable_id('system', key)


def public(row):
    row = dict(row)
    url = f"/api/canvas/media/{row['id']}"
    return {**{k: row[k] for k in ('id', 'name', 'kind', 'mime_type', 'size_bytes', 'folder_id', 'origin', 'source_task_id', 'created_at')},
            'url': url, 'thumbnail_url': url + '/thumbnail' if row['kind'] == 'image' else None}


# GEN-RESULT-LIFECYCLE-20261119: an item of 生成历史 shares its task's life cycle. Its linked
# tasks are ``source_task_id`` plus every ``task_assets`` row pointing at it; while all of them
# are in the trash the item is hidden (a query filter: rows and files are untouched) and
# comes back when a task is restored. Items outside 生成历史 (copies, uploads, results moved
# out before 2026-11-19) are independent of tasks.
GENERATED_FOLDERS = tuple(media_schema.stable_id('system', key) for key in ('generated_image', 'generated_video', 'generated_audio'))
_GEN_IN = '(' + ','.join(f"'{i}'" for i in GENERATED_FOLDERS) + ')'
_LINKED = ('SELECT 1 FROM tasks t WHERE t.id IN (SELECT {m}.source_task_id UNION '
           'SELECT a.task_id FROM task_assets a WHERE a.media_id={m}.id) AND t.deleted_at IS {state}')


def trashed_sql(alias='media'):
    """SQL predicate: the row is a 生成历史 item whose linked tasks are all in the trash."""
    return (f'(COALESCE({alias}.folder_id, \'\') IN {_GEN_IN} AND EXISTS ({_LINKED.format(m=alias, state="NOT NULL")}) '
            f'AND NOT EXISTS ({_LINKED.format(m=alias, state="NULL")}))')


def is_trashed(db, row):
    if row['folder_id'] not in GENERATED_FOLDERS:
        return False
    return db.execute(f'SELECT {trashed_sql("m")} FROM media m WHERE m.id=?', (row['id'],)).fetchone()[0] == 1


def status(media_id, reveal_trashed=False):
    """('ok', row) | ('trashed', row) | ('deleted', tombstone) | ('missing', None).

    ``trashed``: a 生成历史 item whose tasks are all in the trash (hidden until restored);
    ``reveal_trashed`` reports it as ``ok`` (the task center shows its own trashed results).
    """
    db = tasks.get_db()
    if reveal_trashed:
        row = db.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()
        if row is not None:
            return 'ok', dict(row)
    else:
        # Resolve the row and its trash state in one SQLite snapshot.
        row = db.execute(f'SELECT m.*, {trashed_sql("m")} AS trashed FROM media m WHERE m.id=?',
                         (media_id,)).fetchone()
        if row is not None:
            item = dict(row)
            return ('trashed' if item.pop('trashed') else 'ok'), item
    row = db.execute('SELECT * FROM media_tombstones WHERE id=?', (media_id,)).fetchone()
    return ('deleted', dict(row)) if row is not None else ('missing', None)


def deleted_public(row):
    return {'id': row['id'], 'name': row['name'], 'kind': row['kind'], 'deleted': True, 'deleted_at': row['deleted_at']}


def trashed_public(row):
    return {'id': row['id'], 'name': row['name'], 'kind': row['kind'], 'trashed': True, 'source_task_id': row['source_task_id']}


def trashed_error(row):
    error = MediaError('该生成结果所在的任务在回收站，恢复任务后可用', 409, 'media_trashed')
    error.media = trashed_public(row)
    return error


def deleted_error(row):
    error = MediaError('素材已删除', 410, 'media_deleted')
    error.media = deleted_public(row)
    return error


def get_media(media_id):
    state, row = status(_check_id(media_id))
    if state == 'deleted':
        raise deleted_error(row)
    if state == 'missing':
        raise MediaError('素材不存在', 404, 'media_not_found')
    if state == 'trashed':
        raise trashed_error(row)
    return row


def media_path(row):
    directory = root()
    path = directory / row['relpath']
    if path.resolve() != path or not path.is_relative_to(directory) or not path.is_file():
        # Deletion may have committed after the caller read the media row.
        state, current = status(row['id'], reveal_trashed=True)
        if state == 'deleted':
            raise deleted_error(current)
        raise MediaError('素材文件不可读取', 409, 'file_missing')
    return path


def task_media(task_asset_id):
    """For the task center (S3): ('none', None) when not in the library (fall back to output)."""
    row = tasks.get_db().execute('SELECT media_id FROM task_assets WHERE id=?', (task_asset_id,)).fetchone()
    if row is None or not row['media_id']:
        return 'none', None
    state, media = status(row['media_id'], reveal_trashed=True)
    return ('none', None) if state == 'missing' else (state, media)


# ---------------------------------------------------------------- folders

def _folder(db, folder_id):
    if not isinstance(folder_id, str) or not MEDIA_ID.fullmatch(folder_id):
        raise MediaError('文件夹编号无效', 400, 'invalid_id')
    row = db.execute('SELECT * FROM media_folders WHERE id=?', (folder_id,)).fetchone()
    if row is None:
        raise MediaError('文件夹不存在', 404, 'folder_not_found')
    return dict(row)


def _placement(db, folder_id, kind=None, origin=None, move=False):
    """Target folder for items: root, a user folder, or the system subfolder of the same kind.

    生成历史 and its type subfolders only take generation results (origin generated, user
    decision 2026-11-17). ``move`` (GEN-RESULT-LIFECYCLE-20261119): nothing is moved into
    生成历史 any more; it only receives new results (a copy moved back would share its
    task's life cycle again).
    """
    if folder_id is None:
        return None
    folder = _folder(db, folder_id)
    if folder['system_key']:
        if move:
            raise MediaError('生成历史只接收新生成的结果，不能移入或复制进来', 409, 'folder_generated_only')
        if origin != 'generated':
            raise MediaError('生成历史只接收生成结果，上传素材不能移入', 409, 'folder_generated_only')
        if kind is None or folder['system_key'] != 'generated_' + kind:
            raise MediaError('生成历史下的图片/视频/音频只接收对应类型的生成结果', 409, 'folder_target_invalid')
    return folder_id


def folder_public(db, row):
    count = db.execute(f'SELECT COUNT(*) FROM media WHERE folder_id=? AND NOT {trashed_sql()}', (row['id'],)).fetchone()[0]
    return {**{k: row[k] for k in ('id', 'title', 'parent_id', 'system_key', 'icon', 'created_at', 'updated_at')}, 'media_count': count}


def list_folders():
    db = tasks.get_db()
    rows = db.execute('SELECT * FROM media_folders ORDER BY system_key IS NULL, created_at, id').fetchall()
    # Seeded folders share one timestamp: keep their declared order (S9 O1), others by time then id.
    rows.sort(key=lambda r: (r['system_key'] is None, r['created_at'], _SEED_ORDER.get(r['id'], len(_SEED_ORDER)), r['id']))
    return [folder_public(db, r) for r in rows]


_SEED_ORDER = {media_schema.stable_id('system', key): index for index, (key, _, _) in enumerate(media_schema.SYSTEM_FOLDERS)}
_SEED_ORDER.update({media_schema.stable_id('default', title): len(_SEED_ORDER) + index
                    for index, (title, _) in enumerate(media_schema.DEFAULT_FOLDERS)})


def _save_folder(data, folder_id=None):
    if not isinstance(data, dict) or not data or set(data) - {'title', 'parent_id', 'icon'}:
        raise MediaError('文件夹字段无效')
    with store.write_transaction() as db:
        old = _folder(db, folder_id) if folder_id else None
        if old and old['system_key']:
            raise MediaError('系统文件夹不能修改', 409, 'folder_system')
        icon = data.get('icon', old['icon'] if old else 'folder')
        if icon not in ICONS:
            raise MediaError('文件夹图标无效')
        title = data.get('title', old['title'] if old else None)
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise MediaError('文件夹名称须为1至120个字符', 400, 'invalid_name')
        title = title.strip()
        renamed = old is None or title != old['title']
        # User decision 2026-11-17 (E3): only new names are checked; existing folders keep theirs.
        if renamed and '/' in title:
            raise MediaError('文件夹名称不能包含“/”', 400, 'invalid_name')
        parent_id = data.get('parent_id', old['parent_id'] if old else None)
        if parent_id is not None:
            if _folder(db, parent_id)['system_key']:
                raise MediaError('系统文件夹下不能新建或移入文件夹', 409, 'folder_target_invalid')
            ancestor, seen = parent_id, set()
            while ancestor is not None:
                if ancestor == folder_id or ancestor in seen:
                    raise MediaError('文件夹不能移动到自身或子文件夹中', 409, 'folder_cycle')
                seen.add(ancestor)
                ancestor = _folder(db, ancestor)['parent_id']
        if renamed or parent_id != old['parent_id']:
            # Same level = same parent (root included); names compare trimmed and case-insensitive.
            siblings = db.execute('SELECT id, title FROM media_folders WHERE parent_id IS ? AND id IS NOT ?', (parent_id, folder_id))
            if any(r['title'].strip().casefold() == title.casefold() for r in siblings):
                raise MediaError(f'同一位置已有名为“{title}”的文件夹', 409, 'folder_name_conflict')
        now = tasks.utcnow()
        if old:
            db.execute('UPDATE media_folders SET title=?,parent_id=?,icon=?,updated_at=? WHERE id=?', (title, parent_id, icon, now, folder_id))
        else:
            folder_id = uuid.uuid4().hex
            db.execute('INSERT INTO media_folders VALUES (?,?,?,?,?,?,?)', (folder_id, title, parent_id, None, icon, now, now))
        return folder_public(db, _folder(db, folder_id))


def create_folder(data):
    return _save_folder(data)


def update_folder(folder_id, data):
    return _save_folder(data, folder_id)


def delete_folder(folder_id):
    """Never deletes media: a non-empty folder is refused."""
    with store.write_transaction() as db:
        if _folder(db, folder_id)['system_key']:
            raise MediaError('系统文件夹不能删除', 409, 'folder_system')
        if db.execute('SELECT 1 FROM media_folders WHERE parent_id=? LIMIT 1', (folder_id,)).fetchone() or \
                db.execute('SELECT 1 FROM media WHERE folder_id=? LIMIT 1', (folder_id,)).fetchone():
            raise MediaError('文件夹非空，请先移出素材和子文件夹', 409, 'folder_not_empty')
        db.execute('DELETE FROM media_folders WHERE id=?', (folder_id,))


# ---------------------------------------------------------------- ingest

def _digest(path):
    digest, size = hashlib.sha256(), 0
    with open(path, 'rb') as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _detect(path):
    try:
        return store._detect_media(Path(path))
    except MediaError:
        raise
    except store.CanvasError as error:
        status_code = error.status if error.status >= 500 else 400
        raise MediaError(str(error), status_code, 'unsupported_media') from error


def _existing(db, checksum, origin):
    """Dedup target: the oldest item with this content (the original, not a copy).

    A hidden 生成历史 item (its task is in the trash) is not reused for non-generated
    content: emptying the trash would delete the user's upload with it.
    """
    for row in db.execute('SELECT * FROM media WHERE sha256=? ORDER BY created_at, id', (checksum,)).fetchall():
        if origin == 'generated' or not is_trashed(db, row):
            return row
    return None


def _journal(db, media_id, target):
    journal = store._transaction_files.get()
    if journal is not None and journal[0] is db:
        journal[1].append(('media', media_id, target))


def _insert(db, media_id, checksum, target, name, mime, size, origin, folder_id, source_task_id, created_at):
    db.execute('INSERT INTO media VALUES (?,?,?,?,?,?,?,?,?,?,?)',
               (media_id, checksum, target.name, folder_id, name, mime, mime.split('/')[0], size, origin,
                source_task_id, created_at or tasks.utcnow()))


def import_file(path, *, name, origin, folder_id=None, source_task_id=None, link=True, created_at=None):
    """Register an existing file (hard link, or copy across file systems / when link=False).

    Dedup by sha256: an existing item is returned unchanged -> (media_id, False).
    """
    if origin not in ORIGINS:
        raise ValueError(origin)
    source = Path(path).absolute()
    if not source.is_file():
        raise MediaError('素材文件不可读取', 409, 'file_missing')
    name = _name(name)
    mime, extension = _detect(source)
    checksum, size = _digest(source)
    if not size:
        raise MediaError('素材不能为空', 400, 'empty_file')
    with store.write_transaction() as db:
        existing = _existing(db, checksum, origin)
        if existing:
            return existing['id'], False
        folder_id = _placement(db, folder_id, mime.split('/')[0], origin)
        media_id = uuid.uuid4().hex
        target = root() / (media_id + extension)
        try:
            if not link:
                raise OSError('copy requested')
            os.link(source, target)
        except OSError:
            temporary = target.with_name(target.name + '.tmp')
            try:
                shutil.copyfile(source, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        _journal(db, media_id, target)
        _insert(db, media_id, checksum, target, name, mime, size, origin, folder_id, source_task_id, created_at)
        return media_id, True


def register_generated(task_id, path, kind, *, name=None):
    """S2 Worker entry: put a succeeded task output into 生成历史/<kind> and link task_assets."""
    kind = kind[len('output_'):] if isinstance(kind, str) and kind.startswith('output_') else kind
    if kind not in KINDS or type(task_id) is not int:
        raise ValueError('kind/task_id')
    source = Path(path).absolute()
    # Probing/hashing runs outside the write lock; a retry after a failed link step is idempotent.
    media_id, created = import_file(source, name=name or source.name, origin='generated',
                                    folder_id=system_folder_id('generated_' + kind), source_task_id=task_id)
    orphan = None
    with store.write_transaction() as db:
        row = db.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()
        if row is None or row['kind'] != kind:
            raise MediaError('生成结果类型与登记不符', 400, 'unsupported_media')
        if db.execute('SELECT 1 FROM tasks WHERE id=?', (task_id,)).fetchone() is None:
            # GEN-RESULT-LIFECYCLE: the task was permanently deleted between its success and
            # this registration; undo the item created for it (never a pre-existing one).
            if created and not db.execute('SELECT 1 FROM task_assets WHERE media_id=? AND task_id IS NOT NULL', (media_id,)).fetchone():
                db.execute('DELETE FROM media WHERE id=?', (media_id,))
                orphan = root() / row['relpath']
        else:
            db.execute('UPDATE task_assets SET media_id=? WHERE task_id=? AND path IN (?,?)', (media_id, task_id, str(path), str(source)))
    if orphan is not None:
        orphan.unlink(missing_ok=True)
        raise MediaError('任务已彻底删除，结果不再入库', 404, 'media_not_found')
    return media_id


def save_upload(stream, name, *, folder_id=None, origin='upload'):
    """Upload bytes into the library -> (public media, deduplicated)."""
    if origin not in UPLOAD_ORIGINS:
        raise MediaError('素材来源无效')
    name = _name(name)
    media_id = uuid.uuid4().hex
    staging = root() / (media_id + '.upload.tmp')
    digest, size = hashlib.sha256(), 0
    target = None
    try:
        with staging.open('xb') as output:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > store.MAX_ASSET_BYTES:
                    raise MediaError('素材不得超过100MiB', 413, 'file_too_large')
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if not size:
            raise MediaError('素材不能为空', 400, 'empty_file')
        mime, extension = _detect(staging)
        checksum = digest.hexdigest()
        with store.write_transaction() as db:
            kind = mime.split('/')[0]
            folder_id = _placement(db, folder_id, kind, origin)
            existing = _existing(db, checksum, origin)
            if existing:
                # Dedup returns the existing item unchanged (folder, name, origin), also when it is a
                # generation result in 生成历史: the client offers 定位 / 移到当前文件夹 (user decision
                # 2026-11-17; the Q6 "move to the root as an upload" rule only applies to migration).
                media_path(existing)
                return public(existing), True
            target = root() / (media_id + extension)
            os.replace(staging, target)
            _journal(db, media_id, target)
            _insert(db, media_id, checksum, target, name, mime, size, origin, folder_id, None, None)
            return public(db.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()), False
    finally:
        staging.unlink(missing_ok=True)


# ---------------------------------------------------------------- listing / move

def _filters(folder_id=None, include_subfolders=False, kind=None, q=None, origin=None):
    db = tasks.get_db()
    clauses, params = [f'NOT {trashed_sql()}'], []
    if folder_id == 'root':
        clauses.append('folder_id IS NULL')
    elif folder_id is not None:
        _folder(db, folder_id)
        if include_subfolders:
            ids = [r[0] for r in db.execute('''WITH RECURSIVE tree(id) AS (SELECT ? UNION
                SELECT f.id FROM media_folders f JOIN tree t ON f.parent_id=t.id) SELECT id FROM tree''', (folder_id,))]
            clauses.append(f"folder_id IN ({','.join('?' * len(ids))})")
            params += ids
        else:
            clauses.append('folder_id=?')
            params.append(folder_id)
    if kind is not None:
        if kind not in KINDS:
            raise MediaError('素材类型无效')
        clauses.append('kind=?')
        params.append(kind)
    if origin is not None:
        if origin not in ORIGINS:
            raise MediaError('素材来源无效')
        clauses.append('origin=?')
        params.append(origin)
    if q:
        if not isinstance(q, str) or len(q) > 200:
            raise MediaError('搜索词无效')
        clauses.append("name LIKE ? ESCAPE '\\'")
        params.append('%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
    return ' WHERE ' + ' AND '.join(clauses), params


def list_media(page=1, limit=50, **filters):
    if type(page) is not int or page < 1 or type(limit) is not int or not 1 <= limit <= 200:
        raise MediaError('分页参数无效')
    where, params = _filters(**filters)
    db = tasks.get_db()
    total = db.execute('SELECT COUNT(*) FROM media' + where, params).fetchone()[0]
    rows = db.execute(f'SELECT * FROM media{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?', params + [limit, (page - 1) * limit])
    return {'items': [public(r) for r in rows], 'total': total, 'page': page, 'limit': limit}


def select_ids(**filters):
    where, params = _filters(**filters)
    ids = [r[0] for r in tasks.get_db().execute(f'SELECT id FROM media{where} ORDER BY created_at DESC, id DESC LIMIT ?', params + [MAX_SELECT + 1])]
    if len(ids) > MAX_SELECT:
        raise MediaError(f'匹配素材超过{MAX_SELECT}项，请缩小范围', 400, 'too_many')
    return {'ids': ids, 'total': len(ids)}


def move_media(ids, folder_id):
    """“移动到文件夹”, all-or-nothing -> {'media': [...], 'copied': [{source_id, id}]}.

    Uploads and other items only change ``folder_id``. An item of 生成历史 is copied instead
    (GEN-RESULT-LIFECYCLE-20261119, user decision 4): a new independent item (new id, hard
    link to the same file, same name/origin/source task) lands in the target folder and the
    original stays in 生成历史 with its task. ``media`` lists the resulting items in order.
    """
    ids = _ids(ids)
    created_files = []
    try:
        with store.write_transaction() as db:
            rows = [db.execute('SELECT * FROM media WHERE id=?', (i,)).fetchone() for i in ids]
            if any(r is None for r in rows):
                raise MediaError('素材不存在或已删除', 404, 'media_not_found')
            if any(is_trashed(db, r) for r in rows):
                raise MediaError('所选生成结果的任务在回收站，恢复任务后才能操作', 409, 'media_trashed')
            result, copied = [], []
            for row in rows:
                if row['folder_id'] == folder_id:
                    result.append(row['id'])
                    continue
                _placement(db, folder_id, row['kind'], row['origin'], move=True)
                if row['folder_id'] in GENERATED_FOLDERS:
                    new_id = _copy_item(db, row, folder_id, created_files)
                    copied.append({'source_id': row['id'], 'id': new_id})
                    result.append(new_id)
                else:
                    db.execute('UPDATE media SET folder_id=? WHERE id=?', (folder_id, row['id']))
                    result.append(row['id'])
            return {'media': [public(db.execute('SELECT * FROM media WHERE id=?', (i,)).fetchone()) for i in result],
                    'copied': copied}
    except BaseException:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise


def _copy_item(db, row, folder_id, created_files):
    """Independent library item sharing ``row``'s file (hard link; copy across file systems)."""
    source = media_path(row)
    new_id = uuid.uuid4().hex
    target = root() / (new_id + source.suffix)
    try:
        os.link(source, target)
    except OSError:
        temporary = target.with_name(target.name + '.tmp')
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    created_files.append(target)
    _insert(db, new_id, row['sha256'], target, row['name'], row['mime_type'], row['size_bytes'], row['origin'],
            folder_id, row['source_task_id'], tasks.utcnow())
    return new_id


def rename_media(media_id, name):
    """Rename one item (display/download name only; the file, id and folder are unchanged).

    Canvas documents keep their embedded name snapshot until the next save; clients read the
    current name through ``info``/``lookup``. Deleted items answer 410 media_deleted.
    """
    _check_id(media_id)
    name = _name(name)
    with store.write_transaction() as db:
        get_media(media_id)
        db.execute('UPDATE media SET name=? WHERE id=?', (name, media_id))
        return public(db.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone())


# ---------------------------------------------------------------- aliases

def add_alias(scope, old_id, media_id):
    if scope not in ALIAS_SCOPES or not isinstance(old_id, str) or not old_id:
        raise ValueError('alias')
    tasks.get_db().execute('INSERT OR IGNORE INTO media_aliases VALUES (?,?,?,?)', (scope, old_id, _check_id(media_id), tasks.utcnow()))


_URLS = (
    (re.compile(r'^/api/canvas/media/([0-9a-f]{32})(?:/.*)?$'), None),
    (re.compile(r'^/api/canvas/workflows/[A-Za-z0-9_-]{1,80}/assets/([0-9a-f]{32})$'), 'workflow'),
    (re.compile(r'^/api/canvas/projects/[A-Za-z0-9_-]{1,80}/assets/([0-9a-f]{32})$'), 'library'),
    (re.compile(r'^/api/canvas/library/items/(local|library|workflow|task):([0-9]+|[0-9a-f]{32})(?:/.*)?$'), 'key'),
)


def resolve(ref):
    """Media id for a media id, ``scope:old_id`` or an old asset URL; None if unknown."""
    if not isinstance(ref, str) or len(ref) > 600:
        return None
    db = tasks.get_db()
    scope, old = None, None
    if MEDIA_ID.fullmatch(ref):
        if status(ref)[0] != 'missing':
            return ref
        found = {r[0] for r in db.execute('SELECT media_id FROM media_aliases WHERE old_id=?', (ref,))}
        return found.pop() if len(found) == 1 else None
    if ref.startswith('/'):
        path = urlsplit(ref).path
        for pattern, kind in _URLS:
            match = pattern.fullmatch(path)
            if match:
                if kind is None:
                    return match.group(1) if status(match.group(1))[0] != 'missing' else None
                scope, old = (match.group(1), match.group(2)) if kind == 'key' else (kind, match.group(1))
                break
    else:
        scope, _, old = ref.partition(':')
    if scope not in ALIAS_SCOPES or not old:
        return None
    row = db.execute('SELECT media_id FROM media_aliases WHERE scope=? AND old_id=?', (scope, old)).fetchone()
    if row:
        return row[0]
    if scope == 'task' and old.isdigit():
        row = db.execute('SELECT media_id FROM task_assets WHERE id=?', (int(old),)).fetchone()
        return row[0] if row and row[0] else None
    return None


def legacy_media(scope, old_id):
    """S9 (QA D1): gate for the old read/reference routes.

    An old identity that entered the library (alias, or a task output linked to media) is
    served from the library: returns the media row (``ok``) or raises 410 ``media_deleted``
    when it was deleted there. None when the old item never entered the library.
    """
    if scope not in ALIAS_SCOPES or not isinstance(old_id, str) or not old_id:
        return None
    media_id = resolve(f'{scope}:{old_id}')
    if not media_id:
        return None
    state, row = status(media_id)
    if state == 'missing':
        return None
    if state == 'deleted':
        error = MediaError('素材已在素材库中删除', 410, 'media_deleted')
        error.media = deleted_public(row)
        raise error
    if state == 'trashed':
        raise trashed_error(row)
    return row


def lookup(refs):
    if not isinstance(refs, list) or not refs or len(refs) > MAX_IDS or any(not isinstance(r, str) for r in refs):
        raise MediaError(f'refs 须为1至{MAX_IDS}个素材引用', 400, 'invalid_id')
    items = []
    for ref in dict.fromkeys(refs):
        media_id = resolve(ref)
        state, row = status(media_id) if media_id else ('missing', None)
        item = {'ref': ref, 'status': state, 'media_id': media_id if state != 'missing' else None}
        if state == 'ok':
            item['media'] = public(row)
        elif state == 'deleted':
            item['media'] = deleted_public(row)
        elif state == 'trashed':
            item['media'] = trashed_public(row)
        items.append(item)
    return {'items': items}


# ---------------------------------------------------------------- global groups
# A group is an ordered set of media ids (no file copies), visible to all projects.
# Deleting a member media keeps its membership as a "已删除" placeholder, like nodes.

MAX_GROUP = 100


def _group_row(db, group_id):
    if not isinstance(group_id, str) or not MEDIA_ID.fullmatch(group_id):
        raise MediaError('素材组编号无效', 400, 'invalid_id')
    row = db.execute('SELECT * FROM media_groups WHERE id=?', (group_id,)).fetchone()
    if row is None:
        raise MediaError('素材组不存在', 404, 'group_not_found')
    return dict(row)


def _group_public(db, row):
    members = [r[0] for r in db.execute('SELECT media_id FROM media_group_members WHERE group_id=? ORDER BY position', (row['id'],))]
    live = {r[0] for r in db.execute(
        'SELECT m.id FROM media m JOIN media_group_members g ON g.media_id=m.id WHERE g.group_id=?', (row['id'],))}
    return {**{k: row[k] for k in ('id', 'title', 'created_at', 'updated_at')}, 'media_ids': members,
            'member_count': len(members), 'deleted_count': len(members) - len(live)}


def _group_title(title):
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise MediaError('素材组名称须为1至120个字符', 400, 'invalid_name')
    return title.strip()


def _members(db, value, existing=()):
    """New member ids must be live media; ids already in the group may be placeholders."""
    if not isinstance(value, list) or len(value) > MAX_GROUP or any(not isinstance(i, str) or not MEDIA_ID.fullmatch(i) for i in value):
        raise MediaError(f'media_ids 须为最多{MAX_GROUP}个素材编号', 400, 'invalid_id')
    value = list(dict.fromkeys(value))
    for media_id in value:
        if media_id not in existing and db.execute('SELECT 1 FROM media WHERE id=?', (media_id,)).fetchone() is None:
            raise MediaError('素材不存在或已删除', 404, 'media_not_found')
    return value


def _write_members(db, group_id, media_ids):
    db.execute('DELETE FROM media_group_members WHERE group_id=?', (group_id,))
    db.executemany('INSERT INTO media_group_members VALUES (?,?,?)', [(group_id, m, i) for i, m in enumerate(media_ids)])


def list_groups():
    db = tasks.get_db()
    return [_group_public(db, r) for r in db.execute('SELECT * FROM media_groups ORDER BY updated_at DESC, id').fetchall()]


def get_group(group_id):
    db = tasks.get_db()
    return _group_public(db, _group_row(db, group_id))


def expand_group(group_id, include_deleted=True):
    """Members in order: [{media_id, status: ok|deleted|missing, media}]; generation callers pass include_deleted=False."""
    group = get_group(group_id)
    items = []
    for media_id in group['media_ids']:
        state, row = status(media_id)
        if state != 'ok' and not include_deleted:
            continue
        items.append({'media_id': media_id, 'status': state,
                      'media': public(row) if state == 'ok' else deleted_public(row) if state == 'deleted' else
                      trashed_public(row) if state == 'trashed' else None})
    return {'group': group, 'items': items}


def create_group(title, media_ids, *, group_id=None, created_at=None):
    """``group_id``/``created_at`` let S1b keep old project group ids (documents reference them)."""
    title = _group_title(title)
    with store.write_transaction() as db:
        media_ids = _members(db, media_ids)
        if not media_ids:
            raise MediaError('素材组至少需要一个素材', 400, 'invalid_request')
        group_id = _check_id(group_id) if group_id is not None else uuid.uuid4().hex
        if db.execute('SELECT 1 FROM media_groups WHERE id=?', (group_id,)).fetchone():
            raise MediaError('素材组已存在', 409, 'invalid_request')
        now = tasks.utcnow()
        db.execute('INSERT INTO media_groups VALUES (?,?,?,?)', (group_id, title, created_at or now, now))
        _write_members(db, group_id, media_ids)
        return _group_public(db, _group_row(db, group_id))


def update_group(group_id, data):
    """``title``; ``media_ids`` (replace, ordered) or ``add``/``remove`` (append/remove)."""
    if not isinstance(data, dict) or not data or set(data) - {'title', 'media_ids', 'add', 'remove'} or ('media_ids' in data and ({'add', 'remove'} & set(data))):
        raise MediaError('素材组字段无效')
    with store.write_transaction() as db:
        row = _group_row(db, group_id)
        current = [r[0] for r in db.execute('SELECT media_id FROM media_group_members WHERE group_id=? ORDER BY position', (group_id,))]
        members = current
        if 'media_ids' in data:
            members = _members(db, data['media_ids'], set(current))
        if 'remove' in data:
            remove = data['remove']
            if not isinstance(remove, list) or len(remove) > MAX_GROUP or any(not isinstance(i, str) or not MEDIA_ID.fullmatch(i) for i in remove):
                raise MediaError(f'remove 须为最多{MAX_GROUP}个素材编号', 400, 'invalid_id')
            removed = set(remove)  # placeholders (deleted media) can be removed too
            members = [m for m in members if m not in removed]
        if 'add' in data:
            members = list(dict.fromkeys(members + _members(db, data['add'], set(current))))
        if len(members) > MAX_GROUP:
            raise MediaError(f'素材组最多{MAX_GROUP}个素材', 400, 'too_many')
        if not members:
            raise MediaError('素材组至少需要一个素材；如不再需要请删除素材组', 400, 'invalid_request')
        title = _group_title(data['title']) if 'title' in data else row['title']
        db.execute('UPDATE media_groups SET title=?,updated_at=? WHERE id=?', (title, tasks.utcnow(), group_id))
        _write_members(db, group_id, members)
        return _group_public(db, _group_row(db, group_id))


def delete_group(group_id):
    """Deletes only the reference set, never media."""
    with store.write_transaction() as db:
        _group_row(db, group_id)
        db.execute('DELETE FROM media_groups WHERE id=?', (group_id,))


# ---------------------------------------------------------------- deletion

def strip_document(document, removed):
    """Remove deleted ids from inputs; ``asset``/``candidates`` keep them as placeholders.

    Returns (document, stripped node count, placeholder node count).
    """
    nodes, stripped, placeholders = [], 0, 0
    for node in document.get('nodes', []):
        original = json.dumps(node, sort_keys=True)
        node = dict(node)
        if (node.get('asset') or {}).get('id') in removed or any(c.get('id') in removed for c in node.get('candidates', []) if isinstance(c, dict)):
            placeholders += 1
        lost_input = False
        if 'referenceAssets' in node:
            kept = [a for a in node['referenceAssets'] if a.get('id') not in removed]
            lost_input = len(kept) != len(node['referenceAssets'])
            node['referenceAssets'] = kept
        if 'referenceGroups' in node:
            groups = []
            for group in node['referenceGroups']:
                ids = [i for i in group.get('asset_ids', []) if i not in removed]
                lost_input = lost_input or len(ids) != len(group.get('asset_ids', []))
                if ids:
                    groups.append({**group, 'asset_ids': ids})
            node['referenceGroups'] = groups
        if 'referenceOrder' in node:
            node['referenceOrder'] = [i for i in node['referenceOrder'] if i not in removed]
        if 'referenceMentions' in node:
            node['referenceMentions'] = {k: v for k, v in node['referenceMentions'].items() if v not in removed}
        if isinstance(node.get('characterRefs'), dict):
            node['characterRefs'] = {k: {**v, 'assetIds': [i for i in v.get('assetIds', []) if i not in removed]} if isinstance(v, dict) else v
                                     for k, v in node['characterRefs'].items()}
        if lost_input and node.get('type') in GENERATION and node.get('asset'):
            node['upstreamStale'] = True
        if json.dumps(node, sort_keys=True) != original:
            stripped += 1
        nodes.append(node)
    return {**document, 'nodes': nodes}, stripped, placeholders


def _active_workflows(db):
    return db.execute('''SELECT w.id, w.title AS workflow_title, w.project_id, p.title AS project_title, w.document
        FROM canvas_workflows w LEFT JOIN canvas_projects p ON p.id=w.project_id WHERE
        NOT EXISTS (SELECT 1 FROM canvas_deletions d WHERE d.scope='workflow' AND d.id=w.id) AND
        NOT EXISTS (SELECT 1 FROM canvas_deletions d WHERE d.scope='project' AND d.id=w.project_id)
        ORDER BY p.title, w.title, w.id''').fetchall()


def _plan(db, ids):
    rows, missing = [], []
    for media_id in ids:
        row = db.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()
        (rows.append(dict(row)) if row else missing.append(media_id))
    present = [r['id'] for r in rows]
    removed = set(present)
    for media_id in present:
        removed |= {r[0] for r in db.execute('SELECT old_id FROM media_aliases WHERE media_id=?', (media_id,))}
    affected, documents = [], {}
    if removed:
        for wf in _active_workflows(db):
            if not any(i in wf['document'] for i in removed):
                continue
            document, stripped, placeholders = strip_document(json.loads(wf['document']), removed)
            if not (stripped or placeholders):
                continue
            if stripped:
                documents[wf['id']] = document
            affected.append({'workflow_id': wf['id'], 'workflow_title': wf['workflow_title'], 'project_id': wf['project_id'],
                             'project_title': wf['project_title'], 'placeholder_nodes': placeholders, 'stripped_nodes': stripped})
    from characters import usage
    characters = usage(db, sorted(removed))
    groups = [g for g in db.execute('SELECT id,asset_ids FROM canvas_asset_groups').fetchall()
              if set(json.loads(g['asset_ids'])) & removed]
    media_groups = {}
    for media_id in present:
        for r in db.execute('SELECT g.id, g.title FROM media_groups g JOIN media_group_members m ON m.group_id=g.id WHERE m.media_id=?', (media_id,)):
            media_groups[r['id']] = {'id': r['id'], 'title': r['title']}
    task_ids = set()
    for media_id in present:
        task_ids |= {r[0] for r in db.execute('SELECT task_id FROM task_assets WHERE media_id=? AND task_id IS NOT NULL', (media_id,))}
    # A copy outside 生成历史 keeps its source task as provenance only; the task card shows
    # the original, so only 生成历史 items count their source task.
    task_ids |= {r['source_task_id'] for r in rows if r['source_task_id'] is not None and r['folder_id'] in GENERATED_FOLDERS}
    return {'rows': rows, 'removed': removed, 'documents': documents, 'groups': groups,
            'summary': {'items': [public(r) for r in rows], 'missing': missing, 'affected_workflows': affected,
                        'characters': characters, 'asset_groups': len(groups),
                        'media_groups': sorted(media_groups.values(), key=lambda g: (g['title'], g['id'])), 'task_ids': sorted(task_ids)}}


def delete_preview(ids):
    ids = _ids(ids)
    db = tasks.get_db()
    owns = not db.in_transaction
    if owns:
        db.execute('BEGIN')
    try:
        return _plan(db, ids)['summary']
    finally:
        if owns:
            db.rollback()


def apply_delete(db, plan, staged, token):
    """Inside the caller's write transaction: tombstones, references, then stage the files.

    Files are renamed to ``*.deleting-<token>`` (``staged``); the caller unlinks them after
    commit (``finish_delete``) or renames them back on failure (``undo_delete``).
    """
    now = tasks.utcnow()
    for row in plan['rows']:
        db.execute('INSERT OR REPLACE INTO media_tombstones VALUES (?,?,?,?,?,?,?)',
                   (row['id'], row['name'], row['kind'], row['mime_type'], row['origin'], row['source_task_id'], now))
        db.execute('DELETE FROM media WHERE id=?', (row['id'],))
    from characters import unlink_local
    unlink_local(db, sorted(plan['removed']))
    for group in plan['groups']:
        kept = [i for i in json.loads(group['asset_ids']) if i not in plan['removed']]
        if kept:
            db.execute('UPDATE canvas_asset_groups SET asset_ids=?,updated_at=? WHERE id=?', (json.dumps(kept), now, group['id']))
        else:
            db.execute('DELETE FROM canvas_asset_groups WHERE id=?', (group['id'],))
    for workflow_id, document in plan['documents'].items():
        encoded = store.validate_document(document, workflow_id)
        db.execute('UPDATE canvas_workflows SET document=?,revision=revision+1,updated_at=? WHERE id=?', (encoded, now, workflow_id))
        db.execute('UPDATE canvas_projects SET updated_at=? WHERE id=(SELECT project_id FROM canvas_workflows WHERE id=?)', (now, workflow_id))
    directory = root()
    for row in plan['rows']:
        path = directory / row['relpath']
        if path.resolve() != path or not path.is_relative_to(directory) or not path.exists():
            continue
        pending = path.with_name(f'{path.name}.deleting-{token}')
        try:
            os.rename(path, pending)
        except OSError as error:
            raise MediaError(f'素材文件无法删除，未做任何更改：{path.name}', 409, 'file_missing') from error
        staged.append((path, pending))


def undo_delete(staged):
    if staged:
        # Rollback has released the lock; a second deletion could already have won.
        _reconcile_staged_deletes(reversed(staged))


def finish_delete(staged):
    removed_files = 0
    for _, pending in staged:
        try:
            pending.unlink()
            removed_files += 1
        except OSError:
            pass  # unregistered and never served; reclaimable by maintenance
    return removed_files


def recover_staged_deletes():
    """Reconcile interrupted deletions with committed rows under the same writer lock."""
    directory = root()
    pending_files = []
    with os.scandir(directory) as entries:
        for entry in entries:
            match = STAGED_DELETE.fullmatch(entry.name)
            if match and entry.is_file(follow_symlinks=False):
                pending_files.append((directory / entry.name, directory / match['filename']))
    if not pending_files:
        return
    _reconcile_staged_deletes((path, pending) for pending, path in pending_files)


def _reconcile_staged_deletes(staged):
    restored = removed = 0
    with store.write_transaction() as db:
        for path, pending in staged:
            if pending.is_symlink() or not pending.is_file():
                continue  # a concurrent startup or normal post-commit cleanup handled it
            media_id = path.stem
            row = db.execute('SELECT relpath FROM media WHERE id=?', (media_id,)).fetchone()
            try:
                if row is not None and row['relpath'] == path.name:
                    # A failed transaction leaves the media row. Never overwrite a file.
                    if not path.exists() and not path.is_symlink():
                        os.rename(pending, path)
                        restored += 1
                    elif not path.is_symlink() and path.samefile(pending):
                        pending.unlink(missing_ok=True)
                        removed += 1
                    else:
                        LOG.warning('media_delete_recovery_conflict file=%s', path.name)
                elif row is None and db.execute('SELECT 1 FROM media_tombstones WHERE id=?', (media_id,)).fetchone():
                    pending.unlink(missing_ok=True)
                    removed += 1
            except FileNotFoundError:
                continue  # normal post-commit cleanup is allowed to win
            except OSError:
                LOG.exception('media_delete_recovery_failed file=%s', path.name)
    if restored or removed:
        LOG.info('media_delete_recovery restored=%s removed=%s', restored, removed)


def delete_media(ids):
    """Permanent library deletion: rows, files, references; nodes keep placeholders."""
    ids = _ids(ids)
    staged, token = [], uuid.uuid4().hex
    try:
        with store.write_transaction() as db:
            plan = _plan(db, ids)
            apply_delete(db, plan, staged, token)
            summary = plan['summary']
    except BaseException:
        undo_delete(staged)
        raise
    removed_files = finish_delete(staged)
    return {**summary, 'deleted_ids': [r['id'] for r in plan['rows']], 'files_removed': removed_files}
