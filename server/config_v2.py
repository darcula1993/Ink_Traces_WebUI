"""config.json v2: load, validate and expose runtime views (doc/development.md, 配置).

v2 separates accounts (``providers``) from capabilities (``generation``) and keeps
deployment items under ``deployment``. Only v2 is accepted: a v1 file, unknown keys or
bad types stop the service with a report that names key paths but never values.

CLI (used by start.sh/setup.sh; prints no credentials):
    python3 server/config_v2.py check [CONFIG]
    python3 server/config_v2.py get <dotted.path> [CONFIG]   # server./client./deployment. only
"""
import copy
import json
import os
import sys
from urllib.parse import urlsplit

CONFIG_VERSION = 2
ENDPOINT_ID_PLACEHOLDER = 'ep-your-endpoint-id'
LEGACY_TOP_LEVEL = ('api', 'video', 'audio', 'openai')
MIGRATE_HINT = '请先停服务并运行 scripts/migrate-config-v2.py（默认试运行）迁移到 v2'

# Non-sensitive built-in defaults. Credentials default to empty; the example file is
# documentation only and is never merged at runtime.
DEFAULTS = {
    'config_version': CONFIG_VERSION,
    'auth': {'username': '', 'password': '', 'secret_key': ''},
    'server': {
        'host': '0.0.0.0',
        'port': 5000,
        'cors_origins': [],
        'request_timeout_seconds': 120,
        'poll_timeout_seconds': 30,
        'download_timeout_seconds': 120,
        'worker_concurrency': 3,
        'polling_concurrency': 2,
        'asset_concurrency': 1,
        'worker_lease_seconds': 900,
        'worker_heartbeat_seconds': 10,
        'gunicorn_max_requests': 1500,
        'gunicorn_max_requests_jitter': 150,
        'cleanup_interval_seconds': 3600,
        'orphan_grace_hours': 24,
    },
    'client': {'host': '0.0.0.0', 'port': 4545},
    'providers': {
        'byteplus': {
            'api_key': '',
            'endpoint': 'https://ark.ap-southeast.bytepluses.com',
            'endpoint_ids': {'seedance_2_5': ''},
            'request_timeout_seconds': 600,
            'upload_timeout_seconds': 120,
        },
        'cupsy': {
            'api_key': '',
            'endpoint': 'https://cupsy.io',
            'request_timeout_seconds': 120,
        },
    },
    'generation': {
        'image': {
            'default': 'byteplus',
            'byteplus': {'model': 'dola-seedream-5-5-261028'},
            'cupsy': {'poll_max_attempts': 1800},
        },
        'video': {
            'poll_interval_seconds': 4,
            'poll_max_attempts': 1800,
            'byteplus': {'model': '', 'fast_model': ''},
            'cupsy': {'model': 'seedance-2.5'},
        },
        'audio': {
            'poll_interval_seconds': 4,
            'poll_max_attempts': 1800,
            'cupsy': {'model': 'seed-audio-1.0'},
        },
    },
    'deployment': {
        'public_base_url': '',
        'cupsy_source': {
            'base_url': '',
            'asset_token_ttl_seconds': 7200,
            'auto_configure': True,
            'certificate_email': '',
        },
    },
}


class ConfigError(Exception):
    """Startup-blocking configuration problems; messages contain key paths only."""

    def __init__(self, problems, path=None):
        self.problems = list(problems)
        self.path = path
        super().__init__(self.report())

    def report(self):
        head = f'config.json 无法使用（{self.path}）' if self.path else 'config.json 无法使用'
        return '\n'.join([head + '：'] + [f'  - {item}' for item in self.problems])


# --- leaf validators: return an error description (no value) or None ------------------

def _string(value):
    return None if isinstance(value, str) else '必须为字符串'


def _integer(minimum, maximum=None):
    def check(value):
        if type(value) is not int:
            return '必须为整数'
        if value < minimum or (maximum is not None and value > maximum):
            return f'必须在 {minimum}–{maximum} 之间' if maximum is not None else f'必须 ≥ {minimum}'
        return None
    return check


def _boolean(value):
    return None if type(value) is bool else '必须为 true 或 false'


def _string_list(value):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return '必须为字符串数组'
    return None


def _choice(*options):
    def check(value):
        return None if value in options else '必须为 ' + ' 或 '.join(options)
    return check


def _version(value):
    return None if type(value) is int and value == CONFIG_VERSION else f'必须为 {CONFIG_VERSION}'


def _url(origin_only):
    def check(value):
        if not isinstance(value, str):
            return '必须为字符串'
        if not value.strip():
            return None
        try:
            parsed = urlsplit(value.strip())
            host = parsed.hostname
            parsed.port  # noqa: B018 - raises on an invalid port
        except ValueError:
            return '不是有效的 HTTP(S) 地址'
        if parsed.scheme not in ('http', 'https') or not host:
            return '必须为 http:// 或 https:// 地址'
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return '不能包含凭据、查询参数或片段'
        if origin_only and parsed.path not in ('', '/'):
            return '只能填写源地址（协议://主机[:端口]），不能带路径'
        return None
    return check


def is_placeholder_endpoint_id(value):
    value = str(value or '').strip().lower()
    return not value or value == ENDPOINT_ID_PLACEHOLDER or value.startswith('ep-your-') or '<' in value


def _endpoint_id(value):
    if not isinstance(value, str):
        return '必须为字符串'
    if is_placeholder_endpoint_id(value):
        return None
    return None if value.strip().startswith('ep-') else '必须为 BytePlus 控制台的 ep-... 接入点ID或留空'


_str, _pos, _nonneg, _port = _string, _integer(1), _integer(0), _integer(1, 65535)

SCHEMA = {
    'config_version': _version,
    'auth': {'username': _str, 'password': _str, 'secret_key': _str},
    'server': {
        'host': _str, 'port': _port, 'cors_origins': _string_list,
        'request_timeout_seconds': _pos, 'poll_timeout_seconds': _pos, 'download_timeout_seconds': _pos,
        'worker_concurrency': _pos, 'generation_concurrency': _pos, 'polling_concurrency': _pos,
        'asset_concurrency': _pos, 'worker_lease_seconds': _pos, 'worker_heartbeat_seconds': _pos,
        'gunicorn_max_requests': _nonneg, 'gunicorn_max_requests_jitter': _nonneg,
        'cleanup_interval_seconds': _pos, 'orphan_grace_hours': _nonneg,
    },
    'client': {'host': _str, 'port': _port},
    'providers': {
        'byteplus': {
            'api_key': _str, 'endpoint': _url(False), 'endpoint_ids': {'seedance_2_5': _endpoint_id},
            'request_timeout_seconds': _pos, 'upload_timeout_seconds': _pos,
        },
        'cupsy': {'api_key': _str, 'endpoint': _url(False), 'request_timeout_seconds': _pos},
    },
    'generation': {
        'image': {
            'default': _choice('byteplus', 'cupsy'),
            'byteplus': {'model': _str},
            'cupsy': {'poll_max_attempts': _pos},
        },
        'video': {
            'poll_interval_seconds': _pos, 'poll_max_attempts': _pos,
            'byteplus': {'model': _str, 'fast_model': _str},
            'cupsy': {'model': _str},
        },
        'audio': {'poll_interval_seconds': _pos, 'poll_max_attempts': _pos, 'cupsy': {'model': _str}},
    },
    'deployment': {
        'public_base_url': _url(True),
        'cupsy_source': {
            'base_url': _url(True), 'asset_token_ttl_seconds': _integer(7200),
            'auto_configure': _boolean, 'certificate_email': _str,
        },
    },
}


def _walk(schema, value, path, problems):
    if not isinstance(value, dict):
        problems.append(f'{path}: 必须为对象')
        return
    for key in value:
        if key not in schema:
            problems.append(f'{path + "." if path else ""}{key}: 未知键（v2 不接受）')
    for key, rule in schema.items():
        if key not in value:
            continue
        child = f'{path + "." if path else ""}{key}'
        if isinstance(rule, dict):
            _walk(rule, value[key], child, problems)
        else:
            error = rule(value[key])
            if error:
                problems.append(f'{child}: {error}')


def _merge(defaults, overrides):
    merged = copy.deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def validate(raw):
    """Return ``(config_with_defaults, warnings)`` or raise ConfigError (paths only)."""
    if not isinstance(raw, dict):
        raise ConfigError(['顶层必须为 JSON 对象'])
    if 'config_version' not in raw:
        legacy = [key for key in LEGACY_TOP_LEVEL if key in raw]
        hint = f'（含旧段 {", ".join(legacy)}）' if legacy else ''
        raise ConfigError([f'缺少 config_version，判定为旧格式 v1{hint}；{MIGRATE_HINT}'])
    problems = []
    if _version(raw['config_version']):
        problems.append(f'config_version: 必须为 {CONFIG_VERSION}；{MIGRATE_HINT}')
    legacy = [key for key in LEGACY_TOP_LEVEL if key in raw]
    if legacy:
        problems.append(f'存在 v1 旧段 {", ".join(legacy)}；{MIGRATE_HINT}')
    _walk({k: v for k, v in SCHEMA.items() if k != 'config_version'},
          {k: v for k, v in raw.items() if k not in ('config_version', *legacy)}, '', problems)
    if problems:
        raise ConfigError(problems)
    config = _merge(DEFAULTS, raw)
    warnings = []
    if is_placeholder_endpoint_id(config['providers']['byteplus']['endpoint_ids']['seedance_2_5']):
        warnings.append('providers.byteplus.endpoint_ids.seedance_2_5 未配置：BytePlus Seedance 2.5 提交将被拒绝')
    if not config['providers']['byteplus']['api_key']:
        warnings.append('providers.byteplus.api_key 为空：BytePlus 图片/视频/图层不可用')
    if not config['providers']['cupsy']['api_key']:
        warnings.append('providers.cupsy.api_key 为空：Cupsy 图片/视频/音频不可用')
    return config, warnings


def load(path):
    """Read and validate a v2 file. Missing, unparsable, v1 or invalid files raise ConfigError."""
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise ConfigError(['文件不存在；新部署运行 ./setup.sh 或复制 config.json.example 后填写'], path) from None
    except json.JSONDecodeError as error:
        # Position only; the decoder message could echo file content.
        raise ConfigError([f'JSON 解析失败（第 {error.lineno} 行第 {error.colno} 列）'], path) from None
    except OSError as error:
        raise ConfigError([f'无法读取：{error.strerror}'], path) from None
    try:
        return validate(raw)
    except ConfigError as error:
        raise ConfigError(error.problems, path) from None


# --- runtime views: account + capability merged into the adapter dicts used by app.py ----

def image_byteplus(config):
    account = config['providers']['byteplus']
    return {
        'api_key': account['api_key'], 'endpoint': account['endpoint'],
        'model': config['generation']['image']['byteplus']['model'],
        'request_timeout_seconds': account['request_timeout_seconds'],
        'upload_timeout_seconds': account['upload_timeout_seconds'],
    }


def image_cupsy(config):
    account = config['providers']['cupsy']
    return {
        'api_key': account['api_key'], 'endpoint': account['endpoint'],
        'request_timeout_seconds': account['request_timeout_seconds'],
        'poll_max_attempts': config['generation']['image']['cupsy']['poll_max_attempts'],
    }


def video_byteplus(config):
    account = config['providers']['byteplus']
    video = config['generation']['video']['byteplus']
    return {
        'api_key': account['api_key'], 'endpoint': account['endpoint'],
        'model': video['model'], 'fast_model': video['fast_model'],
        'seedance_2_5_model': account['endpoint_ids']['seedance_2_5'],
        'request_timeout_seconds': account['request_timeout_seconds'],
        'upload_timeout_seconds': account['upload_timeout_seconds'],
    }


def _cupsy_source(config):
    source = config['deployment']['cupsy_source']
    return {'source_base_url': source['base_url'], 'asset_token_ttl_seconds': source['asset_token_ttl_seconds']}


def video_cupsy(config):
    account = config['providers']['cupsy']
    return {
        'api_key': account['api_key'], 'endpoint': account['endpoint'],
        'model': config['generation']['video']['cupsy']['model'], **_cupsy_source(config),
    }


def audio_cupsy(config):
    account = config['providers']['cupsy']
    return {
        'api_key': account['api_key'], 'endpoint': account['endpoint'],
        'model': config['generation']['audio']['cupsy']['model'], **_cupsy_source(config),
    }


def polling(config, kind):
    section = config['generation'][kind]
    return {'poll_interval_seconds': section['poll_interval_seconds'], 'poll_max_attempts': section['poll_max_attempts']}


def public_origin(config):
    """``(scheme, host, port)`` of deployment.public_base_url, or ``('http', '', None)``."""
    value = config['deployment']['public_base_url'].strip().rstrip('/')
    if not value:
        return 'http', '', None
    parsed = urlsplit(value)
    return parsed.scheme, parsed.hostname, parsed.port


# --- CLI -------------------------------------------------------------------------------

_GET_PREFIXES = ('server.', 'client.', 'deployment.')


def _cli(argv):
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
    if len(argv) >= 1 and argv[0] == 'check' and len(argv) <= 2:
        path = argv[1] if len(argv) == 2 else default
        try:
            _config, warnings = load(path)
        except ConfigError as error:
            print(error.report(), file=sys.stderr)
            return 2
        for warning in warnings:
            print(f'警告: {warning}', file=sys.stderr)
        print(f'OK: config.json v{CONFIG_VERSION} 校验通过')
        return 0
    if len(argv) in (2, 3) and argv[0] == 'get':
        dotted = argv[1]
        if not dotted.startswith(_GET_PREFIXES):
            print('get 只允许读取 server./client./deployment. 下的非敏感项', file=sys.stderr)
            return 2
        try:
            value, _warnings = load(argv[2] if len(argv) == 3 else default)
        except ConfigError as error:
            print(error.report(), file=sys.stderr)
            return 2
        for part in dotted.split('.'):
            if not isinstance(value, dict) or part not in value:
                print(f'未知键路径: {dotted}', file=sys.stderr)
                return 2
            value = value[part]
        print(str(value).lower() if isinstance(value, bool) else value)
        return 0
    print(__doc__.strip().split('CLI', 1)[1], file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))
