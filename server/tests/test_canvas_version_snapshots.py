"""VERSION-SNAPSHOT-20261123: per-version prompt/params/providerSelection snapshots on canvas nodes.

Covers:
1. Schema validation of ``node.versionSnapshots`` in ``canvas_store.validate_document`` + alias
   normalization + duplicate workflow runtime stripping.
2. Capture at submission time in ``tasks.create_task`` (image, video, audio) — user edits node
   while generating -> write-back writes the ORIGINAL submission snapshot, not post-edit state.
3. Group Run submission captures snapshot & write-back persists it onto ``node.versionSnapshots``.
4. ``task-sync`` returns ``versionSnapshots``; ``merge_stale_save`` preserves new snapshots.
5. ``POST /api/canvas/workflows/<wid>/version-snapshots`` fallback lookup reconstructs legacy
   image/video/audio tasks cleanly, strips ``ep-`` IDs & signed URLs, handles tombstones and
   ``task_assets`` fallback, and skips uploaded non-task assets.
6. ``public_task`` strips internal ``canvas_node_snapshot`` from public task responses.
7. ``canvas_templates`` rejects ``versionSnapshots``; ``local_delete.strip_document`` prunes
   removed candidate snapshots.
"""
import io
from pathlib import Path

from PIL import Image
import pytest

import app as application
import canvas_group_run as group_run
import canvas_group_submit
import canvas_store as store
import canvas_writeback
import local_delete
import media_library
import profile_runtime
import storage
import task_public
import tasks as task_db
from provider_profiles import save_profile


def _png_bytes(color=(30, 90, 150)):
    buf = io.BytesIO()
    Image.new('RGB', (16, 16), color).save(buf, format='PNG')
    return buf.getvalue()


@pytest.fixture
def env(isolated_backend, monkeypatch):
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(isolated_backend / 'canvas_assets'))
    calls = []

    def guard(*args, **kwargs):
        calls.append(args)
        raise AssertionError('provider must not be called in snapshot tests')

    for name in ('get', 'post', 'put', 'delete', 'request'):
        if hasattr(application.HTTP, name):
            monkeypatch.setattr(application.HTTP, name, guard)
    for adapter in ('ark', 'cupsy'):
        monkeypatch.setitem(
            application.API_PROVIDERS,
            adapter,
            profile_runtime.ProfileConfig(
                {'api_key': 'synthetic', 'endpoint': 'https://mock.invalid', 'model': 'seedream-5-0-pro'},
                adapter,
            ),
        )
    monkeypatch.setattr(
        application,
        'CUPSY_VIDEO_CONFIG',
        profile_runtime.ProfileConfig(
            {'api_key': 'synthetic', 'endpoint': 'https://mock.invalid', 'source_base_url': 'https://mock.invalid'},
            'cupsy',
        ),
    )
    monkeypatch.setattr(
        application,
        'CUPSY_AUDIO_CONFIG',
        profile_runtime.ProfileConfig(
            {'api_key': 'synthetic', 'endpoint': 'https://mock.invalid', 'source_base_url': 'https://mock.invalid'},
            'cupsy',
        ),
    )
    project = store.create_project('snapshots')['id']
    wf = store.create_workflow(project, 'canvas')
    return {'project_id': project, 'workflow': wf, 'calls': calls, 'client': application.app.test_client()}


def _save_nodes(wf_id, *nodes, edges=None, groups=None):
    current = store.workflow(wf_id)
    doc = {**current['document'], 'nodes': list(nodes)}
    if edges is not None:
        doc['edges'] = list(edges)
    if groups is not None:
        doc['groups'] = list(groups)
    return store.update_workflow(wf_id, current['title'], doc, current['revision'])


def _doc_node(wf_id, node_id):
    return next(n for n in store.workflow(wf_id)['document']['nodes'] if n['id'] == node_id)


def _attach_output(tid, kind='image', color=(200, 30, 30), filename='out_0.png'):
    directory = Path(storage.OUTPUT_DIR) / kind / str(tid)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if kind == 'image':
        path.write_bytes(_png_bytes(color))
        task_db.register_asset(tid, 'output_image', str(path), 'image/png')
    elif kind == 'video':
        # Minimal valid mp4-like bytes won't be probed if registered via output_video + register_generated;
        # use real fake bytes + register_media directly where needed, or minimal header.
        path.write_bytes(b'\x00\x00\x00\x18ftypmp42' + bytes(color) * 8)
        task_db.register_asset(tid, 'output_video', str(path), 'video/mp4')
    elif kind == 'audio':
        path.write_bytes(b'ID3\x03\x00\x00\x00\x00\x00\x00' + bytes(color) * 8)
        task_db.register_asset(tid, 'output_audio', str(path), 'audio/mpeg')
    return path


# ---------------------------------------------------------------- 1. Schema validation


def test_validation_accepts_valid_snapshots_for_all_generation_types(env):
    wf_id = env['workflow']['id']
    pid = 'a' * 32
    m1, m2, m3 = '1' * 32, '2' * 32, '3' * 32
    nodes = [
        {
            'id': 'img1', 'type': 'image', 'title': '图', 'x': 0, 'y': 0, 'text': 'curr',
            'params': {'ratio': '1:1', 'resolution': '1K'},
            'providerSelection': {'provider': 'ark', 'profile_id': pid},
            'versionSnapshots': {
                m1: {
                    'text': '雨夜霓虹巷口，@林默 缓步走来',
                    'params': {'model': 'seedream-5-0-pro', 'ratio': '16:9', 'resolution': '2K', 'output_format': 'png', 'watermark': False},
                    'providerSelection': {'provider': 'ark', 'profile_id': pid},
                    'taskId': 1234,
                    'createdAt': '2026-11-23T00:10:00+00:00',
                },
            },
        },
        {
            'id': 'vid1', 'type': 'video', 'title': '视频', 'x': 300, 'y': 0, 'text': '',
            'params': {'model': 'seedance-2.5', 'ratio': '16:9', 'resolution': '720p', 'duration': 5},
            'providerSelection': {'provider': 'cupsy', 'profile_id': None},
            'versionSnapshots': {
                m2: {
                    'text': '镜头推进',
                    'params': {'model': 'seedance-2.5', 'ratio': 'adaptive', 'resolution': '720p', 'duration': -1, 'video_mode': 'reference', 'omni_reference_task_type': 'auto', 'generate_audio': True},
                    'providerSelection': {'provider': 'cupsy', 'profile_id': None},
                    'taskId': None,
                    'createdAt': None,
                },
            },
        },
        {
            'id': 'aud1', 'type': 'audio', 'title': '音频', 'x': 600, 'y': 0, 'text': '',
            'params': {'speaker': '', 'output_format': 'mp3', 'sample_rate': 48000, 'enable_subtitle': True},
            'providerSelection': {'provider': 'cupsy', 'profile_id': None},
            'versionSnapshots': {
                m3: {
                    'text': '脚步声渐近',
                    'params': {'model': 'seed-audio-1.0', 'speaker': 'vivi', 'output_format': 'wav', 'sample_rate': 24000, 'enable_subtitle': False},
                    'providerSelection': None,
                },
            },
        },
    ]
    saved = _save_nodes(wf_id, *nodes)
    assert saved['revision'] == 2
    assert _doc_node(wf_id, 'img1')['versionSnapshots'][m1]['taskId'] == 1234
    assert _doc_node(wf_id, 'vid1')['versionSnapshots'][m2]['params']['duration'] == -1
    assert _doc_node(wf_id, 'aud1')['versionSnapshots'][m3]['params']['speaker'] == 'vivi'


def test_validation_rejects_invalid_version_snapshots(env):
    wf_id = env['workflow']['id']
    asset = store.save_asset(wf_id, io.BytesIO(_png_bytes()), 'ref.png')
    valid_id = 'a' * 32

    # Disallowed node types: asset and text
    with pytest.raises(store.CanvasError):
        _save_nodes(wf_id, {
            'id': 'a1', 'type': 'asset', 'title': 'ref', 'x': 0, 'y': 0,
            'asset': asset, 'candidates': [asset], 'selectedCandidateId': asset['id'],
            'versionSnapshots': {},
        })
    with pytest.raises(store.CanvasError):
        _save_nodes(wf_id, {'id': 't1', 'type': 'text', 'title': 'txt', 'x': 0, 'y': 0, 'text': 'hi', 'versionSnapshots': {}})

    # Bad container types / >100 entries / bad keys / unknown snapshot fields / legacy params / bad types
    bad_snapshots = [
        [],
        'not-a-dict',
        None,
        {f'{i:032x}': {'text': 'x'} for i in range(101)},
        {'': {'text': 'x'}},
        {'bad/key': {'text': 'x'}},
        {'a' * 65: {'text': 'x'}},
        {valid_id: 'not-a-dict'},
        {valid_id: {'text': 'ok', 'unknownField': 1}},
        {valid_id: {'text': 123}},
        {valid_id: {'text': 'x' * 50001}},
        {valid_id: {'params': {'provider': 'ark'}}},
        {valid_id: {'params': {'profile_id': 'a' * 32}}},
        {valid_id: {'params': {'profile_revision': 1}}},
        {valid_id: {'params': {'first_frame': 'x'}}},
        {valid_id: {'params': {'last_frame': 'y'}}},
        {valid_id: {'params': {'speaker': 'vivi'}}},  # audio param on image node
        {valid_id: {'providerSelection': {'provider': 'invalid', 'profile_id': None}}},
        {valid_id: {'providerSelection': {'provider': 'ark', 'profile_id': 'not-hex'}}},
        {valid_id: {'providerSelection': {'provider': 'ark', 'api_key': 'secret'}}},
        {valid_id: {'taskId': 0}},
        {valid_id: {'taskId': -5}},
        {valid_id: {'taskId': True}},
        {valid_id: {'taskId': '12'}},
        {valid_id: {'createdAt': ''}},
        {valid_id: {'createdAt': 'x' * 41}},
        {valid_id: {'createdAt': 12345}},
    ]
    for bad in bad_snapshots:
        with pytest.raises(store.CanvasError):
            _save_nodes(wf_id, {'id': 'n1', 'type': 'image', 'title': 'img', 'x': 0, 'y': 0, 'versionSnapshots': bad})

    # Video snapshot rejects image-only params (e.g. output_format='mp4')
    with pytest.raises(store.CanvasError):
        _save_nodes(wf_id, {
            'id': 'v1', 'type': 'video', 'title': 'vid', 'x': 0, 'y': 0,
            'versionSnapshots': {valid_id: {'params': {'output_format': 'mp4'}}},
        })
    # Audio snapshot rejects image-only params (e.g. watermark=False)
    with pytest.raises(store.CanvasError):
        _save_nodes(wf_id, {
            'id': 'au1', 'type': 'audio', 'title': 'aud', 'x': 0, 'y': 0,
            'versionSnapshots': {valid_id: {'params': {'watermark': False}}},
        })


def _insert_media_row(task_id, kind, mime, filename, payload):
    import hashlib
    import uuid
    media_id = uuid.uuid4().hex
    ext = {'image': '.png', 'video': '.mp4', 'audio': '.wav'}[kind]
    target = media_library.root() / (media_id + ext)
    target.write_bytes(payload)
    folder_id = media_library.system_folder_id('generated_' + kind)
    with store.write_transaction() as db:
        media_library._insert(
            db, media_id, hashlib.sha256(payload).hexdigest(), target, filename,
            mime, len(payload), 'generated', folder_id, task_id, task_db.utcnow(),
        )
    return media_id


def test_normalize_media_refs_rekeys_version_snapshots_and_duplicate_strips(env):
    wf_id = env['workflow']['id']
    media, _ = media_library.save_upload(io.BytesIO(_png_bytes()), 'gen.png', origin='upload')
    old_id = '9' * 32
    media_library.add_alias('workflow', old_id, media['id'])
    task_db.get_db().commit()

    old_ref = {
        'id': old_id, 'name': 'gen.png', 'mime_type': 'image/png', 'kind': 'image',
        'url': f'/api/canvas/workflows/{wf_id}/assets/{old_id}', 'size_bytes': media['size_bytes'],
    }
    snap = {'text': '原始提示词', 'params': {'ratio': '16:9', 'resolution': '2K'}}
    _save_nodes(wf_id, {
        'id': 'n1', 'type': 'image', 'title': '图', 'x': 0, 'y': 0, 'text': '当前提示词',
        'asset': old_ref, 'candidates': [old_ref], 'selectedCandidateId': old_id,
        'versionSnapshots': {old_id: snap},
    })
    saved_node = _doc_node(wf_id, 'n1')
    assert saved_node['selectedCandidateId'] == media['id']
    assert media['id'] in saved_node['versionSnapshots']
    assert old_id not in saved_node['versionSnapshots']
    assert saved_node['versionSnapshots'][media['id']] == snap

    # Duplicating the workflow strips runtime outputs and versionSnapshots
    copied = store.duplicate_workflow(wf_id)
    copied_node = copied['document']['nodes'][0]
    assert copied_node['candidates'] == []
    assert 'versionSnapshots' not in copied_node
    # Source workflow stays intact
    assert media['id'] in _doc_node(wf_id, 'n1')['versionSnapshots']


# ---------------------------------------------------------------- 2. Capture on submit + edit while generating


def test_submit_captures_original_snapshot_immune_to_edits_while_generating(env):
    wf_id = env['workflow']['id']
    client = env['client']
    profile = save_profile({
        'name': 'ark-img', 'kind': 'image', 'adapter': 'ark', 'api_key': 'synthetic',
        'settings': {'endpoint': 'https://mock.invalid', 'model': 'seedream-5-0-pro'},
    })
    original_sel = {'provider': 'ark', 'profile_id': profile['id']}
    original_params = {'ratio': '16:9', 'resolution': '2K', 'output_format': 'png', 'watermark': False}
    original_text = '雨夜霓虹巷口，@林默 缓步走来'
    saved = _save_nodes(wf_id, {
        'id': 'img1', 'type': 'image', 'title': '镜头1', 'x': 0, 'y': 0,
        'text': original_text, 'params': original_params, 'providerSelection': original_sel,
    })

    resp = client.post('/api/generate', json={
        'canvas_workflow_id': wf_id,
        'canvas_node_id': 'img1',
        'canvas_workflow_revision': saved['revision'],
        'provider': 'ark',
        'profile_id': profile['id'],
        'prompt': original_text,
        'aspect_ratio': '16:9',
        'resolution': '2K',
        'output_format': 'png',
        'background': 'default',
        'watermark': False,
    })
    assert resp.status_code == 202, resp.json
    tid1 = resp.json['task_id']

    # Verify task row captured canvas_node_snapshot, while public_task() strips it!
    raw_task = task_db.get_task(tid1)
    assert raw_task['params']['canvas_node_snapshot'] == {
        'text': original_text,
        'params': original_params,
        'providerSelection': original_sel,
    }
    pub = task_public.public_task(raw_task)
    assert 'canvas_node_snapshot' not in pub['params']
    assert 'canvas_node_snapshot' in raw_task['params']  # original dict not mutated
    detail_resp = client.get(f'/api/tasks/{tid1}')
    assert detail_resp.status_code == 200
    assert 'canvas_node_snapshot' not in (detail_resp.json['task'].get('params') or {})

    # User attaches running task AND edits prompt, params, and providerSelection WHILE generating!
    edited_text = '阳光明媚的海滩，完全不同的第二版'
    edited_params = {'ratio': '1:1', 'resolution': '1K', 'output_format': 'jpeg', 'watermark': True}
    edited_sel = {'provider': 'cupsy', 'profile_id': None}
    _save_nodes(wf_id, {
        'id': 'img1', 'type': 'image', 'title': '镜头1', 'x': 0, 'y': 0,
        'text': edited_text, 'params': edited_params, 'providerSelection': edited_sel,
        'task': {'id': tid1, 'status': 'processing', 'error': None},
    })

    # Task 1 completes -> writeback persists ORIGINAL submission snapshot!
    _attach_output(tid1, 'image', color=(220, 40, 40), filename='v1.png')
    task_db.complete_task(tid1, {'mock': True})
    assert canvas_writeback.apply_task_result(tid1)

    n1 = _doc_node(wf_id, 'img1')
    # Live node still has the user's post-edit text/params/providerSelection
    assert n1['text'] == edited_text
    assert n1['params'] == edited_params
    assert n1['providerSelection'] == edited_sel
    # Candidate 1's snapshot has the ORIGINAL submission text/params/providerSelection!
    cand1_id = n1['candidates'][0]['id']
    snap1 = n1['versionSnapshots'][cand1_id]
    assert snap1['text'] == original_text
    assert snap1['params'] == original_params
    assert snap1['providerSelection'] == original_sel
    assert snap1['taskId'] == tid1
    assert snap1['createdAt'] == raw_task['created_at']

    # Second submission captures the edited state; writeback keeps snap1 untouched and adds snap2!
    rev_now = store.workflow(wf_id)['revision']
    resp2 = client.post('/api/generate', json={
        'canvas_workflow_id': wf_id,
        'canvas_node_id': 'img1',
        'canvas_workflow_revision': rev_now,
        'provider': 'cupsy',
        'prompt': edited_text,
        'aspect_ratio': '1:1',
        'resolution': '1K',
        'output_format': 'jpeg',
        'background': 'default',
        'watermark': True,
    })
    assert resp2.status_code == 202, resp2.json
    tid2 = resp2.json['task_id']
    _save_nodes(wf_id, {**n1, 'task': {'id': tid2, 'status': 'pending', 'error': None}})
    _attach_output(tid2, 'image', color=(40, 200, 90), filename='v2.png')
    task_db.complete_task(tid2, {'mock': True})
    assert canvas_writeback.apply_task_result(tid2)

    n1_after = _doc_node(wf_id, 'img1')
    assert len(n1_after['candidates']) == 2
    cand2_id = n1_after['candidates'][1]['id']
    assert n1_after['versionSnapshots'][cand1_id] == snap1
    snap2 = n1_after['versionSnapshots'][cand2_id]
    assert snap2['text'] == edited_text
    assert snap2['params'] == edited_params
    assert snap2['providerSelection'] == edited_sel
    assert snap2['taskId'] == tid2
    assert env['calls'] == []


def test_submit_captures_snapshot_for_video_and_audio_nodes(env):
    wf_id = env['workflow']['id']
    client = env['client']
    vid_params = {
        'model': 'seedance-2.5', 'ratio': '16:9', 'resolution': '720p', 'duration': 8,
        'video_mode': 'reference', 'omni_reference_task_type': 'extend', 'generate_audio': False,
    }
    aud_params = {'speaker': 'vivi', 'output_format': 'wav', 'sample_rate': 24000, 'enable_subtitle': False}
    saved = _save_nodes(
        wf_id,
        {
            'id': 'v1', 'type': 'video', 'title': '视频1', 'x': 0, 'y': 0,
            'text': '无人机俯拍雨夜街景', 'params': vid_params,
            'providerSelection': {'provider': 'cupsy', 'profile_id': None},
        },
        {
            'id': 'a1', 'type': 'audio', 'title': '配音1', 'x': 300, 'y': 0,
            'text': '林默轻声说道：今晚别回头。', 'params': aud_params,
            'providerSelection': {'provider': 'cupsy', 'profile_id': None},
        },
    )

    rv = client.post('/api/video/generate', json={
        'canvas_workflow_id': wf_id, 'canvas_node_id': 'v1', 'canvas_workflow_revision': saved['revision'],
        'provider': 'cupsy', 'prompt': '无人机俯拍雨夜街景',
        'model': 'seedance-2.5', 'ratio': '16:9', 'resolution': '720p', 'duration': 8,
        'video_mode': 'reference', 'omni_reference_task_type': 'extend', 'generate_audio': False,
    })
    assert rv.status_code == 202, rv.json
    vid_tid = rv.json['db_task_id']
    vid_task = task_db.get_task(vid_tid)
    assert vid_task['params']['canvas_node_snapshot'] == {
        'text': '无人机俯拍雨夜街景',
        'params': vid_params,
        'providerSelection': {'provider': 'cupsy', 'profile_id': None},
    }
    assert 'canvas_node_snapshot' not in task_public.public_task(vid_task)['params']

    ra = client.post('/api/audio/generate', json={
        'canvas_workflow_id': wf_id, 'canvas_node_id': 'a1', 'canvas_workflow_revision': saved['revision'],
        'provider': 'cupsy', 'prompt': '林默轻声说道：今晚别回头。',
        'speaker': 'vivi', 'output_format': 'wav', 'sample_rate': 24000, 'enable_subtitle': False,
        'reference_mode': 'audio',
    })
    assert ra.status_code == 202, ra.json
    aud_tid = ra.json['task_id']
    aud_task = task_db.get_task(aud_tid)
    assert aud_task['params']['canvas_node_snapshot'] == {
        'text': '林默轻声说道：今晚别回头。',
        'params': aud_params,
        'providerSelection': {'provider': 'cupsy', 'profile_id': None},
    }
    assert 'canvas_node_snapshot' not in task_public.public_task(aud_task)['params']


# ---------------------------------------------------------------- 3. Group Run submission + writeback


def test_group_run_submission_captures_and_writes_back_version_snapshot(env, monkeypatch):
    wf_id = env['workflow']['id']
    monkeypatch.setattr(group_run, '_submitter', canvas_group_submit.submit)
    monkeypatch.setattr(group_run, '_estimator', canvas_group_submit.estimate)
    params = {'ratio': '16:9', 'resolution': '2K', 'output_format': 'png', 'watermark': False}
    sel = {'provider': 'ark', 'profile_id': None}
    saved = _save_nodes(
        wf_id,
        {
            'id': 'g1', 'type': 'image', 'title': '组内节点', 'x': 0, 'y': 0,
            'text': '组运行原始提示词', 'params': params, 'providerSelection': sel,
        },
        groups=[{'id': 'grp1', 'title': '节点组1', 'nodeIds': ['g1']}],
    )
    prev = group_run.preview(wf_id, 'grp1', saved['revision'])
    run = group_run.create_run(wf_id, 'grp1', saved['revision'], prev['preview_token'])
    tid = run['nodes'][0]['task_id']
    assert tid is not None
    raw_task = task_db.get_task(tid)
    assert raw_task['params']['group_run_id'] == run['id']
    assert raw_task['params']['canvas_node_snapshot'] == {
        'text': '组运行原始提示词',
        'params': params,
        'providerSelection': sel,
    }

    _attach_output(tid, 'image', color=(10, 120, 220), filename='group_out.png')
    task_db.complete_task(tid, {'mock': True})
    canvas_writeback.apply_task_result(tid)

    node = _doc_node(wf_id, 'g1')
    cid = node['candidates'][0]['id']
    snap = node['versionSnapshots'][cid]
    assert snap['text'] == '组运行原始提示词'
    assert snap['params'] == params
    assert snap['providerSelection'] == sel
    assert snap['taskId'] == tid


# ---------------------------------------------------------------- 4. task-sync & merge_stale_save


def test_task_sync_and_merge_stale_save_preserve_version_snapshots(env):
    wf_id = env['workflow']['id']
    client = env['client']
    params = {'ratio': '4:3', 'resolution': '1K', 'output_format': 'png', 'watermark': False}
    sel = {'provider': 'ark', 'profile_id': None}
    saved = _save_nodes(wf_id, {
        'id': 'n1', 'type': 'image', 'title': '图1', 'x': 0, 'y': 0,
        'text': '窗口提交提示词', 'params': params, 'providerSelection': sel,
    })

    # Submit task via API so canvas_node_snapshot is captured
    resp = client.post('/api/generate', json={
        'canvas_workflow_id': wf_id, 'canvas_node_id': 'n1', 'canvas_workflow_revision': saved['revision'],
        'provider': 'ark', 'prompt': '窗口提交提示词', 'aspect_ratio': '4:3', 'resolution': '1K',
        'output_format': 'png', 'background': 'default', 'watermark': False,
    })
    assert resp.status_code == 202, resp.json
    tid = resp.json['task_id']

    base = _save_nodes(wf_id, {
        **_doc_node(wf_id, 'n1'),
        'task': {'id': tid, 'status': 'pending', 'error': None},
    })
    _attach_output(tid, 'image', color=(150, 50, 200), filename='sync.png')
    task_db.complete_task(tid, {'mock': True})

    # task-sync triggers writeback and returns versionSnapshots
    sync_resp = client.post(f'/api/canvas/workflows/{wf_id}/task-sync', json={'task_ids': [tid]})
    assert sync_resp.status_code == 200
    fields = sync_resp.json['nodes']['n1']
    cid = fields['candidates'][0]['id']
    assert cid in fields['versionSnapshots']
    assert fields['versionSnapshots'][cid]['text'] == '窗口提交提示词'
    assert fields['versionSnapshots'][cid]['params'] == params
    assert fields['versionSnapshots'][cid]['taskId'] == tid

    # Stale client based on `base['revision']` edits text concurrently and PUTs -> merges without losing snapshot!
    stale_doc = base['document']
    stale_doc['nodes'][0]['text'] = '离线窗口并发修改的提示词'
    put_resp = client.put(
        f'/api/canvas/workflows/{wf_id}',
        json={'title': base['title'], 'document': stale_doc, 'revision': base['revision']},
    )
    assert put_resp.status_code == 200, put_resp.json
    assert put_resp.json['merged'] is True
    merged_node = put_resp.json['document']['nodes'][0]
    assert merged_node['text'] == '离线窗口并发修改的提示词'
    assert merged_node['candidates'][0]['id'] == cid
    assert merged_node['versionSnapshots'][cid]['text'] == '窗口提交提示词'
    assert merged_node['versionSnapshots'][cid]['params'] == params
    assert merged_node['versionSnapshots'][cid]['providerSelection'] == sel


# ---------------------------------------------------------------- 5. Fallback lookup endpoint


def test_version_snapshots_endpoint_reconstructs_legacy_tasks_and_sanitizes(env):
    wf_id = env['workflow']['id']
    client = env['client']
    url = f'/api/canvas/workflows/{wf_id}/version-snapshots'
    profile_a = 'a' * 32
    profile_b = 'b' * 32

    # Validation errors
    assert client.post('/api/canvas/workflows/nonexistent/version-snapshots', json={'media_ids': ['1' * 32]}).status_code == 404
    for bad in ([], None, 'abc', ['not-hex'], [f'{i:032x}' for i in range(101)]):
        assert client.post(url, json={'media_ids': bad}).status_code == 400

    # 1) Legacy image task with ep- model ID, signed URL in prompt, legacy size/seedream55 fields
    fake_ep = 'ep-20261115123456-abcde'  # secret-scan: allow
    img_tid = task_db.create_task(
        'image',
        f'雨夜街头 参考 https://tos.example.invalid/a.png?X-Tos-Signature=secret123 和 {fake_ep}',
        {
            'aspect_ratio': '16:9', 'resolution': '2K', 'output_format': 'png',
            'watermark': True, 'background': 'auto', 'seedream55': True,
            'size': '2560x1440', 'provider': 'ark', 'model': fake_ep,
            'profile_id': profile_a,
        },
        provider='ark', status='succeeded',
    )
    img_path = _attach_output(img_tid, 'image', color=(10, 20, 30), filename='legacy_img.png')
    img_media_id = media_library.register_generated(img_tid, img_path, 'image', name='legacy_img.png')

    # 2) Legacy image task with custom dimensions (no resolution)
    custom_tid = task_db.create_task(
        'image',
        '自定义尺寸插画',
        {
            'aspect_ratio': 'custom', 'custom_width': 1280, 'custom_height': 960,
            'output_format': 'jpeg', 'watermark': False, 'provider': 'cupsy',
            'model': 'seedream-5.0-pro', 'size': '1280x960',
        },
        provider='cupsy', status='succeeded',
    )
    custom_path = _attach_output(custom_tid, 'image', color=(40, 50, 60), filename='custom_img.png')
    custom_media_id = media_library.register_generated(custom_tid, custom_path, 'image', name='custom_img.png')

    # 3) Legacy video task (contains output_format='mp4', fast=False, return_last_frame=False which must be stripped!)
    vid_tid = task_db.create_task(
        'video',
        '镜头环绕特写',
        {
            'model': 'seedance-2.5', 'ratio': '16:9', 'resolution': '720p', 'duration': -1,
            'video_mode': 'reference', 'omni_reference_task_type': 'extend', 'generate_audio': True,
            'output_format': 'mp4', 'fast': False, 'return_last_frame': False,
            'provider': 'cupsy', 'profile_id': profile_b,
        },
        provider='cupsy', status='succeeded',
    )
    vid_media_id = _insert_media_row(vid_tid, 'video', 'video/mp4', 'legacy_vid.mp4', b'fake-video-bytes-1')

    # 4) Legacy audio task (contains watermark=False, reference_mode='none', speaker=None)
    aud_tid = task_db.create_task(
        'audio',
        '风铃清脆作响',
        {
            'model': 'seed-audio-1.0', 'output_format': 'ogg_opus', 'sample_rate': 48000,
            'enable_subtitle': True, 'watermark': False, 'reference_mode': 'none', 'speaker': None,
        },
        provider='cupsy', status='succeeded',
    )
    aud_media_id = _insert_media_row(aud_tid, 'audio', 'audio/wav', 'legacy_aud.wav', b'fake-audio-bytes-1')

    # 5) Uploaded non-task media (must be skipped cleanly!)
    upload_media, _ = media_library.save_upload(io.BytesIO(_png_bytes((200, 200, 10))), 'user_upload.png', origin='upload')
    upload_media_id = upload_media['id']

    # 6) Tombstone media (deleted from library, still on canvas as placeholder -> still resolves via media_tombstones!)
    del_tid = task_db.create_task(
        'image', '已删历史版本提示词', {'aspect_ratio': '1:1', 'resolution': '1K', 'output_format': 'png'},
        provider='ark', status='succeeded',
    )
    del_path = _attach_output(del_tid, 'image', color=(99, 11, 77), filename='deleted_img.png')
    del_media_id = media_library.register_generated(del_tid, del_path, 'image', name='deleted_img.png')
    media_library.delete_media([del_media_id])

    # 7) Fallback via task_assets when media.source_task_id is NULL
    ta_tid = task_db.create_task(
        'image', '通过task_assets回溯', {'aspect_ratio': '3:4', 'resolution': '2K'},
        provider='ark', status='succeeded',
    )
    ta_path = _attach_output(ta_tid, 'image', color=(11, 99, 77), filename='ta_img.png')
    ta_media_id = media_library.register_generated(ta_tid, ta_path, 'image', name='ta_img.png')
    db = task_db.get_db()
    db.execute('UPDATE media SET source_task_id=NULL WHERE id=?', (ta_media_id,))
    db.execute('UPDATE task_assets SET media_id=? WHERE task_id=?', (ta_media_id, ta_tid))
    db.commit()

    # 8) Layer task output (not image/video/audio -> skipped cleanly)
    layer_tid = task_db.create_task('layer', '分层任务', {'size': '1024x1024'}, provider='ark', status='succeeded')
    layer_path = _attach_output(layer_tid, 'image', color=(5, 5, 5), filename='layer.png')
    layer_media_id = media_library.register_generated(layer_tid, layer_path, 'image', name='layer.png')

    resp = client.post(url, json={
        'media_ids': [
            img_media_id, img_media_id,  # duplicate should be deduplicated
            custom_media_id, vid_media_id, aud_media_id,
            upload_media_id, del_media_id, ta_media_id, layer_media_id,
        ],
    })
    assert resp.status_code == 200, resp.json
    snaps = resp.json['snapshots']

    # Non-task upload and layer task skipped
    assert upload_media_id not in snaps
    assert layer_media_id not in snaps

    # Legacy image: ep- model stripped, signed URL & ep- in prompt masked, legacy keys omitted
    s_img = snaps[img_media_id]
    assert 'X-Tos-Signature' not in s_img['text']
    assert fake_ep not in s_img['text']
    assert 'ep-***' in s_img['text']
    assert s_img['params'] == {
        'ratio': '16:9', 'resolution': '2K', 'output_format': 'png', 'watermark': True, 'background': 'auto',
    }
    assert 'model' not in s_img['params']  # ep-... stripped
    assert 'size' not in s_img['params']
    assert 'provider' not in s_img['params']
    assert 'profile_id' not in s_img['params']
    assert s_img['providerSelection'] == {'provider': 'ark', 'profile_id': profile_a}
    assert s_img['taskId'] == img_tid
    assert s_img['createdAt']

    # Legacy custom image
    s_custom = snaps[custom_media_id]
    assert s_custom['params'] == {
        'model': 'seedream-5.0-pro', 'ratio': 'custom', 'custom_width': 1280, 'custom_height': 960,
        'output_format': 'jpeg', 'watermark': False,
    }
    assert 'resolution' not in s_custom['params']
    assert s_custom['providerSelection'] == {'provider': 'cupsy', 'profile_id': None}

    # Legacy video: output_format/fast/return_last_frame stripped
    s_vid = snaps[vid_media_id]
    assert s_vid['text'] == '镜头环绕特写'
    assert s_vid['params'] == {
        'model': 'seedance-2.5', 'ratio': '16:9', 'resolution': '720p', 'duration': -1,
        'video_mode': 'reference', 'omni_reference_task_type': 'extend', 'generate_audio': True,
    }
    assert s_vid['providerSelection'] == {'provider': 'cupsy', 'profile_id': profile_b}

    # Legacy audio: watermark/reference_mode stripped, speaker=None -> ''
    s_aud = snaps[aud_media_id]
    assert s_aud['text'] == '风铃清脆作响'
    assert s_aud['params'] == {
        'model': 'seed-audio-1.0', 'speaker': '', 'output_format': 'ogg_opus',
        'sample_rate': 48000, 'enable_subtitle': True,
    }
    assert s_aud['providerSelection'] == {'provider': 'cupsy', 'profile_id': None}

    # Tombstone & task_assets fallback resolved cleanly
    assert snaps[del_media_id]['text'] == '已删历史版本提示词'
    assert snaps[del_media_id]['params'] == {'ratio': '1:1', 'resolution': '1K', 'output_format': 'png'}
    assert snaps[ta_media_id]['text'] == '通过task_assets回溯'
    assert snaps[ta_media_id]['params'] == {'ratio': '3:4', 'resolution': '2K'}

    # Every reconstructed snapshot passes canvas_store.validate_document cleanly!
    _save_nodes(
        wf_id,
        {'id': 'n_img', 'type': 'image', 'title': 'i', 'x': 0, 'y': 0,
         'versionSnapshots': {img_media_id: s_img, custom_media_id: s_custom, del_media_id: snaps[del_media_id], ta_media_id: snaps[ta_media_id]}},
        {'id': 'n_vid', 'type': 'video', 'title': 'v', 'x': 100, 'y': 0,
         'versionSnapshots': {vid_media_id: s_vid}},
        {'id': 'n_aud', 'type': 'audio', 'title': 'a', 'x': 200, 'y': 0,
         'versionSnapshots': {aud_media_id: s_aud}},
    )


# ---------------------------------------------------------------- 6. Templates & local_delete


def test_canvas_templates_rejects_version_snapshots(env):
    client = env['client']
    payload = {
        'nodes': [{
            'id': 'n0', 'dx': 0, 'dy': 0, 'type': 'image', 'title': '图',
            'params': {'ratio': '16:9'},
            'versionSnapshots': {'a' * 32: {'text': 'old', 'params': {'ratio': '1:1'}}},
        }],
        'edges': [],
    }
    resp = client.post('/api/canvas/templates', json={'name': '带快照模板', 'payload': payload})
    assert resp.status_code == 400


def test_local_delete_strip_document_prunes_removed_version_snapshots():
    id_keep, id_drop = '1' * 32, '2' * 32
    doc = {
        'nodes': [{
            'id': 'n1', 'type': 'image', 'title': '图', 'x': 0, 'y': 0,
            'asset': {'id': id_drop, 'kind': 'image'},
            'candidates': [{'id': id_keep, 'kind': 'image'}, {'id': id_drop, 'kind': 'image'}],
            'selectedCandidateId': id_drop,
            'versionSnapshots': {
                id_keep: {'text': '保留版本', 'params': {'ratio': '1:1'}},
                id_drop: {'text': '已删版本', 'params': {'ratio': '16:9'}},
            },
        }],
        'edges': [],
    }
    stripped, touched, dropped = local_delete.strip_document(doc, {id_drop})
    assert touched == 1 and dropped == 0
    node = stripped['nodes'][0]
    assert [c['id'] for c in node['candidates']] == [id_keep]
    assert node['selectedCandidateId'] == id_keep
    assert list(node['versionSnapshots']) == [id_keep]
    assert node['versionSnapshots'][id_keep]['text'] == '保留版本'


def test_retry_preserves_existing_snapshot_and_retired_provider_omits_selection(env, monkeypatch):
    wf_id = env['workflow']['id']
    client = env['client']
    orig_snap = {
        'text': '初版提示词',
        'params': {'ratio': '16:9', 'resolution': '2K'},
        'providerSelection': {'provider': 'ark', 'profile_id': None},
    }
    _save_nodes(wf_id, {
        'id': 'n1', 'type': 'image', 'title': '图', 'x': 0, 'y': 0,
        'text': '已经改掉的提示词', 'params': {'ratio': '1:1', 'resolution': '1K'},
        'providerSelection': {'provider': 'cupsy', 'profile_id': None},
    })
    retried_tid = task_db.create_task(
        'image', '初版提示词',
        {'canvas_workflow_id': wf_id, 'canvas_node_id': 'n1', 'canvas_node_snapshot': orig_snap},
        provider='ark', status='pending', retry_of=999,
    )
    assert task_db.get_task(retried_tid)['params']['canvas_node_snapshot'] == orig_snap

    # Retired 'google' provider in legacy task: snapshot still reconstructs prompt/params, omits providerSelection
    legacy_google = task_db.create_task(
        'image', '历史谷歌任务', {'aspect_ratio': '16:9', 'resolution': '1K', 'provider': 'google'},
        provider='google', status='succeeded',
    )
    snap = canvas_writeback.snapshot_from_task(task_db.get_task(legacy_google))
    assert snap['text'] == '历史谷歌任务'
    assert snap['params'] == {'ratio': '16:9', 'resolution': '1K'}
    assert 'providerSelection' not in snap

    # Auth guard on version-snapshots endpoint
    monkeypatch.setattr(application, 'AUTH_CONFIG', {'username': 'producer', 'password': 'test-key-password'})
    assert client.post(f'/api/canvas/workflows/{wf_id}/version-snapshots', json={'media_ids': ['1' * 32]}).status_code == 401


# ---------------------------------------------------------------- 7. D1 Security & defense-in-depth regression


def test_d1_put_rejects_signed_urls_ep_ids_and_secrets_in_version_snapshots(env):
    wf_id = env['workflow']['id']
    client = env['client']
    valid_id = 'c' * 32
    fake_ep = 'ep-20261115123456-abcde'  # secret-scan: allow
    fake_sk = 'sk-1234567890abcdef1234567890'  # secret-scan: allow
    fake_bearer = 'Bearer abcdef1234567890secret'  # secret-scan: allow
    signed_url_1 = 'https://tos.example.invalid/img.png?X-Tos-Signature=deadbeef1234&X-Tos-Credential=AK123'
    signed_url_2 = 'https://tos.example.invalid/img.png?X-Tos-Signature=deadbeef1234'

    # All 4 QA D1 repros + additional sensitive-value vectors must be rejected with HTTP 400
    rejected_snapshots = [
        {'text': signed_url_1, 'params': {'ratio': '16:9'}},
        {'text': '正常提示词', 'params': {'model': fake_ep, 'ratio': '16:9'}},
        {'text': '正常提示词', 'params': {'model': signed_url_2, 'ratio': '16:9'}},
        {'text': f'key {fake_sk}', 'params': {'ratio': '16:9'}},
        {'text': f'参考接入点 {fake_ep}', 'params': {'ratio': '16:9'}},
        {'text': f'Authorization: {fake_bearer}', 'params': {'ratio': '16:9'}},
        {'text': '正常提示词', 'params': {'ratio': signed_url_2}},
        {'text': '正常提示词', 'params': {'model': 'https://cdn.example.invalid/model.bin'}},
    ]
    for snap in rejected_snapshots:
        doc = {
            **store.workflow(wf_id)['document'],
            'nodes': [{
                'id': 'n1', 'type': 'image', 'title': '图', 'x': 0, 'y': 0,
                'text': 'ok', 'params': {'ratio': '16:9'},
                'versionSnapshots': {valid_id: snap},
            }],
        }
        resp = client.put(
            f'/api/canvas/workflows/{wf_id}',
            json={'title': 'canvas', 'document': doc, 'revision': 1},
        )
        assert resp.status_code == 400, (snap, resp.json)
        assert store.workflow(wf_id)['revision'] == 1

    # Normal creative prompts with @mentions, punctuation, step-2/ep-1/desk-lamp and valid model names succeed!
    ok_doc = {
        **store.workflow(wf_id)['document'],
        'nodes': [
            {
                'id': 'n1', 'type': 'image', 'title': '图', 'x': 0, 'y': 0, 'text': 'curr',
                'params': {'ratio': '16:9', 'resolution': '2K'},
                'versionSnapshots': {
                    valid_id: {
                        'text': '雨夜霓虹巷口，@林默 站在 @图片1 旁，film-noir (35mm, f/1.8), desk-lamp, step-2, ep-1！',
                        'params': {'model': 'seedream-5-0-pro', 'ratio': '16:9', 'resolution': '2K'},
                    },
                },
            },
            {
                'id': 'n2', 'type': 'video', 'title': '视频', 'x': 300, 'y': 0, 'text': 'curr',
                'params': {'model': 'seedance-2.5', 'ratio': '16:9', 'resolution': '720p', 'duration': 5},
                'versionSnapshots': {
                    'd' * 32: {
                        'text': '@角色卡 镜头缓慢推进，雨滴反光',
                        'params': {'model': 'seedance-2.5', 'ratio': '16:9', 'resolution': '720p', 'duration': 5},
                    },
                },
            },
        ],
    }
    ok_resp = client.put(
        f'/api/canvas/workflows/{wf_id}',
        json={'title': 'canvas', 'document': ok_doc, 'revision': 1},
    )
    assert ok_resp.status_code == 200, ok_resp.json


def test_d1_public_document_and_workflow_read_mask_raw_version_snapshots(env):
    import json
    wf_id = env['workflow']['id']
    client = env['client']
    valid_id = 'e' * 32
    fake_ep = 'ep-20261115123456-abcde'  # secret-scan: allow
    fake_sk = 'sk-1234567890abcdef1234567890'  # secret-scan: allow
    signed_url = 'https://tos.example.invalid/img.png?X-Tos-Signature=deadbeef1234&X-Tos-Credential=AK123'

    raw_doc = {
        'version': 1,
        'viewport': {'x': 0, 'y': 0, 'zoom': 1},
        'edges': [],
        'nodes': [{
            'id': 'n1', 'type': 'image', 'title': '图', 'x': 0, 'y': 0, 'text': 'ok',
            'versionSnapshots': {
                valid_id: {
                    'text': f'参考 {signed_url} 与 {fake_ep} 和 {fake_sk}',
                    'params': {'model': fake_ep, 'ratio': '16:9', 'resolution': '2K'},
                },
            },
        }],
    }
    # 1) Direct public_document masking (without mutating input)
    pub = task_public.public_document(raw_doc)
    pub_snap = pub['nodes'][0]['versionSnapshots'][valid_id]
    assert 'X-Tos-Signature' not in pub_snap['text']
    assert 'X-Tos-Credential' not in pub_snap['text']
    assert fake_ep not in pub_snap['text']
    assert fake_sk not in pub_snap['text']
    assert 'https://tos.example.invalid/…' in pub_snap['text']
    assert 'ep-***' in pub_snap['text']
    assert 'model' not in pub_snap['params']
    assert pub_snap['params'] == {'ratio': '16:9', 'resolution': '2K'}
    # Input dict untouched
    assert fake_ep in raw_doc['nodes'][0]['versionSnapshots'][valid_id]['text']

    # 2) Simulate legacy/raw DB row -> both store.workflow() and GET /api/canvas/workflows/<wid> mask it
    db = task_db.get_db()
    db.execute('UPDATE canvas_workflows SET document=? WHERE id=?', (json.dumps(raw_doc), wf_id))
    db.commit()

    via_store = store.workflow(wf_id)['document']['nodes'][0]['versionSnapshots'][valid_id]
    assert 'X-Tos-Signature' not in via_store['text']
    assert fake_ep not in via_store['text']
    assert fake_sk not in via_store['text']
    assert 'model' not in via_store['params']

    via_http = client.get(f'/api/canvas/workflows/{wf_id}').json['workflow']['document']['nodes'][0]['versionSnapshots'][valid_id]
    assert 'X-Tos-Signature' not in via_http['text']
    assert fake_ep not in via_http['text']
    assert fake_sk not in via_http['text']
    assert 'model' not in via_http['params']


def test_d1_writeback_scrubs_sensitive_user_prompt_so_validation_never_fails(env):
    wf_id = env['workflow']['id']
    fake_ep = 'ep-20261115123456-abcde'  # secret-scan: allow
    fake_sk = 'sk-1234567890abcdef1234567890'  # secret-scan: allow
    dirty_text = f'雨夜参考 https://tos.example.invalid/a.png?X-Tos-Signature=deadbeef1234 和 {fake_ep} 密钥 {fake_sk}'
    _save_nodes(wf_id, {
        'id': 'n1', 'type': 'image', 'title': '图', 'x': 0, 'y': 0,
        'text': dirty_text, 'params': {'ratio': '16:9', 'resolution': '1K'},
        'providerSelection': {'provider': 'ark', 'profile_id': None},
    })
    tid = task_db.create_task(
        'image', dirty_text,
        {'canvas_workflow_id': wf_id, 'canvas_node_id': 'n1', 'aspect_ratio': '16:9', 'resolution': '1K'},
        provider='ark', status='pending',
    )
    _save_nodes(wf_id, {**_doc_node(wf_id, 'n1'), 'task': {'id': tid, 'status': 'processing', 'error': None}})
    _attach_output(tid, 'image', color=(80, 140, 200), filename='scrubbed.png')
    task_db.complete_task(tid, {'mock': True})

    # Writeback must succeed cleanly (validate_document accepts the scrubbed snapshot!)
    assert canvas_writeback.apply_task_result(tid)
    node = _doc_node(wf_id, 'n1')
    cid = node['candidates'][0]['id']
    snap = node['versionSnapshots'][cid]
    assert 'X-Tos-Signature' not in snap['text']
    assert fake_ep not in snap['text']
    assert fake_sk not in snap['text']
    assert 'https://tos.example.invalid/…' in snap['text']
    assert 'ep-***' in snap['text']


