"""EP-MASK-20261115: Ark endpoint (接入点) IDs never reach a client in error texts.

Provider errors such as Ark's 404 "model or endpoint ... does not exist" echo the
endpoint ID.  New errors are masked where the app extracts them; rows and canvas
documents stored before the fix are masked on output.  FAKE_EP is an obvious
test value, never a real endpoint.
"""
import json

import pytest

import app as application
import tasks as task_db
import worker
from billing_support import (  # noqa: F401  (fixtures)
    Response, assert_known_failure, billing_env, image_task, posts, run_until_idle, submit_video,
)
from task_public import ENDPOINT_MASK, mask_endpoint_ids, mask_text, public_task

FAKE_EP = 'ep-20990101000000-maskprobe'  # secret-scan: allow
FAKE_EP_M = 'ep-m-20990101000000-maskprobe'  # secret-scan: allow
ARK_404 = f'The model or endpoint {FAKE_EP} does not exist or you do not have access to it.'
SIGNED = 'https://bucket.tos.invalid/out/v.mp4?X-Tos-Signature=fakesig2222&token=faketok'


def _clean(*payloads):
    text = json.dumps(payloads, ensure_ascii=False)
    assert 'maskprobe' not in text
    assert 'fakesig2222' not in text and 'faketok' not in text


def _client():
    return application.app.test_client()


def _public_views(task_id, task_type):
    client = _client()
    detail = client.get(f'/api/tasks/{task_id}').get_json()
    status = client.get(f'/api/tasks/status?ids={task_id}').get_json()
    listing = client.get(f'/api/tasks?type={task_type}').get_json()
    ledger = client.get('/api/cost-ledger').get_json()
    _clean(detail, status, listing, ledger)
    return detail['task'], status['tasks'][0]


# ------------------------------------------------------------------ unit (acceptance 3)

def test_mask_replaces_endpoint_ids_only():
    assert mask_endpoint_ids(ARK_404) == ARK_404.replace(FAKE_EP, ENDPOINT_MASK)
    assert mask_text(f'model={FAKE_EP_M},x') == 'model=ep-***,x'
    assert mask_text(f'{FAKE_EP.upper()}') == ENDPOINT_MASK
    for text in ('step-by-step', 'ep-1 第一集', 'ep-2026 片段', 'deep-20990101000000-abc',
                 'keep-20990101000000-x', 'EP-12-final', 'ep-test', ''):
        assert mask_text(text) == text
    assert mask_endpoint_ids(None) is None and mask_endpoint_ids(3) == 3


def test_signed_url_masking_does_not_regress_alongside_endpoint_ids():
    masked = mask_text(f'{ARK_404} 下载失败: {SIGNED} url: /x?X-Tos-Signature=abc&x=1')
    assert 'ep-***' in masked and 'https://bucket.tos.invalid/…' in masked
    assert 'maskprobe' not in masked and 'X-Tos' not in masked and 'abc&x' not in masked


def test_public_task_masks_result_text_but_not_prompt_or_params():
    task = {'id': 1, 'prompt': f'镜头 {FAKE_EP}', 'params': {'note': FAKE_EP},
            'error': ARK_404, 'result': {'error_details': {'message': ARK_404}}}
    public = public_task(task)
    assert public['error'] == ARK_404.replace(FAKE_EP, 'ep-***')
    assert public['result']['error_details']['message'] == public['error']
    assert public['prompt'] == task['prompt'] and public['params'] == task['params']
    assert task['error'] == ARK_404  # stored copy untouched


# ------------------------------------------------------------------ new errors (acceptance 1)

def test_ark_image_sync_404_is_masked_at_source(billing_env, posts):
    posts.install(Response(payload={'error': {'message': ARK_404, 'code': 'InvalidEndpointOrModel.NotFound'}},
                           status_code=404))
    task_id = image_task('ark')
    run_until_idle(worker.Worker())
    assert posts.count == 1
    stored = assert_known_failure(task_id)
    assert stored['error'] == ARK_404.replace(FAKE_EP, 'ep-***')
    assert 'maskprobe' not in json.dumps(stored, ensure_ascii=False)
    detail, status = _public_views(task_id, 'image')
    assert detail['error'] == status['error'] == stored['error']
    for log in billing_env.iterdir():
        assert 'maskprobe' not in log.read_text(encoding='utf-8')


def test_ark_video_submit_rejection_is_masked(billing_env, posts):
    posts.install(Response(payload={'error': {'message': ARK_404}}, status_code=404))
    response = submit_video()
    assert response.status_code == 404
    body = response.get_json()
    _clean(body)
    stored = assert_known_failure(body['db_task_id'])
    assert stored['error'] == ARK_404.replace(FAKE_EP, 'ep-***')
    _public_views(body['db_task_id'], 'video')


class _Get:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {}

    def json(self):
        return self._payload


@pytest.mark.parametrize(('provider', 'kind', 'payload', 'status_code'), [
    ('ark', 'video', {'status': 'failed', 'error': {'message': ARK_404}}, 200),
    ('ark', 'video', {'error': {'message': ARK_404}}, 404),
    ('cupsy', 'video', {'status': 'failed', 'message': ARK_404}, 200),
    ('cupsy', 'audio', {'status': 'failed', 'error': {'message': ARK_404}}, 200),
])
def test_async_poll_failures_are_masked(billing_env, monkeypatch, provider, kind, payload, status_code):
    params = {'provider': provider, 'output_format': 'mp3' if kind == 'audio' else 'mp4'}
    task_id = task_db.create_task(kind, 'mask', params, provider=provider,
                                  external_task_id=f'{kind}_remote_mask', status='processing')
    monkeypatch.setattr(application.HTTP, 'get', lambda *_a, **_k: _Get(payload, status_code))
    runner = worker.Worker()
    runner.process(task_db.claim_next_task(runner.worker_id, task_types=('video', 'audio')))
    stored = task_db.get_task(task_id)
    assert stored['status'] == 'failed'
    assert not (stored.get('result') or {}).get('result_unknown')
    assert 'ep-***' in stored['error'] and 'maskprobe' not in stored['error']
    _public_views(task_id, kind)


# ------------------------------------------------------------------ stored history (acceptance 2)

def test_legacy_task_rows_are_masked_on_output_only():
    task_id = task_db.create_task('video', 'legacy', {'model': 'seedance'})
    task_db.fail_task(task_id, 'placeholder', {'error_details': {'message': ARK_404}})
    # Simulate a legacy DB row written before fail_task began masking ep- IDs at persistence.
    raw_error = f'{ARK_404} {SIGNED}'
    task_db.get_db().execute('UPDATE tasks SET error = ? WHERE id = ?', (raw_error, task_id))
    task_db.get_db().commit()
    detail, status = _public_views(task_id, 'video')
    assert detail['error'].startswith('The model or endpoint ep-*** does not exist')
    assert detail['result']['error_details']['message'] == ARK_404.replace(FAKE_EP, 'ep-***')
    assert status['error'] == detail['error']
    assert FAKE_EP in task_db.get_task(task_id)['error']  # legacy row not rewritten on read


def _canvas_with_task(monkeypatch, tmp_path, task_error):
    import canvas_store as store
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(tmp_path / 'canvas_assets'))
    wf = store.create_workflow(store.create_project('p')['id'], 'c')
    with application.app.test_request_context('/', method='POST', json={'canvas_workflow_id': wf['id']}):
        task_id = task_db.create_task('video', 'p', {}, status='pending')
    node = {'id': 'n1', 'type': 'video', 'title': 'n1', 'x': 0, 'y': 0, 'text': '',
            'task': {'id': task_id, 'status': 'failed' if task_error else 'pending', 'error': task_error}}
    current = store.workflow(wf['id'])
    store.update_workflow(wf['id'], current['title'], {**current['document'], 'nodes': [node]}, current['revision'])
    return store, wf, task_id


def test_canvas_writeback_and_task_sync_mask_raw_task_error(monkeypatch, tmp_path):
    import canvas_writeback
    store, wf, task_id = _canvas_with_task(monkeypatch, tmp_path, None)
    task_db.fail_task(task_id, ARK_404)  # e.g. a row written before this fix
    canvas_writeback.apply_task_result(task_id)
    stored = store.workflow(wf['id'])['document']['nodes'][0]['task']
    assert stored['status'] == 'failed' and stored['error'] == ARK_404.replace(FAKE_EP, 'ep-***')
    sync = _client().post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [task_id]}).get_json()
    _clean(sync)
    assert sync['nodes']['n1']['task']['error'] == stored['error']


def test_legacy_canvas_documents_are_masked_in_every_response(monkeypatch, tmp_path):
    store, wf, task_id = _canvas_with_task(monkeypatch, tmp_path, ARK_404)
    task_db.fail_task(task_id, ARK_404)
    client = _client()
    got = client.get(f"/api/canvas/workflows/{wf['id']}").get_json()
    _clean(got)
    assert got['workflow']['document']['nodes'][0]['task']['error'] == ARK_404.replace(FAKE_EP, 'ep-***')
    workflow = got['workflow']
    saved = client.put(f"/api/canvas/workflows/{wf['id']}",
                       json={'title': workflow['title'], 'document': workflow['document'], 'revision': workflow['revision']})
    assert saved.status_code == 200
    _clean(saved.get_json())
    _clean(client.post(f"/api/canvas/workflows/{wf['id']}/task-sync", json={'task_ids': [task_id]}).get_json())
    _clean(client.get('/api/cost-ledger').get_json())
