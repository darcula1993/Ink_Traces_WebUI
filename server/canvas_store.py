"""Canvas workflows and durable media, independent from task/workspace cleanup."""
from contextlib import contextmanager
from contextvars import ContextVar

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import uuid

from PIL import Image
import tasks as task_db

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_ASSET_BYTES = 100 * 1024 * 1024
ID = re.compile(r'^[A-Za-z0-9_-]{1,80}$')


class CanvasError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def init_canvas_db():
    db = task_db.get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS canvas_projects (
            id TEXT PRIMARY KEY, title TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS canvas_workflows (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL, document TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES canvas_projects(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS canvas_assets (
            id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, name TEXT NOT NULL,
            mime_type TEXT NOT NULL, kind TEXT NOT NULL, sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL, filename TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(workflow_id, sha256),
            FOREIGN KEY(workflow_id) REFERENCES canvas_workflows(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_canvas_workflows_updated ON canvas_workflows(project_id, updated_at DESC);
    ''')
    db.commit()
    from canvas_library import init_library_db
    init_library_db()
    from canvas_project_settings import init_settings_db
    init_settings_db()
    from canvas_cleanup import init_cleanup_db
    init_cleanup_db()
    from canvas_library_folders import initialize_existing_defaults
    initialize_existing_defaults()
    from canvas_catalog import init_catalog_db
    init_catalog_db()
    from canvas_writeback import init_writeback_db
    init_writeback_db()


_transaction_files = ContextVar('canvas_transaction_files', default=None)


@contextmanager
def write_transaction():
    """Serialize scope validation and mutation without committing a caller's lock."""
    db = task_db.get_db()
    if db.in_transaction:
        yield db
    else:
        files = []
        token = _transaction_files.set((db, files))
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        except BaseException:
            # The SQLite context has rolled back. Only reclaim files created by
            # this transaction; deduplicated pre-existing files are never listed.
            for table, asset_id, path in reversed(files):
                if db.execute(f'SELECT 1 FROM {table} WHERE id=?', (asset_id,)).fetchone() is None:
                    path.unlink(missing_ok=True)
            raise
        finally:
            _transaction_files.reset(token)


def get_project(project_id):
    from canvas_cleanup import is_deleted
    if is_deleted('project', project_id):
        raise CanvasError('项目不存在', 404)
    row = task_db.get_db().execute('SELECT * FROM canvas_projects WHERE id=?', (project_id,)).fetchone()
    if row is None:
        raise CanvasError('项目不存在', 404)
    return dict(row)


def list_projects():
    from canvas_cleanup import is_deleted
    return [dict(row) for row in task_db.get_db().execute('SELECT * FROM canvas_projects ORDER BY updated_at DESC,id') if not is_deleted('project', row['id'])]


def create_project(title):
    project_id, now = uuid.uuid4().hex, task_db.utcnow()
    db = task_db.get_db()
    with write_transaction():
        db.execute('INSERT INTO canvas_projects VALUES (?,?,?,?)', (project_id, title_value(title), now, now))
        from canvas_library_folders import ensure_default_folders
        ensure_default_folders(project_id)
    return get_project(project_id)


def rename_project(project_id, title):
    get_project(project_id)
    db = task_db.get_db()
    with write_transaction():
        get_project(project_id)
        db.execute('UPDATE canvas_projects SET title=?,updated_at=? WHERE id=?',
                   (title_value(title), task_db.utcnow(), project_id))
    return get_project(project_id)


def asset_root():
    root = Path(os.environ.get('NANOBANANA_CANVAS_ASSET_DIR',
                str(Path(task_db.DB_PATH).absolute().parent / 'canvas_assets'))).absolute()
    if root.resolve() != root:
        raise CanvasError('画布素材目录不可经过符号链接', 400)
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_document():
    return {'version': 1, 'nodes': [], 'edges': [], 'viewport': {'x': 0, 'y': 0, 'zoom': 1}}


def workflow(workflow_id):
    from canvas_cleanup import is_deleted
    if is_deleted('workflow', workflow_id):
        raise CanvasError('画布不存在', 404)
    row = task_db.get_db().execute('SELECT * FROM canvas_workflows WHERE id=?', (workflow_id,)).fetchone()
    if row is None:
        raise CanvasError('画布不存在', 404)
    get_project(row['project_id'])
    result = dict(row)
    result['document'] = json.loads(result['document'])
    return result


def list_workflows(project_id):
    from canvas_cleanup import is_deleted
    get_project(project_id)
    return [dict(row) for row in task_db.get_db().execute(
        'SELECT id,project_id,title,revision,created_at,updated_at FROM canvas_workflows WHERE project_id=? ORDER BY updated_at DESC,id', (project_id,)) if not is_deleted('workflow', row['id'])]


def title_value(title):
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise CanvasError('画布标题须为1至120个字符')
    return title.strip()


def _number(value, minimum=-1000000, maximum=1000000):
    return type(value) in (float, int) and minimum <= value <= maximum and math.isfinite(value)


# Prompt reference mentions use the skill-style @图片N/@视频N/@音频N labels (user 2026-11-14).
MENTION_KEY = re.compile(r'@(?:图片|视频|音频)[1-9][0-9]*')
LEGACY_MENTION_KEY = re.compile(r'\[(?:Image|Video|Audio)[1-9][0-9]*\]')
# Canvas audio node options mirror the Cupsy Seed Audio 1.0 values accepted by /api/audio/generate.
AUDIO_FIELDS = {'speaker', 'output_format', 'sample_rate', 'enable_subtitle'}
AUDIO_SPEAKERS = ('vivi', 'mindy', 'kian', 'jess', 'opal')
AUDIO_FORMATS = ('mp3', 'wav', 'ogg_opus')
AUDIO_SAMPLE_RATES = (8000, 16000, 24000, 32000, 44100, 48000)


def _validate_audio_field(key, value):
    if key == 'speaker':
        if value not in (None, '') and (not isinstance(value, str) or value not in AUDIO_SPEAKERS):
            raise CanvasError('预设声线仅支持自动或 ' + '、'.join(AUDIO_SPEAKERS))
    elif key == 'output_format':
        if not isinstance(value, str) or value not in AUDIO_FORMATS:
            raise CanvasError('音频格式仅支持 MP3、WAV 或 OGG Opus')
    elif key == 'sample_rate':
        if type(value) is not int or value not in AUDIO_SAMPLE_RATES:
            raise CanvasError('音频采样率仅支持 8000、16000、24000、32000、44100 或 48000')
    elif key == 'enable_subtitle' and type(value) is not bool:
        raise CanvasError('字幕开关必须为布尔值')


def validate_document(document, workflow_id):
    if not isinstance(document, dict) or type(document.get('version')) is not int or document['version'] != 1:
        raise CanvasError('不支持的画布文档版本')
    try:
        encoded = json.dumps(document, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise CanvasError('无效画布文档')
    if len(encoded.encode('utf-8')) > MAX_DOCUMENT_BYTES:
        raise CanvasError('画布文档过大', 413)
    legacy_dropped = False
    nodes, edges, viewport = document.get('nodes'), document.get('edges'), document.get('viewport')
    if not isinstance(nodes, list) or len(nodes) > 500 or not isinstance(edges, list) or len(edges) > 2000:
        raise CanvasError('画布最多500个节点和2000条连线')
    if not isinstance(viewport, dict) or set(viewport) != {'x', 'y', 'zoom'} or not all(_number(viewport.get(k)) for k in ('x', 'y')) or not _number(viewport.get('zoom'), .1, 4):
        raise CanvasError('无效画布视口')
    if set(document) - {'version', 'nodes', 'edges', 'viewport', 'groups'}:
        raise CanvasError('未知画布文档字段')
    registered = {row['id']: asset_public(dict(row)) for row in task_db.get_db().execute(
        'SELECT * FROM canvas_assets WHERE workflow_id=?', (workflow_id,))}

    def validate_asset(asset):
        if not isinstance(asset, dict) or not isinstance(asset.get('id'), str):
            raise CanvasError('素材引用无效')
        expected = registered.get(asset['id'])
        if expected is None or any(asset.get(key) != expected[key] for key in ('url', 'name', 'mime_type', 'kind')):
            raise CanvasError('素材必须引用本画布的持久素材')
        if set(asset) - set(expected) or ('size_bytes' in asset and asset['size_bytes'] != expected['size_bytes']):
            raise CanvasError('素材引用字段无效')

    seen = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get('id'), str) or not ID.fullmatch(node['id']) or node['id'] in seen:
            raise CanvasError('节点ID无效或重复')
        seen.add(node['id'])
        if set(node) - {'id', 'type', 'title', 'x', 'y', 'text', 'params', 'asset', 'candidates', 'selectedCandidateId', 'task', 'referenceAssets', 'referenceGroups', 'rating', 'referenceOrder', 'providerSelection', 'referenceMentions', 'upstreamStale'}:
            raise CanvasError('未知节点字段')
        if type(node.get('rating', 0)) is not int or not 0 <= node.get('rating', 0) <= 5:
            raise CanvasError('节点评级必须为0至5的整数')
        if node.get('type') not in ('text', 'image', 'video', 'audio', 'asset'):
            raise CanvasError('未知节点类型')
        if 'upstreamStale' in node:
            if node['type'] not in ('image', 'video', 'audio'):
                raise CanvasError('仅图像、视频、音频生成节点可标记上游已变更')
            if type(node['upstreamStale']) is not bool:
                raise CanvasError('上游变更标记必须为布尔值')
        order = node.get('referenceOrder', [])
        if not isinstance(order, list) or len(order) > 600 or any(not isinstance(i, str) or not re.fullmatch(r'[0-9a-f]{32}', i) for i in order) or len(set(order)) != len(order):
            raise CanvasError('参考素材排序须为最多600个不重复的素材编号')
        mentions = node.get('referenceMentions', {})
        if isinstance(mentions, dict) and any(isinstance(k, str) and LEGACY_MENTION_KEY.fullmatch(k) for k in mentions):
            # User 2026-11-14: legacy [Image1] keys are not migrated; drop them so old canvases stay savable.
            mentions = {k: v for k, v in mentions.items() if not (isinstance(k, str) and LEGACY_MENTION_KEY.fullmatch(k))}
            node['referenceMentions'] = mentions
            legacy_dropped = True
        if not isinstance(mentions, dict) or len(mentions) > 600 or any(not isinstance(k, str) or not MENTION_KEY.fullmatch(k) or not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{32}', v) for k, v in mentions.items()):
            raise CanvasError('参考素材提及须为最多600项的有效标签与素材编号映射')
        if node['type'] == 'asset' and mentions:
            raise CanvasError('素材节点不能包含参考素材提及')
        if node['type'] == 'asset' and order:
            raise CanvasError('素材节点不能包含参考素材排序')
        from canvas_project_settings import validate_node_selection
        validate_node_selection(node['type'], node.get('providerSelection'))
        if not all(_number(node.get(k)) for k in ('x', 'y')):
            raise CanvasError('节点坐标无效')
        for key, maximum in (('title', 240), ('text', 50000)):
            if not isinstance(node.get(key, ''), str) or len(node.get(key, '')) > maximum:
                raise CanvasError('节点标题或文本无效')
        params = node.get('params', {})
        from canvas_image_params import IMAGE_FIELDS, validate_field
        if not isinstance(params, dict) or set(params) - IMAGE_FIELDS - AUDIO_FIELDS - {'provider', 'model', 'ratio', 'resolution', 'duration', 'profile_id', 'profile_revision', 'video_mode', 'first_frame', 'last_frame', 'omni_reference_task_type', 'generate_audio'}:
            raise CanvasError('节点参数无效')
        for key, value in params.items():
            if node['type'] == 'audio' and key in AUDIO_FIELDS:
                _validate_audio_field(key, value)
            elif key in AUDIO_FIELDS - IMAGE_FIELDS:
                raise CanvasError('此参数仅适用于音频生成节点')
            elif key in IMAGE_FIELDS:
                validate_field(node['type'], key, value)
            elif key == 'generate_audio':
                if type(value) is not bool:
                    raise CanvasError('输出音频开关必须为布尔值')
            elif key == 'video_mode':
                if value not in ('reference', 'keyframe'): raise CanvasError('视频模式无效')
            elif key == 'omni_reference_task_type':
                if value not in ('auto', 'reference', 'edit', 'extend'): raise CanvasError('任务类型无效')
            elif key == 'profile_id':
                if value not in (None, '') and (not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value)):
                    raise CanvasError('接口配置ID无效')
            elif key == 'profile_revision':
                if value is not None and (type(value) is not int or value < 1):
                    raise CanvasError('接口配置版本无效')
            elif key == 'duration':
                auto_video = node['type'] == 'video' and _number(value, -1, -1)
                if value not in (None, '') and not (auto_video or _number(value, 0, 3600) or isinstance(value, str) and len(value) <= 16):
                    raise CanvasError('时长参数无效')
            elif value is not None and (not isinstance(value, str) or len(value) > 240):
                raise CanvasError('节点参数无效')
        if node.get('asset') is not None:
            validate_asset(node['asset'])
            if node['type'] not in ('text', 'asset') and node['asset']['kind'] != node['type']:
                raise CanvasError('节点输出素材类型不匹配')
        candidates = node.get('candidates', [])
        if not isinstance(candidates, list) or len(candidates) > 100:
            raise CanvasError('候选素材最多100个')
        for candidate in candidates:
            validate_asset(candidate)
            if node['type'] not in ('text', 'asset') and candidate['kind'] != node['type']:
                raise CanvasError('候选素材类型与节点不匹配')
        references = node.get('referenceAssets', [])
        if not isinstance(references, list) or len(references) > 100:
            raise CanvasError('参考素材最多100个')
        for reference in references:
            validate_asset(reference)
        groups = node.get('referenceGroups', [])
        if not isinstance(groups, list) or len(groups) > 30:
            raise CanvasError('参考素材组最多30个')
        reference_ids = {a['id'] for a in references}
        group_ids = set()
        for group in groups:
            if not isinstance(group, dict) or set(group) != {'id', 'title', 'asset_ids'} or not isinstance(group['id'], str) or not ID.fullmatch(group['id']) or group['id'] in group_ids:
                raise CanvasError('参考素材组无效')
            group_ids.add(group['id'])
            title_value(group['title'])
            ids = group['asset_ids']
            if not isinstance(ids, list) or not ids or len(ids) > 100 or any(not isinstance(i, str) or i not in reference_ids for i in ids):
                raise CanvasError('素材组必须引用节点内已有参考素材')
        selected = node.get('selectedCandidateId')
        if selected is not None and (not isinstance(selected, str) or selected not in {a['id'] for a in candidates}):
            raise CanvasError('选定素材必须属于候选列表')
        asset = node.get('asset')
        if (asset is not None and selected != asset['id']) or (selected is not None and asset is None):
            raise CanvasError('节点输出必须与选定候选一致')
        if node['type'] == 'asset':
            if asset is None or asset['kind'] not in ('image', 'video', 'audio'):
                raise CanvasError('素材节点必须绑定本画布的图像、视频或音频素材')
            if params or node.get('task') is not None or references or groups:
                raise CanvasError('素材节点不能包含生成参数、任务或参考输入')
            if any(candidate['kind'] != asset['kind'] for candidate in candidates):
                raise CanvasError('素材节点历史版本必须为相同媒体类型')
            if len({candidate['id'] for candidate in candidates}) != len(candidates):
                raise CanvasError('素材节点历史版本不能重复')
            if asset['kind'] != 'image' and (len(candidates) != 1 or candidates[0]['id'] != asset['id']):
                raise CanvasError('视频或音频素材节点只能绑定一个素材')
        task = node.get('task')
        if task is not None:
            if not isinstance(task, dict) or set(task) - {'id', 'status', 'error'}:
                raise CanvasError('任务引用无效')
            if task.get('id') is not None and (type(task['id']) is not int or task['id'] < 1):
                raise CanvasError('任务ID必须为正整数')
            if task.get('status') not in ('submitting', 'unknown', 'preparing', 'pending', 'processing', 'cancel_requested', 'succeeded', 'failed', 'cancelled'):
                raise CanvasError('任务状态无效')
            if task.get('error') is not None and (not isinstance(task['error'], str) or len(task['error']) > 4096):
                raise CanvasError('任务错误信息无效')
    groups = document.get('groups', [])
    if not isinstance(groups, list) or len(groups) > 500:
        raise CanvasError('画布最多500个节点组')
    group_ids, grouped_nodes = set(), set()
    nodes_by_id = {node['id']: node for node in nodes}
    for group in groups:
        if not isinstance(group, dict) or not {'id', 'title', 'nodeIds'} <= set(group) or set(group) - {'id', 'title', 'nodeIds', 'keyframeNodeId', 'color'}:
            raise CanvasError('节点组字段无效')
        if 'color' in group and (not isinstance(group['color'], str) or group['color'] not in {'green', 'cyan', 'blue', 'purple', 'amber', 'rose'}):
            raise CanvasError('节点组颜色无效')
        ident, title, members = group['id'], group['title'], group['nodeIds']
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident in group_ids:
            raise CanvasError('节点组ID无效或重复')
        if not isinstance(title, str) or not title.strip() or len(title) > 100:
            raise CanvasError('节点组标题须为1至100个字符')
        if not isinstance(members, list) or not members or len(members) > 500:
            raise CanvasError('节点组须包含1至500个节点')
        for member in members:
            if not isinstance(member, str) or member not in seen or member in grouped_nodes:
                raise CanvasError('节点组成员须存在且每个节点只能归属一个组')
            grouped_nodes.add(member)
        if 'keyframeNodeId' in group:
            owner = group['keyframeNodeId']
            video = nodes_by_id.get(owner) if isinstance(owner, str) else None
            if video is None or owner not in members or video['type'] != 'video' or video.get('params', {}).get('video_mode') != 'keyframe':
                raise CanvasError('首尾帧节点组须指向组内首尾帧模式的视频节点')
        group_ids.add(ident)
    edge_ids, pairs = set(), set()
    types = {node['id']: node['type'] for node in nodes}
    source_types = {node['id']: node['asset']['kind'] if node['type'] == 'asset' else node['type'] for node in nodes}
    targets = {'text': {'image', 'video', 'audio'}, 'image': {'image', 'video', 'audio'},
               'video': {'video'}, 'audio': {'video', 'audio'}}
    adjacency = {node_id: [] for node_id in seen}
    indegree = {node_id: 0 for node_id in seen}
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {'id', 'source', 'target'} or not isinstance(edge.get('id'), str) or not ID.fullmatch(edge['id']) or edge['id'] in edge_ids:
            raise CanvasError('连线ID无效或重复')
        edge_ids.add(edge['id'])
        if not isinstance(edge.get('source'), str) or not isinstance(edge.get('target'), str) or edge['source'] not in seen or edge['target'] not in seen:
            raise CanvasError('连线必须连接已有节点')
        source, target = edge['source'], edge['target']
        if source == target or (source, target) in pairs:
            raise CanvasError('不能连接自身或重复连接两个节点')
        if types[target] == 'asset' or types[target] not in targets[source_types[source]]:
            raise CanvasError('不支持此节点类型连接')
        pairs.add((source, target))
        adjacency[source].append(target)
        indegree[target] += 1
    queue = [node_id for node_id, count in indegree.items() if not count]
    visited = 0
    while queue:
        source = queue.pop()
        visited += 1
        for target in adjacency[source]:
            indegree[target] -= 1
            if not indegree[target]:
                queue.append(target)
    if visited != len(nodes):
        raise CanvasError('节点连接不能形成循环')
    return json.dumps(document, ensure_ascii=False, allow_nan=False) if legacy_dropped else encoded


def create_workflow(project_id, title, document=None):
    get_project(project_id)
    workflow_id = uuid.uuid4().hex
    title = title_value(title)
    now = task_db.utcnow()
    db = task_db.get_db()
    with write_transaction():
        get_project(project_id)
        encoded = validate_document(default_document() if document is None else document, workflow_id)
        db.execute('INSERT INTO canvas_workflows VALUES (?,?,?,?,1,?,?)', (workflow_id, project_id, title, encoded, now, now))
        db.execute('UPDATE canvas_projects SET updated_at=? WHERE id=?', (now, project_id))
    return workflow(workflow_id)


def update_workflow(workflow_id, title, document, revision, with_merge=False):
    """Save a document. A stale base whose later revisions are all server
    write-backs (canvas_writebacks) is merged instead of rejected; with
    ``with_merge`` the result is (workflow, merged)."""
    workflow(workflow_id)
    if type(revision) is not int or revision < 1:
        raise CanvasError('revision 必须为正整数')
    title = title_value(title)
    db = task_db.get_db()
    merged = False
    with write_transaction():
        # A stale editor gets the conflict flow even when its document references
        # assets a newer revision removed (e.g. local material deletion).
        current = workflow(workflow_id)['revision']
        if current != revision:
            from canvas_writeback import merge_stale_save
            document = merge_stale_save(db, workflow_id, revision, current, document)
            if document is None:
                raise CanvasError('画布已被其他窗口修改，请重新载入后重试', 409)
            merged, revision = True, current
        encoded = validate_document(document, workflow_id)
        changed = db.execute('''UPDATE canvas_workflows SET title=?, document=?,revision=revision+1,updated_at=?
                                WHERE id=? AND revision=?''',
                             (title, encoded, task_db.utcnow(), workflow_id, revision)).rowcount
        if changed:
            db.execute('UPDATE canvas_projects SET updated_at=? WHERE id=(SELECT project_id FROM canvas_workflows WHERE id=?)', (task_db.utcnow(), workflow_id))
    if not changed:
        raise CanvasError('画布已被其他窗口修改，请重新载入后重试', 409)
    return (workflow(workflow_id), merged) if with_merge else workflow(workflow_id)


def asset_public(row):
    library = 'project_id' in row
    owner_key = 'project_id' if library else 'workflow_id'
    resource = 'projects' if library else 'workflows'
    return {**{key: row[key] for key in ('id', 'name', 'mime_type', 'kind', 'size_bytes')},
            'url': f"/api/canvas/{resource}/{row[owner_key]}/assets/{row['id']}"}


def get_asset(owner_id, asset_id, library=False, allow_archived=False):
    if not allow_archived:
        get_project(owner_id) if library else workflow(owner_id)
    if library:
        from canvas_cleanup import is_library_asset_deleted
        if is_library_asset_deleted(asset_id):
            raise CanvasError('素材已清理', 404)
    table = 'canvas_library_assets' if library else 'canvas_assets'
    owner_key = 'project_id' if library else 'workflow_id'
    row = task_db.get_db().execute(f'SELECT * FROM {table} WHERE {owner_key}=? AND id=?',
                                 (owner_id, asset_id)).fetchone()
    if row is None:
        raise CanvasError('素材不存在', 404)
    return dict(row)


def asset_path(row):
    root = asset_root()
    directory = root / 'library' / row['project_id'] if 'project_id' in row else root / row['workflow_id']
    path = directory / row['filename']
    if path.resolve() != path or not path.is_relative_to(root) or not path.is_file():
        raise CanvasError('素材文件不存在', 404)
    return path


def _detect_media(path):
    with path.open('rb') as handle:
        head = handle.read(64)
    try:
        with Image.open(path) as picture:
            fmt = picture.format
            if fmt not in ('PNG', 'JPEG', 'WEBP', 'GIF'):
                raise CanvasError('不支持的图片格式')
            picture.verify()
        return {'PNG': ('image/png', '.png'), 'JPEG': ('image/jpeg', '.jpg'),
                'WEBP': ('image/webp', '.webp'), 'GIF': ('image/gif', '.gif')}[fmt]
    except (OSError, SyntaxError, Image.DecompressionBombError):
        pass
    media = None
    if head[:4] == b'RIFF' and head[8:12] == b'WAVE':
        media = ('audio/wav', '.wav', {'wav'})
    elif head[:4] == b'OggS':
        media = ('audio/ogg', '.ogg', {'ogg'})
    elif head[:3] == b'ID3' or (len(head) >= 2 and head[0] == 255 and head[1] & 0xe0 == 0xe0):
        media = ('audio/mpeg', '.mp3', {'mp3'})
    elif len(head) >= 12 and head[4:8] == b'ftyp':
        media = ('video/mp4', '.mp4', {'mov', 'mp4'})
    elif head[:4] == b'\x1aE\xdf\xa3':
        media = ('video/webm', '.webm', {'matroska', 'webm'})
    if media is None:
        raise CanvasError('仅支持 PNG/JPEG/WebP/GIF、MP4/WebM、MP3/WAV/OGG 媒体')
    # Inspect the actual container and streams, not the client-provided MIME or filename.
    # Network protocols are disabled; probing is bounded and never invokes a shell.
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-protocol_whitelist', 'file',
             '-probesize', '8000000', '-analyzeduration', '2000000',
             '-show_entries', 'stream=codec_type:format=format_name', '-of', 'json', str(path)],
            capture_output=True, timeout=10, check=False)
    except FileNotFoundError:
        raise CanvasError('服务缺少音视频格式检查工具 ffprobe', 503)
    except subprocess.TimeoutExpired:
        raise CanvasError('媒体格式检查超时')
    try:
        probe = json.loads(result.stdout)
        formats = set(probe.get('format', {}).get('format_name', '').split(','))
        stream_types = {item.get('codec_type') for item in probe.get('streams', [])}
    except (ValueError, TypeError, AttributeError):
        raise CanvasError('音视频文件格式无效')
    if result.returncode or not (formats & media[2]) or media[0].split('/')[0] not in stream_types:
        raise CanvasError('音视频文件格式无效')
    return media[:2]


def _copy_provenance(db, asset_id, copy_source, created):
    """Canvas copy provenance (see local_delete): only assets produced by a copy are copies.

    - new asset from a copy: record the source;
    - dedup hit from a copy: add the source only if the hit is already a pure copy
      (it then survives until all of its copy sources are deleted); an independent
      asset (direct upload, task import) never becomes a copy;
    - dedup hit from a non-copy save: the asset gains an independent identity, so
      its copy records are dropped and deleting a former source no longer affects it.
    """
    if copy_source == 'workflow:' + asset_id:
        return  # re-copying an asset onto itself changes nothing
    if copy_source is not None:
        if created or db.execute('SELECT 1 FROM canvas_asset_copies WHERE asset_id=?', (asset_id,)).fetchone():
            db.execute('INSERT OR IGNORE INTO canvas_asset_copies VALUES (?,?,?)', (asset_id, copy_source, task_db.utcnow()))
    elif not created:
        db.execute('DELETE FROM canvas_asset_copies WHERE asset_id=?', (asset_id,))


def save_asset(workflow_id, stream, name, library=False, copy_source=None):
    """Store a durable asset. ``copy_source`` (catalog key) marks a canvas copy."""
    if library and copy_source is not None:
        raise ValueError('copy_source only applies to canvas assets')
    if library:
        get_project(workflow_id)
    else:
        workflow(workflow_id)
    table = 'canvas_library_assets' if library else 'canvas_assets'
    owner_key = 'project_id' if library else 'workflow_id'
    if not isinstance(name, str) or not name or len(name) > 240 or '/' in name or '\\' in name or any(ord(c) < 32 for c in name):
        raise CanvasError('无效素材文件名')
    directory = asset_root() / 'library' / workflow_id if library else asset_root() / workflow_id
    if directory.resolve() != directory:
        raise CanvasError('无效素材目录')
    directory.mkdir(parents=True, exist_ok=True)
    asset_id = uuid.uuid4().hex
    temporary = directory / f'{asset_id}.tmp'
    size, digest = 0, hashlib.sha256()
    target = None
    try:
        with temporary.open('xb') as handle:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ASSET_BYTES:
                    raise CanvasError('素材不得超过100MiB', 413)
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if not size:
            raise CanvasError('素材不能为空')
        mime, extension = _detect_media(temporary)
        checksum = digest.hexdigest()
        db = task_db.get_db()
        with write_transaction():
            get_project(workflow_id) if library else workflow(workflow_id)
            existing = db.execute(f'SELECT * FROM {table} WHERE {owner_key}=? AND sha256=?', (workflow_id, checksum)).fetchone()
            if existing:
                current = get_asset(workflow_id, existing['id'], library=library)
                asset_path(current)
                if not library:
                    _copy_provenance(db, existing['id'], copy_source, False)
                return asset_public(current)
            target = directory / (asset_id + extension)
            os.replace(temporary, target)
            journal = _transaction_files.get()
            if journal is not None and journal[0] is db:
                journal[1].append((table, asset_id, target))
            db.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?)',
                       (asset_id, workflow_id, name, mime, mime.split('/')[0], checksum, size, target.name, task_db.utcnow()))
            if not library:
                _copy_provenance(db, asset_id, copy_source, True)
            result = asset_public(get_asset(workflow_id, asset_id, library=library))
        return result
    except Exception:
        if target is not None:
            target.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
