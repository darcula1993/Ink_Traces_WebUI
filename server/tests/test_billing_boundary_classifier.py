"""Billing boundary: `_request_not_sent` must never call a possibly-sent request "unsent".

Synthetic exceptions cover the decision table; real 127.0.0.1 sockets cover what
requests/urllib3 actually raise (refused, close-after-read, read timeout, RST, TLS vs plaintext).
"""

import pytest
import requests

import app as application
from billing_support import (
    ABORTED, DNS, REFUSED, RESET, WRITE_TIMEOUT, closed_port, local_server,  # noqa: F401
)


class _Weird(requests.RequestException):
    pass


MAYBE_SENT = [
    requests.exceptions.ReadTimeout('read timed out'),
    WRITE_TIMEOUT,
    ABORTED,
    RESET,
    requests.exceptions.ConnectionError("('Connection aborted.', BrokenPipeError(32, 'Broken pipe'))"),
    requests.exceptions.ConnectionError(''),
    requests.exceptions.ConnectionError(
        "Caused by NewConnectionError('...'): Read timed out"),  # mixed text still contains "timed out"
    requests.exceptions.SSLError('EOF occurred in violation of protocol'),
    requests.exceptions.SSLError('Connection refused'),  # SSL is never treated as pre-send
    requests.exceptions.ProxyError('Connection refused'),
    requests.exceptions.ChunkedEncodingError('incomplete chunk'),
    requests.exceptions.ContentDecodingError('bad gzip'),
    requests.exceptions.TooManyRedirects('redirect loop'),
    requests.exceptions.RetryError('too many 500'),
    requests.RequestException('Connection refused'),  # bare base class is not a ConnectionError
    _Weird('Failed to resolve'),
    RuntimeError('Connection refused'),
    ValueError('NameResolutionError'),
]

UNSENT = [
    requests.exceptions.ConnectTimeout('connect timed out'),
    requests.exceptions.InvalidURL('bad url'),
    requests.exceptions.MissingSchema('no schema'),
    requests.exceptions.InvalidSchema('no adapter'),
    requests.exceptions.URLRequired('url required'),
    requests.exceptions.InvalidHeader('bad header'),
    DNS,
    REFUSED,
    requests.exceptions.ConnectionError('[Errno -2] Name or service not known'),
    requests.exceptions.ConnectionError('nodename nor servname provided, or not known'),
]


@pytest.mark.parametrize('error', MAYBE_SENT, ids=lambda e: f'{type(e).__name__}:{str(e)[:30]}')
def test_possibly_sent_errors_are_never_classified_unsent(error):
    assert application._request_not_sent(error) is False


@pytest.mark.parametrize('error', UNSENT, ids=lambda e: f'{type(e).__name__}:{str(e)[:30]}')
def test_provably_unsent_errors_are_classified_unsent(error):
    assert application._request_not_sent(error) is True


@pytest.mark.parametrize(('error', 'error_type'), [
    (requests.exceptions.ReadTimeout('x'), 'upstream_timeout'),
    (WRITE_TIMEOUT, 'upload_timeout'),
    (ABORTED, 'request_error_unknown'),
    (requests.exceptions.SSLError('x'), 'request_error_unknown'),
])
def test_unknown_error_type_mapping(error, error_type):
    assert application._unknown_request_error_type(error) == error_type


# --- real sockets: classify what requests actually raises -----------------------------------

def _post(url, timeout=(2, 0.4)):
    # Plain requests (no retry adapter) so each case costs one connection attempt.
    try:
        requests.post(url + '/v1/generate', json={'prompt': 'x'}, timeout=timeout)
    except requests.RequestException as error:
        return error
    raise AssertionError('expected a requests error')


def test_real_connection_refused_is_unsent():
    error = _post(f'http://127.0.0.1:{closed_port()}')
    assert isinstance(error, requests.exceptions.ConnectionError)
    assert application._request_not_sent(error) is True


@pytest.mark.parametrize(('mode', 'scheme', 'posts'), [
    ('close', 'http', 1),    # server read the whole POST, then closed without answering
    ('hang', 'http', 1),     # server read the POST and never answered -> ReadTimeout
    ('reset', 'http', 1),    # server read the POST, then sent RST
    ('garbage', 'https', 0),  # TLS client against plaintext server -> SSLError
])
def test_real_socket_failures_after_connect_are_possibly_sent(local_server, mode, scheme, posts):
    server = local_server(mode)
    error = _post(server.url(scheme))
    assert application._request_not_sent(error) is False
    assert server.posts == posts
    if mode == 'hang':
        assert isinstance(error, requests.exceptions.ReadTimeout)
    if mode == 'garbage':
        assert isinstance(error, requests.exceptions.SSLError)
