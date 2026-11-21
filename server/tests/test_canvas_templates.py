"""Backend tests for persistent canvas node-group structural templates (V24-W2-TEMPLATES-API)."""
import pytest

import app as application
import canvas_templates as tpl
import tasks as task_db


@pytest.fixture
def client():
    return application.app.test_client()


def sample_payload(**overrides):
    base = {
        'groupTitle': '分镜出图到视频',
        'groupColor': 'cyan',
        'nodes': [
            {
                'id': 'n0',
                'dx': 0,
                'dy': 0,
                'type': 'image',
                'title': '首帧画面',
                'params': {'model': 'seedream-5-0-pro', 'ratio': '16:9', 'resolution': '1K', 'watermark': False},
                'providerSelection': {'provider': 'ark', 'profile_id': 'a' * 32},
                'text': '雨夜霓虹街道特写',
                'size': {'scale': 1.25},
            },
            {
                'id': 'n1',
                'dx': 420,
                'dy': 0,
                'type': 'video',
                'title': '动态运镜',
                'params': {
                    'model': 'seedance-2.5',
                    'ratio': 'adaptive',
                    'resolution': '480p',
                    'duration': 5,
                    'video_mode': 'reference',
                    'omni_reference_task_type': 'extend',
                    'generate_audio': True,
                },
                'providerSelection': {'provider': 'cupsy', 'profile_id': 'b' * 32},
                'text': '镜头缓慢推进',
            },
        ],
        'edges': [{'source': 'n0', 'target': 'n1'}],
    }
    base.update(overrides)
    return base


def test_empty_by_default_and_idempotent_init(client):
    tpl.init_templates_db()
    tpl.init_templates_db()
    resp = client.get('/api/canvas/templates')
    assert resp.status_code == 200
    assert resp.json == {'success': True, 'templates': []}


def test_crud_order_and_prompt_flag(client):
    r1 = client.post('/api/canvas/templates', json={
        'name': '  短剧标准流  ',
        'include_prompts': False,
        'payload': sample_payload(),
    })
    assert r1.status_code == 201, r1.json
    t1 = r1.json['template']
    assert t1['name'] == '短剧标准流'
    assert t1['include_prompts'] is False
    assert t1['node_count'] == 2
    assert t1['edge_count'] == 1
    assert all(node.get('text', '') == '' for node in t1['payload']['nodes'])
    assert t1['payload']['groupColor'] == 'cyan'
    assert t1['payload']['nodes'][0]['providerSelection'] == {'provider': 'ark', 'profile_id': 'a' * 32}

    # Index-based edges + include_prompts=True
    r2 = client.post('/api/canvas/templates', json={
        'name': '含提示词模板',
        'include_prompts': True,
        'payload': sample_payload(edges=[{'sourceIndex': 0, 'targetIndex': 1}]),
    })
    assert r2.status_code == 201, r2.json
    t2 = r2.json['template']
    assert t2['include_prompts'] is True
    assert t2['payload']['nodes'][0]['text'] == '雨夜霓虹街道特写'
    assert t2['payload']['edges'] == [{'source': 0, 'target': 1}]

    # Force distinct updated_at so ordering assertion is deterministic
    db = task_db.get_db()
    db.execute('UPDATE canvas_group_templates SET updated_at=? WHERE id=?', ('2026-11-20T01:00:00Z', t1['id']))
    db.execute('UPDATE canvas_group_templates SET updated_at=? WHERE id=?', ('2026-11-20T02:00:00Z', t2['id']))
    db.commit()

    listed = client.get('/api/canvas/templates')
    assert listed.status_code == 200
    assert [item['id'] for item in listed.json['templates']] == [t2['id'], t1['id']]

    # Delete existing -> 200; delete again -> 404; bad id -> 404
    deleted = client.delete(f"/api/canvas/templates/{t1['id']}")
    assert deleted.status_code == 200
    assert deleted.json == {'success': True, 'deleted_id': t1['id']}
    assert client.delete(f"/api/canvas/templates/{t1['id']}").status_code == 404
    assert client.delete('/api/canvas/templates/not-a-valid-hex').status_code == 404

    remaining = client.get('/api/canvas/templates').json['templates']
    assert [item['id'] for item in remaining] == [t2['id']]


def test_name_and_bounds_validation(client):
    for bad_name in ['', '   ', '名' * 81, 'bad\x00name', 123, None]:
        resp = client.post('/api/canvas/templates', json={'name': bad_name, 'payload': sample_payload()})
        assert resp.status_code == 400, bad_name

    # Empty nodes & >40 nodes rejected
    assert client.post('/api/canvas/templates', json={
        'name': '空节点', 'payload': sample_payload(nodes=[], edges=[]),
    }).status_code == 400

    too_many = [
        {'id': f'n{i}', 'dx': i * 10, 'dy': 0, 'type': 'image', 'title': f'图{i}', 'params': {}}
        for i in range(41)
    ]
    assert client.post('/api/canvas/templates', json={
        'name': '超上限', 'payload': sample_payload(nodes=too_many, edges=[]),
    }).status_code == 400

    # Exactly 40 nodes succeeds
    exactly_40 = too_many[:40]
    ok = client.post('/api/canvas/templates', json={
        'name': '四十节点', 'payload': sample_payload(nodes=exactly_40, edges=[]),
    })
    assert ok.status_code == 201, ok.json

    # Non-bool include_prompts & unknown top-level keys rejected
    assert client.post('/api/canvas/templates', json={
        'name': 'x', 'include_prompts': 'yes', 'payload': sample_payload(),
    }).status_code == 400
    assert client.post('/api/canvas/templates', json={
        'name': 'x', 'payload': sample_payload(), 'extra': 1,
    }).status_code == 400


def test_edge_graph_and_node_type_validation(client):
    # Incompatible edge direction (video -> image)
    assert client.post('/api/canvas/templates', json={
        'name': '非法方向',
        'payload': sample_payload(edges=[{'source': 'n1', 'target': 'n0'}]),
    }).status_code == 400

    # Self-loop
    assert client.post('/api/canvas/templates', json={
        'name': '自环',
        'payload': sample_payload(edges=[{'source': 'n0', 'target': 'n0'}]),
    }).status_code == 400

    # Cycle (image -> image -> image)
    cycle_nodes = [
        {'id': 'a', 'dx': 0, 'dy': 0, 'type': 'image', 'title': 'A', 'params': {}},
        {'id': 'b', 'dx': 100, 'dy': 0, 'type': 'image', 'title': 'B', 'params': {}},
    ]
    assert client.post('/api/canvas/templates', json={
        'name': '循环图',
        'payload': {'nodes': cycle_nodes, 'edges': [{'source': 'a', 'target': 'b'}, {'source': 'b', 'target': 'a'}]},
    }).status_code == 400

    # Asset node type is disallowed in structural templates
    assert client.post('/api/canvas/templates', json={
        'name': '含素材节点',
        'payload': {'nodes': [{'dx': 0, 'dy': 0, 'type': 'asset', 'title': '图', 'params': {}}], 'edges': []},
    }).status_code == 400


def test_rejects_secrets_signed_urls_and_runtime_media_fields(client):
    # Forbidden runtime/media fields on node
    for forbidden_field, val in [
        ('task', {'id': 1, 'status': 'succeeded'}),
        ('asset', {'id': 'f' * 32, 'kind': 'image', 'url': '/api/canvas/media/' + 'f' * 32}),
        ('candidates', []),
        ('referenceAssets', []),
        ('api_key', 'test-key-value'),
    ]:
        payload = sample_payload()
        payload['nodes'][0][forbidden_field] = val
        resp = client.post('/api/canvas/templates', json={'name': '非法字段', 'payload': payload})
        assert resp.status_code == 400, forbidden_field

    # Forbidden credential / signed URL / inline base64 values inside text or params
    bad_values = [
        'https://storage.example.invalid/clip.mp4?X-Amz-Signature=deadbeef12345678',  # secret-scan: allow
        'https://cdn.example.invalid/out.mp4?Signature=abcd1234efgh5678',  # secret-scan: allow
        'Authorization: Bearer test-key-token-placeholder-123456',  # secret-scan: allow
        '/api/cupsy/source/abcdef123456',
        '/api/canvas/media/' + '1' * 32,
        'data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==',
        'sk-test-key-placeholder-1234567890abcdef',  # secret-scan: allow
    ]
    for bad_text in bad_values:
        payload = sample_payload()
        payload['nodes'][0]['text'] = bad_text
        # Must be rejected even when include_prompts=False!
        resp = client.post('/api/canvas/templates', json={
            'name': '敏感值测试', 'include_prompts': False, 'payload': payload,
        })
        assert resp.status_code == 400, bad_text

    # Forbidden key inside params
    payload = sample_payload()
    payload['nodes'][0]['params']['api_key'] = 'test-key-123'
    assert client.post('/api/canvas/templates', json={'name': '参数凭据', 'payload': payload}).status_code == 400


def test_auth_and_same_origin_write_guards(client, monkeypatch):
    # Cross-site POST & DELETE refused with 403
    r_cross_post = client.post(
        '/api/canvas/templates',
        json={'name': '跨站测试', 'payload': sample_payload()},
        headers={'Origin': 'https://evil.example.invalid'},
    )
    assert r_cross_post.status_code == 403

    r_cross_site = client.post(
        '/api/canvas/templates',
        json={'name': '跨站Fetch', 'payload': sample_payload()},
        headers={'Sec-Fetch-Site': 'cross-site'},
    )
    assert r_cross_site.status_code == 403

    # Non-JSON POST refused with 415
    r_plain = client.post('/api/canvas/templates', data='not-json', content_type='text/plain')
    assert r_plain.status_code == 415

    # Create one cleanly, then check cross-site DELETE refusal
    created = client.post('/api/canvas/templates', json={'name': '正常模板', 'payload': sample_payload()}).json['template']
    r_cross_del = client.delete(
        f"/api/canvas/templates/{created['id']}",
        headers={'Origin': 'https://evil.example.invalid'},
    )
    assert r_cross_del.status_code == 403

    # Auth guard inherited from application-wide require_login
    monkeypatch.setattr(application, 'AUTH_CONFIG', {'username': 'producer', 'password': 'test-key-password'})
    assert client.get('/api/canvas/templates').status_code == 401
    assert client.post('/api/canvas/templates', json={'name': '未登录', 'payload': sample_payload()}).status_code == 401
    assert client.delete(f"/api/canvas/templates/{created['id']}").status_code == 401
