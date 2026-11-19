"""Canvas references submitted by library id, snapshotted by hard link (GEN-RESULT-LIFECYCLE-20261119, user plan A).

Before: the browser downloaded each reference from the library and uploaded it again as a
multipart file, so every task held a real copy. Now a canvas submission sends the form field
``reference_media`` = JSON ``[{"field": <file field>, "id": <media or canvas asset id>,
"filename": <part filename>}, ...]`` instead of file parts (plain file parts still work and may
be combined, e.g. the old tool pages).

``attach`` (before_request, generation routes only) resolves every entry to the library file
and adds it to ``request.files`` as a read-only ``FileStorage`` with the same field, filename
and MIME type the browser's Blob part carried, in order. The route handlers therefore run
unchanged and the Provider request is byte-for-byte what it was. Unknown, deleted, trashed or
wrongly typed ids are refused with 400 before the handler runs (no task, no estimate, no call).

``link`` (after_request) replaces each task-side reference file whose bytes equal a submitted
library file with a hard link to it (same inode; a copy stays when linking fails, e.g. across
file systems). Files the handlers re-encode (images are normalized to PNG) only match when the
normalization left the bytes unchanged; otherwise the normalized copy is kept, as before.
Queued tasks and retries read only these task-side snapshots, so later library deletion does
not affect them.
"""
import hashlib
import json
import logging
import os
import uuid

from flask import g, jsonify, request
from werkzeug.datastructures import FileStorage, MultiDict

LOG = logging.getLogger(__name__)
ROUTES = {'/api/generate', '/api/video/generate', '/api/audio/generate'}
# File field -> required kind (None: decided by the route, e.g. audio image/audio references).
FIELDS = {'images': 'image', 'image': 'image', 'last_image': 'image', 'ref_images': 'image',
          'ref_videos': 'video', 'ref_audios': 'audio', 'references': None}
MAX_ENTRIES = 64


class ReferenceError_(ValueError):
    def __init__(self, message, code='invalid_reference', status=400, reference_id=None):
        super().__init__(message)
        self.code, self.status, self.reference_id = code, status, reference_id


def _entries(raw):
    try:
        entries = json.loads(raw)
    except ValueError:
        raise ReferenceError_('reference_media 必须是 JSON 数组')
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise ReferenceError_(f'reference_media 必须是最多 {MAX_ENTRIES} 项的数组')
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {'field', 'id', 'filename'} or entry.get('field') not in FIELDS \
                or not isinstance(entry.get('id'), str) or not isinstance(entry.get('filename'), str) \
                or not entry['filename'] or len(entry['filename']) > 255:
            raise ReferenceError_('reference_media 项无效')
    return entries


def _resolve(workflow_id, entry):
    import canvas_media_refs
    import canvas_store as store
    import media_library as media
    asset_id = entry['id']
    state = media.status(asset_id)[0] if media.MEDIA_ID.fullmatch(asset_id) else 'missing'
    name = entry['filename']
    if state == 'deleted':
        raise ReferenceError_(f'参考素材“{name}”已在素材库中删除，请替换或移除后再生成', 'media_deleted')
    if state == 'trashed':
        raise ReferenceError_(f'参考素材“{name}”所在的生成任务在回收站，请恢复任务或替换后再生成', 'media_trashed')
    if state == 'missing' and not isinstance(workflow_id, str):
        raise ReferenceError_(f'参考素材“{name}”不存在', 'media_not_found')
    try:
        path, mime, kind = canvas_media_refs.reference(workflow_id, asset_id)
    except store.CanvasError as error:
        code = getattr(error, 'code', None) or ('media_deleted' if error.status == 410 else 'media_not_found')
        raise ReferenceError_(f'参考素材“{name}”不可用：{error}', code)
    expected = FIELDS[entry['field']]
    if (expected and kind != expected) or kind not in ('image', 'video', 'audio'):
        raise ReferenceError_(f'参考素材“{name}”类型不符（{kind}），不能作为 {entry["field"]} 提交', 'reference_kind_mismatch')
    return str(path), mime, kind


def attach():
    if request.method != 'POST' or request.path not in ROUTES or request.mimetype != 'multipart/form-data':
        return None
    raw = request.form.get('reference_media')
    if raw is None:
        return None
    try:
        entries = _entries(raw)
        resolved = []
        for entry in entries:
            try:
                resolved.append((entry, *_resolve(request.form.get('canvas_workflow_id'), entry)))
            except ReferenceError_ as error:
                error.reference_id = entry['id']
                raise
    except ReferenceError_ as error:
        payload = {'success': False, 'error': str(error), 'code': error.code}
        if error.reference_id:
            payload['reference_id'] = error.reference_id
        return jsonify(payload), error.status
    # The old upload counted the references against the request limit: keep that limit.
    from flask import current_app
    limit = current_app.config.get('MAX_CONTENT_LENGTH')
    if limit and (request.content_length or 0) + sum(os.path.getsize(item[1]) for item in resolved) > limit:
        return jsonify(success=False, error='上传文件总大小超过100MB限制'), 413
    files = MultiDict(list(request.files.items(multi=True)))
    handles, sources = [], []
    for entry, path, mime, _kind in resolved:
        handle = open(path, 'rb')
        handles.append(handle)
        sources.append(path)
        files.add(entry['field'], FileStorage(stream=handle, filename=entry['filename'], name=entry['field'], content_type=mime))
    g.reference_handles, g.reference_sources = handles, sources
    request._get_current_object().__dict__['files'] = files
    return None


def _digest(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _task_reference_paths(task_id):
    import tasks as task_db
    paths = [a['path'] for a in task_db.list_assets(task_id) if str(a['kind']).startswith('input_')]
    paths += [a['local_path'] for a in task_db.list_task_provider_assets_for_tasks([task_id], ('image', 'audio', 'video'))]
    return list(dict.fromkeys(p for p in paths if p))


def link_snapshots(task_id, sources):
    """Hard-link task-side reference files that equal a submitted library file -> linked count."""
    by_size = {}
    for source in dict.fromkeys(sources):
        try:
            by_size.setdefault(os.path.getsize(source), []).append(source)
        except OSError:
            continue
    hashes, linked = {}, 0
    for path in _task_reference_paths(task_id):
        try:
            candidates = by_size.get(os.path.getsize(path), [])
            if not candidates:
                continue
            digest = None
            for source in candidates:
                if os.path.samefile(source, path):
                    break
                digest = digest or _digest(path)
                if hashes.setdefault(source, _digest(source)) != digest:
                    continue
                temporary = f'{path}.{uuid.uuid4().hex}.link'
                try:
                    os.link(source, temporary)
                    os.replace(temporary, path)
                    linked += 1
                except OSError as error:  # e.g. another file system: the copy stays
                    LOG.info('reference_snapshot_copy_kept task=%s error=%s', task_id, error)
                finally:
                    if os.path.exists(temporary):
                        os.remove(temporary)
                break
        except OSError:
            continue
    return linked


def link(response):
    sources = g.pop('reference_sources', None)
    if not sources or response.status_code not in (200, 201, 202):
        return response
    try:
        body = response.get_json(silent=True) or {}
        task_id = body.get('db_task_id') or body.get('task_id')
        if isinstance(task_id, int) and task_id > 0:
            link_snapshots(task_id, sources)
    except Exception:
        LOG.exception('reference_snapshot_link_failed')
    return response


def close(_error=None):
    for handle in g.pop('reference_handles', ()) or ():
        try:
            handle.close()
        except OSError:
            pass


def install(app):
    app.before_request(attach)
    app.after_request(link)
    app.teardown_request(close)
