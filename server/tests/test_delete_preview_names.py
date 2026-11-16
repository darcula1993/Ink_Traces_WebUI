"""FIX-B1B-20261114: delete preview names affected projects/canvases; character uploads are identifiable.

Display-only: the deletion decision and execution are unchanged (asserted against bulk-delete).
"""
import io

import canvas_store as store
from test_canvas_catalog import setup, upload
from test_canvas_library_folders import image_bytes
from test_local_delete import local_upload, copy_to, doc_with_reference, bulk


def preview(client, keys, project_id=None):
    body = {'keys': keys} if project_id is None else {'keys': keys, 'project_id': project_id}
    r = client.post('/api/canvas/library/items/delete-preview', json=body)
    assert r.status_code == 200, r.json
    return r.json


def test_preview_lists_project_and_canvas_names_with_node_counts():
    client, p, w = setup()
    item = local_upload(client)
    copy = copy_to(client, w, item)
    doc_with_reference(w, copy)
    other_p = store.create_project('别人的项目')['id']
    other_w = store.create_workflow(other_p, '别人的画布')['id']
    other_copy = copy_to(client, other_w, item)
    doc_with_reference(other_w, other_copy)

    plan = preview(client, [item['key']], p)
    rows = {r['workflow_id']: r for r in plan['affected_workflows']}
    assert set(rows) == {w, other_w} and plan['workflows'] == 2
    own, other = rows[w], rows[other_w]
    assert (own['project_title'], own['workflow_title'], own['other_project']) == ('first', 'canvas', False)
    assert (other['project_title'], other['workflow_title'], other['other_project']) == ('别人的项目', '别人的画布', True)
    assert own['canvas_copies'] == 1 and own['affected_nodes'] == 2 and own['removed_nodes'] == 1
    assert sum(r['affected_nodes'] for r in rows.values()) == plan['affected_nodes']
    assert plan['affected_workflows'][0]['workflow_id'] == other_w  # other-project canvases listed first

    # Context decides "other": viewed from the other project the flags flip.
    flipped = {r['workflow_id']: r['other_project'] for r in preview(client, [item['key']], other_p)['affected_workflows']}
    assert flipped == {w: True, other_w: False}
    # No context + unowned local item: every canvas is flagged (warning errs on the visible side).
    assert all(r['other_project'] for r in preview(client, [item['key']])['affected_workflows'])

    # Execution unchanged: same canvases rewritten, same copies deleted.
    result = bulk(client, [item['key']]).json
    assert result['success'] and sorted(result['workflow_ids']) == sorted([w, other_w])
    assert sorted(result['deleted_copy_ids']) == sorted([copy['id'], other_copy['id']])


def test_preview_without_references_and_source_project_fallback():
    client, p, w = setup()
    lonely = local_upload(client, 'blue', 'lonely.png')
    plan = preview(client, [lonely['key']], p)
    assert plan['affected_workflows'] == [] and plan['canvas_copies'] == 0

    lib = upload(client, p, 'green')
    other_p = store.create_project('second')['id']
    other_w = store.create_workflow(other_p, 'far')['id']
    copy_to(client, w, {'selection': {'source': 'library', 'id': lib['id']}})
    copy_to(client, other_w, {'selection': {'source': 'library', 'id': lib['id']}})
    # Without context, the project owning the selected library item is the reference.
    flags = {r['workflow_id']: r['other_project'] for r in preview(client, ['library:' + lib['id']])['affected_workflows']}
    assert flags == {w: False, other_w: True}


def test_preview_rejects_bad_project_context():
    client, p, _ = setup()
    item = local_upload(client)
    for bad in (5, ['x'], 'x' * 201):
        r = client.post('/api/canvas/library/items/delete-preview', json={'keys': [item['key']], 'project_id': bad})
        assert r.status_code == 400


def test_character_uploads_go_to_media_not_the_old_catalog():
    """LIBRARY-GLOBAL S6c: character uploads are media items; the old 本地素材 catalog no longer gets them."""
    client, p, _ = setup()
    plain = local_upload(client, 'red', 'plain.png')
    c = client.post('/api/characters', json={'name': '林'}).json['character']
    r = client.post(f"/api/characters/{c['id']}/images", data={'file': [(io.BytesIO(image_bytes('blue')), 'role.png')]},
                    content_type='multipart/form-data')
    assert r.status_code in (200, 201), r.json
    items = {i['asset']['name']: i for i in client.get('/api/canvas/library/items?scope=all&source=local').json['items']}
    assert set(items) == {'plain.png'} and items['plain.png']['characters'] == []
    media_id = r.json['images'][0]['media_id']
    plan = client.post('/api/canvas/media/delete-preview', json={'ids': [media_id]}).json
    assert [x['name'] for x in plan['characters']] == ['林']
    assert plain['key'] != 'local:' + media_id
