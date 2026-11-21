"""V24-W3-EXPORT-PACK-20261121: backend tests for canvas scene asset pack export."""
import copy
import csv
import io
import json
from pathlib import Path
import zipfile

from flask import Flask
from PIL import Image
import pytest

import canvas_export_pack as export_pack
import canvas_store as store
from canvas_api import canvas_api
from media_api import media_api
import media_library as media
import storage
import tasks as task_db


@pytest.fixture
def app_and_client(isolated_backend, monkeypatch):
    monkeypatch.setenv('NANOBANANA_CANVAS_ASSET_DIR', str(isolated_backend / 'canvas_assets'))
    store.init_canvas_db()
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(canvas_api)
    app.register_blueprint(media_api)
    return app, app.test_client()


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


def _png_bytes(color='blue', size=(16, 12)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    return buf.getvalue()


def _create_workflow(client, title='第一场·雨夜追逐'):
    project = client.post('/api/canvas/projects', json={'title': '短剧项目'}).json['project']
    resp = client.post(f"/api/canvas/projects/{project['id']}/workflows", json={'title': title})
    assert resp.status_code == 201
    return resp.json['workflow']


def _save_workflow(client, workflow, document, title=None):
    resp = client.put(
        f"/api/canvas/workflows/{workflow['id']}",
        json={'title': title or workflow['title'], 'document': document, 'revision': workflow['revision']},
    )
    assert resp.status_code == 200, resp.get_json()
    return resp.json['workflow']


def _create_generated_task_media(client, workflow, *, kind='image', provider='ark', params=None,
                                 payload=None, filename='out.png', mime='image/png',
                                 output_kind='output_image'):
    task_id = task_db.create_task(kind, provider, params or {})
    out_dir = Path(storage.OUTPUT_DIR) / kind / str(task_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    raw = payload if payload is not None else _png_bytes()
    out_path.write_bytes(raw)
    task_db.register_asset(task_id, output_kind, str(out_path), mime)
    task_db.update_task(task_id, status='succeeded')
    imp = client.post(f"/api/canvas/workflows/{workflow['id']}/task-results", json={'task_id': task_id})
    assert imp.status_code == 200, imp.get_json()
    [asset] = imp.json['assets']
    return task_id, asset, raw


def _make_node(node_id, node_type, title, *, x=0, y=0, text='', asset=None,
               task_id=None, finalized=None, params=None):
    node = {
        'id': node_id,
        'type': node_type,
        'title': title,
        'x': x,
        'y': y,
        'text': text,
        'params': params or {},
    }
    if asset is not None:
        node['asset'] = asset
        node['candidates'] = [asset]
        node['selectedCandidateId'] = asset['id']
    if task_id is not None:
        node['task'] = {'id': task_id, 'status': 'succeeded'}
    if finalized is not None:
        node['finalized'] = finalized
    return node


def test_scope_filtering_custom_order_and_zip_stored_manifest(client):
    wf = _create_workflow(client, '第一场 霓虹雨夜')
    img_task_id, img_asset, img_bytes = _create_generated_task_media(
        client, wf,
        kind='image',
        provider='ark',
        params={
            'model': 'seedream-5.0-pro',
            'resolution': '1K',
            'ratio': '16:9',
            'prompt': '霓虹街道上的雨衣侦探',
            'cost_estimate': {
                'status': 'estimate',
                'model': 'seedream-5.0-pro',
                'minimum_cost': 0.045,
                'maximum_cost': 0.045,
            },
        },
        payload=_png_bytes('red', (32, 18)),
        filename='shot1.png',
        mime='image/png',
        output_kind='output_image',
    )
    aud_bytes = b'RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
    aud_task_id, aud_asset, _ = _create_generated_task_media(
        client, wf,
        kind='audio',
        provider='cupsy',
        params={'model': 'seed-audio-1.0', 'output_format': 'wav', 'sample_rate': 24000, 'prompt': '低沉雨声与心跳'},
        payload=aud_bytes,
        filename='rain.wav',
        mime='audio/wav',
        output_kind='output_audio',
    )
    img2_task_id, img2_asset, img2_bytes = _create_generated_task_media(
        client, wf,
        kind='image',
        provider='cupsy',
        params={
            'model': 'seedream-5.5',
            'resolution': '2K',
            'ratio': '1:1',
            'prompt': '特写镜头',
            'cost_estimate': {
                'status': 'estimate',
                'model': 'seedream-5.5',
                'minimum_cost': 0.035,
                'maximum_cost': 0.035,
            },
        },
        payload=_png_bytes('green', (24, 24)),
        filename='shot2.png',
        mime='image/png',
        output_kind='output_image',
    )

    doc = copy.deepcopy(wf['document'])
    doc['nodes'] = [
        _make_node('n-text', 'text', '场记笔记', text='纯文字'),
        _make_node('n-img-final', 'image', '镜头A', text='雨夜侦探远景', asset=img_asset, task_id=img_task_id, finalized=True),
        _make_node('n-aud-final', 'audio', '镜头B_环境音', text='雨滴与远雷', asset=aud_asset, task_id=aud_task_id, finalized=True),
        _make_node('n-img-draft', 'image', '镜头C_草稿', text='未定稿镜头', asset=img2_asset, task_id=img2_task_id, finalized=False),
        _make_node('n-empty', 'image', '镜头D_无结果', text='尚未生成'),
    ]
    wf = _save_workflow(client, wf, doc)

    # 1. scope=finalized
    prev_final = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack/preview", json={'scope': 'finalized'})
    assert prev_final.status_code == 200
    body_final = prev_final.get_json()
    assert [item['node_id'] for item in body_final['items']] == ['n-img-final', 'n-aud-final']
    assert body_final['items'][0]['finalized'] is True
    assert body_final['items'][0]['model'] == 'Seedream 5.0 Pro'
    assert body_final['items'][0]['estimated_cost_usd'] == '0.045'
    assert body_final['items'][0]['estimate_display'] == '$0.045'
    assert body_final['items'][1]['model'] == 'Seed Audio 1.0'
    assert body_final['items'][1]['estimated_cost_usd'] == 'unknown'
    assert body_final['items'][1]['estimate_display'] == '未知'
    assert body_final['total_bytes'] == len(img_bytes) + len(aud_bytes)

    # 2. scope=selected (includes a text node and nonexistent node -> skipped)
    prev_sel = client.post(
        f"/api/canvas/workflows/{wf['id']}/export-pack/preview",
        json={'scope': 'selected', 'node_ids': ['n-img-draft', 'n-text', 'n-missing']},
    )
    assert prev_sel.status_code == 200
    body_sel = prev_sel.get_json()
    assert [item['node_id'] for item in body_sel['items']] == ['n-img-draft']
    skipped_reasons = {entry['node_id']: entry['reason'] for entry in body_sel['skipped']}
    assert skipped_reasons == {'n-text': 'no_media', 'n-missing': 'node_not_found'}

    # 3. scope=all (empty generation node appears in skipped)
    prev_all = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack/preview", json={'scope': 'all'})
    assert prev_all.status_code == 200
    body_all = prev_all.get_json()
    assert [item['node_id'] for item in body_all['items']] == ['n-img-final', 'n-aud-final', 'n-img-draft']
    assert any(entry['node_id'] == 'n-empty' and entry['reason'] == 'no_result' for entry in body_all['skipped'])

    # 4. Export ZIP_STORED with custom ordered_node_ids
    exp = client.post(
        f"/api/canvas/workflows/{wf['id']}/export-pack",
        json={'scope': 'finalized', 'ordered_node_ids': ['n-aud-final', 'n-img-final']},
    )
    assert exp.status_code == 200
    assert exp.mimetype == 'application/zip'
    assert exp.headers.get('X-Content-Type-Options') == 'nosniff'
    assert exp.headers.get('Cache-Control') == 'private, no-store'
    assert exp.headers.get('X-Export-Pack-Count') == '2'
    disp = exp.headers.get('Content-Disposition', '')
    assert 'ink-traces-' in disp and '-pack.zip' in disp

    with zipfile.ZipFile(io.BytesIO(exp.data), 'r') as zf:
        infos = zf.infolist()
        names = [info.filename for info in infos]
        assert 'shotlist.csv' in names
        assert 'shotlist.json' in names
        for info in infos:
            assert info.compress_type == zipfile.ZIP_STORED

        media_names = [n for n in names if n.startswith('media/')]
        assert len(media_names) == 2
        assert media_names[0].startswith('media/01_') and media_names[0].endswith(f'_t{aud_task_id}.wav')
        assert media_names[1].startswith('media/02_') and media_names[1].endswith(f'_t{img_task_id}.png')
        assert zf.read(media_names[0]) == aud_bytes
        assert zf.read(media_names[1]) == img_bytes

        # Check shotlist.csv (UTF-8 BOM + columns + values)
        raw_csv = zf.read('shotlist.csv')
        assert raw_csv.startswith(b'\xef\xbb\xbf')
        rows = list(csv.DictReader(io.StringIO(raw_csv.decode('utf-8-sig'))))
        assert len(rows) == 2
        assert rows[0]['shot_no'] == '1'
        assert rows[0]['node_id'] == 'n-aud-final'
        assert rows[0]['filename'] == media_names[0]
        assert rows[0]['media_type'] == 'audio'
        assert rows[0]['finalized'] == 'true'
        assert rows[0]['model'] == 'Seed Audio 1.0'
        assert rows[0]['estimated_cost_usd'] == 'unknown'
        assert rows[1]['shot_no'] == '2'
        assert rows[1]['node_id'] == 'n-img-final'
        assert rows[1]['estimated_cost_usd'] == '0.045'
        assert rows[1]['model'] == 'Seedream 5.0 Pro'

        # Check shotlist.json
        manifest = json.loads(zf.read('shotlist.json').decode('utf-8'))
        assert manifest['schema_version'] == 1
        assert manifest['scope'] == 'finalized'
        assert manifest['summary']['total_items'] == 2
        assert manifest['summary']['unknown_cost_count'] == 1
        assert [i['node_id'] for i in manifest['items']] == ['n-aud-final', 'n-img-final']
        assert manifest['items'][0]['estimated_cost_usd'] == 'unknown'
        assert manifest['items'][1]['estimated_cost_usd'] == '0.045'


def test_deleted_and_trashed_media_are_skipped(client):
    wf = _create_workflow(client, '删除与回收站测试')
    t_live, a_live, _ = _create_generated_task_media(client, wf, payload=_png_bytes('blue'), filename='live.png')
    t_del, a_del, _ = _create_generated_task_media(client, wf, payload=_png_bytes('red'), filename='del.png')
    t_trash, a_trash, _ = _create_generated_task_media(client, wf, payload=_png_bytes('green'), filename='trash.png')

    doc = copy.deepcopy(wf['document'])
    doc['nodes'] = [
        _make_node('n-live', 'image', '可用镜头', asset=a_live, task_id=t_live, finalized=True),
        _make_node('n-del', 'image', '已删镜头', asset=a_del, task_id=t_del, finalized=True),
        _make_node('n-trash', 'image', '回收站镜头', asset=a_trash, task_id=t_trash, finalized=True),
    ]
    wf = _save_workflow(client, wf, doc)

    # Delete a_del from media library; move t_trash to trash (deleted_at != NULL)
    media.delete_media([a_del['id']])
    db = task_db.get_db()
    db.execute('UPDATE tasks SET deleted_at = ? WHERE id = ?', (task_db.utcnow(), t_trash))
    db.commit()

    prev = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack/preview", json={'scope': 'all'})
    assert prev.status_code == 200
    data = prev.get_json()
    assert [item['node_id'] for item in data['items']] == ['n-live']
    skipped = {entry['node_id']: entry['reason'] for entry in data['skipped']}
    assert skipped['n-del'] == 'deleted'
    assert skipped['n-trash'] == 'trashed'

    exp = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack", json={'scope': 'all'})
    assert exp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exp.data), 'r') as zf:
        media_names = [n for n in zf.namelist() if n.startswith('media/')]
        assert len(media_names) == 1
        manifest = json.loads(zf.read('shotlist.json').decode('utf-8'))
        manifest_skipped = {entry['node_id']: entry['reason'] for entry in manifest['skipped']}
        assert manifest_skipped['n-del'] == 'deleted'
        assert manifest_skipped['n-trash'] == 'trashed'


def test_filename_sanitization_traversal_bidi_and_windows_reserved(client):
    wf = _create_workflow(client, '../CON\u202e\x07画布')
    t1, a1, _ = _create_generated_task_media(client, wf, payload=_png_bytes('blue'), filename='a.png')
    t2, a2, _ = _create_generated_task_media(client, wf, payload=_png_bytes('red'), filename='b.png')
    t3, a3, _ = _create_generated_task_media(client, wf, payload=_png_bytes('green'), filename='c.png')

    doc = copy.deepcopy(wf['document'])
    doc['nodes'] = [
        _make_node('n-trav', 'image', '../../etc/passwd', asset=a1, task_id=t1, finalized=True),
        _make_node('n-win', 'image', 'CON', asset=a2, task_id=t2, finalized=True),
        _make_node('n-bidi', 'image', 'shot\u202egnp.exe\x00:*?"<>|', asset=a3, task_id=t3, finalized=True),
    ]
    wf = _save_workflow(client, wf, doc)

    exp = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack", json={'scope': 'all'})
    assert exp.status_code == 200
    disp = exp.headers.get('Content-Disposition', '')
    assert '..' not in disp and '\u202e' not in disp and '\x07' not in disp

    with zipfile.ZipFile(io.BytesIO(exp.data), 'r') as zf:
        media_names = sorted(n for n in zf.namelist() if n.startswith('media/'))
        assert len(media_names) == 3
        for name in media_names:
            assert name.startswith('media/')
            leaf = name[len('media/'):]
            assert '/' not in leaf and '\\' not in leaf and '..' not in leaf
            assert '\u202e' not in leaf and '\x00' not in leaf
            assert not any(ch in leaf for ch in ':*?"<>|')
            assert leaf.endswith('.png')
        # Windows reserved CON must be prefixed, not bare CON
        assert '_shot_CON_' in media_names[1]


def test_path_traversal_and_outside_symlink_refused(client, isolated_backend):
    wf = _create_workflow(client, '越界路径防护')
    t_ok, a_ok, _ = _create_generated_task_media(client, wf, payload=_png_bytes('blue'), filename='ok.png')
    t_esc, a_esc, _ = _create_generated_task_media(client, wf, payload=_png_bytes('red'), filename='esc.png')
    t_sym, a_sym, _ = _create_generated_task_media(client, wf, payload=_png_bytes('green'), filename='sym.png')

    outside_secret = isolated_backend / 'outside_secret.txt'
    outside_secret.write_text('TOP_SECRET_OUTSIDE_FILE_DO_NOT_READ', encoding='utf-8')

    doc = copy.deepcopy(wf['document'])
    doc['nodes'] = [
        _make_node('n-ok', 'image', '正常素材', asset=a_ok, task_id=t_ok, finalized=True),
        _make_node('n-esc', 'image', '越界相对路径', asset=a_esc, task_id=t_esc, finalized=True),
        _make_node('n-sym', 'image', '符号链接越界', asset=a_sym, task_id=t_sym, finalized=True),
    ]
    wf = _save_workflow(client, wf, doc)

    # Tamper DB directly to simulate compromised media.relpath & symlink escape & malformed node URL
    db = task_db.get_db()
    db.execute('UPDATE media SET relpath = ? WHERE id = ?', ('../../outside_secret.txt', a_esc['id']))

    sym_row = db.execute('SELECT relpath FROM media WHERE id = ?', (a_sym['id'],)).fetchone()
    sym_file = media.root() / sym_row['relpath']
    sym_file.unlink()
    sym_file.symlink_to(outside_secret)

    # Also inject a raw forged asset URL into stored document JSON
    raw_doc = json.loads(db.execute('SELECT document FROM canvas_workflows WHERE id = ?', (wf['id'],)).fetchone()['document'])
    raw_doc['nodes'].append({
        'id': 'n-forged',
        'type': 'image',
        'title': '伪造路径',
        'x': 0,
        'y': 0,
        'finalized': True,
        'asset': {'id': '../outside_secret', 'url': '/etc/passwd', 'name': 'x', 'kind': 'image', 'mime_type': 'image/png'},
    })
    db.execute('UPDATE canvas_workflows SET document = ? WHERE id = ?', (json.dumps(raw_doc), wf['id']))
    db.commit()

    prev = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack/preview", json={'scope': 'all'})
    assert prev.status_code == 200
    pdata = prev.get_json()
    assert [i['node_id'] for i in pdata['items']] == ['n-ok']
    skipped = {s['node_id']: s['reason'] for s in pdata['skipped']}
    assert skipped['n-esc'] == 'unsafe_path'
    assert skipped['n-sym'] == 'unsafe_path'
    assert skipped['n-forged'] == 'unsafe_path'
    assert 'TOP_SECRET_OUTSIDE_FILE_DO_NOT_READ' not in prev.get_data(as_text=True)

    exp = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack", json={'scope': 'all'})
    assert exp.status_code == 200
    assert b'TOP_SECRET_OUTSIDE_FILE_DO_NOT_READ' not in exp.data
    with zipfile.ZipFile(io.BytesIO(exp.data), 'r') as zf:
        media_names = [n for n in zf.namelist() if n.startswith('media/')]
        assert len(media_names) == 1
        manifest_text = zf.read('shotlist.json').decode('utf-8')
        assert '/etc/passwd' not in manifest_text
        assert str(isolated_backend) not in manifest_text


def test_zero_leak_for_api_keys_signed_urls_endpoints_and_local_paths(client, isolated_backend):
    # Construct realistic synthetic secrets at runtime to test thorough scrubbing without false secret-scan triggers.
    fake_api_key = 'sk-' + 'AbCdEfGhIjKlMnOpQrStUvWxYz123456'  # secret-scan: allow
    fake_bearer = 'eyJhbGciOiJIUzI1NiJ9.syntheticPayloadToken9999'  # secret-scan: allow
    fake_sig = '9a8b7c6d5e4f3a2b1c0d9e8f'
    fake_token = 'tok_secret_value_88776655'
    fake_endpoint = 'ep-20990101-test'  # secret-scan: allow
    fake_signed_url = (
        f'https://tos-bucket.example.invalid/private/video.mp4'
        f'?X-Tos-Signature={fake_sig}&Signature={fake_sig}&token={fake_token}'  # secret-scan: allow
    )
    local_abs_path = str(isolated_backend / 'secret_dir' / 'config.json')
    data_abs_path = '/data/private_user/Nanobanana/config.json'

    wf = _create_workflow(client, f'场次_{fake_endpoint}_{data_abs_path}')
    t1, a1, _ = _create_generated_task_media(
        client, wf,
        kind='image',
        provider='ark',
        params={
            'model': fake_endpoint,
            'api_key': fake_api_key,
            'prompt': f'api_key={fake_api_key} Bearer {fake_bearer} {fake_signed_url} {fake_endpoint} {local_abs_path} {data_abs_path}',
        },
        payload=_png_bytes('blue'),
        filename='leak.png',
    )

    doc = copy.deepcopy(wf['document'])
    doc['nodes'] = [
        _make_node(
            'n-leak', 'image',
            f'镜头_{fake_endpoint}_Bearer {fake_bearer}',
            text=(
                f'主角持伞走在街上 api_key="{fake_api_key}" '
                f'Authorization: Bearer {fake_bearer} '
                f'ref={fake_signed_url} '
                f'endpoint={fake_endpoint} '
                f'path={local_abs_path} {data_abs_path}'
            ),
            asset=a1,
            task_id=t1,
            finalized=True,
        ),
    ]
    wf = _save_workflow(client, wf, doc)

    forbidden_substrings = [
        fake_api_key,
        fake_bearer,
        fake_sig,
        fake_token,
        fake_endpoint,
        local_abs_path,
        data_abs_path,
        str(isolated_backend),
        str(storage.OUTPUT_DIR),
    ]

    prev = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack/preview", json={'scope': 'all'})
    assert prev.status_code == 200
    prev_text = prev.get_data(as_text=True)
    for secret in forbidden_substrings:
        assert secret not in prev_text, f'Leaked in preview: {secret}'
    for header_val in prev.headers.values():
        for secret in forbidden_substrings:
            assert secret not in header_val, f'Leaked in preview header: {secret}'

    exp = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack", json={'scope': 'all'})
    assert exp.status_code == 200
    for header_val in exp.headers.values():
        for secret in forbidden_substrings:
            assert secret not in header_val, f'Leaked in export header: {secret}'

    with zipfile.ZipFile(io.BytesIO(exp.data), 'r') as zf:
        csv_text = zf.read('shotlist.csv').decode('utf-8-sig')
        json_text = zf.read('shotlist.json').decode('utf-8')
        all_names = '\n'.join(zf.namelist())
        for blob_name, content in (('names', all_names), ('shotlist.csv', csv_text), ('shotlist.json', json_text)):
            for secret in forbidden_substrings:
                assert secret not in content, f'Leaked in {blob_name}: {secret}'
        # Confirm endpoint was masked cleanly to ep-***
        assert 'ep-***' in json_text or 'ep-***' in csv_text


def test_pack_size_limit_same_origin_and_auth_guard(app_and_client, monkeypatch):
    app, client = app_and_client
    wf = _create_workflow(client, '安全门禁测试')
    t1, a1, raw = _create_generated_task_media(client, wf, payload=_png_bytes('blue', (64, 64)), filename='big.png')
    doc = copy.deepcopy(wf['document'])
    doc['nodes'] = [_make_node('n-big', 'image', '大图', asset=a1, task_id=t1, finalized=True)]
    wf = _save_workflow(client, wf, doc)

    # 1. Cross-origin / non-JSON rejected
    cross = client.post(
        f"/api/canvas/workflows/{wf['id']}/export-pack",
        json={'scope': 'all'},
        headers={'Origin': 'https://evil.example.invalid'},
    )
    assert cross.status_code == 403
    cross_site = client.post(
        f"/api/canvas/workflows/{wf['id']}/export-pack/preview",
        json={'scope': 'all'},
        headers={'Sec-Fetch-Site': 'cross-site'},
    )
    assert cross_site.status_code == 403
    bad_ct = client.post(
        f"/api/canvas/workflows/{wf['id']}/export-pack/preview",
        data='{"scope":"all"}',
        content_type='text/plain',
    )
    assert bad_ct.status_code == 415

    # 2. Empty scope export returns 400
    empty_exp = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack", json={'scope': 'selected', 'node_ids': []})
    assert empty_exp.status_code == 400

    # 3. Safety byte cap triggers over_limit in preview and 413 in export
    monkeypatch.setattr(export_pack, 'MAX_PACK_BYTES', max(1, len(raw) - 1))
    prev = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack/preview", json={'scope': 'all'})
    assert prev.status_code == 200
    assert prev.get_json()['over_limit'] is True
    exp = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack", json={'scope': 'all'})
    assert exp.status_code == 413

    # 4. Blueprint inherits app-level authentication before_request guard
    auth_app = Flask('export_pack_auth_test')
    auth_app.config.update(TESTING=True)

    @auth_app.before_request
    def _mock_auth():
        from flask import jsonify, request as req
        if req.path.startswith('/api/canvas/') and req.headers.get('X-Test-Auth') != 'ok':
            return jsonify(success=False, error='未登录'), 401

    auth_app.register_blueprint(canvas_api)
    auth_client = auth_app.test_client()

    unauth_prev = auth_client.post(f"/api/canvas/workflows/{wf['id']}/export-pack/preview", json={'scope': 'all'})
    assert unauth_prev.status_code == 401
    unauth_exp = auth_client.post(f"/api/canvas/workflows/{wf['id']}/export-pack", json={'scope': 'all'})
    assert unauth_exp.status_code == 401
    auth_prev = auth_client.post(
        f"/api/canvas/workflows/{wf['id']}/export-pack/preview",
        json={'scope': 'all'},
        headers={'X-Test-Auth': 'ok'},
    )
    assert auth_prev.status_code == 200


def test_qa_redaction_bypasses_and_idempotency(client):
    """Regression for QA AC2 probes: colon-prefixed paths, colon-formatted signature headers,
    escaped JSON secrets, and idempotent sanitization without bracket corruption."""
    fake_uuid_key = '550e8400-e29b-41d4-a716-446655440000'
    fake_tos_sec_tok = 'STS_tos_sec_token_99887766'
    fake_tos_sig = 'tos_header_sig_abcdef123456'
    fake_amz_sec_tok = 'IQoJb3JpZ2luX2V4YW1wbGVfYW16X3Rva2Vu'
    fake_amz_cred_key = 'AKIA' + 'IOSFODNN7EXAMPLE'  # secret-scan: allow
    fake_goog_sig = 'goog_header_sig_55443322'
    colon_root_path = '/root/.ssh/id_rsa'
    colon_data_path = '/data/private_other/config.json'
    file_home_path = '/home/alice/.env'

    prompt_payload = (
        f'path:{colon_root_path} path:{colon_data_path} file:{file_home_path} '
        f'X-Tos-Security-Token: {fake_tos_sec_tok} '
        f'X-Tos-Signature: {fake_tos_sig} '
        f'X-Amz-Security-Token: {fake_amz_sec_tok} '
        f'X-Amz-Credential={fake_amz_cred_key}/20261121/us-east-1/s3/aws4_request '
        f'X-Goog-Signature: {fake_goog_sig} '
        f'{{\\"api_key\\": \\"{fake_uuid_key}\\", \\"note\\": \\"ok\\"}} '
        f'{{"api_key": "{fake_uuid_key}"}}'
    )

    # 1. Direct sanitize_text idempotency & no [REDACTED]] corruption
    once = export_pack.sanitize_text(prompt_payload, collapse_whitespace=True)
    twice = export_pack.sanitize_text(once, collapse_whitespace=True)
    assert once == twice, f'Not idempotent:\n1: {once}\n2: {twice}'
    assert '[REDACTED]]' not in once
    assert '[REDACTED]]' not in twice
    assert '[PATH_REDACTED]]' not in once
    for leaked in (
        fake_uuid_key,
        fake_tos_sec_tok,
        fake_tos_sig,
        fake_amz_sec_tok,
        fake_amz_cred_key,
        fake_goog_sig,
        colon_root_path,
        colon_data_path,
        file_home_path,
    ):
        assert leaked not in once, f'Leaked in sanitize_text: {leaked}'
    # Normal non-secret JSON field stays intact
    assert '\\"note\\": \\"ok\\"' in once

    # 2. Full end-to-end preview + ZIP (shotlist.csv & shotlist.json) verification
    wf = _create_workflow(client, '脱敏绕过回归')
    aud_bytes = b'RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
    t_aud, a_aud, _ = _create_generated_task_media(
        client, wf,
        kind='audio',
        provider='cupsy',
        params={'model': 'seed-audio-1.0', 'prompt': prompt_payload},
        payload=aud_bytes,
        filename='probe.wav',
        mime='audio/wav',
        output_kind='output_audio',
    )
    doc = copy.deepcopy(wf['document'])
    doc['nodes'] = [
        _make_node('n-probe', 'audio', f'探针 path:{colon_root_path}', text='', asset=a_aud, task_id=t_aud, finalized=True),
    ]
    wf = _save_workflow(client, wf, doc)

    prev = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack/preview", json={'scope': 'all'})
    assert prev.status_code == 200
    prev_text = prev.get_data(as_text=True)

    exp = client.post(f"/api/canvas/workflows/{wf['id']}/export-pack", json={'scope': 'all'})
    assert exp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exp.data), 'r') as zf:
        csv_text = zf.read('shotlist.csv').decode('utf-8-sig')
        json_text = zf.read('shotlist.json').decode('utf-8')

    for surface, content in (('preview', prev_text), ('shotlist.csv', csv_text), ('shotlist.json', json_text)):
        assert '[REDACTED]]' not in content, f'Bracket corruption in {surface}: {content}'
        assert '[PATH_REDACTED]]' not in content, f'Path bracket corruption in {surface}: {content}'
        for leaked in (
            fake_uuid_key,
            fake_tos_sec_tok,
            fake_tos_sig,
            fake_amz_sec_tok,
            fake_amz_cred_key,
            fake_goog_sig,
            colon_root_path,
            colon_data_path,
            file_home_path,
            '/20261121/us-east-1/s3/aws4_request',
        ):
            assert leaked not in content, f'Leaked {leaked} in {surface}'
