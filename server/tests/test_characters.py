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
    assert set(c) == {'id', 'name', 'description', 'kind', 'folder_id', 'voice', 'images', 'created_at', 'updated_at'}
    assert client.post('/api/characters', json={'name': '林'}).status_code == 409
    alice = create(client, 'Alice')
    r = client.post('/api/characters', json={'name': 'alice'})
    assert r.status_code == 409 and r.json['error'] == '角色名已存在'
    assert client.patch(f"/api/characters/{alice['id']}", json={'name': '林'}).status_code == 409
    for bad in ['', '   ', 'a' * 25, '林 一', '林　一', '@林', '林[1]', '林(甲)', '林（甲）', '林/一', '林\\一', '图片1', '视频12', '音频3', 123, None]:
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
    # CHAR-FOLDERS-20261122: uploads land in the character's 角色卡/<name> folder and are referenced by media id
    first = media_row(images[0]['asset_id'])
    assert images[0]['asset_ref'] == images[0]['media_id'] == images[0]['asset_id'] and first is not None
    assert first['folder_id'] == c['folder_id'] and first['origin'] == 'upload' and first['name'] == 'red.png'
    assert media_count() == 6 and local_count() == 0 and not (store.asset_root() / 'characters').exists()
    listed = {m['id'] for m in client.get('/api/canvas/media', query_string={'folder_id': c['folder_id']}).json['items']}
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
    # removing from the character deletes only the reference and moves the item back to root
    assert client.get(images[-1]['url']).status_code == 404
    assert media_row(order[0]) is not None and media_row(order[0])['folder_id'] is None
    assert client.get('/api/canvas/media/' + order[0]).status_code == 200
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
    import os
    import media_library as media
    p, w = workflow()
    c, fresh = create(client), create(client, '新角色')
    item = media_upload(client, png('green'), 'g.png')
    files = sorted(x.name for x in (store.asset_root() / 'media').iterdir())
    # direct media id from root moves in place into 角色卡/林 without copying
    r = client.post(f"/api/characters/{c['id']}/images", json={'source': 'media', 'media_id': item['id']})
    assert r.status_code == 201, r.json
    assert r.json['images'][0]['asset_id'] == item['id']
    assert media_row(item['id'])['folder_id'] == c['folder_id']
    # adding another character's item hard-link copies into 角色卡/新角色 without stealing from 角色卡/林
    r = client.post(f"/api/characters/{fresh['id']}/images", json={'source': 'library', 'asset_ref': {'source': 'media', 'id': item['id']}})
    assert r.status_code == 201
    fresh_img_id = r.json['images'][0]['asset_id']
    assert fresh_img_id != item['id'] and media_row(fresh_img_id)['folder_id'] == fresh['folder_id']
    assert media_row(item['id'])['folder_id'] == c['folder_id']
    assert os.stat(media.media_path(media_row(fresh_img_id))).st_ino == os.stat(media.media_path(media_row(item['id']))).st_ino
    # canvas "加入角色": canvas nodes reference media ids (root audio moves in place into 角色卡/新角色)
    audio_item = media_upload(client, wav(), 'a.wav')
    r = client.post(f"/api/characters/{fresh['id']}/voice-audio", json={'source': 'canvas', 'workflow_id': w, 'asset_id': audio_item['id']})
    assert r.status_code == 201, r.json
    assert r.json['voice']['asset_id'] == audio_item['id'] and media_row(audio_item['id'])['folder_id'] == fresh['folder_id']
    assert media_count() == 3 and local_count() == 0 and not tasks.get_db().execute('SELECT count(*) FROM canvas_assets').fetchone()[0]
    assert sorted(x.name for x in (store.asset_root() / 'media').iterdir()) == sorted(
        files + [media_row(fresh_img_id)['relpath'], media_row(audio_item['id'])['relpath']]
    )
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
    """Old project-library / canvas copies not migrated yet are registered directly into 角色卡/<name> (no 本地素材)."""
    p, w = workflow()
    c = create(client)
    lib = client.post(f'/api/canvas/projects/{p}/assets', data={'file': (io.BytesIO(png('green')), 'g.png')}).json['asset']
    r = client.post(f"/api/characters/{c['id']}/images", json={'source': 'library', 'asset_ref': {'source': 'library', 'id': lib['id']}})
    assert r.status_code == 201, r.json
    row = media_row(r.json['images'][0]['asset_id'])
    assert row['name'] == 'g.png' and row['folder_id'] == c['folder_id'] and row['origin'] == 'upload'
    assert store.get_asset(p, lib['id'], library=True)  # ownership of the source untouched
    canvas = client.post(f'/api/canvas/workflows/{w}/assets', data={'file': (io.BytesIO(png('blue')), 'b.png')}).json['asset']
    r = client.post(f"/api/characters/{c['id']}/images", json={'source': 'canvas', 'workflow_id': w, 'asset_id': canvas['id']})
    assert r.status_code == 201 and media_row(r.json['images'][0]['asset_id'])['folder_id'] == c['folder_id']
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
    b_copy = client.post(f"/api/characters/{b['id']}/images", json={'source': 'media', 'media_id': shared[0]['media_id']}).json['images'][0]
    assert b_copy['media_id'] != shared[0]['media_id']
    imported = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': a['id']}).json['assets']
    assert {u['name'] for u in client.get('/api/characters', query_string={'asset_ref': shared[0]['asset_ref']}).json['characters']} == {'林'}
    assert {u['name'] for u in client.get('/api/characters', query_string={'asset_ref': b_copy['asset_ref']}).json['characters']} == {'月'}
    preview = client.post('/api/canvas/media/delete-preview', json={'ids': [shared[0]['media_id'], b_copy['media_id']]}).json
    assert [(x['name'], x['asset_ids']) for x in preview['characters']] == [('月', [b_copy['asset_id']]), ('林', [shared[0]['asset_id']])]
    # Deleting 林's item unlinks only 林; 月's hard-linked copy in 角色卡/月 stays alive.
    before = client.get(f"/api/characters/{a['id']}").json['character']['updated_at']
    result = media_delete(client, [shared[0]['media_id']])
    assert len(result['characters']) == 1 and result['characters'][0]['name'] == '林'
    after = client.get(f"/api/characters/{a['id']}").json['character']
    assert [i['asset_id'] for i in after['images']] == [shared[1]['asset_id']] and after['images'][0]['position'] == 0
    assert after['updated_at'] > before
    assert [i['asset_id'] for i in client.get(f"/api/characters/{b['id']}").json['character']['images']] == [b_copy['asset_id']]
    assert client.get(b_copy['url']).data == png('red')
    # Deleting 月's copy unlinks 月 too.
    assert len(media_delete(client, [b_copy['media_id']])['characters']) == 1
    assert client.get(f"/api/characters/{b['id']}").json['character']['images'] == []
    # the canvas referenced 林's media directly: deleted -> 410, the other stays
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


def test_character_prop_kind_create_and_update(client):
    """V2-REAL-USE F11: character cards support 'character' (default) and 'prop' (物件) template kinds."""
    default_card = create(client, '林')
    assert default_card['kind'] == 'character'
    prop_card = client.post('/api/characters', json={'name': '青铜灯笼', 'description': '锈迹斑驳', 'kind': 'prop'}).json['character']
    assert prop_card['kind'] == 'prop' and prop_card['description'] == '锈迹斑驳'
    patched = client.patch(f"/api/characters/{prop_card['id']}", json={'kind': 'character'}).json['character']
    assert patched['kind'] == 'character'
    patched_back = client.patch(f"/api/characters/{prop_card['id']}", json={'kind': 'prop'}).json['character']
    assert patched_back['kind'] == 'prop'
    assert client.post('/api/characters', json={'name': '坏类型', 'kind': 'scene'}).status_code == 400
    assert client.patch(f"/api/characters/{prop_card['id']}", json={'kind': 'invalid'}).status_code == 400


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


# ---- CHAR-FOLDERS-20261122：角色卡专用系统文件夹、单素材移除回根目录、删除预览与同步删图 ----

def _register_generated_media(kind='image', raw=None, name=None):
    from pathlib import Path
    import media_library as media
    import storage
    tid = tasks.create_task(kind, 'gen prompt', {}, status='succeeded')
    directory = Path(storage.OUTPUT_DIR) / str(tid)
    directory.mkdir(parents=True, exist_ok=True)
    if kind == 'image':
        data = raw if raw is not None else png('cyan')
        fname = name or 'gen_img.png'
        mime = 'image/png'
    else:
        data = raw if raw is not None else wav(1.5)
        fname = name or 'gen_voice.wav'
        mime = 'audio/wav'
    path = directory / fname
    path.write_bytes(data)
    tasks.register_asset(tid, 'output_' + kind, str(path), mime)
    media_id = media.register_generated(tid, path, 'output_' + kind, name=fname)
    return tid, media_id, path


def test_character_folder_lifecycle_create_rename_and_slash_rejected(client):
    import media_library as media
    char_root_id = media.system_folder_id('characters')
    c1 = create(client, '林深')
    c2 = create(client, '苏月')
    custom = client.post('/api/canvas/media/folders', json={'title': '我的镜头'}).json['folder']

    folders = client.get('/api/canvas/media/folders').json['folders']
    by_id = {f['id']: f for f in folders}
    assert char_root_id in by_id
    assert by_id[char_root_id]['title'] == '角色卡'
    assert by_id[char_root_id]['system_key'] == 'characters'
    assert by_id[char_root_id]['parent_id'] is None
    assert by_id[char_root_id]['icon'] == 'character'
    # Pre-seeded user folder '角色' stays untouched alongside system folder '角色卡'.
    user_role_folder = next(f for f in folders if f['title'] == '角色' and f['system_key'] is None)
    assert user_role_folder['parent_id'] is None

    for ch in (c1, c2):
        sub = by_id[ch['folder_id']]
        assert sub['id'] == media.character_folder_id(ch['id'])
        assert sub['title'] == ch['name']
        assert sub['parent_id'] == char_root_id
        assert sub['system_key'] == f"character:{ch['id']}"
        assert sub['icon'] == 'character'

    # Ordering: fixed system folders -> character:* subfolders (by created_at, id) -> seeded defaults -> custom user folders.
    sys_keys = [f['system_key'] for f in folders if f['system_key'] is not None]
    assert sys_keys[:5] == ['generated', 'generated_image', 'generated_video', 'generated_audio', 'characters']
    assert sys_keys[5:] == [f"character:{c1['id']}", f"character:{c2['id']}"]
    non_sys_titles = [f['title'] for f in folders if f['system_key'] is None]
    assert non_sys_titles == ['音效', '角色', '场景', '物品', '风格', custom['title']]

    # Renaming character atomically renames its 角色卡/<name> subfolder.
    renamed = client.patch(f"/api/characters/{c1['id']}", json={'name': '林深改'}).json['character']
    assert renamed['folder_id'] == c1['folder_id']
    refreshed = {f['id']: f for f in client.get('/api/canvas/media/folders').json['folders']}
    assert refreshed[c1['folder_id']]['title'] == '林深改'

    # '/' and '\' rejected on create and rename.
    for bad in ('林/深', '林\\深'):
        r_create = client.post('/api/characters', json={'name': bad})
        assert r_create.status_code == 400 and '斜杠' in r_create.json['error']
        r_patch = client.patch(f"/api/characters/{c1['id']}", json={'name': bad})
        assert r_patch.status_code == 400 and '斜杠' in r_patch.json['error']


def test_character_media_placement_move_vs_hardlink_copy_and_idempotent_dedup(client):
    import os
    import media_library as media

    p, w = workflow()
    c1, c2 = create(client, '甲'), create(client, '乙')

    # 1) Direct uploads land in 角色卡/<name>.
    up_img = upload_images(client, c1['id'], 'red').json['images'][0]
    assert media_row(up_img['media_id'])['folder_id'] == c1['folder_id']
    up_voice = client.post(f"/api/characters/{c1['id']}/voice-audio",
                           data={'file': (io.BytesIO(wav(1.0)), 'v1.wav')}).json['voice']
    assert media_row(up_voice['media_id'])['folder_id'] == c1['folder_id']

    # 2) Adding from root and from a user folder moves in place (same media_id, canvas refs intact).
    root_img = media_upload(client, png('green'), 'from_root.png')
    user_folder = client.post('/api/canvas/media/folders', json={'title': '定妆'}).json['folder']
    uf_img = media_upload(client, png('blue'), 'from_uf.png', folder_id=user_folder['id'])
    from test_local_delete import doc_with_reference
    root_asset = {k: root_img[k] for k in ('id', 'name', 'mime_type', 'kind', 'size_bytes', 'url')}
    doc_with_reference(w, root_asset)

    r_root = client.post(f"/api/characters/{c1['id']}/images", json={'source': 'media', 'media_id': root_img['id']})
    assert r_root.status_code == 201 and r_root.json['images'][0]['media_id'] == root_img['id']
    assert media_row(root_img['id'])['folder_id'] == c1['folder_id']
    assert client.get(root_img['url']).data == png('green')

    r_uf = client.post(f"/api/characters/{c1['id']}/images", json={'source': 'media', 'media_id': uf_img['id']})
    assert r_uf.status_code == 201 and r_uf.json['images'][0]['media_id'] == uf_img['id']
    assert media_row(uf_img['id'])['folder_id'] == c1['folder_id']

    # 3) Adding from 生成历史 hard-link copies into 角色卡/<name> and survives permanent deletion of source task!
    gen_tid, gen_img_id, _ = _register_generated_media('image', png('yellow'), 'gen_y.png')
    gen_vtid, gen_aud_id, _ = _register_generated_media('audio', wav(2.0), 'gen_v.wav')

    r_gen = client.post(f"/api/characters/{c1['id']}/images", json={'source': 'media', 'media_id': gen_img_id})
    assert r_gen.status_code == 201
    char_gen_id = r_gen.json['images'][0]['media_id']
    assert char_gen_id != gen_img_id
    assert media_row(char_gen_id)['folder_id'] == c1['folder_id']
    assert media_row(gen_img_id)['folder_id'] == media.system_folder_id('generated_image')
    assert os.stat(media.media_path(media_row(char_gen_id))).st_ino == os.stat(media.media_path(media_row(gen_img_id))).st_ino

    # Idempotent: adding the same 生成历史 image again (by media_id or by re-upload) creates NO duplicate copy!
    before_count = media_count()
    r_gen_dup1 = client.post(f"/api/characters/{c1['id']}/images", json={'source': 'media', 'media_id': gen_img_id})
    assert r_gen_dup1.status_code == 201 and r_gen_dup1.json['images'][0]['media_id'] == char_gen_id
    r_gen_dup2 = client.post(f"/api/characters/{c1['id']}/images",
                             data={'file': (io.BytesIO(png('yellow')), 'dup_y.png')}, content_type='multipart/form-data')
    assert r_gen_dup2.status_code == 201 and r_gen_dup2.json['images'][0]['media_id'] == char_gen_id
    assert media_count() == before_count

    # Voice from 生成历史 also hard-link copies, and re-setting same 生成历史 voice is idempotent.
    r_gv = client.post(f"/api/characters/{c2['id']}/voice-audio", json={'source': 'media', 'media_id': gen_aud_id})
    assert r_gv.status_code == 201
    char_gv_id = r_gv.json['voice']['media_id']
    assert char_gv_id != gen_aud_id and media_row(char_gv_id)['folder_id'] == c2['folder_id']
    assert os.stat(media.media_path(media_row(char_gv_id))).st_ino == os.stat(media.media_path(media_row(gen_aud_id))).st_ino
    before_vcount = media_count()
    r_gv_dup = client.post(f"/api/characters/{c2['id']}/voice-audio", json={'source': 'media', 'media_id': gen_aud_id})
    assert r_gv_dup.status_code == 201 and r_gv_dup.json['voice']['media_id'] == char_gv_id
    assert media_count() == before_vcount

    # Permanently deleting both source tasks deletes 生成历史 originals (410) while character copies remain 200!
    tasks.move_tasks_to_trash([gen_tid, gen_vtid])
    assert client.delete(f'/api/tasks/{gen_tid}?permanent=1').json['media_deleted'] == 1
    assert client.delete(f'/api/tasks/{gen_vtid}?permanent=1').json['media_deleted'] == 1
    assert client.get(f'/api/canvas/media/{gen_img_id}').status_code == 410
    assert client.get(f'/api/canvas/media/{gen_aud_id}').status_code == 410
    assert client.get(f'/api/canvas/media/{char_gen_id}').data == png('yellow')
    assert client.get(f'/api/canvas/media/{char_gv_id}').data == wav(2.0)

    # 4) Adding an image from Character 1 to Character 2 hard-link copies into 角色卡/乙 without stealing from 角色卡/甲.
    r_cross = client.post(f"/api/characters/{c2['id']}/images", json={'source': 'media', 'media_id': up_img['media_id']})
    assert r_cross.status_code == 201
    c2_img_id = r_cross.json['images'][0]['media_id']
    assert c2_img_id != up_img['media_id']
    assert media_row(c2_img_id)['folder_id'] == c2['folder_id']
    assert media_row(up_img['media_id'])['folder_id'] == c1['folder_id']
    assert os.stat(media.media_path(media_row(c2_img_id))).st_ino == os.stat(media.media_path(media_row(up_img['media_id']))).st_ino

    # 5) Validation failure (MAX_IMAGES) never moves a root item out of root!
    c3 = create(client, '满员')
    assert upload_images(client, c3['id'], *COLORS[:8]).status_code == 201
    extra_root = media_upload(client, png((12, 34, 56)), 'stay_root.png')
    assert media_row(extra_root['id'])['folder_id'] is None
    assert client.post(f"/api/characters/{c3['id']}/images", json={'source': 'media', 'media_id': extra_root['id']}).status_code == 400
    assert media_row(extra_root['id'])['folder_id'] is None


def test_character_remove_single_image_replace_and_clear_voice_return_to_root(client):
    p, w = workflow()
    c = create(client, '林')
    imgs = upload_images(client, c['id'], 'red', 'blue').json['images']
    imported = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id']}).json['assets']

    # Removing a single image moves it back to library root, preserving media_id, file, and canvas refs.
    r_del = client.delete(f"/api/characters/{c['id']}/images/{imgs[0]['media_id']}")
    assert r_del.status_code == 200
    assert media_row(imgs[0]['media_id'])['folder_id'] is None
    assert media_row(imgs[1]['media_id'])['folder_id'] == c['folder_id']
    assert client.get(imported[0]['url']).data == png('red')

    # Replacing voice moves old voice back to root; new voice lands in 角色卡/<name>.
    v1 = client.post(f"/api/characters/{c['id']}/voice-audio", data={'file': (io.BytesIO(wav(1.0)), 'v1.wav')}).json['voice']
    assert media_row(v1['media_id'])['folder_id'] == c['folder_id']
    v2 = client.post(f"/api/characters/{c['id']}/voice-audio", data={'file': (io.BytesIO(wav(2.0)), 'v2.wav')}).json['voice']
    assert media_row(v1['media_id'])['folder_id'] is None
    assert media_row(v2['media_id'])['folder_id'] == c['folder_id']

    # Failed replacement (over 30s) leaves v2 in 角色卡/<name> and rolls back failed upload.
    before = media_count()
    assert client.post(f"/api/characters/{c['id']}/voice-audio", data={'file': (io.BytesIO(wav(31.0)), 'bad.wav')}).status_code == 400
    assert media_row(v2['media_id'])['folder_id'] == c['folder_id'] and media_count() == before

    # Clearing voice via PATCH moves v2 back to root.
    cleared = client.patch(f"/api/characters/{c['id']}", json={'voice': None})
    assert cleared.status_code == 200 and cleared.json['character']['voice'] is None
    assert media_row(v2['media_id'])['folder_id'] is None
    assert client.get('/api/canvas/media/' + v2['media_id']).data == wav(2.0)


def test_character_folders_reject_manual_folder_and_move_operations(client):
    import media_library as media

    char_root_id = media.system_folder_id('characters')
    c1, c2 = create(client, '林'), create(client, '月')
    c1_img = upload_images(client, c1['id'], 'red').json['images'][0]
    root_img = media_upload(client, png('green'), 'root.png')
    user_folder = client.post('/api/canvas/media/folders', json={'title': '普通'}).json['folder']

    # Manual upload into 角色卡 or 角色卡/<name> -> 409 folder_character_managed.
    for target in (char_root_id, c1['folder_id']):
        r = client.post('/api/canvas/media', data={'file': (io.BytesIO(png('blue')), 'x.png'), 'folder_id': target})
        assert r.status_code == 409 and r.json['code'] == 'folder_character_managed'

    # Manual move INTO 角色卡 or 角色卡/<name> -> 409 folder_character_managed.
    for target in (char_root_id, c1['folder_id']):
        r = client.post('/api/canvas/media/move', json={'ids': [root_img['id']], 'folder_id': target})
        assert r.status_code == 409 and r.json['code'] == 'folder_character_managed'
        assert media_row(root_img['id'])['folder_id'] is None

    # Manual move OUT of 角色卡/<name> (to root, user folder, other character, same character) -> 409 folder_character_managed.
    for target in (None, user_folder['id'], c2['folder_id'], c1['folder_id']):
        r = client.post('/api/canvas/media/move', json={'ids': [c1_img['media_id']], 'folder_id': target})
        assert r.status_code == 409 and r.json['code'] == 'folder_character_managed'
        assert media_row(c1_img['media_id'])['folder_id'] == c1['folder_id']

    # Mixed batch (root item + character item) is all-or-nothing: root item does not move!
    mixed = client.post('/api/canvas/media/move', json={'ids': [root_img['id'], c1_img['media_id']], 'folder_id': user_folder['id']})
    assert mixed.status_code == 409 and mixed.json['code'] == 'folder_character_managed'
    assert media_row(root_img['id'])['folder_id'] is None and media_row(c1_img['media_id'])['folder_id'] == c1['folder_id']

    # Manual rename / delete / subfolder-create / reparent-into on 角色卡 & 角色卡/<name> -> 409 folder_character_managed.
    for target in (char_root_id, c1['folder_id']):
        r_ren = client.patch('/api/canvas/media/folders/' + target, json={'title': '改名'})
        assert r_ren.status_code == 409 and r_ren.json['code'] == 'folder_character_managed'
        r_del = client.delete('/api/canvas/media/folders/' + target)
        assert r_del.status_code == 409 and r_del.json['code'] == 'folder_character_managed'
        r_sub = client.post('/api/canvas/media/folders', json={'title': '子目录', 'parent_id': target})
        assert r_sub.status_code == 409 and r_sub.json['code'] == 'folder_character_managed'
        r_reparent = client.patch('/api/canvas/media/folders/' + user_folder['id'], json={'parent_id': target})
        assert r_reparent.status_code == 409 and r_reparent.json['code'] == 'folder_character_managed'


def test_delete_character_preview_and_keep_vs_permanent_delete(client):
    import media_library as media
    from test_local_delete import doc_with_reference

    p, w = workflow()
    # Empty character preview
    empty_c = create(client, '空角色')
    ep = client.get(f"/api/characters/{empty_c['id']}/delete-preview")
    assert ep.status_code == 200 and ep.json['media_count'] == 0
    assert ep.json['folder_title'] == '角色卡 / 空角色'
    assert ep.json['preview'] == {
        'items': [], 'missing': [], 'affected_workflows': [],
        'characters': [], 'asset_groups': 0, 'media_groups': [], 'task_ids': [],
    }
    assert client.get('/api/characters/' + 'f' * 32 + '/delete-preview').status_code == 404

    # Character 1: default delete (delete_media=False) moves media to root and removes empty 角色卡/<name> folder.
    c1 = create(client, '保留素材')
    imgs1 = upload_images(client, c1['id'], 'red', 'blue').json['images']
    voice1 = client.post(f"/api/characters/{c1['id']}/voice-audio", data={'file': (io.BytesIO(wav(1.0)), 'v1.wav')}).json['voice']
    imported1 = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c1['id']}).json['assets']
    doc_with_reference(w, imported1[0])
    grp1 = client.post('/api/canvas/media/groups', json={'title': '角色组1', 'media_ids': [imgs1[0]['media_id']]}).json['group']

    prev1 = client.get(f"/api/characters/{c1['id']}/delete-preview").json
    assert prev1['character'] == {'id': c1['id'], 'name': '保留素材', 'folder_id': c1['folder_id']}
    assert prev1['folder_title'] == '角色卡 / 保留素材'
    assert prev1['media_count'] == 3
    assert {i['id'] for i in prev1['preview']['items']} == {imgs1[0]['media_id'], imgs1[1]['media_id'], voice1['media_id']}
    assert prev1['preview']['characters'] == []  # excludes self!
    assert prev1['preview']['affected_workflows'][0]['workflow_id'] == w
    assert prev1['preview']['media_groups'] == [{'id': grp1['id'], 'title': '角色组1'}]

    # Invalid delete_media values rejected with 400 without deleting.
    assert client.delete(f"/api/characters/{c1['id']}?delete_media=maybe").status_code == 400
    assert client.delete(f"/api/characters/{c1['id']}", json={'delete_media': 'yes'}).status_code == 400
    assert client.delete(f"/api/characters/{c1['id']}", json={'extra': True}).status_code == 400
    assert client.get(f"/api/characters/{c1['id']}").status_code == 200

    res1 = client.delete(f"/api/characters/{c1['id']}")
    assert res1.status_code == 200
    assert res1.json['references_removed'] == 3 and res1.json['media_moved_to_root'] == 3
    assert res1.json['deleted_media_ids'] == [] and res1.json['files_removed'] == 0
    for mid in (imgs1[0]['media_id'], imgs1[1]['media_id'], voice1['media_id']):
        assert media_row(mid)['folder_id'] is None
        assert client.get('/api/canvas/media/' + mid).status_code == 200
    assert c1['folder_id'] not in {f['id'] for f in client.get('/api/canvas/media/folders').json['folders']}

    # Character 2: permanent delete (?delete_media=1) deletes media + tombstones + canvas placeholders + folder!
    p2, w2 = workflow()
    c2 = create(client, '同步删图')
    imgs2 = upload_images(client, c2['id'], 'green', 'yellow').json['images']
    voice2 = client.post(f"/api/characters/{c2['id']}/voice-audio", data={'file': (io.BytesIO(wav(2.0)), 'v2.wav')}).json['voice']
    imported2 = client.post(f'/api/canvas/workflows/{w2}/character-assets', json={'character_id': c2['id']}).json['assets']
    before_wf = doc_with_reference(w2, imported2[0])
    grp2 = client.post('/api/canvas/media/groups', json={'title': '角色组2', 'media_ids': [imgs2[0]['media_id']]}).json['group']
    file_paths = [media.media_path(media_row(m)) for m in (imgs2[0]['media_id'], imgs2[1]['media_id'], voice2['media_id'])]

    res2 = client.delete(f"/api/characters/{c2['id']}?delete_media=1")
    assert res2.status_code == 200
    assert res2.json['references_removed'] == 3 and res2.json['media_moved_to_root'] == 0
    assert set(res2.json['deleted_media_ids']) == {imgs2[0]['media_id'], imgs2[1]['media_id'], voice2['media_id']}
    assert res2.json['files_removed'] == 3
    assert res2.json['affected_workflows'][0]['workflow_id'] == w2
    assert res2.json['media_groups'] == [{'id': grp2['id'], 'title': '角色组2'}]
    for fp in file_paths:
        assert not fp.exists()
    for mid in (imgs2[0]['media_id'], imgs2[1]['media_id'], voice2['media_id']):
        gone = client.get('/api/canvas/media/' + mid)
        assert gone.status_code == 410 and gone.json['code'] == 'media_deleted'
    after_wf = store.workflow(w2)
    assert after_wf['revision'] == before_wf['revision'] + 1
    nodes = {n['id']: n for n in after_wf['document']['nodes']}
    assert nodes['src']['asset']['id'] == imgs2[0]['media_id']  # placeholder kept
    assert nodes['gen']['referenceAssets'] == [] and nodes['gen']['referenceMentions'] == {}
    assert client.get('/api/canvas/media/groups/' + grp2['id']).json['group']['deleted_count'] == 1
    assert c2['folder_id'] not in {f['id'] for f in client.get('/api/canvas/media/folders').json['folders']}

    # Character 3: permanent delete via JSON body {'delete_media': True}
    c3 = create(client, 'JSON删图')
    img3 = upload_images(client, c3['id'], 'purple').json['images'][0]
    res3 = client.delete(f"/api/characters/{c3['id']}", json={'delete_media': True})
    assert res3.status_code == 200 and res3.json['deleted_media_ids'] == [img3['media_id']] and res3.json['files_removed'] == 1
    assert client.get('/api/canvas/media/' + img3['media_id']).status_code == 410


def test_delete_character_permanent_rollback_on_file_rename_failure(client, monkeypatch):
    import os
    import media_library as media
    from test_local_delete import doc_with_reference

    p, w = workflow()
    c = create(client, '回滚角色')
    imgs = upload_images(client, c['id'], 'red', 'blue').json['images']
    imported = client.post(f'/api/canvas/workflows/{w}/character-assets', json={'character_id': c['id']}).json['assets']
    before_wf = doc_with_reference(w, imported[0])
    paths = [media.media_path(media_row(i['media_id'])) for i in imgs]

    real_rename = os.rename
    calls = []

    def flaky_rename(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:
            raise OSError('synthetic rename failure')
        return real_rename(src, dst)

    monkeypatch.setattr(media.os, 'rename', flaky_rename)
    r = client.delete(f"/api/characters/{c['id']}?delete_media=1")
    assert r.status_code == 409
    monkeypatch.setattr(media.os, 'rename', real_rename)

    # Atomic rollback: character, folder, media rows, files, and canvas workflow all intact!
    assert client.get(f"/api/characters/{c['id']}").status_code == 200
    assert len(client.get(f"/api/characters/{c['id']}").json['character']['images']) == 2
    assert c['folder_id'] in {f['id'] for f in client.get('/api/canvas/media/folders').json['folders']}
    for i, fp in zip(imgs, paths):
        assert fp.exists() and media_row(i['media_id'])['folder_id'] == c['folder_id']
        assert client.get('/api/canvas/media/' + i['media_id']).status_code == 200
    assert tasks.get_db().execute('SELECT COUNT(*) FROM media_tombstones').fetchone()[0] == 0
    assert not any('.deleting-' in x.name for x in media.root().iterdir())
    assert store.workflow(w)['revision'] == before_wf['revision']


def test_startup_migration_ensure_character_folders(client):
    import os
    import media_library as media

    root_img = media_upload(client, png('red'), 'legacy_root.png')
    shared_img = media_upload(client, png('green'), 'legacy_shared.png')
    _, gen_img_id, _ = _register_generated_media('image', png('blue'), 'legacy_gen.png')
    stray_img = media_upload(client, png('orange'), 'stray.png')

    cid_a = 'a' * 32
    cid_b = 'b' * 32
    dead_empty_fid = media.character_folder_id('c' * 32)
    dead_nonempty_fid = media.character_folder_id('d' * 32)
    char_root_id = media.system_folder_id('characters')
    now = tasks.utcnow()

    # Seed legacy rows bypassing create_character / add_images so no character:* folders exist yet.
    db = tasks.get_db()
    db.execute("INSERT INTO characters VALUES (?, '旧甲', '旧甲', '', 'character', ?, ?)", (cid_a, now, now))
    db.execute("INSERT INTO characters VALUES (?, '旧乙', '旧乙', '', 'character', ?, ?)", (cid_b, now, now))
    db.execute("INSERT INTO character_media VALUES (?, ?, 'image', 0, 20, 20, NULL, ?)", (cid_a, root_img['id'], now))
    db.execute("INSERT INTO character_media VALUES (?, ?, 'image', 1, 20, 20, NULL, ?)", (cid_a, gen_img_id, now))
    db.execute("INSERT INTO character_media VALUES (?, ?, 'image', 2, 20, 20, NULL, ?)", (cid_a, shared_img['id'], now))
    db.execute("INSERT INTO character_media VALUES (?, ?, 'image', 0, 20, 20, NULL, ?)", (cid_b, shared_img['id'], now))
    # Orphan character:* folders (one empty, one still holding a media row).
    db.execute('INSERT INTO media_folders VALUES (?,?,?,?,?,?,?)',
               (dead_empty_fid, '已删空', char_root_id, 'character:' + 'c' * 32, 'character', now, now))
    db.execute('INSERT INTO media_folders VALUES (?,?,?,?,?,?,?)',
               (dead_nonempty_fid, '已删非空', char_root_id, 'character:' + 'd' * 32, 'character', now, now))
    db.execute('UPDATE media SET folder_id=? WHERE id=?', (dead_nonempty_fid, stray_img['id']))
    db.commit()

    # Run startup migration twice (verify idempotency).
    chars.init_characters_db()
    first_a = chars.get_character(cid_a)
    first_b = chars.get_character(cid_b)
    first_count = media_count()
    chars.init_characters_db()
    assert chars.get_character(cid_a) == first_a
    assert chars.get_character(cid_b) == first_b
    assert media_count() == first_count

    folders = {f['id']: f for f in client.get('/api/canvas/media/folders').json['folders']}
    fid_a, fid_b = media.character_folder_id(cid_a), media.character_folder_id(cid_b)
    assert folders[fid_a]['title'] == '旧甲' and folders[fid_a]['parent_id'] == char_root_id
    assert folders[fid_b]['title'] == '旧乙' and folders[fid_b]['parent_id'] == char_root_id
    assert dead_empty_fid not in folders
    assert dead_nonempty_fid in folders  # never deletes a non-empty orphan folder

    # Root image moved in place into 角色卡/旧甲; 生成历史 image hard-link copied & rebound while original stays.
    a_ids = [i['media_id'] for i in first_a['images']]
    b_ids = [i['media_id'] for i in first_b['images']]
    assert a_ids[0] == root_img['id'] and media_row(root_img['id'])['folder_id'] == fid_a
    assert a_ids[1] != gen_img_id and media_row(a_ids[1])['folder_id'] == fid_a
    assert media_row(gen_img_id)['folder_id'] == media.system_folder_id('generated_image')
    assert os.stat(media.media_path(media_row(a_ids[1]))).st_ino == os.stat(media.media_path(media_row(gen_img_id))).st_ino
    # Shared image split cleanly: A and B each own an independent hard-linked item in their own folder.
    assert a_ids[2] != b_ids[0]
    assert media_row(a_ids[2])['folder_id'] == fid_a and media_row(b_ids[0])['folder_id'] == fid_b
    assert os.stat(media.media_path(media_row(a_ids[2]))).st_ino == os.stat(media.media_path(media_row(b_ids[0]))).st_ino


def test_post_commit_get_character_error_keeps_committed_hardlink_files(client, monkeypatch):
    """QA D1 regression: post-commit failure in get_character() must never unlink committed hard-linked files."""
    import media_library as media

    c = create(client, '提交保护')
    _, gen_img_id, _ = _register_generated_media('image', png('cyan'), 'gen_img_d1.png')
    _, gen_aud_id, _ = _register_generated_media('audio', wav(1.5), 'gen_aud_d1.wav')

    real_get = chars.get_character

    def boom(_character_id):
        raise RuntimeError('post-commit read failure')

    # 1) add_images() commits hard-link copy from 生成历史, then get_character() raises
    monkeypatch.setattr(chars, 'get_character', boom)
    with pytest.raises(RuntimeError, match='post-commit read failure'):
        chars.add_images(c['id'], data={'source': 'media', 'media_id': gen_img_id})
    monkeypatch.setattr(chars, 'get_character', real_get)

    after_img = chars.get_character(c['id'])
    assert len(after_img['images']) == 1
    copied_img_id = after_img['images'][0]['media_id']
    assert copied_img_id != gen_img_id
    assert media_row(copied_img_id)['folder_id'] == c['folder_id']
    assert media.media_path(media_row(copied_img_id)).is_file()
    assert client.get('/api/canvas/media/' + copied_img_id).data == png('cyan')

    # 2) set_voice() commits hard-link copy from 生成历史, then get_character() raises
    monkeypatch.setattr(chars, 'get_character', boom)
    with pytest.raises(RuntimeError, match='post-commit read failure'):
        chars.set_voice(c['id'], data={'source': 'media', 'media_id': gen_aud_id})
    monkeypatch.setattr(chars, 'get_character', real_get)

    after_voice = chars.get_character(c['id'])
    assert after_voice['voice'] is not None
    copied_aud_id = after_voice['voice']['media_id']
    assert copied_aud_id != gen_aud_id
    assert media_row(copied_aud_id)['folder_id'] == c['folder_id']
    assert media.media_path(media_row(copied_aud_id)).is_file()
    assert client.get('/api/canvas/media/' + copied_aud_id).data == wav(1.5)


def test_startup_migration_skips_missing_legacy_file_without_crashing(client, caplog):
    """QA D2 regression: a missing legacy 生成历史 file on disk must be skipped with warning, never crashing boot."""
    import logging
    import media_library as media

    healthy_root = media_upload(client, png('red'), 'healthy_root.png')
    _, healthy_gen_id, _ = _register_generated_media('image', png('green'), 'healthy_gen.png')
    _, broken_gen_id, _ = _register_generated_media('image', png('blue'), 'broken_gen.png')

    # Delete the broken 生成历史 item's physical media file from disk before migration!
    broken_file = media.media_path(media_row(broken_gen_id))
    broken_file.unlink()
    assert not broken_file.exists()

    cid = 'e' * 32
    now = tasks.utcnow()
    db = tasks.get_db()
    db.execute("INSERT INTO characters VALUES (?, '残缺迁移', '残缺迁移', '', 'character', ?, ?)", (cid, now, now))
    db.execute("INSERT INTO character_media VALUES (?, ?, 'image', 0, 20, 20, NULL, ?)", (cid, broken_gen_id, now))
    db.execute("INSERT INTO character_media VALUES (?, ?, 'image', 1, 20, 20, NULL, ?)", (cid, healthy_root['id'], now))
    db.execute("INSERT INTO character_media VALUES (?, ?, 'image', 2, 20, 20, NULL, ?)", (cid, healthy_gen_id, now))
    db.commit()

    with caplog.at_level(logging.WARNING, logger='characters'):
        chars.init_characters_db()

    assert any('character_folder_migration_skip' in rec.message and broken_gen_id in rec.message for rec in caplog.records)
    fid = media.character_folder_id(cid)
    migrated = chars.get_character(cid)
    ids = [i['media_id'] for i in migrated['images']]
    # Broken row skipped safely; healthy root moved in place; healthy 生成历史 hard-link copied and rebound!
    assert ids[0] == broken_gen_id
    assert ids[1] == healthy_root['id'] and media_row(healthy_root['id'])['folder_id'] == fid
    assert ids[2] != healthy_gen_id and media_row(ids[2])['folder_id'] == fid
    assert media.media_path(media_row(ids[2])).is_file()
    assert client.get('/api/canvas/media/' + ids[2]).data == png('green')
