"""Task browsing, favorites, trash and downloads, independent of providers."""
import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_file, after_this_request
import storage
import tasks as task_db
from request_utils import as_bool, positive_id
from task_media import (
    _task_download_name, _task_png_text_entries, _task_output_asset,
    _task_asset_response, _attach_task_input_references,
)

task_api = Blueprint('tasks', __name__)


TASK_VIEWS = {'all', 'favorite', 'active', 'trash'}


TASK_SORTS = {'newest', 'oldest', 'updated'}


TASK_FILTER_STATUSES = {
    'submitting', 'preparing', 'pending', 'processing', 'cancel_requested',
    'succeeded', 'failed', 'cancelled',
}


FAVORITE_GROUP_COLORS = {'green', 'cyan', 'blue', 'violet', 'rose', 'amber'}


def _task_group_filter():
    raw_group = request.args.get('favorite_group')
    if raw_group is None or raw_group == '':
        return None, None
    try:
        group_id = positive_id(raw_group)
    except (TypeError, ValueError):
        return None, (jsonify({'success': False, 'error': 'favorite_group 必须是正整数'}), 400)
    if group_id <= 0:
        return None, (jsonify({'success': False, 'error': 'favorite_group 必须是正整数'}), 400)
    return group_id, None


def _task_advanced_filters():
    status = request.args.get('status', '').strip().lower()
    provider = request.args.get('provider', '').strip()
    model = request.args.get('model', '').strip()
    created_after = request.args.get('created_after', '').strip()
    if status and status not in TASK_FILTER_STATUSES:
        return None, (jsonify({'success': False, 'error': '未知任务状态'}), 400)
    if len(provider) > 80:
        return None, (jsonify({'success': False, 'error': 'provider 过滤值过长'}), 400)
    if len(model) > 160:
        return None, (jsonify({'success': False, 'error': 'model 过滤值过长'}), 400)
    if created_after:
        try:
            parsed = datetime.fromisoformat(created_after.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            created_after = parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            return None, (jsonify({'success': False, 'error': 'created_after 必须是 ISO 日期时间'}), 400)
    return {
        'status': status or None,
        'provider': provider or None,
        'model': model or None,
        'created_after': created_after or None,
    }, None


def _parse_task_ids(data, maximum=500):
    raw_ids = data.get('ids') if isinstance(data, dict) else None
    if not isinstance(raw_ids, list) or not raw_ids:
        return None, (jsonify({'success': False, 'error': 'ids 必须是非空数组'}), 400)
    if len(raw_ids) > maximum:
        return None, (jsonify({'success': False, 'error': f'单次最多处理 {maximum} 个任务'}), 400)
    task_ids = []
    for raw_id in raw_ids:
        if isinstance(raw_id, bool):
            return None, (jsonify({'success': False, 'error': '任务 ID 必须是正整数'}), 400)
        try:
            task_id = positive_id(raw_id)
        except (TypeError, ValueError):
            return None, (jsonify({'success': False, 'error': '任务 ID 必须是正整数'}), 400)
        if task_id <= 0:
            return None, (jsonify({'success': False, 'error': '任务 ID 必须是正整数'}), 400)
        if task_id not in task_ids:
            task_ids.append(task_id)
    return task_ids, None


@task_api.route('/api/tasks', methods=['GET'])
def api_list_tasks():
    task_type = request.args.get('type')
    advanced_filters, advanced_error = _task_advanced_filters()
    if advanced_error:
        return advanced_error
    favorite_arg = request.args.get('favorite')
    favorite = None if favorite_arg is None else favorite_arg.lower() in ('1', 'true', 'yes')
    active = request.args.get('active', '').lower() in ('1', 'true', 'yes')
    deleted = request.args.get('deleted', '').lower() in ('1', 'true', 'yes')
    ungrouped = request.args.get('ungrouped', '').lower() in ('1', 'true', 'yes')
    search = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'newest')
    if sort not in TASK_SORTS:
        return jsonify({'success': False, 'error': '未知排序方式'}), 400
    favorite_group, group_error = _task_group_filter()
    if group_error:
        return group_error
    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 100))
        offset = max(0, int(request.args.get('offset', 0)))
    except ValueError:
        return jsonify({'success': False, 'error': 'limit 和 offset 必须是整数'}), 400
    tasks, total = task_db.list_tasks(
        task_type, advanced_filters['status'], limit, offset, summary=True, favorite=favorite, active=active,
        search=search, deleted=deleted, favorite_group=favorite_group,
        ungrouped=ungrouped, sort=sort, provider=advanced_filters['provider'],
        model=advanced_filters['model'], created_after=advanced_filters['created_after'],
    )
    for t in tasks:
        t['summary'] = True
    return jsonify({'success': True, 'tasks': tasks, 'total': total})


@task_api.route('/api/tasks/filter-options', methods=['GET'])
def api_task_filter_options():
    task_type = request.args.get('type')
    deleted = request.args.get('deleted', '').lower() in ('1', 'true', 'yes')
    return jsonify({
        'success': True,
        **task_db.get_task_filter_options(task_type=task_type, deleted=deleted),
    })


@task_api.route('/api/tasks/status', methods=['GET'])
def api_task_statuses():
    raw_ids = request.args.get('ids', '')
    if not raw_ids:
        return jsonify({'success': False, 'error': '缺少任务 ids'}), 400
    task_ids = []
    for raw_id in raw_ids.split(','):
        try:
            task_id = positive_id(raw_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '任务 ID 必须是正整数'}), 400
        if task_id <= 0:
            return jsonify({'success': False, 'error': '任务 ID 必须是正整数'}), 400
        if task_id not in task_ids:
            task_ids.append(task_id)
    if len(task_ids) > 100:
        return jsonify({'success': False, 'error': '单次最多查询 100 个任务'}), 400
    statuses = task_db.get_task_statuses(task_ids)
    found = {int(task['id']) for task in statuses}
    return jsonify({
        'success': True,
        'tasks': statuses,
        'missing_ids': [task_id for task_id in task_ids if task_id not in found],
    })


@task_api.route('/api/tasks/navigation', defaults={'task_id': None}, methods=['GET'])
@task_api.route('/api/tasks/<int:task_id>/navigation', methods=['GET'])
def api_task_navigation(task_id):
    task_type = request.args.get('type')
    view = request.args.get('view', 'all')
    search = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'newest')
    if view not in TASK_VIEWS:
        return jsonify({'success': False, 'error': '未知任务分类'}), 400
    if sort not in TASK_SORTS:
        return jsonify({'success': False, 'error': '未知排序方式'}), 400
    favorite_group, group_error = _task_group_filter()
    if group_error:
        return group_error
    ungrouped = request.args.get('ungrouped', '').lower() in ('1', 'true', 'yes')
    advanced_filters, advanced_error = _task_advanced_filters()
    if advanced_error:
        return advanced_error
    navigation = task_db.get_task_navigation(
        task_id=task_id,
        task_type=task_type,
        favorite=True if view == 'favorite' else None,
        active=view == 'active',
        search=search,
        deleted=view == 'trash',
        favorite_group=favorite_group if view == 'favorite' else None,
        ungrouped=ungrouped if view == 'favorite' else False,
        sort=sort,
        status=advanced_filters['status'], provider=advanced_filters['provider'],
        model=advanced_filters['model'], created_after=advanced_filters['created_after'],
    )
    return jsonify({'success': True, 'navigation': navigation})


@task_api.route('/api/tasks/selection', methods=['GET'])
def api_task_selection():
    task_type = request.args.get('type')
    view = request.args.get('view', 'all')
    search = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'newest')
    if view not in TASK_VIEWS:
        return jsonify({'success': False, 'error': '未知任务分类'}), 400
    if sort not in TASK_SORTS:
        return jsonify({'success': False, 'error': '未知排序方式'}), 400
    favorite_group, group_error = _task_group_filter()
    if group_error:
        return group_error
    ungrouped = request.args.get('ungrouped', '').lower() in ('1', 'true', 'yes')
    advanced_filters, advanced_error = _task_advanced_filters()
    if advanced_error:
        return advanced_error
    task_ids = task_db.list_task_ids(
        task_type=task_type,
        favorite=True if view == 'favorite' else None,
        active=view == 'active',
        search=search,
        deleted=view == 'trash',
        favorite_group=favorite_group if view == 'favorite' else None,
        ungrouped=ungrouped if view == 'favorite' else False,
        sort=sort,
        status=advanced_filters['status'], provider=advanced_filters['provider'],
        model=advanced_filters['model'], created_after=advanced_filters['created_after'],
    )
    return jsonify({'success': True, 'ids': task_ids, 'total': len(task_ids)})


@task_api.route('/api/tasks/<int:task_id>', methods=['GET'])
def api_get_task(task_id):
    t = task_db.get_task(task_id)
    if not t:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    _attach_task_input_references([t])
    return jsonify({'success': True, 'task': t})


@task_api.route('/api/tasks/<int:task_id>/favorite', methods=['PATCH'])
def api_favorite_task(task_id):
    task = task_db.get_task(task_id)
    if not task:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('favorite'), bool):
        return jsonify({'success': False, 'error': 'favorite 必须是布尔值'}), 400
    task_db.set_task_favorite(task_id, data['favorite'])
    return jsonify({'success': True, 'favorite': data['favorite'], 'task': task_db.get_task(task_id)})


@task_api.route('/api/favorite-groups', methods=['GET'])
def api_list_favorite_groups():
    return jsonify({
        'success': True,
        'groups': task_db.list_favorite_groups(request.args.get('type')),
    })


@task_api.route('/api/favorite-groups', methods=['POST'])
def api_create_favorite_group():
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()
    color = str(data.get('color') or 'green').strip().lower()
    if not name or len(name) > 40:
        return jsonify({'success': False, 'error': '分组名称长度必须为 1-40 个字符'}), 400
    if color not in FAVORITE_GROUP_COLORS:
        return jsonify({'success': False, 'error': '未知分组颜色'}), 400
    try:
        group = task_db.create_favorite_group(name, color)
    except Exception as error:
        if 'UNIQUE constraint failed' in str(error):
            return jsonify({'success': False, 'error': '收藏分组名称已存在'}), 409
        raise
    return jsonify({'success': True, 'group': group}), 201


@task_api.route('/api/favorite-groups/<int:group_id>', methods=['PATCH'])
def api_update_favorite_group(group_id):
    if not task_db.get_favorite_group(group_id):
        return jsonify({'success': False, 'error': '收藏分组不存在'}), 404
    data = request.get_json(silent=True) or {}
    name = None
    color = None
    if 'name' in data:
        name = str(data.get('name') or '').strip()
        if not name or len(name) > 40:
            return jsonify({'success': False, 'error': '分组名称长度必须为 1-40 个字符'}), 400
    if 'color' in data:
        color = str(data.get('color') or '').strip().lower()
        if color not in FAVORITE_GROUP_COLORS:
            return jsonify({'success': False, 'error': '未知分组颜色'}), 400
    try:
        group = task_db.update_favorite_group(group_id, name=name, color=color)
    except Exception as error:
        if 'UNIQUE constraint failed' in str(error):
            return jsonify({'success': False, 'error': '收藏分组名称已存在'}), 409
        raise
    return jsonify({'success': True, 'group': group})


@task_api.route('/api/favorite-groups/<int:group_id>', methods=['DELETE'])
def api_delete_favorite_group(group_id):
    if not task_db.delete_favorite_group(group_id):
        return jsonify({'success': False, 'error': '收藏分组不存在'}), 404
    return jsonify({'success': True})


@task_api.route('/api/tasks/<int:task_id>/favorite-groups', methods=['PATCH'])
def api_set_task_favorite_groups(task_id):
    if not task_db.get_task(task_id):
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    data = request.get_json(silent=True) or {}
    raw_group_ids = data.get('group_ids')
    if not isinstance(raw_group_ids, list):
        return jsonify({'success': False, 'error': 'group_ids 必须是数组'}), 400
    group_ids = []
    for raw_group_id in raw_group_ids:
        if isinstance(raw_group_id, bool):
            return jsonify({'success': False, 'error': '分组 ID 必须是正整数'}), 400
        try:
            group_id = positive_id(raw_group_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '分组 ID 必须是正整数'}), 400
        if group_id <= 0:
            return jsonify({'success': False, 'error': '分组 ID 必须是正整数'}), 400
        group_ids.append(group_id)
    try:
        task_db.replace_task_favorite_groups(task_id, group_ids)
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    return jsonify({'success': True, 'task': task_db.get_task(task_id)})


@task_api.route('/api/tasks/bulk-favorite-groups', methods=['POST'])
def api_bulk_favorite_groups():
    data = request.get_json(silent=True) or {}
    task_ids, id_error = _parse_task_ids(data)
    if id_error:
        return id_error
    raw_group_ids = data.get('group_ids')
    if not isinstance(raw_group_ids, list):
        return jsonify({'success': False, 'error': 'group_ids 必须是数组'}), 400
    try:
        group_ids = [positive_id(group_id) for group_id in raw_group_ids]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '分组 ID 必须是整数'}), 400
    if any(group_id <= 0 for group_id in group_ids):
        return jsonify({'success': False, 'error': '分组 ID 必须是正整数'}), 400
    mode = data.get('mode', 'add')
    if mode not in ('add', 'remove', 'replace'):
        return jsonify({'success': False, 'error': '未知分组更新方式'}), 400
    try:
        updated = task_db.update_tasks_favorite_groups(task_ids, group_ids, mode)
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    return jsonify({'success': True, 'updated': len(updated), 'updated_ids': updated})


@task_api.route('/api/tasks/bulk-delete', methods=['POST'])
def api_bulk_delete_tasks():
    data = request.get_json(silent=True) or {}
    task_ids, id_error = _parse_task_ids(data)
    if id_error:
        return id_error
    permanent = bool(data.get('permanent', False))
    if not permanent:
        moved_ids = task_db.move_tasks_to_trash(task_ids)
        missing_ids = [task_id for task_id in task_ids if task_id not in moved_ids]
        return jsonify({
            'success': True,
            'deleted': len(moved_ids),
            'trashed': len(moved_ids),
            'deleted_ids': moved_ids,
            'trashed_ids': moved_ids,
            'missing_ids': missing_ids,
        })

    deleted_ids = []
    missing_ids = []
    skipped_ids = []
    for task_id in task_ids:
        task = task_db.get_task(task_id)
        if not task:
            missing_ids.append(task_id)
            continue
        if task.get('deleted_at') is None or task.get('status') == 'cancel_requested':
            skipped_ids.append(task_id)
            continue
        storage.remove_task_files(task)
        task_db.delete_task(task_id)
        deleted_ids.append(task_id)

    return jsonify({
        'success': True,
        'deleted': len(deleted_ids),
        'deleted_ids': deleted_ids,
        'missing_ids': missing_ids,
        'skipped_ids': skipped_ids,
    })


@task_api.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def api_delete_task(task_id):
    t = task_db.get_task(task_id)
    if not t:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    permanent = request.args.get('permanent', '').lower() in ('1', 'true', 'yes')
    if permanent:
        if t.get('deleted_at') is None:
            return jsonify({'success': False, 'error': '任务需要先移入回收站'}), 409
        if t.get('status') == 'cancel_requested':
            return jsonify({'success': False, 'error': '任务仍在取消中，请稍后再彻底删除'}), 409
        storage.remove_task_files(t)
        task_db.delete_task(task_id)
        return jsonify({'success': True, 'permanent': True})
    moved = task_db.move_tasks_to_trash([task_id])
    return jsonify({'success': True, 'trashed': bool(moved)})


@task_api.route('/api/tasks/<int:task_id>/restore', methods=['POST'])
def api_restore_task(task_id):
    task = task_db.get_task(task_id)
    if not task:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    if task.get('deleted_at') is None:
        return jsonify({'success': False, 'error': '任务不在回收站'}), 409
    restored = task_db.restore_tasks([task_id])
    if not restored:
        return jsonify({'success': False, 'error': '任务仍在取消中，请稍后再恢复'}), 409
    return jsonify({'success': True, 'task': task_db.get_task(task_id)})


@task_api.route('/api/tasks/bulk-restore', methods=['POST'])
def api_bulk_restore_tasks():
    data = request.get_json(silent=True) or {}
    task_ids, id_error = _parse_task_ids(data)
    if id_error:
        return id_error
    restored_ids = task_db.restore_tasks(task_ids)
    return jsonify({
        'success': True,
        'restored': len(restored_ids),
        'restored_ids': restored_ids,
        'skipped_ids': [task_id for task_id in task_ids if task_id not in restored_ids],
    })


@task_api.route('/api/tasks/bulk-download', methods=['POST'])
def api_bulk_download_tasks():
    data = request.get_json(silent=True) or {}
    task_ids, id_error = _parse_task_ids(data, maximum=5000)
    if id_error:
        return id_error

    raw = as_bool(data.get('raw', False))
    archive = tempfile.NamedTemporaryFile(prefix='ink-traces-', suffix='.zip', delete=False)
    archive_path = archive.name
    archive.close()
    file_count = 0
    try:
        tasks_by_id = {task['id']: task for task in task_db.get_tasks_by_ids(task_ids)}
        assets_by_task = {}
        for asset in task_db.list_assets_for_tasks(task_ids, ('output_image', 'output_video', 'output_audio')):
            assets_by_task.setdefault(asset['task_id'], []).append(asset)
        # Generated media is already compressed; deflating it again wastes CPU.
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
            for task_id in task_ids:
                for asset in assets_by_task.get(task_id, []):
                    if not os.path.isfile(asset['path']):
                        continue
                    task = tasks_by_id.get(task_id)
                    if not task:
                        continue
                    filename = os.path.basename(asset['path'])
                    original = raw and asset.get('kind') == 'output_image'
                    download_name = _task_download_name(task, filename, original=original)
                    archive_name = f'{asset["task_type"]}-task-{task_id}/{download_name}'
                    if filename.lower().endswith('.png') and not raw:
                        with bundle.open(archive_name, 'w') as target:
                            for chunk in storage.iter_png_with_text(
                                asset['path'], _task_png_text_entries(task),
                            ):
                                target.write(chunk)
                    else:
                        bundle.write(asset['path'], arcname=archive_name)
                    file_count += 1
        if file_count == 0:
            os.remove(archive_path)
            return jsonify({'success': False, 'error': '所选任务没有可下载的结果'}), 404
    except Exception:
        if os.path.exists(archive_path):
            os.remove(archive_path)
        raise

    @after_this_request
    def remove_archive(response):
        try:
            os.remove(archive_path)
        except OSError:
            pass
        return response

    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    archive_id = uuid.uuid4().hex[:8]
    return send_file(
        archive_path,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'ink-traces-tasks-{timestamp}-{archive_id}.zip',
        max_age=0,
    )


@task_api.route('/api/tasks/clear', methods=['DELETE'])
def api_clear_tasks():
    """Move all visible tasks to trash; permanent removal stays explicit."""
    tasks, _ = task_db.list_tasks(limit=None)
    moved = task_db.move_tasks_to_trash([task['id'] for task in tasks])
    return jsonify({'success': True, 'deleted': len(moved), 'trashed': len(moved)})


@task_api.route('/api/tasks/<int:task_id>/file/<path:filename>', methods=['GET'])
def api_task_file(task_id, filename):
    """提供任务输出文件的访问"""
    t = task_db.get_task(task_id)
    if not t or not t.get('output_dir'):
        return jsonify({'success': False, 'error': '文件不存在'}), 404
    output_dir = os.path.abspath(t['output_dir'])
    filepath = os.path.abspath(os.path.join(output_dir, filename))
    if os.path.commonpath([output_dir, filepath]) != output_dir:
        return jsonify({'success': False, 'error': '文件不存在'}), 404
    if not os.path.isfile(filepath):
        return jsonify({'success': False, 'error': '文件不存在'}), 404
    output_asset = _task_output_asset(task_id, filename)
    if output_asset:
        return _task_asset_response(t, output_asset, filename, as_attachment=False)
    response = send_file(filepath, conditional=True, max_age=31536000)
    response.cache_control.public = True
    response.cache_control.immutable = True
    return response


@task_api.route('/api/tasks/<int:task_id>/download/<path:filename>', methods=['GET'])
def api_download_task_file(task_id, filename):
    task = task_db.get_task(task_id)
    asset = _task_output_asset(task_id, filename) if task else None
    if not task or not asset:
        return jsonify({'success': False, 'error': '下载文件不存在'}), 404
    return _task_asset_response(
        task,
        asset,
        filename,
        as_attachment=True,
        raw=as_bool(request.args.get('raw', False)),
    )
