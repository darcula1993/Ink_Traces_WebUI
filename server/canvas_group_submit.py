"""Server-side submission and estimation for group runs (GROUP-RUN-20261115 B3).

``submit`` is the ``canvas_group_run`` submitter: it assembles one node's request
with ``canvas_submit`` (the browser's rules, ported in A1) and dispatches it
through the existing ``/api/generate`` / ``/api/video/generate`` /
``/api/audio/generate`` views inside an internal request context, so every
server check (profile scope, validate_generation, validate_submission, model
capabilities, canvas task association, estimate snapshot) runs exactly as for a
single-node browser submission.  No other provider path exists here.

Outcome rules (billing boundary; never retried, never resubmitted):

* a generation task row created by this call is the only evidence that a
  provider could have been reached, so no task row -> ``SubmitRejected``;
* a task row plus ``result_unknown`` (response or task result), or an Ark video
  route failure that did not report its task (the provider POST happens inside
  that route) -> ``{'task_id', 'result_unknown': True}``;
* otherwise the task id is returned and the task's own terminal state decides.

``estimate`` is the ``canvas_group_run`` estimator, using ``cost_estimate``
(the ledger formulas): preview counts an in-group upstream video by its planned
duration (Auto = model maximum); submit probes the real reference files.  Audio
has no price data and stays unknown (never zero).
"""
import contextlib
import contextvars
import copy
import json
import logging

import canvas_store as store
import tasks as task_db

LOG = logging.getLogger('nanobanana.canvas_group_submit')

_SUBMISSION = contextvars.ContextVar('canvas_group_submission', default=None)
ACTIVE_TASK = ('pending', 'preparing', 'processing', 'cancel_requested')
PLACEHOLDER_PREFIX = 'groupup'
AUTO_DURATION_MAX = {'seedance-2.5': 30, 'seedance-2.5-moderated': 30}


def current_submission():
    """{'run_id', 'workflow_id', 'node_id'} while a group run submits a node internally, else None.

    Only this module sets it; request bodies can never set it (B4 guard and
    tasks.create_task rely on that).
    """
    return _SUBMISSION.get()


@contextlib.contextmanager
def _internal_context(path='/', **kwargs):
    """A fresh app + request context for an internal, already-authorised call.

    The inner call gets its own database connection (the app teardown closes
    it); the caller's thread-local connection is set aside and restored, so a
    worker or an outer request never finds its connection closed.
    """
    import app as application
    outer = getattr(task_db._local, 'conn', None)
    if outer is not None:
        del task_db._local.conn
    try:
        with application.app.app_context():
            with application.app.test_request_context(path, **kwargs):
                from flask import session
                session['logged_in'] = True  # the run was created by a logged-in user
                yield application
    finally:
        task_db.close_db()
        if outer is not None:
            task_db._local.conn = outer


def _capabilities():
    import canvas_submit
    with _internal_context():
        return canvas_submit.live_capabilities()


def _comparable(request):
    return ({k: v for k, v in request['fields'].items() if k != 'canvas_workflow_revision'},
            [(f['field'], f['asset_id'], f['filename']) for f in request['files']], request['path'])


def _task_after(before_id, run_id, node_id):
    row = task_db.get_db().execute(
        """SELECT id FROM tasks WHERE id>? AND json_extract(params,'$.group_run_id')=?
             AND json_extract(params,'$.canvas_node_id')=? ORDER BY id DESC LIMIT 1""",
        (before_id, run_id, node_id)).fetchone()
    return row['id'] if row else None


def _request_body(workflow_id, request, open_files):
    """Werkzeug request arguments: the browser's FormData (fields then files in order) or JSON.

    Each file part carries the reference's stored MIME type (library item, or a legacy
    canvas copy), like the browser's Blob.
    """
    import canvas_media_refs
    import canvas_submit
    from werkzeug.datastructures import MultiDict
    if request['multipart']:
        data = MultiDict(list(canvas_submit.form_fields(request['fields']).items()))
        for item in request['files']:
            mime = canvas_media_refs.reference(workflow_id, item['asset_id'])[1]
            handle = item['file'].open('rb')
            open_files.append(handle)
            data.add(item['field'], (handle, item['filename'], mime))
        return dict(data=data, content_type='multipart/form-data')
    return dict(json=request['fields'])


def _write_node_task(workflow_id, node_id, task_id):
    """Write only node.task into the saved document and record it as a write-back.

    The canvas_writebacks row lets a stale editor save merge (interface C, group
    run rule in merge_stale_save) instead of getting a 409.  Returns True when written.
    """
    from canvas_writeback import ACTIVE_STATUSES
    task = task_db.get_task(task_id) or {}
    status = task.get('status') if task.get('status') in ACTIVE_STATUSES else 'pending'
    db = task_db.get_db()
    with store.write_transaction():
        row = store.workflow(workflow_id)
        document, revision = row['document'], row['revision']
        nodes, written = [], False
        for node in document.get('nodes', []):
            if isinstance(node, dict) and node.get('id') == node_id:
                current = node.get('task') if isinstance(node.get('task'), dict) else {}
                if current.get('id') == task_id:
                    return False
                node = {**node, 'task': {'id': task_id, 'status': status, 'error': None}}
                written = True
            nodes.append(node)
        if not written:
            return False
        encoded = store.validate_document({**document, 'nodes': nodes}, workflow_id)
        now = task_db.utcnow()
        if not db.execute('UPDATE canvas_workflows SET document=?, revision=revision+1, updated_at=? WHERE id=? AND revision=?',
                          (encoded, now, workflow_id, revision)).rowcount:
            return False
        db.execute('UPDATE canvas_projects SET updated_at=? WHERE id=?', (now, row['project_id']))
        db.execute('INSERT INTO canvas_writebacks VALUES (?,?,?,?,?)', (workflow_id, revision + 1, node_id, task_id, now))
    return True


def _attach(workflow_id, node_id, task_id):
    """node.task + catch-up write-back when the task already finished before node.task existed."""
    import canvas_writeback
    try:
        _write_node_task(workflow_id, node_id, task_id)
    except Exception:  # the task exists: never turn this into a resubmission or an unknown
        LOG.exception('group_run_node_task_write_failed workflow=%s node=%s task=%s', workflow_id, node_id, task_id)
        return
    task = task_db.get_task(task_id)
    if task and task['status'] not in ACTIVE_TASK:
        try:
            canvas_writeback.apply_task_result(task_id, workflow_id)
        except Exception:
            LOG.exception('group_run_catch_up_writeback_failed task=%s', task_id)


def _response_json(response):
    try:
        payload = response.get_json(silent=True)
    except Exception:
        payload = None
    return payload if isinstance(payload, dict) else {}


def submit(workflow_id, node_id, ctx):
    """canvas_group_run submitter: {'task_id', 'result_unknown'?} or raises SubmitRejected."""
    import canvas_submit
    from canvas_group_run import SubmitRejected
    run_id = ctx['run_id']
    if task_db.get_db().in_transaction:
        raise SubmitRejected('内部错误：提交时存在未完成的数据库事务，尚未提交生成')
    try:
        capabilities = _capabilities()
    except Exception:
        LOG.exception('group_run_capabilities_failed node=%s', node_id)
        raise SubmitRejected('无法读取生成服务配置，尚未提交生成')
    try:
        request = canvas_submit.assemble(workflow_id, node_id, capabilities)
        checked = canvas_submit.build_request({'id': workflow_id, 'revision': ctx.get('revision'), 'document': ctx['document']},
                                              node_id, capabilities, read_metadata=lambda asset: {'has_alpha': True},
                                              resolve_file=lambda asset: None)
    except canvas_submit.CanvasSubmitError as error:
        raise SubmitRejected(error.message)
    except store.CanvasError as error:
        raise SubmitRejected(str(error))
    if _comparable(request) != _comparable(checked):
        # The saved document changed this node's request after the run checked it (rule 6).
        raise SubmitRejected('节点在提交前被修改，尚未提交生成；请重新运行')
    open_files, response, raised = [], None, None
    try:
        body = _request_body(workflow_id, request, open_files)
    except (OSError, store.CanvasError) as error:
        for handle in open_files:
            handle.close()
        LOG.warning('group_run_reference_unreadable node=%s error=%s', node_id, error)
        raise SubmitRejected('无法读取参考素材，尚未提交生成')
    before = task_db.get_db().execute('SELECT COALESCE(MAX(id), 0) FROM tasks').fetchone()[0]
    task_db.get_db().commit()
    token = _SUBMISSION.set({'run_id': run_id, 'workflow_id': workflow_id, 'node_id': node_id})
    try:
        with _internal_context(request['path'], method='POST', **body) as application:
            try:
                response = application.app.full_dispatch_request()
            except Exception as error:  # TESTING / PROPAGATE_EXCEPTIONS re-raise view errors
                raised = error
    finally:
        _SUBMISSION.reset(token)
        for handle in open_files:
            handle.close()
    task_id = _task_after(before, run_id, node_id)
    payload = _response_json(response) if response is not None else {}
    status = response.status_code if response is not None else 500
    if task_id is None:
        if raised is None and status < 300 and payload.get('success'):
            # Accepted without a findable task row: cannot prove nothing was sent.
            raise RuntimeError('提交已受理但找不到对应任务')
        message = payload.get('error') if isinstance(payload.get('error'), str) else None
        raise SubmitRejected(message or (str(raised) if raised else '提交被拒绝，尚未创建任务'))
    _attach(workflow_id, node_id, task_id)
    task = task_db.get_task(task_id) or {}
    result = task.get('result') if isinstance(task.get('result'), dict) else {}
    reported = payload.get('db_task_id') or payload.get('task_id')
    unknown = payload.get('result_unknown') is True or (task.get('status') == 'failed' and result.get('result_unknown') is True)
    if not unknown and request['path'] == '/api/video/generate' and request['fields'].get('provider') == 'ark' \
            and (raised is not None or (status >= 300 and reported != task_id)):
        unknown = True  # the Ark POST runs inside this route; an unreported failure may have reached it
    if unknown:
        return {'task_id': task_id, 'result_unknown': True}
    return {'task_id': task_id}


# ---------------------------------------------------------------- estimation

def _planned_seconds(node):
    import canvas_submit
    params = node.get('params') or {}
    seconds = canvas_submit.js_number(params.get('duration') if params.get('duration') is not None else 5)
    if seconds == -1:
        return AUTO_DURATION_MAX.get(params.get('model'), 15)
    return seconds if isinstance(seconds, (int, float)) and seconds > 0 else None


def _preview_document(workflow_id, document, upstream):
    """In-group upstream nodes will be rerun: give each a result to resolve against.

    An upstream without a result gets a placeholder asset; video upstreams are
    counted by their planned duration, never by an old result's length.  The
    placeholders then go through the write-back's mention reconciliation (QA D3),
    so prompts and bindings read exactly as they will once the results arrive.
    """
    from canvas_reference_rebind import reconcile_reference_mentions
    original, document = document, copy.deepcopy(document)
    planned = {}
    for node in document.get('nodes') or []:
        if not isinstance(node, dict) or node.get('id') not in upstream:
            continue
        asset = node.get('asset') if isinstance(node.get('asset'), dict) else None
        if not asset or not asset.get('id'):
            asset = {'id': PLACEHOLDER_PREFIX + node['id'], 'kind': node.get('type'), 'name': node.get('title') or node['id'],
                     'url': f'/api/canvas/workflows/{workflow_id}/assets/placeholder'}
            node['asset'] = asset
        if node.get('type') == 'video':
            planned[asset['id']] = _planned_seconds(node)
    document['nodes'] = reconcile_reference_mentions(original, document)
    return document, planned


def _image_estimate(fields, provider, image_count):
    import app as application
    import canvas_submit
    import cost_estimate
    adapter = fields['provider']
    if adapter not in cost_estimate.IMAGE_PROVIDERS:
        return {'known': False, 'usd': None, 'reason': 'no_price_data'}
    seedream55 = adapter == 'ark' and canvas_submit.is_seedream55(provider.get('capability_model') or provider.get('model'))
    ratio = str(fields.get('aspect_ratio') or '1:1').strip().lower()
    resolution = str(fields.get('resolution') or '1K').upper()
    width, height = fields.get('custom_width'), fields.get('custom_height')
    try:
        if adapter == 'cupsy' and ratio != 'custom':
            size = application.CUPSY_SEEDREAM_SIZE_MAP[resolution][ratio]
        else:
            size = application.resolve_seedream_pro_size(ratio, resolution, width, height, seedream55=seedream55)
    except (KeyError, ValueError, TypeError):
        return {'known': False, 'usd': None, 'reason': 'no_estimate_snapshot'}
    params = {'size': size, 'aspect_ratio': ratio, 'resolution': resolution, 'custom_width': width, 'custom_height': height}
    dimensions = cost_estimate._image_size(adapter, params)
    if not dimensions:
        return {'known': False, 'usd': None, 'reason': 'no_estimate_snapshot'}
    family = cost_estimate.SEEDREAM_50_PRO if adapter == 'cupsy' else (
        cost_estimate.SEEDREAM_55 if seedream55 else cost_estimate.SEEDREAM_50_PRO)
    result = cost_estimate.estimate_image_cost(family, dimensions[0], dimensions[1], image_count, size_assumed=dimensions[2])
    if not result['known']:
        return {'known': False, 'usd': None, 'reason': result.get('reason') or 'unknown'}
    return {'known': True, 'usd': result['maximum_cost'], 'reason': None}


def _video_estimate(fields, durations):
    import cost_estimate
    if fields['provider'] not in cost_estimate.VIDEO_PROVIDERS or fields.get('model') not in cost_estimate.VIDEO_MODELS:
        return {'known': False, 'usd': None, 'reason': 'no_price_data'}
    result = cost_estimate.estimate_video_cost(
        model=fields['model'], provider=fields['provider'], resolution=fields.get('resolution'),
        ratio=fields.get('ratio') or 'adaptive', duration=fields.get('duration'), fast=bool(fields.get('fast')),
        reference_video_durations=[] if fields.get('video_mode') == 'keyframe' else durations)
    # A range (Auto duration) is compared by its maximum, so the confirmation never under-states it.
    return {'known': True, 'usd': result['maximum_cost'], 'reason': None}


def estimate(workflow, node, ctx):
    """canvas_group_run estimator: {'known', 'usd', 'reason'}; unknown is never zero."""
    import canvas_submit
    import cost_estimate
    if node.get('type') == 'audio':
        return {'known': False, 'usd': None, 'reason': 'no_price_data'}
    if node.get('type') not in ('image', 'video'):
        return {'known': False, 'usd': None, 'reason': 'not_generation'}
    workflow_id = workflow['id']
    document, planned = ctx.get('document') or workflow['document'], {}
    if ctx.get('phase') == 'preview':
        document, planned = _preview_document(workflow_id, document, set(ctx.get('run_upstream') or []))

    def resolve_file(asset):
        if asset.get('id') in planned or str(asset.get('id', '')).startswith(PLACEHOLDER_PREFIX):
            return None
        import canvas_media_refs
        return canvas_media_refs.reference_of(workflow_id, asset)[0]

    try:
        capabilities = _capabilities()
        request = canvas_submit.build_request({'id': workflow_id, 'revision': workflow.get('revision'), 'document': document},
                                              node['id'], capabilities, read_metadata=lambda asset: {'has_alpha': True},
                                              resolve_file=resolve_file)
    except canvas_submit.CanvasSubmitError:
        return {'known': False, 'usd': None, 'reason': 'invalid_node'}
    fields = request['fields']
    provider = canvas_submit.selected_provider(capabilities, node.get('providerSelection'), node.get('type')) or {}
    if node['type'] == 'image':
        return _image_estimate(fields, provider, sum(1 for f in request['files'] if f['kind'] == 'image'))
    durations = []
    for item in request['files']:
        if item['kind'] != 'video':
            continue
        if item['asset_id'] in planned:
            durations.append(planned[item['asset_id']])
        else:
            durations.append(cost_estimate.probe_duration(str(item['file'])) if item['file'] else None)
    return _video_estimate(fields, durations)


def register():
    import canvas_group_run
    canvas_group_run.set_submitter(submit)
    canvas_group_run.set_estimator(estimate)
