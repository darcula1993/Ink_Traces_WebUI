"""V24-W2-COMPARE-FINAL-20261121 AC1: optional boolean `finalized` on canvas nodes with full backward compatibility."""
import io
import pytest
from PIL import Image

import app as application
import canvas_store as store
from test_canvas_node_selection import make


def _png_bytes():
    buf = io.BytesIO()
    Image.new('RGB', (16, 16), (40, 120, 80)).save(buf, format='PNG')
    return buf.getvalue()


@pytest.mark.parametrize('kind', ['image', 'video', 'audio', 'text'])
@pytest.mark.parametrize('value', [True, False])
def test_finalized_boolean_round_trip(kind, value):
    _, workflow, node = make(kind, selected=None if kind == 'text' else 'explicit')
    node['finalized'] = value
    workflow['document']['nodes'] = [node]
    store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    saved = store.workflow(workflow['id'])['document']['nodes'][0]
    assert saved['finalized'] is value


def test_asset_node_finalized_round_trip():
    project = store.create_project('final-asset')
    workflow = store.create_workflow(project['id'], 'canvas')
    asset = store.save_asset(workflow['id'], io.BytesIO(_png_bytes()), 'shot.png')
    node = {
        'id': 'a1',
        'type': 'asset',
        'title': 'shot.png',
        'x': 10,
        'y': 20,
        'text': '',
        'params': {},
        'asset': asset,
        'candidates': [asset],
        'selectedCandidateId': asset['id'],
        'task': None,
        'finalized': True,
    }
    doc = {**workflow['document'], 'nodes': [node]}
    store.update_workflow(workflow['id'], 'canvas', doc, 1)
    saved = store.workflow(workflow['id'])['document']['nodes'][0]
    assert saved['finalized'] is True


def test_legacy_document_without_finalized_is_unchanged_and_compatible():
    _, workflow, node = make('image')
    assert 'finalized' not in workflow['document']['nodes'][0]
    client = application.app.test_client()
    url = f"/api/canvas/workflows/{workflow['id']}"
    resp = client.get(url)
    assert resp.status_code == 200
    assert 'finalized' not in resp.json['workflow']['document']['nodes'][0]

    # Toggling finalized True -> False -> omitted via HTTP API persists cleanly.
    node['finalized'] = True
    workflow['document']['nodes'] = [node]
    r1 = client.put(url, json={'title': 'canvas', 'document': workflow['document'], 'revision': 2})
    assert r1.status_code == 200
    assert client.get(url).json['workflow']['document']['nodes'][0]['finalized'] is True

    del node['finalized']
    workflow['document']['nodes'] = [node]
    r2 = client.put(url, json={'title': 'canvas', 'document': workflow['document'], 'revision': 3})
    assert r2.status_code == 200
    assert 'finalized' not in client.get(url).json['workflow']['document']['nodes'][0]


@pytest.mark.parametrize('invalid', [None, 1, 0, 'true', 'false', '', [], {}, {'finalized': True}])
def test_non_boolean_finalized_is_rejected_400(invalid):
    _, workflow, node = make('image')
    node['finalized'] = invalid
    workflow['document']['nodes'] = [node]
    with pytest.raises(store.CanvasError, match='定稿') as exc_info:
        store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    assert exc_info.value.status == 400
    assert store.workflow(workflow['id'])['revision'] == 2

    client = application.app.test_client()
    resp = client.put(
        f"/api/canvas/workflows/{workflow['id']}",
        json={'title': 'canvas', 'document': workflow['document'], 'revision': 2},
    )
    assert resp.status_code == 400
    assert store.workflow(workflow['id'])['revision'] == 2


def test_duplicate_workflow_clears_generation_node_finalized():
    _, workflow, node = make('image')
    node['finalized'] = True
    workflow['document']['nodes'] = [node]
    store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    copied = store.duplicate_workflow(workflow['id'])
    assert 'finalized' not in copied['document']['nodes'][0]
    assert store.workflow(workflow['id'])['document']['nodes'][0]['finalized'] is True
