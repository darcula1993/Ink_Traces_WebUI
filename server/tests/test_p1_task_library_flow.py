"""P1-TASK-LIBRARY-FLOW-20261120: backend tests for library sorting, metadata, read-only references,
drag/move lifecycle rules, and task canvas_source resolution.
"""
import io
import json
from pathlib import Path

from PIL import Image

import app as application
import canvas_store as store
import characters
import media_library as media
import storage
import tasks
from test_canvas_asset_nodes import media as media_files  # noqa: F401
from test_local_delete import doc_with_reference

SYSTEM = {k: media.system_folder_id(k) for k in ('generated', 'generated_image', 'generated_video', 'generated_audio')}


def client():
    return application.app.test_client()


def make_png(width, height, color):
    buf = io.BytesIO()
    Image.new('RGB', (width, height), color).save(buf, format='PNG')
    return buf.getvalue()


def up(c, raw, name, **form):
    r = c.post('/api/canvas/media', data={'file': (io.BytesIO(raw), name), **form})
    assert r.status_code in (200, 201), r.json
    return r.json['media']


def test_media_sorting_stable_pagination_and_metadata(media_files):
    c = client()
    # Create three distinct images with known sizes and names, plus video/audio.
    small = up(c, make_png(16, 12, (255, 0, 0)), 'beta.png')
    medium = up(c, make_png(120, 80, (0, 255, 0)) + b'0' * 4000, 'alpha.png')
    large = up(c, make_png(240, 160, (0, 0, 255)) + b'1' * 12000, 'Gamma.png')

    assert small['width'] == 16 and small['height'] == 12 and small['duration_seconds'] is None
    assert medium['width'] == 120 and medium['height'] == 80
    assert large['width'] == 240 and large['height'] == 160

    # Video & audio metadata
    vname, vraw = media_files['video']
    vid = up(c, vraw, vname)
    assert vid['kind'] == 'video'
    assert vid['width'] and vid['height']
    assert vid['duration_seconds'] and vid['duration_seconds'] > 0

    aname, araw = media_files['audio']
    aud = up(c, araw, aname)
    assert aud['kind'] == 'audio'
    assert aud['duration_seconds'] and aud['duration_seconds'] > 0

    # Check sorting on images only so sizes/names are deterministic
    get_ids = lambda **q: [i['id'] for i in c.get('/api/canvas/media', query_string={'kind': 'image', **q}).json['items']]

    assert get_ids(sort='name_asc') == [medium['id'], small['id'], large['id']]
    assert get_ids(sort='name_desc') == [large['id'], small['id'], medium['id']]
    assert get_ids(sort='size_desc') == [large['id'], medium['id'], small['id']]
    assert get_ids(sort='size_asc') == [small['id'], medium['id'], large['id']]

    # Newest vs oldest opposite order
    newest = get_ids(sort='newest')
    oldest = get_ids(sort='oldest')
    assert newest == list(reversed(oldest))

    # Pagination stays stable across pages for name_asc and size_desc
    p1 = get_ids(sort='size_desc', limit='2', page='1')
    p2 = get_ids(sort='size_desc', limit='2', page='2')
    assert p1 + p2 == [large['id'], medium['id'], small['id']]

    # Invalid sort rejected with 400
    bad = c.get('/api/canvas/media', query_string={'sort': 'invalid_sort'})
    assert bad.status_code == 400 and bad.json['code'] == 'invalid_request'


def test_media_readonly_references_endpoint():
    c = client()
    m_unused = up(c, make_png(32, 32, (10, 20, 30)), 'unused.png')
    r_empty = c.get(f"/api/canvas/media/{m_unused['id']}/references")
    assert r_empty.status_code == 200 and r_empty.json['success']
    assert r_empty.json['workflows'] == []
    assert r_empty.json['media_groups'] == []
    assert r_empty.json['characters'] == []
    assert r_empty.json['task_ids'] == []
    assert r_empty.json['total_references'] == 0

    # Create media referenced by workflow, media_group, and character card
    m_used = up(c, make_png(64, 64, (40, 50, 60)), 'used.png')
    proj = store.create_project('引用测试项目')
    wf = store.create_workflow(proj['id'], '引用测试画布')
    node_asset = {k: m_used[k] for k in ('id', 'name', 'mime_type', 'kind', 'size_bytes', 'url')}
    doc_with_reference(wf['id'], node_asset)
    grp = media.create_group('主角参考组', [m_used['id']])
    char = characters.create_character({'name': '测试角色', 'kind': 'character', 'description': 'desc'})
    characters.add_images(char['id'], data={'source': 'media', 'media_id': m_used['id']})

    r_used = c.get(f"/api/canvas/media/{m_used['id']}/references")
    assert r_used.status_code == 200 and r_used.json['success']
    data = r_used.json
    assert any(w['workflow_id'] == wf['id'] and w['project_title'] == '引用测试项目' for w in data['workflows'])
    assert any(g['id'] == grp['id'] and g['title'] == '主角参考组' for g in data['media_groups'])
    assert any(ch['id'] == char['id'] and ch['name'] == '测试角色' for ch in data['characters'])
    assert data['total_references'] >= 3

    # Verify read-only: media still exists and is readable!
    assert c.get(f"/api/canvas/media/{m_used['id']}/info").status_code == 200


def test_drag_move_vs_generated_copy_and_forbid_into_generated():
    c = client()
    f_user = c.post('/api/canvas/media/folders', json={'title': '角色定妆'}).json['folder']
    f_user2 = c.post('/api/canvas/media/folders', json={'title': '场景参考'}).json['folder']

    # 1. Uploaded media moves between user folders (same id)
    uploaded = up(c, make_png(48, 48, (90, 10, 10)), 'upload.png', folder_id=f_user['id'])
    mv = c.post('/api/canvas/media/move', json={'ids': [uploaded['id']], 'folder_id': f_user2['id']})
    assert mv.status_code == 200
    assert mv.json['copied'] == []
    assert mv.json['media'][0]['id'] == uploaded['id']
    assert mv.json['media'][0]['folder_id'] == f_user2['id']

    # 2. Upload moved into 生成历史 or its subfolder is forbidden (409 folder_generated_only)
    forbid = c.post('/api/canvas/media/move', json={'ids': [uploaded['id']], 'folder_id': SYSTEM['generated_image']})
    assert forbid.status_code == 409 and forbid.json['code'] == 'folder_generated_only'
    forbid_root = c.post('/api/canvas/media/move', json={'ids': [uploaded['id']], 'folder_id': SYSTEM['generated']})
    assert forbid_root.status_code == 409 and forbid_root.json['code'] == 'folder_generated_only'

    # 3. Generated result in 生成历史 moved to user folder => hard-link copy; original stays in 生成历史
    tid = tasks.create_task('image', 'p', {}, status='succeeded')
    out_dir = Path(storage.OUTPUT_DIR) / str(tid)
    out_dir.mkdir(parents=True)
    out_file = out_dir / 'gen.png'
    out_file.write_bytes(make_png(80, 80, (10, 90, 10)))
    tasks.register_asset(tid, 'output_image', str(out_file), 'image/png')
    gen_id = media.register_generated(tid, str(out_file), 'image', name='gen.png')

    cp = c.post('/api/canvas/media/move', json={'ids': [gen_id], 'folder_id': f_user['id']})
    assert cp.status_code == 200
    assert len(cp.json['copied']) == 1
    assert cp.json['copied'][0]['source_id'] == gen_id
    new_id = cp.json['copied'][0]['id']
    assert new_id != gen_id
    assert cp.json['media'][0]['folder_id'] == f_user['id']
    assert cp.json['media'][0]['width'] == 80 and cp.json['media'][0]['height'] == 80

    # Original stays in 生成历史/图片
    orig = c.get(f'/api/canvas/media/{gen_id}/info').json['media']
    assert orig['folder_id'] == SYSTEM['generated_image']


def test_task_detail_canvas_source_resolution_and_deleted_cases():
    c = client()
    # Standalone tool task -> canvas_source is None
    standalone_id = tasks.create_task('image', 'standalone prompt', {}, status='succeeded')
    r_standalone = c.get(f'/api/tasks/{standalone_id}')
    assert r_standalone.status_code == 200
    assert r_standalone.json['task']['canvas_source'] is None

    # Canvas task -> resolves project, workflow, and node label
    proj = store.create_project('短剧第一季')
    wf = store.create_workflow(proj['id'], '第一集分镜')
    doc = {
        'version': 1,
        'viewport': {'x': 0, 'y': 0, 'zoom': 1},
        'edges': [],
        'nodes': [
            {
                'id': 'node-hero-1',
                'type': 'image',
                'title': '主角特写',
                'x': 100,
                'y': 120,
                'text': 'hero closeup',
                'params': {},
                'asset': None,
                'candidates': [],
                'selectedCandidateId': None,
                'task': None,
            }
        ],
    }
    store.update_workflow(wf['id'], wf['title'], doc, wf['revision'])
    tid = tasks.create_task(
        'image',
        'hero closeup',
        {'canvas_workflow_id': wf['id'], 'canvas_node_id': 'node-hero-1'},
        status='succeeded',
    )

    r_canvas = c.get(f'/api/tasks/{tid}')
    assert r_canvas.status_code == 200
    src = r_canvas.json['task']['canvas_source']
    assert src['project_id'] == proj['id']
    assert src['project_name'] == '短剧第一季'
    assert src['workflow_id'] == wf['id']
    assert src['workflow_name'] == '第一集分镜'
    assert src['node_id'] == 'node-hero-1'
    assert src['node_label'] == '主角特写'
    assert src['project_deleted'] is False
    assert src['workflow_deleted'] is False
    assert src['node_deleted'] is False

    # After removing the node from the workflow -> node_deleted is True, workflow still live
    latest = store.workflow(wf['id'])
    store.update_workflow(wf['id'], latest['title'], {**doc, 'nodes': []}, latest['revision'])
    r_node_gone = c.get(f'/api/tasks/{tid}')
    src_gone = r_node_gone.json['task']['canvas_source']
    assert src_gone['workflow_deleted'] is False
    assert src_gone['node_deleted'] is True
    assert src_gone['node_label'] is None

    # After deleting the workflow -> workflow_deleted is True
    db = tasks.get_db()
    db.execute('DELETE FROM canvas_workflows WHERE id = ?', (wf['id'],))
    db.commit()
    r_wf_gone = c.get(f'/api/tasks/{tid}')
    src_wf_gone = r_wf_gone.json['task']['canvas_source']
    assert src_wf_gone['workflow_deleted'] is True
    assert src_wf_gone['node_deleted'] is True
