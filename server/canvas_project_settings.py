"""Project-wide provider selection, separate from immutable submitted tasks."""
import json
import re

import tasks
from canvas_store import CanvasError, get_project, workflow
from provider_profiles import load_profile, ProfileError

ADAPTERS = {'image': {'ark', 'cupsy'}, 'video': {'ark', 'cupsy'}, 'audio': {'cupsy'}}


def init_settings_db():
    db = tasks.get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS canvas_project_generation_settings (
        project_id TEXT PRIMARY KEY REFERENCES canvas_projects(id),
        revision INTEGER NOT NULL, providers TEXT NOT NULL)''')
    db.commit()


def get_settings(project_id):
    get_project(project_id)
    row = tasks.get_db().execute('SELECT revision,providers FROM canvas_project_generation_settings WHERE project_id=?', (project_id,)).fetchone()
    return {'revision': row['revision'], 'providers': json.loads(row['providers'])} if row else {'revision': 0, 'providers': dict.fromkeys(ADAPTERS)}


def validate_selection(kind, value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'provider', 'profile_id'}:
        raise CanvasError('项目接口配置格式无效')
    provider, profile_id = value.get('provider'), value.get('profile_id')
    if not isinstance(provider, str) or provider not in ADAPTERS[kind]:
        raise CanvasError('该生成类型不支持所选接口')
    if profile_id is not None:
        if not isinstance(profile_id, str) or not profile_id:
            raise CanvasError('接口配置编号无效')
        try:
            profile = load_profile(profile_id, kind=kind, require_enabled=True)
        except ProfileError as error:
            raise CanvasError(str(error), error.status)
        if profile['adapter'] != provider:
            raise CanvasError('接口配置与Provider不匹配')
    return {'provider': provider, 'profile_id': profile_id}


def validate_node_selection(kind, value):
    """Validate persisted shape only: inactive/deleted profiles must not block editing."""
    if value is None:
        return None
    if kind not in ADAPTERS or not isinstance(value, dict) or set(value) - {'provider', 'profile_id'}:
        raise CanvasError('节点接口配置格式无效')
    provider, profile_id = value.get('provider'), value.get('profile_id')
    if not isinstance(provider, str) or provider not in ADAPTERS[kind]:
        raise CanvasError('该节点类型不支持所选接口')
    if profile_id is not None and (not isinstance(profile_id, str) or not re.fullmatch(r'[0-9a-f]{32}', profile_id)):
        raise CanvasError('接口配置编号无效')
    return {'provider': provider, 'profile_id': profile_id}


def _request_revision(value):
    if isinstance(value, str) and len(value) <= 12 and value.isdecimal():
        value = int(value)
    return value if type(value) is int else None


def update_settings(project_id, data):
    get_project(project_id)
    if set(data) != {'revision', 'providers'} or type(data.get('revision')) is not int or data['revision'] < 0:
        raise CanvasError('请提供有效的项目配置版本和接口设置')
    providers = data['providers']
    if not isinstance(providers, dict) or set(providers) != set(ADAPTERS):
        raise CanvasError('请提供图像、视频和音频三类项目接口设置')
    validated = {kind: validate_selection(kind, providers[kind]) for kind in ADAPTERS}
    db = tasks.get_db()
    from canvas_store import write_transaction
    with write_transaction():
        get_project(project_id)
        db.execute('INSERT OR IGNORE INTO canvas_project_generation_settings VALUES (?,0,?)', (project_id, json.dumps(dict.fromkeys(ADAPTERS))))
        result = db.execute('UPDATE canvas_project_generation_settings SET providers=?,revision=revision+1 WHERE project_id=? AND revision=?', (json.dumps(validated), project_id, data['revision']))
        if result.rowcount != 1:
            raise CanvasError('项目接口设置已更新，请刷新后重试', 409)
    return get_settings(project_id)


def validate_generation(data, kind):
    """Bind new node submissions to the saved selection; preserve legacy project guards."""
    workflow_id = data.get('canvas_workflow_id')
    has_node = 'canvas_node_id' in data
    if workflow_id is None:
        if has_node or 'canvas_workflow_revision' in data:
            raise CanvasError('节点生成请求必须指定画布')
        return
    if not isinstance(workflow_id, str) or not workflow_id:
        raise CanvasError('画布编号无效')
    saved = workflow(workflow_id)
    selected = None
    if has_node:
        from canvas_store import ID
        node_id = data.get('canvas_node_id')
        if not isinstance(node_id, str) or not ID.fullmatch(node_id):
            raise CanvasError('节点编号无效')
        if _request_revision(data.get('canvas_workflow_revision')) != saved['revision']:
            raise CanvasError('画布已改变，请保存或刷新后重新生成', 409)
        node = next((n for n in saved['document']['nodes'] if n['id'] == node_id), None)
        if node is None:
            raise CanvasError('节点不存在', 404)
        if node['type'] != kind:
            raise CanvasError('节点类型与生成接口不匹配')
        selected = validate_node_selection(kind, node.get('providerSelection'))
    if selected is None:
        settings = get_settings(saved['project_id'])
        if _request_revision(data.get('project_settings_revision')) != settings['revision']:
            raise CanvasError('项目接口设置已改变，请刷新后重新生成', 409)
        selected = settings['providers'][kind]
        if selected is None:
            raise CanvasError('请先配置节点或项目生成接口', 409)
    if data.get('provider') != selected['provider'] or (data.get('profile_id') or None) != selected['profile_id']:
        raise CanvasError('生成接口必须使用已保存的节点或项目配置', 409)
    validate_selection(kind, selected)


def register_settings_routes(blueprint, body):
    from flask import request, jsonify

    @blueprint.route('/api/canvas/projects/<project_id>/generation-settings', methods=['GET', 'PUT'])
    def project_generation_settings(project_id):
        settings = get_settings(project_id) if request.method == 'GET' else update_settings(project_id, body())
        return jsonify(success=True, settings=settings)
