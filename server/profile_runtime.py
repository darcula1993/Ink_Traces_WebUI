"""Request/task-local immutable provider selections, without global credential mutation."""
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

_current = ContextVar('provider_profile', default=None)


def current_profile():
    return _current.get()


def public_selection(kind=None, adapter=None, existing=None):
    profile = current_profile()
    if profile:
        return {'profile_id': profile['id'], 'profile_revision': profile['revision']}
    if existing and existing.get('profile_id'):
        return {}
    if kind and adapter:
        from provider_profiles import load_source_profile
        source = load_source_profile(kind, adapter)
        if source and source['enabled'] and source['api_key']:
            return {'profile_id': source['id'], 'profile_revision': source['revision']}
    return {}


def asset_provider():
    profile = current_profile()
    return f"cupsy:profile:{profile['id']}:{profile['revision']}" if profile else 'cupsy'


def asset_provider_matches(asset_provider_value, *, explicit_profile=False):
    expected = asset_provider()
    if asset_provider_value == expected:
        return True
    profile = current_profile()
    if not explicit_profile and profile and profile.get('source_key') and asset_provider_value == 'cupsy':
        return True
    return False


@contextmanager
def profile_scope(profile):
    token = _current.set(profile)
    try:
        yield profile
    finally:
        _current.reset(token)


def load_selection(params):
    if not params or not params.get('profile_id'):
        return None
    from provider_profiles import load_profile
    return load_profile(params['profile_id'], params['profile_revision'])


def asset_selection(asset):
    scope = asset.get('provider', '') if asset else ''
    if not scope.startswith('cupsy:profile:'):
        return None
    _, _, profile_id, revision = scope.split(':')
    from provider_profiles import load_profile
    return load_profile(profile_id, int(revision))


def task_context(function):
    @wraps(function)
    def wrapped(task_id, *args, **kwargs):
        import tasks
        task = tasks.get_task(task_id)
        with profile_scope(load_selection((task or {}).get('params'))):
            return function(task_id, *args, **kwargs)
    return wrapped


def asset_context(function):
    @wraps(function)
    def wrapped(asset_id, *args, **kwargs):
        import tasks
        with profile_scope(asset_selection(tasks.get_provider_asset(asset_id))):
            return function(asset_id, *args, **kwargs)
    return wrapped


class ProfileConfig(Mapping):
    """Read-only view: immutable revision inside an explicit scope, latest DB config profile
    outside a scope, falling back to config.json only when no DB config profile exists."""
    def __init__(self, fallback, adapter, kind=None):
        self.fallback = fallback
        self.adapter = adapter
        self.kind = kind

    def has_db_source(self):
        if not self.kind or not self.adapter:
            return False
        from provider_profiles import load_source_profile
        return load_source_profile(self.kind, self.adapter) is not None

    def values_dict(self):
        profile = current_profile()
        if profile and (self.adapter is None or profile['adapter'] == self.adapter):
            # Do not inherit endpoints or credentials from an unrelated legacy account.
            return {**profile['settings'], 'api_key': profile['api_key']}
        if self.kind:
            from provider_profiles import load_source_profile
            if self.adapter is not None:
                source = load_source_profile(self.kind, self.adapter)
                if source is not None:
                    if source['enabled']:
                        return {**source['settings'], 'api_key': source['api_key']}
                    disabled_settings = {k: v for k, v in source['settings'].items() if k != 'seedance_2_5_model'}
                    return {**disabled_settings, 'api_key': ''}
            elif self.kind == 'audio':
                source = load_source_profile('audio', 'cupsy')
                if source is not None and source['enabled']:
                    return {**self.fallback, **source['settings']}
        return self.fallback

    def __getitem__(self, key):
        return self.values_dict()[key]

    def __iter__(self):
        return iter(self.values_dict())

    def __len__(self):
        return len(self.values_dict())


def install_profile_requests(app):
    from flask import request, g, jsonify
    from provider_profiles import load_profile, ProfileError

    @app.before_request
    def select_profile():
        kinds = {'/api/generate': 'image', '/api/video/generate': 'video', '/api/audio/generate': 'audio'}
        kind = kinds.get(request.path)
        if request.method != 'POST' or not kind:
            return
        data = request.form if request.mimetype == 'multipart/form-data' else (request.get_json(silent=True) or {})
        if not isinstance(data, Mapping):
            return jsonify(success=False, error='请求必须为对象'), 400
        from canvas_project_settings import validate_generation
        from canvas_store import CanvasError
        try:
            validate_generation(data, kind)
        except CanvasError as error:
            return jsonify(success=False, error=str(error)), error.status
        profile_id = data.get('profile_id')
        if not profile_id:
            from provider_profiles import load_source_profile
            if kind == 'image':
                import app as application
                adapter = data.get('provider') or application.get_session_image_provider()
            elif kind == 'video':
                adapter = data.get('provider') or 'ark'
            else:
                adapter = data.get('provider') or 'cupsy'
            source = load_source_profile(kind, adapter) if isinstance(adapter, str) else None
            if source and source['enabled'] and source['api_key']:
                g.provider_profile_token = _current.set(source)
            return
        try:
            profile = load_profile(profile_id, kind=kind, require_enabled=True)
            if data.get('provider') and data.get('provider') != profile['adapter']:
                return jsonify(success=False, error='接口配置与Provider不匹配'), 400
            if kind == 'video' and not data.get('provider') and profile['adapter'] != 'ark':
                return jsonify(success=False, error='请同时指定接口对应的Provider'), 400
            g.provider_profile_token = _current.set(profile)
        except ProfileError as error:
            return jsonify(success=False, error=str(error)), error.status

    @app.teardown_request
    def release_profile(_error=None):
        token = g.pop('provider_profile_token', None)
        if token is not None:
            _current.reset(token)


def setting(name, fallback):
    profile = current_profile()
    return profile['settings'].get(name, fallback) if profile else fallback
