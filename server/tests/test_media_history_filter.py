"""V24-W3-BUDGET-HISTORY-20261121 AC2: global media library 生成历史 read-only filters & sanitized provenance."""
import json
from pathlib import Path

import app as application
import canvas_store as store
import media_library as media
import storage
import tasks
from test_canvas_library_folders import image_bytes

GEN_ROOT = media.system_folder_id('generated')
GEN_IMAGE = media.system_folder_id('generated_image')


def _client():
    return application.app.test_client()


def _seed_generated_canvas_item(workflow_id, node_id, *, prompt, color, filename, params=None, provider='ark', kind='image'):
    full_params = {
        'canvas_workflow_id': workflow_id,
        'canvas_node_id': node_id,
        'size': '1024x1024',
        **(params or {}),
    }
    tid = tasks.create_task(kind, prompt, full_params, provider=provider, status='succeeded')
    out_dir = Path(storage.OUTPUT_DIR) / str(tid)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_bytes(image_bytes(color))
    tasks.register_asset(tid, 'output_' + kind, str(path), 'image/png')
    media_id = media.register_generated(tid, path, kind, name=filename)
    return tid, media_id


def _save_nodes(workflow_id, nodes):
    doc = {'version': 1, 'nodes': nodes, 'edges': [], 'viewport': {'x': 0, 'y': 0, 'zoom': 1}}
    with store.write_transaction() as db:
        db.execute(
            'UPDATE canvas_workflows SET document=?, revision=revision+1 WHERE id=?',
            (json.dumps(doc), workflow_id),
        )


def test_history_filter_by_project_workflow_finalized_and_trash_guard():
    proj_a = store.create_project('短剧甲')
    wf_a1 = store.create_workflow(proj_a['id'], '第一集')
    wf_a2 = store.create_workflow(proj_a['id'], '第二集')
    proj_b = store.create_project('短剧乙')
    wf_b1 = store.create_workflow(proj_b['id'], '序章')

    t_a1_old, m_a1_old = _seed_generated_canvas_item(
        wf_a1['id'], 'n1', prompt='雨夜霓虹街景旧候选', color='red', filename='a1-old.png',
        params={'seedream55': True},
    )
    t_a1_fin, m_a1_fin = _seed_generated_canvas_item(
        wf_a1['id'], 'n1', prompt='雨夜霓虹街景定稿', color='green', filename='a1-final.png',
        params={'seedream55': True},
    )
    t_a2, m_a2 = _seed_generated_canvas_item(
        wf_a2['id'], 'n2', prompt='清晨山谷镜头', color='blue', filename='a2.png',
    )
    t_b1, m_b1 = _seed_generated_canvas_item(
        wf_b1['id'], 'nb1', prompt='赛博实验室定稿', color='yellow', filename='b1-final.png',
    )
    t_trashed, m_trashed = _seed_generated_canvas_item(
        wf_a1['id'], 'n_trash', prompt='回收站隐藏镜头', color='purple', filename='a1-trashed.png',
    )

    _save_nodes(wf_a1['id'], [
        {
            'id': 'n1', 'type': 'image', 'title': '镜头一·雨夜', 'x': 0, 'y': 0,
            'finalized': True,
            'task': {'id': t_a1_fin, 'status': 'succeeded'},
            'asset': {'id': m_a1_fin, 'name': 'a1-final.png', 'kind': 'image', 'url': f'/api/canvas/media/{m_a1_fin}'},
            'candidates': [
                {'id': m_a1_old, 'name': 'a1-old.png', 'kind': 'image', 'url': f'/api/canvas/media/{m_a1_old}'},
                {'id': m_a1_fin, 'name': 'a1-final.png', 'kind': 'image', 'url': f'/api/canvas/media/{m_a1_fin}'},
            ],
        },
        {
            'id': 'n_trash', 'type': 'image', 'title': '将被回收', 'x': 200, 'y': 0,
            'finalized': True,
            'task': {'id': t_trashed, 'status': 'succeeded'},
            'asset': {'id': m_trashed, 'name': 'a1-trashed.png', 'kind': 'image', 'url': f'/api/canvas/media/{m_trashed}'},
        },
    ])
    _save_nodes(wf_a2['id'], [
        {
            'id': 'n2', 'type': 'image', 'title': '镜头二·山谷', 'x': 0, 'y': 0,
            'finalized': False,
            'task': {'id': t_a2, 'status': 'succeeded'},
            'asset': {'id': m_a2, 'name': 'a2.png', 'kind': 'image', 'url': f'/api/canvas/media/{m_a2}'},
        },
    ])
    _save_nodes(wf_b1['id'], [
        {
            'id': 'nb1', 'type': 'image', 'title': '序章主图', 'x': 0, 'y': 0,
            'finalized': True,
            'task': {'id': t_b1, 'status': 'succeeded'},
            'asset': {'id': m_b1, 'name': 'b1-final.png', 'kind': 'image', 'url': f'/api/canvas/media/{m_b1}'},
        },
    ])

    # Move t_trashed into trash: must stay strictly hidden under ALL filter combinations.
    tasks.move_tasks_to_trash([t_trashed])

    c = _client()
    base = {'folder_id': GEN_ROOT, 'include_subfolders': '1'}

    all_gen = c.get('/api/canvas/media', query_string=base).get_json()
    assert {i['id'] for i in all_gen['items']} == {m_a1_old, m_a1_fin, m_a2, m_b1}
    assert m_trashed not in {i['id'] for i in all_gen['items']}

    # Project filter (items + /ids).
    by_proj_a = c.get('/api/canvas/media', query_string={**base, 'project_id': proj_a['id']}).get_json()
    assert {i['id'] for i in by_proj_a['items']} == {m_a1_old, m_a1_fin, m_a2}
    assert by_proj_a['total'] == 3
    ids_proj_a = c.get('/api/canvas/media/ids', query_string={**base, 'project_id': proj_a['id']}).get_json()
    assert set(ids_proj_a['ids']) == {m_a1_old, m_a1_fin, m_a2}

    # Workflow filter.
    by_wf_a1 = c.get('/api/canvas/media', query_string={**base, 'workflow_id': wf_a1['id']}).get_json()
    assert {i['id'] for i in by_wf_a1['items']} == {m_a1_old, m_a1_fin}

    # Finalized-only filter: selects only finalized nodes' active assets, NOT rejected candidates or trashed items.
    by_final = c.get('/api/canvas/media', query_string={**base, 'finalized_only': '1'}).get_json()
    assert {i['id'] for i in by_final['items']} == {m_a1_fin, m_b1}
    assert m_a1_old not in {i['id'] for i in by_final['items']}
    assert m_trashed not in {i['id'] for i in by_final['items']}
    ids_final = c.get('/api/canvas/media/ids', query_string={**base, 'finalized_only': '1'}).get_json()
    assert set(ids_final['ids']) == {m_a1_fin, m_b1}

    # Combined project + finalized_only.
    by_proj_a_final = c.get(
        '/api/canvas/media',
        query_string={**base, 'project_id': proj_a['id'], 'finalized_only': '1'},
    ).get_json()
    assert [i['id'] for i in by_proj_a_final['items']] == [m_a1_fin]

    # Filter options endpoint returns active projects and workflows.
    opts = c.get('/api/canvas/media/history-filters').get_json()
    assert opts['success'] is True
    assert {p['id'] for p in opts['projects']} >= {proj_a['id'], proj_b['id']}
    assert {w['id'] for w in opts['workflows']} >= {wf_a1['id'], wf_a2['id'], wf_b1['id']}

    # Invalid filter params return 400.
    assert c.get('/api/canvas/media', query_string={'finalized_only': 'invalid'}).status_code == 400
    assert c.get('/api/canvas/media', query_string={'project_id': 'x' * 121}).status_code == 400


def test_source_provenance_sanitizes_secrets_signed_urls_ep_ids_and_truncates():
    proj = store.create_project('安全脱敏项目')
    wf = store.create_workflow(proj['id'], '脱敏画布')
    secret_ep = 'ep-20990101000000-secret88'  # secret-scan: allow
    secret_key = 'sk-proj-supersecretkey123456'  # secret-scan: allow
    signed_url = 'https://tos.example.invalid/bucket/private.png?X-Tos-Signature=deadbeef99&X-Tos-Credential=ak99'
    secret_bearer = 'Bearer ' + 'synthetic_token_99'
    long_prompt = (
        f'电影级镜头 {secret_ep} 使用 {signed_url} 密钥 {secret_key} '
        f'api_key=my_hidden_secret_99 {secret_bearer} '
        + '霓虹雨夜城市街道反光与远景山脉轮廓' * 10
    )

    tid, mid = _seed_generated_canvas_item(
        wf['id'],
        'node-safe',
        prompt=long_prompt,
        color='orange',
        filename='safe.png',
        params={'model': secret_ep, 'seedream55': True},
    )
    _save_nodes(wf['id'], [{
        'id': 'node-safe', 'type': 'image', 'title': f'主镜头 {secret_ep}', 'x': 0, 'y': 0,
        'finalized': True,
        'task': {'id': tid, 'status': 'succeeded'},
        'asset': {'id': mid, 'name': 'safe.png', 'kind': 'image', 'url': f'/api/canvas/media/{mid}'},
    }])

    res = _client().get('/api/canvas/media', query_string={'folder_id': GEN_IMAGE}).get_json()
    item = next(i for i in res['items'] if i['id'] == mid)
    prov = item['source_provenance']
    assert prov['project_title'] == '安全脱敏项目'
    assert prov['workflow_title'] == '脱敏画布'
    assert prov['model_label'] == 'Seedream 5.5'
    assert prov['finalized'] is True
    assert len(prov['prompt_preview']) <= 120
    assert prov['prompt_preview'].endswith('…')

    dumped = json.dumps(prov, ensure_ascii=False)
    for forbidden in (secret_ep, 'secret88', secret_key, 'deadbeef99', 'ak99', 'my_hidden_secret_99', 'synthetic_token_99'):
        assert forbidden not in dumped, f'Leaked secret fragment {forbidden!r} in {dumped}'
