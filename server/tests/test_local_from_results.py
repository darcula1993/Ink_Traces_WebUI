"""LOCAL-FROM-RESULT-20261116: add generated results to 本地素材 as independent copies."""
import os
from pathlib import Path

import pytest
import canvas_store as store
import canvas_writeback
import local_from_results
import local_uploads
import storage
import tasks
from test_canvas_catalog import setup, task_outputs
from test_local_delete import bulk, doc_with_reference

URL = '/api/canvas/library/local/from-results'


class _Reply:
    def __init__(self, status_code, json):
        self.status_code, self.json = status_code, json

    def get_data(self, as_text=False):
        import json as _json
        return _json.dumps(self.json, ensure_ascii=False)


def add(client, items, **extra):
    """LIBRARY-GLOBAL S3: the HTTP endpoint is retired (410); the legacy copy logic is
    still exercised directly until the old tables are dropped."""
    try:
        return _Reply(200, local_from_results.add_results({'items': items, **extra}))
    except store.CanvasError as error:
        return _Reply(error.status, {'success': False, 'error': str(error)})


@pytest.fixture
def legacy_canvas_copies(monkeypatch):
    """Pre-migration canvases hold canvas copies of task results (the input this legacy logic handles).

    LIBRARY-GLOBAL: the integrated write-back references media instead; switch it off only to
    create such legacy copies (see test_canvas_media_refs for the media write-back).
    """
    monkeypatch.setattr(store, 'MEDIA_REFERENCES', False)


def test_from_results_endpoint_is_retired_with_chinese_410():
    client, p, w = setup()
    tid, _ = task_outputs(w, count=1)
    r = client.post(URL, json={'items': [{'source': 'task', 'task_id': tid}]})
    assert r.status_code == 410 and r.json['code'] == 'endpoint_retired' and '移动到文件夹' in r.json['error']
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_local_uploads').fetchone()[0] == 0


def local_items(client):
    r = client.get('/api/canvas/library/items?scope=all&source=local')
    assert r.status_code == 200, r.json
    return r.json['items']


def local_files():
    return sorted(p.name for p in local_uploads.root().iterdir())


def local_path(local_id):
    return local_uploads.path_for(tasks.get_db().execute('SELECT * FROM canvas_local_uploads WHERE id=?', (local_id,)).fetchone())


def test_task_output_becomes_unowned_hardlinked_copy_that_survives_task_trash_and_purge():
    client, p, w = setup()
    tid, selections = task_outputs(w, count=2)
    sources = [Path(a['path']) for a in tasks.list_assets(tid)]
    r = add(client, [{'source': 'task', 'task_id': tid}])
    assert r.status_code == 200, r.json
    assert [i['status'] for i in r.json['items']] == ['created', 'created'] and r.json['skipped'] == []
    assert [i['ref']['output'] for i in r.json['items']] == [s['id'] for s in selections]
    listed = local_items(client)
    assert {i['key'] for i in listed} == {i['key'] for i in r.json['items']}
    assert all(i['project_title'] is None or not i.get('project_id') for i in listed)
    # Only in 全部项目: the project scope never lists unowned local items.
    project = client.get('/api/canvas/library/items', query_string={'project_id': p, 'scope': 'project', 'source': 'local'}).json
    assert project['total'] == 0
    copies = [local_path(i['local_id']) for i in r.json['items']]
    for source, copy in zip(sources, copies):
        assert copy != source and copy.parent == local_uploads.root()
        assert os.stat(copy).st_ino == os.stat(source).st_ino  # hard link, same filesystem
        assert source.exists()  # never moved
    # Trash, then permanently delete the task: the local copies stay readable.
    assert client.delete(f'/api/tasks/{tid}').json['trashed']
    assert client.delete(f'/api/tasks/{tid}?permanent=1').status_code == 200
    assert not any(s.exists() for s in sources)
    for item, copy in zip(r.json['items'], copies):
        assert copy.read_bytes()
        assert client.get(f"/api/canvas/library/items/{item['key']}/download").status_code == 200


def test_history_single_output_and_project_cleanup_keep_local_copy():
    client, p, w = setup()
    tid, selections = task_outputs(w, count=2)
    r = add(client, [{'source': 'task', 'task_id': str(tid), 'output': selections[1]['id']}])
    assert [i['ref'] for i in r.json['items']] == [{'source': 'task', 'task_id': tid, 'output': selections[1]['id']}]
    copy = local_path(r.json['items'][0]['local_id'])
    canvas_writeback.import_task_assets(w, tid)
    assert client.delete('/api/canvas/projects/' + p, json={'cleanup_assets': True}).status_code == 200
    assert copy.exists() and len(local_items(client)) == 1


def test_canvas_node_result_and_copies_deduplicate_by_source_without_new_files(legacy_canvas_copies):
    client, p, w = setup()
    tid, selections = task_outputs(w, count=1)
    imported = canvas_writeback.import_task_assets(w, tid)[0]
    first = add(client, [{'source': 'canvas_asset', 'workflow_id': w, 'asset_id': imported['id']}])
    assert first.json['items'][0]['status'] == 'created', first.json
    copy = local_path(first.json['items'][0]['local_id'])
    canvas_file = store.asset_path(store.get_asset(w, imported['id']))
    assert os.stat(copy).st_ino == os.stat(canvas_file).st_ino and copy != canvas_file
    files = local_files()
    # Same canvas asset again, and the task output that produced it: existing, no new file.
    again = add(client, [{'source': 'canvas_asset', 'workflow_id': w, 'asset_id': imported['id']},
                         {'source': 'task', 'task_id': tid}])
    assert [i['status'] for i in again.json['items']] == ['existing', 'existing']
    assert {i['local_id'] for i in again.json['items']} == {first.json['items'][0]['local_id']}
    assert local_files() == files
    # A canvas copy of a task result (copy provenance task:<id>) traces to the same origin.
    other = store.create_workflow(p, 'other')['id']
    copied = client.post(f'/api/canvas/workflows/{other}/library-references', json={'items': selections}).json['assets'][0]
    traced = add(client, [{'source': 'canvas_asset', 'workflow_id': other, 'asset_id': copied['id']}])
    assert traced.json['items'][0]['status'] == 'existing' and local_files() == files
    rows = dict(tasks.get_db().execute('SELECT source_key,local_id FROM canvas_local_sources').fetchall())
    assert rows['task:' + selections[0]['id']] == first.json['items'][0]['local_id']


def test_copy_of_local_item_on_canvas_returns_that_local_item():
    client, p, w = setup()
    tid, selections = task_outputs(None, count=1)
    created = add(client, [{'source': 'task', 'task_id': tid}]).json['items'][0]
    copied = client.post(f'/api/canvas/workflows/{w}/library-references', json={'items': [{'source': 'local', 'id': created['local_id']}]}).json['assets'][0]
    r = add(client, [{'source': 'canvas_asset', 'workflow_id': w, 'asset_id': copied['id']}])
    assert r.json['items'][0]['status'] == 'existing' and r.json['items'][0]['local_id'] == created['local_id']


def test_deleting_local_copy_keeps_task_output_and_canvas_then_readding_creates_new(legacy_canvas_copies):
    client, p, w = setup()
    tid, selections = task_outputs(w, count=1)
    imported = canvas_writeback.import_task_assets(w, tid)[0]
    saved = doc_with_reference(w, imported)
    created = add(client, [{'source': 'canvas_asset', 'workflow_id': w, 'asset_id': imported['id']}]).json['items'][0]
    task_file = Path(tasks.list_assets(tid)[0]['path'])
    canvas_file = store.asset_path(store.get_asset(w, imported['id']))
    copy = local_path(created['local_id'])
    r = bulk(client, [created['key']])
    assert r.status_code == 200 and r.json['success'] and r.json['canvas_copies'] == 0, r.json
    assert not copy.exists() and task_file.read_bytes() and canvas_file.read_bytes()
    assert store.workflow(w)['revision'] == saved['revision']  # canvas untouched
    assert client.get(imported['url']).status_code == 200
    assert client.get(f"/api/canvas/library/items/task:{selections[0]['id']}/download").status_code == 200
    again = add(client, [{'source': 'task', 'task_id': tid}]).json['items'][0]
    assert again['status'] == 'created' and again['local_id'] != created['local_id']


def test_skipped_reasons_are_chinese_and_carry_no_addresses():
    client, p, w = setup()
    failed = tasks.create_task('image', 'x', {}, status='failed')
    remote = tasks.create_task('image', 'x', {}, status='succeeded')
    tasks.update_task(remote, result={'images': ['https://signed.example/x.png?sig=secret']})
    trashed, _ = task_outputs(None, count=1)
    tasks.move_tasks_to_trash([trashed])
    gone, selections = task_outputs(None, count=1)
    Path(tasks.list_assets(gone)[0]['path']).unlink()
    r = add(client, [{'source': 'task', 'task_id': failed}, {'source': 'task', 'task_id': remote},
                     {'source': 'task', 'task_id': trashed}, {'source': 'task', 'task_id': 999999},
                     {'source': 'task', 'task_id': gone}, {'source': 'task', 'task_id': gone, 'output': '424242'},
                     {'source': 'canvas_asset', 'workflow_id': w, 'asset_id': 'a' * 32},
                     {'source': 'canvas_asset', 'workflow_id': 'b' * 32, 'asset_id': 'a' * 32}])
    assert r.status_code == 200 and r.json['items'] == []
    assert [s['reason'] for s in r.json['skipped']] == [
        '任务未成功，没有可加入的结果', '生成结果尚未下载到本地，暂不能加入', '任务已删除或在回收站', '任务不存在',
        '结果文件不存在或已清理', '结果不存在', '画布素材不存在', '画布不存在或已删除']
    assert 'http' not in r.get_data(as_text=True) and 'sig=' not in r.get_data(as_text=True)
    assert local_files() == []


@pytest.mark.parametrize('payload,status', [
    ({'items': []}, 400),
    ({'items': [{'source': 'task'}]}, 400),
    ({'items': [{'source': 'task', 'task_id': 1, 'path': '/etc/passwd'}]}, 400),
    ({'items': [{'source': 'canvas_asset', 'workflow_id': '../x', 'asset_id': 'a' * 32}]}, 400),
    ({'items': [{'source': 'local', 'id': 'a' * 32}]}, 400),
    ({'items': [{'source': 'task', 'task_id': 1}], 'folder_id': 'f' * 32}, 400),
    ({'items': [{'source': 'task', 'task_id': 1}], 'tag_ids': ['missing']}, 404),
])
def test_invalid_requests_write_nothing(payload, status):
    client, p, w = setup()
    tid, _ = task_outputs(None, count=1)
    payload = {**payload, 'items': [{**i, 'task_id': tid} if i.get('task_id') == 1 else i for i in payload['items']]}
    r = add(client, **payload)
    assert r.status_code == status, r.json
    assert local_files() == [] and tasks.get_db().execute('SELECT count(*) FROM canvas_local_sources').fetchone()[0] == 0


def test_folder_null_is_accepted_and_cross_filesystem_falls_back_to_copy(monkeypatch):
    client, p, w = setup()
    tid, _ = task_outputs(None, count=1)
    source = Path(tasks.list_assets(tid)[0]['path'])

    def no_link(*args):
        raise OSError(18, 'Invalid cross-device link')
    monkeypatch.setattr(local_from_results.os, 'link', no_link)
    created = add(client, [{'source': 'task', 'task_id': tid}], folder_id=None).json['items'][0]
    copy = local_path(created['local_id'])
    assert os.stat(copy).st_ino != os.stat(source).st_ino and copy.read_bytes() == source.read_bytes()
    assert not [n for n in local_files() if n.endswith('.tmp')]


def test_failed_registration_rolls_back_staged_link(monkeypatch):
    client, p, w = setup()
    tid, _ = task_outputs(None, count=1)
    source = Path(tasks.list_assets(tid)[0]['path'])

    def broken(db, local_id, *args):
        raise RuntimeError('boom')
    monkeypatch.setattr(local_from_results, '_attach', broken)
    with pytest.raises(RuntimeError):
        local_from_results.add_results({'items': [{'source': 'task', 'task_id': tid}]})
    assert local_files() == [] and source.exists()
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_local_uploads').fetchone()[0] == 0
