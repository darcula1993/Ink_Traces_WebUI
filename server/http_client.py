"""Shared outbound HTTP client with connection pooling and conservative retries."""

import requests
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _build_session():
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({'GET', 'HEAD'}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    session = requests.Session()
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


class PooledHttpClient:
    def __init__(self):
        self._local = threading.local()

    def _session(self):
        session = getattr(self._local, 'session', None)
        if session is None:
            session = _build_session()
            self._local.session = session
        return session

    def get(self, *args, **kwargs):
        return self._session().get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self._session().post(*args, **kwargs)


HTTP = PooledHttpClient()
