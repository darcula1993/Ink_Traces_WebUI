"""CHARACTER-LIBRARY-20261114 A: local character library backend (acceptance 1, 2, 5 backend parts)."""
import base64
import io
import sqlite3
import wave

import pytest
from PIL import Image

import app as application
import canvas_store as store
import characters as chars
import tasks
from test_canvas_image_params import setup as image_setup
from test_generation import FakeResponse, _png_bytes


def png(color='red', size=(20, 20)):
    b = io.BytesIO(); Image.new('RGB', size, color).save(b, format='PNG'); return b.getvalue()


def wav(seconds=1.0, rate=8000):
    b = io.BytesIO()
    with wave.open(b, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
        out.writeframes(b'\x00\x00' * int(rate * seconds))
    return b.getvalue()


COLORS = ['red', 'green', 'blue', 'white', 'black', 'yellow', 'purple', 'orange', 'pink']


@pytest.fixture
def client():
    return application.app.test_client()


def create(client, name='林', **extra):
    r = client.post('/api/characters', json={'name': name, **extra})
    assert r.status_code == 201, r.json
    return r.json['character']


def upload_images(client, cid, *colors):
    return client.post(f'/api/characters/{cid}/images',
                       data={'file': [(io.BytesIO(png(c)), f'{c}.png') for c in colors]}, content_type='multipart/form-data')


def workflow():
    p = store.create_project('p')['id']
    return p, store.create_workflow(p, 'w')['id']


# ---- 验收1：CRUD、名称、图片上限、声音 -------------------------------------------------

def test_crud_name_rules_uniqueness_and_description(client):
    c = create(client, ' 林 ', description='  黑发，青色长衫  ')
    assert c['name'] == '林' and c['description'] == '黑发，青色长衫' and c['images'] == [] and c['voice'] is None
    assert set(c) == {'id', 'name', 'description', 'voice', 'images', 'created_at', 'updated_at'}
    assert client.post('/api/characters', json={'name': '林'}).status_code == 409
    alice = create(client, 'Alice')
    r = client.post('/api/characters', json={'name': 'alice'})
    assert r.status_code == 409 and r.json['error'] == '角色名已存在'
    assert client.patch(f"/api/characters/{alice['id']}", json={'name': '林'}).status_code == 409
    for bad in ['', '   ', 'a' * 25, '林 一', '林　一', '@林', '林[1]', '林(甲)', '林（甲）', '图片1', '视频12', '音频3', 123, None]:
        r = client.post('/api/characters', json={'name': bad})
        assert r.status_code == 400, bad
        assert r.json['success'] is False and any('一' <= ch <= '鿿' for ch in r.json['error'])
    assert client.post('/api/characters', json={'name': '图片A'}).status_code == 201
    assert client.post('/api/characters', json={'name': 'x' * 24}).status_code == 201
    assert client.post('/api/characters', json={'name': '甲', 'description': '字' * 301}).status_code == 400
    assert client.post('/api/characters', json={'name': '乙', 'description': '字' * 300}).status_code == 201
    assert client.post('/api/characters', json={'name': '丙', 'notes': 'x'}).status_code == 400
    updated = client.patch(f"/api/characters/{alice['id']}", json={'name': 'ALICE', 'description': '新描述'}).json['character']
    assert updated['name'] == 'ALICE' and updated['description'] == '新描述' and updated['updated_at'] >= alice['updated_at']
    assert client.get(f"/api/characters/{alice['id']}").json['character'] == updated
    names = [x['name'] for x in client.get('/api/characters').json['characters']]
    assert 'ALICE' in names and '林' in names
    assert client.get('/api/characters/' + 'f' * 32).status_code == 404
    assert client.get('/api/characters/../etc').status_code == 404
    assert client.delete(f"/api/characters/{alice['id']}").status_code == 200
    assert client.get(f"/api/characters/{alice['id']}").status_code == 404
    assert client.post('/api/characters', json={'name': 'alice'}).status_code == 201  # name freed


def local_count():
    return tasks.get_db().execute('SELECT count(*) FROM canvas_local_uploads').fetchone()[0]


def media_count():
    return tasks.get_db().execute('SELECT count(*) FROM media').fetchone()[0]


def media_row(media_id):
    return tasks.get_db().execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()


def media_upload(client, raw, name, **form):
    r = client.post('/api/canvas/media', data={'file': (io.BytesIO(raw), name), **form})
    assert r.status_code == 201, r.json
    return r.json['media']


def media_delete(client, ids):
    r = client.post('/api/canvas/media/delete', json={'ids': ids})
    assert r.status_code == 200, r.json
    return r.json


def test_images_limit_order_dedup_and_delete(client):
    c = create(client)
    r = upload_images(client, c['id'], *COLORS[:6])
    assert r.status_code == 201 and len(r.json['images']) == 6
    images = r.json['character']['images']
    assert [i['position'] for i in images] == list(range(6))
    assert images[0]['width'] == 20 and images[0]['height'] == 20 and images[0]['mime_type'] == 'image/png'
    assert set(images[0]) >= {'asset_id', 'asset_ref', 'media_id', 'url', 'name', 'mime_type', 'width', 'height', 'position'}
    # S6c: uploads are registered in the global media library root and referenced by media id
    first = media_row(images[0]['asset_id'])
    assert images[0]['asset_ref'] == images[0]['media_id'] == images[0]['asset_id'] and first is not None
    assert first['folder_id'] is None and first['origin'] == 'upload' and first['name'] == 'red.png'
    assert media_count() == 6 and local_count() == 0 and not (store.asset_root() / 'characters').exists()
    listed = {m['id'] for m in client.get('/api/canvas/media', query_string={'folder_id': 'root'}).json['items']}
    assert {i['asset_id'] for i in images} <= listed
    assert client.get(images[0]['url']).data == png('red')
    assert client.get('/api/canvas/media/' + images[0]['asset_id']).data == png('red')
    assert client.get(images[0]['thumbnail_url']).mimetype == 'image/webp'
    # duplicates are idempotent and do not count
    again = upload_images(client, c['id'], 'red')
    assert again.status_code == 201 and again.json['images'][0]['asset_id'] == images[0]['asset_id'] and media_count() == 6
    # 6 + 3 new > 8 -> rejected, nothing written (neither reference nor library item nor file)
    files = sorted(p.name for p in (store.asset_root() / 'media').iterdir())
    assert upload_images(client, c['id'], *COLORS[6:9]).status_code == 400
    assert len(client.get(f"/api/characters/{c['id']}").json['character']['images']) == 6 and media_count() == 6
    assert sorted(p.name for p in (store.asset_root() / 'media').iterdir()) == files
    assert upload_images(client, c['id'], *COLORS[6:8]).status_code == 201
    assert upload_images(client, c['id'], 'pink').status_code == 400
    images = client.get(f"/api/characters/{c['id']}").json['character']['images']
    assert len(images) == 8
    order = [i['asset_id'] for i in reversed(images)]
    reordered = client.patch(f"/api/characters/{c['id']}", json={'image_order': order}).json['character']
    assert [i['asset_id'] for i in reordered['images']] == order
    assert client.patch(f"/api/characters/{c['id']}", json={'image_order': order[:-1]}).status_code == 400
    removed = client.delete(f"/api/characters/{c['id']}/images/{order[0]}")
    assert removed.status_code == 200
    left = removed.json['character']['images']
    assert [i['asset_id'] for i in left] == order[1:] and [i['position'] for i in left] == list(range(7))
    # removing from the character deletes only the reference
    assert client.get(images[-1]['url']).status_code == 404
    assert media_row(order[0]) is not None and client.get('/api/canvas/media/' + order[0]).status_code == 200
    r = client.post(f"/api/characters/{c['id']}/images", data={'file': (io.BytesIO(wav()), 'a.wav')})
    assert r.status_code == 400
    assert media_count() == 8  # the refused audio was not left in the library


def test_voice_audio_only_type_duration_and_clear(client):
    c = create(client)
    r = client.post(f"/api/characters/{c['id']}/voice-audio", data={'file': (io.BytesIO(wav(2)), 'voice.wav')})
    assert r.status_code == 201, r.json
    voice = r.json['voice']
    assert voice['type'] == 'audio' and voice['name'] == 'voice.wav' and abs(voice['duration'] - 2) < 0.05
    assert set(voice) >= {'type', 'asset_id', 'asset_ref', 'media_id', 'url', 'name', 'duration'}
    assert media_row(voice['asset_id'])['kind'] == 'audio' and local_count() == 0
    assert client.get(voice['url']).data == wav(2)
    assert client.post(f"/api/characters/{c['id']}/voice-audio", data={'file': (io.BytesIO(wav(31)), 'long.wav')}).status_code == 400
    assert media_count() == 1  # the over-long upload was rolled back
    assert client.get(f"/api/characters/{c['id']}").json['character']['voice'] == voice
    assert client.post(f"/api/characters/{c['id']}/voice-audio", data={'file': (io.BytesIO(png()), 'x.png')}).status_code == 400
    second = client.post(f"/api/characters/{c['id']}/voice-audio", data={'file': (io.BytesIO(wav(30)), 'v2.wav')}).json['voice']
    assert second['asset_id'] != voice['asset_id'] and client.get(voice['url']).status_code == 404
    assert media_row(voice['asset_id']) is not None  # replaced reference only
    assert client.patch(f"/api/characters/{c['id']}", json={'voice': {'type': 'speaker', 'speaker': 'vivi'}}).status_code == 400
    assert client.patch(f"/api/characters/{c['id']}", json={'voice': second}).status_code == 200
    cleared = client.patch(f"/api/characters/{c['id']}", json={'voice': None}).json['character']
    assert cleared['voice'] is None and client.get(second['url']).status_code == 404 and media_row(second['asset_id']) is not None


def test_mp3_voice_accepted(client, tmp_path):
    import subprocess
    target = tmp_path / 'v.mp3'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=1', '-y', str(target)], check=True)
    c = create(client)
    r = client.post(f"/api/characters/{c['id']}/voice-audio", data={'file': (io.BytesIO(target.read_bytes()), 'v.mp3')})
    assert r.status_code == 201 and r.json['voice']['type'] == 'audio'


def test_delete_character_keeps_media_and_imported_references(client):
    p, w = workflow()
    c = create(client)
    images = upload_images(client, c['id'], 'red', 'blue').json['character']['images']
    client.post(f"/api/characters/{c['id']}/voice-audio", data={'file': (io.BytesIO(wav()), 'v.wav')})
    imported = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id'], 'image_ids': [images[1]['asset_id']], 'voice': True}).json
    deleted = client.delete(f"/api/characters/{c['id']}")
    assert deleted.status_code == 200 and deleted.json['references_removed'] == 3
    assert client.get(images[0]['url']).status_code == 404
    assert media_count() == 3
    assert client.get(imported['assets'][0]['url']).data == png('blue')
    assert client.get(imported['voice']['url']).data == wav()
    assert client.delete(f"/api/characters/{c['id']}").status_code == 404
    other = create(client, '月')
    assert client.delete(f"/api/characters/{other['id']}", headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403


# ---- 验收2：来源（S6c：media id 直接引用；旧身份走别名；库外来源先入库根目录） -----------------

def test_media_sources_reference_without_copies(client):
    p, w = workflow()
    c, fresh = create(client), create(client, '新角色')
    item = media_upload(client, png('green'), 'g.png')
    files = sorted(x.name for x in (store.asset_root() / 'media').iterdir())
    # direct media id and the library selection shape {source:'media', id}
    r = client.post(f"/api/characters/{c['id']}/images", json={'source': 'media', 'media_id': item['id']})
    assert r.status_code == 201, r.json
    assert r.json['images'][0]['asset_id'] == item['id']
    r = client.post(f"/api/characters/{fresh['id']}/images", json={'source': 'library', 'asset_ref': {'source': 'media', 'id': item['id']}})
    assert r.status_code == 201 and r.json['images'][0]['asset_id'] == item['id']
    # canvas "加入角色": canvas nodes reference media ids
    r = client.post(f"/api/characters/{fresh['id']}/voice-audio", json={'source': 'canvas', 'workflow_id': w, 'asset_id': media_upload(client, wav(), 'a.wav')['id']})
    assert r.status_code == 201, r.json
    assert media_count() == 2 and local_count() == 0 and not tasks.get_db().execute('SELECT count(*) FROM canvas_assets').fetchone()[0]
    assert sorted(x.name for x in (store.asset_root() / 'media').iterdir()) == sorted(files + [media_row(r.json['voice']['asset_id'])['relpath']])
    # wrong kinds / unknown / deleted
    audio_id = r.json['voice']['asset_id']
    assert client.post(f"/api/characters/{c['id']}/images", json={'source': 'media', 'media_id': audio_id}).status_code == 400
    assert client.post(f"/api/characters/{c['id']}/images", json={'source': 'media', 'media_id': 'f' * 32}).status_code == 404
    assert client.post(f"/api/characters/{c['id']}/images", json={'source': 'media', 'media_id': 'bad'}).status_code == 400
    assert client.post(f"/api/characters/{c['id']}/images", json={'source': 'media', 'media_id': item['id'], 'x': 1}).status_code == 400
    assert client.post(f"/api/characters/{c['id']}/images", json={'source': 'url', 'url': 'https://x'}).status_code == 400
    assert client.post(f"/api/characters/{c['id']}/images", json={'source': 'canvas', 'workflow_id': w, 'asset_id': 'f' * 32}).status_code == 404
    other = media_upload(client, png('white'), 'w.png')
    media_delete(client, [other['id']])
    r = client.post(f"/api/characters/{c['id']}/images", json={'source': 'media', 'media_id': other['id']})
    assert r.status_code == 410 and r.json['success'] is False


def test_old_identities_resolve_through_aliases(client):
    import media_library
    c = create(client)
    item = media_upload(client, png('green'), 'g.png')
    old = 'a' * 32
    media_library.add_alias('local', old, item['id']); tasks.get_db().commit()
    r = client.post(f"/api/characters/{c['id']}/images", json={'source': 'library', 'asset_ref': 'local:' + old})
    assert r.status_code == 201, r.json
    assert r.json['images'][0]['asset_id'] == item['id'] and media_count() == 1
    r = client.post(f"/api/characters/{c['id']}/images", json={'source': 'library', 'asset_ref': {'source': 'local', 'id': old}})
    assert r.status_code == 201 and len(r.json['character']['images']) == 1
    assert [x['id'] for x in client.get('/api/characters', query_string={'asset_ref': 'local:' + old}).json['characters']] == [c['id']]
    assert [x['id'] for x in client.get('/api/characters', query_string={'asset_ref': item['id']}).json['characters']] == [c['id']]
    assert client.get('/api/characters', query_string={'asset_ref': 'library:' + 'b' * 32}).json['characters'] == []
    # old reference ids still address the image (read, reorder, remove)
    assert client.get(f"/api/characters/{c['id']}/assets/{old}").data == png('green')
    assert client.patch(f"/api/characters/{c['id']}", json={'image_order': [old]}).status_code == 200
    assert client.delete(f"/api/characters/{c['id']}/images/{old}").json['character']['images'] == []
    # a migrated old canvas asset id (workflow alias)
    p, w = workflow()
    canvas_old = 'c' * 32
    media_library.add_alias('workflow', canvas_old, item['id']); tasks.get_db().commit()
    r = client.post(f"/api/characters/{c['id']}/images", json={'source': 'canvas', 'workflow_id': w, 'asset_id': canvas_old})
    assert r.status_code == 201 and r.json['images'][0]['asset_id'] == item['id'] and media_count() == 1


def test_sources_outside_library_are_registered_in_root(client):
    """Old project-library / canvas copies not migrated yet are copied into the library root (no 本地素材)."""
    p, w = workflow()
    c = create(client)
    lib = client.post(f'/api/canvas/projects/{p}/assets', data={'file': (io.BytesIO(png('green')), 'g.png')}).json['asset']
    r = client.post(f"/api/characters/{c['id']}/images", json={'source': 'library', 'asset_ref': {'source': 'library', 'id': lib['id']}})
    assert r.status_code == 201, r.json
    row = media_row(r.json['images'][0]['asset_id'])
    assert row['name'] == 'g.png' and row['folder_id'] is None and row['origin'] == 'upload'
    assert store.get_asset(p, lib['id'], library=True)  # ownership of the source untouched
    canvas = client.post(f'/api/canvas/workflows/{w}/assets', data={'file': (io.BytesIO(png('blue')), 'b.png')}).json['asset']
    r = client.post(f"/api/characters/{c['id']}/images", json={'source': 'canvas', 'workflow_id': w, 'asset_id': canvas['id']})
    assert r.status_code == 201 and media_row(r.json['images'][0]['asset_id']) is not None
    # same content again (from another source) dedups to the same media item
    r = client.post(f"/api/characters/{c['id']}/images", data={'file': (io.BytesIO(png('blue')), 'again.png')})
    assert r.status_code == 201 and len(r.json['character']['images']) == 2
    assert media_count() == 2 and local_count() == 0
    # deleting the copied-from originals does not affect the character
    for key in ('library:' + lib['id'], 'workflow:' + canvas['id']):
        assert client.delete('/api/canvas/library/items/' + key).status_code == 200
    images = client.get(f"/api/characters/{c['id']}").json['character']['images']
    assert [client.get(i['url']).data for i in images] == [png('green'), png('blue')]


def test_deleting_referenced_media_lists_and_unlinks_characters(client):
    p, w = workflow()
    a, b = create(client, '林'), create(client, '月')
    shared = upload_images(client, a['id'], 'red', 'blue').json['images']
    client.post(f"/api/characters/{b['id']}/images", json={'source': 'media', 'media_id': shared[0]['media_id']})
    imported = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': a['id']}).json['assets']
    users = client.get('/api/characters', query_string={'asset_ref': shared[0]['asset_ref']}).json['characters']
    assert {u['name'] for u in users} == {'林', '月'}
    preview = client.post('/api/canvas/media/delete-preview', json={'ids': [shared[0]['media_id']]}).json
    assert [(x['name'], x['asset_ids']) for x in preview['characters']] == [('月', [shared[0]['asset_id']]), ('林', [shared[0]['asset_id']])]
    before = client.get(f"/api/characters/{a['id']}").json['character']['updated_at']
    result = media_delete(client, [shared[0]['media_id']])
    assert len(result['characters']) == 2
    after = client.get(f"/api/characters/{a['id']}").json['character']
    assert [i['asset_id'] for i in after['images']] == [shared[1]['asset_id']] and after['images'][0]['position'] == 0
    assert after['updated_at'] > before
    assert client.get(f"/api/characters/{b['id']}").json['character']['images'] == []
    # the canvas referenced the media directly: deleted -> 410, the other stays
    assert client.get(imported[0]['url']).status_code == 410 and client.get(imported[1]['url']).status_code == 200
    # voice reference is unlinked the same way
    voice = client.post(f"/api/characters/{a['id']}/voice-audio", data={'file': (io.BytesIO(wav()), 'v.wav')}).json['voice']
    media_delete(client, [voice['media_id']])
    assert client.get(f"/api/characters/{a['id']}").json['character']['voice'] is None


# ---- character-assets：S6c 返回 media 引用，不复制；幂等；无自动生成 -----------------------------

def test_character_assets_import_references_media(client, monkeypatch):
    monkeypatch.setattr(application.HTTP, 'post', lambda *a, **k: pytest.fail('network'))
    monkeypatch.setattr(application.HTTP, 'get', lambda *a, **k: pytest.fail('network'))
    p, w = workflow()
    c = create(client)
    images = upload_images(client, c['id'], 'red', 'blue', 'green').json['character']['images']
    ids = [images[2]['asset_id'], images[0]['asset_id']]
    first = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id'], 'image_ids': ids})
    assert first.status_code == 200, first.json
    assert [a['name'] for a in first.json['assets']] == ['green.png', 'red.png'] and first.json['voice'] is None
    assert [a['id'] for a in first.json['assets']] == ids and set(first.json['mapping']) == set(ids)
    assert first.json['assets'][0] == {'id': ids[0], 'name': 'green.png', 'mime_type': 'image/png', 'kind': 'image',
                                       'size_bytes': len(png('green')), 'url': '/api/canvas/media/' + ids[0]}
    second = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id'], 'image_ids': ids})
    assert second.json['assets'] == first.json['assets']
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_assets').fetchone()[0] == 0
    assert tasks.get_db().execute('SELECT count(*) FROM canvas_asset_copies').fetchone()[0] == 0
    assert client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id'], 'image_ids': [], 'voice': True}).status_code == 404
    client.post(f"/api/characters/{c['id']}/voice-audio", data={'file': (io.BytesIO(wav()), 'v.wav')})
    v1 = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id'], 'image_ids': [], 'voice': True}).json
    v2 = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id'], 'image_ids': [], 'voice': True}).json
    assert v1['assets'] == [] and v1['voice']['kind'] == 'audio' and v1['voice'] == v2['voice']
    allimg = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id']}).json
    assert len(allimg['assets']) == 3
    doc = store.workflow(w)['document']
    doc['nodes'] = [{'id': 'n', 'type': 'image', 'x': 0, 'y': 0, 'referenceAssets': first.json['assets'],
                     'characterRefs': {c['id']: {'name': '林', 'assetIds': [a['id'] for a in first.json['assets']]}}}]
    assert client.put(f'/api/canvas/workflows/{w}', json={'title': 'w', 'document': doc, 'revision': 1}).status_code == 200
    for bad in [{'character_id': 'f' * 32, 'image_ids': []}, {'character_id': c['id'], 'image_ids': ['f' * 32]},
                {'character_id': c['id'], 'image_ids': 'x'}, {'character_id': c['id'], 'voice': 'yes'},
                {'character_id': c['id'], 'extra': 1}]:
        assert client.post(f'/api/canvas/workflows/{w}/character-assets', json=bad).status_code in (400, 404), bad
    assert client.post('/api/canvas/workflows/' + 'f' * 32 + '/character-assets', json={'character_id': c['id']}).status_code == 404
    assert tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


def test_media_kept_after_character_deleted_then_library_delete_placeholders(client):
    """Deleting the character keeps the media; deleting the media later leaves node placeholders / strips inputs."""
    p, w = workflow()
    c = create(client)
    upload_images(client, c['id'], 'red')
    ref = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id']}).json['assets'][0]
    client.delete(f"/api/characters/{c['id']}")
    assert client.get(ref['url']).status_code == 200
    result = media_delete(client, [ref['id']])
    assert result['deleted_ids'] == [ref['id']] and result['characters'] == []


def test_character_change_does_not_touch_canvas(client):
    """验收5后端部分：角色更新/删除不改画布文档，不建任务。"""
    p, w = workflow()
    c = create(client)
    upload_images(client, c['id'], 'red')
    imported = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id']}).json
    doc = store.workflow(w)['document']
    doc['nodes'] = [{'id': 'n', 'type': 'image', 'x': 0, 'y': 0, 'text': '【人物】\n林对应@图片1', 'referenceAssets': imported['assets'],
                     'referenceMentions': {'@图片1': imported['assets'][0]['id']},
                     'characterRefs': {c['id']: {'name': '林', 'assetIds': [imported['assets'][0]['id']]}}}]
    store.update_workflow(w, 'w', doc, 1)
    before = store.workflow(w)
    before_updated = client.get(f"/api/characters/{c['id']}").json['character']['updated_at']
    upload_images(client, c['id'], 'blue')
    assert client.get(f"/api/characters/{c['id']}").json['character']['updated_at'] > before_updated
    client.delete(f"/api/characters/{c['id']}")
    after = store.workflow(w)
    assert after['revision'] == before['revision'] and after['document'] == before['document']
    assert client.get(imported['assets'][0]['url']).status_code == 200
    assert tasks.get_db().execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


# ---- node.characterRefs 白名单与校验 ------------------------------------------------------

def _save(w, node):
    doc = store.workflow(w)['document']; doc['nodes'] = [node]
    return store.update_workflow(w, 'w', doc, store.workflow(w)['revision'])


@pytest.mark.parametrize('refs', [{}, {'a' * 32: {'name': '林', 'assetIds': []}},
                                  {'a' * 32: {'name': '林', 'assetIds': ['b' * 32, 'c' * 32]}, 'd' * 32: {'name': 'x' * 24, 'assetIds': ['e' * 32] * 1}}])
@pytest.mark.parametrize('kind', ['image', 'video', 'audio'])
def test_character_refs_accepted(refs, kind):
    p, w = workflow()
    saved = _save(w, {'id': 'n', 'type': kind, 'x': 0, 'y': 0, 'characterRefs': refs})
    assert saved['document']['nodes'][0]['characterRefs'] == refs


@pytest.mark.parametrize('refs', [None, [], 'x', {'bad': {'name': '林', 'assetIds': []}}, {'A' * 32: {'name': '林', 'assetIds': []}},
                                  {'a' * 32: {'name': '林'}}, {'a' * 32: {'assetIds': []}}, {'a' * 32: {'name': '', 'assetIds': []}},
                                  {'a' * 32: {'name': 'x' * 25, 'assetIds': []}}, {'a' * 32: {'name': '林', 'assetIds': ['b' * 32, 'b' * 32]}},
                                  {'a' * 32: {'name': '林', 'assetIds': ['bad']}}, {'a' * 32: {'name': '林', 'assetIds': [f'{i:032x}' for i in range(10)]}},
                                  {'a' * 32: {'name': '林', 'assetIds': [], 'imageIds': []}}, {'a' * 32: {'name': '林', 'assetIds': [], 'useVoice': True}},
                                  {f'{i:032x}': {'name': '林', 'assetIds': []} for i in range(51)}])
def test_character_refs_rejected(refs):
    p, w = workflow()
    with pytest.raises(store.CanvasError):
        _save(w, {'id': 'n', 'type': 'image', 'x': 0, 'y': 0, 'characterRefs': refs})


@pytest.mark.parametrize('stamp', ['2026-11-14T08:30:00.123456+00:00', '2026-11-14T08:30:00Z', '2026-11-14'])
def test_character_refs_updated_at_accepted(stamp):
    p, w = workflow()
    refs = {'a' * 32: {'name': '林', 'assetIds': [], 'updatedAt': stamp}}
    assert _save(w, {'id': 'n', 'type': 'image', 'x': 0, 'y': 0, 'characterRefs': refs})['document']['nodes'][0]['characterRefs'] == refs


@pytest.mark.parametrize('stamp', [None, 123, '', 'yesterday', '2026-13-01T00:00:00', '2026-11-14T08:30:00+00:00' + ' ' * 20])
def test_character_refs_updated_at_rejected(stamp):
    p, w = workflow()
    with pytest.raises(store.CanvasError):
        _save(w, {'id': 'n', 'type': 'image', 'x': 0, 'y': 0, 'characterRefs': {'a' * 32: {'name': '林', 'assetIds': [], 'updatedAt': stamp}}})


def test_character_refs_updated_at_from_api_roundtrip(client):
    p, w = workflow()
    c = create(client)
    refs = {c['id']: {'name': c['name'], 'assetIds': [], 'updatedAt': c['updated_at']}}
    _save(w, {'id': 'n', 'type': 'image', 'x': 0, 'y': 0, 'characterRefs': refs})
    upload_images(client, c['id'], 'red')
    changed = client.get(f"/api/characters/{c['id']}").json['character']['updated_at']
    saved = store.workflow(w)['document']['nodes'][0]['characterRefs'][c['id']]['updatedAt']
    assert saved == c['updated_at'] and changed != saved


@pytest.mark.parametrize('kind', ['text'])
def test_character_refs_only_on_generation_nodes(kind):
    p, w = workflow()
    with pytest.raises(store.CanvasError):
        _save(w, {'id': 'n', 'type': kind, 'x': 0, 'y': 0, 'characterRefs': {}})


def test_media_delete_strips_character_ref_asset_ids(client):
    p, w = workflow()
    c = create(client)
    upload_images(client, c['id'], 'red', 'blue')
    imported = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id']}).json['assets']
    _save(w, {'id': 'n', 'type': 'image', 'x': 0, 'y': 0, 'referenceAssets': imported,
              'characterRefs': {c['id']: {'name': '林', 'assetIds': [a['id'] for a in imported]}}})
    media_delete(client, [imported[0]['id']])
    node = store.workflow(w)['document']['nodes'][0]
    assert node['characterRefs'][c['id']]['assetIds'] == [imported[1]['id']]
    assert [a['id'] for a in node['referenceAssets']] == [imported[1]['id']]


# ---- 迁移 -----------------------------------------------------------------------------

def test_old_database_migrates():
    db = tasks.get_db()
    db.executescript('DROP TABLE character_media; DROP TABLE characters;')
    db.commit()
    store.init_canvas_db()
    assert {'characters', 'character_media'} <= {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # an early characters table without description is upgraded in place, rows preserved
    db.executescript('''DROP TABLE character_media; DROP TABLE characters;
        CREATE TABLE characters (id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);''')
    db.execute("INSERT INTO characters VALUES (?,?,?,?,?)", ('a' * 32, '林', '林', 't', 't'))
    db.commit()
    store.init_canvas_db()
    store.init_canvas_db()  # idempotent
    assert chars.get_character('a' * 32)['description'] == ''


# ---- 提交：角色写成的普通提示词与参考可通过现有校验，原样进入 Provider 请求 ------------------

def test_character_prompt_text_reaches_provider_unchanged(monkeypatch):
    client, wid, body = image_setup(monkeypatch)
    prompt = ('【人物】\n林对应@图片1、@图片2，只采用五官、发型和服装，不采用图片背景；两张参考共同定义同一人物，不生成多个副本。\n'
              '林的外貌设定：黑发，青色长衫\n\n林站在门口，背景参考@图片3')
    captured = []

    def post(url, **kwargs):
        captured.append(kwargs['json'])
        return FakeResponse(payload={'data': [{'b64_json': base64.b64encode(_png_bytes()).decode()}]})
    monkeypatch.setattr(application.HTTP, 'post', post)
    payload = {**{k: str(v) for k, v in body.items()}, 'prompt': prompt,
               'images': [(io.BytesIO(png(c)), f'{c}.png') for c in ('red', 'blue', 'green')]}
    response = client.post('/api/generate', data=payload, content_type='multipart/form-data')
    assert response.status_code == 202, response.json
    with application.app.test_request_context():
        application.execute_image_task(response.json['task_id'])
    assert len(captured) == 1
    assert captured[0]['prompt'] == prompt
    sent = captured[0]['image']
    assert isinstance(sent, list) and len(sent) == 3
