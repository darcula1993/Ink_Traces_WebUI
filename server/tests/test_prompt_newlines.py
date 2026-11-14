"""CHARACTER-LIBRARY-20261114 D1: multipart prompts arrive as CRLF; every generation entry stores
and forwards LF so the mock Provider sees the same text as the JSON path."""
import io

import pytest

import app as application
import tasks as task_db
from PIL import Image

from test_generation import FakeResponse, _png_bytes


class Download(FakeResponse):
    def raise_for_status(self):
        return None


def _ref_png():
    buffer = io.BytesIO()
    Image.new('RGB', (320, 320), (200, 40, 40)).save(buffer, format='PNG')
    return buffer.getvalue()

RAW = '【人物】\r\n林对应@图片1。\r\n\r\n旧式\r回车\n已是LF'
EXPECTED = '【人物】\n林对应@图片1。\n\n旧式\n回车\n已是LF'


def post(client, url, body, form, files=None):
    if not form:
        return client.post(url, json=body)
    data = {key: str(value).lower() if type(value) is bool else str(value) for key, value in body.items()}
    data.update(files or {})
    return client.post(url, data=data, content_type='multipart/form-data')


def test_normalize_newlines_helper():
    from request_utils import normalize_newlines
    assert normalize_newlines(RAW) == EXPECTED
    assert normalize_newlines('\r\r\n\n') == '\n\n\n'
    assert normalize_newlines(None) is None


@pytest.mark.parametrize('form', [False, True])
def test_ark_image_prompt_is_lf(monkeypatch, form):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'synthetic', 'endpoint': 'https://provider.invalid', 'model': 'test-model',
    })
    observed = []
    monkeypatch.setattr(application.HTTP, 'post', lambda _url, **k: observed.append(k['json']) or FakeResponse(
        payload={'data': [{'url': 'https://media.invalid/out.png', 'output_format': 'png'}]}))
    monkeypatch.setattr(application.HTTP, 'get', lambda *_a, **_k: Download(
        content=_png_bytes(), headers={'Content-Type': 'image/png'}))
    client = application.app.test_client()
    response = post(client, '/api/generate', {'provider': 'ark', 'prompt': RAW, 'aspect_ratio': '1:1', 'resolution': '2K'}, form)
    assert response.status_code in (200, 202), response.get_json()
    task_id = response.get_json()['task_id']
    assert task_db.get_task(task_id)['prompt'] == EXPECTED
    _payload, status = application.execute_image_task(task_id)
    assert status == 200, _payload
    assert observed and observed[-1]['prompt'] == EXPECTED


@pytest.mark.parametrize('form', [False, True])
def test_ark_video_prompt_is_lf(monkeypatch, form):
    monkeypatch.setattr(application, 'ARK_VIDEO_CONFIG', {
        'api_key': 'synthetic', 'endpoint': 'https://ark.invalid', 'model': 'endpoint-20', 'seedance_2_5_model': 'endpoint-25',
    })
    sent = []
    monkeypatch.setattr(application.HTTP, 'post', lambda _url, **k: sent.append(k['json']) or FakeResponse(
        payload={'id': 'synthetic-video', 'status': 'queued'}))
    client = application.app.test_client()
    body = {'provider': 'ark', 'model': 'seedance-2.5', 'video_mode': 'reference', 'prompt': RAW}
    files = {'ref_images': (io.BytesIO(_ref_png()), 'ref.png', 'image/png')}
    response = post(client, '/api/video/generate', body, form, files)
    assert response.status_code == 200, response.get_json()
    assert task_db.get_task(response.get_json()['db_task_id'])['prompt'] == EXPECTED
    assert sent[-1]['content'][0] == {'type': 'text', 'text': EXPECTED}


@pytest.mark.parametrize('form', [False, True])
def test_cupsy_audio_prompt_is_lf(monkeypatch, form):
    monkeypatch.setattr(application, 'CUPSY_VIDEO_CONFIG', {
        'api_key': 'synthetic', 'endpoint': 'https://cupsy.invalid', 'model': 'seedance-2.5', 'source_base_url': 'https://studio.invalid',
    })
    sent = []
    monkeypatch.setattr(application.HTTP, 'post', lambda _url, **k: sent.append(k['json']) or FakeResponse(
        status_code=202, payload={'id': 'synthetic-audio', 'status': 'queued'}))
    client = application.app.test_client()
    response = post(client, '/api/audio/generate', {'prompt': RAW}, form,
                    {'unused': (io.BytesIO(b'x'), 'unused.txt', 'text/plain')})
    assert response.status_code == 202, response.get_json()
    task_id = response.get_json()['task_id']
    assert task_db.get_task(task_id)['prompt'] == EXPECTED
    application.poll_audio_task_once(task_id)
    assert sent and sent[-1]['text_prompt'] == EXPECTED


@pytest.mark.parametrize('form', [False, True])
def test_cupsy_video_queued_prompt_is_lf(monkeypatch, form):
    monkeypatch.setattr(application, 'CUPSY_VIDEO_CONFIG', {
        'api_key': 'synthetic', 'endpoint': 'https://cupsy.invalid', 'model': 'seedance-2.5', 'source_base_url': 'https://studio.invalid',
    })
    monkeypatch.setattr(application.HTTP, 'post', lambda *_a, **_k: pytest.fail('queue path must not call the Provider'))
    client = application.app.test_client()
    body = {'provider': 'cupsy', 'model': 'seedance-2.5', 'video_mode': 'reference', 'prompt': RAW}
    response = post(client, '/api/video/generate', body, form)
    assert response.status_code == 202, response.get_json()
    assert task_db.get_task(response.get_json()['db_task_id'])['prompt'] == EXPECTED
