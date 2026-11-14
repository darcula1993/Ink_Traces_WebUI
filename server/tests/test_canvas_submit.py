"""GROUP-RUN-20261115 A1: server-side canvas request assembly (no submission, no Provider).

The shared cases (tests/data/canvas_submit_cases.json) are also run against the browser's
submitCanvasGeneration by client/tests/canvasSubmitParity.test.js: both sides must produce the
same route, fields, reference order and file names, or refuse with the same Chinese reason.
"""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

import canvas_store as store
import canvas_submit
import tasks as task_db
from canvas_submit import CanvasSubmitError, build_request, capabilities_from_sources, form_fields

SHARED = json.loads((Path(__file__).parent / 'data' / 'canvas_submit_cases.json').read_text(encoding='utf-8'))
SOURCES = SHARED['sources']
CAPABILITIES = capabilities_from_sources(SOURCES['image'], SOURCES['video'], SOURCES['audio'], SOURCES['profiles'])


def _run(case):
    workflow = {**SHARED['workflow'], 'document': {'version': 1, 'nodes': case['nodes'], 'edges': case['edges']}}

    def read_metadata(asset):
        value = (case.get('metadata') or {}).get(asset['id'])
        if value is None:
            raise OSError('metadata unavailable')
        return value

    def resolve_file(asset):
        if asset['id'] in (case.get('unreadable') or []):
            raise OSError('unreadable')
        return asset['id']

    return build_request(workflow, case['node'], CAPABILITIES, read_metadata=read_metadata, resolve_file=resolve_file)


@pytest.mark.parametrize('case', SHARED['cases'], ids=[c['name'] for c in SHARED['cases']])
def test_shared_case_matches_browser(case):
    expect = case['expect']
    if 'error' in expect:
        with pytest.raises(CanvasSubmitError) as raised:
            _run(case)
        assert raised.value.message == expect['error']
        return
    result = _run(case)
    assert result['path'] == expect['path']
    assert result['multipart'] is expect['multipart']
    assert result['fields'] == expect['fields']
    # Same JSON types as the browser's JSON body (bool stays bool, numbers stay numbers).
    assert json.dumps(result['fields'], sort_keys=True) == json.dumps(expect['fields'], sort_keys=True)
    if expect['multipart']:
        js = {key: ('true' if value is True else 'false' if value is False else str(value)) for key, value in expect['fields'].items()}
        assert form_fields(result['fields']) == js
    assert [[f['field'], f['asset_id'], f['filename']] for f in result['files']] == expect['files']
    assert all(f['file'] == f['asset_id'] for f in result['files'])


def test_capabilities_port_matches_browser_shape():
    image = CAPABILITIES['image']
    assert [o['id'] for o in image] == [f"profile:{'9' * 32}", 'cupsy', 'ark']
    assert image[0]['capability_model'] == 'dola-seedream-5-5-261028' and image[0]['profile_id'] == '9' * 32
    assert [o['id'] for o in CAPABILITIES['video']] == ['ark', 'cupsy']
    assert CAPABILITIES['video'][1]['models'] == [{'id': 'seedance-2.5', 'name': 'Seedance 2.5'},
                                                  {'id': 'seedance-2.5-moderated', 'name': 'Seedance 2.5 Enhanced Moderation'}]
    assert CAPABILITIES['audio'] == [{'id': 'cupsy', 'provider': 'cupsy', 'name': 'Cupsy（原配置）', 'model': 'seed-audio-1.0'}]
    video_profile = capabilities_from_sources({}, {}, {}, [
        {'id': 'v' * 32, 'kind': 'video', 'adapter': 'cupsy', 'name': 'V', 'enabled': True, 'has_api_key': True, 'is_default': True,
         'revision': 2, 'settings': {}}])['video'][0]
    assert video_profile['model'] == 'seedance-2.5' and video_profile['name'] == 'V · 默认'
    assert [m['id'] for m in video_profile['models']] == ['seedance-2.5', 'seedance-2.5-moderated']


def test_js_value_semantics():
    assert canvas_submit.js_number(' 6 ') == 6 and canvas_submit.js_number('') == 0 and canvas_submit.js_number('0x10') == 16
    assert canvas_submit.js_number('5s') != canvas_submit.js_number('5s')  # NaN
    assert canvas_submit.js_trim('﻿ a 　') == 'a' and canvas_submit.js_trim('\x1c a') == '\x1c a'
    assert form_fields({'a': True, 'b': 5, 'c': 5.0, 'd': 'x'}) == {'a': 'true', 'b': '5', 'c': '5', 'd': 'x'}


# ---------- against the real canvas store and files (still no submission) ----------

def _png(alpha):
    buffer = io.BytesIO()
    Image.new('RGBA' if alpha else 'RGB', (8, 8), (1, 2, 3, 0) if alpha else (1, 2, 3)).save(buffer, 'PNG')
    buffer.seek(0)
    return buffer


def _canvas(nodes_for):
    project = store.create_project('A1')
    workflow = store.create_workflow(project['id'], '画布')
    with store.write_transaction():
        first = store.save_asset(workflow['id'], _png(True), 'first.png')
        second = store.save_asset(workflow['id'], _png(False), 'second.png')
    nodes, edges = nodes_for(first, second)
    document = {'version': 1, 'nodes': nodes, 'edges': edges, 'viewport': {'x': 0, 'y': 0, 'zoom': 1}}
    saved = store.update_workflow(workflow['id'], '画布', document, workflow['revision'])
    return saved, first, second


def _tasks():
    return task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0]


def test_assemble_reads_saved_document_and_canvas_files_without_submitting(monkeypatch):
    posted = []
    monkeypatch.setattr('requests.Session.request', lambda *a, **k: posted.append(a) or pytest.fail('network call'))

    def nodes_for(first, second):
        upstream = {'id': 'up', 'type': 'asset', 'title': 'up', 'x': 0, 'y': 0, 'asset': second, 'candidates': [second], 'selectedCandidateId': second['id']}
        target = {'id': 'v', 'type': 'video', 'title': '镜头', 'x': 0, 'y': 0, 'text': '从 @图片1 到 @图片2',
                  'providerSelection': {'provider': 'cupsy', 'profile_id': None},
                  'params': {'model': 'seedance-2.5', 'video_mode': 'keyframe', 'duration': 5},
                  'referenceAssets': [first], 'referenceOrder': [first['id'], second['id']]}
        return [upstream, target], [{'id': 'e1', 'source': 'up', 'target': 'v'}]

    saved, first, second = _canvas(nodes_for)
    before = _tasks()
    result = canvas_submit.assemble(saved['id'], 'v', CAPABILITIES)
    assert _tasks() == before == 0 and posted == []
    assert result['path'] == '/api/video/generate'
    assert result['fields']['canvas_workflow_revision'] == saved['revision']
    assert result['fields']['ratio'] == 'adaptive' and result['fields']['result_name'] == '镜头'
    assert [(f['field'], f['asset_id']) for f in result['files']] == [('image', first['id']), ('last_image', second['id'])]
    for item in result['files']:
        assert item['file'].is_file() and item['file'] == store.asset_path(store.get_asset(saved['id'], item['asset_id']))


def test_assemble_reads_real_alpha_metadata():
    def nodes_for(first, second):
        node = lambda id, ref: {'id': id, 'type': 'image', 'title': id, 'x': 0, 'y': 0, 'text': 'p',
                                'providerSelection': {'provider': 'ark', 'profile_id': None}, 'params': {'background': 'transparent'},
                                'referenceAssets': [ref]}
        return [node('alpha', first), node('opaque', second)], []

    saved, first, _ = _canvas(nodes_for)
    result = canvas_submit.assemble(saved['id'], 'alpha', CAPABILITIES)
    assert result['fields']['background'] == 'transparent' and result['files'][0]['asset_id'] == first['id']
    with pytest.raises(CanvasSubmitError, match='没有可确认的 Alpha 通道'):
        canvas_submit.assemble(saved['id'], 'opaque', CAPABILITIES)


def test_assemble_refuses_missing_file_like_the_browser():
    def nodes_for(first, second):
        return [{'id': 'n', 'type': 'image', 'title': 'n', 'x': 0, 'y': 0, 'text': 'p',
                 'providerSelection': {'provider': 'ark', 'profile_id': None}, 'referenceAssets': [first]}], []

    saved, first, _ = _canvas(nodes_for)
    store.asset_path(store.get_asset(saved['id'], first['id'])).unlink()
    with pytest.raises(CanvasSubmitError) as raised:
        canvas_submit.assemble(saved['id'], 'n', CAPABILITIES)
    assert raised.value.message == '无法读取参考素材“first.png”，尚未提交生成'
    with pytest.raises(store.CanvasError):
        canvas_submit.assemble('missing', 'n', CAPABILITIES)


def test_live_capabilities_reads_the_same_sources_as_the_browser():
    import app as application
    import provider_profiles
    provider_profiles.save_profile({'name': '视频账号', 'kind': 'video', 'adapter': 'cupsy', 'enabled': True, 'is_default': True,
                                    'settings': {'endpoint': 'https://example.invalid'}, 'api_key': 'test-only'})
    with application.app.test_request_context('/'):
        capabilities = canvas_submit.live_capabilities()
    assert [o['provider'] for o in capabilities['video'] if o.get('profile_id')] == ['cupsy']
    assert set(capabilities) == {'image', 'video', 'audio'}
