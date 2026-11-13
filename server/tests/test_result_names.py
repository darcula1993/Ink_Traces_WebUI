from pathlib import Path
import app as application
import canvas_store as store
import tasks
import storage
from result_names import clean_result_name, result_display_name
from test_canvas_library_folders import image_bytes


def make_task(params, status='succeeded', kind='image', count=2):
    tid = tasks.create_task(kind, 'p', params, status=status)
    directory = Path(storage.OUTPUT_DIR) / str(tid)
    directory.mkdir(parents=True)
    tasks.update_task(tid, output_dir=str(directory))
    for i in range(count):
        path = directory / f'image_{i}.png'
        path.write_bytes(image_bytes('red'))
        tasks.register_asset(tid, 'output_image', str(path), 'image/png')
    return tid


def test_sanitize_and_names():
    assert clean_result_name('铁门/首帧\\..\x00:*') == '铁门 首帧'
    assert len(clean_result_name('长' * 300)) == 80
    assert result_display_name('铁门首帧', 3105, 'image_0.png') == '铁门首帧_3105.png'
    assert result_display_name('铁门首帧', 3105, 'image_1.png') == '铁门首帧_3105_2.png'
    assert result_display_name('n', 7, 'video.mp4') == 'n_7.mp4'
    assert result_display_name('n', 7, 'audio.mp3') == 'n_7.mp3'
    assert result_display_name('', 7, 'video.mp4') is None


def test_request_result_name_stored_and_used_everywhere():
    client = application.app.test_client()
    p = store.create_project('p')['id']
    w = store.create_workflow(p, 'c')['id']
    with application.app.test_request_context('/', method='POST', json={'canvas_workflow_id': w, 'result_name': '铁门/首帧'}):
        tid = tasks.create_task('image', 'p', {}, status='succeeded')
    assert tasks.get_task(tid)['params']['result_name'] == '铁门 首帧'
    directory = Path(storage.OUTPUT_DIR) / str(tid)
    directory.mkdir(parents=True)
    tasks.update_task(tid, output_dir=str(directory))
    for i in range(2):
        path = directory / f'image_{i}.png'
        path.write_bytes(image_bytes(['red', 'blue'][i]))
        tasks.register_asset(tid, 'output_image', str(path), 'image/png')
    # library listing
    items = client.get('/api/canvas/library/items', query_string={'project_id': p, 'scope': 'project', 'source': 'generated'}).json['items']
    assert sorted(i['asset']['name'] for i in items) == [f'铁门 首帧_{tid}.png', f'铁门 首帧_{tid}_2.png']
    # catalog download
    key = items[0]['key']
    r = client.get(f'/api/canvas/library/items/{key}/download')
    assert 'filename*=UTF-8' in r.headers['Content-Disposition']
    # cross-canvas import
    w2 = store.create_workflow(p, 'c2')['id']
    r = client.post(f'/api/canvas/workflows/{w2}/library-references', json={'items': [i['selection'] for i in items]})
    assert sorted(a['name'] for a in r.json['assets']) == [f'铁门 首帧_{tid}.png', f'铁门 首帧_{tid}_2.png']
    r = client.post(f'/api/canvas/workflows/{w2}/task-results', json={'task_id': tid})
    if r.status_code == 200:
        assert sorted(a['name'] for a in r.json['assets']) == [f'铁门 首帧_{tid}.png', f'铁门 首帧_{tid}_2.png']
    # task download + raw download; disk names untouched
    r = client.get(f'/api/tasks/{tid}/download/image_1.png')
    assert r.status_code == 200 and 'filename*=UTF-8' in r.headers['Content-Disposition']
    assert f'_{tid}_2.png' in r.headers['Content-Disposition']
    assert (directory / 'image_1.png').is_file()


def test_legacy_task_keeps_old_names():
    tid = make_task({})
    task = tasks.get_task(tid)
    import task_media
    assert task_media._task_download_name(task, 'image_1.png').startswith(f'ink-traces-image-task-{tid}-')
    assert task_media._task_download_name(task, 'image_1.png').endswith('output-02.png')
