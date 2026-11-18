"""CARD-PROMPT-RESIZE-20261118: manual node size (node.size = {scale}) is kept by the canvas document validation."""
import pytest

import canvas_store as store
from test_canvas_node_selection import make


@pytest.mark.parametrize('kind', ['image', 'video', 'audio'])
@pytest.mark.parametrize('scale', [0.5, 1.75, 3])
def test_generation_node_size_round_trip(kind, scale):
    _, workflow, node = make(kind)
    node['size'] = {'scale': scale}
    workflow['document']['nodes'] = [node]
    store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    assert store.workflow(workflow['id'])['document']['nodes'][0]['size'] == {'scale': scale}


def test_size_defaults_absent_and_can_be_removed():
    _, workflow, node = make('image')
    assert 'size' not in workflow['document']['nodes'][0]
    node['size'] = {'scale': 2}
    workflow['document']['nodes'] = [node]
    store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    del node['size']
    workflow['document']['nodes'] = [node]
    store.update_workflow(workflow['id'], 'canvas', workflow['document'], 3)
    assert 'size' not in store.workflow(workflow['id'])['document']['nodes'][0]


@pytest.mark.parametrize('value', [None, 2, [], {}, {'scale': 0.1}, {'scale': 5}, {'scale': True}, {'scale': '2'},
                                   {'scale': 1, 'width': 300}, {'width': 300, 'height': 200}])
def test_invalid_size_is_rejected(value):
    _, workflow, node = make('video')
    node['size'] = value
    workflow['document']['nodes'] = [node]
    with pytest.raises(store.CanvasError, match='节点尺寸'):
        store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
    assert store.workflow(workflow['id'])['revision'] == 2


def test_text_node_rejects_size():
    _, workflow, node = make()
    node.pop('providerSelection', None)
    node.update(type='text', size={'scale': 2})
    workflow['document']['nodes'] = [node]
    with pytest.raises(store.CanvasError, match='文本节点'):
        store.update_workflow(workflow['id'], 'canvas', workflow['document'], 2)
