"""Tests for V24-W3-STAGE-ETA-20261121 (#13):
- AC1: Expanded public_stage whitelist + server stage signals during upload/generate/download
- AC2: Read-only 30-day P50/P25-P75 task duration stats + GET /api/tasks/duration-stats
"""

from datetime import datetime, timedelta, timezone
import json
import threading

import pytest

import app as application
import task_duration_stats
import task_public
import tasks as task_db
import worker
from billing_support import billing_env  # noqa: F401


def _insert_task(
    *,
    task_type='video',
    status='succeeded',
    prompt='SECRET_USER_PROMPT_DO_NOT_LEAK',
    params=None,
    provider='ark',
    created_at=None,
    completed_at=None,
    deleted_at=None,
):
    now = datetime.now(timezone.utc)
    created = created_at or (now - timedelta(hours=1)).isoformat()
    completed = completed_at
    if completed is None and status == 'succeeded':
        completed = (datetime.fromisoformat(created) + timedelta(seconds=30)).isoformat()
    db = task_db.get_db()
    cur = db.execute(
        '''INSERT INTO tasks
           (type, status, prompt, params, provider, created_at, completed_at, updated_at, deleted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            task_type,
            status,
            prompt,
            json.dumps(params or {}),
            provider,
            created,
            completed,
            completed or created,
            deleted_at,
        ),
    )
    db.commit()
    return cur.lastrowid


# ------------------------------------------------------------------ AC1: public_stage whitelist & live stage signals

def test_public_stage_whitelist_and_sanitization():
    for stage in ('uploading', 'queued', 'generating', 'downloading'):
        assert task_public.public_stage({'status': 'processing', 'stage': stage}) == stage
        for other_status in ('pending', 'preparing', 'succeeded', 'failed', 'cancelled', 'cancel_requested'):
            assert task_public.public_stage({'status': other_status, 'stage': stage}) is None

    for unsafe in (
        None,
        '',
        'unknown',
        'https://bucket.invalid/x?X-Tos-Signature=secret',
        'ep-20990101000000-fake01',  # secret-scan: allow (synthetic endpoint fixture)
    ):
        assert task_public.public_stage({'status': 'processing', 'stage': unsafe}) is None
    assert task_public.public_stage(None) is None


def test_ark_video_reports_generating_during_poll_and_clears_after_reschedule(billing_env, monkeypatch):
    task_id = task_db.create_task(
        'video', 'stage', {'provider': 'ark', 'output_format': 'mp4'},
        provider='ark', external_task_id='cgt-stage-gen-1', status='processing',
    )
    observed = {}

    class FakeResp:
        status_code = 200
        text = '{"status": "running", "content": {}}'

        def json(self):
            return {'status': 'running', 'content': {}}

    def fake_get(_url, **_kwargs):
        def read_public():
            try:
                client = application.app.test_client()
                observed['status'] = client.get(f'/api/tasks/status?ids={task_id}').get_json()['tasks'][0]
                observed['detail'] = client.get(f'/api/tasks/{task_id}').get_json()['task']
            finally:
                task_db.close_db()

        t = threading.Thread(target=read_public)
        t.start()
        t.join(10)
        return FakeResp()

    monkeypatch.setattr(application.HTTP, 'get', fake_get)
    runner = worker.Worker()
    claimed = task_db.claim_next_task(runner.worker_id, task_types=('video', 'audio'))
    runner.process(claimed)

    assert observed['status']['status'] == 'processing'
    assert observed['status']['stage'] == 'generating'
    assert observed['detail']['stage'] == 'generating'
    # Reschedule clears stage per existing rules.
    assert task_db.get_task(task_id)['stage'] is None


def test_cupsy_video_reports_uploading_while_waiting_for_assets_then_generating(billing_env, monkeypatch, tmp_path):
    ref_file = tmp_path / 'ref.png'
    ref_file.write_bytes(b'fake-png')
    asset = task_db.create_provider_asset('cupsy', 'image', 'sha-stage-1', 'ref.png', 'image/png', 8, str(ref_file))
    task_id = task_db.create_task(
        'video', 'stage', {'provider': 'cupsy', 'model': 'seedance-2.5'},
        provider='cupsy', status='pending',
    )
    task_db.link_task_provider_asset(task_id, asset['id'], 'reference_image', 0)

    # 1. Asset not active yet -> sets uploading before returning preparing, then reschedule clears to None.
    claimed = task_db.claim_next_task('stage-w1', task_types=('video', 'audio'))
    outcome = application.poll_video_task_once(claimed['id'])
    assert outcome['state'] == 'preparing'
    assert task_db.get_task(task_id)['stage'] == 'uploading'
    task_db.reschedule_task(task_id, 0, status='pending')
    assert task_db.get_task(task_id)['stage'] is None

    # 2. Asset becomes active -> sets generating before HTTP.post to Cupsy.
    task_db.update_provider_asset(asset['id'], status='active', asset_uri='asset://cupsy/1')
    seen_during_post = {}

    class PostResp:
        status_code = 200
        text = '{"id": "cupsy-vid-1"}'

        def json(self):
            return {'id': 'cupsy-vid-1'}

    def fake_post(_url, **_kwargs):
        seen_during_post['stage'] = task_db.get_task(task_id)['stage']
        return PostResp()

    monkeypatch.setattr(application.HTTP, 'post', fake_post)
    claimed2 = task_db.claim_next_task('stage-w1', task_types=('video', 'audio'))
    outcome2 = application.poll_video_task_once(claimed2['id'])
    assert outcome2['state'] == 'pending'
    assert seen_during_post['stage'] == 'generating'


# ------------------------------------------------------------------ AC2: duration stats aggregation & endpoint

def test_duration_stats_percentiles_fallback_window_and_privacy(billing_env):
    now = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
    recent_start = now - timedelta(days=5)

    # 5 video tasks for seedance-2.5: 20, 30, 40, 50, 60 -> P25=30, P50=40, P75=50
    for sec in (20, 30, 40, 50, 60):
        _insert_task(
            task_type='video',
            params={'model': 'seedance-2.5'},
            created_at=recent_start.isoformat(),
            completed_at=(recent_start + timedelta(seconds=sec)).isoformat(),
        )
    # 1 video task for seedance-2.0 (< 2 samples -> must NOT appear in by_model, degrades to video type)
    _insert_task(
        task_type='video',
        params={'model': 'seedance-2.0'},
        created_at=recent_start.isoformat(),
        completed_at=(recent_start + timedelta(seconds=200)).isoformat(),
    )
    # 3 image tasks with Ark endpoint IDs (must normalize to seedream-5.0-pro, never leak ep-...)
    for sec in (10, 20, 30):
        _insert_task(
            task_type='image',
            params={'model': 'ep-20990101000000-fake02'},  # secret-scan: allow (synthetic endpoint fixture)
            created_at=recent_start.isoformat(),
            completed_at=(recent_start + timedelta(seconds=sec)).isoformat(),
        )
    # Out-of-window (35 days ago), failed, trashed, negative duration: all must be excluded.
    old_start = now - timedelta(days=35)
    _insert_task(
        task_type='audio',
        params={'model': 'seed-audio-1.0'},
        created_at=old_start.isoformat(),
        completed_at=(old_start + timedelta(seconds=15)).isoformat(),
    )
    _insert_task(
        task_type='audio',
        status='failed',
        params={'model': 'seed-audio-1.0'},
        created_at=recent_start.isoformat(),
        completed_at=(recent_start + timedelta(seconds=15)).isoformat(),
    )
    _insert_task(
        task_type='audio',
        status='succeeded',
        params={'model': 'seed-audio-1.0'},
        created_at=recent_start.isoformat(),
        completed_at=(recent_start + timedelta(seconds=15)).isoformat(),
        deleted_at=now.isoformat(),
    )
    _insert_task(
        task_type='audio',
        status='succeeded',
        params={'model': 'seed-audio-1.0'},
        created_at=recent_start.isoformat(),
        completed_at=(recent_start - timedelta(seconds=5)).isoformat(),
    )

    stats = task_duration_stats.compute_duration_stats(window_days=30, now=now)
    dumped = json.dumps(stats, ensure_ascii=False)
    assert 'ep-20990101000000' not in dumped
    assert 'SECRET_USER_PROMPT' not in dumped

    assert stats['by_model']['video:seedance-2.5'] == {
        'type': 'video',
        'model': 'seedance-2.5',
        'sample_count': 5,
        'p25_seconds': 30.0,
        'p50_seconds': 40.0,
        'p75_seconds': 50.0,
    }
    assert 'video:seedance-2.0' not in stats['by_model']
    assert stats['by_model']['image:seedream-5.0-pro'] == {
        'type': 'image',
        'model': 'seedream-5.0-pro',
        'sample_count': 3,
        'p25_seconds': 15.0,
        'p50_seconds': 20.0,
        'p75_seconds': 25.0,
    }
    assert stats['by_type']['audio'] is None

    # Fallback: querying seedance-2.0 (< 2 samples) degrades to video type summary (all 6 video tasks).
    fallback = task_duration_stats.compute_duration_stats(
        window_days=30, task_type='video', model='seedance-2.0', now=now,
    )
    assert fallback['stat']['scope'] == 'type'
    assert fallback['stat']['sample_count'] == 6
    assert fallback['stat']['model'] is None

    # No samples for audio -> stat is None.
    empty_audio = task_duration_stats.compute_duration_stats(
        window_days=30, task_type='audio', model='seed-audio-1.0', now=now,
    )
    assert empty_audio['stat'] is None


def test_duration_stats_endpoint_auth_and_validation(billing_env, monkeypatch):
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=2)).isoformat()
    for sec in (20, 40):
        _insert_task(
            task_type='image',
            params={'model': 'ep-20990101000000-fake03', 'seedream55': True},  # secret-scan: allow (synthetic endpoint fixture)
            created_at=start,
            completed_at=(now - timedelta(hours=2) + timedelta(seconds=sec)).isoformat(),
        )

    client = application.app.test_client()
    # Auth enabled -> 401 when unauthenticated
    monkeypatch.setattr(application, 'AUTH_CONFIG', {'username': 'admin', 'password_hash': 'x'})
    unauth = client.get('/api/tasks/duration-stats')
    assert unauth.status_code == 401

    # Logged-in session -> 200
    with client.session_transaction() as sess:
        sess['logged_in'] = True
    resp = client.get('/api/tasks/duration-stats?type=image&model=seedream-5.5')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['success'] is True
    assert payload['window_days'] == 30
    assert payload['stat']['scope'] == 'model'
    assert payload['stat']['model'] == 'seedream-5.5'
    assert payload['stat']['sample_count'] == 2
    assert payload['stat']['p50_seconds'] == 30.0
    serialized = json.dumps(payload, ensure_ascii=False)
    assert 'ep-20990101000000' not in serialized
    assert 'SECRET_USER_PROMPT' not in serialized

    # Invalid type -> 400
    bad = client.get('/api/tasks/duration-stats?type=bogus')
    assert bad.status_code == 400
