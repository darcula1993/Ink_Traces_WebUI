"""GROUP-RUN-20261115 B3: server-side group-run submission and re-estimation.

The real submitter/estimator (canvas_group_submit) drive the real generation
routes.  Providers are mocked: every HTTP method raises unless a test installs
its own fake, and no task is ever executed by a worker (completion is
simulated, then the real canvas write-back and on_task_terminal run).
"""
import hashlib
import io
import json
import subprocess
from pathlib import Path

import pytest
import requests
from PIL import Image

import app as application
import canvas_group_run as group_run
import canvas_group_submit
import canvas_store as store
import canvas_submit
import canvas_writeback
import cost_estimate
import storage
import tasks as task_db
from test_generation import FakeResponse


def png(color='red'):
    data = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(data, format='PNG')
    return data.getvalue()


@pytest.fixture(scope='module')
def mp4(tmp_path_factory):
    path = tmp_path_factory.mktemp('group-submit-media') / 'clip.mp4'
    subprocess.run(['/usr/bin/ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=16x16:r=5',
                    '-t', '0.2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
    return path.read_bytes()


class Wire:
    """Records what each generation view actually received (the provider-facing request input)."""
    ENDPOINTS = ('generate', 'video_generate', 'generate_audio')

    def __init__(self, monkeypatch):
        self.calls = []
        for endpoint in self.ENDPOINTS:
            original = application.app.view_functions[endpoint]
            monkeypatch.setitem(application.app.view_functions, endpoint, self._wrap(original))

    def _wrap(self, original):
        def view(*args, **kwargs):
            from flask import request
            files = []
            for key, item in request.files.items(multi=True):
                content = item.stream.read()
                item.stream.seek(0)
                files.append((key, item.filename, item.mimetype, hashlib.sha256(content).hexdigest()))
            self.calls.append({'path': request.path, 'multipart': request.mimetype == 'multipart/form-data',
                               'form': list(request.form.items(multi=True)), 'json': request.get_json(silent=True),
                               'files': files})
            return original(*args, **kwargs)
        return view


def without_revision(call):
    call = dict(call)
    call['form'] = [(k, v) for k, v in call['form'] if k != 'canvas_workflow_revision']
    if isinstance(call['json'], dict):
        call['json'] = {k: v for k, v in call['json'].items() if k != 'canvas_workflow_revision'}
    return call


class Env:
    def __init__(self, workflow_id):
        self.wid = workflow_id
        self.client = application.app.test_client()
        self.url = '/api/canvas/workflows/' + workflow_id

    def doc(self):
        return store.workflow(self.wid)['document']

    @staticmethod
    def node(doc, node_id):
        return next(n for n in doc['nodes'] if n['id'] == node_id)

    def save(self, nodes, edges, members):
        wf = store.workflow(self.wid)
        doc = {**wf['document'], 'nodes': nodes,
               'edges': [{'id': f'e{i}', 'source': s, 'target': t} for i, (s, t) in enumerate(edges)],
               'groups': [{'id': 'g', 'title': '节点组1', 'nodeIds': members}]}
        store.update_workflow(self.wid, wf['title'], doc, wf['revision'])

    def asset(self, data, name):
        return store.save_asset(self.wid, io.BytesIO(data), name)

    def preview(self):
        response = self.client.post(f'{self.url}/groups/g/run-preview', json={'revision': store.workflow(self.wid)['revision']})
        assert response.status_code == 200, response.json
        return response.json['preview']

    def start(self):
        p = self.preview()
        response = self.client.post(self.url + '/group-runs', json={'group_id': 'g', 'revision': p['revision'], 'preview_token': p['preview_token']})
        assert response.status_code == 201, response.json
        return response.json['run']

    def run(self, run_id):
        return self.client.get(f'{self.url}/group-runs/{run_id}').json['run']

    @staticmethod
    def entry(run, node_id):
        return next(n for n in run['nodes'] if n['node_id'] == node_id)

    def finish(self, task_id, kind='image', data=None):
        directory = Path(storage.OUTPUT_DIR) / kind / str(task_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ('image_0.png' if kind == 'image' else 'video_0.mp4')
        path.write_bytes(data or png('blue'))
        task_db.register_asset(task_id, 'output_' + kind, str(path), 'image/png' if kind == 'image' else 'video/mp4')
        task_db.complete_task(task_id, {'images' if kind == 'image' else 'videos': [str(path)]})
        canvas_writeback.apply_task_result(task_id)
        return group_run.on_task_terminal(task_id)


def generation(node_id, kind, text, provider='ark', **params):
    return {'id': node_id, 'type': kind, 'title': node_id, 'x': 0, 'y': 0, 'text': text, 'params': params,
            'providerSelection': {'provider': provider, 'profile_id': None}}


@pytest.fixture
def env(isolated_backend, monkeypatch):
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(isolated_backend / 'canvas_assets'))

    def guard(*args, **kwargs):
        raise AssertionError('provider must not be called')
    for name in ('get', 'post', 'put', 'delete', 'request'):
        if hasattr(application.HTTP, name):
            monkeypatch.setattr(application.HTTP, name, guard)
    monkeypatch.setattr('requests.Session.request', guard)
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {'api_key': 'test-key', 'endpoint': 'https://provider.invalid', 'model': 'test-model'})
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {'api_key': 'test-key', 'endpoint': 'https://provider.invalid',
                                                          'model': 'seedance-20-endpoint', 'seedance_2_5_model': 'ep-test'})
    monkeypatch.setattr(application, 'CUPSY_VIDEO_CONFIG', {'api_key': 'test-key', 'endpoint': 'https://cupsy.invalid',
                                                            'model': 'seedance-2.5', 'source_base_url': 'https://source.invalid'})
    # The real B3 submitter/estimator are registered by app.py; make sure no other test left a mock.
    canvas_group_submit.register()
    project = store.create_project('B3')
    return Env(store.create_workflow(project['id'], '画布')['id'])


def image_chain(env):
    src = env.asset(png('red'), 'src.png')
    nodes = [{'id': 'src', 'type': 'asset', 'title': 'src', 'x': 0, 'y': 0, 'asset': src, 'candidates': [src], 'selectedCandidateId': src['id']},
             generation('a', 'image', '画一只猫', ratio='16:9'),
             generation('b', 'image', '参考 @图片1 画同一只猫', ratio='1:1', resolution='2K')]
    env.save(nodes, [('src', 'a'), ('a', 'b')], ['a', 'b'])
    return src


# ① group submission == single-node browser submission, field by field

def test_group_submission_matches_single_node_submission(env, monkeypatch):
    image_chain(env)
    wire = Wire(monkeypatch)
    run = env.start()
    a_task = env.entry(run, 'a')['task_id']
    assert env.entry(run, 'a')['status'] == 'submitted' and env.entry(run, 'b')['status'] == 'waiting'
    assert task_db.get_task(a_task)['params']['group_run_id'] == run['id']
    assert env.node(env.doc(), 'a')['task'] == {'id': a_task, 'status': 'pending', 'error': None}
    run = env.finish(a_task)
    b_task = env.entry(run, 'b')['task_id']
    assert env.entry(run, 'b')['status'] == 'submitted' and b_task
    run = env.finish(b_task)
    assert run['status'] == 'completed'
    group_calls = list(wire.calls)
    assert [c['path'] for c in group_calls] == ['/api/generate', '/api/generate']
    # b received a's new result as its reference, as multipart like the browser's FormData.
    a_result = env.node(env.doc(), 'a')['asset']
    assert group_calls[1]['multipart'] and [f[0] for f in group_calls[1]['files']] == ['images']
    # a's result is a library media reference (no canvas copy); b got exactly its bytes.
    import media_library
    assert a_result['url'] == f"/api/canvas/media/{a_result['id']}"
    assert task_db.get_db().execute('SELECT COUNT(*) FROM canvas_assets WHERE id=?', (a_result['id'],)).fetchone()[0] == 0
    a_bytes = media_library.media_path(media_library.get_media(a_result['id'])).read_bytes()
    assert group_calls[1]['files'][0][1:] == (a_result['name'], 'image/png', hashlib.sha256(a_bytes).hexdigest())

    # Replay each node exactly as the browser would (assembled request over HTTP) and compare.
    caps = None
    with application.app.test_request_context('/'):
        caps = canvas_submit.live_capabilities()
    for node_id, group_call, group_task in (('a', group_calls[0], a_task), ('b', group_calls[1], b_task)):
        request = canvas_submit.assemble(env.wid, node_id, caps)
        expected_form = list(canvas_submit.form_fields(request['fields']).items())
        if request['multipart']:
            body = {k: v for k, v in expected_form}
            body.update({f['field']: (f['file'].open('rb'), f['filename'], 'image/png') for f in request['files']})
            response = env.client.post(request['path'], data=body, content_type='multipart/form-data')
            assert without_revision(group_call)['form'] == [(k, v) for k, v in expected_form if k != 'canvas_workflow_revision']
        else:
            response = env.client.post(request['path'], json=request['fields'])
            assert without_revision(group_call)['json'] == {k: v for k, v in request['fields'].items() if k != 'canvas_workflow_revision'}
        assert response.status_code == 202, response.json
        browser_call = wire.calls[-1]
        assert without_revision(browser_call) == without_revision(group_call)
        single = task_db.get_task(response.json['task_id'])
        grouped = task_db.get_task(group_task)
        strip = lambda params: {k: v for k, v in params.items() if k not in ('group_run_id', 'cost_estimate')}
        assert strip(grouped['params']) == strip(single['params']) and 'group_run_id' not in single['params']
        assert grouped['prompt'] == single['prompt'] and grouped['provider'] == single['provider']
        ce = lambda t: {k: v for k, v in t['params']['cost_estimate'].items() if k != 'computed_at'}
        assert ce(grouped) == ce(single)
        inputs = lambda t: [hashlib.sha256(Path(a['path']).read_bytes()).hexdigest() for a in task_db.list_assets(t) if a['kind'] == 'input_image']
        assert inputs(group_task) == inputs(single['id'])
    # Both group tasks are associated with the canvas like single-node tasks.
    owners = {row['task_id'] for row in task_db.get_db().execute('SELECT task_id FROM canvas_workflow_tasks WHERE workflow_id=?', (env.wid,))}
    assert {a_task, b_task} <= owners


def test_preview_and_submit_estimates_match_the_ledger_snapshot(env):
    image_chain(env)
    preview = env.preview()
    by_node = {n['node_id']: n['estimate'] for n in preview['nodes']}
    run = env.start()
    a_task = env.entry(run, 'a')['task_id']
    snapshot = task_db.get_task(a_task)['params']['cost_estimate']
    assert by_node['a'] == {'known': True, 'usd': round(snapshot['maximum_cost'], 6), 'reason': None}
    run = env.finish(a_task)
    b_snapshot = task_db.get_task(env.entry(run, 'b')['task_id'])['params']['cost_estimate']
    # b had no result at preview: the planned upstream image counted as one reference.
    assert b_snapshot['reference_count'] == 1
    assert by_node['b'] == {'known': True, 'usd': round(b_snapshot['maximum_cost'], 6), 'reason': None}
    assert preview['total']['unknown_count'] == 0


def test_audio_estimate_is_unknown_never_zero(env):
    env.save([generation('s', 'audio', '一段旁白', provider='cupsy')], [], ['s'])
    preview = env.preview()
    assert preview['nodes'][0]['estimate'] == {'known': False, 'usd': None, 'reason': 'no_price_data'}
    assert preview['total'] == {'usd': 0.0, 'known_count': 0, 'unknown_count': 1, 'node_count': 1}


# ② node.task write-back: stale page saves merge without 409 and without node_modified

def test_stale_page_save_merges_node_task_and_branch_continues(env):
    image_chain(env)
    stale = store.workflow(env.wid)
    run = env.start()
    a_task = env.entry(run, 'a')['task_id']
    current = store.workflow(env.wid)
    assert current['revision'] == stale['revision'] + 1
    row = task_db.get_db().execute('SELECT node_id, task_id FROM canvas_writebacks WHERE workflow_id=? AND revision=?',
                                   (env.wid, current['revision'])).fetchone()
    assert (row['node_id'], row['task_id']) == ('a', a_task)
    # The open page still has the pre-run document (a without task) and moves a node.
    document = stale['document']
    env.node(document, 'src')['x'] = 120
    response = env.client.put(env.url, json={'title': stale['title'], 'document': document, 'revision': stale['revision']})
    assert response.status_code == 200, response.json
    saved = store.workflow(env.wid)['document']
    assert env.node(saved, 'a')['task'] == {'id': a_task, 'status': 'pending', 'error': None}
    assert env.node(saved, 'src')['x'] == 120
    run = env.finish(a_task)
    assert env.entry(run, 'b')['status'] == 'submitted' and env.entry(run, 'b')['reason'] is None


def test_merge_rule_is_limited_to_group_tasks_and_older_client_tasks(env):
    env.save([generation('a', 'image', 'p')], [], ['a'])
    stale = store.workflow(env.wid)
    ordinary = task_db.create_task('image', 'p', {'canvas_workflow_id': env.wid, 'canvas_node_id': 'a'})
    assert canvas_group_submit._write_node_task(env.wid, 'a', ordinary)
    # Ordinary task: unchanged interface-C rule, the client's (older) node state is kept.
    response = env.client.put(env.url, json={'title': stale['title'], 'document': stale['document'], 'revision': stale['revision']})
    assert response.status_code == 200
    assert env.node(env.doc(), 'a').get('task') is None
    # A client bound to a newer task keeps it even against a group-run task.
    stale = store.workflow(env.wid)
    group_task = task_db.create_task('image', 'p', {'canvas_workflow_id': env.wid, 'canvas_node_id': 'a', 'group_run_id': 'r'})
    newer = task_db.create_task('image', 'p', {'canvas_workflow_id': env.wid, 'canvas_node_id': 'a'})
    assert canvas_group_submit._write_node_task(env.wid, 'a', group_task)
    document = stale['document']
    env.node(document, 'a')['task'] = {'id': newer, 'status': 'pending', 'error': None}
    response = env.client.put(env.url, json={'title': stale['title'], 'document': document, 'revision': stale['revision']})
    assert response.status_code == 200
    assert env.node(env.doc(), 'a')['task']['id'] == newer


# ③ re-estimate before submission: higher or unknown -> not submitted

def video_chain(env, duration=5):
    nodes = [generation('a', 'video', '镜头一', provider='cupsy', model='seedance-2.5', duration=duration),
             generation('b', 'video', '延续 @视频1', provider='cupsy', model='seedance-2.5', duration=5)]
    env.save(nodes, [('a', 'b')], ['a', 'b'])


def expected_video(refs):
    return round(cost_estimate.estimate_video_cost(model='seedance-2.5', provider='cupsy', resolution='720p', ratio='16:9',
                                                   duration=5, reference_video_durations=refs)['maximum_cost'], 6)


def test_video_preview_uses_planned_upstream_duration(env):
    video_chain(env, duration=8)
    nodes = {n['node_id']: n['estimate'] for n in env.preview()['nodes']}
    assert nodes['b'] == {'known': True, 'usd': expected_video([8]), 'reason': None}
    video_chain(env, duration=-1)  # Auto: counted at the model maximum, never under-stated
    nodes = {n['node_id']: n['estimate'] for n in env.preview()['nodes']}
    assert nodes['b']['usd'] == expected_video([30])


def test_higher_re_estimate_pauses_without_submitting(env, monkeypatch, mp4):
    video_chain(env)
    wire = Wire(monkeypatch)
    run = env.start()
    a_task = env.entry(run, 'a')['task_id']
    monkeypatch.setattr(cost_estimate, 'probe_duration', lambda path: 12.0)
    run = env.finish(a_task, 'video', mp4)
    assert run['status'] == 'awaiting_confirm'
    b = env.entry(run, 'b')
    assert b['status'] == 'waiting' and b['task_id'] is None
    assert b['estimate']['usd'] == expected_video([5]) and b['pending_estimate']['usd'] == expected_video([12])
    assert len(wire.calls) == 1 and task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 1
    run = env.client.post(f"{env.url}/group-runs/{run['id']}/confirm", json={'confirm_token': run['confirm']['confirm_token']}).json['run']
    b = env.entry(run, 'b')
    assert b['status'] == 'submitted' and len(wire.calls) == 2
    assert wire.calls[1]['multipart'] and [(f[0], f[2]) for f in wire.calls[1]['files']] == [('ref_videos', 'video/mp4')]
    assert task_db.get_task(b['task_id'])['params']['cost_estimate']['maximum_cost'] == pytest.approx(expected_video([12]))


def test_lower_re_estimate_submits(env, mp4):
    video_chain(env)
    run = env.start()
    run = env.finish(env.entry(run, 'a')['task_id'], 'video', mp4)  # real probe: 0.2 s < planned 5 s
    assert run['status'] == 'running' and env.entry(run, 'b')['status'] == 'submitted'


def test_estimate_turning_unknown_pauses(env, monkeypatch):
    image_chain(env)
    run = env.start()
    original = cost_estimate.estimate_image_cost
    monkeypatch.setattr(cost_estimate, 'estimate_image_cost',
                        lambda *a, **k: {**original(*a, **k), 'known': False, 'reason': 'above_price_ceiling'})
    run = env.finish(env.entry(run, 'a')['task_id'])
    b = env.entry(run, 'b')
    assert run['status'] == 'awaiting_confirm' and b['task_id'] is None and b['pending_estimate']['known'] is False


# Outcome classification (billing boundary): rejected / failed / unknown, never retried

def test_invalid_node_is_rejected_without_task(env):
    env.save([generation('a', 'image', '   '), generation('b', 'image', 'p')], [('a', 'b')], ['a', 'b'])
    run = env.start()
    a = env.entry(run, 'a')
    assert (a['status'], a['reason'], a['message']) == ('failed', 'submit_rejected', '请填写生成提示词')
    assert env.entry(run, 'b')['reason'] == 'upstream_failed'
    assert task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0


def test_route_rejection_without_task_is_submit_rejected(env, monkeypatch):
    import canvas_image_params

    def refuse(*args, **kwargs):
        raise store.CanvasError('服务端参数复核未通过')
    monkeypatch.setattr(canvas_image_params, 'validate_submission', refuse)
    env.save([generation('a', 'image', 'p')], [], ['a'])
    run = env.start()
    a = env.entry(run, 'a')
    assert (a['status'], a['reason'], a['message']) == ('failed', 'submit_rejected', '服务端参数复核未通过')
    assert task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
    assert run['status'] == 'completed'


def ark_video(env):
    env.save([generation('a', 'video', '镜头', model='seedance-2.0', duration=5), generation('b', 'image', 'p')],
             [], ['a', 'b'])


def test_ark_video_timeout_is_unknown_and_stops_run(env, monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        raise requests.exceptions.ReadTimeout('read timed out')
    monkeypatch.setattr(application.HTTP, 'post', post)
    ark_video(env)
    run = env.start()
    a = env.entry(run, 'a')
    assert (a['status'], a['reason']) == ('unknown', 'result_unknown') and a['task_id']
    assert run['status'] == 'stopped' and len(calls) == 1
    run = env.run(run['id'])
    assert len(calls) == 1 and env.entry(run, 'a')['task_id'] == a['task_id']


def test_ark_video_provider_error_is_a_failed_task(env, monkeypatch):
    calls = []
    monkeypatch.setattr(application.HTTP, 'post', lambda url, **k: calls.append(url) or FakeResponse(status_code=400, payload={'error': {'message': 'bad'}}))
    env.save([generation('a', 'video', '镜头', model='seedance-2.0', duration=5)], [], ['a'])
    run = env.start()
    a = env.entry(run, 'a')
    assert (a['status'], a['reason']) == ('failed', 'task_failed') and run['status'] == 'completed' and len(calls) == 1


def test_ark_video_accepted(env, monkeypatch):
    sent = []
    monkeypatch.setattr(application.HTTP, 'post', lambda url, **k: sent.append(k['json']) or FakeResponse(status_code=200, payload={'id': 'synthetic'}))
    env.save([generation('a', 'video', '镜头', model='seedance-2.0', duration=5)], [], ['a'])
    run = env.start()
    a = env.entry(run, 'a')
    assert a['status'] == 'submitted' and len(sent) == 1
    task = task_db.get_task(a['task_id'])
    assert task['external_task_id'] == 'synthetic' and task['params']['group_run_id'] == run['id']
    assert env.node(env.doc(), 'a')['task']['id'] == a['task_id']


def test_view_error_after_task_follows_the_task(env, monkeypatch):
    image_chain(env)

    def broken(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(storage, 'register_file', broken)
    run = env.start()
    a = env.entry(run, 'a')
    # The image route runs no provider call itself; its task is failed, the branch is blocked.
    assert (a['status'], a['reason']) == ('failed', 'task_failed') and run['status'] == 'completed'
    assert env.entry(run, 'b')['reason'] == 'upstream_failed'


def test_edit_between_check_and_submit_is_rejected(env, monkeypatch):
    env.save([generation('a', 'image', 'p')], [], ['a'])
    original = canvas_submit.assemble

    def edited(workflow_id, node_id, capabilities):
        wf = store.workflow(workflow_id)
        doc = wf['document']
        env.node(doc, node_id)['text'] = 'changed'
        store.update_workflow(workflow_id, wf['title'], doc, wf['revision'])
        return original(workflow_id, node_id, capabilities)
    monkeypatch.setattr(canvas_submit, 'assemble', edited)
    run = env.start()
    a = env.entry(run, 'a')
    assert (a['status'], a['reason']) == ('failed', 'submit_rejected') and '修改' in a['message']
    assert task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0


# group_run_id can only come from the internal submission

def test_request_body_cannot_set_group_run_id(env):
    env.save([generation('a', 'image', 'p')], [], ['a'])
    wf = store.workflow(env.wid)
    body = {'prompt': 'p', 'provider': 'ark', 'canvas_workflow_id': env.wid, 'canvas_node_id': 'a',
            'canvas_workflow_revision': wf['revision'], 'group_run_id': 'forged'}
    response = env.client.post('/api/generate', json=body)
    assert response.status_code == 202, response.json
    assert 'group_run_id' not in task_db.get_task(response.json['task_id'])['params']
    assert canvas_group_submit.current_submission() is None


def test_retry_drops_group_run_id(env):
    tid = task_db.create_task('image', 'p', {'provider': 'ark', 'group_run_id': 'r', 'size': '1024x1024'}, provider='ark')
    task_db.fail_task(tid, 'x')
    (Path(storage.OUTPUT_DIR) / 'image' / str(tid)).mkdir(parents=True)
    task_db.update_task(tid, output_dir=str(Path(storage.OUTPUT_DIR) / 'image' / str(tid)))
    response = env.client.post(f'/api/tasks/{tid}/retry', json={})
    assert response.status_code == 202, response.json
    assert 'group_run_id' not in task_db.get_task(response.json['task_id'])['params']


def test_internal_context_keeps_caller_connection_open(env):
    db = task_db.get_db()
    capabilities = canvas_group_submit._capabilities()
    assert set(capabilities) == {'image', 'video', 'audio'}
    assert task_db.get_db() is db and db.execute('SELECT 1').fetchone()[0] == 1
