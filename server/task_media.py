"""Task media responses, download names and reference metadata."""
import os
import re
import shutil
from pathlib import Path
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


OUTPUT_KINDS = ('output_image', 'output_video', 'output_audio')
RESULT_DELETED = '结果已删除'


class ResultDeleted(Exception):
    """The library item holding this task output was deleted (LIBRARY-GLOBAL S3)."""


def _library_state(media_id):
    """('ok', media row) | ('deleted', tombstone) | ('none', None); missing ids count as none."""
    if not media_id:
        return 'none', None
    import media_library
    state, row = media_library.status(media_id)
    return ('none', None) if state == 'missing' else (state, row)


def _library_file(row):
    import media_library
    try:
        return str(media_library.media_path(row))
    except media_library.MediaError:
        return None


def _task_output_asset(task_id, filename):
    """Output asset served for ``filename``; the file is read from the library when the
    output is registered there (LIBRARY-GLOBAL S3), else from the task output directory.

    Raises ``ResultDeleted`` when the library item was deleted (the task card stays)."""
    for asset in task_db.list_assets(task_id):
        if asset['kind'] not in OUTPUT_KINDS or os.path.basename(asset['path']) != filename:
            continue
        state, row = _library_state(asset.get('media_id'))
        if state == 'deleted':
            raise ResultDeleted(filename)
        if state == 'ok':
            path = _library_file(row)
            if path:
                return {**asset, 'path': path, 'mime_type': row.get('mime_type') or asset.get('mime_type')}
        if os.path.isfile(asset['path']):
            return asset
    return None


def deleted_thumbnail(task, filename):
    """A result thumbnail whose source output was deleted from the library is hidden too."""
    result = task.get('result') if isinstance(task.get('result'), dict) else {}
    thumbnails = [os.path.basename(str(u)) for u in result.get('local_thumbnails') or []]
    images = [os.path.basename(str(u)) for u in result.get('local_images') or []]
    if filename not in thumbnails or thumbnails.index(filename) >= len(images):
        return False
    source = images[thumbnails.index(filename)]
    for asset in task_db.list_assets(task['id']):
        if asset['kind'] in OUTPUT_KINDS and os.path.basename(asset['path']) == source:
            return _library_state(asset.get('media_id'))[0] == 'deleted'
    return False


def attach_library_status(tasks):
    """Annotate ``result`` with where each output lives (LIBRARY-GLOBAL S3).

    Contract agreed with S4b: only outputs registered in the library get an entry in
    ``result.media=[{output_url, media_id, status:'ok'|'deleted', kind, name,
    url?, thumbnail_url?, folder_id?}]`` (``url``/``thumbnail_url``/``folder_id`` only
    when ok; ``folder_id`` null = root). Tasks with such outputs also get
    ``deleted_outputs`` and ``result_deleted`` (every output was deleted in the library;
    the task card stays and shows 结果已删除). Local URLs only, no signed addresses.
    """
    by_id = {task['id']: task for task in tasks if task and task.get('id') is not None}
    if not by_id:
        return tasks
    outputs = {}
    for asset in task_db.list_assets_for_tasks(list(by_id), OUTPUT_KINDS):
        outputs.setdefault(asset['task_id'], []).append(asset)
    media_ids = {a['media_id'] for rows in outputs.values() for a in rows if a.get('media_id')}
    if not media_ids:
        return tasks
    db = task_db.get_db()
    present, deleted = {}, {}
    ids = sorted(media_ids)
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ','.join('?' for _ in chunk)
        present.update((r['id'], dict(r)) for r in db.execute(
            f'SELECT id,name,kind,folder_id FROM media WHERE id IN ({marks})', chunk))
        deleted.update((r['id'], dict(r)) for r in db.execute(
            f'SELECT id,name,kind FROM media_tombstones WHERE id IN ({marks})', chunk))
    for task_id, rows in outputs.items():
        entries = []
        for asset in sorted(rows, key=lambda a: a['id']):
            media_id = asset.get('media_id')
            output_url = f'/api/tasks/{task_id}/file/{os.path.basename(asset["path"])}'
            if media_id in present:
                row = present[media_id]
                url = f'/api/canvas/media/{media_id}'
                entries.append({'output_url': output_url, 'media_id': media_id, 'status': 'ok', 'kind': row['kind'],
                                'name': row['name'], 'url': url, 'folder_id': row['folder_id'],
                                'thumbnail_url': url + '/thumbnail' if row['kind'] == 'image' else None})
            elif media_id in deleted:
                row = deleted[media_id]
                entries.append({'output_url': output_url, 'media_id': media_id, 'status': 'deleted',
                                'kind': row['kind'], 'name': row['name']})
        if not entries:
            continue
        task = by_id[task_id]
        result = dict(task['result']) if isinstance(task.get('result'), dict) else {}
        removed = sum(1 for e in entries if e['status'] == 'deleted')
        result['media'] = entries
        result['deleted_outputs'] = removed
        result['result_deleted'] = removed == len(rows)
        task['result'] = result
    return tasks


def remove_task_files(task):
    """Permanent task deletion (LIBRARY-GLOBAL S3): remove the task's own files only.

    Library files (``<asset_root>/media``) are never removed here, whatever a task row
    points at; an output registered in the library survives as the library item (its
    task output path is only a second hard link or an independent copy). Other task
    files and the output directory are removed as before.
    """
    import media_library
    library = media_library.root()
    paths = {asset['path'] for asset in task_db.list_assets(task['id'])}
    params = task.get('params') or {}
    paths.update(params.get('ref_video_paths') or [])
    for path in paths:
        if Path(path).absolute().is_relative_to(library):
            continue
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
    task_db.delete_assets(paths)
    output_dir = task.get('output_dir')
    if output_dir and os.path.isdir(output_dir):
        directory = Path(output_dir).absolute()
        if not (library.is_relative_to(directory) or directory.is_relative_to(library)):
            shutil.rmtree(output_dir, ignore_errors=True)


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
