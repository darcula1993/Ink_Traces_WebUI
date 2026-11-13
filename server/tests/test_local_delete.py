"""LOCAL-DELETE-20261113: permanent local delete, canvas copy cascade and select-all."""
import io
from pathlib import Path

import pytest
import app as application
import canvas_store as store
import local_uploads
import tasks
from test_canvas_catalog import setup, upload, task_outputs
from test_canvas_library_folders import image_bytes


def local_upload(client, color='red', name='raw.png'):
    r = client.post('/api/workspace/assets/img_tabs', data={'file': (io.BytesIO(image_bytes(color)), name)})
    assert r.status_code == 201, r.json
    items = client.get('/api/canvas/library/items?scope=all&source=local').json['items']
    return next(i for i in items if i['asset']['name'] == name)


def copy_to(client, w, item):
    r = client.post(f'/api/canvas/workflows/{w}/library-references', json={'items': [item['selection']]})
    assert r.status_code == 200, r.json
    return r.json['assets'][0]


def doc_with_reference(w, asset, extra_nodes=()):
    current = store.workflow(w)
    nodes = [
        {'id': 'src', 'type': 'asset', 'title': 'a', 'x': 0, 'y': 0, 'asset': asset, 'candidates': [asset], 'selectedCandidateId': asset['id']},
        {'id': 'gen', 'type': 'image', 'title': 'g', 'x': 300, 'y': 0, 'text': '参考 @图片1', 'params': {},
         'referenceAssets': [asset], 'referenceOrder': [asset['id']], 'referenceMentions': {'@图片1': asset['id']},
         'referenceGroups': [{'id': 'grp', 'title': '组', 'asset_ids': [asset['id']]}]},
        *extra_nodes]
    document = {'version': 1, 'nodes': nodes, 'edges': [{'id': 'e1', 'source': 'src', 'target': 'gen'}],
                'viewport': {'x': 0, 'y': 0, 'zoom': 1}, 'groups': [{'id': 'g1', 'title': '节点组1', 'nodeIds': ['src', 'gen']}]}
    return store.update_workflow(w, current['title'], document, current['revision'])


def bulk(client, keys, path='bulk-delete', **headers):
    return client.post('/api/canvas/library/items/' + path, json={'keys': keys}, headers=headers)


def test_delete_cascades_canvas_copies_and_rewrites_documents():
    client, p, w = setup()
    item = local_upload(client)
    copy = copy_to(client, w, item)
    other_w = store.create_workflow(p, 'second')['id']
    second = copy_to(client, other_w, item)
    # Canvas-to-canvas copy of a copy is followed transitively.
    third_w = store.create_workflow(p, 'third')['id']
    chained = client.post(f'/api/canvas/workflows/{third_w}/library-references', json={'items': [{'source': 'workflow', 'id': copy['id']}]}).json['assets'][0]
    saved = doc_with_reference(w, copy)
    local_file = local_uploads.path_for(tasks.get_db().execute('SELECT * FROM canvas_local_uploads').fetchone())
    copy_file = store.asset_path(store.get_asset(w, copy['id']))

    preview = bulk(client, [item['key']], 'delete-preview')
    assert preview.status_code == 200, preview.json
    assert preview.json['items'] == 1 and preview.json['canvas_copies'] == 3 and preview.json['workflows'] == 3
    assert preview.json['affected_nodes'] == 2 and preview.json['removed_nodes'] == 1
    assert local_file.exists()  # preview never mutates

    r = bulk(client, [item['key']])
    assert r.status_code == 200 and r.json['success'], r.json
    assert sorted(r.json['deleted_copy_ids']) == sorted([copy['id'], second['id'], chained['id']])
    assert not local_file.exists() and not copy_file.exists()
    assert not any(path.name.count('.deleting-') for path in store.asset_root().rglob('*'))
    assert client.get(item['asset']['url']).status_code == 404
    assert client.get(copy['url']).status_code == 404
    updated = store.workflow(w)
    assert updated['revision'] == saved['revision'] + 1
    gen = updated['document']['nodes']
    assert [n['id'] for n in gen] == ['gen']
    node = gen[0]
    assert node['referenceAssets'] == [] and node['referenceOrder'] == [] and node['referenceMentions'] == {} and node['referenceGroups'] == []
    assert node['text'] == '参考 @图片1'  # user prompt text is never rewritten
    assert updated['document']['edges'] == [] and updated['document']['groups'] == [{'id': 'g1', 'title': '节点组1', 'nodeIds': ['gen']}]
    assert client.get('/api/canvas/library/items?scope=all&source=local').json['total'] == 0


def test_shared_originals_project_library_generated_and_cupsy_are_kept():
    client, p, w = setup()
    item = local_upload(client)
    # Project library copy (project material) with identical content stays.
    saved = client.post(f'/api/canvas/projects/{p}/library-items/save', json={'items': [item['selection']]}).json['assets'][0]
    # Direct canvas upload of the same bytes is an independent upload, not a copy.
    direct = upload(client, store.create_workflow(p, 'direct')['id'], 'red', workflow=True)
    tid, refs = task_outputs(w, 1)
    row = tasks.get_db().execute('SELECT * FROM canvas_local_uploads').fetchone()
    original = local_uploads.path_for(row)
    # A second registration sharing the physical original (dedup) keeps the file.
    tasks.get_db().execute('INSERT INTO canvas_local_uploads VALUES (?,?,?,?,?,?,?,?)',
                           ('f' * 32, 'alias.png', row['mime_type'], row['kind'], 'other-digest', row['size_bytes'], row['filename'], row['created_at']))
    tasks.get_db().commit()
    r = bulk(client, [item['key'], 'task:' + refs[0]['id'], 'cupsy:7'])
    assert r.status_code == 200 and r.json['success'] is False
    assert {x['key'] for x in r.json['rejected']} == {'task:' + refs[0]['id'], 'cupsy:7'}
    assert r.json['deleted_keys'] == [item['key']] and r.json['files_retained_shared'] == 1
    assert original.exists()
    assert client.get(saved['url']).status_code == 200 and client.get(direct['url']).status_code == 200
    assert client.get(f"/api/canvas/library/items/task:{refs[0]['id']}/download").status_code == 200
    # Deleting the alias now removes the last owner of the original.
    assert bulk(client, ['local:' + 'f' * 32]).json['files_removed'] == 1
    assert not original.exists()


def test_project_and_direct_canvas_uploads_are_deleted_with_their_copies():
    client, p, w = setup()
    lib = upload(client, p, 'blue')
    group = client.post(f'/api/canvas/projects/{p}/asset-groups', json={'title': '组', 'asset_ids': [lib['id']]}).json['group']
    other = upload(client, p, 'green')
    group2 = client.post(f'/api/canvas/projects/{p}/asset-groups', json={'title': '组2', 'asset_ids': [lib['id'], other['id']]}).json['group']
    # Group snapshot route also records provenance.
    snap = client.post(f'/api/canvas/workflows/{w}/reference-assets', json={'group_ids': [group['id']]}).json['assets'][0]
    second_w = store.create_workflow(p, 'second')['id']
    direct = upload(client, second_w, 'red', workflow=True)
    third_w = store.create_workflow(p, 'third')['id']
    direct_copy = client.post(f'/api/canvas/workflows/{third_w}/library-references', json={'items': [{'source': 'workflow', 'id': direct['id']}]}).json['assets'][0]
    doc_with_reference(w, snap)
    doc_with_reference(second_w, direct)
    lib_file = store.asset_path(store.get_asset(p, lib['id'], library=True))
    keys = ['library:' + lib['id'], 'workflow:' + direct['id']]
    preview = bulk(client, keys, 'delete-preview').json
    assert preview['items'] == 2 and preview['canvas_copies'] == 2 and preview['workflows'] == 3
    assert preview['removed_nodes'] == 2 and 'hidden' not in preview
    r = bulk(client, keys).json
    assert r['success'] and set(r['deleted_keys']) == set(keys)
    assert sorted(r['deleted_copy_ids']) == sorted([snap['id'], direct_copy['id']])
    for url in (lib['url'], direct['url'], snap['url'], direct_copy['url']):
        assert client.get(url).status_code == 404
    assert not lib_file.exists() and client.get(other['url']).status_code == 200
    groups = client.get(f'/api/canvas/projects/{p}/asset-groups').json['groups']
    assert [(g['id'], g['asset_ids']) for g in groups] == [(group2['id'], [other['id']])]
    for workflow_id in (w, second_w):
        assert [n['id'] for n in store.workflow(workflow_id)['document']['nodes']] == ['gen']
    # No hash fallback: an unrelated canvas asset with identical bytes but no provenance stays.
    item = local_upload(client, 'green', 'same.png')
    lookalike = store.save_asset(w, io.BytesIO(image_bytes('green')), 'lookalike.png')
    assert bulk(client, [item['key']]).json['deleted_copy_ids'] == []
    assert client.get(lookalike['url']).status_code == 200


def test_concurrent_editor_gets_conflict_after_delete():
    client, p, w = setup()
    item = local_upload(client)
    copy = copy_to(client, w, item)
    stale = doc_with_reference(w, copy)
    assert bulk(client, [item['key']]).status_code == 200
    # The open editor still holds the old revision and a reference to the deleted copy.
    r = client.put(f'/api/canvas/workflows/{w}', json={'title': stale['title'], 'document': stale['document'], 'revision': stale['revision']})
    assert r.status_code == 409
    fresh = store.workflow(w)
    r = client.put(f'/api/canvas/workflows/{w}', json={'title': fresh['title'], 'document': stale['document'], 'revision': fresh['revision']})
    assert r.status_code == 400  # the deleted copy can no longer be referenced


def test_rollback_leaves_no_half_deleted_state(monkeypatch):
    client, p, w = setup()
    item = local_upload(client)
    copy = copy_to(client, w, item)
    doc_with_reference(w, copy)
    before = store.workflow(w)
    real = __import__('os').rename
    calls = []
    def flaky(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise OSError('synthetic')
        return real(src, dst)
    import local_delete
    monkeypatch.setattr(local_delete.os, 'rename', flaky)
    r = bulk(client, [item['key']])
    assert r.status_code == 409
    monkeypatch.setattr(local_delete.os, 'rename', real)
    assert store.workflow(w)['revision'] == before['revision']
    assert client.get(item['asset']['url']).status_code == 200 and client.get(copy['url']).status_code == 200
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_assets').fetchone()[0] == 1


@pytest.mark.parametrize('keys', [None, [], 'local:x', ['local:../../etc'], ['local:' + 'A' * 32], ['task:0'], ['bogus:' + 'a' * 32], [1], ['x'] * 501])
def test_invalid_ids_rejected_without_changes(keys):
    client, p, w = setup()
    item = local_upload(client)
    r = client.post('/api/canvas/library/items/bulk-delete', json={'keys': keys})
    assert r.status_code == 400, r.json
    assert client.get(item['asset']['url']).status_code == 200


def test_missing_ids_reported_and_same_origin_enforced():
    client, p, w = setup()
    item = local_upload(client)
    gone = 'local:' + 'e' * 32
    assert bulk(client, [item['key']], Origin='https://evil.example').status_code == 403
    assert bulk(client, [item['key']], **{'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.post('/api/canvas/library/items/bulk-delete', data='{"keys":[]}', content_type='text/plain').status_code == 415
    assert client.get(item['asset']['url']).status_code == 200
    r = bulk(client, [item['key'], gone], Origin='http://localhost')
    assert r.status_code == 200 and r.json['missing'] == [gone] and r.json['deleted_keys'] == [item['key']]


def test_login_required_when_auth_enabled(monkeypatch):
    client, p, w = setup()
    item = local_upload(client)
    monkeypatch.setattr(application, 'AUTH_CONFIG', {'username': 'u', 'password': 'p'})
    assert bulk(client, [item['key']]).status_code == 401
    assert bulk(client, [item['key']], 'delete-preview').status_code == 401


def test_select_all_returns_every_filtered_item_beyond_page():
    client, p, w = setup()
    for i in range(3):
        local_upload(client, ['red', 'blue', 'green'][i], f'n{i}.png')
    page = client.get('/api/canvas/library/items?scope=all&source=local&limit=1').json
    assert page['total'] == 3 and len(page['items']) == 1
    every = client.get('/api/canvas/library/item-selection?scope=all&source=local&limit=1&q=n').json
    assert every['total'] == 3 and len(every['items']) == 3
    assert client.get('/api/canvas/library/item-selection?scope=all&source=local&q=n1').json['total'] == 1


def import_task(client, w, color='red'):
    from test_canvas_catalog import task_outputs
    tid, _ = task_outputs(w, 1)  # task_outputs writes a red image0
    r = client.post(f'/api/canvas/workflows/{w}/task-results', json={'task_id': tid})
    assert r.status_code == 200, r.json
    return r.json['assets'][0]


def test_copy_deduplicated_onto_direct_upload_keeps_it():
    """QA D1/B: direct canvas upload first, then same-bytes local copy into that canvas."""
    client, p, w = setup()
    direct = upload(client, w, 'red', workflow=True)
    item = local_upload(client, 'red', 'same.png')
    copy = copy_to(client, w, item)
    assert copy['id'] == direct['id']  # same-canvas hash dedup
    saved = doc_with_reference(w, copy)
    r = bulk(client, [item['key']]).json
    assert r['deleted_copy_ids'] == [] and r['canvas_copies'] == 0
    assert client.get(direct['url']).status_code == 200
    # The independent asset survives, so node references to it stay valid and untouched.
    after = store.workflow(w)
    assert after['document'] == saved['document']


def test_copy_deduplicated_onto_imported_generation_result_keeps_it():
    """QA D1/A: imported task result first, then same-bytes local copy."""
    client, p, w = setup()
    generated = import_task(client, w)
    item = local_upload(client, 'red', 'reupload.png')
    assert copy_to(client, w, item)['id'] == generated['id']
    assert bulk(client, [item['key']]).json['deleted_copy_ids'] == []
    assert client.get(generated['url']).status_code == 200


def test_independent_save_onto_existing_copy_detaches_it():
    """QA D1/M: local copy first, then a same-bytes task import / direct upload / snapshot."""
    client, p, w = setup()
    item = local_upload(client, 'red', 'first.png')
    copy = copy_to(client, w, item)
    generated = import_task(client, w)
    assert generated['id'] == copy['id']
    assert bulk(client, [item['key']]).json['deleted_copy_ids'] == []
    assert client.get(generated['url']).status_code == 200
    # Same for a direct upload deduplicated onto a pure copy.
    w2 = store.create_workflow(p, 'w2')['id']
    item2 = local_upload(client, 'blue', 'second.png')
    copy2 = copy_to(client, w2, item2)
    assert upload(client, w2, 'blue', workflow=True)['id'] == copy2['id']
    assert bulk(client, [item2['key']]).json['deleted_copy_ids'] == []
    assert client.get(copy2['url']).status_code == 200


def test_copy_with_two_sources_survives_until_both_are_deleted():
    client, p, w = setup()
    lib = upload(client, p, 'green')
    item = local_upload(client, 'green', 'twin.png')  # same bytes as the project asset
    via_snapshot = client.post(f'/api/canvas/workflows/{w}/reference-assets', json={'asset_ids': [lib['id']]}).json['assets'][0]
    assert copy_to(client, w, item)['id'] == via_snapshot['id']
    assert bulk(client, [item['key']]).json['deleted_copy_ids'] == []
    assert client.get(via_snapshot['url']).status_code == 200
    assert bulk(client, ['library:' + lib['id']]).json['deleted_copy_ids'] == [via_snapshot['id']]
    assert client.get(via_snapshot['url']).status_code == 404
    # Preview of both together counts the shared copy once.
    w2 = store.create_workflow(p, 'w2')['id']
    lib2 = upload(client, p, 'blue')
    item2 = local_upload(client, 'blue', 'twin2.png')
    client.post(f'/api/canvas/workflows/{w2}/reference-assets', json={'asset_ids': [lib2['id']]})
    copy_to(client, w2, item2)
    assert bulk(client, [item2['key'], 'library:' + lib2['id']], 'delete-preview').json['canvas_copies'] == 1


def test_recopying_a_copy_onto_itself_keeps_it_deletable():
    client, p, w = setup()
    item = local_upload(client)
    copy = copy_to(client, w, item)
    again = client.post(f'/api/canvas/workflows/{w}/library-references', json={'items': [{'source': 'workflow', 'id': copy['id']}]}).json['assets'][0]
    assert again['id'] == copy['id']
    assert bulk(client, [item['key']]).json['deleted_copy_ids'] == [copy['id']]
