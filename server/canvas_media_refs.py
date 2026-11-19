"""LIBRARY-GLOBAL-20261116 S2: generation results and canvas references through the global media library.

* ``register_task_outputs``: after a task succeeds its local outputs are registered into
  生成历史/<kind> (``media_library.register_generated``, hard link, idempotent by sha256);
  layer tasks and thumbnails are never registered.
* ``import_task_media``: the write-back references the media ids instead of copying files
  into the canvas (``node.asset``/``candidates`` = ``node_asset(row)``).
* ``reference``: reference files for submission are read through media; old canvas asset ids
  still work (media alias ``workflow:<old id>`` first, else the canvas copy).

Media write-back is on since integration (S1b ``canvas_store.validate_document`` accepts media
ids, ``canvas_store.MEDIA_REFERENCES = True``); the old copying write-back only remains as the
switched-off fallback. Registration and reference
resolution do not depend on the switch. Nothing here calls a provider or retries a task.
"""
import logging
from pathlib import Path

import canvas_store as store
import media_library as media
import storage
import tasks as task_db

LOG = logging.getLogger('nanobanana.canvas_media_refs')

MEDIA_PREFIX = '/api/canvas/media/'
OUTPUT_KINDS = ('output_image', 'output_video', 'output_audio')
GENERATION_TASKS = ('image', 'video', 'audio')
NODE_ASSET_KEYS = ('id', 'name', 'mime_type', 'kind', 'size_bytes')


def enabled():
    """True once validate_document accepts media references (S1b sets canvas_store.MEDIA_REFERENCES)."""
    return getattr(store, 'MEDIA_REFERENCES', False) is True


def node_asset(row):
    """The asset object a canvas node stores for a media item (same keys as canvas_store.asset_public)."""
    return {**{key: row[key] for key in NODE_ASSET_KEYS}, 'url': MEDIA_PREFIX + row['id']}


def _display_name(task, path):
    from result_names import result_display_name, task_result_name
    return result_display_name(task_result_name(task.get('params')), task['id'], path.name) or f"{task['id']}_{path.name}"


def register_task_outputs(task_id, strict=False):
    """Register a succeeded generation task's local outputs into the library.

    Returns [(task_asset_id, state, media_id)] in output order; state is ``ok`` or
    ``deleted`` (the user deleted the result in the library: it is never re-imported)
    or ``failed`` (unreadable output; only when not ``strict``, else CanvasError).
    Tasks that are not succeeded, layer tasks and non-output files are skipped.
    """
    task = task_db.get_task(task_id)
    if not task or task['status'] != 'succeeded' or task.get('type') not in GENERATION_TASKS:
        return []
    output_root = Path(storage.OUTPUT_DIR).absolute()
    results = []
    for asset in task_db.list_assets(task_id):
        if asset['kind'] not in OUTPUT_KINDS:
            continue
        if asset.get('media_id'):
            state, _row = media.status(asset['media_id'])
            if state in ('ok', 'deleted', 'trashed'):
                results.append((asset['id'], state, asset['media_id']))
                continue
        path = Path(asset['path']).absolute()
        try:
            if path.resolve() != path or not path.is_relative_to(output_root) or not path.is_file():
                raise store.CanvasError('任务输出文件不可读取', 409)
            media_id = media.register_generated(task['id'], path, asset['kind'], name=_display_name(task, path))
        except (store.CanvasError, OSError, ValueError) as error:
            if strict:
                raise store.CanvasError('任务输出文件不可读取', 409) from error
            LOG.warning('media_register_failed task=%s asset=%s error=%s', task_id, asset['id'], error)
            results.append((asset['id'], 'failed', None))
            continue
        results.append((asset['id'], 'ok', media_id))
    return results


def register_task_outputs_safely(task_id):
    """Worker hook: failures only log; the task row is never touched."""
    try:
        results = register_task_outputs(task_id)
        if results:
            LOG.info('media_registered task=%s items=%s', task_id, sum(1 for _, state, _ in results if state == 'ok'))
        return results
    except Exception:
        LOG.exception('media_register_hook_failed task=%s', task_id)
        return []


def import_task_media(workflow_id, task_id):
    """Write-back import without copies: node assets referencing the task's media items."""
    store.workflow(workflow_id)
    task = task_db.get_task(task_id)
    if not task or task.get('deleted_at'):
        raise store.CanvasError('任务不存在', 404)
    if task['status'] != 'succeeded':
        raise store.CanvasError('只能导入成功任务的结果', 409)
    results = register_task_outputs(task_id, strict=True)
    if not results:
        raise store.CanvasError('任务没有可导入的本地输出', 409)
    assets = []
    for _asset_id, state, media_id in results:
        if state != 'ok':
            continue
        current, row = media.status(media_id)
        if current == 'ok':
            assets.append(node_asset(row))
    if not assets:
        raise store.CanvasError('任务结果已从素材库删除', 409)
    from canvas_cleanup import record_task_reference
    with store.write_transaction():
        record_task_reference(workflow_id, task_id)
    return assets


class ReferenceDeleted(store.CanvasError):
    def __init__(self, name):
        super().__init__(f'参考素材“{name}”已从素材库删除', 410)


def reference(workflow_id, asset_id):
    """(path, mime_type, kind) of a node reference by asset id.

    A media id reads the library file (deleted -> ReferenceDeleted); an old canvas asset id
    goes through its media alias first, else the canvas copy (archived canvases allowed).
    """
    if not isinstance(asset_id, str) or not media.MEDIA_ID.fullmatch(asset_id):
        raise store.CanvasError('素材编号无效')
    state, row = media.status(asset_id)
    if state == 'missing':
        alias = media.resolve('workflow:' + asset_id)
        if alias:
            state, row = media.status(alias)
    if state == 'deleted':
        raise ReferenceDeleted(row.get('name') or asset_id)
    if state == 'trashed':
        raise store.CanvasError(f'参考素材“{row.get("name") or asset_id}”所在的生成任务在回收站，请恢复任务或替换后再生成', 409)
    if state == 'ok':
        return media.media_path(row), row['mime_type'], row['kind']
    canvas = store.get_asset(workflow_id, asset_id, allow_archived=True)
    return store.asset_path(canvas), canvas['mime_type'], canvas['kind']


def reference_of(workflow_id, asset):
    """``reference`` for a node asset object whose URL must name the same id."""
    asset_id, url = asset.get('id') if isinstance(asset, dict) else None, asset.get('url') if isinstance(asset, dict) else None
    if not is_reference_url(workflow_id, url) or not isinstance(asset_id, str) or url.rsplit('/', 1)[-1] != asset_id:
        raise store.CanvasError('素材引用无效')
    return reference(workflow_id, asset_id)


def is_reference_url(workflow_id, url):
    """URL forms a node reference may carry: the library or (legacy) this canvas's copies."""
    return isinstance(url, str) and (url.startswith(MEDIA_PREFIX) or url.startswith(f'/api/canvas/workflows/{workflow_id}/assets/'))


def media_hashes(ids):
    """{media id: sha256} for the given ids that are live library items."""
    ids = [i for i in dict.fromkeys(ids) if isinstance(i, str)]
    if not ids:
        return {}
    marks = ','.join('?' * len(ids))
    return {row['id']: row['sha256'] for row in task_db.get_db().execute(f'SELECT id, sha256 FROM media WHERE id IN ({marks})', ids)}
