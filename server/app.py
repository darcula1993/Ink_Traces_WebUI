import seedream55 as seedream55_capabilities
import layer_options
import tempfile
from flask import Flask, request, jsonify, send_file, send_from_directory, session, g
from flask_cors import CORS
from werkzeug.exceptions import ClientDisconnected, RequestEntityTooLarge
import os
import base64
import requests
import io
import json
import sys
import secrets
import re
import time
import zipfile
import hashlib
import mimetypes
import shutil
import threading
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
from PIL import Image, UnidentifiedImageError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import uuid
from datetime import datetime, timezone
import tasks as task_db
import storage
import png_metadata
from http_client import HTTP
from logging_config import configure_logging
from response_compression import install_compression
from request_utils import as_bool, normalize_newlines
from task_api import task_api
from canvas_api import canvas_api
from canvas_store import init_canvas_db
import profile_runtime
import config_v2
from provider_profiles import init_profiles_db
from provider_api import provider_api

configure_logging()

app = Flask(__name__)
app.json.sort_keys = False
app.json.ensure_ascii = False
install_compression(app)
app.register_blueprint(task_api)
app.register_blueprint(canvas_api)
init_canvas_db()
init_profiles_db()
app.register_blueprint(provider_api)
import cost_ledger
cost_ledger.register_routes(app)
import cost_estimate


@app.teardown_appcontext
def close_database_connection(_error=None):
    task_db.close_db()


# Per-thread marker: set immediately before a non-idempotent Ark generation POST.
# Exceptions raised while it is unset happened before any request left this process.
_PROVIDER_DISPATCH = threading.local()


def reset_provider_dispatch():
    _PROVIDER_DISPATCH.started = False


def _mark_provider_dispatch():
    _PROVIDER_DISPATCH.started = True


def provider_dispatch_started():
    return bool(getattr(_PROVIDER_DISPATCH, 'started', False))


_PRE_SEND_REQUEST_ERRORS = tuple(
    error for error in (
        requests.exceptions.ConnectTimeout, requests.exceptions.InvalidURL,
        requests.exceptions.MissingSchema, requests.exceptions.InvalidSchema,
        requests.exceptions.URLRequired, getattr(requests.exceptions, 'InvalidHeader', None),
    ) if error is not None
)
_PRE_SEND_CONNECTION_MARKERS = (
    'newconnectionerror', 'nameresolutionerror', 'failed to resolve',
    'failed to establish a new connection', 'name or service not known',
    'nodename nor servname', 'connection refused',
)


def _request_not_sent(error):
    """True only when a requests error proves no request bytes reached the provider.

    ConnectTimeout, URL/header validation and TCP/DNS connection setup failures
    happen before the request is written; anything else (read/write timeouts,
    aborted or reset connections, TLS or proxy errors, unknown errors) may have
    reached the provider and is treated as result-unknown.
    """
    if isinstance(error, _PRE_SEND_REQUEST_ERRORS):
        return True
    if isinstance(error, requests.exceptions.ConnectionError) and not isinstance(
        error, (requests.exceptions.SSLError, requests.exceptions.ProxyError)
    ):
        text = f'{error!r} {error}'.lower()
        return 'timed out' not in text and any(marker in text for marker in _PRE_SEND_CONNECTION_MARKERS)
    return False


def _unknown_request_error_type(error):
    if isinstance(error, requests.exceptions.ReadTimeout):
        return 'upstream_timeout'
    if 'write operation timed out' in str(error).lower():
        return 'upload_timeout'
    return 'request_error_unknown'

# Flask配置 - 文件上传限制
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# 加载配置文件
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
CLIENT_DIST_DIR = os.path.join(PROJECT_ROOT, 'client', 'dist')
# v2 only (config_v2.py). NANOBANANA_CONFIG_FILE lets isolated tests/fixtures point at a
# synthetic file; production uses <repo>/config.json. There is no fallback to the example.
CONFIG_FILE = os.environ.get('NANOBANANA_CONFIG_FILE') or os.path.join(PROJECT_ROOT, 'config.json')
SECRET_KEY_FILE = os.path.join(PROJECT_ROOT, '.flask_secret_key')


def load_config(path=None):
    """Load config.json v2; any problem prints a path-only report and stops the process."""
    try:
        loaded, warnings = config_v2.load(path or CONFIG_FILE)
    except config_v2.ConfigError as error:
        print(error.report(), file=sys.stderr, flush=True)
        # Exit code 4 is Gunicorn's APP_LOAD_ERROR: the arbiter halts instead of respawning.
        raise SystemExit(4) from None
    for warning in warnings:
        print(f'Config warning: {warning}', file=sys.stderr, flush=True)
    return loaded


def ensure_secret_key(auth_config):
    """Use config/env/local ignored file so sessions survive restarts."""
    configured = auth_config.get('secret_key') or os.environ.get('INK_TRACES_SECRET_KEY')
    if configured:
        return configured

    try:
        if os.path.exists(SECRET_KEY_FILE):
            with open(SECRET_KEY_FILE, 'r', encoding='utf-8') as f:
                key = f.read().strip()
                if key:
                    return key
        key = secrets.token_urlsafe(48)
        with open(SECRET_KEY_FILE, 'w', encoding='utf-8') as f:
            f.write(key)
        try:
            os.chmod(SECRET_KEY_FILE, 0o600)
        except OSError:
            pass
        return key
    except Exception as e:
        print(f"Warning: Failed to persist Flask secret key: {e}")
        return secrets.token_urlsafe(48)


def get_cors_origins(cfg):
    configured = cfg['server']['cors_origins']
    if configured:
        return configured

    client_port = cfg['client']['port']
    origins = [
        f'http://localhost:{client_port}',
        f'http://127.0.0.1:{client_port}',
    ]
    public_scheme, public_host, public_port = config_v2.public_origin(cfg)
    if public_host:
        origins.append(f'{public_scheme}://{public_host}')
        if public_port:
            origins.append(f'{public_scheme}://{public_host}:{public_port}')
    return origins

config = load_config()
CORS(app, supports_credentials=True, origins=get_cors_origins(config))

# 认证配置
AUTH_CONFIG = config.get('auth', {})
app.config['SECRET_KEY'] = ensure_secret_key(AUTH_CONFIG)

# 登录接口
@app.route('/api/login', methods=['POST'])
def login():
    if not AUTH_CONFIG.get('username'):
        session['logged_in'] = True
        return jsonify({'success': True, 'auth_enabled': False})

    data = request.get_json(silent=True) or {}
    username = data.get('username', '')
    password = data.get('password', '')
    if username == AUTH_CONFIG.get('username') and password == AUTH_CONFIG.get('password'):
        session['logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '用户名或密码错误'}), 401

@app.route('/api/auth/check', methods=['GET'])
def auth_check():
    if not AUTH_CONFIG.get('username'):
        return jsonify({'success': True, 'auth_enabled': False})
    if session.get('logged_in'):
        return jsonify({'success': True, 'auth_enabled': True})
    return jsonify({'success': False}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.before_request
def start_request_timer():
    g.request_started_at = time.perf_counter()
    g.request_id = request.headers.get('X-Request-ID') or uuid.uuid4().hex


@app.before_request
def require_login():
    # 不需要认证的路径
    open_paths = ['/api/login', '/api/auth/check', '/api/health', '/api/live', '/api/ready']
    if not AUTH_CONFIG.get('username'):
        return  # 未配置 auth 则不启用认证
    if request.path in open_paths:
        return
    if request.path.startswith('/api/upload_video/') or request.path.startswith('/api/cupsy/source/'):
        return
    if not request.path.startswith('/api'):
        return
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': '未登录'}), 401

profile_runtime.install_profile_requests(app)


@app.after_request
def log_request(response):
    started_at = getattr(g, 'request_started_at', None)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2) if started_at else None
    response.headers['X-Request-ID'] = getattr(g, 'request_id', '')
    logged_path = request.path
    if logged_path.startswith('/api/cupsy/source/'):
        logged_path = '/api/cupsy/source/<redacted>'
    app.logger.info(
        'request_completed',
        extra={
            'request_id': getattr(g, 'request_id', None),
            'method': request.method,
            'path': logged_path,
            'status': response.status_code,
            'duration_ms': duration_ms,
        },
    )
    return response

# API Provider 配置
# Image providers: BytePlus Ark and Cupsy only.
# Runtime adapter keys stay 'ark'/'cupsy' (task params, profiles); config v2 names the
# BytePlus account 'byteplus'.
API_PROVIDERS = {
    'cupsy': config_v2.image_cupsy(config),
    'ark': config_v2.image_byteplus(config),
}
API_PROVIDERS = {key: profile_runtime.ProfileConfig(value, key) for key, value in API_PROVIDERS.items()}
UNSUPPORTED_RETRY_ERROR = '该任务使用的接入不受支持，请改选 BytePlus 或 Cupsy 后重新生成'
CURRENT_PROVIDER = 'cupsy' if config['generation']['image']['default'] == 'cupsy' else 'ark'


def get_session_image_provider():
    selected = profile_runtime.current_profile()
    if selected and selected['kind'] == 'image':
        return selected['adapter']
    if session.get('image_provider_default') != CURRENT_PROVIDER:
        session['image_provider'] = CURRENT_PROVIDER
        session['image_provider_default'] = CURRENT_PROVIDER
    provider = session.get('image_provider', CURRENT_PROVIDER)
    return provider if provider in API_PROVIDERS else CURRENT_PROVIDER


def get_image_provider_config(provider):
    provider = provider if provider in API_PROVIDERS else CURRENT_PROVIDER
    return provider, API_PROVIDERS.get(provider, API_PROVIDERS['ark'])


def get_layer_provider_config():
    """Layer decomposition always uses the BytePlus image model (generation.image.byteplus.model)."""
    return get_image_provider_config('ark')


def get_provider_key(provider, provider_config):
    if provider == 'cupsy':
        return _cupsy_settings()['api_key']
    return provider_config.get('api_key', '')


def get_provider_default_model(provider, provider_config):
    if provider == 'cupsy':
        return 'seedream-5.0-pro'
    return provider_config.get('model') or 'seedream-5-0-pro'

# 服务器配置
SERVER_HOST = config['server']['host']
SERVER_PORT = config['server']['port']

# 公网访问配置（deployment.public_base_url；用于生成给外部服务访问的文件 URL，如 Ark 视频参考）
PUBLIC_SCHEME, PUBLIC_HOST, PUBLIC_PORT = config_v2.public_origin(config)

# 上传视频目录（供外部服务下载的公网可访问视频参考文件）
UPLOAD_VIDEO_DIR = storage.UPLOAD_VIDEO_DIR

REQUEST_TIMEOUT = config['server']['request_timeout_seconds']
POLL_TIMEOUT = config['server']['poll_timeout_seconds']
DOWNLOAD_TIMEOUT = config['server']['download_timeout_seconds']
ARK_IMAGE_TIMEOUT = max(REQUEST_TIMEOUT, config['providers']['byteplus']['request_timeout_seconds'])
ARK_IMAGE_UPLOAD_TIMEOUT = max(30, config['providers']['byteplus']['upload_timeout_seconds'])
ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm'}
ALLOWED_VIDEO_MIMES = {'video/mp4', 'video/quicktime', 'video/x-m4v', 'video/webm'}


def resolve_ark_timeouts(provider_config=None):
    """Resolve Ark upload/read timeouts, sharing image defaults with video calls."""
    provider_config = provider_config or {}
    shared_config = API_PROVIDERS.get('ark', {})
    upload_timeout = provider_config.get(
        'upload_timeout_seconds',
        shared_config.get('upload_timeout_seconds', ARK_IMAGE_UPLOAD_TIMEOUT),
    )
    request_timeout = provider_config.get(
        'request_timeout_seconds',
        shared_config.get('request_timeout_seconds', ARK_IMAGE_TIMEOUT),
    )
    return (
        profile_runtime.setting('upload_timeout_seconds', max(30, int(upload_timeout or ARK_IMAGE_UPLOAD_TIMEOUT))),
        profile_runtime.setting('request_timeout_seconds', max(30, int(request_timeout or ARK_IMAGE_TIMEOUT))),
    )

def build_public_url(path):
    """根据 deployment.public_base_url 构建公网可访问的 URL"""
    if not PUBLIC_HOST:
        return None
    # 默认端口省略
    default_ports = {'http': 80, 'https': 443}
    if PUBLIC_PORT and int(PUBLIC_PORT) != default_ports.get(PUBLIC_SCHEME, -1):
        return f'{PUBLIC_SCHEME}://{PUBLIC_HOST}:{PUBLIC_PORT}{path}'
    return f'{PUBLIC_SCHEME}://{PUBLIC_HOST}{path}'

def save_temp_file(file_storage, suffix='.mp4'):
    """保存上传文件到 upload_video 目录，返回 (本地路径, 公网 URL)"""
    file_id = str(uuid.uuid4())
    orig_name = getattr(file_storage, 'filename', '') or ''
    ext = (os.path.splitext(orig_name)[1] or suffix).lower()
    mime = (getattr(file_storage, 'content_type', '') or '').split(';', 1)[0].lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise ValueError('不支持的视频文件类型')
    if mime and mime not in ALLOWED_VIDEO_MIMES:
        raise ValueError('不支持的视频 MIME 类型')
    fname = f'{file_id}{ext}'
    filepath = os.path.join(UPLOAD_VIDEO_DIR, fname)
    file_storage.seek(0)
    temp_path = f'{filepath}.tmp'
    try:
        file_storage.save(temp_path)
        os.replace(temp_path, filepath)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    storage.register_file(None, 'video_upload', filepath, mime or None, storage.upload_expiry())
    public_url = build_public_url(f'/api/upload_video/{fname}')
    return filepath, public_url

SENSITIVE_KEYS = {'key', 'apikey', 'api_key', 'authorization', 'password', 'prompt', 'secret', 'secret_key', 'token'}


def redact_url(url):
    try:
        split = urlsplit(url)
        query = urlencode([
            (key, '***REDACTED***' if key.lower() in SENSITIVE_KEYS else value)
            for key, value in parse_qsl(split.query, keep_blank_values=True)
        ])
        return urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))
    except Exception:
        return url


def redact_sensitive(value):
    """Remove keys and bearer values before persisting local diagnostics."""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in SENSITIVE_KEYS or any(part in key_lower for part in ('api_key', 'secret', 'password', 'token')):
                redacted[key] = '***REDACTED***'
            elif key_lower in ('data', 'b64_json') and isinstance(item, str) and len(item) > 1024:
                redacted[key] = f'<omitted {len(item)} characters>'
            elif key_lower in ('api_url', 'url') and isinstance(item, str):
                redacted[key] = redact_url(item)
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        if value.lower().startswith('bearer '):
            return 'Bearer ***REDACTED***'
        if value.startswith('data:') and len(value) > 1024:
            return f'<omitted data URL: {len(value)} characters>'
    return value

# Prompt收藏存储文件路径
PROMPTS_FILE = os.path.join(os.path.dirname(__file__), 'prompts.json')
PROMPTS_EXAMPLE_FILE = os.path.join(os.path.dirname(__file__), 'prompts.json.example')

# 错误日志目录
ERROR_LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'error_logs')
if not os.path.exists(ERROR_LOGS_DIR):
    os.makedirs(ERROR_LOGS_DIR)

def save_error_log(error_type, request_data, response_data, error_message=None):
    """
    保存错误日志到JSON文件

    Args:
        error_type: 错误类型 (如 'generation_failed', 'api_error', 'safety_blocked')
        request_data: 请求数据字典
        response_data: API响应数据
        error_message: 可选的错误消息
    """
    try:
        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename = f"{error_type}_{timestamp}.json"
        filepath = os.path.join(ERROR_LOGS_DIR, filename)

        # 构建日志数据
        log_data = {
            'timestamp': datetime.now().isoformat(),
            'error_type': error_type,
            'error_message': error_message,
            'request': redact_sensitive(request_data),
            'response': redact_sensitive(response_data)
        }

        # 保存到文件
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

        print(f"Error log saved to: {filepath}")
        return filepath
    except Exception as e:
        print(f"Failed to save error log: {e}")
        return None

def load_prompts():
    """Load prompts from SQLite, importing the legacy JSON file once."""
    prompts = task_db.list_prompts()
    if prompts:
        return prompts

    source_file = PROMPTS_FILE if os.path.exists(PROMPTS_FILE) else PROMPTS_EXAMPLE_FILE
    if not os.path.exists(source_file):
        return []
    try:
        with open(source_file, 'r', encoding='utf-8') as f:
            legacy_prompts = json.load(f)
        task_db.import_prompts(legacy_prompts)
        return task_db.list_prompts()
    except Exception as e:
        print(f"Error importing prompts: {e}")
        return []

def image_to_base64(image):
    """将PIL Image转换为base64字符串"""
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def parse_api_error(response, response_data=None):
    """解析API错误并返回友好的错误信息"""
    status_code = response.status_code
    error_info = {
        'type': 'unknown',
        'message': '',
        'details': {},
        'user_message': ''
    }

    # 解析响应体中的错误信息
    if response_data is None and response.text:
        try:
            response_data = response.json()
        except:
            pass

    if isinstance(response_data, list) and len(response_data) == 1:
        response_data = response_data[0]

    error_obj = {}
    error_message = ''
    error_status = ''
    error_reasons = set()

    if response_data and isinstance(response_data, dict) and isinstance(response_data.get('error'), dict):
        error_obj = response_data['error']
        error_message = error_obj.get('message', '') or ''
        error_status = error_obj.get('status', '') or ''
        for detail in error_obj.get('details', []) or []:
            if isinstance(detail, dict) and detail.get('reason'):
                error_reasons.add(detail['reason'])

    # HTTP状态码错误
    if 'API_KEY_INVALID' in error_reasons or ('api key' in error_message.lower() and any(word in error_message.lower() for word in ('expired', 'invalid'))):
        error_info['type'] = 'unauthorized'
        error_info['user_message'] = 'API密钥无效或已过期，请更新对应 Provider 的 API Key'
    elif status_code == 400:
        error_info['type'] = 'bad_request'
        error_info['user_message'] = '请求参数错误，请检查输入内容'
    elif status_code == 401:
        error_info['type'] = 'unauthorized'
        error_info['user_message'] = 'API密钥无效或已过期，请联系管理员'
    elif status_code == 403:
        error_info['type'] = 'forbidden'
        error_info['user_message'] = '没有权限访问此API，请联系管理员'
    elif status_code == 404:
        error_info['type'] = 'not_found'
        error_info['user_message'] = 'API端点不存在，请联系管理员'
    elif status_code == 429:
        error_info['type'] = 'rate_limit'
        error_info['user_message'] = 'API调用次数已达上限，请稍后再试'
    elif status_code == 500:
        error_info['type'] = 'server_error'
        error_info['user_message'] = 'API服务器内部错误，请稍后再试'
    elif status_code == 503:
        error_info['type'] = 'service_unavailable'
        error_info['user_message'] = 'API服务暂时不可用，请稍后再试'
    else:
        error_info['user_message'] = f'API返回错误 (状态码: {status_code})'

    # 提取详细错误信息
    if response_data and isinstance(response_data, dict):
        if 'error' in response_data:
            if isinstance(error_obj, dict):
                error_info['message'] = error_message
                error_info['details']['code'] = error_obj.get('code', status_code)
                error_info['details']['status'] = error_status
                if error_reasons:
                    error_info['details']['reasons'] = sorted(error_reasons)

    return error_info

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'Server is running'})


@app.route('/api/live', methods=['GET'])
def live():
    return jsonify({'status': 'ok'})


@app.route('/api/ready', methods=['GET'])
def ready():
    try:
        database_ok = task_db.ping()
        disk = storage.storage_usage()
        worker = task_db.latest_worker_heartbeat()
        worker_ok = False
        if worker and worker.get('last_seen_at'):
            last_seen = datetime.fromisoformat(worker['last_seen_at'])
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            worker_ok = (datetime.now(timezone.utc) - last_seen).total_seconds() < 30
        ready_status = database_ok and worker_ok
        return jsonify({
            'status': 'ready' if ready_status else 'not_ready',
            'database': database_ok,
            'disk_free_bytes': disk['free'],
            'worker_ok': worker_ok,
            'worker': worker,
        }), 200 if ready_status else 503
    except Exception as e:
        return jsonify({'status': 'not_ready', 'error': str(e)}), 503

# ==================== API Provider Switching ====================

@app.route('/api/provider', methods=['GET'])
def get_provider():
    """获取当前 API provider 信息"""
    current_provider = get_session_image_provider()
    return jsonify({
        'success': True,
        'current_provider': current_provider,
        'current_model': get_provider_default_model(current_provider, API_PROVIDERS.get(current_provider, {})),
        'providers': {
            'cupsy': {
                'name': 'Cupsy',
                'model': 'seedream-5.0-pro',
                'available': bool(get_provider_key('cupsy', API_PROVIDERS['cupsy'])),
            },
            'ark': {
                'name': 'BytePlus Ark',
                'model': API_PROVIDERS['ark'].get('model', ''),
                'capability_model': seedream55_capabilities.MODEL if seedream55_capabilities.enabled() else API_PROVIDERS['ark'].get('model', ''),
                'available': bool(API_PROVIDERS['ark'].get('api_key'))
            }
        }
    })

@app.route('/api/provider', methods=['POST'])
def switch_provider():
    """切换 API provider"""
    try:
        data = request.get_json()
        new_provider = data.get('provider')

        if new_provider not in API_PROVIDERS:
            return jsonify({
                'success': False,
                'error': 'Invalid provider. Must be "ark" or "cupsy"'
            }), 400

        if new_provider == 'ark':
            if not API_PROVIDERS.get('ark', {}).get('api_key'):
                return jsonify({
                    'success': False,
                    'error': 'Provider "ark" is not configured'
                }), 400
        elif not get_provider_key(new_provider, API_PROVIDERS[new_provider]):
            return jsonify({
                'success': False,
                'error': f'Provider "{new_provider}" is not configured'
            }), 400

        session['image_provider'] = new_provider
        current_api = API_PROVIDERS[new_provider]
        model_id = get_provider_default_model(new_provider, current_api)

        provider_names = {'ark': 'BytePlus Ark', 'cupsy': 'Cupsy'}
        provider_name = provider_names.get(new_provider, new_provider)

        return jsonify({
            'success': True,
            'message': f'Switched to {provider_name}',
            'provider': new_provider,
            'model': model_id
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ==================== Prompt Collection API ====================

@app.route('/api/prompts', methods=['GET'])
def get_prompts():
    """获取所有prompts"""
    try:
        prompts = load_prompts()
        return jsonify({'success': True, 'prompts': prompts})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/prompts', methods=['POST'])
def create_prompt():
    """创建新的prompt"""
    try:
        data = request.json
        text = data.get('text')

        if not text or not text.strip():
            return jsonify({'success': False, 'error': 'Prompt text is required'}), 400

        new_prompt = task_db.create_prompt(
            text.strip(),
            created_at=task_db.utcnow(),
        )
        return jsonify({'success': True, 'prompt': new_prompt})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/prompts/<int:prompt_id>', methods=['PUT'])
def update_prompt(prompt_id):
    """更新prompt"""
    try:
        data = request.json
        new_text = data.get('text')

        if not new_text or not new_text.strip():
            return jsonify({'success': False, 'error': 'Prompt text is required'}), 400

        if not task_db.update_prompt(prompt_id, new_text.strip()):
            return jsonify({'success': False, 'error': 'Prompt not found'}), 404
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/prompts/<int:prompt_id>', methods=['DELETE'])
def delete_prompt(prompt_id):
    """删除prompt"""
    try:
        if not task_db.delete_prompt(prompt_id):
            return jsonify({'success': False, 'error': 'Prompt not found'}), 404
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


ARK_SEEDREAM_PRO_MAX_REFERENCES = 10
ARK_SEEDREAM_PRO_MIN_PIXELS = 1280 * 720
ARK_SEEDREAM_PRO_MAX_PIXELS = 4_624_220
ARK_SEEDREAM_PRO_MIN_RATIO = 1 / 16
ARK_SEEDREAM_PRO_MAX_RATIO = 16
ARK_SEEDREAM_PRO_SIZE_MAP = {
    '1K': {
        '1:1': '1024x1024', '4:3': '1152x864', '3:4': '864x1152',
        '16:9': '1424x800', '9:16': '800x1424', '3:2': '1248x832',
        '2:3': '832x1248', '21:9': '1568x672',
    },
    '2K': {
        '1:1': '2048x2048', '4:3': '2368x1776', '3:4': '1776x2368',
        '16:9': '2816x1584', '9:16': '1584x2816', '3:2': '2496x1664',
        '2:3': '1664x2496', '21:9': '3136x1344',
    },
}
ARK_SEEDREAM_OUTPUT_MIMES = {'png': 'image/png', 'jpeg': 'image/jpeg'}
CUPSY_SEEDREAM_SIZE_MAP = {
    '1K': {'1:1': '1024x1024', '4:3': '1152x864', '3:4': '864x1152', '16:9': '1280x720', '9:16': '720x1280'},
    '2K': {'1:1': '2048x2048', '4:3': '2304x1728', '3:4': '1728x2304', '16:9': '2560x1440', '9:16': '1440x2560'},
}


def resolve_seedream_pro_size(aspect_ratio, resolution, custom_width=None, custom_height=None, seedream55=False):
    aspect_ratio = str(aspect_ratio or '1:1').strip().lower()
    if aspect_ratio != 'custom':
        resolution = str(resolution or '1K').strip().upper()
        if seedream55 and resolution == '1.5K':
            if aspect_ratio == 'auto': return '1.5K'
            if aspect_ratio not in seedream55_capabilities.SIZES: raise ValueError('Seedream 5.5 不支持当前比例')
            return seedream55_capabilities.SIZES[aspect_ratio]
        if resolution not in ARK_SEEDREAM_PRO_SIZE_MAP:
            raise ValueError('Seedream 5.0 Pro 仅支持 1K 或 2K')
        if aspect_ratio == 'auto':
            return resolution
        size = ARK_SEEDREAM_PRO_SIZE_MAP[resolution].get(aspect_ratio)
        if not size:
            raise ValueError(f'Seedream 5.0 Pro 不支持当前比例: {aspect_ratio}')
        return size

    try:
        width = int(custom_width)
        height = int(custom_height)
    except (TypeError, ValueError):
        raise ValueError('自定义宽度和高度必须是正整数') from None
    if width <= 0 or height <= 0:
        raise ValueError('自定义宽度和高度必须是正整数')
    if width % 16 or height % 16:
        raise ValueError('自定义宽度和高度必须是 16 的倍数')
    pixels = width * height
    if not ARK_SEEDREAM_PRO_MIN_PIXELS <= pixels <= ARK_SEEDREAM_PRO_MAX_PIXELS:
        raise ValueError('自定义尺寸总像素必须在 921600 到 4624220 之间')
    ratio = width / height
    if not ARK_SEEDREAM_PRO_MIN_RATIO <= ratio <= ARK_SEEDREAM_PRO_MAX_RATIO:
        raise ValueError('自定义尺寸宽高比必须在 1:16 到 16:1 之间')
    return f'{width}x{height}'


def _generate_ark_image(
    prompt, aspect_ratio, resolution, parts, output_format='png', watermark=False,
    provider_config=None, model_id=None, custom_width=None, custom_height=None,
    background=None, layer_decomposition=False, defer_download=False, seedream55=False, layer_decomposition_options=None,
):
    """调用 BytePlus Ark Seedream 5.0 Pro API 生成单张图片。"""
    ark_cfg = provider_config or API_PROVIDERS.get('ark', {})
    api_key = ark_cfg.get('api_key', '')
    endpoint = ark_cfg.get('endpoint', '').rstrip('/')
    model = model_id or ark_cfg.get('model') or 'seedream-5-0-pro'
    upload_timeout, request_timeout = resolve_ark_timeouts(ark_cfg)
    resolution = str(resolution or '1K').upper()
    output_format = str(output_format or 'png').lower()

    if layer_decomposition:
        size = str(resolution or 'auto')
        if size.lower() == 'auto':
            size = 'auto'
        else:
            size = size.upper()
        if size not in {'auto', '1K', '1.5K', '2K'}:
            return jsonify({'success': False, 'error': '图层分解分辨率仅支持 Auto、1K、1.5K 或 2K', 'error_type': 'invalid_size'}), 400
    else:
        try:
            size = resolve_seedream_pro_size(aspect_ratio, resolution, custom_width, custom_height, seedream55=seedream55)
        except ValueError as error:
            return jsonify({'success': False, 'error': str(error), 'error_type': 'invalid_size'}), 400
    if output_format not in ARK_SEEDREAM_OUTPUT_MIMES:
        return jsonify({'success': False, 'error': '输出格式仅支持 png 或 jpeg', 'error_type': 'invalid_output_format'}), 400

    body = {
        'model': model,
        'prompt': prompt,
        'size': size,
        # Keep the long-running generation response small; the worker downloads
        # the short-lived Ark URL immediately after generation completes.
        'response_format': 'url',
        'watermark': bool(watermark),
        'output_format': output_format,
    }
    if layer_decomposition:
        body['layer_decomposition'] = True
        if layer_decomposition_options is not None:
            body['layer_decomposition_options'] = layer_decomposition_options
    if background in {'transparent', 'opaque'} or (seedream55 and background == 'auto' and not layer_decomposition):
        body['background'] = background

    # 参考图（取 parts 中的 inlineData）
    ref_images = [
        (p['inlineData'].get('mimeType') or 'image/png', p['inlineData']['data'])
        for p in parts if 'inlineData' in p
    ]
    if len(ref_images) > ARK_SEEDREAM_PRO_MAX_REFERENCES:
        return jsonify({'success': False, 'error': 'Seedream 5.0 Pro 最多支持10张参考图', 'error_type': 'too_many_images'}), 400
    if layer_decomposition and len(ref_images) != 1:
        return jsonify({'success': False, 'error': '图层分解必须且只能使用一张源图片', 'error_type': 'invalid_image_count'}), 400
    if len(ref_images) == 1:
        body['image'] = f"data:{ref_images[0][0]};base64,{ref_images[0][1]}"
    elif len(ref_images) > 1:
        body['image'] = [f"data:{mime};base64,{data}" for mime, data in ref_images]

    url = f'{endpoint}/api/v3/images/generations'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}

    print(f'Using API: ARK, URL: {url}, Model: {model}, Size: {size}')

    req_info = {
        'prompt': prompt, 'aspect_ratio': aspect_ratio, 'resolution': resolution,
        'size': size, 'output_format': output_format, 'watermark': bool(watermark),
        'response_format': body['response_format'],
        'reference_count': len(ref_images),
        'reference_base64_bytes': sum(len(data) for _mime, data in ref_images),
        'background': background,
        'layer_decomposition': bool(layer_decomposition),
    }

    try:
        _mark_provider_dispatch()
        response = HTTP.post(url, headers=headers, json=body, timeout=(upload_timeout, request_timeout))
    except requests.exceptions.ConnectTimeout as e:
        save_error_log('ark_request_error', req_info, {}, str(e))
        return jsonify({
            'success': False,
            'error': '连接 Ark API 超时，请求尚未提交；任务已结束，可直接重试',
            'error_type': 'connect_timeout',
            'retryable': True,
            'error_details': {'message': str(e), 'timeout_seconds': upload_timeout},
        }), 503
    except requests.exceptions.ReadTimeout as e:
        save_error_log('ark_request_timeout', req_info, {}, str(e))
        return jsonify({
            'success': False,
            'error': f'Ark 在 {request_timeout} 秒内未返回，任务结果未知；为避免重复提交，系统未自动重试',
            'error_type': 'upstream_timeout',
            'retryable': False,
            'result_unknown': True,
            'error_details': {
                'message': '请求已经发出，但没有及时收到响应。请先在 Ark 控制台确认任务结果，再决定是否重新生成。',
                'timeout_seconds': request_timeout,
            },
        }), 504
    except requests.exceptions.RequestException as e:
        save_error_log('ark_request_error', req_info, {}, str(e))
        if 'write operation timed out' in str(e).lower():
            return jsonify({
                'success': False,
                'error': f'Ark 请求体在 {upload_timeout} 秒内未上传完成，任务结果未知；系统未自动重试',
                'error_type': 'upload_timeout',
                'retryable': False,
                'result_unknown': True,
                'error_details': {
                    'message': '参考素材上传到 Ark 时连接过慢。请确认 Ark 控制台结果后再决定是否重新生成。',
                    'timeout_seconds': upload_timeout,
                },
            }), 504
        if not _request_not_sent(e):
            return jsonify({
                'success': False,
                'error': f'Ark API 请求可能已发出、结果未知（{e}）；为避免重复计费，系统未自动重试，请先到Provider核实',
                'error_type': 'request_error_unknown',
                'retryable': False,
                'result_unknown': True,
            }), 502
        return jsonify({
            'success': False,
            'error': f'Ark API 网络请求失败: {e}',
            'error_type': 'request_error',
            'retryable': False,
        }), 502
    except Exception as e:
        # Non-requests error raised from inside the POST: whether bytes left cannot be proven.
        save_error_log('ark_request_error', req_info, {}, str(e))
        return jsonify({
            'success': False,
            'error': f'Ark API 请求可能已发出、结果未知（{e}）；为避免重复计费，系统未自动重试，请先到Provider核实',
            'error_type': 'request_error_unknown',
            'retryable': False,
            'result_unknown': True,
        }), 500

    resp_data = response.json() if response.text else {}

    if response.status_code != 200:
        err_msg = resp_data.get('error', {}).get('message', f'Ark API 错误 {response.status_code}') if isinstance(resp_data.get('error'), dict) else resp_data.get('error', f'Ark API 错误 {response.status_code}')
        save_error_log('ark_api_error', req_info, resp_data, err_msg)
        return jsonify({
            'success': False,
            'error': err_msg,
            'error_type': 'api_error',
            'retryable': response.status_code == 429,
        }), response.status_code

    if layer_decomposition and any(item.get('error') for item in resp_data.get('data', [])):
        return {'success':False, 'error':'Provider部分图层生成失败，未发布不完整版本', 'retryable':False}, 502

    # 解析返回的图片
    images = []
    items = []
    source_urls = []
    for item in resp_data.get('data', []):
        if 'error' in item:
            continue
        item_format = str(item.get('output_format') or output_format).lower()
        mime_type = ARK_SEEDREAM_OUTPUT_MIMES.get(item_format, ARK_SEEDREAM_OUTPUT_MIMES[output_format])
        if item.get('b64_json'):
            data_url = f"data:{mime_type};base64,{item['b64_json']}"
            images.append(data_url)
            items.append({**item, 'data_url': data_url, 'source_url': None})
        elif item.get('url'):
            source_url = str(item['url'])
            if defer_download:
                if source_url.startswith(('https://', 'http://')):
                    source = {'url': source_url, 'mime_type': mime_type}
                    images.append(source)
                    items.append({**item, 'image_source': source, 'source_url': source_url})
                    source_urls.append(source_url)
                continue
            try:
                img_resp = HTTP.get(source_url, timeout=(10, profile_runtime.setting('download_timeout_seconds', DOWNLOAD_TIMEOUT)))
                if img_resp.status_code == 200:
                    b64 = base64.b64encode(img_resp.content).decode('utf-8')
                    response_mime = img_resp.headers.get('Content-Type', '').split(';', 1)[0]
                    data_url = f"data:{response_mime or mime_type};base64,{b64}"
                    images.append(data_url)
                    items.append({**item, 'data_url': data_url, 'source_url': source_url})
                    if source_url.startswith(('https://', 'http://')):
                        source_urls.append(source_url)
            except Exception:
                pass

    if not images:
        save_error_log('ark_generation_failed', req_info, resp_data, '未能生成图片')
        return jsonify({'success': False, 'error': '未能生成图片', 'error_type': 'generation_failed'}), 500

    return {
        'success': True,
        'images': images,
        'items': items,
        'source_urls': source_urls,
        'output_format': output_format,
    }, 200


def _response_payload(response):
    if isinstance(response, tuple):
        response_obj, status_code = response
    else:
        response_obj, status_code = response, 200
    if isinstance(response_obj, dict):
        return response_obj, status_code
    return response_obj.get_json(), status_code


def _save_generated_image(source, output_dir, stem):
    """Preserve provider bytes; only use Base64 for providers returning inline data."""
    temporary = os.path.join(output_dir, f'.{stem}-{uuid.uuid4().hex}.download')
    try:
        if isinstance(source, str) and source.startswith('data:'):
            storage.save_data_url(source, temporary)
        elif isinstance(source, dict) and source.get('url'):
            headers = _cupsy_headers() if source.get('cupsy_authenticated') else {}
            with HTTP.get(source['url'], headers=headers, timeout=(10, profile_runtime.setting('download_timeout_seconds', DOWNLOAD_TIMEOUT)), stream=True) as download:
                download.raise_for_status()
                storage.stream_response_to_file(download, temporary)
        else:
            raise ValueError('无效的生成图片来源')
        with Image.open(temporary) as image:
            image_format = image.format
            image.verify()
        if image_format not in {'PNG', 'JPEG'}:
            raise ValueError('端点返回了不支持的图片格式')
        extension = 'png' if image_format == 'PNG' else 'jpg'
        path = os.path.join(output_dir, f'{stem}.{extension}')
        os.replace(temporary, path)
        return path, 'image/png' if extension == 'png' else 'image/jpeg'
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


@profile_runtime.task_context
def execute_image_task(task_id):
    """Execute one persisted image task and store only lightweight result metadata."""
    reset_provider_dispatch()
    task = task_db.get_task(task_id)
    if not task:
        return {'success': False, 'error': '任务不存在'}, 404
    if task_db.cancellation_requested(task_id):
        task_db.finalize_task_cancel(task_id)
        return {'success': False, 'cancelled': True, 'error': '任务已取消', 'task_id': task_id}, 409

    params = task.get('params') or {}
    requested_provider = task.get('provider') or params.get('provider')
    if requested_provider not in API_PROVIDERS:
        # Unsupported providers must fail visibly, never fall back to another account.
        message = f'不支持的图片 provider: {requested_provider}'
        task_db.fail_task(task_id, message, {'error_type': 'provider_unavailable'})
        return {'success': False, 'error': message, 'error_type': 'provider_unavailable', 'retryable': False, 'task_id': task_id}, 400
    provider, provider_config = get_image_provider_config(requested_provider)
    model_id = params.get('model') or get_provider_default_model(provider, provider_config)
    output_dir = task.get('output_dir') or storage.task_output_dir('image', task_id)
    input_assets = [
        asset for asset in task_db.list_assets(task_id)
        if asset['kind'] == 'input_image' and os.path.isfile(asset['path'])
    ]
    input_assets.sort(key=storage.reference_asset_sort_key)

    parts = []
    local_refs = []
    for asset in input_assets:
        if provider != 'cupsy':
            with open(asset['path'], 'rb') as handle:
                encoded = base64.b64encode(handle.read()).decode('utf-8')
            parts.append({'inlineData': {'mimeType': asset.get('mime_type') or 'image/png', 'data': encoded}})
        local_refs.append(f'/api/tasks/{task_id}/file/{os.path.basename(asset["path"])}')
    parts.append({'text': task.get('prompt') or ''})

    try:
        if provider == 'cupsy':
            response = _generate_cupsy_image(task)
        else:
            response = _generate_ark_image(
                task.get('prompt') or '',
                params.get('aspect_ratio', '1:1'),
                params.get('resolution', '1K'),
                parts,
                params.get('output_format', 'png'),
                bool(params.get('watermark', False)),
                provider_config,
                model_id,
                params.get('custom_width'),
                params.get('custom_height'),
                params.get('background'),
                defer_download=True,
                seedream55=params.get('seedream55', False),
            )
        response_data, status_code = _response_payload(response)
    except Exception as e:
        if provider in task_db.NON_IDEMPOTENT_PROVIDERS and provider_dispatch_started():
            # The POST may already have reached the provider; never let the worker resubmit it.
            message = task_db.worker_exception_error(e)
            task_db.fail_task_result_unknown(task_id, message, 'worker_exception')
            return {
                'success': False, 'error': message, 'error_type': 'worker_exception',
                'retryable': False, 'result_unknown': True, 'task_id': task_id,
            }, 500
        task_db.fail_task(task_id, str(e))
        return {'success': False, 'error': str(e), 'error_type': 'request_error', 'task_id': task_id}, 500

    if task_db.cancellation_requested(task_id):
        task_db.finalize_task_cancel(task_id)
        return {'success': False, 'cancelled': True, 'error': '任务已取消', 'task_id': task_id}, 409

    if response_data.get('pending'):
        return response_data, status_code
    if not response_data.get('success'):
        error_result = {
            'error_type': response_data.get('error_type'),
            'error_details': response_data.get('error_details'),
            'result_unknown': bool(response_data.get('result_unknown', False)),
        }
        task_db.fail_task(task_id, response_data.get('error', '图片生成失败'), error_result)
        response_data['task_id'] = task_id
        return response_data, status_code

    local_images = []
    local_thumbnails = []
    for index, image_source in enumerate(response_data.get('images') or []):
        if task_db.cancellation_requested(task_id):
            storage.remove_task_output_files(task_id)
            task_db.finalize_task_cancel(task_id)
            return {'success': False, 'cancelled': True, 'error': '任务已取消', 'task_id': task_id}, 409
        try:
            path, mime_type = _save_generated_image(image_source, output_dir, f'image_{index}')
        except (requests.RequestException, OSError, ValueError) as error:
            if provider == 'cupsy' and isinstance(error, requests.RequestException):
                return {'pending': True, 'retry_after': 15, 'error': f'生成图片下载失败: {error}'}, 202
            task_db.fail_task(task_id, f'生成图片保存失败: {error}', {'source_urls': response_data.get('source_urls', [])})
            return {'success': False, 'retryable': False, 'error': '生成图片保存失败'}, 502
        filename = os.path.basename(path)
        storage.register_file(task_id, 'output_image', path, mime_type)
        local_images.append(f'/api/tasks/{task_id}/file/{filename}')
        thumbnail_name = f'thumb_{index}.webp'
        thumbnail_path = os.path.join(output_dir, thumbnail_name)
        try:
            storage.create_image_thumbnail(path, thumbnail_path)
            storage.register_file(task_id, 'output_thumbnail', thumbnail_path, 'image/webp')
            local_thumbnails.append(f'/api/tasks/{task_id}/file/{thumbnail_name}')
        except (OSError, ValueError):
            app.logger.warning('thumbnail_generation_failed task_id=%s file=%s', task_id, filename)

    if not local_images:
        task_db.fail_task(task_id, '未能保存生成图片')
        return {'success': False, 'error': '未能保存生成图片', 'error_type': 'generation_failed', 'task_id': task_id}, 500

    result = {
        'local_images': local_images,
        'local_thumbnails': local_thumbnails,
        'local_refs': local_refs,
        'source_urls': [
            url for url in (response_data.get('source_urls') or [])
            if isinstance(url, str) and url.startswith(('https://', 'http://'))
        ],
        'output_format': response_data.get('output_format', params.get('output_format', 'png')),
    }
    if not task_db.complete_task(task_id, result, output_dir):
        storage.remove_task_output_files(task_id)
        task_db.finalize_task_cancel(task_id)
        return {'success': False, 'cancelled': True, 'error': '任务已取消', 'task_id': task_id}, 409

    payload = {
        'success': True,
        'images': local_images,
        'task_id': task_id,
    }
    return payload, 200


@profile_runtime.task_context
def execute_layer_task(task_id):
    """Run one Seedream layer-decomposition task and initialize its studio document."""
    reset_provider_dispatch()
    task = task_db.get_task(task_id)
    if not task:
        return {'success': False, 'error': '图层任务不存在'}, 404
    params = task.get('params') or {}
    project_id = params.get('project_id')
    assets = [asset for asset in task_db.list_assets(task_id) if asset['kind'] == 'input_image']
    if len(assets) != 1 or not os.path.isfile(assets[0]['path']):
        task_db.fail_task(task_id, '图层分解源图片不存在')
        return {'success': False, 'error': '图层分解源图片不存在'}, 400

    with open(assets[0]['path'], 'rb') as handle:
        encoded = base64.b64encode(handle.read()).decode('utf-8')
    parts = [{'inlineData': {'mimeType': assets[0].get('mime_type') or 'image/png', 'data': encoded}}]
    _provider, provider_config = get_image_provider_config('ark')
    response = _generate_ark_image(
        task.get('prompt') or '', 'auto', params.get('size', 'auto'), parts,
        params.get('output_format', 'png'), False, provider_config,
        params.get('model'), layer_decomposition=True, defer_download=True,
        layer_decomposition_options=params.get('layer_decomposition_options'),
    )
    response_data, status_code = _response_payload(response)
    if not response_data.get('success'):
        task_db.fail_task_merging_result(task_id, response_data.get('error', '图层分解失败'), {
            'error_type': response_data.get('error_type'),
            'error_details': response_data.get('error_details'),
            'result_unknown': bool(response_data.get('result_unknown', False)),
        })
        response_data['task_id'] = task_id
        return response_data, status_code

    output_dir = task.get('output_dir') or storage.task_output_dir('layer', task_id)
    provider_items = response_data.get('items') or [
        {'data_url': data_url, 'z_index': index}
        for index, data_url in enumerate(response_data.get('images') or [])
    ]
    if len(provider_items) > params.get('layer_decomposition_options', {}).get('max_images', 100):
        task_db.fail_task(task_id, 'Provider输出数量超过请求上限')
        return {'success':False, 'error':'Provider输出数量超过请求上限'}, 502
    recognitions = [layer_options.recognition(item.get('text_recognition')) for item in provider_items]
    if len(json.dumps(recognitions).encode()) > 8 * 1024 * 1024:
        task_db.fail_task(task_id, 'OCR元数据总量超过8MB限制')
        return {'success':False,'error':'OCR元数据总量超过8MB限制'}, 502
    saved = []
    provider_items = sorted(provider_items, key=lambda value: int(value.get('z_index') or 0))
    for index, item in enumerate(provider_items):
        image_source = item.get('image_source') or item.get('data_url')
        if not image_source:
            continue
        z_index = int(item.get('z_index', index) or 0)
        is_base = z_index == 0
        item_format = str(item.get('output_format') or ('png' if not is_base else params.get('output_format', 'png'))).lower()
        extension = 'jpg' if item_format in {'jpg', 'jpeg'} else 'png'
        mime_type = 'image/jpeg' if extension == 'jpg' else 'image/png'
        path, mime_type = _save_generated_image(image_source, output_dir, 'base' if is_base else f'layer_{z_index:02d}')
        filename = os.path.basename(path)
        storage.register_file(task_id, 'output_image', path, mime_type)
        metadata = storage.inspect_image(path)
        thumbnail_name = 'base_thumb.webp' if is_base else f'layer_{z_index:02d}_thumb.webp'
        thumbnail_path = os.path.join(output_dir, thumbnail_name)
        storage.create_image_thumbnail(path, thumbnail_path, max_size=320)
        storage.register_file(task_id, 'output_thumbnail', thumbnail_path, 'image/webp')
        saved.append({
            'z_index': z_index,
            'name': item.get('name') or ('基础图' if is_base else f'图层 {z_index}'),
            'description': item.get('description') or '',
            'bounding_box': item.get('bounding_box'),
            'text_recognition': layer_options.recognition(item.get('text_recognition')),
            'size': item.get('size') or f'{metadata["width"]}x{metadata["height"]}',
            'output_format': item_format,
            'local_url': f'/api/tasks/{task_id}/file/{filename}',
            'thumbnail_url': f'/api/tasks/{task_id}/file/{thumbnail_name}',
            'source_url': item.get('source_url'),
            'width': metadata['width'],
            'height': metadata['height'],
        })
    if not saved or not any(item['z_index'] == 0 for item in saved):
        task_db.fail_task(task_id, 'Ark 未返回有效的基础图')
        return {'success': False, 'error': 'Ark 未返回有效的基础图'}, 500

    saved.sort(key=lambda item: item['z_index'])
    base_item = next(item for item in saved if item['z_index'] == 0)
    canvas_width, canvas_height = base_item['width'], base_item['height']
    document_layers = []
    for item in saved:
        bounds = (item.get('bounding_box') or {}).get('absolute')
        if not isinstance(bounds, list) or len(bounds) != 4:
            bounds = [0, 0, canvas_width, canvas_height]
        left, top, right, bottom = [int(value) for value in bounds]
        document_layers.append({
            'id': f'{task_id}:{item["z_index"]}', **item,
            'x': left, 'y': top,
            'display_width': max(1, right - left),
            'display_height': max(1, bottom - top),
            'rotation': 0, 'opacity': 1, 'visible': True,
            'locked': item['z_index'] == 0,
        })
    result = {
        'project_id': project_id,
        'base_image': base_item['local_url'],
        'local_images': [base_item['local_url']],
        'local_thumbnails': [base_item['thumbnail_url']],
        'layers': [item for item in saved if item['z_index'] != 0],
        'source_urls': response_data.get('source_urls') or [],
    }
    document = {
        'canvas': {'width': canvas_width, 'height': canvas_height, 'background': 'transparent'},
        'layers': document_layers,
        'selected_layer_id': document_layers[-1]['id'] if document_layers else None,
        'task_id': task_id,
    }
    if not task_db.complete_task(task_id, result, output_dir):
        storage.remove_task_output_files(task_id)
        task_db.finalize_task_cancel(task_id)
        return {'success': False, 'cancelled': True, 'error': '任务已取消'}, 409
    task_db.add_layer_revision(
        int(project_id), task_id, task.get('prompt') or '', params.get('size', 'auto'), result, document,
    )
    return {'success': True, 'task_id': task_id, 'project_id': project_id, 'result': result}, 200


def _validate_layer_source(metadata, size_bytes):
    if metadata.get('format') not in {'png', 'jpeg'}:
        raise ValueError('图层分解源图片仅支持 PNG 或 JPEG')
    if size_bytes > 30 * 1024 * 1024:
        raise ValueError('图层分解源图片不能超过 30 MB')
    if not 512 * 512 <= int(metadata.get('pixels') or 0) <= 6000 * 6000:
        raise ValueError('图层分解源图片总像素必须在 512×512 到 6000×6000 之间')
    ratio = metadata['width'] / metadata['height']
    if not 1 / 16 <= ratio <= 16:
        raise ValueError('图层分解源图片宽高比必须在 1:16 到 16:1 之间')


def _queue_layer_task(project, prompt, size, options_data=None):
    normalized_size = 'auto' if str(size).lower() == 'auto' else str(size).upper()
    if normalized_size not in {'auto', '1K', '1.5K', '2K'}:
        raise ValueError('图层分解分辨率仅支持 Auto、1K、1.5K 或 2K')
    provider, provider_config = get_layer_provider_config()
    if not get_provider_key(provider, provider_config):
        raise ValueError('Ark 未配置 API Key')
    model = get_provider_default_model(provider, provider_config)
    options = layer_options.options(options_data or {}, model)
    task_id = task_db.create_task(
        'layer', prompt or '', {
            'project_id': project['id'], 'size': normalized_size,
            'output_format': 'png', 'provider': 'ark',
            'model': get_provider_default_model(provider, provider_config),
            'layer_decomposition': True,
            **({'layer_decomposition_options': options} if options else {}),
        }, provider='ark', status='preparing',
    )
    output_dir = storage.task_output_dir('layer', task_id)
    source_path = os.path.join(output_dir, 'source.png')
    storage.clone_workspace_image(project['source_path'], source_path)
    storage.register_file(task_id, 'input_image', source_path, 'image/png')
    task_db.update_task(task_id, output_dir=output_dir, status='pending', next_run_at=task_db.utcnow())
    task_db.update_layer_project(project['id'], current_task_id=task_id)
    return task_id


@app.route('/api/generate', methods=['POST'])
def generate():
    """Queue single-shot image jobs (Ark / Cupsy)."""
    db_task_id = None
    try:
        is_form_request = request.mimetype == 'multipart/form-data'

        if is_form_request:
            prompt = normalize_newlines(request.form.get('prompt'))
            aspect_ratio = request.form.get('aspect_ratio', '3:4')
            resolution = request.form.get('resolution', '1K')
            custom_width = request.form.get('custom_width')
            custom_height = request.form.get('custom_height')
            output_format = request.form.get('output_format', 'png').lower()
            background = request.form.get('background', 'default').lower()
            watermark = request.form.get('watermark', 'false').lower() == 'true'
            provider = request.form.get('provider', get_session_image_provider())
            model_id = request.form.get('model', None)
            raw_image_urls = request.form.get('image_urls', '[]')
            try:
                image_urls = json.loads(raw_image_urls)
            except (TypeError, json.JSONDecodeError):
                return jsonify({'success': False, 'error': 'image_urls 格式错误'}), 400
        else:
            data = request.get_json(silent=True) or {}
            prompt = normalize_newlines(data.get('prompt'))
            aspect_ratio = data.get('aspect_ratio', '9:16')
            resolution = data.get('resolution', '1K')
            custom_width = data.get('custom_width')
            custom_height = data.get('custom_height')
            output_format = str(data.get('output_format', 'png')).lower()
            background = str(data.get('background', 'default')).lower()
            watermark = as_bool(data.get('watermark', False))
            provider = data.get('provider', get_session_image_provider())
            model_id = data.get('model')
            image_urls = data.get('image_urls') or []

        if not isinstance(image_urls, list) or any(not isinstance(url, str) for url in image_urls):
            return jsonify({'success': False, 'error': 'image_urls 必须是字符串数组'}), 400

        if not prompt:
            return jsonify({'success': False, 'error': '请提供图片描述'}), 400
        if provider not in API_PROVIDERS:
            return jsonify({'success': False, 'error': f'未知 provider: {provider}'}), 400
        if (request.form if is_form_request else data).get('canvas_node_id') and 'aspect_ratio' not in (request.form if is_form_request else data):
            aspect_ratio = '1:1'
        aspect_ratio = str(aspect_ratio or '').strip().lower()
        valid_ratios = {'1:1', '4:3', '3:4', '16:9', '9:16', 'custom'} if provider == 'cupsy' else (set(ARK_SEEDREAM_PRO_SIZE_MAP['1K']) | {'auto', 'custom'})
        seedream55 = provider == 'ark' and seedream55_capabilities.enabled(get_provider_default_model(provider, API_PROVIDERS[provider]))
        valid_resolutions = {'1K', '2K'}
        if seedream55: valid_resolutions = {'1K', '1.5K', '2K'}
        if aspect_ratio not in valid_ratios:
            return jsonify({'success': False, 'error': f'不支持的图片比例: {aspect_ratio}'}), 400
        if aspect_ratio != 'custom' and str(resolution).upper() not in valid_resolutions:
            return jsonify({'success': False, 'error': f'不支持的图片分辨率: {resolution}'}), 400
        resolution = str(resolution).upper()
        resolved_size = None
        if provider == 'cupsy' and aspect_ratio != 'custom':
            resolved_size = CUPSY_SEEDREAM_SIZE_MAP[resolution][aspect_ratio]
        else:
            try:
                resolved_size = resolve_seedream_pro_size(
                    aspect_ratio, resolution, custom_width, custom_height, seedream55=seedream55,
                )
            except ValueError as error:
                return jsonify({'success': False, 'error': str(error)}), 400
            if aspect_ratio == 'custom':
                custom_width, custom_height = (int(value) for value in resolved_size.split('x', 1))
        provider, provider_config = get_image_provider_config(provider)
        if not get_provider_key(provider, provider_config):
            return jsonify({'success': False, 'error': f'{provider} 未配置 API Key'}), 400
        if provider == 'cupsy' and output_format not in {'png', 'jpeg'}:
            return jsonify({'success': False, 'error': 'Cupsy 图片格式仅支持 PNG 或 JPEG'}), 400
        if provider == 'cupsy':
            if (request.files.getlist('images') or image_urls) and not _cupsy_source_ready():
                return jsonify({'success': False, 'error': 'Cupsy 参考图片需要配置公网 HTTP(S) 素材源'}), 400
        model_id = get_provider_default_model(provider, provider_config)
        from canvas_image_params import validate_submission
        from canvas_store import CanvasError
        try:
            validate_submission(request.form if is_form_request else data, provider, model_id)
        except CanvasError as error:
            return jsonify(success=False, error=str(error)), error.status

        images_files = request.files.getlist('images') if is_form_request else []
        workspace_image_paths = []
        for image_url in image_urls:
            image_path = storage.resolve_workspace_asset_url('img_tabs', image_url)
            if not image_path:
                return jsonify({'success': False, 'error': '参考图片不存在或不属于当前工作区'}), 400
            workspace_image_paths.append(image_path)
        if images_files or workspace_image_paths:
            max_reference_images = ARK_SEEDREAM_PRO_MAX_REFERENCES
            if len(images_files) + len(workspace_image_paths) > max_reference_images:
                return jsonify({'success': False, 'error': f'当前 Provider 最多只能上传{max_reference_images}张图片'}), 400
        if background not in ({'default', 'auto', 'transparent', 'opaque'} if seedream55 else {'default', 'transparent', 'opaque'}):
            return jsonify({'success': False, 'error': '背景参数仅支持默认、透明或不透明'}), 400
        if seedream55 and background == 'transparent' and output_format != 'png':
            return jsonify(success=False, error='透明背景必须使用 PNG 输出格式'), 400
        if background != 'default' and not seedream55:
            if provider != 'ark':
                return jsonify({'success': False, 'error': '背景控制仅支持 Seedream 5.0 Pro'}), 400
            if len(images_files) + len(workspace_image_paths) != 1:
                return jsonify({'success': False, 'error': '背景控制需要且只能使用一张带 Alpha 通道的参考图'}), 400
            source_metadata = storage.inspect_uploaded_image(images_files[0]) if images_files else storage.inspect_image(workspace_image_paths[0])
            if not source_metadata.get('has_alpha'):
                return jsonify({'success': False, 'error': '参考图片不包含 Alpha 通道，无法控制透明背景'}), 400
            if background == 'transparent' and output_format == 'jpeg':
                return jsonify({'success': False, 'error': '透明背景必须使用 PNG 输出格式'}), 400

        params = {
            'seedream55': seedream55,
            'aspect_ratio': aspect_ratio,
            'provider': provider,
            'model': model_id,
        }
        if aspect_ratio != 'custom':
            params['resolution'] = resolution
        params['output_format'] = output_format
        params['watermark'] = watermark
        params['size'] = resolved_size
        if background != 'default':
            params['background'] = background
        elif seedream55:
            params['background'] = 'auto'
        if aspect_ratio == 'custom':
            params['custom_width'] = custom_width
            params['custom_height'] = custom_height
        db_task_id = task_db.create_task('image', prompt, params, provider=provider, status='preparing')
        output_dir = storage.task_output_dir('image', db_task_id)
        task_db.update_task(db_task_id, output_dir=output_dir)

        for index, image_file in enumerate(images_files):
            path = os.path.join(output_dir, f'ref_{index}.png')
            storage.save_uploaded_image(image_file, path)
            storage.register_file(db_task_id, 'input_image', path, 'image/png')
        for offset, image_path in enumerate(workspace_image_paths, start=len(images_files)):
            path = os.path.join(output_dir, f'ref_{offset}.png')
            storage.clone_workspace_image(image_path, path)
            storage.register_file(db_task_id, 'input_image', path, 'image/png')

        if provider == 'cupsy':
            for index, asset in enumerate(task_db.list_assets(db_task_id)):
                if asset['kind'] == 'input_image':
                    imported = create_cupsy_asset_from_path(asset['path'], 'image')
                    task_db.link_task_provider_asset(db_task_id, imported['id'], 'reference_image', index)

        task_db.update_task(db_task_id, status='pending', next_run_at=task_db.utcnow())
        return jsonify({
            'success': True,
            'queued': True,
            'task_id': db_task_id,
            'status': 'pending',
        }), 202

    except ClientDisconnected:
        if db_task_id is not None:
            task_db.fail_task(db_task_id, '连接断开，请重试')
        return jsonify({'success': False, 'error': '连接断开，请重试'}), 400
    except RequestEntityTooLarge:
        if db_task_id is not None:
            task_db.fail_task(db_task_id, '上传文件总大小超过100MB限制')
        return jsonify({'success': False, 'error': '上传文件总大小超过100MB限制'}), 413
    except Exception as e:
        if db_task_id is not None:
            task_db.fail_task(db_task_id, str(e))
        print(f'Error generating image: {str(e)}')
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        storage.release_process_memory()


# ============================================================
# Video Generation (Seedance 2.0 / 2.5 via BytePlus Ark)
# ============================================================

ARK_VIDEO_CONFIG = profile_runtime.ProfileConfig(config_v2.video_byteplus(config), 'ark')
CUPSY_VIDEO_CONFIG = profile_runtime.ProfileConfig(config_v2.video_cupsy(config), 'cupsy')
CUPSY_AUDIO_CONFIG = profile_runtime.ProfileConfig(config_v2.audio_cupsy(config), 'cupsy')
VIDEO_CONFIG = profile_runtime.ProfileConfig(config_v2.polling(config, 'video'), None)
AUDIO_CONFIG = profile_runtime.ProfileConfig(config_v2.polling(config, 'audio'), None)
SEEDANCE_20 = 'seedance-2.0'
SEEDANCE_25 = 'seedance-2.5'
SEEDANCE_25_MODERATED = 'seedance-2.5-moderated'
CUPSY_SEEDANCE_MODELS = {SEEDANCE_25, SEEDANCE_25_MODERATED}
CUPSY_AUDIO_MODEL = 'seed-audio-1.0'
CUPSY_AUDIO_FORMATS = {'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg_opus': 'audio/ogg'}
CUPSY_AUDIO_SAMPLE_RATES = {8000, 16000, 24000, 32000, 44100, 48000}
CUPSY_AUDIO_SPEAKERS = {'vivi', 'mindy', 'kian', 'jess', 'opal'}
CUPSY_ASSET_SOURCE_MIN_TTL = 7200
# Seedance 2.5 on BytePlus Ark is reached through an account-specific endpoint ID (ep-...).
# The repository only ships a placeholder; a real ID must come from config.json or the profile.
ARK_ENDPOINT_ID_PLACEHOLDER = config_v2.ENDPOINT_ID_PLACEHOLDER
SEEDANCE_25_MISSING_ENDPOINT_ERROR = (
    'Ark Seedance 2.5 尚未配置接入点ID：请在 config.json 的 providers.byteplus.endpoint_ids.seedance_2_5 '
    '或该视频接口配置中填写 BytePlus 控制台的 ep-... 接入点ID'
)
is_placeholder_endpoint_id = config_v2.is_placeholder_endpoint_id


def deployment_seedance_25_endpoint():
    """Deployment-wide Seedance 2.5 endpoint ID (providers.byteplus.endpoint_ids.seedance_2_5)."""
    return config['providers']['byteplus']['endpoint_ids']['seedance_2_5']
VIDEO_MODEL_SPECS = {
    SEEDANCE_20: {
        'resolutions': {'480p', '720p', '1080p'},
        'duration_min': 4,
        'duration_max': 15,
        'output_formats': {'mp4'},
        'max_ref_images': 9,
        'max_ref_videos': 3,
        'max_ref_audios': 3,
        'audio_only': False,
        'fast': True,
    },
    SEEDANCE_25: {
        'resolutions': {'480p', '720p', '1080p'},
        'duration_min': 4,
        'duration_max': 30,
        'output_formats': {'mp4', 'mov'},
        'max_ref_images': 30,
        'max_ref_videos': 10,
        'max_ref_audios': 10,
        'audio_only': True,
        'fast': False,
    },
}
ARK_VIDEO_MAX_REQUEST_BYTES = 64 * 1024 * 1024
ARK_VIDEO_MAX_IMAGE_BYTES = 30 * 1024 * 1024
ARK_VIDEO_MAX_AUDIO_BYTES = 15 * 1024 * 1024


def _resolve_video_model(requested_model, provider_config, fast=False):
    """Resolve a stable UI model alias to the provider's concrete model ID."""
    requested = str(requested_model or SEEDANCE_20).strip().lower()
    model_20 = str(provider_config.get('model') or 'dreamina-seedance-2-0-260128').strip()
    # A profile without its own mapping keeps the pre-2026-11-13 behaviour of using the
    # deployment-wide mapping from config.json (previously a hard-coded endpoint ID).
    model_25 = str(
        provider_config.get('seedance_2_5_model')
        or deployment_seedance_25_endpoint()
        or ''
    ).strip()
    configured_25 = not is_placeholder_endpoint_id(model_25)

    aliases_25 = {SEEDANCE_25, 'dreamina-seedance-2.5'} | ({model_25.lower()} if configured_25 else set())
    aliases_20 = {SEEDANCE_20, 'dreamina-seedance-2.0', model_20.lower()}
    if requested in aliases_25:
        model_key = SEEDANCE_25
    elif requested in aliases_20:
        model_key = SEEDANCE_20
    else:
        raise ValueError(f'不支持的视频模型: {requested_model}')
    if model_key == SEEDANCE_25 and not configured_25:
        raise ValueError(SEEDANCE_25_MISSING_ENDPOINT_ERROR)

    spec = VIDEO_MODEL_SPECS[model_key]
    if fast and not spec['fast']:
        raise ValueError('Dreamina Seedance 2.5 不支持快速模式')

    model_id = model_25 if model_key == SEEDANCE_25 else model_20
    if model_key == SEEDANCE_20 and fast:
        configured_fast = provider_config.get('fast_model')
        if configured_fast:
            model_id = str(configured_fast)
        elif model_id == 'dreamina-seedance-2-0-260128':
            model_id = 'dreamina-seedance-2-0-fast-260128'
        else:
            raise ValueError('Ark 快速模式需要配置 generation.video.byteplus.fast_model')
    return model_key, model_id, spec


def _video_fast_available(provider_config):
    model = str(provider_config.get('model') or 'dreamina-seedance-2-0-260128').strip()
    return bool(provider_config.get('fast_model')) or model == 'dreamina-seedance-2-0-260128'


def _cupsy_settings():
    return {
        **CUPSY_VIDEO_CONFIG,
        'api_key': CUPSY_VIDEO_CONFIG.get('api_key', ''),
        'source_base_url': CUPSY_VIDEO_CONFIG.get('source_base_url', '').rstrip('/'),
    }


def _cupsy_audio_settings():
    shared = _cupsy_settings()
    return {
        **shared,
        **CUPSY_AUDIO_CONFIG,
        'api_key': shared['api_key'],
        'endpoint': CUPSY_AUDIO_CONFIG.get('endpoint') or shared.get('endpoint', 'https://cupsy.io'),
        'model': CUPSY_AUDIO_CONFIG.get('model') or CUPSY_AUDIO_MODEL,
    }


def _cupsy_headers(idempotency_key=None):
    settings = _cupsy_settings()
    headers = {
        'Authorization': f'Bearer {settings["api_key"]}',
        'Content-Type': 'application/json',
    }
    if idempotency_key:
        headers['Idempotency-Key'] = idempotency_key
    return headers


def _generate_cupsy_image(task):
    """Replay the frozen image request after 202 or transport errors, never a new job."""
    task_id = task['id']
    params = dict(task.get('params') or {})
    settings = _cupsy_settings()
    endpoint = settings.get('endpoint', 'https://cupsy.io').rstrip('/')
    body = params.get('_cupsy_request')
    if body is None:
        assets = task_db.list_task_provider_assets(task_id)
        failed = next((asset for asset in assets if asset['status'] in {'failed', 'deleted'}), None)
        if failed:
            return {'success': False, 'error': f'参考素材导入失败: {failed.get("error") or failed.get("original_name")}', 'retryable': False}, 400
        if any(asset['status'] != 'active' or not asset.get('asset_uri') for asset in assets):
            return {'pending': True, 'retry_after': 2}, 202
        body = {
            'model': 'seedream-5.0-pro', 'prompt': task['prompt'],
            'size': params['size'], 'n': 1, 'response_format': 'url',
            'stream': False, 'output_format': params.get('output_format', 'png'),
            'watermark': bool(params.get('watermark', False)),
        }
        if assets:
            body['image'] = [asset['asset_uri'] for asset in assets]
        params['_cupsy_request'] = body
        params['_cupsy_idempotency_key'] = f'nanobanana-image-{task_id}-{uuid.uuid4().hex}'
        task_db.update_task(task_id, params=params)
    try:
        response = HTTP.post(
            f'{endpoint}/v1/images/generations', json=body,
            headers=_cupsy_headers(params['_cupsy_idempotency_key']),
            timeout=(profile_runtime.setting('upload_timeout_seconds', 30), API_PROVIDERS['cupsy'].get('request_timeout_seconds', 120)),
        )
        if response.status_code == 202:
            payload = response.json()
            if payload.get('id'):
                task_db.update_task(task_id, external_task_id=payload['id'])
            try:
                delay = int(response.headers.get('Retry-After', payload.get('retry_after', 15)))
            except (ValueError, TypeError):
                delay = 15
            return {'pending': True, 'retry_after': max(2, min(120, delay))}, 202
        if response.status_code == 429 or response.status_code >= 500:
            return {'pending': True, 'retry_after': 15, 'error': _cupsy_error(response, 'Cupsy 暂时不可用')}, 202
        if response.status_code != 200:
            return {'success': False, 'retryable': False, 'error': _cupsy_error(response, 'Cupsy 图片生成失败')}, 502
        payload = response.json()
        images, urls = [], []
        for item in payload.get('data') or []:
            url = item.get('url')
            if not isinstance(url, str):
                continue
            url = urljoin(endpoint + '/', url)
            if not url.startswith(('http://', 'https://')):
                continue
            # Only attach credentials to same-origin artifact endpoints.
            authenticated = urlsplit(url)[:2] == urlsplit(endpoint)[:2]
            images.append({'url': url, 'cupsy_authenticated': authenticated})
            urls.append(url)
        if not images:
            return {'success': False, 'retryable': False, 'error': 'Cupsy 未返回生成图片'}, 502
        return {'success': True, 'images': images, 'source_urls': urls, 'output_format': body['output_format']}, 200
    except requests.RequestException as error:
        return {'pending': True, 'retry_after': 15, 'error': str(error)}, 202


def _cupsy_error(response, fallback):
    try:
        payload = response.json() if response.text else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        return fallback
    error = payload.get('error')
    return str(
        payload.get('message')
        or (error.get('message') if isinstance(error, dict) else error)
        or fallback
    )


def _cupsy_asset_json(asset):
    return {
        'id': asset['id'],
        'provider': asset['provider'],
        'external_asset_id': asset.get('external_asset_id'),
        'asset_uri': asset.get('asset_uri'),
        'kind': asset['kind'],
        'status': asset['status'],
        'name': asset.get('original_name'),
        'mime_type': asset.get('mime_type'),
        'size_bytes': asset.get('size_bytes') or 0,
        'error': asset.get('error'),
        'created_at': asset.get('created_at'),
        'updated_at': asset.get('updated_at'),
        'last_used_at': asset.get('last_used_at'),
        'content_url': f'/api/cupsy/assets/{asset["id"]}/content',
        'thumbnail_url': f'/api/cupsy/assets/{asset["id"]}/thumbnail' if asset['kind'] == 'image' else None,
    }


def _cupsy_source_ready(settings=None):
    base_url = (settings or _cupsy_settings()).get('source_base_url', '')
    return base_url.startswith(('http://', 'https://'))


def _cupsy_source_url(asset):
    settings = _cupsy_settings()
    base_url = settings['source_base_url']
    if not _cupsy_source_ready(settings):
        raise ValueError('Cupsy 素材导入需要配置 deployment.cupsy_source.base_url 公网 HTTP(S) 地址')
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='cupsy-asset-source')
    token = serializer.dumps({'asset_id': asset['id'], 'sha256': asset['sha256']})
    return f'{base_url}/api/cupsy/source/{token}'


def _cupsy_asset_create_request(asset):
    source_url = asset.get('create_source_url')
    if not source_url:
        source_url = _cupsy_source_url(asset)
        task_db.update_provider_asset(asset['id'], create_source_url=source_url)
    body = {'type': asset['kind'], 'source_url': source_url}
    fingerprint = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()[:24]
    return body, f'nanobanana-asset-{asset["id"]}-{fingerprint}'


def create_cupsy_asset_from_upload(file_storage, kind=None):
    mime_type = file_storage.mimetype or 'application/octet-stream'
    inferred_kind = mime_type.split('/', 1)[0]
    kind = kind or inferred_kind
    if kind not in {'image', 'video', 'audio'}:
        raise ValueError('Cupsy 素材仅支持图片、视频或音频')
    if inferred_kind != kind:
        raise ValueError('素材类型与文件 MIME 类型不一致')
    _cupsy_source_url({'id': 0, 'sha256': 'configuration-check'})
    persisted = storage.persist_workspace_upload('cupsy_assets', file_storage)
    local_path = storage.resolve_workspace_asset_url('cupsy_assets', persisted['url'])
    if not local_path:
        raise ValueError('保存 Cupsy 素材失败')
    if profile_runtime.current_profile():
        return create_cupsy_asset_from_path(local_path, kind, persisted['name'])
    sha256 = os.path.basename(local_path).split('.', 1)[0]
    return task_db.create_provider_asset(
        profile_runtime.asset_provider(), kind, sha256, persisted['name'], persisted['mime_type'],
        persisted['size_bytes'], local_path,
    )


def create_cupsy_asset_from_path(path, kind, original_name=None):
    if kind not in {'image', 'video', 'audio'} or not os.path.isfile(path):
        raise ValueError('Cupsy 本地素材无效')
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    mime_type = mimetypes.guess_type(original_name or path)[0] or f'{kind}/octet-stream'
    directory = os.path.join(storage.WORKSPACE_ASSET_DIR, 'cupsy_assets')
    if profile_runtime.current_profile():
        directory = os.path.join(directory, profile_runtime.asset_provider().replace(':', '_'))
    os.makedirs(directory, exist_ok=True)
    extension = os.path.splitext(original_name or path)[1].lower() or mimetypes.guess_extension(mime_type) or '.bin'
    local_path = os.path.join(directory, f'{digest.hexdigest()}{extension}')
    if not os.path.isfile(local_path):
        temp_path = f'{local_path}.{uuid.uuid4().hex}.tmp'
        try:
            shutil.copyfile(path, temp_path)
            os.replace(temp_path, local_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    return task_db.create_provider_asset(
        profile_runtime.asset_provider(), kind, digest.hexdigest(), original_name or os.path.basename(path),
        mime_type, os.path.getsize(local_path), local_path,
    )


@profile_runtime.asset_context
def process_cupsy_asset_once(asset_id):
    """Create or poll one Cupsy Asset without exposing its signed source URL."""
    asset = task_db.get_provider_asset(asset_id)
    if not asset or asset.get('deleted_at'):
        return {'state': 'deleted'}
    settings = _cupsy_settings()
    if not settings['api_key']:
        reason = 'Cupsy 未配置 API Key'
        task_db.update_provider_asset(asset_id, status='failed', error=reason,
                                      next_run_at=None, lease_owner=None, lease_until=None)
        return {'state': 'failed', 'error': reason}
    endpoint = settings.get('endpoint', 'https://cupsy.io').rstrip('/')
    try:
        if not asset.get('external_asset_id'):
            body, idempotency_key = _cupsy_asset_create_request(asset)
            response = HTTP.post(
                f'{endpoint}/v1/assets',
                headers=_cupsy_headers(idempotency_key),
                json=body,
                timeout=(profile_runtime.setting('upload_timeout_seconds', 10), profile_runtime.setting('request_timeout_seconds', 60)),
            )
            if response.status_code not in {200, 201, 202}:
                reason = _cupsy_error(response, f'Cupsy 素材创建失败 {response.status_code}')
                if response.status_code == 429 or response.status_code >= 500:
                    return {'state': 'retry', 'error': reason}
                task_db.update_provider_asset(asset_id, status='failed', error=reason,
                                              next_run_at=None, lease_owner=None, lease_until=None)
                return {'state': 'failed', 'error': reason}
            payload = response.json()
            external_id = payload.get('id') or payload.get('asset_id')
            if not external_id:
                return {'state': 'retry', 'error': 'Cupsy 未返回素材 ID'}
            asset_uri = payload.get('asset_uri') or f'asset://{external_id}'
            task_db.update_provider_asset(
                asset_id, external_asset_id=external_id, asset_uri=asset_uri,
                status='processing', error=None, lease_owner=None, lease_until=None,
            )
            return {'state': 'pending'}

        response = HTTP.get(
            f'{endpoint}/v1/assets/{asset["external_asset_id"]}',
            headers=_cupsy_headers(), timeout=(10, profile_runtime.setting('poll_timeout_seconds', 30)),
        )
        if response.status_code >= 400:
            reason = _cupsy_error(response, f'Cupsy 素材查询失败 {response.status_code}')
            if response.status_code == 429 or response.status_code >= 500:
                return {'state': 'retry', 'error': reason}
            task_db.update_provider_asset(asset_id, status='failed', error=reason,
                                          next_run_at=None, lease_owner=None, lease_until=None)
            return {'state': 'failed', 'error': reason}
        payload = response.json()
        status = str(payload.get('status') or '').lower()
        if status in {'active', 'succeeded', 'ready'} and payload.get('usable', True):
            task_db.update_provider_asset(
                asset_id, status='active', asset_uri=payload.get('asset_uri') or asset.get('asset_uri'),
                mime_type=payload.get('mime_type') or asset.get('mime_type'),
                size_bytes=payload.get('size_bytes') or asset.get('size_bytes'), error=None,
                next_run_at=None, lease_owner=None, lease_until=None,
            )
            return {'state': 'active'}
        if status in {'failed', 'error', 'deleted', 'expired'}:
            reason = payload.get('error') or payload.get('message') or f'Cupsy 素材状态: {status}'
            task_db.update_provider_asset(asset_id, status='failed', error=str(reason),
                                          next_run_at=None, lease_owner=None, lease_until=None)
            return {'state': 'failed', 'error': str(reason)}
        return {'state': 'pending'}
    except (requests.RequestException, ValueError) as error:
        return {'state': 'retry', 'error': str(error)}


@app.route('/api/cupsy/assets', methods=['GET', 'POST'])
def cupsy_assets():
    if request.method == 'GET':
        try:
            ids = None
            if 'ids' in request.args:
                ids = list(dict.fromkeys(int(value) for value in request.args['ids'].split(',')))
                if not ids or len(ids) > 100 or any(value <= 0 for value in ids):
                    raise ValueError()
            limit = max(1, min(100, int(request.args['limit']))) if 'limit' in request.args else None
            offset = max(0, int(request.args.get('offset', 0)))
        except ValueError:
            return jsonify({'success': False, 'error': '素材分页或 ID 参数无效'}), 400
        kind = request.args.get('kind') or None
        search = request.args.get('q', '').strip()
        if ids is None and kind not in (None, 'image', 'video', 'audio'):
            return jsonify(success=False, error='未知素材类型'), 400
        assets = task_db.list_provider_assets('cupsy', limit=limit, offset=offset, ids=ids, kind=kind, search=search)
        total = task_db.count_provider_assets('cupsy', kind=kind, search=search) if ids is None else len(assets)
        kind_counts = {k:task_db.count_provider_assets('cupsy',kind=k,search=search if ids is None else '') for k in ('image','video','audio')}
        return jsonify({
            'success': True,
            'configured': bool(_cupsy_settings()['api_key']),
            'source_ready': _cupsy_source_ready(),
            'assets': [_cupsy_asset_json(asset) for asset in assets],
            'kind_counts': kind_counts,
            'total': total,
            'has_more': ids is None and limit is not None and offset + len(assets) < total,
            'pending_ids': [asset['id'] for asset in assets if asset['status'] not in {'active', 'failed', 'deleted'}],
            'missing_ids': [] if ids is None else sorted(set(ids) - {asset['id'] for asset in assets}),
        })
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'success': False, 'error': '请选择素材文件'}), 400
    try:
        from local_uploads import capture_user_upload
        with capture_user_upload(upload):
            asset = create_cupsy_asset_from_upload(upload, request.form.get('kind') or None)
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    return jsonify({'success': True, 'asset': _cupsy_asset_json(asset)}), 202


@app.route('/api/cupsy/assets/<int:asset_id>/content', methods=['GET', 'HEAD'])
def cupsy_asset_content(asset_id):
    asset = task_db.get_provider_asset(asset_id)
    if not asset or asset.get('deleted_at') or not os.path.isfile(asset['local_path']):
        return jsonify({'success': False, 'error': '素材不存在'}), 404
    return send_file(asset['local_path'], mimetype=asset.get('mime_type'), conditional=True)


@app.route('/api/cupsy/assets/<int:asset_id>/thumbnail', methods=['GET', 'HEAD'])
def cupsy_asset_thumbnail(asset_id):
    asset = task_db.get_provider_asset(asset_id)
    if not asset or asset.get('deleted_at') or asset['kind'] != 'image' or not os.path.isfile(asset['local_path']):
        return jsonify({'success': False, 'error': '素材不存在'}), 404
    try:
        path = storage.cached_image_thumbnail(asset['local_path'])
        return send_file(path, mimetype='image/webp', conditional=True, max_age=3600)
    except (OSError, ValueError):
        return jsonify({'success': False, 'error': '素材预览不可用'}), 422


@app.route('/api/cupsy/source/<token>', methods=['GET', 'HEAD'])
def cupsy_asset_source(token):
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='cupsy-asset-source')
    try:
        # Verify signature before resolving the account-specific lifetime.
        payload = serializer.loads(token)
        source_asset = task_db.get_provider_asset(payload.get('asset_id'))
        with profile_runtime.profile_scope(profile_runtime.asset_selection(source_asset)):
            ttl = max(CUPSY_ASSET_SOURCE_MIN_TTL, int(_cupsy_settings().get(
                'asset_token_ttl_seconds', CUPSY_ASSET_SOURCE_MIN_TTL) or CUPSY_ASSET_SOURCE_MIN_TTL))
        payload = serializer.loads(token, max_age=ttl)
    except SignatureExpired:
        return jsonify({'success': False, 'error': '素材地址已过期'}), 410
    except BadSignature:
        return jsonify({'success': False, 'error': '素材地址无效'}), 404
    asset = task_db.get_provider_asset(payload.get('asset_id'))
    if (
        not asset or asset.get('deleted_at') or asset.get('sha256') != payload.get('sha256')
        or not os.path.isfile(asset['local_path'])
    ):
        return jsonify({'success': False, 'error': '素材不存在'}), 404
    return send_file(asset['local_path'], mimetype=asset.get('mime_type'), conditional=True)


@profile_runtime.asset_context
def _delete_cupsy_asset(asset_id):
    asset = task_db.get_provider_asset(asset_id)
    if not asset or asset.get('deleted_at'):
        return False, 404, '素材不存在'
    if task_db.provider_asset_has_active_tasks(asset_id):
        return False, 409, '素材正被进行中的任务使用'
    settings = _cupsy_settings()
    if asset.get('external_asset_id') and settings['api_key']:
        try:
            response = HTTP.delete(
                f'{settings.get("endpoint", "https://cupsy.io").rstrip("/")}/v1/assets/{asset["external_asset_id"]}',
                headers=_cupsy_headers(), timeout=(10, profile_runtime.setting('request_timeout_seconds', 30)),
            )
        except requests.RequestException as error:
            return False, 502, f'Cupsy 素材删除失败: {error}'
        if response.status_code not in {200, 204, 404}:
            return False, 502, _cupsy_error(response, 'Cupsy 素材删除失败')
    now = task_db.utcnow()
    task_db.update_provider_asset(
        asset_id, status='deleted', deleted_at=now, next_run_at=None,
        lease_owner=None, lease_until=None, error=None,
    )
    try:
        os.remove(asset['local_path'])
    except FileNotFoundError:
        pass
    try:
        os.remove(asset['local_path'] + '.thumb.webp')
    except FileNotFoundError:
        pass
    return True, 200, None


@app.route('/api/cupsy/assets/bulk-delete', methods=['POST'])
def bulk_delete_cupsy_assets():
    data = request.get_json(silent=True) or {}
    raw_ids = data.get('ids')
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({'success': False, 'error': 'ids 必须是非空数组'}), 400
    if len(raw_ids) > 100:
        return jsonify({'success': False, 'error': '单次最多删除 100 个素材'}), 400
    if any(not isinstance(asset_id, int) or isinstance(asset_id, bool) for asset_id in raw_ids):
        return jsonify({'success': False, 'error': 'ids 包含无效素材 ID'}), 400
    asset_ids = list(dict.fromkeys(raw_ids))
    if any(asset_id <= 0 for asset_id in asset_ids):
        return jsonify({'success': False, 'error': 'ids 包含无效素材 ID'}), 400

    deleted_ids = []
    missing_ids = []
    failed = []
    for asset_id in asset_ids:
        deleted, status_code, error = _delete_cupsy_asset(asset_id)
        if deleted:
            deleted_ids.append(asset_id)
        elif status_code == 404:
            missing_ids.append(asset_id)
        else:
            failed.append({'id': asset_id, 'status': status_code, 'error': error})
    return jsonify({
        'success': not failed,
        'deleted': len(deleted_ids),
        'deleted_ids': deleted_ids,
        'missing_ids': missing_ids,
        'failed': failed,
    })


@app.route('/api/cupsy/assets/<int:asset_id>', methods=['DELETE'])
def delete_cupsy_asset(asset_id):
    deleted, status_code, error = _delete_cupsy_asset(asset_id)
    if not deleted:
        return jsonify({'success': False, 'error': error}), status_code
    return jsonify({'success': True})


def _validate_video_settings(model_key, spec, ratio, duration, resolution, output_format, video_mode, fast, files_data):
    if duration != -1 and not spec['duration_min'] <= duration <= spec['duration_max']:
        return f'{model_key} 不支持的视频时长: {duration}'
    if resolution not in spec['resolutions']:
        return f'{model_key} 不支持的视频分辨率: {resolution}'
    if output_format not in spec['output_formats']:
        return f'{model_key} 不支持的输出格式: {output_format}'
    if fast and not spec['fast']:
        return f'{model_key} 不支持快速模式'

    if video_mode == 'keyframe':
        has_first = bool(files_data.get('first_frame'))
        has_last = bool(files_data.get('last_frame'))
        if has_last and not has_first:
            return '设置尾帧时必须同时提供首帧'
        if model_key == SEEDANCE_25 and (has_first or has_last) and ratio != 'adaptive':
            return 'Seedance 2.5 首尾帧模式仅支持 adaptive 画幅'
        return None

    ref_images = files_data.get('ref_images', [])
    ref_videos = files_data.get('ref_videos', [])
    ref_audios = files_data.get('ref_audios', [])
    if len(ref_images) > spec['max_ref_images']:
        return f'{model_key} 最多支持 {spec["max_ref_images"]} 张参考图片'
    if len(ref_videos) > spec['max_ref_videos']:
        return f'{model_key} 最多支持 {spec["max_ref_videos"]} 个参考视频'
    if len(ref_audios) > spec['max_ref_audios']:
        return f'{model_key} 最多支持 {spec["max_ref_audios"]} 个参考音频'
    if ref_audios and not spec['audio_only'] and not (ref_images or ref_videos):
        return 'Seedance 2.0 使用参考音频时还必须提供参考图片或视频'
    return None


@app.route('/api/video/provider', methods=['GET'])
def get_video_provider_info():
    cupsy = _cupsy_settings()
    return jsonify({
        'success': True,
        'current': 'ark',
        'fast_available': _video_fast_available(ARK_VIDEO_CONFIG),
        'providers': {
            'ark': {
                'available': bool(ARK_VIDEO_CONFIG.get('api_key')), 'models': [SEEDANCE_20, SEEDANCE_25],
                # False while only the repository placeholder is present: Seedance 2.5 submissions return 400.
                'seedance_2_5_configured': not is_placeholder_endpoint_id(
                    ARK_VIDEO_CONFIG.get('seedance_2_5_model') or deployment_seedance_25_endpoint()),
            },
            'cupsy': {
                'available': bool(cupsy['api_key']),
                'source_ready': _cupsy_source_ready(cupsy),
                'models': [SEEDANCE_25, SEEDANCE_25_MODERATED],
            },
        },
    })


@app.route('/api/audio/provider', methods=['GET'])
def get_audio_provider_info():
    settings = _cupsy_audio_settings()
    return jsonify({
        'success': True,
        'current': 'cupsy',
        'providers': {
            'cupsy': {
                'available': bool(settings['api_key']),
                'source_ready': _cupsy_source_ready(settings),
                'models': [CUPSY_AUDIO_MODEL],
            },
        },
        'capabilities': {
            'formats': list(CUPSY_AUDIO_FORMATS),
            'sample_rates': sorted(CUPSY_AUDIO_SAMPLE_RATES),
            'speaker_aliases': sorted(CUPSY_AUDIO_SPEAKERS),
            'max_duration_seconds': 120,
            'max_audio_references': 3,
            'max_image_references': 1,
            'max_prompt_code_points': 3000,
        },
    })


def _parse_audio_list(value, field_name):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as error:
            raise ValueError(f'{field_name} 必须是数组') from error
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f'{field_name} 必须是数组')
    return value


@app.route('/api/audio/generate', methods=['POST'])
def generate_audio():
    settings = _cupsy_audio_settings()
    if not settings['api_key']:
        return jsonify({'success': False, 'error': 'Cupsy 未配置 API Key'}), 400

    has_files = bool(request.files)
    data = request.form if has_files else (request.get_json(silent=True) or {})
    prompt = normalize_newlines(str(data.get('prompt') or data.get('text_prompt') or '')).strip()
    if not prompt:
        return jsonify({'success': False, 'error': '请填写音频提示词'}), 400
    if len(prompt) > 3000:
        return jsonify({'success': False, 'error': '音频提示词不能超过 3000 个字符'}), 400

    model = str(data.get('model') or settings.get('model') or CUPSY_AUDIO_MODEL).strip().lower()
    if model != CUPSY_AUDIO_MODEL:
        return jsonify({'success': False, 'error': 'Cupsy 音频端点仅支持 Seed Audio 1.0'}), 400
    output_format = str(data.get('output_format') or 'mp3').strip().lower()
    if output_format not in CUPSY_AUDIO_FORMATS:
        return jsonify({'success': False, 'error': '音频格式仅支持 MP3、WAV 或 OGG Opus'}), 400
    try:
        sample_rate = int(data.get('sample_rate') or 44100)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'sample_rate 必须是整数'}), 400
    if sample_rate not in CUPSY_AUDIO_SAMPLE_RATES:
        return jsonify({'success': False, 'error': '不支持的音频采样率'}), 400

    reference_mode = str(data.get('reference_mode') or 'none').strip().lower()
    if reference_mode not in {'none', 'audio', 'image'}:
        return jsonify({'success': False, 'error': '参考模式仅支持 none、audio 或 image'}), 400
    speaker = str(data.get('speaker') or '').strip().lower()
    if speaker and speaker not in CUPSY_AUDIO_SPEAKERS:
        return jsonify({'success': False, 'error': '不支持的预设声线'}), 400
    if speaker and reference_mode == 'image':
        return jsonify({'success': False, 'error': '预设声线不能与图片参考同时使用'}), 400
    if speaker and reference_mode == 'none':
        reference_mode = 'audio'

    try:
        raw_assets = _parse_audio_list(data.get('cupsy_assets', []), 'cupsy_assets')
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400

    pending_links = []
    expected_kind = 'image' if reference_mode == 'image' else 'audio'
    for position, raw_asset in enumerate(raw_assets):
        raw_id = raw_asset.get('id') if isinstance(raw_asset, dict) else raw_asset
        try:
            asset = task_db.get_provider_asset(raw_id)
        except (TypeError, ValueError):
            asset = None
        if (
            reference_mode == 'none' or not asset or asset.get('deleted_at')
            or asset.get('provider') != profile_runtime.asset_provider() or asset.get('kind') != expected_kind
        ):
            return jsonify({'success': False, 'error': 'Cupsy 音频参考素材无效或类型不匹配'}), 400
        pending_links.append((asset, f'reference_{expected_kind}', position))

    uploads = request.files.getlist('references') if has_files else []
    try:
        for upload in uploads:
            if reference_mode == 'none':
                raise ValueError('添加参考文件前请选择音频或图片参考模式')
            asset = create_cupsy_asset_from_upload(upload, expected_kind)
            pending_links.append((asset, f'reference_{expected_kind}', len(pending_links)))
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400

    reference_count = len(pending_links) + (1 if speaker else 0)
    if reference_mode == 'audio' and reference_count > 3:
        return jsonify({'success': False, 'error': 'Seed Audio 1.0 最多支持 3 个音频或声线参考'}), 400
    if reference_mode == 'image' and reference_count != 1:
        return jsonify({'success': False, 'error': '图片参考模式必须且只能使用 1 张图片'}), 400
    if reference_mode == 'none' and reference_count:
        return jsonify({'success': False, 'error': '纯文本模式不能包含参考素材'}), 400

    params = {
        'model': CUPSY_AUDIO_MODEL,
        'output_format': output_format,
        'sample_rate': sample_rate,
        'enable_subtitle': as_bool(data.get('enable_subtitle', True), default=True),
        'watermark': as_bool(data.get('watermark', False)),
        'reference_mode': reference_mode,
        'speaker': speaker or None,
    }
    task_id = task_db.create_task('audio', prompt, params, provider='cupsy', status='pending')
    output_dir = storage.task_output_dir('audio', task_id)
    task_db.update_task(task_id, output_dir=output_dir)
    for asset, role, position in pending_links:
        task_db.link_task_provider_asset(task_id, asset['id'], role, position)
        task_db.link_asset(asset['local_path'], task_id, expires_at=None)
    return jsonify({
        'success': True,
        'queued': True,
        'task_id': task_id,
        'provider': 'cupsy',
        'status': 'pending',
    }), 202


def _build_ark_body(
    prompt, ratio, duration, resolution, fast, generate_audio, return_last_frame,
    video_mode, files_data, provider_config=None, model_id=None,
    model_key=SEEDANCE_20, output_format='mp4',
):
    """构建 Ark (BytePlus) 请求体"""
    prov = provider_config or ARK_VIDEO_CONFIG
    model = model_id or prov.get('model', 'dreamina-seedance-2-0-260128')

    content = []
    if prompt:
        content.append({'type': 'text', 'text': prompt})

    if video_mode == 'keyframe':
        if files_data.get('first_frame'):
            content.append({'type': 'image_url', 'image_url': {'url': files_data['first_frame']}, 'role': 'first_frame'})
        if files_data.get('last_frame'):
            content.append({'type': 'image_url', 'image_url': {'url': files_data['last_frame']}, 'role': 'last_frame'})
    else:
        for img in files_data.get('ref_images', []):
            content.append({'type': 'image_url', 'image_url': {'url': img}, 'role': 'reference_image'})
        for vid in files_data.get('ref_videos', []):
            content.append({'type': 'video_url', 'video_url': {'url': vid}, 'role': 'reference_video'})
        for aud in files_data.get('ref_audios', []):
            content.append({'type': 'audio_url', 'audio_url': {'url': aud}, 'role': 'reference_audio'})

    body = {
        'model': model,
        'content': content,
        'ratio': ratio,
        'duration': duration,
        'resolution': resolution,
        'generate_audio': generate_audio,
        'watermark': False,
        'return_last_frame': return_last_frame
    }
    if model_key == SEEDANCE_25:
        body['output_format'] = output_format
    return body


def _reference_image_data_url(file_storage):
    file_storage.seek(0)
    raw = file_storage.read()
    if len(raw) >= ARK_VIDEO_MAX_IMAGE_BYTES:
        raise ValueError('单张参考图片必须小于 30 MB')
    image = Image.open(io.BytesIO(raw))
    width, height = image.size
    if not 300 <= width <= 6000 or not 300 <= height <= 6000:
        raise ValueError('参考图片宽高必须在 300 到 6000 像素之间')
    ratio = width / height
    if not 0.4 <= ratio <= 2.5:
        raise ValueError('参考图片宽高比必须在 0.4 到 2.5 之间')
    image = image.convert('RGB')
    return f'data:image/png;base64,{image_to_base64(image)}'


def _reference_audio_data_url(file_storage):
    filename = getattr(file_storage, 'filename', '') or ''
    extension = os.path.splitext(filename)[1].lower()
    if extension not in {'.wav', '.mp3'}:
        raise ValueError('参考音频仅支持 WAV 或 MP3')
    file_storage.seek(0)
    raw = file_storage.read()
    if len(raw) >= ARK_VIDEO_MAX_AUDIO_BYTES:
        raise ValueError('单个参考音频必须小于 15 MB')
    mime = 'audio/wav' if extension == '.wav' else 'audio/mp3'
    return f'data:{mime};base64,{base64.b64encode(raw).decode("utf-8")}'


def _parse_files(has_files, video_mode, model_spec=None):
    """从请求中提取文件数据，统一为 base64 data URI"""
    files_data = {}
    if not has_files:
        return files_data
    spec = model_spec or VIDEO_MODEL_SPECS[SEEDANCE_20]

    if video_mode == 'keyframe':
        img_files = request.files.getlist('image')
        if img_files:
            files_data['first_frame'] = _reference_image_data_url(img_files[0])
        last_files = request.files.getlist('last_image')
        if last_files:
            files_data['last_frame'] = _reference_image_data_url(last_files[0])
    else:
        ref_imgs = request.files.getlist('ref_images')
        if ref_imgs:
            if len(ref_imgs) > spec['max_ref_images']:
                raise ValueError(f'最多支持 {spec["max_ref_images"]} 张参考图片')
            files_data['ref_images'] = [_reference_image_data_url(f) for f in ref_imgs]
        ref_vids = request.files.getlist('ref_videos')
        if ref_vids:
            if len(ref_vids) > spec['max_ref_videos']:
                raise ValueError(f'最多支持 {spec["max_ref_videos"]} 个参考视频')
            files_data['ref_videos'] = []
            files_data['ref_video_paths'] = []
            for f in ref_vids:
                filepath, public_url = save_temp_file(f, suffix='.mp4')
                if not public_url:
                    raise ValueError('视频参考需要在 config.json 中配置 deployment.public_base_url')
                files_data['ref_videos'].append(public_url)
                files_data['ref_video_paths'].append(filepath)
        # 支持前端预上传的视频 URL
        ref_video_urls_raw = request.form.get('ref_video_urls')
        if ref_video_urls_raw:
            urls = json.loads(ref_video_urls_raw)
            if not isinstance(urls, list):
                raise ValueError('ref_video_urls 必须是数组')
            if any(not isinstance(url, str) or not url.strip() for url in urls):
                raise ValueError('ref_video_urls 包含无效地址')
            existing_count = len(files_data.get('ref_videos', []))
            if existing_count + len(urls) > spec['max_ref_videos']:
                raise ValueError(f'最多支持 {spec["max_ref_videos"]} 个参考视频')
            if urls:
                files_data.setdefault('ref_videos', []).extend(urls)
        ref_auds = request.files.getlist('ref_audios')
        if ref_auds:
            if len(ref_auds) > spec['max_ref_audios']:
                raise ValueError(f'最多支持 {spec["max_ref_audios"]} 个参考音频')
            files_data['ref_audios'] = [_reference_audio_data_url(f) for f in ref_auds]
    return files_data


def _persist_ark_video_references(task_id, output_dir, files_data):
    references = []
    if files_data.get('first_frame'):
        references.append(('input_image', 'first_frame.png', 'image/png', files_data['first_frame']))
    if files_data.get('last_frame'):
        references.append(('input_image', 'last_frame.png', 'image/png', files_data['last_frame']))
    references.extend(
        ('input_image', f'reference_image_{index}.png', 'image/png', data_url)
        for index, data_url in enumerate(files_data.get('ref_images', []), 1)
    )
    for index, data_url in enumerate(files_data.get('ref_audios', []), 1):
        mime_type = data_url.split(';', 1)[0].removeprefix('data:')
        extension = 'mp3' if mime_type == 'audio/mp3' else 'wav'
        references.append((
            'input_audio', f'reference_audio_{index}.{extension}', mime_type, data_url,
        ))

    for kind, filename, mime_type, data_url in references:
        path = os.path.join(output_dir, filename)
        storage.save_data_url(data_url, path)
        storage.register_file(task_id, kind, path, mime_type)

    for path in files_data.get('ref_video_paths', []):
        if os.path.isfile(path):
            storage.register_file(task_id, 'input_video', path, expires_at=None)


def _queue_cupsy_video(
    has_files, data, prompt, ratio, duration, resolution, fast, generate_audio,
    video_mode, requested_model,
):
    settings = _cupsy_settings()
    if not settings['api_key']:
        return jsonify({'success': False, 'error': 'Cupsy 未配置 API Key'}), 400
    requested_model = str(requested_model or settings.get('model') or SEEDANCE_25).strip().lower()
    if requested_model == 'dreamina-seedance-2.5':
        requested_model = SEEDANCE_25
    if requested_model not in CUPSY_SEEDANCE_MODELS:
        return jsonify({'success': False, 'error': 'Cupsy 端点仅支持 Seedance 2.5'}), 400
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'duration 必须是整数'}), 400
    if duration != -1 and (duration < 4 or duration > 30):
        return jsonify({'success': False, 'error': 'Cupsy Seedance 2.5 时长必须为 Auto 或 4 到 30 秒'}), 400
    if ratio not in {'adaptive', '16:9', '4:3', '1:1', '3:4', '9:16', '21:9'}:
        return jsonify({'success': False, 'error': f'不支持的视频比例: {ratio}'}), 400
    if resolution not in {'480p', '720p', '1080p'}:
        return jsonify({'success': False, 'error': 'Cupsy Seedance 2.5 仅支持 480p、720p 或 1080p'}), 400
    if video_mode not in {'keyframe', 'reference'}:
        return jsonify({'success': False, 'error': f'不支持的视频模式: {video_mode}'}), 400
    if fast:
        return jsonify({'success': False, 'error': 'Cupsy Seedance 2.5 不支持快速模式'}), 400

    task_type = request.form.get('omni_reference_task_type', 'auto') if has_files else data.get('omni_reference_task_type', 'auto')
    if task_type not in ('auto', 'reference', 'edit', 'extend'):
        return jsonify({'success': False, 'error': '不支持的任务类型'}), 400

    raw_existing = request.form.get('cupsy_assets') if has_files else data.get('cupsy_assets', [])
    if isinstance(raw_existing, str):
        try:
            raw_existing = json.loads(raw_existing)
        except ValueError:
            return jsonify({'success': False, 'error': 'cupsy_assets 必须是数组'}), 400
    if raw_existing is None:
        raw_existing = []
    if not isinstance(raw_existing, list):
        return jsonify({'success': False, 'error': 'cupsy_assets 必须是数组'}), 400

    pending_links = []
    position = 0
    allowed_roles = {
        'first_frame': 'image', 'last_frame': 'image', 'reference_image': 'image',
        'reference_video': 'video', 'reference_audio': 'audio',
    }
    for item in raw_existing:
        if not isinstance(item, dict):
            return jsonify({'success': False, 'error': 'Cupsy 素材引用无效'}), 400
        role = item.get('role')
        try:
            asset = task_db.get_provider_asset(item.get('id'))
        except (TypeError, ValueError):
            asset = None
        if (
            role not in allowed_roles or not asset or asset.get('deleted_at')
            or asset.get('provider') != profile_runtime.asset_provider() or asset.get('kind') != allowed_roles[role]
        ):
            return jsonify({'success': False, 'error': 'Cupsy 素材引用或角色无效'}), 400
        pending_links.append((asset, role, position))
        position += 1

    if video_mode == 'keyframe':
        roles = [link[1] for link in pending_links]
        if any(role not in ('first_frame', 'last_frame') for role in roles):
            return jsonify({'success': False, 'error': '首尾帧模式不接受参考素材角色'}), 400
        first_count = roles.count('first_frame') + (len(request.files.getlist('image')) if has_files else 0)
        last_count = roles.count('last_frame') + (len(request.files.getlist('last_image')) if has_files else 0)
        if (request.form.get('canvas_workflow_id') if has_files else data.get('canvas_workflow_id')) and not first_count:
            return jsonify({'success': False, 'error': '画布首尾帧模式必须提供首帧；无图片时请选择全能参考'}), 400
        if first_count > 1 or last_count > 1 or (last_count and not first_count):
            return jsonify({'success': False, 'error': '首尾帧各限一张，尾帧必须同时提供首帧'}), 400
        if has_files and any(request.files.getlist(key) for key in ('ref_images', 'ref_videos', 'ref_audios')):
            return jsonify({'success': False, 'error': '首尾帧模式不接受参考素材上传'}), 400
        if (request.form.get('ref_video_urls') if has_files else data.get('ref_video_urls')):
            return jsonify({'success': False, 'error': '首尾帧模式不接受视频参考'}), 400
    elif any(link[1] in ('first_frame', 'last_frame') for link in pending_links) or (has_files and (request.files.getlist('image') or request.files.getlist('last_image'))):
        return jsonify({'success': False, 'error': '全能参考模式不接受首尾帧角色'}), 400

    if has_files:
        upload_groups = []
        if video_mode == 'keyframe':
            images = request.files.getlist('image')
            last_images = request.files.getlist('last_image')
            if last_images and not images and not any(link[1] == 'first_frame' for link in pending_links):
                return jsonify({'success': False, 'error': '设置尾帧时必须同时提供首帧'}), 400
            upload_groups.extend((upload, 'image', 'first_frame') for upload in images[:1])
            upload_groups.extend((upload, 'image', 'last_frame') for upload in last_images[:1])
        else:
            upload_groups.extend((upload, 'image', 'reference_image') for upload in request.files.getlist('ref_images'))
            upload_groups.extend((upload, 'video', 'reference_video') for upload in request.files.getlist('ref_videos'))
            upload_groups.extend((upload, 'audio', 'reference_audio') for upload in request.files.getlist('ref_audios'))
        try:
            for upload, kind, role in upload_groups:
                asset = create_cupsy_asset_from_upload(upload, kind)
                pending_links.append((asset, role, position))
                position += 1
        except ValueError as error:
            return jsonify({'success': False, 'error': str(error)}), 400

    ref_video_urls = request.form.get('ref_video_urls') if has_files else data.get('ref_video_urls', [])
    if isinstance(ref_video_urls, str):
        try:
            ref_video_urls = json.loads(ref_video_urls)
        except ValueError:
            return jsonify({'success': False, 'error': 'ref_video_urls 必须是数组'}), 400
    for url in ref_video_urls or []:
        if not isinstance(url, str) or '/api/upload_video/' not in url:
            return jsonify({'success': False, 'error': 'Cupsy 参考视频必须是本项目上传的文件或 Assets 素材'}), 400
        filename = os.path.basename(url.rsplit('/api/upload_video/', 1)[-1])
        path = os.path.join(UPLOAD_VIDEO_DIR, filename)
        try:
            asset = create_cupsy_asset_from_path(path, 'video', filename)
            _cupsy_source_url(asset)
        except ValueError as error:
            return jsonify({'success': False, 'error': str(error)}), 400
        pending_links.append((asset, 'reference_video', position))
        position += 1

    role_counts = {}
    for _asset, role, _position in pending_links:
        role_counts[role] = role_counts.get(role, 0) + 1
    if role_counts.get('reference_image', 0) > 30 or role_counts.get('reference_video', 0) > 10 or role_counts.get('reference_audio', 0) > 10:
        return jsonify({'success': False, 'error': '参考素材数量超过 Cupsy Seedance 2.5 上限'}), 400
    if not prompt.strip() and not pending_links:
        return jsonify({'success': False, 'error': '请提供 prompt 或参考素材'}), 400

    params = {
        'model': requested_model,
        'ratio': ratio,
        'duration': duration,
        'resolution': resolution,
        'output_format': 'mp4',
        'fast': False,
        'generate_audio': bool(generate_audio),
        'return_last_frame': False,
        'video_mode': video_mode,
    }
    if video_mode == 'reference':
        params['omni_reference_task_type'] = task_type
    task_id = task_db.create_task('video', prompt, params, provider='cupsy', status='pending')
    output_dir = storage.task_output_dir('video', task_id)
    task_db.update_task(task_id, output_dir=output_dir)
    for asset, role, link_position in pending_links:
        task_db.link_task_provider_asset(task_id, asset['id'], role, link_position)
        task_db.link_asset(asset['local_path'], task_id, expires_at=None)
    # Estimate snapshot only (never an actual charge); best effort.
    cost_estimate.store_snapshot(task_id)
    return jsonify({
        'success': True, 'queued': True, 'db_task_id': task_id,
        'provider': 'cupsy', 'status': 'pending',
    }), 202


def _video_post_accept_message(external_id, error):
    return f'Provider已受理（编号{external_id}），本地记录失败：{error}；请到Provider核实，勿重复提交'


def _recover_video_post_accept(db_task_id, provider, external_id, request_info, error):
    """Provider accepted the video job but recording it locally failed.

    The external ID is logged first (the database itself may be unwritable). Then one
    activation retry keeps the job pollable so the result can still be fetched; if
    that also fails, the task is failed with result_unknown and the external ID kept.
    Returns the activation result (True/False) or None when the task could not be activated.
    """
    app.logger.error(
        'video_post_accept_error task_id=%s provider=%s external_task_id=%s error=%s',
        db_task_id, provider, external_id, error,
    )
    save_error_log(
        f'{provider}_video_post_accept_error', request_info,
        {'external_task_id': external_id}, str(error),
    )
    try:
        task_db.get_db().rollback()
    except Exception:
        pass
    try:
        activated = task_db.activate_video_task(db_task_id, external_id)
        app.logger.warning(
            'video_post_accept_recovered task_id=%s external_task_id=%s activated=%s',
            db_task_id, external_id, activated,
        )
        return activated
    except Exception as retry_error:
        app.logger.error(
            'video_post_accept_retry_failed task_id=%s external_task_id=%s error=%s',
            db_task_id, external_id, retry_error,
        )
    try:
        task_db.get_db().rollback()
    except Exception:
        pass
    try:
        task_db.update_task(db_task_id, external_task_id=external_id)
    except Exception:
        app.logger.error('video_post_accept_external_id_not_saved task_id=%s external_task_id=%s',
                         db_task_id, external_id)
    try:
        task_db.fail_task_merging_result(db_task_id, _video_post_accept_message(external_id, error), {
            'result_unknown': True, 'error_type': 'post_accept_error', 'external_task_id': external_id,
        })
    except Exception:
        app.logger.error('video_post_accept_result_not_saved task_id=%s external_task_id=%s',
                         db_task_id, external_id)
    return None


@app.route('/api/video/generate', methods=['POST'])
def video_generate():
    """提交视频生成任务，返回 task_id"""
    db_task_id = None
    try:
        has_files = bool(request.content_type and 'multipart' in request.content_type)
        data = {}

        if has_files:
            prompt = normalize_newlines(request.form.get('prompt', ''))
            ratio = request.form.get('ratio', 'adaptive')
            duration = request.form.get('duration', '5')
            duration_provided = 'duration' in request.form
            resolution = request.form.get('resolution', '720p')
            fast = request.form.get('fast', 'false').lower() == 'true'
            generate_audio = request.form.get('generate_audio', 'true').lower() == 'true'
            return_last_frame = request.form.get('return_last_frame', 'false').lower() == 'true'
            video_mode = request.form.get('video_mode', 'keyframe')
            requested_provider = request.form.get('provider')
            requested_model = request.form.get('model', SEEDANCE_20)
            output_format = request.form.get('output_format', 'mp4').lower()
        else:
            data = request.get_json(silent=True) or {}
            prompt = normalize_newlines(data.get('prompt', ''))
            ratio = data.get('ratio', 'adaptive')
            duration = data.get('duration', 5)
            duration_provided = 'duration' in data
            resolution = data.get('resolution', '720p')
            fast = as_bool(data.get('fast', False))
            generate_audio = as_bool(data.get('generate_audio', True), default=True)
            return_last_frame = as_bool(data.get('return_last_frame', False))
            video_mode = data.get('video_mode', 'keyframe')
            requested_provider = data.get('provider')
            requested_model = data.get('model', SEEDANCE_20)
            output_format = str(data.get('output_format', 'mp4')).lower()

        if has_files and video_mode == 'keyframe':
            first_count, last_count = len(request.files.getlist('image')), len(request.files.getlist('last_image'))
            if first_count > 1 or last_count > 1 or any(request.files.getlist(k) for k in ('ref_images', 'ref_videos', 'ref_audios')):
                return jsonify({'success': False, 'error': '首尾帧各限一张，不接受参考素材上传'}), 400
        elif has_files and video_mode == 'reference' and (request.files.getlist('image') or request.files.getlist('last_image')):
            return jsonify({'success': False, 'error': '全能参考模式不接受首尾帧上传'}), 400

        if video_mode == 'keyframe' and (request.form.get('ref_video_urls') if has_files else data.get('ref_video_urls')):
            return jsonify({'success': False, 'error': '首尾帧模式不接受视频参考'}), 400
        provider = requested_provider or 'ark'
        if provider not in {'ark', 'cupsy'}:
            return jsonify({'success': False, 'error': f'不支持的视频 provider: {provider}'}), 400
        if provider == 'cupsy':
            return _queue_cupsy_video(
                has_files, data, prompt, ratio, duration, resolution, fast,
                generate_audio, video_mode, requested_model,
            )
        prov = ARK_VIDEO_CONFIG
        try:
            model_key, model_id, model_spec = _resolve_video_model(requested_model, prov, fast)
        except ValueError as error:
            return jsonify({'success': False, 'error': str(error)}), 400
        if model_key == SEEDANCE_25 and not duration_provided:
            duration = -1
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'duration 必须是整数'}), 400
        if ratio not in {'adaptive', '16:9', '4:3', '1:1', '3:4', '9:16', '21:9'}:
            return jsonify({'success': False, 'error': f'不支持的视频比例: {ratio}'}), 400
        if video_mode not in {'keyframe', 'reference'}:
            return jsonify({'success': False, 'error': f'不支持的视频模式: {video_mode}'}), 400
        try:
            files_data = _parse_files(has_files, video_mode, model_spec)
            if video_mode == 'keyframe' and (request.form.get('canvas_workflow_id') if has_files else data.get('canvas_workflow_id')) and not files_data.get('first_frame'):
                return jsonify({'success': False, 'error': '画布首尾帧模式必须提供首帧；无图片时请选择全能参考'}), 400
        except ValueError as ve:
            return jsonify({'success': False, 'error': str(ve)}), 400

        # JSON body 中的预上传视频 URL
        if not has_files:
            ref_video_urls = data.get('ref_video_urls', [])
            if not isinstance(ref_video_urls, list):
                return jsonify({'success': False, 'error': 'ref_video_urls 必须是数组'}), 400
            if any(not isinstance(url, str) or not url.strip() for url in ref_video_urls):
                return jsonify({'success': False, 'error': 'ref_video_urls 包含无效地址'}), 400
            if ref_video_urls:
                files_data['ref_videos'] = ref_video_urls

        app.logger.warning(
            'Video generate [%s/%s]: ratio=%s, duration=%s, resolution=%s, fast=%s, '
            'audio=%s, return_last_frame=%s, mode=%s, output=%s',
            provider, model_key, ratio, duration, resolution, fast, generate_audio,
            return_last_frame, video_mode, output_format,
        )

        settings_error = _validate_video_settings(
            model_key, model_spec, ratio, duration, resolution, output_format,
            video_mode, fast, files_data,
        )
        if settings_error:
            return jsonify({'success': False, 'error': settings_error}), 400

        if not prompt and not files_data:
            return jsonify({'success': False, 'error': '请提供 prompt 或参考素材'}), 400

        api_key = prov.get('api_key', '')
        endpoint = prov.get('endpoint', '')
        if not api_key:
            return jsonify({'success': False, 'error': f'{provider} 未配置 API Key'}), 400

        body = _build_ark_body(
            prompt, ratio, duration, resolution, fast, generate_audio,
            return_last_frame, video_mode, files_data, prov,
            model_id=model_id, model_key=model_key, output_format=output_format,
        )
        url = f'{endpoint}/api/v3/contents/generations/tasks'
        request_body_bytes = len(
            json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        )
        if request_body_bytes > ARK_VIDEO_MAX_REQUEST_BYTES:
            return jsonify({'success': False, 'error': '提交给 Ark 的请求体不能超过 64 MB'}), 400

        params = {
            'model': model_key,
            'ratio': ratio,
            'duration': duration,
            'resolution': resolution,
            'output_format': output_format,
            'fast': fast,
            'generate_audio': generate_audio,
            'return_last_frame': return_last_frame,
            'video_mode': video_mode,
        }
        ref_video_paths = list(files_data.get('ref_video_paths', []))
        for ref_url in files_data.get('ref_videos', []):
            if isinstance(ref_url, str) and '/api/upload_video/' in ref_url:
                fname = ref_url.rsplit('/api/upload_video/', 1)[-1]
                fp = os.path.join(UPLOAD_VIDEO_DIR, os.path.basename(fname))
                if fp not in ref_video_paths and os.path.isfile(fp):
                    ref_video_paths.append(fp)
        if ref_video_paths:
            params['ref_video_paths'] = ref_video_paths
        if files_data.get('ref_videos'):
            params['ref_video_urls'] = files_data['ref_videos']

        db_task_id = task_db.create_task('video', prompt, params, provider=provider)
        output_dir = storage.task_output_dir('video', db_task_id)
        task_db.update_task(db_task_id, output_dir=output_dir)
        _persist_ark_video_references(db_task_id, output_dir, files_data)
        cost_estimate.store_snapshot(db_task_id)

        upload_timeout, request_timeout = resolve_ark_timeouts(prov)

        request_info = {
            'db_task_id': db_task_id,
            'provider': provider,
            'model': model_key,
            'request_body_bytes': request_body_bytes,
            'reference_images': len(files_data.get('ref_images', [])),
            'reference_videos': len(files_data.get('ref_videos', [])),
            'reference_audios': len(files_data.get('ref_audios', [])),
        }
        try:
            resp = HTTP.post(
                url,
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                json=body,
                timeout=(upload_timeout, request_timeout),
            )
        except requests.exceptions.ConnectTimeout as error:
            message = f'连接 {provider} API 超时，任务尚未提交，请重试'
            task_db.fail_task(db_task_id, message)
            save_error_log(f'{provider}_video_request_error', request_info, {}, str(error))
            return jsonify({
                'success': False,
                'error': message,
                'error_type': 'connect_timeout',
                'retryable': True,
                'result_unknown': False,
                'db_task_id': db_task_id,
            }), 503
        except requests.exceptions.ReadTimeout as error:
            message = f'{provider} 在 {request_timeout} 秒内未返回，任务结果未知；系统未自动重试'
            task_db.fail_task_result_unknown(db_task_id, message, 'upstream_timeout')
            save_error_log(f'{provider}_video_request_timeout', request_info, {}, str(error))
            return jsonify({
                'success': False,
                'error': message,
                'error_type': 'upstream_timeout',
                'retryable': False,
                'result_unknown': True,
                'error_details': {'timeout_seconds': request_timeout},
                'db_task_id': db_task_id,
            }), 504
        except requests.exceptions.RequestException as error:
            error_text = str(error)
            save_error_log(f'{provider}_video_request_error', request_info, {}, error_text)
            if 'write operation timed out' in error_text.lower():
                message = f'{provider} 请求体在 {upload_timeout} 秒内未上传完成，任务结果未知；系统未自动重试'
                task_db.fail_task_result_unknown(db_task_id, message, 'upload_timeout')
                return jsonify({
                    'success': False,
                    'error': message,
                    'error_type': 'upload_timeout',
                    'retryable': False,
                    'result_unknown': True,
                    'error_details': {'timeout_seconds': upload_timeout},
                    'db_task_id': db_task_id,
                }), 504
            if not _request_not_sent(error):
                message = f'{provider} 请求可能已发出、结果未知（{error_text}）；系统未自动重试，请先到Provider核实'
                task_db.fail_task_result_unknown(db_task_id, message, 'request_error_unknown')
                return jsonify({
                    'success': False,
                    'error': message,
                    'error_type': 'request_error_unknown',
                    'retryable': False,
                    'result_unknown': True,
                    'db_task_id': db_task_id,
                }), 502
            message = f'{provider} API 网络请求失败: {error_text}'
            task_db.fail_task(db_task_id, message)
            return jsonify({
                'success': False,
                'error': message,
                'error_type': 'request_error',
                'retryable': False,
                'db_task_id': db_task_id,
            }), 502
        except Exception as error:
            # Non-requests error raised inside the POST: whether bytes left cannot be proven.
            error_text = str(error)
            save_error_log(f'{provider}_video_request_error', request_info, {}, error_text)
            message = f'{provider} 请求可能已发出、结果未知（{error_text}）；系统未自动重试，请先到Provider核实'
            task_db.fail_task_result_unknown(db_task_id, message, 'request_error_unknown')
            return jsonify({
                'success': False,
                'error': message,
                'error_type': 'request_error_unknown',
                'retryable': False,
                'result_unknown': True,
                'db_task_id': db_task_id,
            }), 502
        try:
            resp_data = resp.json() if resp.text else {}
        except ValueError:
            resp_data = {}
        if not isinstance(resp_data, dict):
            resp_data = {}

        if resp.status_code != 200:
            err_obj = resp_data.get('error', {}) if isinstance(resp_data, dict) else {}
            err_msg = resp_data.get('message') or (err_obj.get('message') if isinstance(err_obj, dict) else '') or f'API 错误 {resp.status_code}'
            task_db.fail_task(db_task_id, err_msg)
            return jsonify({'success': False, 'error': err_msg, 'db_task_id': db_task_id}), resp.status_code

        external_id = resp_data.get('task_id') or resp_data.get('id')
        if not external_id:
            task_db.fail_task(db_task_id, '供应商未返回任务 ID')
            return jsonify({'success': False, 'error': '供应商未返回任务 ID', 'db_task_id': db_task_id}), 502

        try:
            activated = task_db.activate_video_task(db_task_id, external_id)
        except Exception as error:
            activated = _recover_video_post_accept(db_task_id, provider, external_id, request_info, error)
            if activated is None:
                return jsonify({
                    'success': False,
                    'error': _video_post_accept_message(external_id, error),
                    'error_type': 'post_accept_error',
                    'retryable': False,
                    'result_unknown': True,
                    'external_task_id': external_id,
                    'db_task_id': db_task_id,
                }), 502
        if not activated:
            task_db.finalize_task_cancel(db_task_id)
            return jsonify({
                'success': False,
                'cancelled': True,
                'error': '任务已取消，本地将不再轮询供应商任务',
                'db_task_id': db_task_id,
            }), 409

        return jsonify({'success': True, 'task_id': external_id, 'db_task_id': db_task_id, 'provider': provider})

    except Exception as e:
        if db_task_id is not None:
            task_db.fail_task(db_task_id, str(e))
        print(f'Error submitting video task: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# Ark status → 统一状态映射
ARK_STATUS_MAP = {
    'queued': 'TASK_STATUS_QUEUED',
    'running': 'TASK_STATUS_PROCESSING',
    'succeeded': 'TASK_STATUS_SUCCEED',
    'failed': 'TASK_STATUS_FAILED',
    'expired': 'TASK_STATUS_FAILED'
}


# ============================================================
# Task Management API
# ============================================================

WORKSPACE_STATE_KEYS = {
    'img_tabs', 'img_activeTab', 'appMode',
    'vid_tabs', 'vid_activeTab',
    'audio_form',
    'gallery_preferences',
    # Last interface chosen per canvas generation node type (image/video/audio).
    'canvas_provider_preferences',
}


@app.route('/api/tasks/<int:task_id>/cancel', methods=['POST'])
@profile_runtime.task_context
def api_cancel_task(task_id):
    task = task_db.get_task(task_id)
    if task and task.get('provider') == 'cupsy' and task.get('type') in {'audio', 'video'} and task.get('external_task_id'):
        settings = _cupsy_audio_settings() if task.get('type') == 'audio' else _cupsy_settings()
        resource_path = (
            f'/v1/audio/generations/{task["external_task_id"]}'
            if task.get('type') == 'audio'
            else f'/v1/videos/{task["external_task_id"]}'
        )
        if settings['api_key']:
            try:
                response = HTTP.delete(
                    f'{settings.get("endpoint", "https://cupsy.io").rstrip("/")}{resource_path}',
                    headers=_cupsy_headers(), timeout=(10, profile_runtime.setting('request_timeout_seconds', 30)),
                )
                if response.status_code not in {200, 202, 204, 404, 409}:
                    app.logger.warning(
                        'cupsy_video_cancel_failed task_id=%s status=%s', task_id, response.status_code
                    )
            except requests.RequestException:
                app.logger.warning('cupsy_video_cancel_request_failed task_id=%s', task_id)
    status = task_db.request_task_cancel(task_id)
    if status is None:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    return jsonify({'success': True, 'status': status, 'task': task_db.get_task(task_id)})


@app.route('/api/tasks/<int:task_id>/retry', methods=['POST'])
@profile_runtime.task_context
def api_retry_task(task_id):
    task = task_db.get_task(task_id)
    if not task:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    if task.get('deleted_at') is not None:
        return jsonify({'success': False, 'error': '请先从回收站恢复任务'}), 409
    if task['type'] != 'image':
        return jsonify({'success': False, 'error': '视频任务请复用参数后重新提交'}), 409
    if task['status'] not in ('failed', 'cancelled'):
        return jsonify({'success': False, 'error': '仅失败或已取消的任务可以重试'}), 409
    retry_provider = task.get('provider') or (task.get('params') or {}).get('provider')
    if retry_provider not in API_PROVIDERS:
        # Never clone an unsupported-provider task into a new pending row.
        return jsonify({
            'success': False, 'error': UNSUPPORTED_RETRY_ERROR, 'code': 'provider_unsupported',
        }), 400
    result = task.get('result')
    if isinstance(result, dict) and result.get('result_unknown'):
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict) or body.get('confirm_duplicate_billing') is not True:
            return jsonify({
                'success': False,
                'error': '该任务结果未知，请求可能已发出并已计费；请先到Provider核实，确认后再重试',
                'code': 'result_unknown_confirm_required',
            }), 409

    retry_params = dict(task.get('params') or {})
    retry_params.pop('_cupsy_request', None)
    retry_params.pop('_cupsy_idempotency_key', None)
    retry_id = task_db.create_task(
        'image', task.get('prompt') or '', retry_params,
        provider=task.get('provider'), status='preparing', retry_of=task_id,
    )
    output_dir, _ = storage.clone_image_inputs(task_id, retry_id)
    if task.get('provider') == 'cupsy':
        for index, asset in enumerate(task_db.list_assets(retry_id)):
            if asset['kind'] == 'input_image':
                imported = create_cupsy_asset_from_path(asset['path'], 'image')
                task_db.link_task_provider_asset(retry_id, imported['id'], 'reference_image', index)
    task_db.update_task(
        retry_id, output_dir=output_dir, status='pending', next_run_at=task_db.utcnow(),
    )
    if task.get('favorite'):
        task_db.set_task_favorite(retry_id, True)
        task_db.replace_task_favorite_groups(
            retry_id,
            [group['id'] for group in task.get('favorite_groups', [])],
        )
    return jsonify({'success': True, 'task_id': retry_id, 'task': task_db.get_task(retry_id)}), 202


@app.route('/api/images/inspect', methods=['POST'])
def api_inspect_image():
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'success': False, 'error': '缺少图片文件'}), 400
    try:
        metadata = storage.inspect_uploaded_image(upload)
        return jsonify({'success': True, 'image': metadata})
    except (OSError, ValueError, UnidentifiedImageError):
        return jsonify({'success': False, 'error': '图片格式无效或文件已损坏'}), 400


@app.route('/api/layer/projects', methods=['GET', 'POST'])
def api_layer_projects():
    if request.method == 'GET':
        return jsonify({'success': True, 'projects': task_db.list_layer_projects()})
    upload = request.files.get('image')
    if not upload or not upload.filename:
        return jsonify({'success': False, 'error': '请选择需要分解的 PNG 或 JPEG 图片'}), 400
    try:
        requested_size = 'auto' if request.form.get('size', 'auto').lower() == 'auto' else request.form.get('size', 'auto').upper()
        if requested_size not in {'auto', '1K', '1.5K', '2K'}:
            raise ValueError('图层分解分辨率仅支持 Auto、1K、1.5K 或 2K')
        provider, provider_config = get_layer_provider_config()
        if not get_provider_key(provider, provider_config):
            raise ValueError('Ark 未配置 API Key')
        layer_options.options(request.form, get_provider_default_model(provider, provider_config))
        upload.stream.seek(0, os.SEEK_END)
        size_bytes = upload.stream.tell()
        upload.stream.seek(0)
        metadata = storage.inspect_uploaded_image(upload)
        _validate_layer_source(metadata, size_bytes)
        name = (request.form.get('name') or os.path.splitext(upload.filename)[0] or '未命名项目').strip()[:120]
        project_id = task_db.create_layer_project(name, upload.filename, None, metadata)
        project_dir = os.path.join(storage.WORKSPACE_ASSET_DIR, 'layer_projects', str(project_id))
        source_path = os.path.join(project_dir, 'source.png')
        storage.save_uploaded_image(upload, source_path)
        stored_metadata = storage.inspect_image(source_path)
        stored_metadata['original_format'] = metadata['format']
        stored_metadata['size_bytes'] = size_bytes
        task_db.update_layer_project(project_id, source_path=source_path, source_metadata=stored_metadata)
        project = task_db.get_layer_project(project_id)
        task_id = _queue_layer_task(project, normalize_newlines(request.form.get('prompt', '')), requested_size, request.form)
        return jsonify({
            'success': True, 'project_id': project_id, 'task_id': task_id,
            'project': task_db.get_layer_project(project_id),
        }), 202
    except (OSError, ValueError, UnidentifiedImageError) as error:
        return jsonify({'success': False, 'error': str(error)}), 400


@app.route('/api/layer/projects/<int:project_id>', methods=['GET', 'PUT', 'DELETE'])
def api_layer_project(project_id):
    project = task_db.get_layer_project(project_id)
    if not project:
        return jsonify({'success': False, 'error': '图层项目不存在'}), 404
    if request.method == 'GET':
        return jsonify({'success': True, 'project': project})
    if request.method == 'DELETE':
        current = project.get('current_task') or {}
        if current.get('status') in task_db.ACTIVE_TASK_STATUSES:
            return jsonify({'success': False, 'error': '项目仍在分解中，请等待任务结束后删除'}), 409
        task_ids = {revision['task_id'] for revision in project.get('revisions', [])}
        if project.get('current_task_id'):
            task_ids.add(project['current_task_id'])
        task_db.update_layer_project(project_id, deleted_at=task_db.utcnow())
        for task_id in task_ids:
            task = task_db.get_task(task_id)
            if task:
                storage.remove_task_files(task)
                task_db.delete_task(task_id)
        source_dir = os.path.dirname(project.get('source_path') or '')
        expected_root = os.path.abspath(os.path.join(storage.WORKSPACE_ASSET_DIR, 'layer_projects'))
        if source_dir and os.path.commonpath([expected_root, os.path.abspath(source_dir)]) == expected_root:
            shutil.rmtree(source_dir, ignore_errors=True)
        return jsonify({'success': True})
    data = request.get_json(silent=True) or {}
    document = data.get('document')
    if not isinstance(document, dict) or not isinstance(document.get('layers', []), list):
        return jsonify({'success': False, 'error': '图层文档格式无效'}), 400
    if len(document['layers']) > 100 or len(json.dumps(document).encode()) > 16 * 1024 * 1024:
        return jsonify(success=False, error='图层文档最多100层、16MB元数据'), 400
    updated = task_db.save_layer_document(project_id, document, data.get('revision'))
    if not updated:
        return jsonify({'success': False, 'error': '项目已在其他页面更新，请刷新后重试'}), 409
    return jsonify({'success': True, 'project': updated})


@app.route('/api/layer/projects/<int:project_id>/source', methods=['GET'])
def api_layer_project_source(project_id):
    project = task_db.get_layer_project(project_id)
    if not project or not project.get('source_path') or not os.path.isfile(project['source_path']):
        return jsonify({'success': False, 'error': '源图片不存在'}), 404
    return send_file(project['source_path'], conditional=True, max_age=3600)


@app.route('/api/layer/projects/<int:project_id>/decompose', methods=['POST'])
def api_decompose_layer_project(project_id):
    project = task_db.get_layer_project(project_id)
    if not project:
        return jsonify({'success': False, 'error': '图层项目不存在'}), 404
    current = project.get('current_task') or {}
    if current.get('status') in task_db.ACTIVE_TASK_STATUSES:
        return jsonify({'success': False, 'error': '当前项目已有分解任务正在执行'}), 409
    data = request.get_json(silent=True) or {}
    try:
        task_id = _queue_layer_task(project, normalize_newlines(data.get('prompt', '')), data.get('size', 'auto'), data)
        return jsonify({'success': True, 'task_id': task_id, 'project_id': project_id}), 202
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400


@app.route('/api/layer/projects/<int:project_id>/revisions/<int:revision_id>/restore', methods=['POST'])
def api_restore_layer_revision(project_id, revision_id):
    project = task_db.get_layer_project(project_id)
    if not project:
        return jsonify({'success': False, 'error': '图层项目不存在'}), 404
    revision = next((item for item in project.get('revisions', []) if item['id'] == revision_id), None)
    if not revision or not revision.get('document'):
        return jsonify({'success': False, 'error': '图层版本不存在或无法恢复'}), 404
    updated = task_db.save_layer_document(project_id, revision['document'])
    return jsonify({'success': True, 'project': updated})


@app.route('/api/layer/projects/<int:project_id>/layers.zip', methods=['GET'])
def api_download_layer_project(project_id):
    project = task_db.get_layer_project(project_id)
    document = (project or {}).get('document') or {}
    layers = document.get('layers') or []
    if not project or not layers:
        return jsonify({'success': False, 'error': '项目还没有可下载的图层'}), 404
    archive = tempfile.SpooledTemporaryFile(max_size=16*1024*1024)
    manifest = {'project': project['name'], 'canvas': document.get('canvas'), 'layers': []}
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for index, layer in enumerate(layers):
            local_url = layer.get('local_url') or ''
            match = re.match(r'^/api/tasks/(\d+)/file/([^/]+)$', local_url)
            task = task_db.get_task(int(match.group(1))) if match else None
            path = os.path.join(task['output_dir'], match.group(2)) if task and task.get('output_dir') else None
            if not path or not os.path.isfile(path):
                continue
            extension = os.path.splitext(path)[1].lower() or '.png'
            archive_name = f'{index:02d}_{re.sub(r"[^a-zA-Z0-9_-]+", "_", layer.get("name") or "layer")}{extension}'
            bundle.write(path, archive_name)
            manifest['layers'].append({**{key: value for key, value in layer.items() if key not in {'local_url', 'thumbnail_url'}}, 'file': archive_name})
        bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    archive.seek(0)
    return send_file(
        archive, mimetype='application/zip', as_attachment=True,
        download_name=f'ink-traces-layer-project-{project_id}.zip', max_age=0,
    )


def _canvas_provider_preferences_error(value):
    """Shape-only check: a remembered profile may later be disabled; the canvas falls back."""
    from canvas_project_settings import ADAPTERS, validate_node_selection
    from canvas_store import CanvasError
    if not isinstance(value, dict) or set(value) - set(ADAPTERS):
        return '接口偏好须为图像/视频/音频对象'
    try:
        for kind, selection in value.items():
            validate_node_selection(kind, selection)
    except CanvasError as error:
        return str(error)
    return None


@app.route('/api/workspace/state/<key>', methods=['GET'])
def api_get_workspace_state(key):
    if key not in WORKSPACE_STATE_KEYS:
        return jsonify({'success': False, 'error': '未知工作区状态键'}), 404
    state = task_db.get_workspace_state(key)
    return jsonify({'success': True, 'state': state})


@app.route('/api/workspace/state/<key>', methods=['PUT'])
def api_set_workspace_state(key):
    if key not in WORKSPACE_STATE_KEYS:
        return jsonify({'success': False, 'error': '未知工作区状态键'}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or 'value' not in data:
        return jsonify({'success': False, 'error': '缺少工作区状态 value'}), 400
    if key == 'canvas_provider_preferences':
        error = _canvas_provider_preferences_error(data['value'])
        if error:
            return jsonify({'success': False, 'error': error}), 400
    normalized = storage.persist_workspace_value(key, data['value'])
    state = task_db.set_workspace_state(key, normalized)
    # Preserve the request's field order so pre-fix clients do not mistake a
    # semantically identical, reordered response for another local change.
    state['value'] = normalized
    return jsonify({'success': True, 'state': state})


@app.route('/api/workspace/assets/<key>', methods=['POST'])
def api_upload_workspace_asset(key):
    if key not in WORKSPACE_STATE_KEYS:
        return jsonify({'success': False, 'error': '未知工作区状态键'}), 404
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'success': False, 'error': '缺少工作区素材文件'}), 400
    try:
        from local_uploads import capture_user_upload
        with capture_user_upload(upload):
            asset = storage.persist_workspace_upload(key, upload, normalize_image=key == 'img_tabs')
        return jsonify({'success': True, 'asset': asset}), 201
    except (OSError, ValueError) as error:
        from local_uploads import UploadRegistrationError
        if isinstance(error, UploadRegistrationError):
            return jsonify(success=False,error=str(error)),500
        return jsonify({'success': False, 'error': '工作区图片格式无效或文件已损坏'}), 400
    finally:
        storage.release_process_memory()


@app.route('/api/workspace/assets/<key>/<path:filename>', methods=['GET'])
def api_workspace_asset(key, filename):
    if key not in WORKSPACE_STATE_KEYS:
        return jsonify({'success': False, 'error': '未知工作区状态键'}), 404
    directory = os.path.join(storage.WORKSPACE_ASSET_DIR, key)
    return send_from_directory(directory, filename, max_age=3600)


@app.route('/api/png-info', methods=['POST'])
def api_png_info():
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'success': False, 'error': '请选择 PNG 文件'}), 400
    try:
        upload.stream.seek(0, os.SEEK_END)
        size_bytes = upload.stream.tell()
        upload.stream.seek(0)
        with Image.open(upload.stream) as image:
            if image.format != 'PNG':
                return jsonify({'success': False, 'error': '文件不是有效的 PNG'}), 400
            width, height = image.size
            entries = dict(getattr(image, 'text', {}) or {})
        parsed = png_metadata.parse_text_entries(entries)
        return jsonify({
            'success': True,
            'image': {
                'name': upload.filename,
                'width': width,
                'height': height,
                'size_bytes': size_bytes,
            },
            'metadata': parsed,
        })
    except (UnidentifiedImageError, OSError, ValueError):
        return jsonify({'success': False, 'error': 'PNG 文件已损坏或无法解析'}), 400


@app.route('/api/upload_video', methods=['POST'])
def api_upload_video():
    """上传视频参考文件，返回公网可访问 URL"""
    f = request.files.get('file')
    if not f:
        return jsonify({'success': False, 'error': '未提供文件'}), 400
    try:
        from local_uploads import capture_user_upload
        with capture_user_upload(f):
            filepath, public_url = save_temp_file(f, suffix='.mp4')
            if not public_url:
                raise ValueError('未配置 deployment.public_base_url，无法生成公网 URL')
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    if not public_url:
        return jsonify({'success': False, 'error': '未配置 deployment.public_base_url，无法生成公网 URL'}), 500
    return jsonify({'success': True, 'url': public_url, 'filepath': filepath})


@app.route('/api/upload_video', methods=['DELETE'])
def api_delete_upload_video():
    """删除已上传的参考视频文件。支持通过 url 或 filename 定位。"""
    data = request.get_json(silent=True) or {}
    url = data.get('url', '')
    filename = data.get('filename', '')
    if url and '/api/upload_video/' in url:
        filename = url.rsplit('/api/upload_video/', 1)[-1]
    if not filename:
        return jsonify({'success': False, 'error': '缺少 url 或 filename'}), 400
    # 防止路径穿越
    safe_name = os.path.basename(filename)
    filepath = os.path.join(UPLOAD_VIDEO_DIR, safe_name)
    if os.path.isfile(filepath):
        try:
            os.remove(filepath)
            task_db.delete_asset(filepath)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': False, 'error': '文件不存在'}), 404


@app.route('/api/upload_video/<path:filename>', methods=['GET'])
def api_upload_video_file(filename):
    """提供上传视频文件（供 Ark 等外部服务下载视频参考素材）"""
    safe_name = os.path.basename(filename)
    filepath = os.path.join(UPLOAD_VIDEO_DIR, safe_name)
    if not os.path.isfile(filepath):
        return jsonify({'success': False, 'error': '文件不存在'}), 404
    return send_file(filepath)


# ============================================================
# Worker-facing video polling
# ============================================================

def _cupsy_video_content(task, assets):
    content = []
    if task.get('prompt'):
        content.append({'type': 'text', 'text': task['prompt']})
    type_for_role = {
        'first_frame': 'image_url', 'last_frame': 'image_url',
        'reference_image': 'image_url', 'reference_video': 'video_url',
        'reference_audio': 'audio_url',
    }
    field_for_type = {
        'image_url': 'image_url', 'video_url': 'video_url', 'audio_url': 'audio_url',
    }
    for asset in assets:
        content_type = type_for_role[asset['role']]
        content.append({
            'type': content_type,
            field_for_type[content_type]: {'url': asset['asset_uri']},
            'role': asset['role'],
        })
    return content


def _cupsy_output_source(payload, endpoint, output_kind, fallback_path):
    """Resolve a completed Cupsy output, preferring its direct artifact route."""
    artifacts = [item for item in (payload.get('artifacts') or []) if isinstance(item, dict)]
    artifact = next((
        item for item in artifacts
        if item.get('id') and (
            str(item.get('kind') or '').lower() == output_kind
            or str(item.get('mime_type') or '').lower().startswith(f'{output_kind}/')
        )
    ), None)
    if artifact is None and len(artifacts) == 1 and artifacts[0].get('id'):
        artifact = artifacts[0]
    if artifact:
        size_bytes = artifact.get('size_bytes') or artifact.get('size')
        try:
            expected_size = int(size_bytes) if size_bytes is not None else None
        except (TypeError, ValueError):
            expected_size = None
        if expected_size is not None and expected_size <= 0:
            expected_size = None
        artifact_id = quote(str(artifact['id']), safe='')
        return f'{endpoint}/v1/artifacts/{artifact_id}/content', expected_size, True

    content_url = str(payload.get('content_url') or '').strip()
    if content_url:
        resolved_url = urljoin(f'{endpoint}/', content_url)
        endpoint_origin = urlsplit(endpoint)[:2]
        content_origin = urlsplit(resolved_url)[:2]
        return resolved_url, None, endpoint_origin == content_origin
    return f'{endpoint}/{fallback_path.lstrip("/")}', None, True


def _download_cupsy_output(payload, endpoint, output_kind, fallback_path, path):
    url, expected_size, authenticated = _cupsy_output_source(
        payload, endpoint, output_kind, fallback_path,
    )
    try:
        with HTTP.get(
            url, headers=_cupsy_headers() if authenticated else {},
            timeout=(10, profile_runtime.setting('download_timeout_seconds', DOWNLOAD_TIMEOUT)), stream=True,
        ) as download:
            if download.status_code >= 400:
                return f'Cupsy {output_kind} download failed {download.status_code}'
            storage.stream_response_to_file(download, path)
    except requests.RequestException as error:
        return str(error)

    if expected_size is not None:
        try:
            actual_size = os.path.getsize(path)
        except OSError as error:
            return str(error)
        if actual_size != expected_size:
            try:
                os.remove(path)
            except OSError:
                pass
            return f'Cupsy {output_kind} download incomplete: {actual_size}/{expected_size} bytes'
    return None


def _poll_cupsy_video_task(task):
    task_id = task['id']
    settings = _cupsy_settings()
    if not settings['api_key']:
        reason = 'Cupsy 未配置 API Key'
        task_db.fail_task(task_id, reason)
        return {'state': 'failed', 'error': reason}
    endpoint = settings.get('endpoint', 'https://cupsy.io').rstrip('/')
    params = task.get('params') or {}
    external_id = task.get('external_task_id')

    if not external_id:
        assets = task_db.list_task_provider_assets(task_id)
        failed = next((asset for asset in assets if asset['status'] == 'failed'), None)
        if failed:
            reason = f'参考素材导入失败: {failed.get("error") or failed.get("original_name")}'
            task_db.fail_task(task_id, reason)
            return {'state': 'failed', 'error': reason}
        if any(asset['status'] != 'active' or not asset.get('asset_uri') for asset in assets):
            return {'state': 'preparing', 'progress': 0}
        cupsy_model = str(params.get('model') or settings.get('model') or SEEDANCE_25).strip().lower()
        if cupsy_model not in CUPSY_SEEDANCE_MODELS:
            cupsy_model = SEEDANCE_25
        body = {
            'model': cupsy_model,
            'content': _cupsy_video_content(task, assets),
            'ratio': params.get('ratio', 'adaptive'),
            'duration': int(params.get('duration', 5)),
            'resolution': params.get('resolution', '720p'),
            'generate_audio': bool(params.get('generate_audio', True)),
            'watermark': False,
        }
        if 'omni_reference_task_type' in params:
            body['omni_reference_task_type'] = params['omni_reference_task_type']
        try:
            response = HTTP.post(
                f'{endpoint}/v1/videos',
                headers=_cupsy_headers(f'nanobanana-video-{task_id}'),
                json=body, timeout=(profile_runtime.setting('upload_timeout_seconds', 10), profile_runtime.setting('request_timeout_seconds', 120)),
            )
        except requests.RequestException as error:
            return {'state': 'retry', 'error': str(error)}
        if response.status_code not in {200, 201, 202}:
            reason = _cupsy_error(response, f'Cupsy 视频提交失败 {response.status_code}')
            if response.status_code == 429 or response.status_code >= 500:
                return {'state': 'retry', 'error': reason}
            task_db.fail_task(task_id, reason)
            return {'state': 'failed', 'error': reason}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        external_id = payload.get('id') or payload.get('video_id') or payload.get('task_id')
        if not external_id:
            return {'state': 'retry', 'error': 'Cupsy 未返回视频任务 ID'}
        if not task_db.activate_video_task(task_id, external_id):
            task_db.finalize_task_cancel(task_id)
            return {'state': 'cancelled'}
        return {'state': 'pending', 'progress': 0}

    try:
        response = HTTP.get(
            f'{endpoint}/v1/videos/{external_id}', headers=_cupsy_headers(), timeout=(10, profile_runtime.setting('poll_timeout_seconds', POLL_TIMEOUT))
        )
    except requests.RequestException as error:
        return {'state': 'retry', 'error': str(error)}
    if response.status_code >= 400:
        reason = _cupsy_error(response, f'Cupsy 视频查询失败 {response.status_code}')
        if response.status_code == 429 or response.status_code >= 500:
            return {'state': 'retry', 'error': reason}
        task_db.fail_task(task_id, reason)
        return {'state': 'failed', 'error': reason}
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    status = str(payload.get('status') or '').lower()
    if status in {'failed', 'error', 'expired', 'cancelled', 'canceled'}:
        reason = payload.get('message') or payload.get('error') or f'Cupsy 视频状态: {status}'
        if isinstance(reason, dict):
            reason = reason.get('message') or json.dumps(reason, ensure_ascii=False)
        task_db.fail_task(task_id, str(reason))
        return {'state': 'failed', 'error': str(reason)}
    if status not in {'succeeded', 'completed', 'ready'}:
        progress = payload.get('progress')
        return {'state': 'pending', 'progress': int(progress) if isinstance(progress, (int, float)) else 0}

    output_dir = task.get('output_dir') or storage.task_output_dir('video', task_id)
    filename = 'video.mp4'
    path = os.path.join(output_dir, filename)
    download_error = _download_cupsy_output(
        payload, endpoint, 'video', f'/v1/videos/{external_id}/content', path,
    )
    if download_error:
        return {'state': 'retry', 'error': download_error}
    storage.register_file(task_id, 'output_video', path, 'video/mp4')
    result = {
        'videos': [],
        'images': [],
        'local_videos': [f'/api/tasks/{task_id}/file/{filename}'],
        'local_images': [],
        'local_thumbnails': [],
        'local_video': f'/api/tasks/{task_id}/file/{filename}',
        'provider_video_id': external_id,
        'artifacts': payload.get('artifacts') or [],
    }
    if not task_db.complete_task(task_id, result, output_dir):
        storage.remove_task_output_files(task_id)
        task_db.finalize_task_cancel(task_id)
        return {'state': 'cancelled'}
    return {'state': 'succeeded', 'result': result}

def _poll_cupsy_audio_task(task):
    task_id = task['id']
    settings = _cupsy_audio_settings()
    if not settings['api_key']:
        reason = 'Cupsy 未配置 API Key'
        task_db.fail_task(task_id, reason)
        return {'state': 'failed', 'error': reason}

    endpoint = settings.get('endpoint', 'https://cupsy.io').rstrip('/')
    params = task.get('params') or {}
    external_id = task.get('external_task_id')
    if not external_id:
        assets = task_db.list_task_provider_assets(task_id)
        failed = next((asset for asset in assets if asset['status'] == 'failed'), None)
        if failed:
            reason = f'参考素材导入失败: {failed.get("error") or failed.get("original_name")}'
            task_db.fail_task(task_id, reason)
            return {'state': 'failed', 'error': reason}
        if any(asset['status'] != 'active' or not asset.get('asset_uri') for asset in assets):
            return {'state': 'preparing', 'progress': 0}

        references = []
        speaker = params.get('speaker')
        if speaker:
            references.append({'speaker': speaker})
        for asset in assets:
            if asset['role'] == 'reference_image':
                references.append({'image_url': asset['asset_uri']})
            elif asset['role'] == 'reference_audio':
                references.append({'audio_url': asset['asset_uri']})

        body = {
            'model': CUPSY_AUDIO_MODEL,
            'text_prompt': task.get('prompt') or '',
            'audio_config': {
                'format': params.get('output_format', 'mp3'),
                'sample_rate': int(params.get('sample_rate', 44100)),
                'enable_subtitle': bool(params.get('enable_subtitle', True)),
            },
            'watermark': bool(params.get('watermark', False)),
        }
        if references:
            body['references'] = references
        try:
            response = HTTP.post(
                f'{endpoint}/v1/audio/generations',
                headers=_cupsy_headers(f'nanobanana-audio-{task_id}'),
                json=body, timeout=(profile_runtime.setting('upload_timeout_seconds', 10), profile_runtime.setting('request_timeout_seconds', 120)),
            )
        except requests.RequestException as error:
            return {'state': 'retry', 'error': str(error)}
        if response.status_code not in {200, 201, 202}:
            reason = _cupsy_error(response, f'Cupsy 音频提交失败 {response.status_code}')
            if response.status_code == 429 or response.status_code >= 500:
                return {'state': 'retry', 'error': reason}
            task_db.fail_task(task_id, reason)
            return {'state': 'failed', 'error': reason}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        external_id = payload.get('id') or payload.get('audio_id') or payload.get('task_id')
        if not external_id:
            return {'state': 'retry', 'error': 'Cupsy 未返回音频任务 ID'}
        if not task_db.activate_video_task(task_id, external_id):
            task_db.finalize_task_cancel(task_id)
            return {'state': 'cancelled'}
        return {'state': 'pending', 'progress': 0}

    try:
        response = HTTP.get(
            f'{endpoint}/v1/audio/generations/{external_id}',
            headers=_cupsy_headers(), timeout=(10, profile_runtime.setting('poll_timeout_seconds', POLL_TIMEOUT)),
        )
    except requests.RequestException as error:
        return {'state': 'retry', 'error': str(error)}
    if response.status_code >= 400:
        reason = _cupsy_error(response, f'Cupsy 音频查询失败 {response.status_code}')
        if response.status_code == 429 or response.status_code >= 500:
            return {'state': 'retry', 'error': reason}
        task_db.fail_task(task_id, reason)
        return {'state': 'failed', 'error': reason}
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    status = str(payload.get('status') or '').lower()
    if status in {'failed', 'error', 'expired', 'cancelled', 'canceled'}:
        reason = payload.get('message') or payload.get('error') or f'Cupsy 音频状态: {status}'
        if isinstance(reason, dict):
            reason = reason.get('message') or json.dumps(reason, ensure_ascii=False)
        task_db.fail_task(task_id, str(reason))
        return {'state': 'failed', 'error': str(reason)}
    if status not in {'succeeded', 'completed', 'ready'}:
        progress = payload.get('progress')
        return {'state': 'pending', 'progress': int(progress) if isinstance(progress, (int, float)) else 0}

    output_format = str(params.get('output_format') or 'mp3').lower()
    if output_format not in CUPSY_AUDIO_FORMATS:
        output_format = 'mp3'
    filename = f'audio.{"ogg" if output_format == "ogg_opus" else output_format}'
    output_dir = task.get('output_dir') or storage.task_output_dir('audio', task_id)
    path = os.path.join(output_dir, filename)
    download_error = _download_cupsy_output(
        payload, endpoint, 'audio',
        f'/v1/audio/generations/{external_id}/content', path,
    )
    if download_error:
        return {'state': 'retry', 'error': download_error}
    storage.register_file(task_id, 'output_audio', path, CUPSY_AUDIO_FORMATS[output_format])
    result = {
        'local_audio': f'/api/tasks/{task_id}/file/{filename}',
        'provider_audio_id': external_id,
        'duration_seconds': payload.get('duration_seconds') or payload.get('duration'),
        'subtitles': payload.get('subtitles'),
        'artifacts': payload.get('artifacts') or [],
    }
    if not task_db.complete_task(task_id, result, output_dir):
        storage.remove_task_output_files(task_id)
        task_db.finalize_task_cancel(task_id)
        return {'state': 'cancelled'}
    return {'state': 'succeeded', 'result': result}


@profile_runtime.task_context
def poll_audio_task_once(task_id):
    task = task_db.get_task(task_id)
    if not task:
        return {'state': 'failed', 'error': '任务不存在'}
    if task_db.cancellation_requested(task_id):
        task_db.finalize_task_cancel(task_id)
        return {'state': 'cancelled'}
    if task.get('provider') != 'cupsy':
        reason = f'不支持的音频 Provider: {task.get("provider")}'
        task_db.fail_task(task_id, reason)
        return {'state': 'failed', 'error': reason}
    return _poll_cupsy_audio_task(task)


@profile_runtime.task_context
def poll_video_task_once(task_id):
    """Poll one provider task once and persist terminal results."""
    task = task_db.get_task(task_id)
    if not task:
        return {'state': 'failed', 'error': '任务不存在'}
    if task_db.cancellation_requested(task_id):
        task_db.finalize_task_cancel(task_id)
        return {'state': 'cancelled'}

    external_task_id = task.get('external_task_id')
    provider = task.get('provider') or 'ark'
    if provider == 'cupsy':
        return _poll_cupsy_video_task(task)
    if provider != 'ark':
        reason = f'已停止支持视频 Provider: {provider}'
        task_db.fail_task(task_id, reason)
        return {'state': 'failed', 'error': reason}
    task_params = task.get('params') or {}
    output_format = task_params.get('output_format', 'mp4')
    if output_format not in {'mp4', 'mov'}:
        output_format = 'mp4'
    prov = ARK_VIDEO_CONFIG
    api_key = prov.get('api_key', '')
    endpoint = prov.get('endpoint', '')

    try:
        response = HTTP.get(
            f'{endpoint}/api/v3/contents/generations/tasks/{external_task_id}',
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=(10, profile_runtime.setting('poll_timeout_seconds', POLL_TIMEOUT)),
        )
    except requests.RequestException as e:
        return {'state': 'retry', 'error': str(e)}

    try:
        response_data = response.json() if response.text else {}
    except ValueError:
        response_data = {}
    if not isinstance(response_data, dict):
        response_data = {}

    if task_db.cancellation_requested(task_id):
        task_db.finalize_task_cancel(task_id)
        return {'state': 'cancelled'}

    if response.status_code >= 400:
        error_obj = response_data.get('error', {})
        reason = (
            response_data.get('message')
            or (error_obj.get('message') if isinstance(error_obj, dict) else '')
            or f'查询失败 {response.status_code}'
        )
        if response.status_code == 429 or response.status_code >= 500:
            return {'state': 'retry', 'error': reason}
        task_db.fail_task(task_id, reason)
        return {'state': 'failed', 'error': reason}

    mapped_status = ARK_STATUS_MAP.get(response_data.get('status', ''), response_data.get('status', ''))
    content = response_data.get('content') or {}
    videos = [{'video_url': content['video_url'], 'video_type': output_format}] if content.get('video_url') else []
    images = [{'image_url': content['last_frame_url']}] if content.get('last_frame_url') else []
    error_obj = response_data.get('error', {})
    reason = error_obj.get('message', '') if isinstance(error_obj, dict) else str(error_obj or '')
    progress = 0

    if mapped_status == 'TASK_STATUS_FAILED':
        task_db.fail_task(task_id, reason or '视频生成失败')
        return {'state': 'failed', 'error': reason or '视频生成失败'}

    if mapped_status != 'TASK_STATUS_SUCCEED':
        return {'state': 'pending', 'progress': progress}

    output_dir = task.get('output_dir') or storage.task_output_dir('video', task_id)
    result = {
        'videos': videos,
        'images': images,
        'local_videos': [],
        'local_images': [],
        'local_thumbnails': [],
    }
    try:
        for index, video in enumerate(videos):
            if task_db.cancellation_requested(task_id):
                storage.remove_task_output_files(task_id)
                task_db.finalize_task_cancel(task_id)
                return {'state': 'cancelled'}
            url = video.get('video_url')
            if not url:
                continue
            video_format = str(video.get('video_type') or output_format).lower()
            if video_format not in {'mp4', 'mov'}:
                video_format = 'mp4'
            filename = f'video.{video_format}' if index == 0 else f'video_{index}.{video_format}'
            mime_type = 'video/quicktime' if video_format == 'mov' else 'video/mp4'
            path = os.path.join(output_dir, filename)
            with HTTP.get(url, timeout=(10, profile_runtime.setting('download_timeout_seconds', DOWNLOAD_TIMEOUT)), stream=True) as download:
                if download.status_code >= 400:
                    return {'state': 'retry', 'error': f'视频下载失败 {download.status_code}'}
                storage.stream_response_to_file(download, path)
            storage.register_file(task_id, 'output_video', path, mime_type)
            result['local_videos'].append(f'/api/tasks/{task_id}/file/{filename}')

        for index, image in enumerate(images):
            if task_db.cancellation_requested(task_id):
                storage.remove_task_output_files(task_id)
                task_db.finalize_task_cancel(task_id)
                return {'state': 'cancelled'}
            url = image.get('image_url')
            if not url:
                continue
            filename = 'last_frame.png' if index == 0 else f'last_frame_{index}.png'
            path = os.path.join(output_dir, filename)
            with HTTP.get(url, timeout=(10, profile_runtime.setting('download_timeout_seconds', DOWNLOAD_TIMEOUT)), stream=True) as download:
                if download.status_code >= 400:
                    return {'state': 'retry', 'error': f'尾帧下载失败 {download.status_code}'}
                storage.stream_response_to_file(download, path)
            storage.register_file(task_id, 'output_image', path, 'image/png')
            result['local_images'].append(f'/api/tasks/{task_id}/file/{filename}')
            thumbnail_name = 'thumbnail.webp' if index == 0 else f'thumbnail_{index}.webp'
            thumbnail_path = os.path.join(output_dir, thumbnail_name)
            try:
                storage.create_image_thumbnail(path, thumbnail_path)
                storage.register_file(task_id, 'output_thumbnail', thumbnail_path, 'image/webp')
                result['local_thumbnails'].append(f'/api/tasks/{task_id}/file/{thumbnail_name}')
            except (OSError, ValueError):
                app.logger.warning('thumbnail_generation_failed task_id=%s file=%s', task_id, filename)
    except requests.RequestException as e:
        return {'state': 'retry', 'error': str(e)}

    if result['local_videos']:
        result['local_video'] = result['local_videos'][0]
    if result['local_images']:
        result['local_last_frame'] = result['local_images'][0]
    if result['local_thumbnails']:
        result['local_thumbnail'] = result['local_thumbnails'][0]
    if not task_db.complete_task(task_id, result, output_dir):
        storage.remove_task_output_files(task_id)
        task_db.finalize_task_cancel(task_id)
        return {'state': 'cancelled'}
    return {'state': 'succeeded', 'result': result}


@app.route('/', defaults={'client_path': ''}, methods=['GET', 'HEAD'])
@app.route('/<path:client_path>', methods=['GET', 'HEAD'])
def serve_client_application(client_path):
    """Serve the production SPA without a resident Vite process."""
    if client_path == 'api' or client_path.startswith('api/'):
        return jsonify({'success': False, 'error': '接口不存在'}), 404
    if not os.path.isfile(os.path.join(CLIENT_DIST_DIR, 'index.html')):
        return jsonify({'success': False, 'error': '前端尚未构建，请运行 npm run build'}), 503

    requested = os.path.abspath(os.path.join(CLIENT_DIST_DIR, client_path))
    if os.path.commonpath([CLIENT_DIST_DIR, requested]) == CLIENT_DIST_DIR and os.path.isfile(requested):
        response = send_from_directory(
            CLIENT_DIST_DIR,
            client_path,
            max_age=31536000 if client_path.startswith('assets/') else 3600,
            conditional=True,
        )
        if client_path.startswith('assets/'):
            response.cache_control.public = True
            response.cache_control.immutable = True
        return response

    return send_from_directory(CLIENT_DIST_DIR, 'index.html', max_age=0, conditional=True)

if __name__ == '__main__':
    print('=' * 60)
    print('Nanobanana Server - Configuration')
    print('=' * 60)
    print(f'Server: http://{SERVER_HOST}:{SERVER_PORT}')
    public_base = build_public_url('')
    if public_base:
        print(f'Public: {public_base}  (used for Ark video reference URLs)')
    else:
        print(f'Public: NOT CONFIGURED  (set deployment.public_base_url in config.json for Ark video reference)')
    print(f'Config Source: {CONFIG_FILE} (v{config_v2.CONFIG_VERSION})')
    print()
    print('API Providers:')
    print(f'  Current: {CURRENT_PROVIDER.upper()}')
    current_api = API_PROVIDERS[CURRENT_PROVIDER]
    print(f'    Provider: {"Cupsy" if CURRENT_PROVIDER == "cupsy" else "BytePlus Ark"}')
    print(f'    Endpoint: {current_api.get("endpoint", "")}')
    print(f'    Model: {get_provider_default_model(CURRENT_PROVIDER, current_api)}')
    print(f'    API Key: {"configured" if get_provider_key(CURRENT_PROVIDER, current_api) else "missing"}')
    print()
    print('=' * 60)
    print(f'Starting server on http://{SERVER_HOST}:{SERVER_PORT}')
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False)
