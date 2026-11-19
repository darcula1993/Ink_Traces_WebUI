"""GEN-RESULT-LIFECYCLE-20261119 plan A: canvas references submitted by library id, hard-link snapshots.

Acceptance 6: the Provider request (reference bytes, order, fields) equals the old multipart upload.
Acceptance 7: deleting the library item after submission does not affect the queued task / retry.
Acceptance 8: unknown / deleted / trashed / wrongly typed ids -> 400, no task, no estimate.
Acceptance 9: task-side reference files share the library file's inode (same file system).
"""
import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image

import app as application
import media_library as media
import storage
import tasks as task_db
import worker
from billing_support import billing_env, posts, run_until_idle  # noqa: F401  (fixtures)

ARK_OK = {'data': [{'url': 'https://media.invalid/generated.png', 'output_format': 'png'}]}


def client():
    return application.app.test_client()


def normalized_png(color):
    """PNG bytes exactly as the image route's normalization writes them (so linking applies)."""
    path = Path(storage.OUTPUT_DIR) / f'norm-{color}.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.save_normalized_image(Image.new('RGB', (4, 3), color), str(path))
    return path.read_bytes()


def foreign_png(color):
    """A PNG the normalization re-encodes (different bytes): only the normalized copy can be kept."""
    buffer = io.BytesIO()
    Image.new('RGB', (4, 3), color).save(buffer, format='PNG', compress_level=0)
    return buffer.getvalue()


def upload(data, name):
    r = client().post('/api/canvas/media', data={'file': (io.BytesIO(data), name)})
    assert r.status_code in (200, 201), r.json
    return r.json['media']


FIELDS = {'prompt': 'p', 'provider': 'ark', 'aspect_ratio': '1:1', 'resolution': '2K'}


def submit_files(items):
    data = dict(FIELDS)
    data['images'] = [(io.BytesIO(b), name, 'image/png') for b, name in items]
    return client().post('/api/generate', data=data, content_type='multipart/form-data')


def submit_ids(entries, **extra):
    data = {**FIELDS, 'reference_media': json.dumps(entries, ensure_ascii=False), **extra}
    return client().post('/api/generate', data=data, content_type='multipart/form-data')


def inputs(task_id):
    return [a['path'] for a in task_db.list_assets(task_id) if a['kind'] == 'input_image']


class Bodies:
    def __init__(self, posts):
        self.bodies = []
        posts.install(self.record)

    def record(self, url, kwargs):
        self.bodies.append({'url': url, 'json': kwargs.get('json'), 'data': kwargs.get('data')})
        import requests
        raise requests.exceptions.ConnectTimeout('captured')  # "certainly not sent": a known failure, retry allowed


def test_image_request_is_identical_and_snapshots_are_hard_links(billing_env, posts):
    bodies = Bodies(posts)
    same, other = normalized_png('red'), foreign_png('blue')
    a, b = upload(same, '甲.png'), upload(other, '乙.png')
    old = submit_files([(same, '甲.png'), (other, '乙.png')])
    new = submit_ids([{'field': 'images', 'id': a['id'], 'filename': '甲.png'},
                      {'field': 'images', 'id': b['id'], 'filename': '乙.png'}])
    assert old.status_code == 202 and new.status_code == 202, (old.json, new.json)
    old_id, new_id = old.json['task_id'], new.json['task_id']
    old_task, new_task = task_db.get_task(old_id), task_db.get_task(new_id)
    strip = lambda params: {**params, 'cost_estimate': {k: v for k, v in params['cost_estimate'].items() if k != 'computed_at'}}
    assert strip(old_task['params']) == strip(new_task['params']) and old_task['prompt'] == new_task['prompt']
    read = lambda tid: [Path(p).read_bytes() for p in inputs(tid)]
    assert read(old_id) == read(new_id) and len(read(new_id)) == 2  # bytes and order
    # 9: the normalization left the first image unchanged -> hard link; the second keeps the normalized copy.
    first, second = inputs(new_id)
    library_first = media.media_path(media.get_media(a['id']))
    assert os.stat(first).st_ino == os.stat(library_first).st_ino
    assert os.stat(second).st_ino != os.stat(media.media_path(media.get_media(b['id']))).st_ino
    # 7: the library items are deleted before the worker runs; the task uses its snapshot.
    assert client().post('/api/canvas/media/delete', json={'ids': [a['id'], b['id']]}).json['files_removed'] == 2
    runner = worker.Worker()
    run_until_idle(runner)
    assert len(bodies.bodies) == 2 and bodies.bodies[0]['json']
    assert bodies.bodies[0] == bodies.bodies[1], 'old upload and id submission sent the same request body'
    assert Path(first).exists() and Path(first).read_bytes() == same


def test_retry_links_the_snapshot_and_sends_the_same_request(billing_env, posts):
    bodies = Bodies(posts)
    same = normalized_png('green')
    item = upload(same, 'g.png')
    task_id = submit_ids([{'field': 'images', 'id': item['id'], 'filename': 'g.png'}]).json['task_id']
    run_until_idle(worker.Worker())
    assert task_db.get_task(task_id)['status'] == 'failed'
    client().post('/api/canvas/media/delete', json={'ids': [item['id']]})
    retry = client().post(f'/api/tasks/{task_id}/retry')
    assert retry.status_code in (200, 201, 202), retry.json
    retry_id = retry.json.get('task_id') or retry.json.get('db_task_id') or retry.json['task']['id']
    assert os.stat(inputs(retry_id)[0]).st_ino == os.stat(inputs(task_id)[0]).st_ino
    run_until_idle(worker.Worker())
    assert len(bodies.bodies) == 2 and bodies.bodies[0] == bodies.bodies[1]


@pytest.mark.parametrize('case', ['unknown', 'deleted', 'trashed', 'kind', 'bad_json', 'bad_field'])
def test_invalid_reference_ids_are_refused_before_any_task(billing_env, case):
    image = upload(normalized_png('white'), 'w.png')
    entries = [{'field': 'images', 'id': image['id'], 'filename': 'w.png'}]
    if case == 'unknown':
        entries[0]['id'] = 'f' * 32
    elif case == 'deleted':
        client().post('/api/canvas/media/delete', json={'ids': [image['id']]})
    elif case == 'trashed':
        tid = task_db.create_task('image', 'p', {}, status='succeeded')
        directory = Path(storage.OUTPUT_DIR) / 'image' / str(tid)
        directory.mkdir(parents=True)
        out = directory / 'image_0.png'
        out.write_bytes(foreign_png('black'))
        task_db.register_asset(tid, 'output_image', str(out), 'image/png')
        entries[0]['id'] = media.register_generated(tid, out, 'image')
        task_db.move_tasks_to_trash([tid])
    elif case == 'kind':
        entries[0]['field'] = 'ref_videos'
    before = task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    if case == 'bad_json':
        r = client().post('/api/generate', data={**FIELDS, 'reference_media': '[{'}, content_type='multipart/form-data')
    elif case == 'bad_field':
        r = submit_ids([{'field': 'secret', 'id': image['id'], 'filename': 'w.png'}])
    else:
        r = submit_ids(entries)
    assert r.status_code == 400, r.json
    code = {'unknown': 'media_not_found', 'deleted': 'media_deleted', 'trashed': 'media_trashed',
            'kind': 'reference_kind_mismatch'}.get(case, 'invalid_reference')
    assert r.json['code'] == code and r.json['error']
    assert task_db.get_db().execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == before


def test_files_and_ids_can_be_combined_and_order_within_a_field_is_kept(billing_env):
    first, second = normalized_png('red'), normalized_png('blue')
    item = upload(second, 'b.png')
    data = {**FIELDS, 'images': [(io.BytesIO(first), 'a.png', 'image/png')],
            'reference_media': json.dumps([{'field': 'images', 'id': item['id'], 'filename': 'b.png'}])}
    r = client().post('/api/generate', data=data, content_type='multipart/form-data')
    assert r.status_code == 202, r.json
    paths = inputs(r.json['task_id'])
    assert [Path(p).read_bytes() for p in paths] == [first, second]
    assert os.stat(paths[1]).st_ino == os.stat(media.media_path(media.get_media(item['id']))).st_ino


def test_request_size_limit_still_counts_references(billing_env, monkeypatch):
    noise = Image.frombytes('RGB', (200, 200), os.urandom(200 * 200 * 3))
    buffer = io.BytesIO()
    noise.save(buffer, format='PNG')
    item = upload(buffer.getvalue(), 'r.png')
    monkeypatch.setitem(application.app.config, 'MAX_CONTENT_LENGTH', 50000)
    r = submit_ids([{'field': 'images', 'id': item['id'], 'filename': 'r.png'}])
    assert r.status_code == 413


def wav_bytes(tone):
    import wave
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(bytes([tone, 0]) * 800)
    return buffer.getvalue()


def test_cupsy_audio_references_by_id_match_uploads_and_link_provider_assets(monkeypatch):
    from test_canvas_audio_params import audio_canvas, configure
    configure(monkeypatch)
    one, two = wav_bytes(3), wav_bytes(9)
    a, b = upload(one, 'one.wav'), upload(two, 'two.wav')
    workflow = audio_canvas()
    base = {'prompt': 'line', 'canvas_workflow_id': workflow['id'], 'canvas_node_id': 'a', 'provider': 'cupsy',
            'model': 'seed-audio-1.0', 'output_format': 'mp3', 'sample_rate': '48000', 'enable_subtitle': 'true',
            'reference_mode': 'audio', 'canvas_workflow_revision': str(workflow['revision'])}
    c = client()
    old = c.post('/api/audio/generate', data={**base, 'references': [(io.BytesIO(one), 'one.wav', 'audio/wav'), (io.BytesIO(two), 'two.wav', 'audio/wav')]},
                 content_type='multipart/form-data')
    new = c.post('/api/audio/generate', data={**base, 'reference_media': json.dumps([
        {'field': 'references', 'id': a['id'], 'filename': 'one.wav'}, {'field': 'references', 'id': b['id'], 'filename': 'two.wav'}])},
        content_type='multipart/form-data')
    assert old.status_code == 202 and new.status_code == 202, (old.json, new.json)
    view = lambda tid: [(x['role'], x['position'], x['kind'], x['original_name'], x['mime_type'], x['sha256'], Path(x['local_path']).read_bytes())
                        for x in task_db.list_task_provider_assets(tid)]
    assert view(old.json['task_id']) == view(new.json['task_id'])
    assert task_db.get_task(old.json['task_id'])['params'] == task_db.get_task(new.json['task_id'])['params']
    for item, media_item in zip(task_db.list_task_provider_assets(new.json['task_id']), (a, b)):
        assert os.stat(item['local_path']).st_ino == os.stat(media.media_path(media.get_media(media_item['id']))).st_ino
