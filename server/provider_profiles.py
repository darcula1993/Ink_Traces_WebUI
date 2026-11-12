"""Private, immutable provider revisions. Public serializers never return credentials."""
import json
import re
import sqlite3
import uuid
from urllib.parse import urlsplit

import tasks as task_db

KINDS = {'image': {'ark', 'cupsy'}, 'video': {'ark', 'cupsy'}, 'audio': {'cupsy'}}
UNSUPPORTED_ADAPTER_ERROR = '生成类型与适配器组合不受支持'
ENDPOINT_ID_PLACEHOLDER_ERROR = 'Seedance 2.5 接入点ID仍是示例占位，请填写 BytePlus 控制台的真实 ep-... 接入点ID或留空'
TIMEOUTS = {'request_timeout_seconds', 'upload_timeout_seconds', 'poll_timeout_seconds', 'download_timeout_seconds'}
COMMON_SETTINGS = {'endpoint', 'model', 'poll_interval_seconds', 'poll_max_attempts'} | TIMEOUTS


class ProfileError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def init_profiles_db():
    db = task_db.get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS provider_profiles (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL, kind TEXT NOT NULL,
            adapter TEXT NOT NULL, name TEXT NOT NULL, enabled INTEGER NOT NULL,
            is_default INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
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
    db.commit()


def public_profile(profile):
    result = {key: profile[key] for key in ('id', 'name', 'kind', 'adapter', 'enabled', 'is_default', 'revision', 'settings', 'asset_scope', 'created_at', 'updated_at')}
    result['has_api_key'] = bool(profile['api_key'])
    result['api_key_mask'] = '••••••••' if profile['api_key'] else ''
    return result


def load_profile(profile_id, revision=None, *, kind=None, require_enabled=False):
    if not isinstance(profile_id, str) or not re.fullmatch(r'[0-9a-f]{32}', profile_id):
        raise ProfileError('接口配置不存在', 404)
    if revision is not None and (type(revision) is not int or revision < 1):
        raise ProfileError('revision 必须为正整数')
    db = task_db.get_db()
    current = db.execute('SELECT * FROM provider_profiles WHERE id=?', (profile_id,)).fetchone()
    if not current:
        raise ProfileError('接口配置不存在', 404)
    row = db.execute('SELECT private_document FROM provider_profile_revisions WHERE profile_id=? AND revision=?',
                     (profile_id, revision if revision is not None else current['revision'])).fetchone()
    if not row:
        raise ProfileError('接口配置版本不存在', 404)
    profile = json.loads(row['private_document'])
    if kind is not None and profile['kind'] != kind:
        raise ProfileError('接口配置与生成类型不匹配')
    if require_enabled and profile['adapter'] not in KINDS.get(profile['kind'], set()):
        raise ProfileError(UNSUPPORTED_ADAPTER_ERROR, 409)
    if require_enabled and (not current['enabled'] or not profile['enabled']):
        raise ProfileError('接口配置已停用', 409)
    if require_enabled and not profile['api_key']:
        raise ProfileError('接口配置尚未填写API密钥', 409)
    return profile


def list_profiles(kind=None):
    if kind is not None and kind not in KINDS:
        raise ProfileError('生成类型无效')
    rows = task_db.get_db().execute('SELECT id FROM provider_profiles ORDER BY kind, name, id').fetchall()
    profiles = [public_profile(load_profile(row['id'])) for row in rows]
    return [p for p in profiles if kind is None or p['kind'] == kind]


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


def save_profile(data, profile_id=None):
    if not isinstance(data, dict) or set(data) - {'revision', 'name', 'kind', 'adapter', 'enabled', 'is_default', 'settings', 'api_key', 'clear_api_key'}:
        raise ProfileError('接口配置字段无效')
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
            'api_key': '', 'created_at': now, 'asset_scope': uuid.uuid4().hex,
        }
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
            allowed = COMMON_SETTINGS | ({'source_base_url', 'asset_token_ttl_seconds'} if adapter == 'cupsy' else set()) | ({'fast_model', 'seedance_2_5_model'} if kind == 'video' and adapter == 'ark' else set())
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
        if clear:
            result['api_key'] = ''
        elif key.strip():
            result['api_key'] = key.strip()
        if previous and (previous['api_key'] != result['api_key'] or any(previous['settings'].get(k) != settings.get(k) for k in ('endpoint', 'source_base_url'))):
            result['asset_scope'] = uuid.uuid4().hex
        result.update(revision=result['revision'] + 1, updated_at=now)
        # Switching defaults is one transaction, including revisions of displaced defaults.
        if result['is_default']:
            defaults = db.execute('SELECT id FROM provider_profiles WHERE kind=? AND is_default=1 AND id<>?', (kind, result['id'])).fetchall()
            for row in defaults:
                displaced = load_profile(row['id'])
                displaced.update(is_default=False, revision=displaced['revision'] + 1, updated_at=now)
                _update_head(displaced)
                _snapshot(displaced)
        if previous:
            _update_head(result)
        else:
            db.execute('INSERT INTO provider_profiles VALUES (?,?,?,?,?,?,?,?,?)',
                       (result['id'], result['revision'], kind, adapter, result['name'], int(result['enabled']), int(result['is_default']), now, now))
        _snapshot(result)
        db.commit()
        return public_profile(result)
    except sqlite3.IntegrityError:
        db.rollback()
        raise ProfileError('同一生成类型的配置名称已存在', 409)
    except Exception:
        db.rollback()
        raise
