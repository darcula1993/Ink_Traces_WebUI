"""PROJECT-BULK-DELETE-20261120: backend tests for bulk-delete-preview and bulk-delete."""
import io
from pathlib import Path

from PIL import Image
import pytest

import app as application
import canvas_cleanup as cleanup
import canvas_store as store
import media_library as media
import storage
import tasks


def _client():
    return application.app.test_client()


def _png_bytes(color='blue'):
    buf = io.BytesIO()
    Image.new('RGB', (16, 16), color).save(buf, 'PNG')
    return buf.getvalue()


def _make_project(title, workflow_count=1):
    project = store.create_project(title)
    workflows = [store.create_workflow(project['id'], f'{title}-wf-{i}') for i in range(workflow_count)]
    return project, workflows


def test_bulk_delete_preview_statuses_and_readonly():
    c = _client()
    p_ok, w_ok = _make_project('可删项目', workflow_count=2)
    # Archive one workflow to confirm workflow_count counts only live workflows.
    cleanup.delete_scope('workflow', w_ok[1]['id'], False)
    tasks.create_task('image', 'done', {'canvas_workflow_id': w_ok[0]['id']}, status='succeeded')

    p_active, w_active = _make_project('活动任务项目', workflow_count=1)
    tasks.create_task('image', 'running', {'canvas_workflow_id': w_active[0]['id']}, status='pending')

    p_leased, w_leased = _make_project('租约中项目', workflow_count=1)
    leased_tid = tasks.create_task('image', 'leased', {'canvas_workflow_id': w_leased[0]['id']}, status='succeeded')
    tasks.get_db().execute('UPDATE tasks SET lease_owner=? WHERE id=?', ('worker-1', leased_tid))
    tasks.get_db().commit()

    p_group, w_group = _make_project('活动节点组项目', workflow_count=1)
    now = tasks.utcnow()
    tasks.get_db().execute(
        """INSERT INTO canvas_group_runs
           (id, workflow_id, group_id, status, base_revision, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        ('run-1', w_group[0]['id'], 'grp-1', 'awaiting_confirm', 1, now, now),
    )
    tasks.get_db().commit()

    p_gone, _ = _make_project('已删项目', workflow_count=0)
    cleanup.delete_scope('project', p_gone['id'], False)

    # Deduplication preserves first-seen order.
    ids = [p_ok['id'], p_active['id'], p_leased['id'], p_group['id'], p_gone['id'], 'nonexistent-id', p_ok['id']]
    res = c.post('/api/canvas/projects/bulk-delete-preview', json={'ids': ids})
    assert res.status_code == 200 and res.json['success'] is True
    rows = res.json['projects']
    assert [r['id'] for r in rows] == [p_ok['id'], p_active['id'], p_leased['id'], p_group['id'], p_gone['id'], 'nonexistent-id']

    by_id = {r['id']: r for r in rows}
    assert by_id[p_ok['id']] == {
        'id': p_ok['id'],
        'title': '可删项目',
        'workflow_count': 1,
        'has_active_tasks': False,
        'active_task_count': 0,
        'can_delete': True,
        'reason': None,
    }
    assert by_id[p_active['id']]['can_delete'] is False
    assert by_id[p_active['id']]['has_active_tasks'] is True
    assert by_id[p_active['id']]['active_task_count'] == 1
    assert '活动任务' in by_id[p_active['id']]['reason']

    assert by_id[p_leased['id']]['can_delete'] is False
    assert by_id[p_leased['id']]['has_active_tasks'] is True
    assert by_id[p_leased['id']]['active_task_count'] == 1

    assert by_id[p_group['id']]['can_delete'] is False
    assert by_id[p_group['id']]['has_active_tasks'] is True
    assert by_id[p_group['id']]['active_task_count'] == 0
    assert '节点组' in by_id[p_group['id']]['reason']

    for missing in (p_gone['id'], 'nonexistent-id'):
        assert by_id[missing]['can_delete'] is False
        assert by_id[missing]['reason'] == '项目不存在'

    # Read-only: none of the live projects were deleted.
    live_ids = {p['id'] for p in store.list_projects()}
    assert {p_ok['id'], p_active['id'], p_leased['id'], p_group['id']} <= live_ids


def test_bulk_delete_validation_and_csrf():
    c = _client()
    for path in ('/api/canvas/projects/bulk-delete-preview', '/api/canvas/projects/bulk-delete'):
        assert c.post(path, json={'ids': []}).status_code == 400
        assert c.post(path, json={'ids': 'not-a-list'}).status_code == 400
        assert c.post(path, json={'ids': ['']}).status_code == 400
        assert c.post(path, json={'ids': [123]}).status_code == 400
        assert c.post(path, json={'ids': [f'p-{i}' for i in range(201)]}).status_code == 400
        assert c.post(path, json={'ids': ['p-1']}, headers={'Origin': 'https://evil.example'}).status_code == 403

    assert c.post('/api/canvas/projects/bulk-delete', json={'ids': ['p-1'], 'cleanup_assets': 'yes'}).status_code == 400


def test_bulk_delete_skips_active_and_missing_without_blocking_batch():
    c = _client()
    p1, _ = _make_project('项目A')
    p2, _ = _make_project('项目B')
    p3, w3 = _make_project('项目C-有活动任务')
    tasks.create_task('image', 'busy', {'canvas_workflow_id': w3[0]['id']}, status='processing')
    p4, w4 = _make_project('项目D-有运行节点组')
    now = tasks.utcnow()
    tasks.get_db().execute(
        """INSERT INTO canvas_group_runs
           (id, workflow_id, group_id, status, base_revision, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        ('run-2', w4[0]['id'], 'grp-2', 'running', 1, now, now),
    )
    tasks.get_db().commit()

    res = c.post('/api/canvas/projects/bulk-delete', json={
        'ids': [p1['id'], p3['id'], p2['id'], p4['id'], 'missing-proj', p1['id']],
        'cleanup_assets': False,
    })
    assert res.status_code == 200 and res.json['success'] is True
    deleted = res.json['deleted']
    skipped = res.json['skipped']
    assert [d['id'] for d in deleted] == [p1['id'], p2['id']]
    assert [d['title'] for d in deleted] == ['项目A', '项目B']
    assert [s['id'] for s in skipped] == [p3['id'], p4['id'], 'missing-proj']
    by_skip = {s['id']: s for s in skipped}
    assert '活动任务' in by_skip[p3['id']]['error'] and by_skip[p3['id']]['cleanup_pending'] is False
    assert '节点组' in by_skip[p4['id']]['error'] and by_skip[p4['id']]['cleanup_pending'] is False
    assert by_skip['missing-proj']['error'] == '项目不存在'

    live_ids = {p['id'] for p in store.list_projects()}
    assert p1['id'] not in live_ids and p2['id'] not in live_ids
    assert p3['id'] in live_ids and p4['id'] in live_ids

    # Re-deleting an already-deleted project skips it as nonexistent.
    res2 = c.post('/api/canvas/projects/bulk-delete', json={'ids': [p1['id']]})
    assert res2.status_code == 200
    assert res2.json['deleted'] == []
    assert res2.json['skipped'][0]['id'] == p1['id']
    assert res2.json['skipped'][0]['error'] == '项目不存在'


def test_bulk_delete_with_cleanup_preserves_global_library_100_percent():
    c = _client()
    p1, w1 = _make_project('含素材库项目')
    p2, w2 = _make_project('普通旧缓存项目')

    # 1. Global library media: one uploaded directly, one generated from a task in p1.
    uploaded, _ = media.save_upload(io.BytesIO(_png_bytes('red')), 'library-upload.png', origin='upload')
    uploaded_file = media.media_path(media.get_media(uploaded['id']))

    tid = tasks.create_task('image', 'gen', {'canvas_workflow_id': w1[0]['id']}, status='succeeded')
    out_dir = Path(storage.OUTPUT_DIR) / 'image' / str(tid)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / 'gen_0.png'
    out_path.write_bytes(_png_bytes('blue'))
    tasks.register_asset(tid, 'output_image', str(out_path), 'image/png')
    tasks.update_task(tid, output_dir=str(out_dir))
    gen_media_id = media.register_generated(tid, out_path, 'image')
    gen_library_file = media.media_path(media.get_media(gen_media_id))

    # 2. Legacy non-library canvas asset & un-registered task output in p2 (should be cleaned up).
    legacy_asset = store.save_asset(w2[0]['id'], io.BytesIO(_png_bytes('green')), 'legacy.png')
    legacy_path = store.asset_path(store.get_asset(w2[0]['id'], legacy_asset['id']))
    plain_tid = tasks.create_task('image', 'plain', {'canvas_workflow_id': w2[0]['id']}, status='succeeded')
    plain_dir = Path(storage.OUTPUT_DIR) / 'image' / str(plain_tid)
    plain_dir.mkdir(parents=True, exist_ok=True)
    plain_out = plain_dir / 'plain.png'
    plain_out.write_bytes(_png_bytes('yellow'))
    tasks.register_asset(plain_tid, 'output_image', str(plain_out), 'image/png')

    res = c.post('/api/canvas/projects/bulk-delete', json={
        'ids': [p1['id'], p2['id']],
        'cleanup_assets': True,
    })
    assert res.status_code == 200 and res.json['success'] is True
    assert len(res.json['deleted']) == 2 and res.json['skipped'] == []

    by_del = {d['id']: d for d in res.json['deleted']}
    assert by_del[p1['id']]['retained_library'] >= 1
    assert by_del[p2['id']]['removed_files'] >= 2

    # Global library files are 100% preserved and readable via media API.
    assert uploaded_file.is_file()
    assert gen_library_file.is_file()
    assert out_path.is_file()
    assert media.status(uploaded['id'])[0] == 'ok'
    assert media.status(gen_media_id)[0] == 'ok'
    assert c.get(f"/api/canvas/media/{uploaded['id']}").status_code == 200
    assert c.get(f'/api/canvas/media/{gen_media_id}').status_code == 200

    # Non-library legacy files in p2 were cleaned up.
    assert not legacy_path.exists()
    assert not plain_out.exists()


def test_bulk_delete_partial_io_failure_records_pending_and_continues(monkeypatch):
    c = _client()
    p_fail, w_fail = _make_project('清理失败项目')
    a_fail = store.save_asset(w_fail[0]['id'], io.BytesIO(_png_bytes('purple')), 'fail.png')
    fail_path = store.asset_path(store.get_asset(w_fail[0]['id'], a_fail['id']))

    p_ok, w_ok = _make_project('正常清理项目')
    a_ok = store.save_asset(w_ok[0]['id'], io.BytesIO(_png_bytes('orange')), 'ok.png')
    ok_path = store.asset_path(store.get_asset(w_ok[0]['id'], a_ok['id']))

    original_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self == fail_path:
            raise OSError('disk busy')
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', flaky_unlink)
    res = c.post('/api/canvas/projects/bulk-delete', json={
        'ids': [p_fail['id'], p_ok['id']],
        'cleanup_assets': True,
    })
    assert res.status_code == 200 and res.json['success'] is True
    assert [d['id'] for d in res.json['deleted']] == [p_ok['id']]
    assert [s['id'] for s in res.json['skipped']] == [p_fail['id']]
    assert res.json['skipped'][0]['cleanup_pending'] is True
    assert fail_path.exists() and not ok_path.exists()
