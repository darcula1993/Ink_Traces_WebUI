"""P2-GLOBAL-TASK-CENTER-20261120: backend tests for cross-type task aggregation,
ids/status/filter-options/navigation, batch delete/restore/purge, and unified trash
empty with v2.2.0 生成历史 lifecycle invariants.
"""
import io
from pathlib import Path

import pytest

import app as application
import canvas_store as store
import characters
import media_library as media
import storage
import tasks
from test_canvas_asset_nodes import media as media_files  # noqa: F401
from test_canvas_library_folders import image_bytes
from test_library_global_s3 import generated, in_library
from test_local_delete import doc_with_reference


def client():
    return application.app.test_client()


def make_generated(task_type='image', color='blue', prompt=None, provider='ark', model=None, workflow_id=None, media_samples=None):
    if task_type == 'image':
        tid, path = generated(color, workflow_id=workflow_id)
        if prompt:
            tasks.get_db().execute('UPDATE tasks SET prompt = ? WHERE id = ?', (prompt, tid))
            tasks.get_db().commit()
        if provider or model:
            t = tasks.get_task(tid)
            params = dict(t.get('params') or {})
            if model:
                params['model'] = model
            tasks.update_task(tid, provider=provider, params=params)
        media_id, lib_file = in_library(tid, path)
        return tid, media_id, lib_file

    params = {'model': model or (f'{task_type}-model')}
    if workflow_id:
        params['canvas_workflow_id'] = workflow_id
    tid = tasks.create_task(task_type, prompt or f'{task_type} prompt', params, provider=provider, status='succeeded')
    out_dir = Path(storage.task_output_dir(task_type, tid))
    out_dir.mkdir(parents=True, exist_ok=True)
    if task_type == 'video':
        out = out_dir / 'video_0.mp4'
        out.write_bytes(media_samples['video'][1])
        tasks.register_asset(tid, 'output_video', str(out), 'video/mp4')
        media_id = media.register_generated(tid, out, 'video', name='video_0.mp4')
        tasks.update_task(tid, output_dir=str(out_dir), result={'local_video': f'/api/tasks/{tid}/file/video_0.mp4'})
        return tid, media_id, media.media_path(media.get_media(media_id))
    if task_type == 'audio':
        out = out_dir / 'audio_0.mp3'
        out.write_bytes(media_samples['audio'][1])
        tasks.register_asset(tid, 'output_audio', str(out), 'audio/mpeg')
        media_id = media.register_generated(tid, out, 'audio', name='audio_0.mp3')
        tasks.update_task(tid, output_dir=str(out_dir), result={'local_audio': f'/api/tasks/{tid}/file/audio_0.mp3'})
        return tid, media_id, media.media_path(media.get_media(media_id))
    # layer
    base = out_dir / 'base.png'
    base.write_bytes(image_bytes(color))
    layer1 = out_dir / 'layer_01.png'
    layer1.write_bytes(image_bytes('green'))
    tasks.register_asset(tid, 'output_image', str(base), 'image/png')
    tasks.register_asset(tid, 'output_image', str(layer1), 'image/png')
    tasks.update_task(
        tid,
        output_dir=str(out_dir),
        result={
            'project_id': 1,
            'base_image': f'/api/tasks/{tid}/file/base.png',
            'local_images': [f'/api/tasks/{tid}/file/base.png'],
            'local_thumbnails': [f'/api/tasks/{tid}/file/base.png'],
            'layers': [{'z_index': 1, 'name': '前景主体', 'local_url': f'/api/tasks/{tid}/file/layer_01.png'}],
        },
    )
    return tid, None, base


def test_list_ids_status_navigation_filter_options_support_type_all_and_single_types(media_files):
    c = client()
    t_img, _, _ = make_generated('image', 'blue', prompt='霓虹雨夜角色', provider='ark', model='seedream-5-0-pro', media_samples=media_files)
    t_vid, _, _ = make_generated('video', 'green', prompt='霓虹雨夜镜头', provider='cupsy', model='seedance-2.5', media_samples=media_files)
    t_aud, _, _ = make_generated('audio', 'red', prompt='霓虹雨夜配乐', provider='cupsy', model='seed-audio-1.0', media_samples=media_files)
    t_lay, _, _ = make_generated('layer', 'white', prompt='霓虹图层拆分', provider='ark', model='seedream-5-5-layer', media_samples=media_files)

    # type=all aggregates all 4 types in stable descending id order with pagination
    p1 = c.get('/api/tasks', query_string={'type': 'all', 'limit': 2, 'offset': 0}).json
    p2 = c.get('/api/tasks', query_string={'type': 'all', 'limit': 2, 'offset': 2}).json
    assert p1['success'] and p1['total'] == 4
    assert [t['id'] for t in p1['tasks']] == [t_lay, t_aud]
    assert [t['id'] for t in p2['tasks']] == [t_vid, t_img]
    # Layer summary exposes layer_count and base_image
    layer_summary = p1['tasks'][0]
    assert layer_summary['type'] == 'layer'
    assert layer_summary['result']['layer_count'] == 1
    assert layer_summary['result']['base_image'].endswith('/base.png')

    # Single type filters still strictly isolate each type
    for kind, expected_id in (('image', t_img), ('video', t_vid), ('audio', t_aud), ('layer', t_lay)):
        res = c.get('/api/tasks', query_string={'type': kind}).json
        assert res['total'] == 1 and [t['id'] for t in res['tasks']] == [expected_id]

    # Search, provider, model, favorite + favorite_group work under type=all
    grp = c.post('/api/favorite-groups', json={'name': '全局精选', 'color': 'green'}).json['group']
    assert c.patch(f'/api/tasks/{t_img}/favorite-groups', json={'group_ids': [grp['id']]}).status_code == 200
    assert c.patch(f'/api/tasks/{t_vid}/favorite-groups', json={'group_ids': [grp['id']]}).status_code == 200
    groups_all = c.get('/api/favorite-groups', query_string={'type': 'all'}).json['groups']
    assert groups_all[0]['task_count'] == 2
    groups_img = c.get('/api/favorite-groups', query_string={'type': 'image'}).json['groups']
    assert groups_img[0]['task_count'] == 1

    searched = c.get('/api/tasks', query_string={'type': 'all', 'q': '霓虹雨夜'}).json
    assert [t['id'] for t in searched['tasks']] == [t_aud, t_vid, t_img]
    by_provider = c.get('/api/tasks', query_string={'type': 'all', 'provider': 'cupsy'}).json
    assert [t['id'] for t in by_provider['tasks']] == [t_aud, t_vid]
    by_model = c.get('/api/tasks', query_string={'type': 'all', 'model': 'seedance-2.5'}).json
    assert [t['id'] for t in by_model['tasks']] == [t_vid]
    by_group = c.get('/api/tasks', query_string={'type': 'all', 'favorite': 'true', 'favorite_group': grp['id']}).json
    assert [t['id'] for t in by_group['tasks']] == [t_vid, t_img]

    # /api/tasks/ids supports type=all and single types, plus filters & view/deleted
    ids_all = c.get('/api/tasks/ids', query_string={'type': 'all'}).json
    assert ids_all['success'] and ids_all['ids'] == [t_lay, t_aud, t_vid, t_img] and ids_all['total'] == 4
    ids_vid = c.get('/api/tasks/ids', query_string={'type': 'video'}).json
    assert ids_vid['ids'] == [t_vid]
    assert c.get('/api/tasks/ids', query_string={'type': 'bogus'}).status_code == 400

    # /api/tasks/status supports type=all and single type scoping
    st_all = c.get('/api/tasks/status', query_string={'type': 'all', 'ids': f'{t_img},{t_vid},{t_lay}'}).json
    assert st_all['success'] and [t['id'] for t in st_all['tasks']] == [t_img, t_vid, t_lay]
    st_img = c.get('/api/tasks/status', query_string={'type': 'image', 'ids': f'{t_img},{t_vid}'}).json
    assert [t['id'] for t in st_img['tasks']] == [t_img] and st_img['missing_ids'] == [t_vid]
    assert c.get('/api/tasks/status', query_string={'type': 'bogus', 'ids': str(t_img)}).status_code == 400

    # /api/tasks/filter-options & /api/tasks/<id>/navigation work with type=all
    opts = c.get('/api/tasks/filter-options', query_string={'type': 'all'}).json
    assert set(opts['providers']) == {'ark', 'cupsy'}
    assert 'seedance-2.5' in opts['models'] and 'seed-audio-1.0' in opts['models']
    nav = c.get(f'/api/tasks/{t_vid}/navigation', query_string={'type': 'all', 'view': 'all'}).json['navigation']
    assert nav['total'] == 4 and nav['position'] == 3 and nav['previous_id'] == t_aud and nav['next_id'] == t_img

    # All query endpoints reject invalid type values consistently with 400
    for bad_type in ('invalid', 'IMAGE'):
        for path in (
            '/api/tasks',
            '/api/tasks/filter-options',
            '/api/tasks/navigation',
            f'/api/tasks/{t_vid}/navigation',
            '/api/favorite-groups',
        ):
            r_bad = c.get(path, query_string={'type': bad_type})
            assert r_bad.status_code == 400 and r_bad.json['success'] is False, (path, bad_type)


def test_unified_trash_single_type_isolation_and_all_types_empty_preserves_copies_and_uploads(media_files):
    c = client()
    project = store.create_project('全局任务测试项目')['id']
    workflow = store.create_workflow(project, '主画布')['id']

    t_img, m_img, f_img = make_generated('image', 'blue', workflow_id=workflow, media_samples=media_files)
    t_vid, m_vid, f_vid = make_generated('video', 'green', media_samples=media_files)
    t_aud, m_aud, f_aud = make_generated('audio', 'red', media_samples=media_files)
    t_lay, _, f_lay = make_generated('layer', 'white', media_samples=media_files)

    # Reference image in canvas, group, and character card (CHAR-FOLDERS-20261122:
    # adding a 生成历史 result to a character hard-link copies it into 角色卡/<name>).
    asset = {k: v for k, v in media.public(media.get_media(m_img)).items() if k in ('id', 'url', 'name', 'kind', 'mime_type', 'size_bytes')}
    doc_with_reference(workflow, asset)
    grp = c.post('/api/canvas/media/groups', json={'title': '角色组', 'media_ids': [m_img]}).json['group']
    ch = characters.create_character({'name': '主角甲', 'kind': 'character', 'description': 'd'})
    _, char_added = characters.add_images(ch['id'], data={'source': 'media', 'media_id': m_img})
    char_copy_id = char_added[0]['media_id']
    assert char_copy_id != m_img

    # Copy m_img out of 生成历史 to a user folder + upload an unrelated user file
    user_folder = c.post('/api/canvas/media/folders', json={'title': '归档'}).json['folder']
    copy_id = c.post('/api/canvas/media/move', json={'ids': [m_img], 'folder_id': user_folder['id']}).json['media'][0]['id']
    upload_id = c.post('/api/canvas/media', data={'file': (io.BytesIO(image_bytes('yellow')), 'mine.png')}).json['media']['id']

    # Move all 4 tasks to trash via /api/tasks/batch/delete with type=all
    r_trash = c.post('/api/tasks/batch/delete', json={'ids': [t_img, t_vid, t_aud, t_lay], 'type': 'all'})
    assert r_trash.status_code == 200 and sorted(r_trash.json['trashed_ids']) == sorted([t_img, t_vid, t_aud, t_lay])

    # All 生成历史 results are hidden while trashed; copies (归档 + 角色卡/主角甲) & upload remain visible
    assert c.get(f'/api/canvas/media/{m_img}').status_code == 409
    assert c.get(f'/api/canvas/media/{m_vid}').status_code == 409
    assert c.get(f'/api/canvas/media/{m_aud}').status_code == 409
    assert c.get(f'/api/canvas/media/{copy_id}').status_code == 200
    assert c.get(f'/api/canvas/media/{char_copy_id}').status_code == 200
    assert c.get(f'/api/canvas/media/{upload_id}').status_code == 200

    # Batch restore single type only restores matching type
    r_res = c.post('/api/tasks/batch/restore', json={'ids': [t_img, t_vid], 'type': 'video'})
    assert r_res.status_code == 200 and r_res.json['restored_ids'] == [t_vid]
    assert tasks.get_task(t_vid)['deleted_at'] is None
    assert tasks.get_task(t_img)['deleted_at'] is not None
    assert c.get(f'/api/canvas/media/{m_vid}').status_code == 200  # restored result visible again
    # Move t_vid back to trash for empty-trash tests
    assert c.post('/api/tasks/batch/delete', json={'ids': [t_vid], 'type': 'video'}).json['trashed'] == 1

    # 1) Single-type empty trash (type='image'): previews affected canvas/group, only deletes image;
    #    both copies (归档 + 角色卡/主角甲) are kept independently!
    prev_img = c.post('/api/tasks/delete-preview', json={'type': 'image'}).json
    assert prev_img['success'] and prev_img['type'] == 'image'
    assert prev_img['task_ids'] == [t_img]
    assert prev_img['types_breakdown'] == {'image': 1}
    assert prev_img['media']['count'] == 1 and prev_img['media']['copies_kept'] == 2
    assert [w['workflow_id'] for w in prev_img['media']['affected_workflows']] == [workflow]
    assert [g['id'] for g in prev_img['media']['media_groups']] == [grp['id']]
    assert prev_img['media']['characters'] == []

    emp_img = c.post('/api/tasks/trash/empty', json={'type': 'image'}).json
    assert emp_img['success'] and emp_img['deleted_ids'] == [t_img] and emp_img['media_deleted'] == 1
    assert tasks.get_task(t_img) is None
    assert not f_img.exists() and c.get(f'/api/canvas/media/{m_img}').status_code == 410
    # Other trashed types MUST remain untouched!
    assert tasks.get_task(t_vid) is not None and tasks.get_task(t_aud) is not None and tasks.get_task(t_lay) is not None
    # Copies (归档 + 角色卡/主角甲) & upload MUST survive!
    assert c.get(f'/api/canvas/media/{copy_id}').status_code == 200
    assert c.get(f'/api/canvas/media/{char_copy_id}').status_code == 200
    assert c.get(f'/api/canvas/media/{upload_id}').status_code == 200

    # 2) All-types empty trash (type='all'): previews remaining video + audio + layer, empties all of them!
    prev_all = c.post('/api/tasks/delete-preview', json={'type': 'all'}).json
    assert prev_all['success'] and prev_all['type'] == 'all'
    assert sorted(prev_all['task_ids']) == sorted([t_vid, t_aud, t_lay])
    assert prev_all['types_breakdown'] == {'video': 1, 'audio': 1, 'layer': 1}
    assert prev_all['media']['count'] == 2  # m_vid + m_aud in 生成历史

    emp_all = c.post('/api/tasks/trash/empty', json={'type': 'all'}).json
    assert emp_all['success'] and emp_all['type'] == 'all'
    assert sorted(emp_all['deleted_ids']) == sorted([t_vid, t_aud, t_lay])
    assert emp_all['media_deleted'] == 2
    assert tasks.get_task(t_vid) is None and tasks.get_task(t_aud) is None and tasks.get_task(t_lay) is None
    assert not f_vid.exists() and not f_aud.exists() and not f_lay.exists()
    assert c.get(f'/api/canvas/media/{m_vid}').status_code == 410
    assert c.get(f'/api/canvas/media/{m_aud}').status_code == 410
    # Copy & upload still intact after emptying all trash!
    assert c.get(f'/api/canvas/media/{copy_id}').status_code == 200
    assert c.get(f'/api/canvas/media/{upload_id}').status_code == 200


def test_active_and_leased_tasks_are_protected_in_batch_purge_and_empty_all(media_files):
    c = client()
    ok_id, ok_media, ok_file = make_generated('image', 'blue', media_samples=media_files)
    live_id, live_media, live_file = make_generated('video', 'green', media_samples=media_files)
    leased_id = tasks.create_task('audio', 'leased', {}, provider='cupsy', status='processing')
    cancelling_id = tasks.create_task('layer', 'cancelling', {}, provider='ark', status='cancel_requested')

    tasks.move_tasks_to_trash([ok_id, leased_id, cancelling_id])
    tasks.update_task(leased_id, lease_owner='worker-9', lease_until='2999-01-01T00:00:00+00:00', status='processing')
    tasks.update_task(cancelling_id, status='cancel_requested')

    # Preview via ids skips live (not_in_trash), leased, and cancel_requested
    prev = c.post('/api/tasks/delete-preview', json={'ids': [ok_id, live_id, leased_id, cancelling_id]}).json
    assert prev['task_ids'] == [ok_id]
    assert prev['skipped'] == {
        str(live_id): 'not_in_trash',
        str(leased_id): 'leased',
        str(cancelling_id): 'cancel_requested',
    }

    # /api/tasks/batch/purge with type='video' cannot purge image ok_id
    r_mismatch = c.post('/api/tasks/batch/purge', json={'ids': [ok_id], 'type': 'video'}).json
    assert r_mismatch['deleted'] == 0 and r_mismatch['missing_ids'] == [ok_id]
    assert tasks.get_task(ok_id) is not None

    # /api/tasks/trash/empty with type='all' purges ok_id and skips leased + cancelling; live untouched
    emp = c.post('/api/tasks/trash/empty', json={'type': 'all'}).json
    assert emp['deleted_ids'] == [ok_id] and emp['media_deleted'] == 1
    assert sorted(emp['skipped_ids']) == sorted([leased_id, cancelling_id])
    assert emp['skipped_reasons'] == {'cancel_requested': 1, 'leased': 1, 'not_in_trash': 0}
    assert tasks.get_task(ok_id) is None and not ok_file.exists()
    assert tasks.get_task(live_id) is not None and live_file.exists()
    assert tasks.get_task(leased_id) is not None and tasks.get_task(cancelling_id) is not None

    # /api/tasks/batch/purge directly on remaining active/not-in-trash ids deletes nothing
    r_purge = c.post('/api/tasks/batch/purge', json={'ids': [live_id, leased_id, cancelling_id], 'type': 'all'}).json
    assert r_purge['deleted'] == 0 and sorted(r_purge['skipped_ids']) == sorted([live_id, leased_id, cancelling_id])
    assert tasks.get_task(live_id) is not None
