"""Task media responses, download names and reference metadata."""
import os
import re
from datetime import datetime, timezone
from flask import Response, send_file
import png_metadata
import storage
import tasks as task_db


def _task_download_name(task, filename, original=False):
    from result_names import result_display_name, task_result_name
    custom = result_display_name(task_result_name(task.get('params')), task['id'], filename,
                                 '_original' if original else '')
    if custom:
        return custom
    extension = os.path.splitext(filename)[1].lower().lstrip('.') or 'bin'
    if extension == 'jpeg':
        extension = 'jpg'
    match = re.search(r'_(\d+)(?:\.[^.]+)?$', filename)
    output_index = int(match.group(1)) + 1 if match else 1
    try:
        created_at = datetime.fromisoformat(str(task.get('created_at') or '').replace('Z', '+00:00'))
    except ValueError:
        created_at = datetime.now(timezone.utc)
    timestamp = created_at.strftime('%Y%m%d%H%M%S')
    name = (
        f'ink-traces-{task.get("type") or "media"}-task-{task["id"]}-'
        f'{timestamp}-output-{output_index:02d}'
    )
    return f'{name}{"-original" if original else ""}.{extension}'


def _task_png_text_entries(task):
    return png_metadata.build_text_entries(task.get('prompt'), task.get('params'))


def _task_output_asset(task_id, filename):
    for asset in task_db.list_assets(task_id):
        if asset['kind'] not in ('output_image', 'output_video', 'output_audio'):
            continue
        if os.path.basename(asset['path']) == filename and os.path.isfile(asset['path']):
            return asset
    return None


def _task_asset_response(task, asset, filename, as_attachment, raw=False):
    original = raw and asset.get('kind') == 'output_image'
    download_name = _task_download_name(task, filename, original=original)
    if filename.lower().endswith('.png') and not raw:
        response = Response(
            storage.iter_png_with_text(
                asset['path'], _task_png_text_entries(task),
            ),
            mimetype='image/png',
        )
        disposition = 'attachment' if as_attachment else 'inline'
        from result_names import content_disposition
        response.headers['Content-Disposition'] = content_disposition(disposition, download_name)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if as_attachment:
            response.headers['Cache-Control'] = 'no-store'
        else:
            response.cache_control.public = True
            response.cache_control.max_age = 31536000
            response.cache_control.immutable = True
        return response

    response = send_file(
        asset['path'],
        mimetype=asset.get('mime_type'),
        as_attachment=as_attachment,
        download_name=download_name,
        conditional=not as_attachment,
        max_age=0 if as_attachment else 31536000,
    )
    if not as_attachment:
        response.cache_control.public = True
        response.cache_control.immutable = True
    return response


def _attach_task_input_references(tasks):
    missing_ref_tasks = []
    for task in tasks:
        result = task.get('result') if isinstance(task.get('result'), dict) else {}
        local_refs = result.get('local_refs') or []
        metadata_fields = ('local_ref_types', 'local_ref_roles', 'local_ref_names', 'local_ref_asset_ids')
        if (
            not local_refs
            or any(len(result.get(field) or []) != len(local_refs) for field in metadata_fields)
        ):
            missing_ref_tasks.append(task)
    if not missing_ref_tasks:
        return tasks

    refs_by_task = {}
    ref_types_by_task = {}
    ref_roles_by_task = {}
    ref_names_by_task = {}
    ref_asset_ids_by_task = {}
    task_ids = [task['id'] for task in missing_ref_tasks]
    task_by_id = {task['id']: task for task in missing_ref_tasks}
    local_type_counts = {}
    for asset in task_db.list_assets_for_tasks(task_ids, ('input_image', 'input_audio', 'input_video')):
        task = task_by_id[asset['task_id']]
        params = task.get('params') if isinstance(task.get('params'), dict) else {}
        media_type = {
            'input_audio': 'audio',
            'input_video': 'video',
        }.get(asset['kind'], 'image')
        count_key = (asset['task_id'], media_type)
        media_index = local_type_counts.get(count_key, 0)
        local_type_counts[count_key] = media_index + 1
        if task.get('type') == 'video' and params.get('video_mode') == 'keyframe' and media_type == 'image':
            role = 'first_frame' if media_index == 0 else 'last_frame'
        else:
            role = f'reference_{media_type}'
        if not os.path.isfile(asset['path']):
            continue
        refs_by_task.setdefault(asset['task_id'], []).append(
            f'/api/tasks/{asset["task_id"]}/file/{os.path.basename(asset["path"])}'
        )
        ref_types_by_task.setdefault(asset['task_id'], []).append(media_type)
        ref_roles_by_task.setdefault(asset['task_id'], []).append(role)
        ref_names_by_task.setdefault(asset['task_id'], []).append(os.path.basename(asset['path']))
        ref_asset_ids_by_task.setdefault(asset['task_id'], []).append(None)
    local_image_task_ids = {
        task_id for task_id in refs_by_task if task_by_id[task_id].get('type') == 'image'
    }
    for asset in task_db.list_task_provider_assets_for_tasks(task_ids, ('image', 'audio', 'video')):
        if asset['task_id'] in local_image_task_ids:
            continue
        if asset.get('deleted_at') or not os.path.isfile(asset['local_path']):
            continue
        refs_by_task.setdefault(asset['task_id'], []).append(
            f'/api/cupsy/assets/{asset["id"]}/content'
        )
        ref_types_by_task.setdefault(asset['task_id'], []).append(asset['kind'])
        ref_roles_by_task.setdefault(asset['task_id'], []).append(asset['role'])
        ref_names_by_task.setdefault(asset['task_id'], []).append(
            asset.get('original_name') or os.path.basename(asset['local_path'])
        )
        ref_asset_ids_by_task.setdefault(asset['task_id'], []).append(asset['id'])
    for task in missing_ref_tasks:
        local_refs = refs_by_task.get(task['id'], [])
        result = dict(task['result']) if isinstance(task.get('result'), dict) else {}
        result['local_refs'] = local_refs
        result['local_ref_types'] = ref_types_by_task.get(task['id'], [])
        result['local_ref_roles'] = ref_roles_by_task.get(task['id'], [])
        result['local_ref_names'] = ref_names_by_task.get(task['id'], [])
        result['local_ref_asset_ids'] = ref_asset_ids_by_task.get(task['id'], [])
        task['result'] = result
    return tasks
