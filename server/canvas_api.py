"""Authenticated canvas endpoints; application-wide auth guards this blueprint."""
import json
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

import canvas_store as store
import storage
import tasks as task_db

canvas_api = Blueprint('canvas_api', __name__)
PREFIX = '/api/canvas/workflows'


@canvas_api.errorhandler(store.CanvasError)
def canvas_error(error):
    return jsonify(success=False, error=str(error)), error.status


@canvas_api.errorhandler(BadRequest)
def invalid_json(error):
    return jsonify(success=False, error='请求数据格式无效'), 400


@canvas_api.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return jsonify(success=False, error='请求数据超过大小限制'), 413


def body():
    if request.content_length and request.content_length > store.MAX_DOCUMENT_BYTES + 4096:
        raise store.CanvasError('请求文档过大', 413)
    raw = request.stream.read(store.MAX_DOCUMENT_BYTES + 4097)
    if len(raw) > store.MAX_DOCUMENT_BYTES + 4096:
        raise store.CanvasError('请求文档过大', 413)
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise store.CanvasError('请求必须为JSON对象')
    if not isinstance(data, dict):
        raise store.CanvasError('请求必须为JSON对象')
    return data


@canvas_api.route('/api/canvas/projects', methods=['GET', 'POST'])
def projects():
    if request.method == 'GET':
        return jsonify(success=True, projects=store.list_projects())
    return jsonify(success=True, project=store.create_project(body().get('title', '未命名项目'))), 201


@canvas_api.route('/api/canvas/projects/<project_id>', methods=['GET', 'PATCH'])
def project_detail(project_id):
    if request.method == 'GET':
        return jsonify(success=True, project=store.get_project(project_id))
    return jsonify(success=True, project=store.rename_project(project_id, body().get('title')))


@canvas_api.route('/api/canvas/projects/<project_id>/workflows', methods=['GET', 'POST'])
def workflows(project_id):
    if request.method == 'GET':
        return jsonify(success=True, workflows=store.list_workflows(project_id))
    data = body()
    return jsonify(success=True, workflow=store.create_workflow(project_id, data.get('title', '未命名画布'), data.get('document'))), 201


@canvas_api.route(PREFIX + '/<workflow_id>', methods=['GET', 'PUT'])
def workflow_detail(workflow_id):
    if request.method == 'GET':
        return jsonify(success=True, workflow=store.workflow(workflow_id))
    data = body()
    return jsonify(success=True, workflow=store.update_workflow(workflow_id, data.get('title'), data.get('document'), data.get('revision')))


@canvas_api.route(PREFIX + '/<workflow_id>/assets', methods=['POST'])
def upload_asset(workflow_id):
    store.workflow(workflow_id)
    upload = request.files.get('file')
    if upload is None:
        raise store.CanvasError('请选择素材文件')
    from canvas_catalog import record_origin
    with store.write_transaction():
        asset = store.save_asset(workflow_id, upload.stream, upload.filename)
        record_origin('workflow', asset['id'], 'uploaded')
    return jsonify(success=True, asset=asset), 201


@canvas_api.route(PREFIX + '/<workflow_id>/assets/<asset_id>', methods=['GET'])
def read_asset(workflow_id, asset_id):
    asset = store.get_asset(workflow_id, asset_id, allow_archived=True)
    response = send_file(store.asset_path(asset), mimetype=asset['mime_type'],
                         download_name=asset['name'], conditional=True)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'private, no-cache'
    return response


@canvas_api.route(PREFIX + '/<workflow_id>/task-results', methods=['POST'])
def import_task_results(workflow_id):
    store.workflow(workflow_id)
    task_id = body().get('task_id')
    if type(task_id) is not int or task_id < 1:
        raise store.CanvasError('task_id 必须为正整数')
    task = task_db.get_task(task_id)
    if not task or task.get('deleted_at'):
        raise store.CanvasError('任务不存在', 404)
    if task['status'] != 'succeeded':
        raise store.CanvasError('只能导入成功任务的结果', 409)
    output_root = Path(storage.OUTPUT_DIR).absolute()
    sources = []
    for asset in task_db.list_assets(task_id):
        if asset['kind'] not in ('output_image', 'output_video', 'output_audio'):
            continue
        path = Path(asset['path']).absolute()
        if path.resolve() != path or not path.is_relative_to(output_root) or not path.is_file():
            raise store.CanvasError('任务输出文件不可读取', 409)
        sources.append(path)
    if not sources:
        raise store.CanvasError('任务没有可导入的本地输出', 409)
    assets = []
    for path in sources:
        try:
            with path.open('rb') as handle:
                assets.append(store.save_asset(workflow_id, handle, path.name))
        except OSError:
            raise store.CanvasError('任务输出文件已改变，请重新检查', 409)
    from canvas_cleanup import record_task_reference
    with store.write_transaction():
        record_task_reference(workflow_id,task_id)
    return jsonify(success=True, assets=assets)


from canvas_library import register_library_routes
register_library_routes(canvas_api, body)

from canvas_cleanup import register_cleanup_routes
register_cleanup_routes(canvas_api, body)

from canvas_catalog import register_routes as register_catalog_routes
register_catalog_routes(canvas_api, body)

from canvas_image_params import register_routes as register_image_param_routes
register_image_param_routes(canvas_api)
