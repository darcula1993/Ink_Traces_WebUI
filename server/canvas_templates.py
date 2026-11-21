"""Persistent structural templates for canvas node groups.

Stores only structural group definitions (relative node coordinates, node types,
titles, safe generation parameters, provider bindings, optional prompt text, and
internal edges). Built-in creative presets are never seeded; all templates are
explicitly saved by the user. Credentials, signed URLs, runtime tasks, media
outputs, and files are strictly rejected.
"""
import json
import math
import re
import uuid

import canvas_store as store
from canvas_image_params import IMAGE_FIELDS, validate_field as validate_image_field
from canvas_project_settings import validate_node_selection
import tasks as task_db

MAX_TEMPLATES = 200
MAX_TEMPLATE_NAME = 80
MAX_GROUP_TITLE = 100
MAX_NODES = 40
MAX_EDGES = 200
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_OFFSET = 100000

HEX32 = re.compile(r'^[0-9a-f]{32}$')
NODE_TYPES = ('image', 'video', 'audio', 'text')
GROUP_COLORS = {'green', 'cyan', 'blue', 'purple', 'amber', 'rose'}
TARGETS = {
    'text': {'image', 'video', 'audio'},
    'image': {'image', 'video', 'audio'},
    'video': {'video'},
    'audio': {'video', 'audio'},
}

TOP_KEYS = {'name', 'include_prompts', 'payload'}
PAYLOAD_KEYS = {'groupTitle', 'groupColor', 'nodes', 'edges'}
NODE_KEYS = {'id', 'dx', 'dy', 'type', 'title', 'params', 'providerSelection', 'text', 'size'}
SAFE_COMMON_PARAMS = {'model', 'ratio', 'resolution', 'duration', 'video_mode', 'omni_reference_task_type', 'generate_audio'}
ALLOWED_PARAMS = IMAGE_FIELDS | store.AUDIO_FIELDS | SAFE_COMMON_PARAMS

FORBIDDEN_KEY_NAMES = {
    'api_key', 'apikey', 'secret', 'secret_key', 'token', 'access_token', 'refresh_token',
    'password', 'passwd', 'authorization', 'cookie', 'credential', 'credentials',
    'private_key', 'access_key', 'signed_url', 'signedurl', 'signature',
    'task', 'asset', 'candidates', 'selectedcandidateid', 'referenceassets',
    'referencegroups', 'referenceorder', 'referencementions', 'characterrefs',
    'upstreamstale', 'file', 'files', 'base64', 'data_url', 'first_frame', 'last_frame',
}

FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----'),
    re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{8,}'),
    re.compile(r'(?i)\b(?:X-Amz-Signature|X-Tos-Signature|X-Goog-Signature|X-Signature|AWSAccessKeyId|OSSAccessKeyId)\s*='),
    re.compile(r'(?i)https?://[^\s"\']*?[?&](?:Signature|sig|token|api_key|apikey|X-Amz-Credential)='),
    re.compile(r'(?i)/api/(?:cupsy/source|upload_video|canvas/media|canvas/workflows)/'),
    re.compile(r'(?i)\bdata:(?:image|video|audio)/[A-Za-z0-9.+-]+;base64,'),
    re.compile(r'\b(?:sk-[A-Za-z0-9_\-]{16,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z\-_]{20,}|gh[pousr]_[0-9A-Za-z]{20,}|xoxb-[0-9A-Za-z\-]{10,})'),
)


def init_templates_db():
    """Idempotently create the canvas_group_templates table."""
    db = task_db.get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS canvas_group_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            include_prompts INTEGER NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_canvas_group_templates_updated
            ON canvas_group_templates(updated_at DESC);
    ''')
    db.commit()


def _number(value, minimum=-MAX_OFFSET, maximum=MAX_OFFSET):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def _has_control_chars(value, allow_newlines=False):
    allowed = {'\n', '\t', '\r'} if allow_newlines else set()
    return any(ord(ch) < 32 and ch not in allowed for ch in value)


def _scan_sensitive(value, depth=0):
    """Reject credentials, signed URLs, runtime/media fields anywhere inside the payload."""
    if depth > 20:
        raise store.CanvasError('模板结构层级过深')
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise store.CanvasError('模板字段名必须为字符串')
            lowered = key.strip().lower()
            if lowered in FORBIDDEN_KEY_NAMES or any(
                marker in lowered for marker in ('api_key', 'apikey', 'secret', 'password', 'passwd', 'private_key', 'access_key', 'signed_url', 'authorization', 'credential')
            ):
                raise store.CanvasError(f'模板不允许包含敏感或运行态字段：{key}')
            _scan_sensitive(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _scan_sensitive(item, depth + 1)
    elif isinstance(value, str):
        for pattern in FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise store.CanvasError('模板内容不允许包含凭据、签名地址或媒体数据')


def _validate_name(value):
    if not isinstance(value, str):
        raise store.CanvasError('模板名称必须为字符串')
    name = value.strip()
    if not 1 <= len(name) <= MAX_TEMPLATE_NAME:
        raise store.CanvasError(f'模板名称须为1至{MAX_TEMPLATE_NAME}个字符')
    if _has_control_chars(name):
        raise store.CanvasError('模板名称包含无效字符')
    return name


def _validate_params(node_type, params):
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise store.CanvasError('节点参数必须为对象')
    if node_type == 'text' and params:
        raise store.CanvasError('文本节点不能包含生成参数')
    extra = set(params) - ALLOWED_PARAMS
    if extra:
        raise store.CanvasError('模板包含不支持的节点参数字段')
    cleaned = {}
    for key, value in params.items():
        if node_type == 'audio' and key in store.AUDIO_FIELDS:
            store._validate_audio_field(key, value)
        elif key in store.AUDIO_FIELDS - IMAGE_FIELDS:
            raise store.CanvasError('此参数仅适用于音频生成节点')
        elif key in IMAGE_FIELDS:
            validate_image_field(node_type, key, value)
        elif key == 'generate_audio':
            if node_type != 'video' or type(value) is not bool:
                raise store.CanvasError('输出音频开关必须为布尔值')
        elif key == 'video_mode':
            if node_type != 'video' or value not in ('reference', 'keyframe'):
                raise store.CanvasError('视频模式无效')
        elif key == 'omni_reference_task_type':
            if node_type != 'video' or value not in ('auto', 'reference', 'edit', 'extend'):
                raise store.CanvasError('任务类型无效')
        elif key == 'duration':
            auto_video = node_type == 'video' and _number(value, -1, -1)
            if value not in (None, '') and not (auto_video or _number(value, 0, 3600) or (isinstance(value, str) and len(value) <= 16)):
                raise store.CanvasError('时长参数无效')
        elif value is not None and (not isinstance(value, str) or len(value) > 240):
            raise store.CanvasError('节点参数无效')
        cleaned[key] = value
    return cleaned


def validate_payload(payload, include_prompts):
    if not isinstance(payload, dict):
        raise store.CanvasError('模板内容必须为JSON对象')
    _scan_sensitive(payload)
    extra_top = set(payload) - PAYLOAD_KEYS
    if extra_top:
        raise store.CanvasError('模板内容包含不支持的顶层字段')

    group_title = payload.get('groupTitle')
    if group_title is not None:
        if not isinstance(group_title, str) or len(group_title.strip()) > MAX_GROUP_TITLE or _has_control_chars(group_title):
            raise store.CanvasError(f'节点组标题须为不超过{MAX_GROUP_TITLE}个字符的字符串')
        group_title = group_title.strip()

    group_color = payload.get('groupColor')
    if group_color is not None:
        if not isinstance(group_color, str) or group_color not in GROUP_COLORS:
            raise store.CanvasError('节点组颜色无效')

    raw_nodes = payload.get('nodes')
    if not isinstance(raw_nodes, list) or not 1 <= len(raw_nodes) <= MAX_NODES:
        raise store.CanvasError(f'模板节点数须为1至{MAX_NODES}个')

    clean_nodes = []
    id_to_index = {}
    node_types = []

    for idx, node in enumerate(raw_nodes):
        if not isinstance(node, dict):
            raise store.CanvasError('模板节点必须为对象')
        if set(node) - NODE_KEYS:
            raise store.CanvasError('模板节点包含不支持的字段')
        node_type = node.get('type')
        if not isinstance(node_type, str) or node_type not in NODE_TYPES:
            raise store.CanvasError('模板节点类型无效（仅支持 image、video、audio、text）')
        if not _number(node.get('dx')) or not _number(node.get('dy')):
            raise store.CanvasError('模板节点相对坐标 dx/dy 无效')

        local_id = node.get('id')
        if local_id is not None:
            if not isinstance(local_id, str) or not store.ID.fullmatch(local_id) or local_id in id_to_index:
                raise store.CanvasError('模板节点局部ID无效或重复')
            id_to_index[local_id] = idx

        title = node.get('title', '')
        if not isinstance(title, str) or len(title) > 240 or _has_control_chars(title):
            raise store.CanvasError('模板节点标题无效')

        text = node.get('text', '')
        if text is None:
            text = ''
        if not isinstance(text, str) or len(text) > 50000:
            raise store.CanvasError('模板节点文本无效')
        stored_text = text if include_prompts else ''

        selection = node.get('providerSelection')
        if selection is not None:
            if node_type == 'text':
                raise store.CanvasError('文本节点不能包含接口绑定')
            selection = validate_node_selection(node_type, selection)

        params = _validate_params(node_type, node.get('params'))

        size = node.get('size')
        clean_size = None
        if size is not None:
            if node_type == 'text':
                raise store.CanvasError('文本节点不能调整大小')
            if (
                not isinstance(size, dict)
                or set(size) != {'scale'}
                or type(size['scale']) not in (int, float)
                or not math.isfinite(size['scale'])
                or not 0.25 <= size['scale'] <= 4
            ):
                raise store.CanvasError('节点尺寸须为0.25至4倍的缩放值')
            clean_size = {'scale': size['scale']}

        entry = {
            'dx': round(float(node['dx']), 2) if isinstance(node['dx'], float) else node['dx'],
            'dy': round(float(node['dy']), 2) if isinstance(node['dy'], float) else node['dy'],
            'type': node_type,
            'title': title,
            'params': params,
            'providerSelection': selection,
        }
        if local_id is not None:
            entry['id'] = local_id
        if include_prompts and stored_text:
            entry['text'] = stored_text
        elif 'text' in node:
            entry['text'] = stored_text
        if clean_size is not None:
            entry['size'] = clean_size
        clean_nodes.append(entry)
        node_types.append(node_type)

    raw_edges = payload.get('edges', [])
    if not isinstance(raw_edges, list) or len(raw_edges) > MAX_EDGES:
        raise store.CanvasError(f'模板连线数不能超过{MAX_EDGES}条')

    def resolve_endpoint(ref):
        if type(ref) is int:
            if 0 <= ref < len(clean_nodes):
                return ref
            raise store.CanvasError('模板连线节点索引越界')
        if isinstance(ref, str) and ref in id_to_index:
            return id_to_index[ref]
        raise store.CanvasError('模板连线必须指向模板内已有节点')

    clean_edges = []
    seen_pairs = set()
    adjacency = {i: [] for i in range(len(clean_nodes))}
    indegree = {i: 0 for i in range(len(clean_nodes))}

    for edge in raw_edges:
        if not isinstance(edge, dict):
            raise store.CanvasError('模板连线必须为对象')
        keys = set(edge)
        if keys == {'source', 'target'}:
            raw_src, raw_dst = edge['source'], edge['target']
        elif keys == {'sourceIndex', 'targetIndex'}:
            raw_src, raw_dst = edge['sourceIndex'], edge['targetIndex']
            if type(raw_src) is not int or type(raw_dst) is not int:
                raise store.CanvasError('模板连线索引必须为整数')
        else:
            raise store.CanvasError('模板连线字段无效')

        src_idx = resolve_endpoint(raw_src)
        dst_idx = resolve_endpoint(raw_dst)
        if src_idx == dst_idx or (src_idx, dst_idx) in seen_pairs:
            raise store.CanvasError('模板连线不能连接自身或重复连接')
        if node_types[dst_idx] not in TARGETS[node_types[src_idx]]:
            raise store.CanvasError('模板包含不支持的节点类型连接')
        seen_pairs.add((src_idx, dst_idx))
        adjacency[src_idx].append(dst_idx)
        indegree[dst_idx] += 1
        clean_edges.append({'source': raw_src, 'target': raw_dst})

    queue = [i for i, deg in indegree.items() if deg == 0]
    visited = 0
    while queue:
        cur = queue.pop()
        visited += 1
        for nxt in adjacency[cur]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited != len(clean_nodes):
        raise store.CanvasError('模板连线不能形成循环')

    cleaned = {
        'nodes': clean_nodes,
        'edges': clean_edges,
    }
    if group_title is not None:
        cleaned['groupTitle'] = group_title
    if group_color is not None:
        cleaned['groupColor'] = group_color

    try:
        encoded = json.dumps(cleaned, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise store.CanvasError('模板内容序列化失败')
    if len(encoded.encode('utf-8')) > MAX_PAYLOAD_BYTES:
        raise store.CanvasError('模板内容超过大小限制')
    return cleaned, encoded


def _public_row(row):
    payload = json.loads(row['payload'])
    nodes = payload.get('nodes') or []
    edges = payload.get('edges') or []
    return {
        'id': row['id'],
        'name': row['name'],
        'include_prompts': bool(row['include_prompts']),
        'payload': payload,
        'node_count': len(nodes),
        'edge_count': len(edges),
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }


def list_templates():
    init_templates_db()
    db = task_db.get_db()
    rows = db.execute(
        'SELECT id, name, include_prompts, payload, created_at, updated_at '
        'FROM canvas_group_templates ORDER BY updated_at DESC, id DESC'
    ).fetchall()
    return [_public_row(row) for row in rows]


def create_template(data):
    init_templates_db()
    if not isinstance(data, dict):
        raise store.CanvasError('请求必须为JSON对象')
    if set(data) - TOP_KEYS:
        raise store.CanvasError('请求包含未知字段')
    name = _validate_name(data.get('name'))
    include_prompts = data.get('include_prompts', False)
    if type(include_prompts) is not bool:
        raise store.CanvasError('include_prompts 必须为布尔值')
    _, encoded = validate_payload(data.get('payload'), include_prompts)

    template_id = uuid.uuid4().hex
    now = task_db.utcnow()
    with store.write_transaction() as db:
        count = db.execute('SELECT COUNT(*) FROM canvas_group_templates').fetchone()[0]
        if count >= MAX_TEMPLATES:
            raise store.CanvasError(f'模板数量已达上限（{MAX_TEMPLATES}个），请先删除不需要的模板')
        db.execute(
            'INSERT INTO canvas_group_templates (id, name, include_prompts, payload, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (template_id, name, 1 if include_prompts else 0, encoded, now, now),
        )
        row = db.execute(
            'SELECT id, name, include_prompts, payload, created_at, updated_at '
            'FROM canvas_group_templates WHERE id = ?',
            (template_id,),
        ).fetchone()
    return _public_row(row)


def delete_template(template_id):
    init_templates_db()
    if not isinstance(template_id, str) or not HEX32.fullmatch(template_id):
        raise store.CanvasError('模板不存在', 404)
    with store.write_transaction() as db:
        cursor = db.execute('DELETE FROM canvas_group_templates WHERE id = ?', (template_id,))
        if cursor.rowcount == 0:
            raise store.CanvasError('模板不存在', 404)
    return {'deleted_id': template_id}


def register_routes(blueprint, body):
    from flask import jsonify, request
    from local_delete import require_same_origin

    @blueprint.route('/api/canvas/templates', methods=['GET', 'POST'])
    def canvas_templates_collection():
        if request.method == 'GET':
            return jsonify(success=True, templates=list_templates())
        require_same_origin(request, json_body=True)
        return jsonify(success=True, template=create_template(body())), 201

    @blueprint.route('/api/canvas/templates/<template_id>', methods=['DELETE'])
    def canvas_templates_item(template_id):
        require_same_origin(request, json_body=False)
        return jsonify(success=True, **delete_template(template_id))
