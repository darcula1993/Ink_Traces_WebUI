"""Billing boundary matrix for image and layer generation (Ark / Cupsy; unknown providers refused).

Axes: provider x time point (before request / during request / after response)
x outcome (result_unknown, error_type, reschedule behaviour, POST count).
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import app as application
import tasks as task_db
import worker
from billing_support import (  # noqa: F401  (fixtures)
    ABORTED, Response, assert_known_failure, assert_unknown, billing_env, image_task,
    layer_task, local_server, closed_port, maybe_sent_errors, nothing_claimable, posts,
    run_until_idle, unsent_errors,
)

SENT = maybe_sent_errors()
UNSENT = unsent_errors()
ARK_OK = {'data': [{'url': 'https://media.invalid/generated.png', 'output_format': 'png'}]}


@pytest.fixture
def runner(billing_env):
    return worker.Worker()


def _broken(*_args, **_kwargs):
    raise RuntimeError('local config failure')


# ---------------------------------------------------------------- before the request

@pytest.mark.parametrize('provider', ['ark'])
def test_image_failure_before_request_is_known_and_not_resubmitted(runner, posts, monkeypatch, provider):
    posts.install(Response(payload=ARK_OK))
    monkeypatch.setattr(application, 'get_image_provider_config', _broken)
    task_id = image_task(provider)

    assert run_until_idle(runner) == 1  # Ark: one attempt only
    assert posts.count == 0
    task = assert_known_failure(task_id)
    assert task['error'] == 'local config failure'


def test_layer_failure_before_request_is_known(runner, posts):
    posts.install(Response(payload=ARK_OK))
    task_id = layer_task(with_source=False)

    assert run_until_idle(runner) == 1
    assert posts.count == 0
    assert '源图片不存在' in assert_known_failure(task_id)['error']


def test_cupsy_failure_before_request_keeps_three_attempts(runner, posts, monkeypatch):
    posts.install(Response(payload={}))
    monkeypatch.setattr(application, 'get_image_provider_config', _broken)
    task_id = image_task('cupsy')

    assert run_until_idle(runner) == 3
    assert posts.count == 0
    assert_known_failure(task_id)


# ---------------------------------------------------------------- during the request

@pytest.mark.parametrize('provider', ['ark'])
@pytest.mark.parametrize(('case', 'error', 'error_type'), SENT, ids=[case for case, _, _ in SENT])
def test_image_possibly_sent_error_is_unknown_once(runner, posts, provider, case, error, error_type):
    posts.install(error)
    task_id = image_task(provider)

    assert run_until_idle(runner) == 1
    assert posts.count == 1
    assert_unknown(task_id, error_type)
    assert nothing_claimable()


@pytest.mark.parametrize('provider', ['ark'])
@pytest.mark.parametrize(('case', 'error'), UNSENT, ids=[case for case, _ in UNSENT])
def test_image_provably_unsent_error_is_known(runner, posts, provider, case, error):
    posts.install(error)
    task_id = image_task(provider)

    assert run_until_idle(runner) == 1
    assert posts.count == 1
    task = assert_known_failure(task_id)
    assert task['result']['error_type'] in {'request_error', 'connect_timeout'}
    if provider == 'ark' and case == 'connect_timeout':
        assert '尚未提交' in task['error'] and '自动重试' not in task['error']


def test_ark_non_requests_error_inside_post_is_unknown(runner, posts):
    posts.install(RuntimeError('adapter crashed mid-request'))
    task_id = image_task('ark')
    assert run_until_idle(runner) == 1
    assert posts.count == 1
    assert_unknown(task_id, 'request_error_unknown')


def test_unknown_provider_task_fails_known_without_any_request(runner, posts):
    # A queued row with an unsupported provider must neither reach a provider nor fall back to Ark.
    posts.install(Response(payload=ARK_OK))
    task_id = image_task('acme')
    assert run_until_idle(runner) == 1
    assert posts.count == 0
    task = assert_known_failure(task_id)
    assert '不支持的图片 provider' in task['error']
    assert nothing_claimable()


@pytest.mark.parametrize(('case', 'error', 'error_type'), SENT + [
    ('runtime', RuntimeError('adapter crashed mid-request'), 'request_error_unknown'),
], ids=[case for case, _, _ in SENT] + ['runtime'])
def test_layer_possibly_sent_error_is_unknown_once(runner, posts, case, error, error_type):
    posts.install(error)
    task_id = layer_task()
    task_db.update_task(task_id, result={'note': 'kept'})

    assert run_until_idle(runner) == 1
    assert posts.count == 1
    task = assert_unknown(task_id, error_type)
    assert task['result']['note'] == 'kept'
    assert nothing_claimable()


@pytest.mark.parametrize(('case', 'error'), UNSENT, ids=[case for case, _ in UNSENT])
def test_layer_provably_unsent_error_is_known(runner, posts, case, error):
    posts.install(error)
    task_id = layer_task()
    assert run_until_idle(runner) == 1
    assert posts.count == 1
    task = assert_known_failure(task_id)
    assert task['result']['result_unknown'] is False


@pytest.mark.parametrize(('case', 'error', 'error_type'), SENT, ids=[case for case, _, _ in SENT])
def test_cupsy_transport_error_replays_same_idempotency_key(runner, posts, case, error, error_type):
    posts.install(error)
    task_id = image_task('cupsy')

    for _ in range(3):
        task = task_db.claim_next_task(runner.worker_id, task_types=('image',))
        assert task['id'] == task_id
        runner.process(task)
        task_db.update_task(task_id, next_run_at=None)
    assert posts.count == 3
    keys = {call['headers'].get('Idempotency-Key') for call in posts.calls}
    assert len(keys) == 1 and None not in keys
    task = task_db.get_task(task_id)
    assert task['status'] == 'processing'
    assert not (task.get('result') or {}).get('result_unknown')


# ---------------------------------------------------------------- after the response

@pytest.mark.parametrize('provider', ['ark'])
def test_provider_5xx_with_body_is_known_and_not_resubmitted(runner, posts, provider):
    posts.install(Response(payload={'error': {'message': 'internal'}}, status_code=500))
    task_id = image_task(provider)
    assert run_until_idle(runner) == 1
    assert posts.count == 1
    assert_known_failure(task_id)
    assert nothing_claimable()


def test_ark_unparseable_response_is_unknown(runner, posts):
    posts.install(Response(json_error=ValueError('broken provider body')))
    task_id = image_task('ark')
    assert run_until_idle(runner) == 1
    assert posts.count == 1
    assert_unknown(task_id, 'worker_exception')


def test_layer_unparseable_response_reaches_worker_branch(runner, posts):
    posts.install(Response(json_error=ValueError('broken provider body')))
    task_id = layer_task()
    assert run_until_idle(runner) == 1
    assert posts.count == 1
    assert_unknown(task_id, 'worker_exception')


def test_layer_provider_rejection_is_known(runner, posts):
    posts.install(Response(payload={'error': {'message': 'bad image'}}, status_code=400))
    task_id = layer_task()
    assert run_until_idle(runner) == 1
    assert posts.count == 1
    assert_known_failure(task_id)


def test_unexpected_crash_after_provider_success_is_unknown(runner, posts, monkeypatch):
    posts.install(Response(payload=ARK_OK))
    monkeypatch.setattr(application, '_save_generated_image', _broken)
    task_id = image_task('ark')
    task_db.update_task(task_id, result={'note': 'kept'})

    assert run_until_idle(runner) == 1
    assert posts.count == 1
    task = assert_unknown(task_id, 'worker_exception')
    assert task['result']['note'] == 'kept'


def test_known_save_failure_after_success_keeps_source_urls(runner, posts, monkeypatch):
    posts.install(Response(payload=ARK_OK))

    def save_fails(*_args, **_kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(application, '_save_generated_image', save_fails)
    task_id = image_task('ark')

    assert run_until_idle(runner) == 1
    assert posts.count == 1
    task = assert_known_failure(task_id)
    assert task['result']['source_urls'] == ['https://media.invalid/generated.png']


def test_process_image_never_reschedules_unknown_payload(runner, monkeypatch):
    seen = []

    def unknown_without_fail(task_id):
        seen.append(task_id)
        return {'success': False, 'result_unknown': True, 'error': 'unknown'}, 502
    monkeypatch.setattr(application, 'execute_image_task', unknown_without_fail)
    task_id = image_task('ark')
    assert run_until_idle(runner) == 1
    assert seen == [task_id]
    assert task_db.get_task(task_id)['status'] == 'processing'


# ---------------------------------------------------------------- real sockets, project HTTP client

@pytest.fixture
def fast_ark_timeouts(monkeypatch):
    monkeypatch.setattr(application, 'resolve_ark_timeouts', lambda *_a, **_k: (2, 0.4))


def _point(provider, url, monkeypatch):
    assert provider == 'ark'
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {
        'api_key': 'test-key', 'endpoint': url, 'model': 'test-model'})


# TLS-vs-plaintext is a handshake failure: urllib3 retries the connect (no HTTP bytes, posts=0),
# which costs ~3s of backoff, hence billing_slow.
@pytest.mark.parametrize(('provider', 'mode', 'scheme', 'posts_seen', 'error_type'), [
    ('ark', 'close', 'http', 1, 'request_error_unknown'),
    ('ark', 'reset', 'http', 1, 'request_error_unknown'),
    ('ark', 'hang', 'http', 1, 'upstream_timeout'),
    pytest.param('ark', 'garbage', 'https', 0, 'request_error_unknown', marks=pytest.mark.billing_slow),
])
def test_real_socket_failure_is_unknown_and_sent_once(
        runner, local_server, fast_ark_timeouts, monkeypatch, provider, mode, scheme, posts_seen, error_type):
    server = local_server(mode)
    _point(provider, server.url(scheme), monkeypatch)
    task_id = image_task(provider)

    assert run_until_idle(runner) == 1
    assert server.posts == posts_seen
    assert server.connections >= 1
    assert_unknown(task_id, error_type)
    assert nothing_claimable()


@pytest.mark.billing_slow  # project adapter retries connect errors with backoff (~3s)
def test_real_refused_connection_is_known(runner, fast_ark_timeouts, monkeypatch):
    _point('ark', f'http://127.0.0.1:{closed_port()}', monkeypatch)
    task_id = image_task('ark')
    assert run_until_idle(runner) == 1
    assert assert_known_failure(task_id)['result']['error_type'] == 'request_error'


# ---------------------------------------------------------------- thread reuse and concurrency

def test_dispatch_marker_does_not_leak_on_reused_thread(runner, posts, monkeypatch):
    posts.install(Response(json_error=ValueError('broken provider body')))
    first, second = image_task('ark'), image_task('ark')
    original_config = application.get_image_provider_config
    calls = []

    def config_for(provider, *args, **kwargs):
        calls.append(provider)
        if len(calls) > 1:  # second task fails before its POST
            raise RuntimeError('local config failure')
        return original_config(provider, *args, **kwargs)
    monkeypatch.setattr(application, 'get_image_provider_config', config_for)

    with ThreadPoolExecutor(max_workers=1) as pool:
        for _ in range(2):
            task = task_db.claim_next_task(runner.worker_id, task_types=('image',))
            pool.submit(runner.process, task).result()
    assert posts.count == 1
    assert_unknown(first, 'worker_exception')
    assert_known_failure(second)


def test_concurrent_marker_is_per_thread(runner, posts, monkeypatch):
    in_post, release = threading.Event(), threading.Event()

    def blocking(url, kwargs):
        in_post.set()
        assert release.wait(5)
        raise ABORTED
    posts.install(blocking)
    original_config = application.get_image_provider_config
    calls = []
    lock = threading.Lock()

    def config_for(provider, *args, **kwargs):
        with lock:
            calls.append(provider)
            unsent = len(calls) > 1  # the second (concurrent) task fails before its POST
        if unsent:
            raise RuntimeError('local config failure')
        return original_config(provider, *args, **kwargs)
    monkeypatch.setattr(application, 'get_image_provider_config', config_for)
    sent_id = image_task('ark')
    sent = task_db.claim_next_task(runner.worker_id, task_types=('image',))
    unsent_id = image_task('ark')
    unsent = task_db.claim_next_task(runner.worker_id, task_types=('image',))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runner.process, sent)
        assert in_post.wait(5)
        pool.submit(runner.process, unsent).result()
        assert_known_failure(unsent_id)
        release.set()
        first.result()
    assert posts.count == 1
    assert_unknown(sent_id, 'request_error_unknown')


def test_parallel_possibly_sent_tasks_each_post_once(runner, posts):
    posts.install(ABORTED)
    ids = [image_task('ark') for _ in range(8)]
    claimed = [task_db.claim_next_task(runner.worker_id, task_types=('image',)) for _ in ids]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(runner.process, claimed))
    assert posts.count == 8
    for task_id in ids:
        assert_unknown(task_id, 'request_error_unknown')
    assert nothing_claimable()


# ---------------------------------------------------------------- G2: unknown provider submission

def test_unknown_provider_submission_creates_no_task_and_sends_nothing(billing_env, posts):
    posts.install(ABORTED)
    client = application.app.test_client()
    response = client.post('/api/generate', json={
        'provider': 'acme', 'prompt': 'x', 'aspect_ratio': '1:1', 'resolution': '1K',
    })
    assert response.status_code == 400 and '未知 provider' in response.get_json()['error']
    assert posts.count == 0
    assert task_db.list_task_ids() == []


# ---------------------------------------------------------------- G3: Worker.process resets the marker itself

def test_marker_from_previous_task_does_not_mark_crash_before_execute(runner, posts, monkeypatch):
    posts.install(ABORTED)
    first = image_task('ark')
    runner.process(task_db.claim_next_task(runner.worker_id, task_types=('image',)))
    assert_unknown(first, 'request_error_unknown')
    assert application.provider_dispatch_started() is True  # left set on this thread

    second = image_task('ark')
    real_load = worker.profile_runtime.load_selection
    crashed = []

    def crash_once(params):
        if not crashed:
            crashed.append(True)
            raise RuntimeError('profile load failure')
        return real_load(params)
    monkeypatch.setattr(worker.profile_runtime, 'load_selection', crash_once)
    runner.process(task_db.claim_next_task(runner.worker_id, task_types=('image',)))

    assert crashed and posts.count == 1
    task = assert_known_failure(second)
    assert task['error'] == 'profile load failure'
