"""Private, immutable provider revisions. Public serializers never return credentials."""
import ipaddress
import json
import re
import sqlite3
import uuid
from urllib.parse import urlsplit

import config_v2
import tasks as task_db

KINDS = {'image': {'ark', 'cupsy'}, 'video': {'ark', 'cupsy'}, 'audio': {'cupsy'}}
CONFIG_PROFILES = (
    ('config:image:ark', 'image', 'ark', 'BytePlus 图像'),
    ('config:image:cupsy', 'image', 'cupsy', 'Cupsy 图像'),
    ('config:video:ark', 'video', 'ark', 'BytePlus 视频'),
    ('config:video:cupsy', 'video', 'cupsy', 'Cupsy 视频'),
    ('config:audio:cupsy', 'audio', 'cupsy', 'Cupsy 音频'),
)
CONFIG_SOURCE_KEYS = {(kind, adapter): key for key, kind, adapter, _ in CONFIG_PROFILES}
UNSUPPORTED_ADAPTER_ERROR = '生成类型与适配器组合不受支持'
ENDPOINT_ID_PLACEHOLDER_ERROR = 'Seedance 2.5 接入点ID仍是示例占位，请填写 BytePlus 控制台的真实 ep-... 接入点ID或留空'
TIMEOUTS = {'request_timeout_seconds', 'upload_timeout_seconds', 'poll_timeout_seconds', 'download_timeout_seconds'}
COMMON_SETTINGS = {'endpoint', 'model', 'poll_interval_seconds', 'poll_max_attempts'} | TIMEOUTS
ARK_IMAGE_CAPABILITY_MODELS = {'', 'dola-seedream-5-5-261028', 'seedream-5-0-pro'}


class ProfileError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def source_key_for(kind, adapter):
    return CONFIG_SOURCE_KEYS.get((kind, adapter))


def init_profiles_db():
    db = task_db.get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS provider_profiles (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL, kind TEXT NOT NULL,
            adapter TEXT NOT NULL, name TEXT NOT NULL, enabled INTEGER NOT NULL,
            is_default INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            source_key TEXT, deleted_at TEXT,
            UNIQUE(kind, name)
        );
        CREATE TABLE IF NOT EXISTS provider_profile_revisions (
            profile_id TEXT NOT NULL, revision INTEGER NOT NULL, private_document TEXT NOT NULL,
            PRIMARY KEY(profile_id, revision),
            FOREIGN KEY(profile_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_profile_default
            ON provider_profiles(kind) WHERE is_default=1;
    ''')
    columns = {row['name'] for row in db.execute('PRAGMA table_info(provider_profiles)').fetchall()}
    if 'source_key' not in columns:
        try:
            db.execute('ALTER TABLE provider_profiles ADD COLUMN source_key TEXT')
        except sqlite3.OperationalError as error:
            if 'duplicate column name' not in str(error).lower():
                raise
    if 'deleted_at' not in columns:
        try:
            db.execute('ALTER TABLE provider_profiles ADD COLUMN deleted_at TEXT')
        except sqlite3.OperationalError as error:
            if 'duplicate column name' not in str(error).lower():
                raise
    db.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_profile_source_key
            ON provider_profiles(source_key) WHERE source_key IS NOT NULL
    ''')
    db.commit()


def public_profile(profile):
    result = {key: profile[key] for key in ('id', 'name', 'kind', 'adapter', 'enabled', 'is_default', 'revision', 'settings', 'asset_scope', 'created_at', 'updated_at')}
    source_key = profile.get('source_key')
    result['source_key'] = source_key
    result['has_api_key'] = bool(profile['api_key'])
    result['api_key_mask'] = '••••••••' if profile['api_key'] else ''
    if profile.get('kind') == 'image':
        if profile.get('adapter') == 'cupsy':
            result['capability_model'] = 'seedream-5.0-pro'
        elif profile.get('adapter') == 'ark':
            import seedream55
            settings = profile.get('settings') or {}
            declared = str(settings.get('capability_model') or '').strip()
            raw_model = settings.get('model') or 'seedream-5-0-pro'
            result['capability_model'] = seedream55.capability_model(raw_model, declared=declared)
    deleted_at = profile.get('deleted_at')
    if deleted_at:
        result['deleted'] = True
        result['deleted_at'] = deleted_at
    return result


def load_profile(profile_id, revision=None, *, kind=None, require_enabled=False, allow_deleted=False):
    if not isinstance(profile_id, str) or not re.fullmatch(r'[0-9a-f]{32}', profile_id):
        raise ProfileError('接口配置不存在', 404)
    if revision is not None and (type(revision) is not int or revision < 1):
        raise ProfileError('revision 必须为正整数')
    db = task_db.get_db()
    current = db.execute('SELECT * FROM provider_profiles WHERE id=?', (profile_id,)).fetchone()
    if not current:
        raise ProfileError('接口配置不存在', 404)
    deleted_at = current['deleted_at'] if 'deleted_at' in current.keys() else None
    if revision is None and deleted_at is not None:
        if require_enabled:
            raise ProfileError('接口配置已停用或已删除', 409)
        if not allow_deleted:
            raise ProfileError('接口配置不存在', 404)
    row = db.execute('SELECT private_document FROM provider_profile_revisions WHERE profile_id=? AND revision=?',
                     (profile_id, revision if revision is not None else current['revision'])).fetchone()
    if not row:
        raise ProfileError('接口配置版本不存在', 404)
    profile = json.loads(row['private_document'])
    profile.setdefault('source_key', current['source_key'])
    if kind is not None and profile['kind'] != kind:
        raise ProfileError('接口配置与生成类型不匹配')
    if require_enabled and profile['adapter'] not in KINDS.get(profile['kind'], set()):
        raise ProfileError(UNSUPPORTED_ADAPTER_ERROR, 409)
    if require_enabled and (not current['enabled'] or not profile['enabled']):
        raise ProfileError('接口配置已停用', 409)
    if require_enabled and not profile['api_key']:
        raise ProfileError('接口配置尚未填写API密钥', 409)
    return profile


def load_source_profile(kind, adapter):
    """Resolve the effective DB-managed base profile for (kind, adapter).

    Returns None only when no config:* row was ever imported for (kind, adapter).
    When the imported config:* row is active, returns it as-is.
    When the imported config:* row was deleted, never falls back to config.json:
    prefers an active enabled default custom profile for (kind, adapter) if one exists,
    otherwise returns the deleted tombstone (enabled=False, api_key='').
    """
    key = source_key_for(kind, adapter)
    if not key:
        return None
    db = task_db.get_db()
    try:
        current = db.execute(
            'SELECT id, revision, enabled, source_key, deleted_at FROM provider_profiles WHERE source_key=?',
            (key,),
        ).fetchone()
    except sqlite3.OperationalError:
        try:
            current = db.execute(
                'SELECT id, revision, enabled, source_key FROM provider_profiles WHERE source_key=?',
                (key,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    if not current:
        return None
    deleted_at = current['deleted_at'] if 'deleted_at' in current.keys() else None
    if deleted_at is not None:
        candidates = db.execute(
            '''SELECT id, revision, enabled, source_key FROM provider_profiles
               WHERE kind=? AND adapter=? AND deleted_at IS NULL AND enabled=1
               ORDER BY is_default DESC, name, id''',
            (kind, adapter),
        ).fetchall()
        first_enabled = None
        for cand in candidates:
            row = db.execute(
                'SELECT private_document FROM provider_profile_revisions WHERE profile_id=? AND revision=?',
                (cand['id'], cand['revision']),
            ).fetchone()
            if not row:
                continue
            profile = json.loads(row['private_document'])
            profile['source_key'] = cand['source_key']
            profile['enabled'] = bool(cand['enabled'])
            if profile.get('api_key'):
                return profile
            if first_enabled is None:
                first_enabled = profile
        if first_enabled is not None:
            return first_enabled
        row = db.execute(
            'SELECT private_document FROM provider_profile_revisions WHERE profile_id=? AND revision=?',
            (current['id'], current['revision']),
        ).fetchone()
        if not row:
            return None
        profile = json.loads(row['private_document'])
        profile['source_key'] = current['source_key']
        profile['enabled'] = False
        profile['api_key'] = ''
        profile['deleted_at'] = deleted_at
        return profile
    row = db.execute(
        'SELECT private_document FROM provider_profile_revisions WHERE profile_id=? AND revision=?',
        (current['id'], current['revision']),
    ).fetchone()
    if not row:
        return None
    profile = json.loads(row['private_document'])
    profile['source_key'] = current['source_key']
    profile['enabled'] = bool(current['enabled'])
    return profile


def list_profiles(kind=None):
    if kind is not None and kind not in KINDS:
        raise ProfileError('生成类型无效')
    rows = task_db.get_db().execute('''
        SELECT id FROM provider_profiles
        WHERE deleted_at IS NULL
        ORDER BY
            CASE kind WHEN 'image' THEN 1 WHEN 'video' THEN 2 WHEN 'audio' THEN 3 ELSE 4 END,
            name, id
    ''').fetchall()
    profiles = [public_profile(load_profile(row['id'])) for row in rows]
    return [p for p in profiles if kind is None or p['kind'] == kind]


def _bounded_int(value, minimum, maximum):
    if type(value) is int and minimum <= value <= maximum:
        return value
    return None


def _config_profile_data(config, kind, adapter):
    cupsy_source = config.get('deployment', {}).get('cupsy_source', {})
    cupsy_account = config.get('providers', {}).get('cupsy', {})
    if (kind, adapter) == ('image', 'ark'):
        view = config_v2.image_byteplus(config)
        default_endpoint = config_v2.DEFAULTS['providers']['byteplus']['endpoint']
        raw = {
            'endpoint': (view.get('endpoint') or default_endpoint).strip(),
            'model': str(view.get('model') or '').strip(),
        }
        for key in ('request_timeout_seconds', 'upload_timeout_seconds'):
            bounded = _bounded_int(view.get(key), 1, 3600)
            if bounded is not None:
                raw[key] = bounded
    elif (kind, adapter) == ('image', 'cupsy'):
        view = config_v2.image_cupsy(config)
        default_endpoint = config_v2.DEFAULTS['providers']['cupsy']['endpoint']
        raw = {
            'endpoint': (view.get('endpoint') or default_endpoint).strip(),
            'model': 'seedream-5.0-pro',
            'source_base_url': str(cupsy_source.get('base_url') or '').strip(),
        }
        ttl = _bounded_int(cupsy_source.get('asset_token_ttl_seconds'), 7200, 86400)
        if ttl is not None:
            raw['asset_token_ttl_seconds'] = ttl
        timeout = _bounded_int(view.get('request_timeout_seconds'), 1, 3600)
        if timeout is not None:
            raw['request_timeout_seconds'] = timeout
        attempts = _bounded_int(view.get('poll_max_attempts'), 1, 100000)
        if attempts is not None:
            raw['poll_max_attempts'] = attempts
    elif (kind, adapter) == ('video', 'ark'):
        view = config_v2.video_byteplus(config)
        poll = config_v2.polling(config, 'video')
        default_endpoint = config_v2.DEFAULTS['providers']['byteplus']['endpoint']
        raw = {
            'endpoint': (view.get('endpoint') or default_endpoint).strip(),
            'model': str(view.get('model') or '').strip(),
            'fast_model': str(view.get('fast_model') or '').strip(),
        }
        ep25 = str(view.get('seedance_2_5_model') or '').strip()
        if ep25 and not config_v2.is_placeholder_endpoint_id(ep25):
            raw['seedance_2_5_model'] = ep25
        for key in ('request_timeout_seconds', 'upload_timeout_seconds'):
            bounded = _bounded_int(view.get(key), 1, 3600)
            if bounded is not None:
                raw[key] = bounded
        interval = _bounded_int(poll.get('poll_interval_seconds'), 1, 300)
        if interval is not None:
            raw['poll_interval_seconds'] = interval
        attempts = _bounded_int(poll.get('poll_max_attempts'), 1, 100000)
        if attempts is not None:
            raw['poll_max_attempts'] = attempts
    elif (kind, adapter) == ('video', 'cupsy'):
        view = config_v2.video_cupsy(config)
        poll = config_v2.polling(config, 'video')
        default_endpoint = config_v2.DEFAULTS['providers']['cupsy']['endpoint']
        model = str(view.get('model') or '').strip()
        if model not in {'', 'seedance-2.5', 'seedance-2.5-moderated', 'dreamina-seedance-2.5'}:
            model = 'seedance-2.5'
        raw = {
            'endpoint': (view.get('endpoint') or default_endpoint).strip(),
            'model': model or 'seedance-2.5',
            'source_base_url': str(view.get('source_base_url') or '').strip(),
        }
        ttl = _bounded_int(view.get('asset_token_ttl_seconds'), 7200, 86400)
        if ttl is not None:
            raw['asset_token_ttl_seconds'] = ttl
        timeout = _bounded_int(cupsy_account.get('request_timeout_seconds'), 1, 3600)
        if timeout is not None:
            raw['request_timeout_seconds'] = timeout
        interval = _bounded_int(poll.get('poll_interval_seconds'), 1, 300)
        if interval is not None:
            raw['poll_interval_seconds'] = interval
        attempts = _bounded_int(poll.get('poll_max_attempts'), 1, 100000)
        if attempts is not None:
            raw['poll_max_attempts'] = attempts
    elif (kind, adapter) == ('audio', 'cupsy'):
        view = config_v2.audio_cupsy(config)
        poll = config_v2.polling(config, 'audio')
        default_endpoint = config_v2.DEFAULTS['providers']['cupsy']['endpoint']
        model = str(view.get('model') or '').strip()
        if model not in {'', 'seed-audio-1.0'}:
            model = 'seed-audio-1.0'
        raw = {
            'endpoint': (view.get('endpoint') or default_endpoint).strip(),
            'model': model or 'seed-audio-1.0',
            'source_base_url': str(view.get('source_base_url') or '').strip(),
        }
        ttl = _bounded_int(view.get('asset_token_ttl_seconds'), 7200, 86400)
        if ttl is not None:
            raw['asset_token_ttl_seconds'] = ttl
        timeout = _bounded_int(cupsy_account.get('request_timeout_seconds'), 1, 3600)
        if timeout is not None:
            raw['request_timeout_seconds'] = timeout
        interval = _bounded_int(poll.get('poll_interval_seconds'), 1, 300)
        if interval is not None:
            raw['poll_interval_seconds'] = interval
        attempts = _bounded_int(poll.get('poll_max_attempts'), 1, 100000)
        if attempts is not None:
            raw['poll_max_attempts'] = attempts
    else:
        raise ProfileError(UNSUPPORTED_ADAPTER_ERROR)
    api_key = str(view.get('api_key') or '').strip()
    if any(ord(c) < 32 for c in api_key) or len(api_key) > 8192:
        api_key = ''
    return _settings(raw, kind, adapter), api_key


def _unique_config_name(db, kind, base_name):
    candidate = base_name
    suffix = 1
    while db.execute('SELECT 1 FROM provider_profiles WHERE kind=? AND name=?', (kind, candidate)).fetchone():
        candidate = f'{base_name}（配置）' if suffix == 1 else f'{base_name}（配置{suffix}）'
        suffix += 1
    return candidate


def sync_config_profiles(config):
    """Idempotently import the 5 base config.json views into provider_profiles without overwriting edits."""
    init_profiles_db()
    db = task_db.get_db()
    created = []
    try:
        db.execute('BEGIN IMMEDIATE')
        now = task_db.utcnow()
        for source_key, kind, adapter, default_name in CONFIG_PROFILES:
            if db.execute('SELECT 1 FROM provider_profiles WHERE source_key=?', (source_key,)).fetchone():
                continue
            settings, api_key = _config_profile_data(config, kind, adapter)
            name = _unique_config_name(db, kind, default_name)
            profile = {
                'id': uuid.uuid4().hex,
                'revision': 1,
                'kind': kind,
                'adapter': adapter,
                'name': name,
                'enabled': True,
                'is_default': False,
                'settings': settings,
                'api_key': api_key,
                'asset_scope': uuid.uuid4().hex,
                'source_key': source_key,
                'created_at': now,
                'updated_at': now,
            }
            db.execute(
                '''INSERT INTO provider_profiles
                   (id, revision, kind, adapter, name, enabled, is_default, created_at, updated_at, source_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (profile['id'], profile['revision'], kind, adapter, name, 1, 0, now, now, source_key),
            )
            _snapshot(profile)
            created.append(public_profile(profile))
        db.commit()
        return created
    except Exception:
        db.rollback()
        raise


def _url(value, optional=False):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value:
        raise ProfileError('接口地址必须为不含凭据的HTTP(S)地址')
    if not value and optional:
        return ''
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ProfileError('接口地址格式无效')
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or '?' in value or '#' in value:
        raise ProfileError('接口地址必须为HTTP(S)，不能包含账号、密码、查询参数或片段')
    if port is not None and not 1 <= port <= 65535:
        raise ProfileError('接口端口无效')
    return value.rstrip('/')


def _settings(data, kind, adapter):
    allowed = set(COMMON_SETTINGS)
    if adapter == 'cupsy':
        allowed |= {'source_base_url', 'asset_token_ttl_seconds'}
    if kind == 'image' and adapter == 'ark':
        allowed |= {'capability_model'}
    if kind == 'video' and adapter == 'ark':
        allowed |= {'fast_model', 'seedance_2_5_model'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ProfileError('接口设置包含不支持的字段')
    result = dict(data)
    result['endpoint'] = _url(result.get('endpoint'))
    for key, value in result.items():
        if key == 'endpoint':
            continue
        if key == 'source_base_url':
            result[key] = _url(value, optional=True)
        elif key == 'capability_model':
            if not isinstance(value, str) or value.strip() not in ARK_IMAGE_CAPABILITY_MODELS:
                raise ProfileError('底层能力模型版本无效，仅支持自动识别、Seedream 5.5 或 Seedream 5.0 Pro')
            result[key] = value.strip()
        elif key in ('model', 'fast_model', 'seedance_2_5_model'):
            if not isinstance(value, str) or len(value) > 240 or value and not re.fullmatch(r'[A-Za-z0-9_.:/-]+', value):
                raise ProfileError('模型名称或映射无效')
            if key == 'seedance_2_5_model' and value and (value.lower() == 'ep-your-endpoint-id' or value.lower().startswith('ep-your-')):
                raise ProfileError(ENDPOINT_ID_PLACEHOLDER_ERROR)
        else:
            if key == 'asset_token_ttl_seconds' and (type(value) is not int or not 7200 <= value <= 86400):
                raise ProfileError('素材来源签名有效期至少7200秒，且不得超过86400秒')
            maximum = 3600 if key in TIMEOUTS else 86400 if key == 'asset_token_ttl_seconds' else 100000 if key == 'poll_max_attempts' else 300
            if type(value) is not int or not 1 <= value <= maximum:
                raise ProfileError('超时、轮询或有效期必须为范围内正整数')
    if adapter == 'cupsy':
        supported = {
            'image': {'seedream-5.0-pro'},
            'audio': {'seed-audio-1.0'},
            'video': {'seedance-2.5', 'seedance-2.5-moderated', 'dreamina-seedance-2.5'},
        }[kind]
        model = result.get('model', '')
        if model and model not in supported:
            label = {'image': '图片', 'audio': '音频', 'video': '视频'}[kind]
            choices = '、'.join(sorted(supported))
            raise ProfileError(f'Cupsy {label}适配器仅支持 {choices}；留空使用默认模型')
        if kind == 'video' and model == 'dreamina-seedance-2.5':
            result['model'] = 'seedance-2.5'
    return result


def _snapshot(profile):
    task_db.get_db().execute('INSERT INTO provider_profile_revisions VALUES (?,?,?)',
                            (profile['id'], profile['revision'], json.dumps(profile, ensure_ascii=False)))


def _update_head(profile):
    task_db.get_db().execute('''UPDATE provider_profiles SET revision=?,name=?,enabled=?,is_default=?,updated_at=? WHERE id=?''',
                            (profile['revision'], profile['name'], int(profile['enabled']), int(profile['is_default']), profile['updated_at'], profile['id']))


def save_profile(data, profile_id=None, *, return_synced=False):
    if not isinstance(data, dict) or set(data) - {'revision', 'name', 'kind', 'adapter', 'enabled', 'is_default', 'settings', 'api_key', 'clear_api_key', 'sync_adapter_api_key'}:
        raise ProfileError('接口配置字段无效')
    sync_adapter = data.get('sync_adapter_api_key', False)
    if type(sync_adapter) is not bool:
        raise ProfileError('同步同服务商密钥选项必须为布尔值')
    db = task_db.get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        previous = load_profile(profile_id) if profile_id else None
        if previous:
            if type(data.get('revision')) is not int or data['revision'] != previous['revision']:
                raise ProfileError('接口配置已改变，请重新载入', 409)
            if any(key in data and data[key] != previous[key] for key in ('kind', 'adapter')):
                raise ProfileError('生成类型和适配器创建后不可更改')
        now = task_db.utcnow()
        result = dict(previous) if previous else {
            'id': uuid.uuid4().hex, 'revision': 0, 'enabled': True, 'is_default': False,
            'api_key': '', 'created_at': now, 'asset_scope': uuid.uuid4().hex, 'source_key': None,
        }
        result.setdefault('source_key', None)
        for key in ('name', 'kind', 'adapter', 'enabled', 'is_default'):
            if key in data:
                result[key] = data[key]
        kind, adapter = result.get('kind'), result.get('adapter')
        if not isinstance(kind, str) or kind not in KINDS or not isinstance(adapter, str) or adapter not in KINDS[kind]:
            raise ProfileError(UNSUPPORTED_ADAPTER_ERROR)
        if not isinstance(result.get('name'), str) or not result['name'].strip() or len(result['name']) > 100 or any(ord(c) < 32 for c in result['name']):
            raise ProfileError('配置名称须为1至100个字符')
        result['name'] = result['name'].strip()
        if type(result['enabled']) is not bool or type(result['is_default']) is not bool:
            raise ProfileError('启用与默认选项必须为布尔值')
        if not result['enabled']:
            result['is_default'] = False
        settings = dict(previous['settings']) if previous else {}
        if 'settings' in data:
            if not isinstance(data['settings'], dict):
                raise ProfileError('接口设置必须为对象')
            allowed = (
                COMMON_SETTINGS
                | ({'source_base_url', 'asset_token_ttl_seconds'} if adapter == 'cupsy' else set())
                | ({'capability_model'} if kind == 'image' and adapter == 'ark' else set())
                | ({'fast_model', 'seedance_2_5_model'} if kind == 'video' and adapter == 'ark' else set())
            )
            if set(data['settings']) - allowed:
                raise ProfileError('接口设置包含不支持的字段')
            for setting, value in data['settings'].items():
                if value is None:
                    settings.pop(setting, None)
                else:
                    settings[setting] = value
        result['settings'] = _settings(settings, kind, adapter)
        clear = data.get('clear_api_key', False)
        if type(clear) is not bool:
            raise ProfileError('清除密钥选项必须为布尔值')
        key = data.get('api_key', '')
        if not isinstance(key, str) or len(key) > 8192 or (key.strip() and any(ord(c) < 32 for c in key)):
            raise ProfileError('API密钥格式无效')
        if clear and key.strip():
            raise ProfileError('不能同时设置和清除API密钥')
        key_changed_explicitly = False
        if clear:
            result['api_key'] = ''
            key_changed_explicitly = True
        elif key.strip():
            result['api_key'] = key.strip()
            key_changed_explicitly = True
        if previous and (previous['api_key'] != result['api_key'] or any(previous['settings'].get(k) != settings.get(k) for k in ('endpoint', 'source_base_url'))):
            result['asset_scope'] = uuid.uuid4().hex
        result.update(revision=result['revision'] + 1, updated_at=now)
        # Switching defaults is one transaction, including revisions of displaced defaults.
        if result['is_default']:
            defaults = db.execute('SELECT id FROM provider_profiles WHERE kind=? AND is_default=1 AND id<>? AND deleted_at IS NULL', (kind, result['id'])).fetchall()
            for row in defaults:
                displaced = load_profile(row['id'])
                displaced.update(is_default=False, revision=displaced['revision'] + 1, updated_at=now)
                _update_head(displaced)
                _snapshot(displaced)
        if previous:
            _update_head(result)
        else:
            db.execute(
                '''INSERT INTO provider_profiles
                   (id, revision, kind, adapter, name, enabled, is_default, created_at, updated_at, source_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (result['id'], result['revision'], kind, adapter, result['name'], int(result['enabled']), int(result['is_default']), now, now, result['source_key']),
            )
        _snapshot(result)
        synced_ids = []
        if sync_adapter and key_changed_explicitly:
            peers = db.execute(
                'SELECT id FROM provider_profiles WHERE adapter=? AND id<>? AND deleted_at IS NULL ORDER BY kind, name, id',
                (adapter, result['id']),
            ).fetchall()
            for row in peers:
                peer = load_profile(row['id'])
                if peer['api_key'] == result['api_key']:
                    continue
                peer.update(
                    api_key=result['api_key'],
                    asset_scope=uuid.uuid4().hex,
                    revision=peer['revision'] + 1,
                    updated_at=now,
                )
                _update_head(peer)
                _snapshot(peer)
                synced_ids.append(peer['id'])
        db.commit()
        public = public_profile(result)
        return (public, synced_ids) if return_synced else public
    except sqlite3.IntegrityError:
        db.rollback()
        raise ProfileError('同一生成类型的配置名称已存在', 409)
    except Exception:
        db.rollback()
        raise


def delete_profile(profile_id, revision):
    """Logically delete a profile (including config-imported defaults) while preserving historical revisions."""
    db = task_db.get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        previous = load_profile(profile_id)
        if type(revision) is not int or revision < 1 or revision != previous['revision']:
            raise ProfileError('接口配置已改变，请重新载入', 409)
        now = task_db.utcnow()
        next_rev = previous['revision'] + 1
        result = dict(previous)
        result.update(
            revision=next_rev,
            enabled=False,
            is_default=False,
            api_key='',
            updated_at=now,
            deleted_at=now,
        )
        db.execute(
            '''UPDATE provider_profiles
               SET revision=?, name=?, enabled=0, is_default=0, updated_at=?, deleted_at=?
               WHERE id=?''',
            (next_rev, f'__deleted__:{profile_id}', now, now, profile_id),
        )
        _snapshot(result)
        db.commit()
        return public_profile(result)
    except Exception:
        db.rollback()
        raise


_KIND_LABELS = {'image': '图像生成', 'video': '视频生成', 'audio': '音频生成'}
_ADAPTER_LABELS = {'ark': 'BytePlus Ark', 'cupsy': 'Cupsy'}
_CUPSY_MODELS = {
    'image': {'seedream-5.0-pro'},
    'audio': {'seed-audio-1.0'},
    'video': {'seedance-2.5', 'seedance-2.5-moderated', 'dreamina-seedance-2.5'},
}
_CUPSY_DEFAULT_MODELS = {'image': 'seedream-5.0-pro', 'audio': 'seed-audio-1.0', 'video': 'seedance-2.5'}
_KEY_PLACEHOLDER_PATTERNS = ('your-', 'your_', 'replace', 'changeme', 'placeholder', 'example', '<', '>', 'sk-xxx')


def _is_placeholder_value(value):
    text = str(value or '').strip().lower()
    if not text:
        return False
    return (
        text == config_v2.ENDPOINT_ID_PLACEHOLDER
        or text.startswith('ep-your-')
        or '<' in text
        or '>' in text
    )


def _is_placeholder_key(value):
    text = str(value or '').strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _KEY_PLACEHOLDER_PATTERNS)


def _is_local_or_private_host(hostname):
    host = (hostname or '').strip().lower().rstrip('.')
    if not host:
        return True
    if host in ('localhost', 'localhost.localdomain') or host.endswith(('.localhost', '.local', '.internal')):
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_unspecified or addr.is_reserved
    except ValueError:
        return False


def _validate_url_check(value, *, label, optional=False):
    """Static URL format/scheme validator for zero-cost preflight (no network calls)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if optional:
            return None, None
        return 'error', f'尚未填写{label}，请输入有效的 HTTP(S) 地址。'
    if not isinstance(value, str):
        return 'error', f'{label}必须为字符串。'
    cleaned = value.strip()
    if len(cleaned) > 2048 or any(c.isspace() or ord(c) < 32 for c in cleaned) or '\\' in cleaned:
        return 'error', f'{label}包含非法空格、控制字符或反斜杠。'
    try:
        parsed = urlsplit(cleaned)
        port = parsed.port
    except ValueError:
        return 'error', f'{label}格式无效，请检查协议、主机名与端口。'
    if parsed.scheme not in ('http', 'https'):
        return 'error', f'{label}仅支持 http:// 或 https:// 协议。'
    if not parsed.hostname:
        return 'error', f'{label}缺少有效主机名。'
    if parsed.username is not None or parsed.password is not None:
        return 'error', f'{label}不能包含内嵌账号或密码。'
    if parsed.query or parsed.fragment or '?' in cleaned or '#' in cleaned:
        return 'error', f'{label}不能包含查询参数（?）或片段（#）。'
    if port is not None and not 1 <= port <= 65535:
        return 'error', f'{label}端口号须在 1 至 65535 之间。'
    return parsed, None


def _coerce_preflight_int(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and value.strip():
        try:
            num = int(value.strip())
            if str(num) == value.strip():
                return num
        except ValueError:
            return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _sanitize_preflight_text(text, raw_key=''):
    from task_public import mask_endpoint_ids
    cleaned = mask_endpoint_ids(str(text or ''))
    if raw_key and len(raw_key) >= 4 and raw_key in cleaned:
        cleaned = cleaned.replace(raw_key, '***')
    return cleaned


def check_profile(profile_id=None, overrides=None):
    """Zero-cost local/static configuration preflight.

    Never initiates external HTTP requests, never invokes paid provider APIs,
    never mutates database state, and never echoes plaintext API keys or raw ep- IDs.
    """
    if overrides is not None and not isinstance(overrides, dict):
        raise ProfileError('预检请求必须为对象')
    overrides = overrides or {}
    allowed_override_keys = {'name', 'kind', 'adapter', 'enabled', 'is_default', 'settings', 'api_key', 'clear_api_key'}
    if set(overrides) - allowed_override_keys:
        raise ProfileError('预检请求包含不支持的字段')

    base = load_profile(profile_id) if profile_id is not None else None
    kind = base['kind'] if base else overrides.get('kind')
    adapter = base['adapter'] if base else overrides.get('adapter')
    enabled = overrides['enabled'] if 'enabled' in overrides else (base['enabled'] if base else True)
    settings = dict(base.get('settings') or {}) if base else {}
    if 'settings' in overrides:
        if not isinstance(overrides['settings'], dict):
            raise ProfileError('接口设置必须为对象')
        for key, value in overrides['settings'].items():
            if value is None:
                settings.pop(key, None)
            else:
                settings[key] = value

    clear_key = bool(overrides.get('clear_api_key', False))
    override_key = overrides.get('api_key')
    if not isinstance(override_key, str):
        override_key = ''
    if clear_key:
        raw_key = ''
    elif override_key.strip():
        raw_key = override_key.strip()
    else:
        saved_key = (base or {}).get('api_key')
        raw_key = saved_key if isinstance(saved_key, str) else ''

    checks = []

    def add(key, label, status, message):
        checks.append({
            'key': key,
            'label': label,
            'status': status,
            'message': _sanitize_preflight_text(message, raw_key),
        })

    # 1. Enabled status
    if type(enabled) is not bool:
        add('enabled', '启用状态', 'error', '启用状态必须为布尔值。')
    elif enabled:
        add('enabled', '启用状态', 'ok', '配置已启用，可在画布与工具页选用。')
    else:
        add('enabled', '启用状态', 'warn', '当前配置已停用，启用后才可用于生成任务。')

    # 2. Kind & adapter compatibility
    valid_pair = isinstance(kind, str) and kind in KINDS and isinstance(adapter, str) and adapter in KINDS[kind]
    if not valid_pair:
        add('kind_adapter', '业务类型与适配器', 'error', UNSUPPORTED_ADAPTER_ERROR + '。')
    else:
        add('kind_adapter', '业务类型与适配器', 'ok',
            f'适配器与业务类型匹配（{_KIND_LABELS.get(kind, kind)} · {_ADAPTER_LABELS.get(adapter, adapter)}）。')

    # 3. API Key presence & format (never echoed)
    if not raw_key:
        add('api_key', 'API Key', 'error', '尚未配置 API Key，无法发起生成请求，请填写有效密钥。')
    elif len(raw_key) > 8192 or any(ord(c) < 32 for c in raw_key):
        add('api_key', 'API Key', 'error', 'API Key 包含非法控制字符或超过长度上限，请重新输入。')
    elif _is_placeholder_key(raw_key):
        add('api_key', 'API Key', 'warn', 'API Key 疑似示例占位文本，请确认已替换为真实密钥（已脱敏，不回显）。')
    else:
        add('api_key', 'API Key', 'ok', 'API Key 已配置（已脱敏保护，不回显明文）。')

    # 4. Base URL (endpoint) protocol & format
    parsed_ep, ep_err = _validate_url_check(settings.get('endpoint'), label='接口地址', optional=False)
    if ep_err:
        add('endpoint', '接口地址', 'error', ep_err)
    elif parsed_ep.scheme == 'http':
        add('endpoint', '接口地址', 'warn', '接口地址格式有效，但当前使用 HTTP 明文协议，建议生产环境改用 HTTPS。')
    else:
        add('endpoint', '接口地址', 'ok', '接口地址格式有效（HTTPS）。')

    # 5. Model / endpoint ID completeness
    if valid_pair:
        model_val = str(settings.get('model') or '').strip()
        model_pattern = re.compile(r'^[A-Za-z0-9_.:/-]{1,240}$')
        if adapter == 'ark' and kind == 'image':
            if not model_val:
                add('model', '模型 / 接入点', 'warn', '未填写默认模型，将按运行时默认 Seedream 模型回退；建议显式填写模型标识或推理接入点 ID。')
            elif _is_placeholder_value(model_val):
                add('model', '模型 / 接入点', 'error', '默认模型仍是示例占位文本，请填写有效模型名称或真实接入点 ID。')
            elif not model_pattern.fullmatch(model_val):
                add('model', '模型 / 接入点', 'error', '默认模型或接入点 ID 包含不支持的字符或长度超限。')
            elif model_val.lower().startswith('ep-'):
                add('model', '模型 / 接入点', 'ok', '已配置 BytePlus Ark 图像推理接入点 ID（已脱敏），格式完整。')
            else:
                add('model', '模型 / 接入点', 'ok', f'默认图像模型格式完整（{model_val}）。')
            raw_cap = settings.get('capability_model')
            if raw_cap is not None and (not isinstance(raw_cap, str) or raw_cap.strip() not in ARK_IMAGE_CAPABILITY_MODELS):
                add('capability_model', '模型能力与估价', 'error', '底层模型能力版本无效，请选择自动识别、Seedream 5.5 或 Seedream 5.0 Pro。')
            else:
                import seedream55
                declared_cap = (raw_cap or '').strip() if isinstance(raw_cap, str) else ''
                effective_cap = seedream55.capability_model(model_val or 'seedream-5-0-pro', declared=declared_cap)
                is_55 = effective_cap.lower() in seedream55.ALIASES
                if declared_cap == seedream55.MODEL:
                    add('capability_model', '模型能力与估价', 'ok', '已显式声明为 Seedream 5.5（开放 1.5K 与原生透明背景；按 5.5 费率估算：1K–1.5K 约 $0.020/张、2K 约 $0.035/张）。')
                elif declared_cap == seedream55.MODEL_50_PRO:
                    add('capability_model', '模型能力与估价', 'ok', '已显式声明为 Seedream 5.0 Pro（按 5.0 Pro 费率估算：1K 约 $0.045/张、2K 约 $0.090/张）。')
                elif is_55:
                    add('capability_model', '模型能力与估价', 'ok', '自动识别为 Seedream 5.5（开放 1.5K 与原生透明背景；按 5.5 费率估算：1K–1.5K 约 $0.020/张、2K 约 $0.035/张）。')
                elif model_val.lower().startswith('ep-'):
                    add('capability_model', '模型能力与估价', 'warn', '推理接入点未声明底层模型版本，当前将回退按 Seedream 5.0 Pro 能力与兜底费率估算（1K 约 $0.045/张、2K 约 $0.090/张，且不开放 1.5K）；若实际为 Seedream 5.5，请在「底层模型能力版本」中显式选择 Seedream 5.5。')
                else:
                    add('capability_model', '模型能力与估价', 'ok', '自动识别为 Seedream 5.0 Pro（按 5.0 Pro 费率估算：1K 约 $0.045/张、2K 约 $0.090/张）。')
        elif adapter == 'ark' and kind == 'video':
            fast_val = str(settings.get('fast_model') or '').strip()
            v25_val = str(settings.get('seedance_2_5_model') or '').strip()
            all_vals = [('Seedance 2.0', model_val), ('Seedance 2.0 Fast', fast_val), ('Seedance 2.5', v25_val)]
            if not any(v for _, v in all_vals):
                add('model', '模型 / 接入点', 'error', '未填写任何视频模型或推理接入点 ID，至少需配置 Seedance 2.0 或 Seedance 2.5 接入点。')
            elif any(_is_placeholder_value(v) for _, v in all_vals if v):
                add('model', '模型 / 接入点', 'error', '视频接入点中存在示例占位文本，请替换为 BytePlus 控制台真实接入点 ID 或留空。')
            elif any(not model_pattern.fullmatch(v) for _, v in all_vals if v):
                add('model', '模型 / 接入点', 'error', '视频模型或接入点 ID 包含不支持的字符或长度超限。')
            elif v25_val and not v25_val.lower().startswith('ep-'):
                add('model', '模型 / 接入点', 'warn', 'Seedance 2.5 接入点通常为 BytePlus 控制台 ep-... 格式，请核对填写是否正确。')
            elif not model_val:
                add('model', '模型 / 接入点', 'warn', '未填写 Seedance 2.0 默认接入点 ID，仅已配置的对应视频版本可用。')
            else:
                add('model', '模型 / 接入点', 'ok', '视频模型 / 推理接入点配置格式完整（接入点 ID 已脱敏）。')
        elif adapter == 'cupsy':
            supported = _CUPSY_MODELS[kind]
            label = {'image': '图像', 'video': '视频', 'audio': '音频'}[kind]
            if model_val and model_val not in supported:
                choices = '、'.join(sorted(supported))
                add('model', '模型 / 接入点', 'error', f'Cupsy {label}适配器仅支持 {choices}，请修正或留空使用默认模型。')
            else:
                effective = _CUPSY_DEFAULT_MODELS[kind] if not model_val else ('seedance-2.5' if model_val == 'dreamina-seedance-2.5' else model_val)
                add('model', '模型 / 接入点', 'ok', f'模型与 Cupsy {label}适配器匹配（{effective}）。')

    # 6. Cupsy public media source & token TTL
    if adapter == 'cupsy':
        src_val = settings.get('source_base_url')
        if src_val is None or (isinstance(src_val, str) and not src_val.strip()):
            add('cupsy_source', '公网素材源地址', 'warn', '未填写公网素材源地址（将沿用部署默认配置）；如需使用参考素材，请确认已配置公网 HTTPS 地址。')
        else:
            parsed_src, src_err = _validate_url_check(src_val, label='公网素材源地址', optional=False)
            if src_err:
                add('cupsy_source', '公网素材源地址', 'error', src_err)
            elif _is_local_or_private_host(parsed_src.hostname):
                add('cupsy_source', '公网素材源地址', 'warn', '公网素材源地址指向本地或内网地址，Cupsy 云端服务可能无法回源拉取参考素材。')
            elif parsed_src.scheme != 'https':
                add('cupsy_source', '公网素材源地址', 'warn', '公网素材源地址使用 HTTP 协议，Cupsy 云端拉取参考素材通常要求有效 HTTPS 证书。')
            else:
                add('cupsy_source', '公网素材源地址', 'ok', '公网素材源地址格式有效（HTTPS 公网形态）。')

        ttl_raw = settings.get('asset_token_ttl_seconds')
        if ttl_raw is None or ttl_raw == '':
            add('cupsy_ttl', '素材签名有效期', 'ok', '未单独设置，将沿用服务端默认有效期（≥ 7200 秒）。')
        else:
            ttl_val = _coerce_preflight_int(ttl_raw)
            if ttl_val is None or not 7200 <= ttl_val <= 86400:
                add('cupsy_ttl', '素材签名有效期', 'error', '素材签名有效期须为 7200 至 86400 秒之间的整数。')
            else:
                add('cupsy_ttl', '素材签名有效期', 'ok', f'素材签名有效期在合法范围内（{ttl_val} 秒）。')

    # 7. Advanced timeouts & polling bounds (when specified)
    numeric_keys = (*sorted(TIMEOUTS), 'poll_interval_seconds', 'poll_max_attempts')
    bad_numeric = []
    any_numeric = False
    for key in numeric_keys:
        if key not in settings or settings[key] is None or settings[key] == '':
            continue
        any_numeric = True
        maximum = 3600 if key in TIMEOUTS else (100000 if key == 'poll_max_attempts' else 300)
        num = _coerce_preflight_int(settings[key])
        if num is None or not 1 <= num <= maximum:
            bad_numeric.append(key)
    if bad_numeric:
        add('timeouts', '超时与轮询参数', 'error', '部分高级超时或轮询参数不是合法范围内的正整数，请检查高级参数。')
    elif any_numeric:
        add('timeouts', '超时与轮询参数', 'ok', '高级超时与轮询参数均在合法范围内。')

    statuses = {item['status'] for item in checks}
    if 'error' in statuses:
        overall = 'error'
        summary = '发现配置错误，请先修正标红项再发起生成（零计费本地预检，未发起外部请求）。'
    elif 'warn' in statuses:
        overall = 'warn'
        summary = '基础配置有效，但存在提醒项，建议核对后再使用（零计费本地预检，未发起外部请求）。'
    else:
        overall = 'ok'
        summary = '全部本地静态检查通过（零计费预检，未发起外部请求）。'

    return {
        'status': overall,
        'summary': _sanitize_preflight_text(summary, raw_key),
        'zero_cost': True,
        'external_calls': 0,
        'checks': checks,
    }
