"""LAYER-SRC-MASK-20261114: layer documents never ship signed Provider URLs."""
import io
import json
import zipfile

import app as application
import tasks as task_db
from task_public import restore_layer_remote_fields

SIGNED = ('https://bucket.tos.invalid/out/layer.png'
          '?X-Tos-Algorithm=TOS4-HMAC-SHA256&X-Tos-Credential=FAKECRED%2F20261114'
          '&X-Tos-Signature=fakesignaturevalue0000&X-Tos-Expires=86400')
BASE_SIGNED = 'https://bucket.tos.invalid/out/base.png?X-Tos-Signature=fakesig2222'
MASKED = 'https://bucket.tos.invalid/…'
LEAK_MARKERS = ('X-Tos', 'FAKECRED', 'fakesignature', 'fakesig2222', '/out/layer.png', '/out/base.png')


def _assert_clean(text):
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    for marker in LEAK_MARKERS:
        assert marker not in text, marker


def _project(tmp_path):
    task_id = task_db.create_task('layer', 'p', {})
    output_dir = tmp_path / 'layer_out'
    output_dir.mkdir()
    (output_dir / 'base.png').write_bytes(b'\x89PNG-base')
    (output_dir / 'layer_01.png').write_bytes(b'\x89PNG-layer')
    base = {'z_index': 0, 'name': '基础图', 'local_url': f'/api/tasks/{task_id}/file/base.png',
            'thumbnail_url': f'/api/tasks/{task_id}/file/base_thumb.webp', 'source_url': BASE_SIGNED}
    layer = {'z_index': 1, 'name': '图层 1', 'local_url': f'/api/tasks/{task_id}/file/layer_01.png',
             'thumbnail_url': f'/api/tasks/{task_id}/file/layer_01_thumb.webp', 'source_url': SIGNED}
    result = {'base_image': base['local_url'], 'layers': [layer], 'source_urls': [BASE_SIGNED, SIGNED]}
    task_db.complete_task(task_id, result, str(output_dir))
    project_id = task_db.create_layer_project('layer', 'a.png', None, {})
    document = {
        'canvas': {'width': 10, 'height': 10},
        'layers': [{'id': f'{task_id}:0', **base, 'x': 0, 'y': 0},
                   {'id': f'{task_id}:1', **layer, 'x': 1, 'y': 1}],
        'task_id': task_id,
    }
    task_db.add_layer_revision(project_id, task_id, 'p', 'auto', result, document)
    return project_id, task_id


def _stored_urls(project_id):
    project = task_db.get_layer_project(project_id)
    docs = [project['document']] + [revision['document'] for revision in project['revisions']]
    return [layer.get('source_url') for doc in docs for layer in doc['layers']]


def test_layer_list_detail_save_restore_export_mask_source_url(tmp_path):
    project_id, task_id = _project(tmp_path)
    client = application.app.test_client()

    _assert_clean(client.get('/api/layer/projects').get_json())
    detail = client.get(f'/api/layer/projects/{project_id}').get_json()
    _assert_clean(detail)
    project = detail['project']
    assert [layer['source_url'] for layer in project['document']['layers']] == [MASKED, MASKED]
    assert project['revisions'][0]['document']['layers'][1]['source_url'] == MASKED
    # Local resources for display/export/compositing stay intact.
    assert project['document']['layers'][1]['local_url'] == f'/api/tasks/{task_id}/file/layer_01.png'
    assert project['document']['layers'][1]['thumbnail_url'] == f'/api/tasks/{task_id}/file/layer_01_thumb.webp'

    # Browser round-trips the masked document; the stored original survives.
    document = project['document']
    document['layers'][1]['x'] = 5
    saved = client.put(f'/api/layer/projects/{project_id}', json={'document': document, 'revision': project['document_revision']})
    assert saved.status_code == 200
    _assert_clean(saved.get_json())
    stored = task_db.get_layer_project(project_id)
    assert stored['document']['layers'][1]['x'] == 5
    assert _stored_urls(project_id) == [BASE_SIGNED, SIGNED, BASE_SIGNED, SIGNED]

    revision_id = stored['revisions'][0]['id']
    restored = client.post(f'/api/layer/projects/{project_id}/revisions/{revision_id}/restore')
    assert restored.status_code == 200
    _assert_clean(restored.get_json())
    assert _stored_urls(project_id) == [BASE_SIGNED, SIGNED, BASE_SIGNED, SIGNED]

    archive = client.get(f'/api/layer/projects/{project_id}/layers.zip')
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.data)) as bundle:
        names = bundle.namelist()
        manifest = bundle.read('manifest.json').decode()
        assert bundle.read(names[1]) == b'\x89PNG-layer'
    _assert_clean(manifest)
    assert len(json.loads(manifest)['layers']) == 2


def test_restore_layer_remote_fields_matches_id_then_local_url_and_drops_unknown_masks():
    project = {'document': {'layers': [
        {'id': 'a', 'local_url': '/api/tasks/1/file/a.png', 'source_url': SIGNED},
    ]}, 'revisions': []}
    incoming = {'layers': [
        {'id': 'a', 'local_url': '/api/tasks/1/file/a.png', 'source_url': MASKED},
        {'id': 'copy', 'local_url': '/api/tasks/1/file/a.png', 'source_url': MASKED},
        {'id': 'new', 'local_url': '/api/tasks/9/file/n.png', 'source_url': MASKED},
        {'id': 'plain', 'local_url': '/api/tasks/9/file/p.png', 'source_url': None},
    ]}
    result = restore_layer_remote_fields(incoming, project)
    assert result['layers'][0]['source_url'] == SIGNED
    assert result['layers'][1]['source_url'] == SIGNED
    assert 'source_url' not in result['layers'][2]
    assert result['layers'][3]['source_url'] is None
    assert incoming['layers'][0]['source_url'] == MASKED


def test_layer_user_content_with_urls_round_trips_verbatim(tmp_path):
    """D1 rework: OCR text, descriptions and layer names containing URLs are user
    content; GET shows them verbatim and a save keeps them byte for byte."""
    project_id, _task_id = _project(tmp_path)
    ocr = '扫码访问 https://shop.example.com/sale/2026?ref=a 立即购买'
    description = '参考 http://example.org/brand/guide.pdf 的配色'
    name = 'https://shop.example.com/banner'
    stored = task_db.get_layer_project(project_id)
    document = stored['document']
    document['layers'][1].update({
        'name': name, 'description': description,
        'text_recognition': {'text': ocr, 'lines': [{'text': ocr, 'runs': [{'text': ocr}]}]},
    })
    assert task_db.save_layer_document(project_id, document, stored['document_revision'])
    client = application.app.test_client()

    project = client.get(f'/api/layer/projects/{project_id}').get_json()['project']
    layer = project['document']['layers'][1]
    assert layer['name'] == name and layer['description'] == description
    assert layer['text_recognition'] == {'text': ocr, 'lines': [{'text': ocr, 'runs': [{'text': ocr}]}]}
    assert layer['source_url'] == MASKED

    before = json.dumps(task_db.get_layer_project(project_id)['document'], ensure_ascii=False, sort_keys=True)
    saved = client.put(f'/api/layer/projects/{project_id}',
                       json={'document': project['document'], 'revision': project['document_revision']})
    assert saved.status_code == 200
    after = json.dumps(task_db.get_layer_project(project_id)['document'], ensure_ascii=False, sort_keys=True)
    assert after == before
    assert '…' not in after

    with zipfile.ZipFile(io.BytesIO(client.get(f'/api/layer/projects/{project_id}/layers.zip').data)) as bundle:
        manifest = json.loads(bundle.read('manifest.json').decode())
    assert manifest['layers'][1]['text_recognition']['text'] == ocr
    assert manifest['layers'][1]['name'] == name
    assert manifest['layers'][1]['source_url'] == MASKED


def test_restore_keeps_non_whitelisted_masked_looking_text_and_hostless_source():
    project = {'document': {'layers': [{'id': 'a', 'source_url': 'https:///no-host.png'}]}, 'revisions': []}
    incoming = {'layers': [{'id': 'a', 'source_url': '远端结果', 'description': 'https://x.example/…'}]}
    result = restore_layer_remote_fields(incoming, project)
    assert result['layers'][0]['source_url'] == 'https:///no-host.png'
    assert result['layers'][0]['description'] == 'https://x.example/…'
