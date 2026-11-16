"""LIBRARY-GLOBAL-20261116 S2: worker registers results into the global library, the write-back
references media ids (no copy), submissions read references through media (legacy ids via alias),
and group runs keep their fingerprint / rebind rules.

All providers are mocks or guards. Documents are checked by the real ``validate_document``
(S1b accepts media references); the S2 test shim was removed at integration (S6a).
"""
import hashlib
import io
import os
from pathlib import Path

import pytest
from PIL import Image

import app as application
import canvas_group_run as group_run
import canvas_media_refs as refs
import canvas_store as store
import canvas_submit
import canvas_writeback
import media_library as media
import storage
import tasks as task_db
import worker
import canvas_group_submit
import test_canvas_group_submit as group_submit_tests
from test_canvas_group_submit import Wire, generation
from test_canvas_writeback import env, make_task, node, doc_node, save_nodes  # noqa: F401  (fixture)


def png(color, size=4):
    data = io.BytesIO()
    Image.new('RGB', (size, size), color).save(data, format='PNG')
    return data.getvalue()


SYSTEM_IMAGE = media.system_folder_id('generated_image')


@pytest.fixture
def submit_env(isolated_backend, monkeypatch):
    """test_canvas_group_submit's env (real submitter/estimator, providers guarded)."""
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(isolated_backend / 'canvas_assets'))

    def guard(*args, **kwargs):
        raise AssertionError('provider must not be called')
    for name in ('get', 'post', 'put', 'delete', 'request'):
        if hasattr(application.HTTP, name):
            monkeypatch.setattr(application.HTTP, name, guard)
    monkeypatch.setattr('requests.Session.request', guard)
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {'api_key': 'test-key', 'endpoint': 'https://provider.invalid', 'model': 'test-model'})
    canvas_group_submit.register()
    project = store.create_project('S2')
    return group_submit_tests.Env(store.create_workflow(project['id'], '画布')['id'])


@pytest.fixture
def media_mode():
    """Media write-back is the integrated default (S1b validate_document accepts media ids); no shim."""
    assert refs.enabled() and store.MEDIA_REFERENCES is True


def media_count():
    return task_db.get_db().execute('SELECT COUNT(*) FROM media').fetchone()[0]


def canvas_files(workflow_id):
    directory = store.asset_root() / workflow_id
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


def output(tid, name, data, kind='output_image', mime='image/png', task_type='image'):
    directory = Path(storage.OUTPUT_DIR) / task_type / str(tid)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    task_db.register_asset(tid, kind, str(path), mime)
    return path


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(worker.application, 'config', {'server': {}})
    return worker.Worker()


# 1 Worker: succeeded outputs enter 生成历史/<kind> once, hard-linked; nothing else does

def test_worker_registers_succeeded_outputs(env, runner, monkeypatch):
    tid = task_db.create_task('image', 'p', {'result_name': '铁门'})

    def execute(task_id):
        output(task_id, 'image_0.png', png('red'))
        output(task_id, 'image_1.png', png('blue'))
        output(task_id, 'thumb_0.webp', png('red'), kind='output_thumbnail', mime='image/webp')
        task_db.complete_task(task_id, {'images': []})
        return {'success': True}, 200
    monkeypatch.setattr(application, 'execute_image_task', execute)
    task = task_db.claim_next_task(runner.worker_id, task_types=('image', 'layer'))
    assert task['id'] == tid
    runner.process(task)
    rows = task_db.get_db().execute('SELECT * FROM media ORDER BY name').fetchall()
    assert [(r['name'], r['folder_id'], r['origin'], r['source_task_id'], r['kind']) for r in rows] == [
        (f'铁门_{tid}.png', SYSTEM_IMAGE, 'generated', tid, 'image'),
        (f'铁门_{tid}_2.png', SYSTEM_IMAGE, 'generated', tid, 'image')]
    linked = {a['kind']: a['media_id'] for a in task_db.list_assets(tid) if a['kind'] == 'output_thumbnail'}
    assert linked == {'output_thumbnail': None}   # thumbnails never enter the library
    for asset in task_db.list_assets(tid):
        if asset['kind'] == 'output_image':
            row = media.get_media(asset['media_id'])
            assert os.stat(media.media_path(row)).st_ino == os.stat(asset['path']).st_ino   # hard link, no copy
    # idempotent: a second hook run (or the write-back) adds nothing
    refs.register_task_outputs(tid)
    assert media_count() == 2
    assert env['calls'] == []


def test_layer_failed_and_unfinished_tasks_are_not_registered(env):
    layer = task_db.create_task('layer', 'p', {}, status='succeeded')
    output(layer, 'base.png', png('red'), task_type='layer')
    failed = task_db.create_task('image', 'p', {}, status='failed')
    output(failed, 'image_0.png', png('blue'))
    pending = task_db.create_task('video', 'p', {}, status='processing')
    output(pending, 'video.mp4', b'not used', kind='output_video', mime='video/mp4', task_type='video')
    for tid in (layer, failed, pending):
        assert refs.register_task_outputs(tid) == []
    assert media_count() == 0


def test_worker_hook_failure_only_logs(env, runner, monkeypatch):
    tid = make_task(env['workflow']['id'], status='succeeded')
    monkeypatch.setattr(media, 'register_generated', lambda *a, **k: (_ for _ in ()).throw(OSError('disk')))
    assert [state for _, state, _ in refs.register_task_outputs_safely(tid)] == ['failed', 'failed']
    runner._register_media(tid)   # never raises
    assert task_db.get_task(tid)['status'] == 'succeeded'


# 2 Write-back references media ids, no copy; deleted results are not resurrected

def test_writeback_references_media_without_copy(env, media_mode):
    wf = env['workflow']
    tid = make_task(wf['id'], colors=('red', 'blue'))
    save_nodes(wf, node('n1', tid))
    task_db.complete_task(tid, {'images': []})
    applied = canvas_writeback.apply_task_result(tid)
    assert list(applied) == [wf['id']]
    result = doc_node(wf, 'n1')
    ids = [a['media_id'] for a in task_db.list_assets(tid) if a['kind'] == 'output_image']
    assert [c['id'] for c in result['candidates']] == ids and result['asset']['id'] == ids[0]
    assert result['asset'] == refs.node_asset(media.get_media(ids[0]))
    assert result['asset']['url'] == f'/api/canvas/media/{ids[0]}'
    assert canvas_files(wf['id']) == []   # no canvas copy
    # idempotent: second write-back changes nothing
    assert canvas_writeback.apply_task_result(tid) == {}
    # POST task-results (manual import) returns the same media references
    response = application.app.test_client().post(f"/api/canvas/workflows/{wf['id']}/task-results", json={'task_id': tid})
    assert response.status_code == 200, response.json
    assert [a['id'] for a in response.json['assets']] == ids
    assert env['calls'] == []


def test_writeback_skips_results_deleted_in_library(env, media_mode):
    wf = env['workflow']
    tid = make_task(wf['id'], colors=('red',))
    task_db.complete_task(tid, {'images': []})
    [(_asset, state, media_id)] = refs.register_task_outputs(tid)
    assert state == 'ok'
    media.delete_media([media_id])
    save_nodes(wf, node('n1', tid))
    assert canvas_writeback.apply_task_result_safely(tid) == {}
    assert media_count() == 0   # the output file still exists but is never re-imported
    assert doc_node(wf, 'n1')['task']['status'] == 'pending'
    with pytest.raises(store.CanvasError, match='已从素材库删除'):
        refs.import_task_media(wf['id'], tid)


def test_without_switch_writeback_keeps_copying(env, monkeypatch):
    # Fallback path only (switch off): the integrated default references media, see above.
    monkeypatch.setattr(store, 'MEDIA_REFERENCES', False)
    wf = env['workflow']
    tid = make_task(wf['id'], colors=('red',))
    save_nodes(wf, node('n1', tid))
    task_db.complete_task(tid, {'images': []})
    canvas_writeback.apply_task_result(tid)
    assert doc_node(wf, 'n1')['asset']['url'].startswith(f"/api/canvas/workflows/{wf['id']}/assets/")
    assert len(canvas_files(wf['id'])) == 1


# 3 Submission reads references through media; old ids via alias; deleted refused

def reference_node(asset):
    return {**generation('g', 'image', '参考 @图片1'), 'referenceAssets': [asset]}


def capabilities():
    with application.app.test_request_context('/'):
        return canvas_submit.live_capabilities()


def test_submit_reads_media_reference_file(submit_env, media_mode):
    media_id, _ = media.import_file(_tmp_png('red'), name='ref.png', origin='upload')
    asset = refs.node_asset(media.get_media(media_id))
    submit_env.save([reference_node(asset)], [], ['g'])
    request = canvas_submit.assemble(submit_env.wid, 'g', capabilities())
    [item] = request['files']
    assert item['asset_id'] == media_id and item['file'] == media.media_path(media.get_media(media_id))
    assert request['multipart']


def test_submit_legacy_canvas_id_uses_alias(submit_env):
    legacy = submit_env.asset(png('green'), 'legacy.png')
    submit_env.save([reference_node(legacy)], [], ['g'])
    # No alias yet: the canvas copy is read as before.
    [item] = canvas_submit.assemble(submit_env.wid, 'g', capabilities())['files']
    assert item['file'] == store.asset_path(store.get_asset(submit_env.wid, legacy['id']))
    # After migration (S1b) the alias wins, even once the old canvas file is gone.
    media_id, _ = media.import_file(item['file'], name='legacy.png', origin='legacy_workflow', link=False)
    with store.write_transaction():
        media.add_alias('workflow', legacy['id'], media_id)
    item['file'].unlink()
    [item] = canvas_submit.assemble(submit_env.wid, 'g', capabilities())['files']
    assert item['asset_id'] == legacy['id'] and item['file'] == media.media_path(media.get_media(media_id))
    assert refs.reference(submit_env.wid, legacy['id'])[1:] == ('image/png', 'image')


def test_submit_refuses_deleted_media_reference(submit_env, media_mode):
    media_id, _ = media.import_file(_tmp_png('red'), name='gone.png', origin='upload')
    upstream = {'id': 'src', 'type': 'asset', 'title': 'src', 'x': 0, 'y': 0}
    asset = refs.node_asset(media.get_media(media_id))
    upstream.update(asset=asset, candidates=[asset], selectedCandidateId=media_id)
    submit_env.save([upstream, generation('g', 'image', '参考 @图片1')], [('src', 'g')], ['g'])
    media.delete_media([media_id])
    # The asset node keeps the id as a "已删除" placeholder; submission is refused before any task.
    assert submit_env.node(submit_env.doc(), 'src')['asset']['id'] == media_id
    before = task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    with pytest.raises(canvas_submit.CanvasSubmitError, match='已从素材库删除'):
        canvas_submit.assemble(submit_env.wid, 'g', capabilities())
    assert task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == before


def test_reference_url_must_match_id(submit_env, media_mode):
    media_id, _ = media.import_file(_tmp_png('red'), name='a.png', origin='upload')
    with pytest.raises(store.CanvasError):
        refs.reference_of(submit_env.wid, {'id': media_id, 'url': refs.MEDIA_PREFIX + 'f' * 32})
    with pytest.raises(store.CanvasError):
        refs.reference_of(submit_env.wid, {'id': media_id, 'url': f'/api/canvas/workflows/other/assets/{media_id}'})


_counter = iter(range(10 ** 6))


def _tmp_png(color):
    path = Path(storage.OUTPUT_DIR) / 'fixtures' / f'{next(_counter)}.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png(color, size=6))
    return path


# 4 Group run with media references: fingerprint, result id and rebind unchanged in rule

def test_group_run_media_chain(submit_env, media_mode, monkeypatch):
    env = submit_env
    media_id, _ = media.import_file(_tmp_png('red'), name='src.png', origin='upload')
    src = refs.node_asset(media.get_media(media_id))
    nodes = [{'id': 'src', 'type': 'asset', 'title': 'src', 'x': 0, 'y': 0, 'asset': src, 'candidates': [src], 'selectedCandidateId': media_id},
             generation('a', 'image', '画一只猫', ratio='16:9'),
             generation('b', 'image', '参考 @图片1 画同一只猫', ratio='1:1', resolution='2K')]
    env.save(nodes, [('src', 'a'), ('a', 'b')], ['a', 'b'])
    wire = Wire(monkeypatch)
    run = env.start()
    a_task = env.entry(run, 'a')['task_id']
    # a's own reference (library item) went to the provider-facing route as its stored bytes
    src_hash = hashlib.sha256(media.media_path(media.get_media(media_id)).read_bytes()).hexdigest()
    assert [f[1:] for f in wire.calls[0]['files']] == [('src.png', 'image/png', src_hash)]
    run = env.finish(a_task)
    a_result = env.node(env.doc(), 'a')['asset']
    assert a_result['url'] == refs.MEDIA_PREFIX + a_result['id']
    assert media.get_media(a_result['id'])['folder_id'] == SYSTEM_IMAGE
    row = task_db.get_db().execute("SELECT status, result_asset_id FROM canvas_group_run_nodes WHERE node_id='a'").fetchone()
    assert (row['status'], row['result_asset_id']) == ('succeeded', a_result['id'])
    b = env.entry(run, 'b')
    assert b['status'] == 'submitted' and b['reason'] is None   # fingerprint unaffected by media ids
    # b received a's library result (rebind to the new id) as its reference
    a_hash = hashlib.sha256(media.media_path(media.get_media(a_result['id'])).read_bytes()).hexdigest()
    assert [f[1:] for f in wire.calls[1]['files']] == [(a_result['name'], 'image/png', a_hash)]
    run = env.finish(b['task_id'])
    assert run['status'] == 'completed'
    assert canvas_files(env.wid) == []   # nothing copied into the canvas


def test_group_run_result_found_after_output_removed(submit_env, media_mode):
    """The run proves "this task's result" by the library hash even when the output file is gone."""
    env = submit_env
    env.save([generation('a', 'image', '画一只猫')], [], ['a'])
    run = env.start()
    a_task = env.entry(run, 'a')['task_id']
    path = output(a_task, 'image_0.png', png('purple'))
    task_db.complete_task(a_task, {'images': [str(path)]})
    canvas_writeback.apply_task_result(a_task)
    media_id = env.node(env.doc(), 'a')['asset']['id']
    path.unlink()   # hard link: the library copy stays
    run = group_run.on_task_terminal(a_task)
    row = task_db.get_db().execute("SELECT status, result_asset_id FROM canvas_group_run_nodes WHERE node_id='a'").fetchone()
    assert (row['status'], row['result_asset_id']) == ('succeeded', media_id)


# 5 S6a: discarding outputs (cancel / refused duplicate completion) never drops the task->media link

def test_remove_task_output_files_keeps_library_linked_outputs(env):
    tid = task_db.create_task('image', 'p', {'result_name': '铁门'})
    kept = output(tid, 'image_0.png', png('red'))
    thumb = output(tid, 'thumb_0.webp', png('red', 2), kind='output_thumbnail', mime='image/webp')
    task_db.complete_task(tid, {'images': []})
    [(_asset, state, media_id)] = refs.register_task_outputs(tid)
    assert state == 'ok'
    # A late duplicate run of the already succeeded task is refused by complete_task and discards
    # its outputs: the registered output keeps its row (media_id) and file, the rest goes.
    assert task_db.complete_task(tid, {'images': []}) is False
    assert storage.remove_task_output_files(tid) == 1
    assert [(a['kind'], a['media_id']) for a in task_db.list_assets(tid)] == [('output_image', media_id)]
    assert kept.exists() and not thumb.exists()
    assert media.status(media_id)[0] == 'ok' and media.media_path(media.get_media(media_id)).is_file()
    # Idempotent re-registration still finds the same item, nothing new.
    assert refs.register_task_outputs(tid) == [(_asset, 'ok', media_id)] and media_count() == 1
    assert env['calls'] == []


def test_cancelled_task_outputs_are_still_removed(env):
    tid = task_db.create_task('image', 'p', {})
    path = output(tid, 'image_0.png', png('blue'))
    assert refs.register_task_outputs(tid) == []   # never succeeded -> never registered
    assert storage.remove_task_output_files(tid) == 1
    assert task_db.list_assets(tid) == [] and not path.exists() and media_count() == 0
