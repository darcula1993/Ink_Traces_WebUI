"""GROUP-RUN-20261115 D3 rework: server port of reconcileReferenceMentions.

Shared cases (server/tests/data/canvas_rebind_cases.json) carry the browser's own output
(client/tests/canvasRebindParity.test.js runs the same file); the server port must match
them node by node.  Write-back integration: a closed page now gets the same prompt and
bindings an open page would save.
"""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

import canvas_store as store
import canvas_writeback
import storage
import tasks as task_db
from canvas_reference_rebind import reconcile_reference_mentions

CASES = json.loads((Path(__file__).parent / 'data' / 'canvas_rebind_cases.json').read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_shared_case_matches_browser(case):
    assert reconcile_reference_mentions(case['before'], case['after']) == case['expected']


def test_unchanged_document_is_returned_as_is():
    case = next(c for c in CASES if c['name'] == 'd3_unbound_first_result_before_external')
    assert reconcile_reference_mentions(case['before'], case['before']) == case['before']['nodes']


def png(color):
    data = io.BytesIO()
    Image.new('RGB', (4, 4), color).save(data, format='PNG')
    return data.getvalue()


@pytest.fixture
def canvas(isolated_backend, monkeypatch):
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(isolated_backend / 'canvas_assets'))
    project = store.create_project('D3')
    return store.create_workflow(project['id'], '画布')['id']


def finish(task_id, color='blue'):
    directory = Path(storage.OUTPUT_DIR) / 'image' / str(task_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'image_0.png'
    path.write_bytes(png(color))
    task_db.register_asset(task_id, 'output_image', str(path), 'image/png')
    task_db.complete_task(task_id, {'images': [str(path)]})
    return canvas_writeback.apply_task_result(task_id)


def d3_canvas(wid, mentions=None):
    ext = store.save_asset(wid, io.BytesIO(png('red')), 'ext.png')
    tid = task_db.create_task('image', 'p', {'canvas_workflow_id': wid, 'canvas_node_id': 'a'})
    b = {'id': 'b', 'type': 'image', 'title': 'b', 'x': 0, 'y': 0, 'text': '@图片1 的风格', 'params': {},
         'providerSelection': {'provider': 'ark', 'profile_id': None}}
    if mentions:
        b['referenceMentions'] = {'@图片1': ext['id']}
    nodes = [{'id': 'a', 'type': 'image', 'title': 'a', 'x': 0, 'y': 0, 'text': '猫', 'params': {},
              'providerSelection': {'provider': 'ark', 'profile_id': None}, 'task': {'id': tid, 'status': 'pending', 'error': None}},
             {'id': 'src', 'type': 'asset', 'title': 'src', 'x': 0, 'y': 0, 'asset': ext, 'candidates': [ext], 'selectedCandidateId': ext['id']},
             b]
    wf = store.workflow(wid)
    store.update_workflow(wid, wf['title'], {**wf['document'], 'nodes': nodes,
                                             'edges': [{'id': 'e1', 'source': 'a', 'target': 'b'}, {'id': 'e2', 'source': 'src', 'target': 'b'}]},
                          wf['revision'])
    return ext, tid


@pytest.mark.parametrize('bound', [False, True])
def test_closed_page_write_back_renumbers_like_open_page(canvas, bound):
    import canvas_submit
    ext, tid = d3_canvas(canvas, bound)
    revision = store.workflow(canvas)['revision']
    assert finish(tid) == {canvas: revision + 1}
    document = store.workflow(canvas)['document']
    b = next(n for n in document['nodes'] if n['id'] == 'b')
    assert b['text'] == '@图片2 的风格' and b['referenceMentions'] == {'@图片2': ext['id']}
    rows = task_db.get_db().execute('SELECT node_id FROM canvas_writebacks WHERE workflow_id=? AND revision=?',
                                    (canvas, revision + 1)).fetchall()
    assert sorted(r['node_id'] for r in rows) == ['a', 'b']
    # The request now points @图片2 at the external reference (second file), with no mention issue.
    inputs = canvas_submit.resolve_node_inputs(b, document['nodes'], document['edges'])
    assert inputs['issues'] == [] and [a['id'] for a in inputs['assets']][1] == ext['id']


def test_stale_open_page_save_rederives_the_same_rebinding(canvas):
    ext, tid = d3_canvas(canvas)
    stale = store.workflow(canvas)
    finish(tid)
    document = stale['document']
    next(n for n in document['nodes'] if n['id'] == 'src')['x'] = 50
    saved, merged = store.update_workflow(canvas, stale['title'], document, stale['revision'], with_merge=True)
    b = next(n for n in saved['document']['nodes'] if n['id'] == 'b')
    assert merged and b['text'] == '@图片2 的风格' and b['referenceMentions'] == {'@图片2': ext['id']}


def test_status_only_write_back_does_not_touch_prompts(canvas):
    ext, tid = d3_canvas(canvas)
    task_db.fail_task(tid, '失败')
    canvas_writeback.apply_task_result(tid)
    b = next(n for n in store.workflow(canvas)['document']['nodes'] if n['id'] == 'b')
    assert b['text'] == '@图片1 的风格' and 'referenceMentions' not in b


# Group run preview / submit with a bound mention (D3 second symptom: invalid_node)

@pytest.fixture
def group_env(isolated_backend, monkeypatch):
    import app as application
    import canvas_group_submit
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(isolated_backend / 'canvas_assets'))

    def guard(*args, **kwargs):
        raise AssertionError('provider must not be called')
    for name in ('get', 'post', 'put', 'delete', 'request'):
        if hasattr(application.HTTP, name):
            monkeypatch.setattr(application.HTTP, name, guard)
    monkeypatch.setattr('requests.Session.request', guard)
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {'api_key': 'test-key', 'endpoint': 'https://provider.invalid', 'model': 'test-model'})
    canvas_group_submit.register()
    return store.create_workflow(store.create_project('D3g')['id'], '画布')['id'], application.app.test_client()


def test_group_preview_and_submit_with_bound_mention(group_env):
    import canvas_group_run as group_run
    wid, client = group_env
    ext = store.save_asset(wid, io.BytesIO(png('red')), 'ext.png')
    gen = lambda node_id, text, **extra: {'id': node_id, 'type': 'image', 'title': node_id, 'x': 0, 'y': 0, 'text': text,
                                          'params': {}, 'providerSelection': {'provider': 'ark', 'profile_id': None}, **extra}
    nodes = [gen('a', '猫'), {'id': 'src', 'type': 'asset', 'title': 'src', 'x': 0, 'y': 0, 'asset': ext, 'candidates': [ext], 'selectedCandidateId': ext['id']},
             gen('b', '@图片1 的风格', referenceMentions={'@图片1': ext['id']})]
    wf = store.workflow(wid)
    store.update_workflow(wid, wf['title'], {**wf['document'], 'nodes': nodes, 'edges': [
        {'id': 'e1', 'source': 'a', 'target': 'b'}, {'id': 'e2', 'source': 'src', 'target': 'b'}],
        'groups': [{'id': 'g', 'title': '节点组1', 'nodeIds': ['a', 'b']}]}, wf['revision'])
    url = f'/api/canvas/workflows/{wid}'
    preview = client.post(f'{url}/groups/g/run-preview', json={'revision': store.workflow(wid)['revision']}).json['preview']
    b_estimate = next(n for n in preview['nodes'] if n['node_id'] == 'b')['estimate']
    assert b_estimate['known'] is True and b_estimate['reason'] is None  # was unknown/invalid_node
    response = client.post(url + '/group-runs', json={'group_id': 'g', 'revision': preview['revision'], 'preview_token': preview['preview_token']})
    assert response.status_code == 201, response.json
    run = response.json['run']
    a_task = next(n for n in run['nodes'] if n['node_id'] == 'a')['task_id']
    finish(a_task)
    run = group_run.on_task_terminal(a_task)
    b = next(n for n in run['nodes'] if n['node_id'] == 'b')
    # Submit phase with the real upstream result: bound mention follows ext as @图片2, no rejection.
    assert b['status'] == 'submitted' and b['reason'] is None, b
    task = task_db.get_task(b['task_id'])
    assert task['prompt'] == '@图片2 的风格'
    inputs = [a['path'] for a in task_db.list_assets(b['task_id']) if a['kind'] == 'input_image']
    ext_bytes = store.asset_path(store.get_asset(wid, ext['id'])).read_bytes()
    assert len(inputs) == 2 and Path(inputs[1]).read_bytes() == ext_bytes


def test_keyframe_and_multi_result_writeback_never_duplicate_mentions(canvas):
    ext = store.save_asset(canvas, io.BytesIO(png('red')), 'ext.png')
    tid = task_db.create_task('image', 'first frame', {'canvas_workflow_id': canvas, 'canvas_node_id': 'a'})
    nodes = [
        {'id': 'a', 'type': 'image', 'title': 'a', 'x': 0, 'y': 0, 'text': '首帧', 'params': {},
         'providerSelection': {'provider': 'ark', 'profile_id': None}, 'task': {'id': tid, 'status': 'pending', 'error': None}},
        {'id': 'src', 'type': 'asset', 'title': 'src', 'x': 0, 'y': 200, 'asset': ext, 'candidates': [ext], 'selectedCandidateId': ext['id']},
        {'id': 'v', 'type': 'video', 'title': 'v', 'x': 300, 'y': 0, 'text': '从 @图片1 到 @图片2',
         'params': {'video_mode': 'keyframe'}, 'providerSelection': {'provider': 'ark', 'profile_id': None}},
    ]
    wf = store.workflow(canvas)
    store.update_workflow(canvas, wf['title'], {**wf['document'], 'nodes': nodes, 'edges': [
        {'id': 'e1', 'source': 'a', 'target': 'v'}, {'id': 'e2', 'source': 'src', 'target': 'v'}]}, wf['revision'])
    finish(tid)
    document = store.workflow(canvas)['document']
    v = next(n for n in document['nodes'] if n['id'] == 'v')
    a = next(n for n in document['nodes'] if n['id'] == 'a')
    assert v['text'] == '从 @图片2 到 @图片1'
    assert v['referenceMentions'] == {'@图片2': ext['id'], '@图片1': a['asset']['id']}
