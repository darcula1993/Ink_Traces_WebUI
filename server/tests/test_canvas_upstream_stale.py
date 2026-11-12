import pytest

import canvas_store as store
from test_canvas_node_selection import make


@pytest.mark.parametrize('kind', ['image', 'video', 'audio'])
@pytest.mark.parametrize('value', [True, False])
def test_generation_node_upstream_stale_round_trip(kind, value):
    _, workflow, node = make(kind)
    node['upstreamStale'] = value
    workflow['document']['nodes'] = [node]
    saved = store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    assert saved['revision'] == 3
    assert store.workflow(workflow['id'])['document']['nodes'][0]['upstreamStale'] is value


def test_upstream_stale_can_be_removed_and_defaults_absent():
    _, workflow, node = make('image')
    assert 'upstreamStale' not in workflow['document']['nodes'][0]
    node['upstreamStale'] = True
    workflow['document']['nodes'] = [node]
    store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    del node['upstreamStale']
    workflow['document']['nodes'] = [node]
    store.update_workflow(workflow['id'], 'canvas', workflow['document'], 3)
    assert 'upstreamStale' not in store.workflow(workflow['id'])['document']['nodes'][0]


@pytest.mark.parametrize('kind', ['text', 'asset'])
@pytest.mark.parametrize('value', [True, False])
def test_non_generation_nodes_reject_upstream_stale(kind, value):
    _, workflow, node = make()
    node.pop('providerSelection', None)
    node.update(type=kind, upstreamStale=value)
    workflow['document']['nodes'] = [node]
    with pytest.raises(store.CanvasError, match='上游已变更'):
        store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    assert store.workflow(workflow['id'])['revision'] == 2


@pytest.mark.parametrize('value', ['true', '', 1, 0, 1.0, None, [], {}])
def test_upstream_stale_must_be_bool(value):
    _, workflow, node = make('video')
    node['upstreamStale'] = value
    workflow['document']['nodes'] = [node]
    with pytest.raises(store.CanvasError, match='布尔'):
        store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    assert store.workflow(workflow['id'])['revision'] == 2


def test_upstream_stale_does_not_bypass_revision_conflict():
    _, workflow, node = make('image')
    node['upstreamStale'] = True
    workflow['document']['nodes'] = [node]
    with pytest.raises(store.CanvasError) as error:
        store.update_workflow(workflow['id'], 'canvas', workflow['document'], 1)
    assert error.value.status == 409
    assert 'upstreamStale' not in store.workflow(workflow['id'])['document']['nodes'][0]
