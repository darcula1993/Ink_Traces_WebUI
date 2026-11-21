"""STORAGE-GC-COMPACT-20261121: tests for completed deletion compaction, empty legacy
canvas dir pruning, orphan disk GC (layer outputs, layer_projects, cupsy_assets,
legacy canvas dirs), orphan workspace_assets cleanup, and soft-deleted layer DB slimming.
"""
import io
import json
import os
import time
from pathlib import Path

from PIL import Image
import pytest

import app as application
import canvas_cleanup as cleanup
import canvas_store as store
import cost_estimate
import cost_ledger
import media_library
import storage
import tasks as task_db
import worker


def _png_bytes(size=(16, 16), color=(120, 40, 200)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    return buf.getvalue()


def _age(path, seconds_ago):
    ts = time.time() - seconds_ago
    os.utime(path, (ts, ts))


def _rich_workflow_doc(task_id):
    return {
        'version': 1,
        'viewport': {'x': 123.5, 'y': -456.0, 'zoom': 0.85},
        'nodes': [
            {
                'id': 'node-img-1',
                'type': 'image_gen',
                'title': '主角定妆',
                'x': 100,
                'y': 200,
                'prompt': 'A' * 4000,
                'params': {'size': '2K', 'aspect_ratio': '16:9', 'seed': 42},
                'candidates': [{'id': 'c1', 'url': '/api/canvas/media/deadbeef', 'extra': 'B' * 500}],
                'references': [{'asset_id': 'ref1', 'kind': 'image'}],
                'asset': {'id': 'a1', 'url': '/api/canvas/media/deadbeef'},
                'error': 'some old error message',
                'task': {'id': task_id, 'status': 'succeeded', 'result': {'big': 'C' * 500}},
            },
            {
                'id': 'node-note-2',
                'type': 'text',
                'x': 300,
                'y': 400,
                'text': 'long note ' * 200,
            },
        ],
        'edges': [{'id': 'e1', 'source': 'node-note-2', 'target': 'node-img-1'}],
        'groups': [{'id': 'g1', 'title': '节点组1', 'nodeIds': ['node-img-1']}],
    }


def _set_workflow_doc(workflow_id, document):
    db = task_db.get_db()
    db.execute(
        'UPDATE canvas_workflows SET document = ?, revision = revision + 1 WHERE id = ?',
        (json.dumps(document, ensure_ascii=False), workflow_id),
    )
    db.commit()


def _make_legacy_workflow_with_asset(title='wf', color=(200, 30, 30)):
    project = store.create_project(f'proj-{title}')
    wf = store.create_workflow(project['id'], title)
    asset = store.save_asset(wf['id'], io.BytesIO(_png_bytes(color=color)), f'{title}.png')
    path = store.asset_path(store.get_asset(wf['id'], asset['id']))
    return project, wf, asset, path


# ---------------------------------------------------------------------------
# AC 1: Completed deletion DB compaction & idempotency
# ---------------------------------------------------------------------------

def test_delete_workflow_and_project_compacts_manifest_and_document():
    project, wf, _, path = _make_legacy_workflow_with_asset('compact-wf')
    tid = task_db.create_task(
        'image', 'hero prompt',
        {'canvas_workflow_id': wf['id'], 'resolution': '2K', 'aspect_ratio': '1:1'},
        provider='ark', status='succeeded',
    )
    _set_workflow_doc(wf['id'], _rich_workflow_doc(tid))

    res = cleanup.delete_scope('workflow', wf['id'], True)
    assert res['deleted'] is True and res['removed_files'] == 1
    assert not path.exists()

    db = task_db.get_db()
    row = db.execute("SELECT completed, manifest FROM canvas_deletions WHERE scope='workflow' AND id=?", (wf['id'],)).fetchone()
    assert row['completed'] == 1
    manifest = json.loads(row['manifest'])
    assert manifest['compacted'] is True
    assert manifest['cleanup_assets'] is True
    assert manifest['title'] == 'compact-wf'
    assert manifest['project_id'] == project['id']
    assert manifest['workflow_ids'] == [wf['id']]
    for dropped in ('candidates', 'library_snapshot', 'done', 'removed_paths', 'shared_task_ids'):
        assert dropped not in manifest

    wf_row = db.execute('SELECT document FROM canvas_workflows WHERE id=?', (wf['id'],)).fetchone()
    doc = json.loads(wf_row['document'])
    assert doc == {
        'version': 1,
        'compacted': True,
        'nodes': [
            {'id': 'node-img-1', 'type': 'image_gen', 'title': '主角定妆', 'task': {'id': tid}},
            {'id': 'node-note-2', 'type': 'text'},
        ],
        'edges': [],
        'groups': [],
    }

    # Idempotent retry of delete_scope returns identical result; wrong cleanup flag still raises 409.
    assert cleanup.delete_scope('workflow', wf['id'], True) == res
    with pytest.raises(store.CanvasError) as exc:
        cleanup.delete_scope('workflow', wf['id'], False)
    assert exc.value.status == 409

    # Repeat compaction is strictly idempotent.
    assert cleanup.compact_completed_deletions() == {'manifests': 0, 'workflows': 0, 'layer_projects': 0}

    # Project-level deletion compacts all child workflows too.
    p2, wf2, _, _ = _make_legacy_workflow_with_asset('compact-proj', color=(10, 200, 10))
    tid2 = task_db.create_task('image', 'p2', {'canvas_workflow_id': wf2['id']}, provider='ark', status='succeeded')
    _set_workflow_doc(wf2['id'], _rich_workflow_doc(tid2))
    cleanup.delete_scope('project', p2['id'], True)
    doc2 = json.loads(db.execute('SELECT document FROM canvas_workflows WHERE id=?', (wf2['id'],)).fetchone()['document'])
    assert doc2['compacted'] is True and doc2['nodes'][0]['task'] == {'id': tid2}
    assert cleanup.compact_completed_deletions() == {'manifests': 0, 'workflows': 0, 'layer_projects': 0}


def test_compact_handles_legacy_empty_manifest_without_keyerror():
    project = store.create_project('legacy-empty')
    wf = store.create_workflow(project['id'], 'legacy-wf')
    db = task_db.get_db()
    db.execute("INSERT INTO canvas_deletions (scope, id, manifest, completed) VALUES ('workflow', ?, '{}', 1)", (wf['id'],))
    db.commit()

    stats = cleanup.compact_completed_deletions()
    assert stats['manifests'] == 1 and stats['workflows'] == 1
    manifest = json.loads(
        db.execute("SELECT manifest FROM canvas_deletions WHERE scope='workflow' AND id=?", (wf['id'],)).fetchone()['manifest']
    )
    assert manifest['compacted'] is True
    assert manifest['cleanup_assets'] is False
    assert manifest['removed_library_ids'] == []
    assert cleanup.compact_completed_deletions() == {'manifests': 0, 'workflows': 0, 'layer_projects': 0}


# ---------------------------------------------------------------------------
# AC 2: Cost ledger & media library provenance survive compaction intact
# ---------------------------------------------------------------------------

def test_compacted_deleted_scope_preserves_cost_ledger_and_media_provenance(tmp_path):
    project = store.create_project('短剧项目甲')
    wf = store.create_workflow(project['id'], '第一集分镜')
    # Deliberately omit canvas_node_id from task params so attribution relies on node.task.id!
    tid = task_db.create_task(
        'image', 'cyberpunk skyline',
        {'canvas_workflow_id': wf['id'], 'resolution': '2K', 'aspect_ratio': '16:9', 'model': 'seedream-5-0-pro'},
        provider='ark', status='succeeded',
    )
    _set_workflow_doc(wf['id'], _rich_workflow_doc(tid))

    out_dir = Path(storage.task_output_dir('image', tid))
    out_file = out_dir / 'out.png'
    out_file.write_bytes(_png_bytes(color=(55, 160, 220)))
    task_db.register_asset(tid, 'output_image', str(out_file), 'image/png')
    media_id = media_library.register_generated(tid, str(out_file), 'image', name='out.png')

    # Snapshot provenance & ledger BEFORE deletion for comparison.
    db = task_db.get_db()
    before_ledger = cost_ledger.build_ledger(project_id=project['id'])
    assert before_ledger['projects'][0]['workflows'][0]['nodes'][0]['title'] == '主角定妆'

    cleanup.delete_scope('project', project['id'], True)

    # Confirm document was actually compacted.
    compacted_doc = json.loads(db.execute('SELECT document FROM canvas_workflows WHERE id=?', (wf['id'],)).fetchone()['document'])
    assert compacted_doc['compacted'] is True
    assert cleanup._doc_tasks(compacted_doc) == {tid}

    # Cost ledger still resolves deleted project/workflow/node names and (workflow_id, task_id) -> node_id.
    after_ledger = cost_ledger.build_ledger(project_id=project['id'])
    assert len(after_ledger['projects']) == 1
    p_entry = after_ledger['projects'][0]
    assert p_entry['id'] == project['id']
    assert p_entry['title'] == '短剧项目甲'
    assert p_entry['deleted'] is True
    wf_entry = p_entry['workflows'][0]
    assert wf_entry['id'] == wf['id']
    assert wf_entry['title'] == '第一集分镜'
    node_entry = wf_entry['nodes'][0]
    assert node_entry['node_id'] == 'node-img-1'
    assert node_entry['title'] == '主角定妆'
    assert node_entry['type'] == 'image_gen'
    assert node_entry['missing'] is False

    # Also verify direct workflow deletion sets workflow deleted=True in cost_ledger while preserving titles/nodes.
    p_wf = store.create_project('短剧项目乙')
    wf_del = store.create_workflow(p_wf['id'], '第二集分镜')
    tid_wf = task_db.create_task(
        'image', 'neon street',
        {'canvas_workflow_id': wf_del['id'], 'resolution': '2K', 'aspect_ratio': '1:1', 'model': 'seedream-5-0-pro'},
        provider='ark', status='succeeded',
    )
    _set_workflow_doc(wf_del['id'], _rich_workflow_doc(tid_wf))
    cleanup.delete_scope('workflow', wf_del['id'], True)
    wf_ledger = cost_ledger.build_ledger(project_id=p_wf['id'])
    assert wf_ledger['projects'][0]['deleted'] is False
    assert wf_ledger['projects'][0]['workflows'][0]['deleted'] is True
    assert wf_ledger['projects'][0]['workflows'][0]['title'] == '第二集分镜'
    assert wf_ledger['projects'][0]['workflows'][0]['nodes'][0]['node_id'] == 'node-img-1'
    assert wf_ledger['projects'][0]['workflows'][0]['nodes'][0]['title'] == '主角定妆'

    # Media library provenance still resolves deleted flags and titles.
    ctx = media_library._provenance_context(db)
    assert ctx['projects'][project['id']]['deleted'] is True
    assert ctx['workflows'][wf['id']]['deleted'] is True
    assert ctx['workflows'][wf['id']]['node_by_task'][tid] == 'node-img-1'
    media_row = db.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()
    prov = media_library._provenance_for_rows(db, [media_row], ctx=ctx)[media_id]
    assert prov['project_id'] == project['id']
    assert prov['project_title'] == '短剧项目甲'
    assert prov['workflow_id'] == wf['id']
    assert prov['workflow_title'] == '第一集分镜'
    assert prov['node_id'] == 'node-img-1'
    assert prov['node_title'] == '主角定妆'


# ---------------------------------------------------------------------------
# AC 3: Protective invariants
# ---------------------------------------------------------------------------

def test_pending_deletion_never_compacted(monkeypatch):
    project, wf, _, path = _make_legacy_workflow_with_asset('pending-wf')
    tid = task_db.create_task('image', 'p', {'canvas_workflow_id': wf['id']}, status='succeeded')
    _set_workflow_doc(wf['id'], _rich_workflow_doc(tid))

    original_unlink = Path.unlink
    monkeypatch.setattr(Path, 'unlink', lambda *a, **k: (_ for _ in ()).throw(OSError('disk busy')))
    with pytest.raises(store.CanvasError):
        cleanup.delete_scope('workflow', wf['id'], True)

    # Calling compaction while completed=0 must touch NOTHING.
    assert cleanup.compact_completed_deletions() == {'manifests': 0, 'workflows': 0, 'layer_projects': 0}

    db = task_db.get_db()
    row = db.execute("SELECT completed, manifest FROM canvas_deletions WHERE scope='workflow' AND id=?", (wf['id'],)).fetchone()
    assert row['completed'] == 0
    manifest = json.loads(row['manifest'])
    assert 'compacted' not in manifest and 'candidates' in manifest
    wf_doc = json.loads(db.execute('SELECT document FROM canvas_workflows WHERE id=?', (wf['id'],)).fetchone()['document'])
    assert 'compacted' not in wf_doc and len(wf_doc['edges']) == 1

    # Also verify a completed=1 project deletion will not compact a child workflow with completed=0.
    db.execute(
        "INSERT INTO canvas_deletions (scope, id, manifest, completed) VALUES ('project', ?, ?, 1)",
        (project['id'], json.dumps({'title': project['title'], 'cleanup_assets': True, 'workflow_ids': [wf['id']]})),
    )
    db.commit()
    stats = cleanup.compact_completed_deletions()
    assert stats['manifests'] == 1 and stats['workflows'] == 0
    wf_doc_still_full = json.loads(db.execute('SELECT document FROM canvas_workflows WHERE id=?', (wf['id'],)).fetchone()['document'])
    assert 'compacted' not in wf_doc_still_full

    # Restore unlink and finish retry -> now both manifest & workflow compact cleanly.
    monkeypatch.setattr(Path, 'unlink', original_unlink)
    cleanup.delete_scope('workflow', wf['id'], True)
    assert not path.exists()
    wf_doc_after = json.loads(db.execute('SELECT document FROM canvas_workflows WHERE id=?', (wf['id'],)).fetchone()['document'])
    assert wf_doc_after['compacted'] is True


def test_non_cleanup_archive_retains_live_task_ids_and_paths_and_protects_future_deletes(tmp_path):
    project, wf1, _, path1 = _make_legacy_workflow_with_asset('retain-1', color=(99, 88, 77))
    live_tid = task_db.create_task('image', 'live', {'canvas_workflow_id': wf1['id']}, status='succeeded')
    gone_path = str(tmp_path / 'canvas_assets' / 'nonexistent.png')
    # Insert a historical uncompacted completed=1 manifest with cleanup_assets=False
    # containing both live and dead task_ids / retained_paths.
    db = task_db.get_db()
    historical_manifest = {
        'title': 'retain-1',
        'cleanup_assets': False,
        'project_id': project['id'],
        'workflow_ids': [wf1['id']],
        'removed_library_ids': [],
        'task_ids': [live_tid, 999999],
        'retained_paths': [str(path1), gone_path],
        'candidates': [{'path': str(path1)}],
        'library_snapshot': [{'id': 'snap'}],
        'done': [],
        'removed_paths': [],
        'shared_task_ids': [],
    }
    db.execute(
        "INSERT INTO canvas_deletions (scope, id, manifest, completed) VALUES ('workflow', ?, ?, 1)",
        (wf1['id'], json.dumps(historical_manifest)),
    )
    db.commit()

    stats = cleanup.compact_completed_deletions()
    assert stats['manifests'] == 1 and stats['workflows'] == 1
    compacted = json.loads(
        db.execute("SELECT manifest FROM canvas_deletions WHERE scope='workflow' AND id=?", (wf1['id'],)).fetchone()['manifest']
    )
    assert compacted['compacted'] is True
    assert compacted['task_ids'] == [live_tid]
    assert compacted['retained_paths'] == [str(path1)]
    assert 'candidates' not in compacted and 'library_snapshot' not in compacted

    # Subsequent project delete with cleanup=True MUST respect retained_paths and keep path1!
    res = cleanup.delete_scope('project', project['id'], True)
    assert path1.exists() and res['retained_shared'] >= 1


def test_is_library_asset_deleted_preserved_after_compaction():
    project, wf, _, path = _make_legacy_workflow_with_asset('lib-del', color=(44, 55, 66))
    with path.open('rb') as handle:
        lib_asset = store.save_asset(project['id'], handle, 'lib.png', library=True)
    cleanup.delete_scope('workflow', wf['id'], True)
    assert cleanup.is_library_asset_deleted(lib_asset['id']) is True
    db = task_db.get_db()
    manifest = json.loads(
        db.execute("SELECT manifest FROM canvas_deletions WHERE scope='workflow' AND id=?", (wf['id'],)).fetchone()['manifest']
    )
    assert manifest['compacted'] is True
    assert lib_asset['id'] in manifest['removed_library_ids']


def test_canvas_assets_media_never_deleted_by_gc_or_delete_scope():
    uploaded, _ = media_library.save_upload(io.BytesIO(_png_bytes(color=(12, 34, 56))), 'keep.png', origin='upload')
    media_file = media_library.media_path(media_library.get_media(uploaded['id']))
    stray_in_media = media_library.root() / 'stray_old.png'
    stray_in_media.write_bytes(b'do-not-delete')
    _age(media_file, 72 * 3600)
    _age(stray_in_media, 72 * 3600)
    _age(media_library.root(), 72 * 3600)

    res = storage.cleanup_orphans(grace_seconds=0)
    assert media_file.exists() and stray_in_media.exists() and media_library.root().is_dir()
    assert res['files'] == 0


# ---------------------------------------------------------------------------
# AC 4: output/layer orphan directory cleanup
# ---------------------------------------------------------------------------

def test_cleanup_orphans_output_layer(tmp_path):
    live_tid = task_db.create_task('layer', 'live', {}, status='succeeded')
    live_dir = Path(storage.task_output_dir('layer', live_tid))
    (live_dir / 'layer_0.png').write_bytes(b'live')
    _age(live_dir, 48 * 3600)

    old_orphan = Path(storage.OUTPUT_DIR) / 'layer' / '99999'
    old_orphan.mkdir(parents=True)
    (old_orphan / 'layer_0.png').write_bytes(b'orphan1')
    (old_orphan / 'layer_1.png').write_bytes(b'orphan2')
    _age(old_orphan, 48 * 3600)

    fresh_orphan = Path(storage.OUTPUT_DIR) / 'layer' / '99998'
    fresh_orphan.mkdir(parents=True)
    (fresh_orphan / 'layer_0.png').write_bytes(b'fresh')

    non_digit = Path(storage.OUTPUT_DIR) / 'layer' / 'manual_backup'
    non_digit.mkdir(parents=True)
    (non_digit / 'keep.png').write_bytes(b'keep')
    _age(non_digit, 48 * 3600)

    outside = tmp_path / 'outside_layer'
    outside.mkdir()
    outside_file = outside / 'secret.txt'
    outside_file.write_text('secret')
    sym_orphan = Path(storage.OUTPUT_DIR) / 'layer' / '99997'
    sym_orphan.mkdir(parents=True)
    (sym_orphan / 'link.txt').symlink_to(outside_file)
    _age(sym_orphan, 48 * 3600)

    res = storage.cleanup_orphans(grace_seconds=24 * 3600)
    assert not old_orphan.exists()
    assert live_dir.exists() and (live_dir / 'layer_0.png').exists()
    assert fresh_orphan.exists()
    assert non_digit.exists()
    assert sym_orphan.exists() and outside_file.read_text() == 'secret'
    assert res['directories'] == 1 and res['files'] == 2


# ---------------------------------------------------------------------------
# AC 5: workspace_assets/layer_projects orphan directory cleanup
# ---------------------------------------------------------------------------

def test_cleanup_orphans_workspace_layer_projects(tmp_path):
    lp_root = Path(storage.WORKSPACE_ASSET_DIR) / 'layer_projects'
    lp_root.mkdir(parents=True, exist_ok=True)

    # Active layer project (old mtime) -> KEEP
    active_pid = task_db.create_layer_project('active-lp')
    active_dir = lp_root / str(active_pid)
    active_dir.mkdir()
    (active_dir / 'source.png').write_bytes(b'active')
    _age(active_dir, 48 * 3600)

    # Soft-deleted layer project (old mtime) -> REMOVE
    deleted_pid = task_db.create_layer_project('deleted-lp')
    task_db.update_layer_project(deleted_pid, deleted_at=task_db.utcnow())
    deleted_dir = lp_root / str(deleted_pid)
    deleted_dir.mkdir()
    (deleted_dir / 'source.png').write_bytes(b'deleted')
    _age(deleted_dir, 48 * 3600)

    # Orphan directory with no DB row (old mtime) -> REMOVE
    orphan_dir = lp_root / '88888'
    orphan_dir.mkdir()
    (orphan_dir / 'source.png').write_bytes(b'orphan')
    _age(orphan_dir, 48 * 3600)

    # Soft-deleted layer project within grace period -> KEEP
    fresh_del_pid = task_db.create_layer_project('fresh-deleted-lp')
    task_db.update_layer_project(fresh_del_pid, deleted_at=task_db.utcnow())
    fresh_del_dir = lp_root / str(fresh_del_pid)
    fresh_del_dir.mkdir()
    (fresh_del_dir / 'source.png').write_bytes(b'fresh')

    # Soft-deleted layer project whose file is in task_assets (known_assets) -> KEEP
    asset_pid = task_db.create_layer_project('known-asset-lp')
    task_db.update_layer_project(asset_pid, deleted_at=task_db.utcnow())
    asset_dir = lp_root / str(asset_pid)
    asset_dir.mkdir()
    tracked_file = asset_dir / 'source.png'
    tracked_file.write_bytes(b'tracked')
    tid = task_db.create_task('layer', 'ref', {}, status='succeeded')
    task_db.register_asset(tid, 'input_image', str(tracked_file), 'image/png')
    _age(asset_dir, 48 * 3600)

    # Non-digit dir -> KEEP
    non_digit = lp_root / 'scratch_dir'
    non_digit.mkdir()
    (non_digit / 'x.png').write_bytes(b'x')
    _age(non_digit, 48 * 3600)

    # Dir containing a symlink -> KEEP & outside file untouched
    outside = tmp_path / 'outside_lp.txt'
    outside.write_text('keep-me')
    sym_dir = lp_root / '77777'
    sym_dir.mkdir()
    (sym_dir / 'escape.txt').symlink_to(outside)
    _age(sym_dir, 48 * 3600)

    res = storage.cleanup_orphans(grace_seconds=24 * 3600)
    assert active_dir.exists()
    assert not deleted_dir.exists()
    assert not orphan_dir.exists()
    assert fresh_del_dir.exists()
    assert asset_dir.exists() and tracked_file.exists()
    assert non_digit.exists()
    assert sym_dir.exists() and outside.read_text() == 'keep-me'
    assert res['directories'] == 2 and res['files'] == 2


# ---------------------------------------------------------------------------
# AC 6: workspace_assets/cupsy_assets orphan file cleanup
# ---------------------------------------------------------------------------

def test_cleanup_orphans_cupsy_assets(tmp_path):
    cupsy_root = Path(storage.WORKSPACE_ASSET_DIR) / 'cupsy_assets'
    cupsy_root.mkdir(parents=True, exist_ok=True)
    profile_subdir = cupsy_root / 'cupsy_prof1'
    profile_subdir.mkdir()

    # 1. Active provider_asset + thumb -> KEEP both
    active_file = cupsy_root / 'active.png'
    active_thumb = cupsy_root / 'active.png.thumb.webp'
    active_file.write_bytes(b'active')
    active_thumb.write_bytes(b'active-thumb')
    task_db.create_provider_asset('cupsy', 'image', 'sha-active', 'a.png', 'image/png', 6, str(active_file))
    _age(active_file, 48 * 3600)
    _age(active_thumb, 48 * 3600)

    # 2. Soft-deleted provider_asset STILL linked in task_provider_assets + thumb -> KEEP both
    linked_file = cupsy_root / 'linked.png'
    linked_thumb = cupsy_root / 'linked.png.thumb.webp'
    linked_file.write_bytes(b'linked')
    linked_thumb.write_bytes(b'linked-thumb')
    linked_pa = task_db.create_provider_asset('cupsy', 'image', 'sha-linked', 'l.png', 'image/png', 6, str(linked_file))
    tid = task_db.create_task('video', 'v', {}, provider='cupsy', status='succeeded')
    task_db.link_task_provider_asset(tid, linked_pa['id'], 'reference', 0)
    task_db.update_provider_asset(linked_pa['id'], status='deleted', deleted_at=task_db.utcnow())
    _age(linked_file, 48 * 3600)
    _age(linked_thumb, 48 * 3600)

    # 3. Soft-deleted provider_asset with NO task_provider_assets link (in profile subdir) + thumb -> REMOVE both
    dead_file = profile_subdir / 'dead.png'
    dead_thumb = profile_subdir / 'dead.png.thumb.webp'
    dead_file.write_bytes(b'dead')
    dead_thumb.write_bytes(b'dead-thumb')
    dead_pa = task_db.create_provider_asset('cupsy:prof1', 'image', 'sha-dead', 'd.png', 'image/png', 4, str(dead_file))
    task_db.update_provider_asset(dead_pa['id'], status='deleted', deleted_at=task_db.utcnow())
    _age(dead_file, 48 * 3600)
    # Leave thumb mtime fresh to prove removing source also removes its stale thumb!

    # 4. Completely unreferenced orphan + thumb -> REMOVE both
    orphan_file = cupsy_root / 'orphan.png'
    orphan_thumb = cupsy_root / 'orphan.png.thumb.webp'
    orphan_file.write_bytes(b'orphan')
    orphan_thumb.write_bytes(b'orphan-thumb')
    _age(orphan_file, 48 * 3600)
    _age(orphan_thumb, 48 * 3600)

    # 5. Unreferenced fresh file within grace period -> KEEP
    fresh_file = cupsy_root / 'fresh.png'
    fresh_file.write_bytes(b'fresh')

    # 6. Symlink escaping outside -> KEEP & outside file untouched
    outside = tmp_path / 'outside_cupsy.png'
    outside.write_bytes(b'secret')
    sym_file = cupsy_root / 'escape.png'
    sym_file.symlink_to(outside)

    # 7. Fresh empty subdir within grace period -> KEEP; emptied profile_subdir -> REMOVED; cupsy_root -> KEPT
    fresh_empty_subdir = cupsy_root / 'cupsy_fresh_empty'
    fresh_empty_subdir.mkdir()

    res = storage.cleanup_orphans(grace_seconds=24 * 3600)
    assert active_file.exists() and active_thumb.exists()
    assert linked_file.exists() and linked_thumb.exists()
    assert not dead_file.exists() and not dead_thumb.exists()
    assert not profile_subdir.exists()
    assert fresh_empty_subdir.is_dir()
    assert cupsy_root.is_dir()
    assert not orphan_file.exists() and not orphan_thumb.exists()
    assert fresh_file.exists()
    assert sym_file.is_symlink() and outside.read_bytes() == b'secret'
    assert res['files'] == 4 and res['directories'] == 1


# ---------------------------------------------------------------------------
# AC 7: cleanup_workspace_assets_all removes orphan key dirs safely
# ---------------------------------------------------------------------------

def test_cleanup_workspace_assets_all_removes_orphan_key_dirs_safely(tmp_path):
    ws_root = Path(storage.WORKSPACE_ASSET_DIR)

    # Key removed from workspace_state with >300s files -> cleaned + empty dir removed.
    task_db.set_workspace_state('img_tabs', {'items': []})
    img_tabs = ws_root / 'img_tabs'
    img_tabs.mkdir(parents=True)
    f1 = img_tabs / 'old.png'
    f1_thumb = img_tabs / 'old.png.thumb.webp'
    f1.write_bytes(b'old')
    f1_thumb.write_bytes(b'thumb')
    _age(f1, 600)
    _age(f1_thumb, 600)
    task_db.delete_workspace_state('img_tabs')

    # Unlisted key with fresh (<300s) file -> kept.
    fresh_tabs = ws_root / 'video_tabs'
    fresh_tabs.mkdir(parents=True)
    fresh_f = fresh_tabs / 'recent.png'
    fresh_f.write_bytes(b'recent')

    # Reserved dirs layer_projects and cupsy_assets with >300s files -> MUST NOT be touched.
    lp_dir = ws_root / 'layer_projects' / '1'
    lp_dir.mkdir(parents=True)
    lp_file = lp_dir / 'source.png'
    lp_file.write_bytes(b'lp')
    _age(lp_file, 600)

    cupsy_dir = ws_root / 'cupsy_assets'
    cupsy_dir.mkdir(parents=True)
    cupsy_file = cupsy_dir / 'c.png'
    cupsy_file.write_bytes(b'cupsy')
    _age(cupsy_file, 600)

    # Symlink dir pointing outside -> MUST NOT be followed or deleted.
    outside_dir = tmp_path / 'outside_ws'
    outside_dir.mkdir()
    outside_f = outside_dir / 'keep.png'
    outside_f.write_bytes(b'keep')
    _age(outside_f, 600)
    sym_dir = ws_root / 'sym_tab'
    sym_dir.symlink_to(outside_dir, target_is_directory=True)

    removed = storage.cleanup_workspace_assets_all()
    assert removed == 2
    assert not img_tabs.exists()
    assert fresh_f.exists()
    assert lp_file.exists() and cupsy_file.exists()
    assert sym_dir.is_symlink() and outside_f.exists()
    assert ws_root.is_dir()


# ---------------------------------------------------------------------------
# AC 8: Legacy empty canvas directory cleanup (delete_scope + cleanup_orphans)
# ---------------------------------------------------------------------------

def test_delete_scope_and_cleanup_orphans_prune_empty_legacy_canvas_dirs(tmp_path):
    # 1. delete_scope(workflow, cleanup=True) removes file + thumb AND empty canvas_assets/<wf_id>
    project, wf, _, path = _make_legacy_workflow_with_asset('empty-prune-wf')
    wf_dir = path.parent
    thumb = Path(str(path) + '.thumb.webp')
    thumb.write_bytes(b'thumb')
    cleanup.delete_scope('workflow', wf['id'], True)
    assert not path.exists() and not thumb.exists()
    assert not wf_dir.exists()

    # 2. delete_scope(project, cleanup=True) removes empty canvas_assets/library/<proj_id> but keeps library root
    p2 = store.create_project('empty-prune-proj')
    lib_asset = store.save_asset(p2['id'], io.BytesIO(_png_bytes(color=(1, 2, 3))), 'lib.png', library=True)
    lib_path = store.asset_path(store.get_asset(p2['id'], lib_asset['id'], library=True))
    lib_proj_dir = lib_path.parent
    cleanup.delete_scope('project', p2['id'], True)
    assert not lib_path.exists()
    assert not lib_proj_dir.exists()
    assert (store.asset_root() / 'library').is_dir()

    # 3. cleanup_orphans prunes old empty legacy dirs under canvas_assets/ and canvas_assets/library/,
    #    while preserving reserved roots (media, library, local_uploads), recent dirs, non-empty dirs, and symlinks.
    croot = store.asset_root()
    for reserved in ('media', 'library', 'local_uploads'):
        rdir = croot / reserved
        rdir.mkdir(parents=True, exist_ok=True)
        _age(rdir, 72 * 3600)

    old_empty_wf = croot / 'legacy_wf_old'
    old_empty_wf.mkdir()
    _age(old_empty_wf, 48 * 3600)

    fresh_empty_wf = croot / 'legacy_wf_fresh'
    fresh_empty_wf.mkdir()

    nonempty_wf = croot / 'legacy_wf_nonempty'
    nonempty_wf.mkdir()
    (nonempty_wf / 'file.png').write_bytes(b'keep')
    _age(nonempty_wf, 48 * 3600)

    old_empty_lib = croot / 'library' / 'legacy_proj_old'
    old_empty_lib.mkdir(parents=True)
    _age(old_empty_lib, 48 * 3600)

    outside_empty = tmp_path / 'outside_empty_dir'
    outside_empty.mkdir()
    _age(outside_empty, 48 * 3600)
    sym_empty = croot / 'legacy_sym'
    sym_empty.symlink_to(outside_empty, target_is_directory=True)

    res = storage.cleanup_orphans(grace_seconds=24 * 3600)
    assert not old_empty_wf.exists()
    assert not old_empty_lib.exists()
    assert fresh_empty_wf.exists()
    assert nonempty_wf.exists() and (nonempty_wf / 'file.png').exists()
    assert (croot / 'media').is_dir()
    assert (croot / 'library').is_dir()
    assert (croot / 'local_uploads').is_dir()
    assert sym_empty.is_symlink() and outside_empty.is_dir()
    assert res['directories'] == 2


# ---------------------------------------------------------------------------
# Soft-deleted layer_projects DB slimming & Worker._cleanup integration
# ---------------------------------------------------------------------------

def test_deleted_layer_project_db_compaction_preserves_live_task_revisions():
    db = task_db.get_db()
    # Case A: soft-deleted layer project with a revision whose task STILL exists in tasks -> MUST preserve!
    pid_live = task_db.create_layer_project('lp-with-live-task')
    tid = task_db.create_task('layer', 'split', {'size': '1K'}, provider='ark', status='succeeded')
    rev_doc = {'layers': [{'id': 'l0', 'width': 1024, 'height': 1024}, {'id': 'l1', 'width': 512, 'height': 512}]}
    task_db.add_layer_revision(pid_live, tid, 'split', '1K', {'layers': 2}, rev_doc)
    task_db.update_layer_project(pid_live, deleted_at=task_db.utcnow())

    assert cleanup.compact_deleted_layer_projects() == 0
    assert cost_estimate._layer_output_sizes(task_db.get_task(tid), db) == [(1024, 1024), (512, 512)]
    assert db.execute('SELECT document FROM layer_projects WHERE id=?', (pid_live,)).fetchone()['document'] is not None

    # Once the task is deleted, compaction clears layer_projects.document and is idempotent.
    task_db.delete_task(tid)
    assert cleanup.compact_deleted_layer_projects() == 1
    assert db.execute('SELECT document FROM layer_projects WHERE id=?', (pid_live,)).fetchone()['document'] is None
    assert cleanup.compact_deleted_layer_projects() == 0

    # Case B: DELETE /api/layer/projects/<id> immediately clears layer_projects.document.
    client = application.app.test_client()
    media, _ = media_library.save_upload(io.BytesIO(_png_bytes((512, 512))), 'lp.png', origin='upload')
    created = client.post('/api/layer/projects', json={'source_media_id': media['id'], 'decompose': False})
    assert created.status_code == 201, created.get_json()
    pid_api = created.get_json()['project_id']
    task_db.save_layer_document(pid_api, {'layers': [{'id': 'base', 'width': 64, 'height': 64, 'blob': 'X' * 2000}]})
    resp = client.delete(f'/api/layer/projects/{pid_api}')
    assert resp.status_code == 200
    row = task_db.get_db().execute('SELECT deleted_at, document FROM layer_projects WHERE id=?', (pid_api,)).fetchone()
    assert row['deleted_at'] is not None and row['document'] is None


def test_worker_cleanup_runs_compact_completed_deletions():
    project = store.create_project('worker-compact')
    wf = store.create_workflow(project['id'], 'worker-wf')
    tid = task_db.create_task('image', 'w', {'canvas_workflow_id': wf['id']}, status='succeeded')
    _set_workflow_doc(wf['id'], _rich_workflow_doc(tid))
    db = task_db.get_db()
    db.execute(
        "INSERT INTO canvas_deletions (scope, id, manifest, completed) VALUES ('workflow', ?, ?, 1)",
        (wf['id'], json.dumps({'title': 'worker-wf', 'cleanup_assets': True, 'candidates': [{'path': '/tmp/x'}]})),
    )
    db.commit()

    worker.Worker()._cleanup()

    db = task_db.get_db()
    manifest = json.loads(
        db.execute("SELECT manifest FROM canvas_deletions WHERE scope='workflow' AND id=?", (wf['id'],)).fetchone()['manifest']
    )
    doc = json.loads(db.execute('SELECT document FROM canvas_workflows WHERE id=?', (wf['id'],)).fetchone()['document'])
    assert manifest['compacted'] is True and 'candidates' not in manifest
    assert doc['compacted'] is True and doc['nodes'][0]['task'] == {'id': tid}


# ---------------------------------------------------------------------------
# QA rework regressions: D1 (dirty manifest counters), D2 (Unicode digits), D3 (cupsy empty subdirs)
# ---------------------------------------------------------------------------

def test_compact_and_retry_tolerate_malformed_manifest_counters():
    project = store.create_project('dirty-manifest-proj')
    wf = store.create_workflow(project['id'], 'dirty-manifest-wf')
    db = task_db.get_db()
    dirty = {
        'title': 'dirty-manifest-wf',
        'cleanup_assets': True,
        'retained_shared': 'not-an-int',
        'retained_ambiguous': True,
        'retained_library': -5,
        'removed_files': 'bad',
        'done': ['/tmp/a', '/tmp/b'],
        'candidates': [{'path': '/tmp/a'}],
    }
    db.execute(
        "INSERT INTO canvas_deletions (scope, id, manifest, completed) VALUES ('workflow', ?, ?, 1)",
        (wf['id'], json.dumps(dirty)),
    )
    db.commit()

    # delete_scope retry on completed dirty manifest must not crash with ValueError.
    retry_res = cleanup.delete_scope('workflow', wf['id'], True)
    assert retry_res == {
        'deleted': True,
        'cleanup_assets': True,
        'removed_files': 2,
        'retained_shared': 0,
        'retained_ambiguous': 0,
        'retained_library': 0,
    }

    # compact_completed_deletions must sanitize malformed counters and finish cleanly.
    stats = cleanup.compact_completed_deletions()
    assert stats['manifests'] == 1 and stats['workflows'] == 1
    compacted = json.loads(
        db.execute("SELECT manifest FROM canvas_deletions WHERE scope='workflow' AND id=?", (wf['id'],)).fetchone()['manifest']
    )
    assert compacted['compacted'] is True
    assert compacted['retained_shared'] == 0
    assert compacted['retained_ambiguous'] == 0
    assert compacted['retained_library'] == 0
    assert compacted['removed_files'] == 2
    assert 'candidates' not in compacted
    assert cleanup.compact_completed_deletions() == {'manifests': 0, 'workflows': 0, 'layer_projects': 0}


def test_cleanup_orphans_skips_non_ascii_digit_dirs_without_crashing():
    # Unicode superscript '²' has '²'.isdigit() == True but int('²') raises ValueError!
    layer_out_root = Path(storage.OUTPUT_DIR) / 'layer'
    layer_out_root.mkdir(parents=True, exist_ok=True)
    unicode_out = layer_out_root / '²'
    unicode_out.mkdir()
    (unicode_out / 'keep.png').write_bytes(b'keep')
    _age(unicode_out, 48 * 3600)

    orphan_out = layer_out_root / '98765'
    orphan_out.mkdir()
    (orphan_out / 'drop.png').write_bytes(b'drop')
    _age(orphan_out, 48 * 3600)

    lp_root = Path(storage.WORKSPACE_ASSET_DIR) / 'layer_projects'
    lp_root.mkdir(parents=True, exist_ok=True)
    unicode_lp = lp_root / '²'
    unicode_lp.mkdir()
    (unicode_lp / 'keep.png').write_bytes(b'keep')
    _age(unicode_lp, 48 * 3600)

    orphan_lp = lp_root / '87654'
    orphan_lp.mkdir()
    (orphan_lp / 'drop.png').write_bytes(b'drop')
    _age(orphan_lp, 48 * 3600)

    res = storage.cleanup_orphans(grace_seconds=24 * 3600)
    assert unicode_out.is_dir() and (unicode_out / 'keep.png').exists()
    assert unicode_lp.is_dir() and (unicode_lp / 'keep.png').exists()
    assert not orphan_out.exists()
    assert not orphan_lp.exists()
    assert res['directories'] == 2 and res['files'] == 2


def test_cleanup_orphans_cupsy_prunes_emptied_and_old_empty_subdirs_keeps_root():
    cupsy_root = Path(storage.WORKSPACE_ASSET_DIR) / 'cupsy_assets'
    cupsy_root.mkdir(parents=True, exist_ok=True)

    # Emptied profile subdir whose orphan file was removed -> subdir pruned too.
    prof2 = cupsy_root / 'cupsy_prof2'
    prof2.mkdir()
    old_file = prof2 / 'orphan.png'
    old_file.write_bytes(b'orphan')
    _age(old_file, 48 * 3600)

    # Already-empty old subdir -> pruned.
    old_empty = cupsy_root / 'cupsy_old_empty'
    old_empty.mkdir()
    _age(old_empty, 48 * 3600)

    # Already-empty fresh subdir (within grace) -> kept.
    fresh_empty = cupsy_root / 'cupsy_fresh_empty'
    fresh_empty.mkdir()

    # Subdir with active file -> kept.
    active_sub = cupsy_root / 'cupsy_active'
    active_sub.mkdir()
    active_file = active_sub / 'a.png'
    active_file.write_bytes(b'active')
    task_db.create_provider_asset('cupsy:active', 'image', 'sha-a2', 'a.png', 'image/png', 6, str(active_file))
    _age(active_file, 48 * 3600)

    _age(cupsy_root, 48 * 3600)

    res = storage.cleanup_orphans(grace_seconds=24 * 3600)
    assert not prof2.exists()
    assert not old_empty.exists()
    assert fresh_empty.is_dir()
    assert active_sub.is_dir() and active_file.exists()
    assert cupsy_root.is_dir()
    assert res['files'] == 1 and res['directories'] == 2
