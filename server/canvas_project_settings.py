"""Per-node provider selection for canvas generation, separate from immutable submitted tasks."""
import re

import tasks
from canvas_store import CanvasError, workflow
from provider_profiles import load_profile, ProfileError

ADAPTERS = {'image': {'ark', 'cupsy'}, 'video': {'ark', 'cupsy'}, 'audio': {'cupsy'}}


def init_settings_db():
    """Keep the legacy table so old rows are neither deleted nor migrated.

    Since 2026-11-13 project defaults are no longer read, written or used for
    canvas generation; every generation node must carry its own selection.
    """
    db = tasks.get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS canvas_project_generation_settings (
        project_id TEXT PRIMARY KEY REFERENCES canvas_projects(id),
        revision INTEGER NOT NULL, providers TEXT NOT NULL)''')
    db.commit()


def validate_selection(kind, value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'provider', 'profile_id'}:
        raise CanvasError('接口配置格式无效')
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


def validate_generation(data, kind):
    """Bind canvas submissions to the saved node's own provider selection.

    Requests without canvas context belong to the legacy tools and are not
    checked here. Project defaults and project_settings_revision are ignored.
    """
    workflow_id = data.get('canvas_workflow_id')
    if workflow_id is None:
        if 'canvas_node_id' in data or 'canvas_workflow_revision' in data:
            raise CanvasError('节点生成请求必须指定画布')
        return
    if not isinstance(workflow_id, str) or not workflow_id:
        raise CanvasError('画布编号无效')
    saved = workflow(workflow_id)
    from canvas_store import ID
    node_id = data.get('canvas_node_id')
    if not isinstance(node_id, str) or not ID.fullmatch(node_id):
        raise CanvasError('节点生成请求必须指定有效节点')
    if _request_revision(data.get('canvas_workflow_revision')) != saved['revision']:
        raise CanvasError('画布已改变，请保存或刷新后重新生成', 409)
    node = next((n for n in saved['document']['nodes'] if n['id'] == node_id), None)
    if node is None:
        raise CanvasError('节点不存在', 404)
    if node['type'] != kind:
        raise CanvasError('节点类型与生成接口不匹配')
    selected = validate_node_selection(kind, node.get('providerSelection'))
    if selected is None:
        raise CanvasError('请先为节点选择接口')
    if data.get('provider') != selected['provider'] or (data.get('profile_id') or None) != selected['profile_id']:
        raise CanvasError('生成接口必须使用节点已保存的接口配置', 409)
    validate_selection(kind, selected)
