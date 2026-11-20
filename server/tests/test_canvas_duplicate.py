"""Backend tests for atomic workflow duplication (P1-CANVAS-WORKFLOW-20261120 P1-2)."""
import io

from PIL import Image
import app as application
import canvas_store as store


def _png_bytes(color=(64, 160, 110)):
    buf = io.BytesIO()
    Image.new('RGB', (32, 32), color).save(buf, format='PNG')
    return buf.getvalue()


def test_duplicate_workflow_strips_runtime_and_preserves_graph_and_media():
    client = application.app.test_client()
    project = store.create_project('测试项目')
    wf = store.create_workflow(project['id'], '分镜A')

    # Upload two global library media items (one as reference, one as generated result).
    r1 = client.post('/api/canvas/media', data={'file': (io.BytesIO(_png_bytes((10, 120, 80))), 'ref.png')})
    assert r1.status_code == 201, r1.get_json()
    ref_media = r1.get_json()['media']
    ref_asset = {
        'id': ref_media['id'],
        'name': ref_media['name'],
        'mime_type': ref_media['mime_type'],
        'kind': ref_media['kind'],
        'size_bytes': ref_media['size_bytes'],
        'url': ref_media['url'],
    }
    r2 = client.post('/api/canvas/media', data={'file': (io.BytesIO(_png_bytes((200, 80, 60))), 'out.png')})
    assert r2.status_code == 201, r2.get_json()
    out_media = r2.get_json()['media']
    out_asset = {
        'id': out_media['id'],
        'name': out_media['name'],
        'mime_type': out_media['mime_type'],
        'kind': out_media['kind'],
        'size_bytes': out_media['size_bytes'],
        'url': out_media['url'],
    }

    doc = {
        'version': 1,
        'viewport': {'x': 12, 'y': 24, 'zoom': 0.8},
        'nodes': [
            {
                'id': 'asset1',
                'type': 'asset',
                'title': '角色图',
                'x': 10,
                'y': 20,
                'text': '',
                'params': {},
                'asset': ref_asset,
                'candidates': [ref_asset],
                'selectedCandidateId': ref_asset['id'],
                'task': None,
            },
            {
                'id': 'gen1',
                'type': 'image',
                'title': '镜头一',
                'x': 420,
                'y': 20,
                'text': '@图片1 雨夜街头',
                'params': {'ratio': '16:9', 'resolution': '2K', 'output_format': 'png'},
                'providerSelection': {'provider': 'ark', 'profile_id': None},
                'asset': out_asset,
                'candidates': [out_asset],
                'selectedCandidateId': out_asset['id'],
                'task': {'id': 77, 'status': 'succeeded', 'error': None},
                'upstreamStale': True,
                'referenceMentions': {'@图片1': ref_asset['id']},
            },
        ],
        'edges': [{'id': 'e1', 'source': 'asset1', 'target': 'gen1'}],
        'groups': [{'id': 'g1', 'title': '节点组1', 'nodeIds': ['asset1', 'gen1'], 'color': 'cyan'}],
    }
    saved = store.update_workflow(wf['id'], '分镜A', doc, wf['revision'])

    res = client.post(f"/api/canvas/workflows/{wf['id']}/duplicate", json={})
    assert res.status_code == 201, res.get_json()
    dup = res.get_json()['workflow']
    assert dup['id'] != wf['id']
    assert dup['project_id'] == project['id']
    assert dup['title'] == '分镜A 副本'
    assert dup['revision'] == 1

    dup_doc = dup['document']
    assert dup_doc['edges'] == doc['edges']
    assert dup_doc['groups'] == doc['groups']
    dup_asset_node = next(n for n in dup_doc['nodes'] if n['id'] == 'asset1')
    dup_gen_node = next(n for n in dup_doc['nodes'] if n['id'] == 'gen1')

    # Asset node preserves global media_id; generation node strips runtime/outputs while keeping params/prompt.
    assert dup_asset_node['asset']['id'] == ref_asset['id']
    assert dup_asset_node['selectedCandidateId'] == ref_asset['id']
    assert dup_gen_node['task'] is None
    assert dup_gen_node['asset'] is None
    assert dup_gen_node['candidates'] == []
    assert dup_gen_node['selectedCandidateId'] is None
    assert 'upstreamStale' not in dup_gen_node
    assert dup_gen_node['text'] == '@图片1 雨夜街头'
    assert dup_gen_node['params'] == doc['nodes'][1]['params']
    assert dup_gen_node['referenceMentions'] == {'@图片1': ref_asset['id']}

    # Source workflow is completely untouched.
    source_after = store.workflow(wf['id'])
    assert source_after['revision'] == saved['revision']
    source_gen = next(n for n in source_after['document']['nodes'] if n['id'] == 'gen1')
    assert source_gen['task']['id'] == 77
    assert source_gen['asset']['id'] == out_asset['id']

    # Second duplicate gets unique numbered title.
    res2 = client.post(f"/api/canvas/workflows/{wf['id']}/duplicate", json={})
    assert res2.status_code == 201
    assert res2.get_json()['workflow']['title'] == '分镜A 副本 2'

    # Non-existent workflow returns 404.
    missing = client.post('/api/canvas/workflows/does-not-exist/duplicate', json={})
    assert missing.status_code == 404
