"""Character library (CHARACTER-LIBRARY-20261114 A, 规格修订 2; LIBRARY-GLOBAL-20261116 S6c).

A character is global (not owned by any project): a unique name, a text description,
up to 8 reference images and an optional reference audio (voice). Images and voice
are *references* to items of the global media library (``media``; the column
``character_media.local_id`` holds the media id); the character stores only the
reference and its order, never a copy and never a registration in the old 本地素材
table.

Sources: an upload is registered in the library root (``media_library.save_upload``,
origin ``upload``, dedup by content); a media id (``{source:'media', media_id}``, or a
library selection ``{source:'media', id}``) is referenced directly; an old identity
(``local:<id>``, ``library:``/``workflow:``/``task:`` keys, old canvas asset ids) is
resolved through ``media_aliases``. Only a selection that is not in the library (Cupsy,
items not migrated yet) is copied into the library root first, then referenced.

Deleting a character or removing an image/voice deletes only the reference. Deleting a
referenced media item (media_library.delete_media) lists the affected characters in the
preview and removes the reference from them (``usage``/``unlink_local``).

``POST /api/canvas/workflows/<wf>/character-assets`` returns media node assets
(``canvas_media_refs.node_asset``); nothing is copied into the canvas.
"""
import io
import json
import logging
import re
import sqlite3
import subprocess
import uuid

from PIL import Image

import canvas_store as store
import media_library as media
import tasks

LOG = logging.getLogger(__name__)
MAX_IMAGES = 8
MAX_VOICE_SECONDS = 30.0
MAX_DESCRIPTION = 300
KINDS = ('character', 'prop')
NAME_FORBIDDEN = re.compile(r'[\s@\[\]()（）/\\]')
NAME_RESERVED = re.compile(r'^(图片|视频|音频)\d+$')
HEX_ID = re.compile(r'^[0-9a-f]{32}$')
VOICE_MIMES = ('audio/wav', 'audio/mpeg')


def _ensure_character_folder(db, character_id, name, now=None):
    """Ensure the system root 角色卡 and this character's 角色卡/<name> subfolder exist."""
    ts = now or tasks.utcnow()
    root_id = media.system_folder_id(media.CHARACTER_ROOT_KEY)
    db.execute(
        'INSERT OR IGNORE INTO media_folders VALUES (?,?,?,?,?,?,?)',
        (root_id, '角色卡', None, media.CHARACTER_ROOT_KEY, 'character', ts, ts),
    )
    fid = media.character_folder_id(character_id)
    sys_key = f'character:{character_id}'
    existing = db.execute('SELECT title, parent_id, system_key FROM media_folders WHERE id=?', (fid,)).fetchone()
    if existing is None:
        db.execute(
            'INSERT INTO media_folders VALUES (?,?,?,?,?,?,?)',
            (fid, name, root_id, sys_key, 'character', ts, ts),
        )
    elif existing['title'] != name or existing['parent_id'] != root_id or existing['system_key'] != sys_key:
        db.execute(
            'UPDATE media_folders SET title=?, parent_id=?, system_key=?, updated_at=? WHERE id=?',
            (name, root_id, sys_key, tasks.utcnow(), fid),
        )
    return fid


def _place_for_character(db, character_id, row, char_folder_id, created_files):
    """Place a validated media row into 角色卡/<name>: move from root/user folder, hard-link copy from 生成历史 or another character."""
    if row['folder_id'] == char_folder_id:
        return row
    in_generated = row['folder_id'] in media.GENERATED_FOLDERS
    source_folder_key = None
    if row['folder_id']:
        src = db.execute('SELECT system_key FROM media_folders WHERE id=?', (row['folder_id'],)).fetchone()
        source_folder_key = src['system_key'] if src else None
    in_other_char = bool(
        source_folder_key
        and source_folder_key.startswith('character:')
        and source_folder_key != f'character:{character_id}'
    )
    used_by_other_char = bool(
        db.execute(
            'SELECT 1 FROM character_media WHERE local_id=? AND character_id!=?',
            (row['id'], character_id),
        ).fetchone()
    )
    if in_generated or in_other_char or used_by_other_char:
        new_id = media._copy_item(db, row, char_folder_id, created_files)
        return dict(db.execute('SELECT * FROM media WHERE id=?', (new_id,)).fetchone())
    db.execute('UPDATE media SET folder_id=? WHERE id=?', (char_folder_id, row['id']))
    return dict(db.execute('SELECT * FROM media WHERE id=?', (row['id'],)).fetchone())


def ensure_character_folders():
    """Startup auto-migration (CHAR-FOLDERS-20261122): idempotently align 角色卡/<name> folders and media placement."""
    db = tasks.get_db()
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'media_folders', 'media', 'characters', 'character_media'} <= tables:
        return
    created_files = []
    try:
        with store.write_transaction() as wdb:
            now = tasks.utcnow()
            root_id = media.system_folder_id(media.CHARACTER_ROOT_KEY)
            wdb.execute(
                'INSERT OR IGNORE INTO media_folders VALUES (?,?,?,?,?,?,?)',
                (root_id, '角色卡', None, media.CHARACTER_ROOT_KEY, 'character', now, now),
            )
            char_rows = wdb.execute('SELECT id, name, created_at FROM characters ORDER BY created_at, id').fetchall()
            live_ids = set()
            for crow in char_rows:
                cid = crow['id']
                live_ids.add(cid)
                fid = _ensure_character_folder(wdb, cid, crow['name'], crow['created_at'])
                cm_rows = wdb.execute(
                    'SELECT local_id FROM character_media WHERE character_id=? ORDER BY role, position, created_at, local_id',
                    (cid,),
                ).fetchall()
                for cm in cm_rows:
                    mrow = wdb.execute('SELECT * FROM media WHERE id=?', (cm['local_id'],)).fetchone()
                    if mrow is None:
                        continue
                    if mrow['folder_id'] != fid:
                        old_id = mrow['id']
                        try:
                            placed = _place_for_character(wdb, cid, dict(mrow), fid, created_files)
                        except (media.MediaError, OSError) as err:
                            LOG.warning('character_folder_migration_skip character=%s media=%s err=%s', cid, old_id, err)
                            continue
                        if placed['id'] != old_id:
                            if wdb.execute(
                                'SELECT 1 FROM character_media WHERE character_id=? AND local_id=?',
                                (cid, placed['id']),
                            ).fetchone():
                                wdb.execute(
                                    'DELETE FROM character_media WHERE character_id=? AND local_id=?',
                                    (cid, old_id),
                                )
                            else:
                                wdb.execute(
                                    'UPDATE character_media SET local_id=? WHERE character_id=? AND local_id=?',
                                    (placed['id'], cid, old_id),
                                )
            for folder in wdb.execute("SELECT id, system_key FROM media_folders WHERE system_key LIKE 'character:%'").fetchall():
                cid = folder['system_key'][len('character:'):]
                if cid not in live_ids:
                    has_media = wdb.execute('SELECT 1 FROM media WHERE folder_id=? LIMIT 1', (folder['id'],)).fetchone()
                    has_child = wdb.execute('SELECT 1 FROM media_folders WHERE parent_id=? LIMIT 1', (folder['id'],)).fetchone()
                    if not has_media and not has_child:
                        wdb.execute('DELETE FROM media_folders WHERE id=?', (folder['id'],))
        created_files.clear()
    except BaseException:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise


def init_characters_db():
    db = tasks.get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS characters (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'character',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS character_media (
        character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
        local_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('image','voice')),
        position INTEGER NOT NULL DEFAULT 0, width INTEGER, height INTEGER, duration REAL,
        created_at TEXT NOT NULL, PRIMARY KEY(character_id, local_id));
    CREATE INDEX IF NOT EXISTS idx_character_media_local ON character_media(local_id);
    ''')
    columns = {row[1] for row in db.execute('PRAGMA table_info(characters)')}
    if 'description' not in columns:  # forward-compatible additive migration
        db.execute("ALTER TABLE characters ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    if 'kind' not in columns:
        db.execute("ALTER TABLE characters ADD COLUMN kind TEXT NOT NULL DEFAULT 'character'")
    db.commit()
    ensure_character_folders()


# ---- validation -------------------------------------------------------------------

def name_value(value):
    if not isinstance(value, str):
        raise store.CanvasError('角色名须为字符串')
    name = value.strip()
    if not 1 <= len(name) <= 24:
        raise store.CanvasError('角色名须为1至24个字符')
    if NAME_FORBIDDEN.search(name) or any(ord(c) < 32 for c in name):
        raise store.CanvasError('角色名不能包含空白、@、方括号、圆括号或斜杠')
    if NAME_RESERVED.fullmatch(name):
        raise store.CanvasError('角色名不能为“图片N”“视频N”“音频N”形式')
    return name


def description_value(value):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise store.CanvasError('角色描述须为字符串')
    value = value.strip()
    if len(value) > MAX_DESCRIPTION:
        raise store.CanvasError(f'角色描述不能超过{MAX_DESCRIPTION}个字')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise store.CanvasError('角色描述包含无效字符')
    return value


def kind_value(value):
    if value is None:
        return 'character'
    if not isinstance(value, str) or value not in KINDS:
        raise store.CanvasError('角色卡类型无效（仅支持 character 或 prop）')
    return value


def _check_id(value, label='角色'):
    if not isinstance(value, str) or not HEX_ID.fullmatch(value):
        raise store.CanvasError(f'{label}不存在', 404)
    return value


def _ensure_unique(db, name, exclude=None):
    row = db.execute('SELECT id FROM characters WHERE name_key=?', (name.casefold(),)).fetchone()
    if row is not None and row['id'] != exclude:
        raise store.CanvasError('角色名已存在', 409)


def _probe_duration(path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-protocol_whitelist', 'file', '-show_entries', 'format=duration',
             '-of', 'json', str(path)], capture_output=True, timeout=10, check=False)
        duration = float(json.loads(result.stdout)['format']['duration'])
    except FileNotFoundError:
        raise store.CanvasError('服务缺少音视频格式检查工具 ffprobe', 503)
    except subprocess.TimeoutExpired:
        raise store.CanvasError('媒体格式检查超时')
    except (ValueError, TypeError, KeyError):
        raise store.CanvasError('无法读取参考音频时长')
    if result.returncode or not duration > 0:
        raise store.CanvasError('无法读取参考音频时长')
    return duration


def _media_facts(row, role):
    """Validate a media row for the role; returns (width, height, duration)."""
    path = media.media_path(row)
    if role == 'image':
        if row['kind'] != 'image':
            raise store.CanvasError('角色图须为图片素材')
        try:
            with Image.open(path) as picture:
                width, height = picture.size
        except (OSError, Image.DecompressionBombError) as error:
            raise store.CanvasError('角色图无法读取', 409) from error
        return width, height, None
    if row['mime_type'] not in VOICE_MIMES:
        raise store.CanvasError('参考音频仅支持 WAV 或 MP3')
    duration = _probe_duration(path)
    if duration > MAX_VOICE_SECONDS + 0.05:
        raise store.CanvasError('参考音频不能超过30秒')
    return None, None, round(duration, 3)


# ---- public shapes ----------------------------------------------------------------

def _url(character_id, local_id):
    return f'/api/characters/{character_id}/assets/{local_id}'


def image_public(row):
    url = _url(row['character_id'], row['local_id'])
    return {'asset_id': row['local_id'], 'asset_ref': row['local_id'], 'media_id': row['local_id'], 'url': url,
            'thumbnail_url': url + '/thumbnail', 'name': row['name'], 'mime_type': row['mime_type'],
            'width': row['width'], 'height': row['height'], 'position': row['position']}


def voice_public(row):
    return {'type': 'audio', 'asset_id': row['local_id'], 'asset_ref': row['local_id'], 'media_id': row['local_id'],
            'url': _url(row['character_id'], row['local_id']), 'name': row['name'],
            'mime_type': row['mime_type'], 'duration': row['duration']}


MEDIA_SQL = '''SELECT m.*, x.name, x.mime_type, x.kind, x.relpath, x.sha256 FROM character_media m
               JOIN media x ON x.id=m.local_id'''


def _public(row, media_rows):
    images = sorted((m for m in media_rows if m['role'] == 'image'), key=lambda m: (m['position'], m['created_at'], m['local_id']))
    voice = next((m for m in media_rows if m['role'] == 'voice'), None)
    kind = row['kind'] if 'kind' in row.keys() and row['kind'] in KINDS else 'character'
    return {'id': row['id'], 'name': row['name'], 'description': row['description'], 'kind': kind,
            'folder_id': media.character_folder_id(row['id']),
            'voice': voice_public(voice) if voice else None, 'images': [image_public(m) for m in images],
            'created_at': row['created_at'], 'updated_at': row['updated_at']}


def _row(db, character_id):
    _check_id(character_id)
    row = db.execute('SELECT * FROM characters WHERE id=?', (character_id,)).fetchone()
    if row is None:
        raise store.CanvasError('角色不存在', 404)
    return row


def _media(db, character_id, role=None):
    sql, args = MEDIA_SQL + ' WHERE m.character_id=?', [character_id]
    if role:
        sql, args = sql + ' AND m.role=?', args + [role]
    return [dict(r) for r in db.execute(sql + ' ORDER BY m.position,m.created_at,m.local_id', args)]


def get_character(character_id):
    db = tasks.get_db()
    return _public(_row(db, character_id), _media(db, character_id))


def _media_ref(value):
    """Media id for a media id, ``media:<id>``, an old ``local:<id>``/``scope:id`` key or URL; None if unknown."""
    if not isinstance(value, str):
        return None
    if value.startswith('media:'):
        value = value[len('media:'):]
    found = media.resolve(value)
    if found is None and HEX_ID.fullmatch(value):
        found = media.resolve('local:' + value)
    return found


def _canonical(db, character_id, ident):
    """The stored reference id for ``ident`` (a media id or an old 本地素材 id via its alias)."""
    if not isinstance(ident, str):
        return ident
    if db.execute('SELECT 1 FROM character_media WHERE character_id=? AND local_id=?', (character_id, ident)).fetchone():
        return ident
    return _media_ref(ident) or ident


def list_characters(asset_ref=None):
    """All characters; with ``asset_ref`` (media id, ``media:<id>`` or an old ``local:<id>``) only those using it."""
    db = tasks.get_db()
    only = None
    if asset_ref is not None:
        ident = _media_ref(asset_ref)
        if ident is None:
            return []
        only = {r[0] for r in db.execute('SELECT character_id FROM character_media WHERE local_id=?', (ident,))}
    grouped = {}
    for item in db.execute(MEDIA_SQL + ' ORDER BY m.position,m.created_at,m.local_id'):
        grouped.setdefault(item['character_id'], []).append(dict(item))
    return [_public(row, grouped.get(row['id'], []))
            for row in db.execute('SELECT * FROM characters ORDER BY updated_at DESC,id')
            if only is None or row['id'] in only]


def get_media(character_id, local_id, role=None):
    db = tasks.get_db()
    _row(db, character_id)
    _check_id(local_id, '角色素材')
    local_id = _canonical(db, character_id, local_id)
    row = db.execute(MEDIA_SQL + ' WHERE m.character_id=? AND m.local_id=?', (character_id, local_id)).fetchone()
    if row is None or (role and row['role'] != role):
        raise store.CanvasError('角色素材不存在', 404)
    return dict(row)


def _touch(db, character_id):
    db.execute('UPDATE characters SET updated_at=? WHERE id=?', (tasks.utcnow(), character_id))


def _renumber(db, character_id):
    rows = db.execute("SELECT local_id FROM character_media WHERE character_id=? AND role='image' "
                      'ORDER BY position,created_at,local_id', (character_id,)).fetchall()
    for position, item in enumerate(rows):
        db.execute('UPDATE character_media SET position=? WHERE character_id=? AND local_id=?', (position, character_id, item[0]))


# ---- used by media_library / local_delete deletion ---------------------------------------------------------

def usage(db, local_ids):
    """Characters referencing these media ids (or alias old ids): [{id, name, asset_ids}]."""
    found = {}
    for local_id in local_ids:
        for r in db.execute('SELECT c.id, c.name FROM character_media m JOIN characters c ON c.id=m.character_id '
                            'WHERE m.local_id=?', (local_id,)):
            found.setdefault(r['id'], {'id': r['id'], 'name': r['name'], 'asset_ids': []})['asset_ids'].append(local_id)
    return sorted(found.values(), key=lambda c: (c['name'], c['id']))


def unlink_local(db, local_ids):
    """Remove references to deleted media ids; renumber image order; bump updated_at."""
    affected = usage(db, local_ids)
    for character in affected:
        for local_id in character['asset_ids']:
            db.execute('DELETE FROM character_media WHERE character_id=? AND local_id=?', (character['id'], local_id))
        _renumber(db, character['id'])
        _touch(db, character['id'])
    return affected


# ---- sources ----------------------------------------------------------------------
# A source is ('media', media_id) or ('upload', stream, name): uploads and copies are
# registered inside the caller's write transaction (save_upload joins it and journals the
# new file), so a refused change leaves no library item behind.

def _copy_source(path, name):
    try:
        return ('copy', path.open('rb'), name)
    except OSError as error:
        raise store.CanvasError('来源素材文件无法读取', 409) from error


def _live(media_id):
    state, _ = media.status(media_id)
    if state == 'deleted':
        raise store.CanvasError('素材已从素材库删除', 410)
    if state == 'trashed':
        raise store.CanvasError('该生成结果所在的任务在回收站，恢复任务后可用', 409)
    if state != 'ok':
        raise store.CanvasError('素材不存在', 404)
    return ('media', media_id)


def _resolve_sources(uploads, data):
    """Return [('media', id) | ('upload'|'copy', stream, name)] without holding a database lock."""
    if uploads is not None:
        return [('upload', upload.stream, upload.filename) for upload in uploads]
    if not isinstance(data, dict):
        raise store.CanvasError('素材来源须为 multipart 上传、media、library 或 canvas')
    source = data.get('source')
    if source == 'media':
        if set(data) - {'source', 'media_id'}:
            raise store.CanvasError('素材来源字段无效')
        ident = data.get('media_id')
        if not isinstance(ident, str) or not HEX_ID.fullmatch(ident):
            raise store.CanvasError('素材编号无效')
        return [_live(_media_ref(ident) or ident)]
    if source == 'library':
        if set(data) - {'source', 'asset_ref'}:
            raise store.CanvasError('素材来源字段无效')
        ref = data.get('asset_ref')
        if isinstance(ref, dict) and ref.get('source') == 'media':
            ident = ref.get('id')
            if set(ref) != {'source', 'id'} or not isinstance(ident, str) or not HEX_ID.fullmatch(ident):
                raise store.CanvasError('素材选择编号无效')
            return [_live(_media_ref(ident) or ident)]
        from canvas_catalog import parse_selection, resolve, selection_from_key
        selection = selection_from_key(ref) if isinstance(ref, str) else ref
        _, _, key = parse_selection(selection)
        found = media.resolve(key)  # old identities migrated into the library (aliases)
        if found is not None:
            return [_live(found)]
        row, path, _ = resolve(selection)  # e.g. Cupsy: copy into the library root
        return [_copy_source(path, row.get('name') or path.name)]
    if source == 'canvas':
        if set(data) - {'source', 'workflow_id', 'asset_id'}:
            raise store.CanvasError('素材来源字段无效')
        workflow_id, asset_id = data.get('workflow_id'), data.get('asset_id')
        if not isinstance(workflow_id, str) or not isinstance(asset_id, str):
            raise store.CanvasError('workflow_id 和 asset_id 必须为字符串')
        store.workflow(workflow_id)
        found = media.resolve('workflow:' + asset_id) if HEX_ID.fullmatch(asset_id) else None
        if found is None and HEX_ID.fullmatch(asset_id) and media.status(asset_id)[0] != 'missing':
            found = asset_id
        if found is not None:
            return [_live(found)]
        row = store.get_asset(workflow_id, asset_id)  # old canvas copy not migrated yet
        return [_copy_source(store.asset_path(row), row['name'])]
    raise store.CanvasError('素材来源须为 multipart 上传、media、library 或 canvas')


def _media_rows(db, sources, folder_id=None):
    """Inside the write transaction: register uploads/copies in the target folder and load rows."""
    rows = []
    for source in sources:
        if source[0] in ('upload', 'copy'):
            media_id = media.save_upload(
                source[1], source[2], folder_id=folder_id, origin='upload', allow_character_folder=bool(folder_id),
            )[0]['id']
        else:
            media_id = source[1]
        row = db.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()
        if row is None:
            raise store.CanvasError('素材不存在或已删除', 404)
        rows.append(dict(row))
    return rows


def _discard(sources):
    for source in sources:
        if source[0] == 'copy':
            source[1].close()  # opened by _copy_source; upload streams belong to Flask


# ---- mutations --------------------------------------------------------------------

def create_character(data):
    if set(data) - {'name', 'description', 'kind'}:
        raise store.CanvasError('未知角色字段')
    name, description, kind = name_value(data.get('name')), description_value(data.get('description')), kind_value(data.get('kind'))
    ident, now = uuid.uuid4().hex, tasks.utcnow()
    try:
        with store.write_transaction() as db:
            _ensure_unique(db, name)
            db.execute('INSERT INTO characters (id, name, name_key, description, kind, created_at, updated_at) VALUES (?,?,?,?,?,?,?)',
                       (ident, name, name.casefold(), description, kind, now, now))
            _ensure_character_folder(db, ident, name, now)
    except sqlite3.IntegrityError as error:
        raise store.CanvasError('角色名已存在', 409) from error
    return get_character(ident)


def update_character(character_id, data):
    if not data or set(data) - {'name', 'description', 'kind', 'voice', 'image_order'}:
        raise store.CanvasError('角色更新字段无效')
    try:
        with store.write_transaction() as db:
            row = _row(db, character_id)
            changed = False
            if 'name' in data:
                name = name_value(data['name'])
                _ensure_unique(db, name, exclude=character_id)
                if name != row['name']:
                    db.execute('UPDATE characters SET name=?,name_key=? WHERE id=?', (name, name.casefold(), character_id))
                    _ensure_character_folder(db, character_id, name, tasks.utcnow())
                    changed = True
            if 'description' in data:
                description = description_value(data['description'])
                if description != row['description']:
                    db.execute('UPDATE characters SET description=? WHERE id=?', (description, character_id))
                    changed = True
            if 'kind' in data:
                kind = kind_value(data['kind'])
                current_kind = row['kind'] if 'kind' in row.keys() else 'character'
                if kind != current_kind:
                    db.execute('UPDATE characters SET kind=? WHERE id=?', (kind, character_id))
                    changed = True
            if 'voice' in data:
                current = _media(db, character_id, 'voice')
                voice = data['voice']
                if voice is None:
                    if current:
                        char_folder_id = media.character_folder_id(character_id)
                        old_voice_id = current[0]['local_id']
                        db.execute("DELETE FROM character_media WHERE character_id=? AND role='voice'", (character_id,))
                        db.execute('UPDATE media SET folder_id=NULL WHERE id=? AND folder_id=?', (old_voice_id, char_folder_id))
                        changed = True
                elif not (isinstance(voice, dict) and voice.get('type') == 'audio' and current
                          and _canonical(db, character_id, voice.get('asset_id')) == current[0]['local_id']):
                    raise store.CanvasError('声音只能清除（null）；参考音频请通过 voice-audio 接口设置')
            if 'image_order' in data:
                order = data['image_order']
                images = [m['local_id'] for m in _media(db, character_id, 'image')]
                if isinstance(order, list) and all(isinstance(i, str) for i in order):
                    order = [_canonical(db, character_id, i) for i in order]
                if not isinstance(order, list) or any(not isinstance(i, str) for i in order) \
                        or len(order) != len(images) or set(order) != set(images):
                    raise store.CanvasError('image_order 须为该角色全部图片编号的排列')
                if order != images:
                    changed = True
                for position, local_id in enumerate(order):
                    db.execute('UPDATE character_media SET position=? WHERE character_id=? AND local_id=?',
                               (position, character_id, local_id))
            if changed:
                _touch(db, character_id)
    except sqlite3.IntegrityError as error:
        raise store.CanvasError('角色名已存在', 409) from error
    return get_character(character_id)


def delete_character_preview(character_id):
    """Read-only preview of deleting a character card and optionally its media."""
    db = tasks.get_db()
    owns = not db.in_transaction
    if owns:
        db.execute('BEGIN')
    try:
        row = _row(db, character_id)
        char_folder_id = media.character_folder_id(character_id)
        char_media_ids = [r[0] for r in db.execute(
            'SELECT local_id FROM character_media WHERE character_id=? ORDER BY role, position, created_at, local_id',
            (character_id,),
        ).fetchall()]
        folder_media_ids = [r[0] for r in db.execute(
            'SELECT id FROM media WHERE folder_id=? ORDER BY created_at DESC, id',
            (char_folder_id,),
        ).fetchall()]
        media_ids = list(dict.fromkeys(char_media_ids + folder_media_ids))
        if media_ids:
            summary = media._plan(db, media_ids)['summary']
            summary['characters'] = [c for c in summary['characters'] if c['id'] != character_id]
        else:
            summary = {
                'items': [],
                'missing': [],
                'affected_workflows': [],
                'characters': [],
                'asset_groups': 0,
                'media_groups': [],
                'task_ids': [],
            }
        return {
            'character': {'id': row['id'], 'name': row['name'], 'folder_id': char_folder_id},
            'folder_title': f"角色卡 / {row['name']}",
            'media_count': len(summary['items']),
            'preview': summary,
        }
    finally:
        if owns:
            db.rollback()


def delete_character(character_id, delete_media=False):
    """Delete a character card: keep media moved back to root (default) or permanently delete media too."""
    _check_id(character_id)
    char_folder_id = media.character_folder_id(character_id)
    if not delete_media:
        with store.write_transaction() as db:
            _row(db, character_id)
            count = db.execute('DELETE FROM character_media WHERE character_id=?', (character_id,)).rowcount
            moved = db.execute('UPDATE media SET folder_id=NULL WHERE folder_id=?', (char_folder_id,)).rowcount
            db.execute('DELETE FROM characters WHERE id=?', (character_id,))
            db.execute('DELETE FROM canvas_asset_copies WHERE source_key=?', ('character:' + character_id,))
            db.execute('DELETE FROM media_folders WHERE id=?', (char_folder_id,))
        return {
            'deleted_id': character_id,
            'references_removed': count,
            'media_moved_to_root': moved,
            'deleted_media_ids': [],
            'files_removed': 0,
        }

    staged, token = [], uuid.uuid4().hex
    try:
        with store.write_transaction() as db:
            _row(db, character_id)
            char_media_ids = [r[0] for r in db.execute(
                'SELECT local_id FROM character_media WHERE character_id=? ORDER BY role, position, created_at, local_id',
                (character_id,),
            ).fetchall()]
            folder_media_ids = [r[0] for r in db.execute(
                'SELECT id FROM media WHERE folder_id=? ORDER BY created_at DESC, id',
                (char_folder_id,),
            ).fetchall()]
            media_ids = list(dict.fromkeys(char_media_ids + folder_media_ids))
            count = db.execute('DELETE FROM character_media WHERE character_id=?', (character_id,)).rowcount
            db.execute('DELETE FROM characters WHERE id=?', (character_id,))
            db.execute('DELETE FROM canvas_asset_copies WHERE source_key=?', ('character:' + character_id,))
            if media_ids:
                plan = media._plan(db, media_ids)
                media.apply_delete(db, plan, staged, token)
                summary = plan['summary']
                deleted_ids = [r['id'] for r in plan['rows']]
            else:
                summary = {'affected_workflows': [], 'media_groups': [], 'task_ids': []}
                deleted_ids = []
            db.execute('UPDATE media SET folder_id=NULL WHERE folder_id=?', (char_folder_id,))
            db.execute('DELETE FROM media_folders WHERE id=?', (char_folder_id,))
    except BaseException:
        media.undo_delete(staged)
        raise
    removed_files = media.finish_delete(staged)
    return {
        'deleted_id': character_id,
        'references_removed': count,
        'media_moved_to_root': 0,
        'deleted_media_ids': deleted_ids,
        'files_removed': removed_files,
        'affected_workflows': summary['affected_workflows'],
        'media_groups': summary['media_groups'],
    }


def add_images(character_id, uploads=None, data=None):
    _row(tasks.get_db(), character_id)
    if uploads is not None and (not uploads or len(uploads) > MAX_IMAGES):
        raise store.CanvasError(f'请选择1至{MAX_IMAGES}张角色图')
    sources = _resolve_sources(uploads, data)
    created_files = []
    try:
        added = []
        with store.write_transaction() as db:
            char_row = _row(db, character_id)
            char_folder_id = _ensure_character_folder(db, character_id, char_row['name'])
            rows = _media_rows(db, sources, folder_id=char_folder_id)
            current_media = _media(db, character_id)
            existing_by_id = {m['local_id']: m['role'] for m in current_media}
            existing_image_by_sha = {m['sha256']: m['local_id'] for m in current_media if m['role'] == 'image'}
            existing_voice_by_sha = {m['sha256']: m['local_id'] for m in current_media if m['role'] == 'voice'}

            # Validate ALL incoming rows before mutating any folder_id or copying files.
            plan = []
            new_rows = []
            seen_new_ids = set()
            seen_new_sha = {}
            for row in rows:
                rid = row['id']
                sha = row['sha256']
                if existing_by_id.get(rid) == 'voice' or sha in existing_voice_by_sha:
                    raise store.CanvasError('该素材已用作角色声音')
                if rid in existing_by_id:
                    plan.append(('existing', rid))
                    continue
                if sha in existing_image_by_sha:
                    plan.append(('existing', existing_image_by_sha[sha]))
                    continue
                if rid in seen_new_ids:
                    plan.append(('batch_dup', rid))
                    continue
                if sha in seen_new_sha:
                    plan.append(('batch_dup', seen_new_sha[sha]))
                    continue
                seen_new_ids.add(rid)
                seen_new_sha[sha] = rid
                new_rows.append(row)
                plan.append(('new', row))

            count = sum(1 for role in existing_by_id.values() if role == 'image')
            if count + len(new_rows) > MAX_IMAGES:
                raise store.CanvasError(f'每个角色最多{MAX_IMAGES}张图片')

            facts = {}
            for row in new_rows:
                width, height, _ = _media_facts(row, 'image')
                facts[row['id']] = (width, height)

            now = tasks.utcnow()
            placed_by_orig_id = {}
            added_ids = set()
            for tag, payload in plan:
                if tag == 'existing':
                    target_id = payload
                elif tag == 'batch_dup':
                    target_id = placed_by_orig_id[payload]
                else:
                    row = payload
                    width, height = facts[row['id']]
                    placed = _place_for_character(db, character_id, row, char_folder_id, created_files)
                    target_id = placed['id']
                    placed_by_orig_id[row['id']] = target_id
                    db.execute('INSERT INTO character_media VALUES (?,?,?,?,?,?,?,?)',
                               (character_id, target_id, 'image', count, width, height, None, now))
                    count += 1
                if target_id not in added_ids:
                    added_ids.add(target_id)
                    added.append(image_public(get_media(character_id, target_id)))
            if new_rows:
                _touch(db, character_id)
        created_files.clear()
    except BaseException:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise
    finally:
        _discard(sources)
    return get_character(character_id), added


def delete_image(character_id, local_id):
    """Remove the reference and move the media item back to library root; the media item is kept."""
    with store.write_transaction() as db:
        local_id = get_media(character_id, local_id, 'image')['local_id']
        char_folder_id = media.character_folder_id(character_id)
        db.execute('DELETE FROM character_media WHERE character_id=? AND local_id=?', (character_id, local_id))
        db.execute('UPDATE media SET folder_id=NULL WHERE id=? AND folder_id=?', (local_id, char_folder_id))
        _renumber(db, character_id)
        _touch(db, character_id)
    return get_character(character_id)


def set_voice(character_id, upload=None, data=None):
    _row(tasks.get_db(), character_id)
    sources = _resolve_sources([upload] if upload is not None else None, data)
    created_files = []
    try:
        with store.write_transaction() as db:
            char_row = _row(db, character_id)
            char_folder_id = _ensure_character_folder(db, character_id, char_row['name'])
            row = _media_rows(db, sources, folder_id=char_folder_id)[0]
            current = _media(db, character_id, 'voice')
            if not (current and (current[0]['local_id'] == row['id'] or current[0]['sha256'] == row['sha256'])):
                if db.execute("SELECT 1 FROM character_media WHERE character_id=? AND local_id=? AND role='image'",
                              (character_id, row['id'])).fetchone():
                    raise store.CanvasError('该素材已用作角色图')
                _, _, duration = _media_facts(row, 'voice')
                placed = _place_for_character(db, character_id, row, char_folder_id, created_files)
                if current:
                    old_voice_id = current[0]['local_id']
                    db.execute("DELETE FROM character_media WHERE character_id=? AND role='voice'", (character_id,))
                    if old_voice_id != placed['id']:
                        db.execute('UPDATE media SET folder_id=NULL WHERE id=? AND folder_id=?', (old_voice_id, char_folder_id))
                db.execute('INSERT INTO character_media VALUES (?,?,?,?,?,?,?,?)',
                           (character_id, placed['id'], 'voice', 0, None, None, duration, tasks.utcnow()))
                _touch(db, character_id)
        created_files.clear()
    except BaseException:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise
    finally:
        _discard(sources)
    return get_character(character_id)


def import_to_workflow(workflow_id, data):
    """Media node assets for selected character images (and optionally its voice).

    The canvas references the library items directly (LIBRARY-GLOBAL); nothing is copied,
    so repeating the call returns the same ids.
    """
    from canvas_media_refs import node_asset
    if set(data) - {'character_id', 'image_ids', 'voice'}:
        raise store.CanvasError('角色导入字段无效')
    store.workflow(workflow_id)
    character_id = data.get('character_id')
    db = tasks.get_db()
    _row(db, character_id)
    image_ids = data.get('image_ids')
    if image_ids is None:
        image_ids = [m['local_id'] for m in _media(db, character_id, 'image')]
    if not isinstance(image_ids, list) or len(image_ids) > MAX_IMAGES or any(not isinstance(i, str) for i in image_ids):
        raise store.CanvasError(f'image_ids 须为最多{MAX_IMAGES}个角色图编号')
    image_ids = list(dict.fromkeys(image_ids))
    include_voice = data.get('voice', False)
    if type(include_voice) is not bool:
        raise store.CanvasError('voice 必须为布尔值')
    rows = {i: get_media(character_id, i, 'image') for i in image_ids}
    voice = None
    if include_voice:
        voices = _media(db, character_id, 'voice')
        if not voices:
            raise store.CanvasError('该角色没有参考音频', 404)
        voice = voices[0]
    for row in list(rows.values()) + ([voice] if voice else []):
        media.media_path(row)  # the file must still be readable
    mapping = {i: node_asset(media.get_media(row['local_id'])) for i, row in rows.items()}
    return {'success': True, 'character_id': character_id, 'assets': [mapping[i] for i in image_ids],
            'mapping': mapping, 'voice': node_asset(media.get_media(voice['local_id'])) if voice else None}


# ---- routes -----------------------------------------------------------------------

def register_routes(bp, body):
    from flask import jsonify, request, send_file
    from local_delete import require_same_origin

    def multipart():
        return (request.mimetype or '').startswith('multipart/')

    @bp.route('/api/characters', methods=['GET', 'POST'])
    def character_api_characters():
        if request.method == 'GET':
            return jsonify(success=True, characters=list_characters(request.args.get('asset_ref')))
        return jsonify(success=True, character=create_character(body())), 201

    @bp.route('/api/characters/<character_id>', methods=['GET', 'PATCH', 'DELETE'])
    def character_api_character(character_id):
        if request.method == 'GET':
            return jsonify(success=True, character=get_character(character_id))
        if request.method == 'PATCH':
            return jsonify(success=True, character=update_character(character_id, body()))
        require_same_origin(request, json_body=False)
        raw_q = request.args.get('delete_media')
        delete_media_flag = False
        if raw_q is not None:
            norm = raw_q.strip().lower()
            if norm in ('1', 'true', 'yes'):
                delete_media_flag = True
            elif norm in ('0', 'false', ''):
                delete_media_flag = False
            else:
                raise store.CanvasError('delete_media 参数无效', 400)
        if request.is_json and request.content_length != 0:
            data = body()
            if set(data) - {'delete_media'}:
                raise store.CanvasError('删除参数字段无效', 400)
            if 'delete_media' in data:
                if type(data['delete_media']) is not bool:
                    raise store.CanvasError('delete_media 必须为布尔值', 400)
                delete_media_flag = data['delete_media']
        return jsonify(success=True, **delete_character(character_id, delete_media=delete_media_flag))

    @bp.get('/api/characters/<character_id>/delete-preview')
    def character_api_delete_preview(character_id):
        return jsonify(success=True, **delete_character_preview(character_id))

    @bp.post('/api/characters/<character_id>/images')
    def character_api_images(character_id):
        if multipart():
            character, added = add_images(character_id, uploads=request.files.getlist('file'))
        else:
            character, added = add_images(character_id, data=body())
        return jsonify(success=True, character=character, images=added), 201

    @bp.delete('/api/characters/<character_id>/images/<asset_id>')
    def character_api_image(character_id, asset_id):
        require_same_origin(request, json_body=False)
        return jsonify(success=True, character=delete_image(character_id, asset_id))

    @bp.post('/api/characters/<character_id>/voice-audio')
    def character_api_voice_audio(character_id):
        if multipart():
            upload = request.files.get('file')
            if upload is None:
                raise store.CanvasError('请选择参考音频文件')
            character = set_voice(character_id, upload=upload)
        else:
            character = set_voice(character_id, data=body())
        return jsonify(success=True, character=character, voice=character['voice']), 201

    @bp.get('/api/characters/<character_id>/assets/<asset_id>')
    def character_api_read_asset(character_id, asset_id):
        row = get_media(character_id, asset_id)
        response = send_file(media.media_path(row), mimetype=row['mime_type'], download_name=row['name'], conditional=True)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'private, no-cache'
        return response

    @bp.get('/api/characters/<character_id>/assets/<asset_id>/thumbnail')
    def character_api_thumbnail(character_id, asset_id):
        from PIL import ImageOps
        row = get_media(character_id, asset_id, 'image')
        output = io.BytesIO()
        try:
            with Image.open(media.media_path(row)) as original:
                original.draft('RGB', (320, 320))
                picture = ImageOps.exif_transpose(original)
                picture.thumbnail((320, 320))
                picture.convert('RGB').save(output, format='WEBP', quality=75)
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            raise store.CanvasError('缩略图不可用', 409) from error
        output.seek(0)
        response = send_file(output, mimetype='image/webp')
        response.headers['Cache-Control'] = 'private, max-age=60'
        return response

    @bp.post('/api/canvas/workflows/<workflow_id>/character-assets')
    def character_api_character_assets(workflow_id):
        return jsonify(import_to_workflow(workflow_id, body()))
