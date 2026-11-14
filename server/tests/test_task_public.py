"""FIX-B1-20261114: task API responses never ship signed Provider URLs."""
import json

import app as application
import tasks as task_db
from task_public import mask_text, mask_url, public_task

SIGNED = ('https://bucket.tos.invalid/out/img.png'
          '?X-Tos-Algorithm=TOS4-HMAC-SHA256&X-Tos-Credential=FAKECRED%2F20261114'
          '&X-Tos-Signature=fakesignaturevalue0000&X-Tos-Expires=86400')
SIGNED_VIDEO = 'https://video.tos.invalid:8443/v.mp4?X-Tos-Signature=fakesig1111&token=faketok'
LEAK_MARKERS = ('X-Tos', 'FAKECRED', 'fakesignature', 'fakesig1111', 'faketok', '/out/img.png', 'v.mp4')


def _assert_clean(payload):
    text = json.dumps(payload, ensure_ascii=False)
    for marker in LEAK_MARKERS:
        assert marker not in text, marker


def test_mask_url_keeps_only_scheme_and_host():
    assert mask_url(SIGNED) == 'https://bucket.tos.invalid/…'
    assert mask_url(SIGNED_VIDEO) == 'https://video.tos.invalid:8443/…'
    assert mask_url('/api/tasks/1/file/image_0.png') == '/api/tasks/1/file/image_0.png'
    assert mask_url('https://') == '远端结果'
    assert mask_url(None) is None


def test_mask_text_hides_embedded_urls_and_signed_queries():
    text = f'尾帧下载失败: {SIGNED} 以及 url: /v.mp4?X-Tos-Signature=abc&x=1 结束'
    masked = mask_text(text)
    assert 'https://bucket.tos.invalid/…' in masked
    assert '结束' in masked and '尾帧下载失败' in masked
    for marker in ('X-Tos', 'FAKECRED', 'abc&x'):
        assert marker not in masked


def test_public_task_does_not_mutate_stored_task():
    task = {'id': 1, 'result': {'source_urls': [SIGNED]}, 'params': {'ref_video_urls': ['https://own.invalid/v.mp4?k=1']}}
    public = public_task(task)
    assert public['result']['source_urls'] == ['https://bucket.tos.invalid/…']
    assert task['result']['source_urls'] == [SIGNED]
    # params are user inputs reused by "复用参数"; untouched.
    assert public['params'] == task['params']


def _signed_task():
    task_id = task_db.create_task('image', 'signed url task', {'model': 'seedream'})
    task_db.complete_task(task_id, {
        'local_images': [f'/api/tasks/{task_id}/file/image_0.png'],
        'local_thumbnails': [f'/api/tasks/{task_id}/file/thumb_0.webp'],
        'source_urls': [SIGNED],
        'videos': [{'video_url': SIGNED_VIDEO, 'video_type': 'mp4'}],
        'images': [{'image_url': SIGNED}],
        'layers': [{'z_index': 1, 'source_url': SIGNED, 'local_url': f'/api/tasks/{task_id}/file/l.png'}],
    })
    return task_id


def test_task_detail_and_mutation_responses_mask_provider_urls():
    task_id = _signed_task()
    client = application.app.test_client()
    detail = client.get(f'/api/tasks/{task_id}').get_json()['task']
    _assert_clean(detail)
    assert detail['result']['source_urls'] == ['https://bucket.tos.invalid/…']
    assert detail['result']['videos'][0]['video_url'] == 'https://video.tos.invalid:8443/…'
    assert detail['result']['layers'][0]['source_url'] == 'https://bucket.tos.invalid/…'
    assert detail['result']['local_images'] == [f'/api/tasks/{task_id}/file/image_0.png']

    favorite = client.patch(f'/api/tasks/{task_id}/favorite', json={'favorite': True}).get_json()
    _assert_clean(favorite)
    groups = client.patch(f'/api/tasks/{task_id}/favorite-groups', json={'group_ids': []}).get_json()
    _assert_clean(groups)
    _assert_clean(client.get('/api/tasks?type=image').get_json())
    _assert_clean(client.get(f'/api/tasks/status?ids={task_id}').get_json())

    # Worker / write-back / download code still read the stored, unmasked row.
    assert task_db.get_task(task_id)['result']['source_urls'] == [SIGNED]


def test_failed_task_error_text_is_masked_in_list_status_and_detail():
    task_id = task_db.create_task('video', 'signed error task', {'model': 'seedance'})
    task_db.fail_task(task_id, f'视频下载失败: {SIGNED_VIDEO}')
    client = application.app.test_client()
    for payload in (
        client.get(f'/api/tasks/{task_id}').get_json(),
        client.get('/api/tasks?type=video').get_json(),
        client.get(f'/api/tasks/status?ids={task_id}').get_json(),
    ):
        _assert_clean(payload)
    assert '视频下载失败: https://video.tos.invalid:8443/…' == client.get(f'/api/tasks/{task_id}').get_json()['task']['error']


def _canvas_failed_task(monkeypatch, tmp_path):
    import canvas_store as store
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(tmp_path / 'canvas_assets'))
    wf = store.create_workflow(store.create_project('p')['id'], 'c')
    with application.app.test_request_context('/', method='POST', json={'canvas_workflow_id': wf['id']}):
        task_id = task_db.create_task('image', 'p', {}, status='pending')
    node = {'id': 'n1', 'type': 'image', 'title': 'n1', 'x': 0, 'y': 0, 'text': '',
            'task': {'id': task_id, 'status': 'pending', 'error': None}}
    current = store.workflow(wf['id'])
    store.update_workflow(wf['id'], current['title'], {**current['document'], 'nodes': [node]}, current['revision'])
    return store, wf, task_id


def test_canvas_writeback_stores_masked_error_and_task_sync_is_clean(monkeypatch, tmp_path):
    """FIX-B1 D1: write-back never puts a signed URL into the canvas document."""
    import canvas_writeback
    store, wf, task_id = _canvas_failed_task(monkeypatch, tmp_path)
    task_db.fail_task(task_id, f'生成图片保存失败: 403 Client Error: Forbidden for url: {SIGNED}')
    assert canvas_writeback.apply_task_result(task_id) == {wf['id']: store.workflow(wf['id'])['revision']}
    stored = store.workflow(wf['id'])['document']['nodes'][0]['task']
    assert stored['status'] == 'failed'
    assert stored['error'] == '生成图片保存失败: 403 Client Error: Forbidden for url: https://bucket.tos.invalid/…'
    _assert_clean(stored)
    client = application.app.test_client()
    sync = client.post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [task_id]}).get_json()
    _assert_clean(sync)
    assert sync['nodes']['n1']['task']['status'] == 'failed'
    # Idempotent: a second write-back changes nothing.
    assert canvas_writeback.apply_task_result(task_id) == {}
    # The task row itself keeps the raw provider text for diagnosis/retry.
    assert SIGNED in task_db.get_task(task_id)['error']


def test_canvas_workflow_responses_mask_legacy_unmasked_errors(monkeypatch, tmp_path):
    """FIX-B1 D1: documents written before the fix are masked in every response."""
    store, wf, task_id = _canvas_failed_task(monkeypatch, tmp_path)
    current = store.workflow(wf['id'])
    legacy = {**current['document']['nodes'][0], 'task': {'id': task_id, 'status': 'failed', 'error': f'视频下载失败: {SIGNED_VIDEO}'}}
    store.update_workflow(wf['id'], current['title'], {**current['document'], 'nodes': [legacy]}, current['revision'])
    client = application.app.test_client()
    got = client.get(f"/api/canvas/workflows/{wf['id']}").get_json()
    _assert_clean(got)
    assert got['workflow']['document']['nodes'][0]['task']['error'] == '视频下载失败: https://video.tos.invalid:8443/…'
    workflow = got['workflow']
    saved = client.put(f"/api/canvas/workflows/{wf['id']}", json={'title': workflow['title'], 'document': workflow['document'], 'revision': workflow['revision']})
    assert saved.status_code == 200
    _assert_clean(saved.get_json())
    _assert_clean(client.post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [task_id]}).get_json())


def test_layer_project_list_and_detail_mask_current_task(monkeypatch):
    """FIX-B1 D2: embedded current_task / revision results carry no signed URLs."""
    task_id = _signed_task()
    project_id = task_db.create_layer_project('layer', 'a.png', None, {})
    task_db.update_layer_project(project_id, current_task_id=task_id)
    failed_id = task_db.create_task('layer', 'p', {})
    task_db.fail_task(failed_id, f'图层下载失败: {SIGNED}')
    failed_project = task_db.create_layer_project('layer2', 'b.png', None, {})
    task_db.update_layer_project(failed_project, current_task_id=failed_id)
    client = application.app.test_client()
    listing = client.get('/api/layer/projects').get_json()
    _assert_clean(listing)
    by_id = {item['id']: item for item in listing['projects']}
    assert by_id[project_id]['current_task']['result']['layers'][0]['local_url'] == f'/api/tasks/{task_id}/file/l.png'
    assert by_id[failed_project]['current_task']['error'] == '图层下载失败: https://bucket.tos.invalid/…'
    for pid in (project_id, failed_project):
        detail = client.get(f'/api/layer/projects/{pid}').get_json()
        _assert_clean(detail)
    assert task_db.get_layer_project(project_id)['current_task']['result']['source_urls'] == [SIGNED]


def test_result_text_fields_mask_embedded_urls():
    public = public_task({'id': 1, 'result': {'error_details': {'message': f'failed at {SIGNED} done'}, 'local_images': ['/api/tasks/1/file/a.png']}})
    assert public['result']['error_details']['message'] == 'failed at https://bucket.tos.invalid/… done'
    assert public['result']['local_images'] == ['/api/tasks/1/file/a.png']
