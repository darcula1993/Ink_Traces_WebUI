"""Durable asset nodes and media-kind edge compatibility."""
import copy
import io
import subprocess
import wave

from PIL import Image
import pytest

import app as application
import canvas_store as store


@pytest.fixture(scope='module')
def media(tmp_path_factory):
    folder = tmp_path_factory.mktemp('asset-node-media')
    image = io.BytesIO()
    Image.new('RGB', (16, 16), 'blue').save(image, format='PNG')
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(8000); out.writeframes(b'\0\0' * 800)
    video = folder / 'test.mp4'
    subprocess.run(['/usr/bin/ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=16x16:r=5', '-t', '0.2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
    return {'image': ('test.png', image.getvalue()), 'audio': ('test.wav', audio.getvalue()), 'video': ('test.mp4', video.read_bytes())}


def setup(media, kind='image'):
    p = store.create_project('素材节点')
    workflow = store.create_workflow(p['id'], '画布')
    name, data = media[kind]
    asset = store.save_asset(workflow['id'], io.BytesIO(data), name)
    node = {'id': 'asset-one', 'type': 'asset', 'title': name, 'text': '', 'x': 0, 'y': 0, 'asset': asset, 'params': {}, 'candidates': [asset], 'selectedCandidateId': asset['id'], 'task': None}
    document = copy.deepcopy(workflow['document'])
    document['nodes'] = [node]
    return workflow, document


@pytest.mark.parametrize('kind', ['image', 'video', 'audio'])
def test_asset_node_save_reload_and_media_bytes(media, kind):
    workflow, document = setup(media, kind)
    client = application.app.test_client()
    url = f"/api/canvas/workflows/{workflow['id']}"
    response = client.put(url, json={'title': '素材节点保存', 'revision': 1, 'document': document})
    assert response.status_code == 200
    assert client.get(url).json['workflow']['document'] == document
    assert client.get(document['nodes'][0]['asset']['url']).data == media[kind][1]


@pytest.mark.parametrize('source', ['image', 'video', 'audio'])
@pytest.mark.parametrize('target', ['image', 'video', 'audio'])
def test_asset_edge_compatibility(media, source, target):
    workflow, document = setup(media, source)
    document['nodes'].append({'id': 'target', 'type': target, 'title': '生成', 'x': 300, 'y': 0})
    document['edges'] = [{'id': 'edge', 'source': 'asset-one', 'target': 'target'}]
    allowed = target == 'video' or source == 'image' or (source == 'audio' and target == 'audio')
    if allowed:
        store.validate_document(document, workflow['id'])
    else:
        with pytest.raises(store.CanvasError): store.validate_document(document, workflow['id'])


@pytest.mark.parametrize('fault', ['missing_asset', 'task', 'params', 'reference', 'candidate', 'incoming', 'foreign_asset'])
def test_reject_invalid_asset_nodes(media, fault):
    workflow, document = setup(media)
    node = document['nodes'][0]
    if fault == 'missing_asset': node.update(asset=None, candidates=[], selectedCandidateId=None)
    elif fault == 'task': node['task'] = {'id': 1, 'status': 'pending'}
    elif fault == 'params': node['params'] = {'model': 'not-applicable'}
    elif fault == 'reference': node['referenceAssets'] = [node['asset']]
    elif fault == 'candidate': node['candidates'].append(node['asset'])
    elif fault == 'incoming':
        document['nodes'].append({'id': 'source', 'type': 'image', 'x': 300, 'y': 0})
        document['edges'] = [{'id': 'edge', 'source': 'source', 'target': node['id']}]
    elif fault == 'foreign_asset':
        _, foreign = setup(media)
        node.update(asset=foreign['nodes'][0]['asset'], candidates=foreign['nodes'][0]['candidates'], selectedCandidateId=foreign['nodes'][0]['selectedCandidateId'])
    with pytest.raises(store.CanvasError): store.validate_document(document, workflow['id'])
