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
import re
import sqlite3
import subprocess
import uuid

from PIL import Image

import canvas_store as store
import media_library as media
import tasks

MAX_IMAGES = 8
MAX_VOICE_SECONDS = 30.0
MAX_DESCRIPTION = 300
NAME_FORBIDDEN = re.compile(r'[\s@\[\]()（）]')
NAME_RESERVED = re.compile(r'^(图片|视频|音频)\d+$')
HEX_ID = re.compile(r'^[0-9a-f]{32}$')
VOICE_MIMES = ('audio/wav', 'audio/mpeg')


def init_characters_db():
    db = tasks.get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS characters (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
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
    db.commit()


# ---- validation -------------------------------------------------------------------

def name_value(value):
    if not isinstance(value, str):
        raise store.CanvasError('角色名须为字符串')
    name = value.strip()
    if not 1 <= len(name) <= 24:
        raise store.CanvasError('角色名须为1至24个字符')
    if NAME_FORBIDDEN.search(name) or any(ord(c) < 32 for c in name):
        raise store.CanvasError('角色名不能包含空白、@、方括号或圆括号')
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


MEDIA_SQL = '''SELECT m.*, x.name, x.mime_type, x.kind, x.relpath FROM character_media m
               JOIN media x ON x.id=m.local_id'''


def _public(row, media):
    images = sorted((m for m in media if m['role'] == 'image'), key=lambda m: (m['position'], m['created_at'], m['local_id']))
    voice = next((m for m in media if m['role'] == 'voice'), None)
    return {'id': row['id'], 'name': row['name'], 'description': row['description'],
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
    for media in db.execute(MEDIA_SQL + ' ORDER BY m.position,m.created_at,m.local_id'):
        grouped.setdefault(media['character_id'], []).append(dict(media))
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
    for position, media in enumerate(rows):
        db.execute('UPDATE character_media SET position=? WHERE character_id=? AND local_id=?', (position, character_id, media[0]))


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


def _media_rows(db, sources):
    """Inside the write transaction: register uploads/copies in the library root and load rows."""
    rows = []
    for source in sources:
        if source[0] in ('upload', 'copy'):
            media_id = media.save_upload(source[1], source[2], origin='upload')[0]['id']
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
    if set(data) - {'name', 'description'}:
        raise store.CanvasError('未知角色字段')
    name, description = name_value(data.get('name')), description_value(data.get('description'))
    ident, now = uuid.uuid4().hex, tasks.utcnow()
    try:
        with store.write_transaction() as db:
            _ensure_unique(db, name)
            db.execute('INSERT INTO characters VALUES (?,?,?,?,?,?)', (ident, name, name.casefold(), description, now, now))
    except sqlite3.IntegrityError as error:
        raise store.CanvasError('角色名已存在', 409) from error
    return get_character(ident)


def update_character(character_id, data):
    if not data or set(data) - {'name', 'description', 'voice', 'image_order'}:
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
                    changed = True
            if 'description' in data:
                description = description_value(data['description'])
                if description != row['description']:
                    db.execute('UPDATE characters SET description=? WHERE id=?', (description, character_id))
                    changed = True
            if 'voice' in data:
                current = _media(db, character_id, 'voice')
                voice = data['voice']
                if voice is None:
                    if current:
                        db.execute("DELETE FROM character_media WHERE character_id=? AND role='voice'", (character_id,))
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


def delete_character(character_id):
    """Delete the character and its references only; media items are kept."""
    with store.write_transaction() as db:
        _row(db, character_id)
        count = db.execute('DELETE FROM character_media WHERE character_id=?', (character_id,)).rowcount
        db.execute('DELETE FROM characters WHERE id=?', (character_id,))
        db.execute('DELETE FROM canvas_asset_copies WHERE source_key=?', ('character:' + character_id,))
    return {'deleted_id': character_id, 'references_removed': count}


def add_images(character_id, uploads=None, data=None):
    _row(tasks.get_db(), character_id)
    if uploads is not None and (not uploads or len(uploads) > MAX_IMAGES):
        raise store.CanvasError(f'请选择1至{MAX_IMAGES}张角色图')
    sources = _resolve_sources(uploads, data)
    try:
        added = []
        with store.write_transaction() as db:
            _row(db, character_id)
            rows = _media_rows(db, sources)
            existing = {m['local_id']: m['role'] for m in _media(db, character_id)}
            fresh = list(dict.fromkeys(r['id'] for r in rows if r['id'] not in existing))
            count = len([r for r in existing.values() if r == 'image'])
            if count + len(fresh) > MAX_IMAGES:
                raise store.CanvasError(f'每个角色最多{MAX_IMAGES}张图片')
            now = tasks.utcnow()
            for row in rows:
                if existing.get(row['id']) == 'voice':
                    raise store.CanvasError('该素材已用作角色声音')
                if row['id'] not in existing:
                    width, height, _ = _media_facts(row, 'image')
                    db.execute('INSERT INTO character_media VALUES (?,?,?,?,?,?,?,?)',
                               (character_id, row['id'], 'image', count, width, height, None, now))
                    existing[row['id']] = 'image'
                    count += 1
                if row['id'] not in {a['asset_id'] for a in added}:
                    added.append(image_public(get_media(character_id, row['id'])))
            if fresh:
                _touch(db, character_id)
        return get_character(character_id), added
    finally:
        _discard(sources)


def delete_image(character_id, local_id):
    """Remove the reference only; the media item is kept."""
    with store.write_transaction() as db:
        local_id = get_media(character_id, local_id, 'image')['local_id']
        db.execute('DELETE FROM character_media WHERE character_id=? AND local_id=?', (character_id, local_id))
        _renumber(db, character_id)
        _touch(db, character_id)
    return get_character(character_id)


def set_voice(character_id, upload=None, data=None):
    _row(tasks.get_db(), character_id)
    sources = _resolve_sources([upload] if upload is not None else None, data)
    try:
        with store.write_transaction() as db:
            _row(db, character_id)
            row = _media_rows(db, sources)[0]
            current = _media(db, character_id, 'voice')
            if current and current[0]['local_id'] == row['id']:
                return get_character(character_id)
            if db.execute("SELECT 1 FROM character_media WHERE character_id=? AND local_id=? AND role='image'",
                          (character_id, row['id'])).fetchone():
                raise store.CanvasError('该素材已用作角色图')
            _, _, duration = _media_facts(row, 'voice')
            db.execute("DELETE FROM character_media WHERE character_id=? AND role='voice'", (character_id,))
            db.execute('INSERT INTO character_media VALUES (?,?,?,?,?,?,?,?)',
                       (character_id, row['id'], 'voice', 0, None, None, duration, tasks.utcnow()))
            _touch(db, character_id)
        return get_character(character_id)
    finally:
        _discard(sources)


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
        return jsonify(success=True, **delete_character(character_id))

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
