"""COST-LEDGER-20261114: estimate-only project cost ledger (never actual charges)."""
from datetime import datetime
import json
from pathlib import Path
import subprocess

import pytest

import app as application
import canvas_store as store
import cost_estimate
import storage
import tasks as task_db
from billing_support import (  # noqa: F401  (fixtures)
    ACCEPTED_ID, Response, billing_env, posts, submit_video,
)

CASES = json.loads((Path(__file__).parent / 'data' / 'cost_estimate_parity.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=[case['name'] for case in CASES])
def test_estimate_matches_client_formula(case):
    estimate = cost_estimate.estimate_video_cost(
        model=case['model'], provider=case['provider'], resolution=case['resolution'], ratio=case['ratio'],
        duration=case['duration'], fast=case['fast'], reference_video_durations=case['ref'],
        now=datetime.fromisoformat(case['now'].replace('Z', '+00:00')))
    expected = case['expected']
    assert estimate['minimum_cost'] == pytest.approx(expected['minimumCost'], rel=1e-12)
    assert estimate['maximum_cost'] == pytest.approx(expected['maximumCost'], rel=1e-12)
    assert estimate['minimum_tokens'] == pytest.approx(expected['minimumTokens'])
    assert estimate['unit_price'] == pytest.approx(expected['unitPrice'])
    assert (estimate['width'], estimate['height']) == (expected['width'], expected['height'])
    assert estimate['input_video_seconds'] == expected['inputVideoSeconds']


def _ledger(**query):
    response = application.app.test_client().get('/api/cost-ledger', query_string=query)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _video_params(**extra):
    return {'model': 'seedance-2.0', 'ratio': '16:9', 'duration': 5, 'resolution': '720p',
            'fast': False, 'video_mode': 'reference', **extra}


def _canvas_task(workflow_id, node_id, kind='video', params=None, status='succeeded', provider='ark', result=None):
    with application.app.test_request_context('/', method='POST', json={
            'canvas_workflow_id': workflow_id, 'canvas_node_id': node_id}):
        task_id = task_db.create_task(kind, 'p', params if params is not None else _video_params(),
                                      provider=provider, status=status)
    if result is not None:
        task_db.update_task(task_id, result=result)
    return task_id


def _no_provider_calls(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('ledger must not call a Provider')
    monkeypatch.setattr(application.HTTP, 'post', forbidden)
    monkeypatch.setattr(application.HTTP, 'get', forbidden)


def test_ledger_groups_project_workflow_node_type_and_date(monkeypatch):
    _no_provider_calls(monkeypatch)
    project = store.create_project('短剧A')
    workflow = store.create_workflow(project['id'], '第一集')
    video = _canvas_task(workflow['id'], 'v1')
    image = _canvas_task(workflow['id'], 'i1', kind='image', params={'aspect_ratio': '1:1'})
    audio = _canvas_task(workflow['id'], 'a1', kind='audio', params={'model': 'x'}, provider='cupsy')
    legacy = task_db.create_task('video', 'p', _video_params(), provider='ark', status='succeeded')
    legacy_image = task_db.create_task('image', 'p', {}, provider='ark', status='succeeded')
    snapshot = lambda: [tuple(row) for row in task_db.get_db().execute('SELECT * FROM tasks ORDER BY id')]
    before = snapshot()

    data = _ledger()
    assert snapshot() == before  # read-only: no snapshot writes on GET
    assert data['disclaimer'] == '估算，非实际扣费'
    assert 'actual' not in json.dumps(data).lower()
    tasks = {item['id']: item for item in data['tasks']}
    assert tasks[video]['estimate_usd'] == {'min': pytest.approx(0.756), 'max': pytest.approx(0.756)}
    assert tasks[video]['node_id'] == 'v1' and tasks[video]['project_id'] == project['id']
    for task_id in (image, audio, legacy_image):
        assert tasks[task_id]['estimate_usd'] is None
        assert tasks[task_id]['unknown_reason'] == 'no_price_data'
    assert tasks[legacy]['project_id'] == '__unassigned__'

    totals = data['totals']['billable']
    assert totals['known_count'] == 2 and totals['unknown_count'] == 3
    assert totals['known_usd_min'] == pytest.approx(0.756 * 2)

    projects = {item['id']: item for item in data['projects']}
    assert projects['__unassigned__']['title'].startswith('未归属项目')
    canvas = projects[project['id']]
    assert canvas['title'] == '短剧A'
    [wf] = canvas['workflows']
    assert wf['title'] == '第一集'
    assert {node['node_id'] for node in wf['nodes']} == {'v1', 'i1', 'a1'}
    assert canvas['totals']['billable']['known_usd_min'] == pytest.approx(0.756)
    assert canvas['totals']['billable']['unknown_count'] == 2
    assert {item['type'] for item in data['types']} == {'video', 'image', 'audio'}
    assert len(data['dates']) == 1

    only = _ledger(project_id=project['id'])
    assert {item['id'] for item in only['tasks']} == {video, image, audio}
    assert {item['id'] for item in _ledger(project_id='__unassigned__')['tasks']} == {legacy, legacy_image}
    assert {item['id'] for item in _ledger(workflow_id=workflow['id'])['tasks']} == {video, image, audio}


def test_status_buckets_never_merge_into_billable_total():
    project = store.create_project('p')
    workflow = store.create_workflow(project['id'], 'w')
    ok = _canvas_task(workflow['id'], 'n1')
    failed = _canvas_task(workflow['id'], 'n2', status='failed')
    cancelled = _canvas_task(workflow['id'], 'n3', status='cancelled')
    unknown = _canvas_task(workflow['id'], 'n4', status='failed', result={'result_unknown': True})
    active = _canvas_task(workflow['id'], 'n5', status='processing')
    data = _ledger()
    buckets = {item['id']: item['bucket'] for item in data['tasks']}
    assert buckets == {ok: 'billable', failed: 'failed', cancelled: 'cancelled',
                       unknown: 'result_unknown', active: 'active'}
    for bucket in ('billable', 'failed', 'cancelled', 'result_unknown', 'active'):
        assert data['totals'][bucket]['count'] == 1
        assert data['totals'][bucket]['known_usd_min'] == pytest.approx(0.756)
    assert '可能已计费' in data['bucket_labels']['result_unknown']
    assert '通常不计费' in data['bucket_labels']['failed']
    assert '通常不计费' in data['bucket_labels']['cancelled']


def test_historical_tasks_are_derived_or_unknown():
    derivable = task_db.create_task('video', 'p', _video_params(duration=-1, model='seedance-2.5'),
                                    provider='cupsy', status='succeeded')
    broken = task_db.create_task('video', 'p', {'model': 'seedance-1.0'}, provider='ark', status='succeeded')
    other = task_db.create_task('video', 'p', _video_params(), provider='mystery', status='succeeded')
    tasks = {item['id']: item for item in _ledger()['tasks']}
    assert tasks[derivable]['basis'] == 'derived'
    assert tasks[derivable]['estimate_usd']['min'] < tasks[derivable]['estimate_usd']['max']
    assert tasks[broken]['estimate_usd'] is None and tasks[broken]['unknown_reason'] == 'no_estimate_snapshot'
    assert tasks[other]['estimate_usd'] is None and tasks[other]['unknown_reason'] == 'unknown_provider'


def test_stored_snapshot_wins_over_rederivation():
    task_id = task_db.create_task('video', 'p', _video_params(), provider='ark', status='succeeded')
    assert cost_estimate.store_snapshot(task_id)['status'] == 'estimate'
    params = task_db.get_task(task_id)['params']
    params['cost_estimate']['minimum_cost'] = params['cost_estimate']['maximum_cost'] = 1.25
    task_db.update_task(task_id, params=params)
    assert cost_estimate.store_snapshot(task_id) is None  # never overwrites an existing snapshot
    [item] = _ledger()['tasks']
    assert item['basis'] == 'snapshot' and item['estimate_usd'] == {'min': 1.25, 'max': 1.25}


def test_ark_submission_stores_snapshot(billing_env, posts):
    posts.install(Response(payload={'id': ACCEPTED_ID}))
    response = submit_video(model='seedance-2.0', ratio='16:9', duration=5, resolution='720p')
    assert response.status_code in (200, 202), response.get_json()
    task_id = response.get_json()['db_task_id']
    snapshot = task_db.get_task(task_id)['params']['cost_estimate']
    assert snapshot['status'] == 'estimate'
    assert snapshot['minimum_cost'] == pytest.approx(0.756)
    assert posts.count == 1  # snapshot adds no provider request


def test_reference_video_seconds_use_local_file_duration(tmp_path):
    upload_dir = Path(storage.UPLOAD_VIDEO_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    clip = upload_dir / 'clip.mp4'
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=64x64:d=7',
                        '-pix_fmt', 'yuv420p', str(clip)], check=True, timeout=30)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip('ffmpeg unavailable')
    task_id = task_db.create_task('video', 'p', _video_params(
        ref_video_urls=['/api/upload_video/clip.mp4', 'https://elsewhere.invalid/x.mp4']),
        provider='ark', status='succeeded')
    snapshot = cost_estimate.store_snapshot(task_id)
    assert snapshot['reference_video_count'] == 2
    assert snapshot['input_video_seconds'] == pytest.approx(12)  # 7s probed + 5s assumed
    assert snapshot['input_duration_assumed'] is True


def test_keyframe_mode_ignores_reference_videos():
    task_id = task_db.create_task('video', 'p', _video_params(
        video_mode='keyframe', ref_video_urls=['/api/upload_video/x.mp4']), provider='ark', status='succeeded')
    [item] = _ledger()['tasks']
    assert item['id'] == task_id and item['assumptions']['input_video_seconds'] == 0


def test_date_filter_and_timezone(monkeypatch):
    task_id = task_db.create_task('video', 'p', _video_params(), provider='ark', status='succeeded')
    task_db.get_db().execute("UPDATE tasks SET created_at='2026-11-13T20:00:00+00:00' WHERE id=?", (task_id,))
    task_db.get_db().commit()
    assert _ledger(tz_offset_minutes=0)['tasks'][0]['date'] == '2026-11-13'
    assert _ledger(tz_offset_minutes=480)['tasks'][0]['date'] == '2026-11-14'
    assert _ledger(**{'from': '2026-11-14', 'tz_offset_minutes': 480})['tasks_total'] == 1
    assert _ledger(**{'from': '2026-11-14'})['tasks_total'] == 0
    client = application.app.test_client()
    for query in ({'from': '11/14'}, {'from': '2026-11-15', 'to': '2026-11-14'}, {'tz_offset_minutes': 'x'}):
        assert client.get('/api/cost-ledger', query_string=query).status_code == 400


def test_deleted_workflow_tasks_stay_visible():
    project = store.create_project('p')
    workflow = store.create_workflow(project['id'], 'w')
    task_id = _canvas_task(workflow['id'], 'n1')
    db = task_db.get_db()
    db.execute('DELETE FROM canvas_task_refs WHERE workflow_id=?', (workflow['id'],)) \
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_task_refs'").fetchone() else None
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute('DELETE FROM canvas_workflows WHERE id=?', (workflow['id'],))
    db.commit()
    db.execute('PRAGMA foreign_keys=ON')
    [item] = _ledger()['tasks']
    assert item['id'] == task_id and item['project_id'] == '__missing__'


def test_cupsy_reference_video_seconds_from_linked_assets(tmp_path):
    clip = tmp_path / 'cupsy_clip.mp4'
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=64x64:d=9',
                        '-pix_fmt', 'yuv420p', str(clip)], check=True, timeout=30)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip('ffmpeg unavailable')
    asset = task_db.create_provider_asset('cupsy', 'video', 'a' * 64, 'clip.mp4', 'video/mp4', 1, str(clip))
    asset_id = asset['id'] if isinstance(asset, dict) else asset
    task_id = task_db.create_task('video', 'p', _video_params(model='seedance-2.5'), provider='cupsy',
                                  status='succeeded')
    task_db.link_task_provider_asset(task_id, asset_id, 'reference_video', 0)
    snapshot = cost_estimate.store_snapshot(task_id)
    assert snapshot['input_video_seconds'] == pytest.approx(9)
    assert snapshot['input_duration_assumed'] is False
    assert snapshot['unit_price'] == pytest.approx(6.40)  # Cupsy priced at BytePlus with-video rate
