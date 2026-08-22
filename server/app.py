from flask import Flask, Response, request, jsonify, send_file, send_from_directory, session, g, after_this_request
from flask_cors import CORS
from werkzeug.exceptions import ClientDisconnected, RequestEntityTooLarge
import os
import base64
import requests
import io
import json
import copy
import secrets
import re
import time
import tempfile
import zipfile
import hashlib
import mimetypes
import shutil
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

configure_logging()

app = Flask(__name__)
app.json.sort_keys = False


@app.teardown_appcontext
def close_database_connection(_error=None):
    task_db.close_db()

# Flask配置 - 文件上传限制
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# 加载配置文件
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
CLIENT_DIST_DIR = os.path.join(PROJECT_ROOT, 'client', 'dist')
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
CONFIG_EXAMPLE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json.example')
SECRET_KEY_FILE = os.path.join(PROJECT_ROOT, '.flask_secret_key')

BUILTIN_DEFAULT_CONFIG = {
    'auth': {'username': '', 'password': '', 'secret_key': ''},
    'server': {
        'host': '0.0.0.0',
        'port': 5000,
        'public_host': '',
        'public_port': 5000,
        'public_scheme': 'http',
        'cors_origins': [],
        'request_timeout_seconds': 120,
        'poll_timeout_seconds': 30,
        'download_timeout_seconds': 120,
        'worker_concurrency': 3,
        'worker_lease_seconds': 900,
        'gunicorn_max_requests': 1500,
        'gunicorn_max_requests_jitter': 150,
        'cleanup_interval_seconds': 3600,
        'orphan_grace_hours': 24,
    },
    'client': {'host': '0.0.0.0', 'port': 4545},
    'api': {
        'default_provider': 'ark',
        'default_model': 'gemini-3.1-flash-image-preview',
        'available_models': [
            {
                'id': 'gemini-3.1-flash-image-preview',
                'name': 'Gemini 3.1 Flash',
                'description': '快速响应，适合快速迭代',
            },
            {
                'id': 'gemini-3-pro-image-preview',
                'name': 'Gemini 3 Pro',
                'description': '高质量生成，更强的理解能力',
            },
        ],
        'vertex': {
            'key': '',
            'model_id': 'gemini-3.1-flash-image-preview',
            'endpoint': 'aiplatform.googleapis.com',
            'project_id': '',
        },
        'ark': {
            'api_key': '',
            'model': 'seedream-5-0-pro',
            'endpoint': 'https://ark.ap-southeast.bytepluses.com',
            'upload_timeout_seconds': 120,
            'request_timeout_seconds': 600,
        },
    },
    'safety': {
        'hate_speech': 'BLOCK_NONE',
        'dangerous_content': 'BLOCK_NONE',
        'sexually_explicit': 'BLOCK_NONE',
        'harassment': 'BLOCK_NONE',
    },
    'video': {
        'poll_interval_seconds': 4,
        'poll_max_attempts': 1800,
        'ark': {
            'api_key': '',
            'endpoint': 'https://ark.ap-southeast.bytepluses.com',
            'model': '',
            'seedance_2_5_model': 'ep-20260807145632-xprc6',
        },
        'cupsy': {
            'api_key': '',
            'endpoint': 'https://cupsy.io',
            'model': 'seedance-2.5',
            'source_base_url': '',
            'asset_token_ttl_seconds': 7200,
        },
    },
    'audio': {
        'poll_interval_seconds': 4,
        'poll_max_attempts': 1800,
        'cupsy': {
            'endpoint': 'https://cupsy.io',
            'model': 'seed-audio-1.0',
        },
    },
}


def deep_merge(defaults, overrides):
    """Recursively merge user config over defaults without mutating either."""
    merged = copy.deepcopy(defaults)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in ('true', '1', 'yes', 'on'):
        return True
    if normalized in ('false', '0', 'no', 'off', ''):
        return False
    return default

def load_config():
    """加载配置文件"""
    defaults = copy.deepcopy(BUILTIN_DEFAULT_CONFIG)
    if os.path.exists(CONFIG_EXAMPLE_FILE):
        try:
            with open(CONFIG_EXAMPLE_FILE, 'r', encoding='utf-8') as f:
                defaults = deep_merge(defaults, json.load(f))
        except Exception as e:
            print(f"Warning: Failed to load config.json.example: {e}")

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return deep_merge(defaults, json.load(f))
    except Exception as e:
        print(f"Warning: Failed to load config.json: {e}")
        print("Using example/default configuration")
        return defaults


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
    configured = cfg.get('server', {}).get('cors_origins') or []
    if configured:
        return configured

    client_port = cfg.get('client', {}).get('port', 4545)
    origins = [
        f'http://localhost:{client_port}',
        f'http://127.0.0.1:{client_port}',
    ]
    public_host = cfg.get('server', {}).get('public_host', '')
    public_scheme = cfg.get('server', {}).get('public_scheme', 'http')
    public_port = cfg.get('server', {}).get('public_port')
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
API_PROVIDERS = {
    'vertex': config['api'].get('vertex', {}),
    'ark': config['api'].get('ark', {})
}
configured_image_provider = config['api'].get('default_provider', 'ark')
CURRENT_PROVIDER = configured_image_provider if configured_image_provider in API_PROVIDERS else 'ark'

# 可用模型配置
AVAILABLE_MODELS = config['api'].get('available_models', [
    {
        "id": "gemini-3.1-flash-image-preview",
        "name": "Gemini 3.1 Flash",
        "description": "快速响应，适合快速迭代"
    },
    {
        "id": "gemini-3-pro-image-preview",
        "name": "Gemini 3 Pro",
        "description": "高质量生成，更强的理解能力"
    }
])
CURRENT_MODEL = config['api'].get('default_model', 'gemini-3.1-flash-image-preview')


def get_session_image_provider():
    if session.get('image_provider_default') != CURRENT_PROVIDER:
        session['image_provider'] = CURRENT_PROVIDER
        session['image_provider_default'] = CURRENT_PROVIDER
    provider = session.get('image_provider', CURRENT_PROVIDER)
    return provider if provider in API_PROVIDERS else CURRENT_PROVIDER


def get_session_image_model():
    model = session.get('image_model', CURRENT_MODEL)
    valid_models = {m['id'] for m in AVAILABLE_MODELS}
    return model if model in valid_models else CURRENT_MODEL

def get_image_provider_config(provider):
    provider = provider if provider in API_PROVIDERS else CURRENT_PROVIDER
    return provider, API_PROVIDERS.get(provider, API_PROVIDERS['ark'])


def get_provider_key(provider, provider_config):
    if provider == 'ark':
        return provider_config.get('api_key', '')
    return provider_config.get('key', '')


def get_provider_default_model(provider, provider_config):
    if provider == 'ark':
        return provider_config.get('model') or 'seedream-5-0-pro'
    return provider_config.get('model_id') or CURRENT_MODEL

# 服务器配置
SERVER_HOST = config['server']['host']
SERVER_PORT = config['server']['port']

# 公网访问配置（用于生成给外部服务访问的文件 URL，如 Ark 视频参考）
PUBLIC_HOST = config['server'].get('public_host', '')
PUBLIC_PORT = config['server'].get('public_port', SERVER_PORT)
PUBLIC_SCHEME = config['server'].get('public_scheme', 'http')

# 上传视频目录（供外部服务下载的公网可访问视频参考文件）
UPLOAD_VIDEO_DIR = storage.UPLOAD_VIDEO_DIR

REQUEST_TIMEOUT = int(config.get('server', {}).get('request_timeout_seconds', 120) or 120)
POLL_TIMEOUT = int(config.get('server', {}).get('poll_timeout_seconds', 30) or 30)
DOWNLOAD_TIMEOUT = int(config.get('server', {}).get('download_timeout_seconds', 120) or 120)
ARK_IMAGE_TIMEOUT = max(
    REQUEST_TIMEOUT,
    int(config.get('api', {}).get('ark', {}).get('request_timeout_seconds', 600) or 600),
)
ARK_IMAGE_UPLOAD_TIMEOUT = max(
    30,
    int(config.get('api', {}).get('ark', {}).get('upload_timeout_seconds', 120) or 120),
)
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
    return max(30, int(upload_timeout or ARK_IMAGE_UPLOAD_TIMEOUT)), max(
        30, int(request_timeout or ARK_IMAGE_TIMEOUT),
    )

def build_public_url(path):
    """根据 config 中的 public_host/port/scheme 构建公网可访问的 URL"""
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

# 安全设置配置
SAFETY_SETTINGS = config['safety']

def build_safety_settings():
    """构建安全设置数组"""
    return [
        {
            "category": "HARM_CATEGORY_HATE_SPEECH",
            "threshold": SAFETY_SETTINGS['hate_speech']
        },
        {
            "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
            "threshold": SAFETY_SETTINGS['dangerous_content']
        },
        {
            "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "threshold": SAFETY_SETTINGS['sexually_explicit']
        },
        {
            "category": "HARM_CATEGORY_HARASSMENT",
            "threshold": SAFETY_SETTINGS['harassment']
        }
    ]

def build_vertex_api_url(model_id, endpoint, api_key):
    return f"https://{endpoint}/v1/publishers/google/models/{model_id}:generateContent?key={api_key}"


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

# Chat会话存储 (内存中存储，重启后会丢失)
# 格式: {session_id: {'history': [contents], 'created_at': timestamp, 'last_used': timestamp}}
chat_sessions = {}

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

def get_or_create_session(session_id=None):
    """获取或创建一个会话"""
    if session_id and session_id in chat_sessions:
        chat_sessions[session_id]['last_used'] = datetime.now().isoformat()
        return session_id, chat_sessions[session_id]['history']
    else:
        # 创建新会话
        new_session_id = str(uuid.uuid4())
        chat_sessions[new_session_id] = {
            'history': [],
            'created_at': datetime.now().isoformat(),
            'last_used': datetime.now().isoformat()
        }
        return new_session_id, []

def add_to_session(session_id, content):
    """向会话添加内容"""
    if session_id in chat_sessions:
        chat_sessions[session_id]['history'].append(content)
        chat_sessions[session_id]['last_used'] = datetime.now().isoformat()

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

def parse_safety_error(response_data):
    """解析安全过滤相关的错误"""
    error_info = {
        'type': 'safety_filter',
        'message': '',
        'details': {},
        'user_message': '内容被安全过滤器拦截'
    }

    safety_issues = []

    # 检查 promptFeedback
    if 'promptFeedback' in response_data:
        prompt_feedback = response_data['promptFeedback']
        if prompt_feedback.get('blockReason') == 'SAFETY':
            error_info['details']['blocked_at'] = 'prompt'

            # 分析安全评级
            if 'safetyRatings' in prompt_feedback:
                for rating in prompt_feedback['safetyRatings']:
                    category = rating.get('category', '')
                    probability = rating.get('probability', '')

                    if probability in ['HIGH', 'MEDIUM']:
                        # 转换为友好的类别名称
                        category_name = category.replace('HARM_CATEGORY_', '').lower()
                        category_names = {
                            'harassment': '骚扰内容',
                            'hate_speech': '仇恨言论',
                            'sexually_explicit': '色情内容',
                            'dangerous_content': '危险内容'
                        }
                        friendly_name = category_names.get(category_name, category_name)
                        safety_issues.append(f"{friendly_name} ({probability.lower()})")

    # 检查 candidates 的 finishReason
    if 'candidates' in response_data and len(response_data['candidates']) > 0:
        candidate = response_data['candidates'][0]
        if candidate.get('finishReason') == 'SAFETY':
            error_info['details']['blocked_at'] = 'response'

            # 分析安全评级
            if 'safetyRatings' in candidate:
                for rating in candidate['safetyRatings']:
                    category = rating.get('category', '')
                    probability = rating.get('probability', '')

                    if probability in ['HIGH', 'MEDIUM']:
                        category_name = category.replace('HARM_CATEGORY_', '').lower()
                        category_names = {
                            'harassment': '骚扰内容',
                            'hate_speech': '仇恨言论',
                            'sexually_explicit': '色情内容',
                            'dangerous_content': '危险内容'
                        }
                        friendly_name = category_names.get(category_name, category_name)
                        safety_issues.append(f"{friendly_name} ({probability.lower()})")

    if safety_issues:
        error_info['details']['issues'] = safety_issues
        issues_text = '、'.join(safety_issues)
        blocked_at = error_info['details'].get('blocked_at', 'content')
        if blocked_at == 'prompt':
            error_info['user_message'] = f'您的提示词包含不适当内容: {issues_text}'
        else:
            error_info['user_message'] = f'生成的内容被拦截，原因: {issues_text}'

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
            'vertex': {
                'name': 'Vertex AI',
                'model': API_PROVIDERS['vertex'].get('model_id', ''),
                'available': bool(API_PROVIDERS['vertex'].get('key'))
            },
            'ark': {
                'name': 'BytePlus Ark',
                'model': API_PROVIDERS['ark'].get('model', ''),
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
                'error': 'Invalid provider. Must be "vertex" or "ark"'
            }), 400

        if new_provider == 'ark':
            if not API_PROVIDERS.get('ark', {}).get('api_key'):
                return jsonify({
                    'success': False,
                    'error': 'Provider "ark" is not configured'
                }), 400
        elif new_provider not in API_PROVIDERS or not API_PROVIDERS[new_provider].get('key'):
            return jsonify({
                'success': False,
                'error': f'Provider "{new_provider}" is not configured'
            }), 400

        session['image_provider'] = new_provider
        current_api = API_PROVIDERS[new_provider]
        model_id = get_provider_default_model(new_provider, current_api)

        provider_names = {'vertex': 'Vertex AI', 'ark': 'BytePlus Ark'}
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

# ==================== Model Selection API ====================

@app.route('/api/model', methods=['GET'])
def get_model():
    """获取当前模型和可用模型列表"""
    return jsonify({
        'success': True,
        'current_model': get_session_image_model(),
        'available_models': AVAILABLE_MODELS
    })

@app.route('/api/model', methods=['POST'])
def switch_model():
    """切换模型"""
    try:
        data = request.get_json()
        new_model = data.get('model')

        if not new_model:
            return jsonify({
                'success': False,
                'error': 'Model ID is required'
            }), 400

        # 验证模型是否在可用列表中
        valid_models = [m['id'] for m in AVAILABLE_MODELS]
        if new_model not in valid_models:
            return jsonify({
                'success': False,
                'error': f'Invalid model. Must be one of: {", ".join(valid_models)}'
            }), 400

        session['image_model'] = new_model

        # 获取模型信息
        model_info = next((m for m in AVAILABLE_MODELS if m['id'] == new_model), None)
        model_name = model_info['name'] if model_info else new_model

        return jsonify({
            'success': True,
            'message': f'Switched to {model_name}',
            'model': new_model
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


# ==================== Chat Session API ====================

@app.route('/api/chat/session', methods=['POST'])
def create_chat_session():
    """创建新的聊天会话"""
    session_id = str(uuid.uuid4())
    chat_sessions[session_id] = {
        'history': [],
        'created_at': datetime.now().isoformat(),
        'last_used': datetime.now().isoformat()
    }
    return jsonify({'success': True, 'session_id': session_id})

@app.route('/api/chat/session/<session_id>', methods=['DELETE'])
def delete_chat_session(session_id):
    """删除聊天会话"""
    if session_id in chat_sessions:
        del chat_sessions[session_id]
        return jsonify({'success': True, 'message': '会话已删除'})
    return jsonify({'success': False, 'error': '会话不存在'}), 404

@app.route('/api/chat/session/<session_id>', methods=['GET'])
def get_chat_session(session_id):
    """获取聊天会话历史"""
    if session_id in chat_sessions:
        return jsonify({
            'success': True,
            'session_id': session_id,
            'history': chat_sessions[session_id]['history'],
            'created_at': chat_sessions[session_id]['created_at'],
            'last_used': chat_sessions[session_id]['last_used']
        })
    return jsonify({'success': False, 'error': '会话不存在'}), 404

def _parse_and_respond(prompt, aspect_ratio, resolution, use_search, enable_chat, session_id, parts, think_level='minimal', provider=None, model_id=None):
    """统一的 Gemini API 调用和响应解析"""
    provider, provider_config = get_image_provider_config(provider)
    model_id = model_id or get_provider_default_model(provider, provider_config)
    api_key = get_provider_key(provider, provider_config)
    endpoint = provider_config.get('endpoint') or 'aiplatform.googleapis.com'

    # Chat模式：获取或创建会话
    current_session_id = None
    history = []
    if enable_chat:
        current_session_id, history = get_or_create_session(session_id)
        print(f'Using session: {current_session_id}, History length: {len(history)}')

    # 构建 contents
    if enable_chat and history:
        contents = history + [{"role": "user", "parts": parts}]
    else:
        contents = [{"role": "user", "parts": parts}]

    # 根据 provider 构建 imageConfig
    if provider == 'vertex':
        image_config = {
            "aspectRatio": aspect_ratio, "imageSize": resolution,
            "imageOutputOptions": {"mimeType": "image/png"},
            "personGeneration": "ALLOW_ALL"
        }
    else:
        image_config = {"aspectRatio": aspect_ratio, "imageSize": resolution}

    request_body = {
        "contents": contents,
        "generationConfig": {
            "temperature": 1, "maxOutputTokens": 32768,
            "responseModalities": ["TEXT", "IMAGE"],
            "topP": 0.95, "imageConfig": image_config,
            "thinkingConfig": {
                "thinkingLevel": think_level.capitalize(),
                "includeThoughts": True
            }
        },
        "safetySettings": build_safety_settings()
    }

    if use_search:
        request_body['tools'] = [{"google_search": {}}]

    api_url = build_vertex_api_url(model_id, endpoint, api_key)
    headers = {'Content-Type': 'application/json'}
    print(f'Using API: {provider.upper()}, URL: {redact_url(api_url)}')

    try:
        response = HTTP.post(api_url, headers=headers, json=request_body, timeout=(10, REQUEST_TIMEOUT))
    except requests.RequestException as e:
        req_info = {
            'prompt': prompt, 'aspect_ratio': aspect_ratio, 'resolution': resolution,
            'use_search': use_search, 'enable_chat': enable_chat, 'session_id': session_id,
            'provider': provider, 'model_id': model_id, 'api_url': api_url
        }
        save_error_log('api_request_error', req_info, {}, str(e))
        return jsonify({'success': False, 'error': f'API 请求失败: {e}', 'error_type': 'request_error'}), 500

    response_data = None
    if response.text:
        try: response_data = response.json()
        except: pass

    req_info = {
        'prompt': prompt, 'aspect_ratio': aspect_ratio, 'resolution': resolution,
        'use_search': use_search, 'enable_chat': enable_chat, 'session_id': session_id,
        'provider': provider, 'model_id': model_id
    }

    if response.status_code != 200:
        error_info = parse_api_error(response, response_data)
        save_error_log(f'api_error_{error_info["type"]}',
            {**req_info, 'api_url': api_url},
            {'status_code': response.status_code, 'response_body': response_data},
            error_info['user_message'])
        return jsonify({'success': False, 'error': error_info['user_message'],
            'error_type': error_info['type'], 'error_details': error_info['details']}), response.status_code

    thinking = ''
    images = []
    model_response_content = None
    finish_reason = None
    safety_ratings = None
    prompt_safety_ratings = None

    try:
        items_to_process = response_data if isinstance(response_data, list) else [response_data]
        for item in items_to_process:
            if 'promptFeedback' in item and 'safetyRatings' in item['promptFeedback']:
                prompt_safety_ratings = item['promptFeedback']['safetyRatings']

            if 'promptFeedback' in item and item['promptFeedback'].get('blockReason') == 'SAFETY':
                safety_error = parse_safety_error(item)
                save_error_log('safety_blocked_prompt', req_info, response_data, safety_error['user_message'])
                return jsonify({'success': False, 'error': safety_error['user_message'],
                    'error_type': safety_error['type'], 'error_details': safety_error['details']}), 400

            if 'candidates' in item and len(item['candidates']) > 0:
                candidate = item['candidates'][0]
                finish_reason = candidate.get('finishReason')
                if 'safetyRatings' in candidate:
                    safety_ratings = candidate['safetyRatings']

                if finish_reason == 'SAFETY':
                    safety_error = parse_safety_error(item)
                    save_error_log('safety_blocked_response', req_info, response_data, safety_error['user_message'])
                    return jsonify({'success': False, 'error': safety_error['user_message'],
                        'error_type': safety_error['type'], 'error_details': safety_error['details']}), 400

                if finish_reason == 'MAX_TOKENS':
                    save_error_log('max_tokens', req_info, response_data, '生成内容超出最大长度限制')
                    return jsonify({'success': False, 'error': '生成内容超出最大长度限制，请简化提示词或调整参数',
                        'error_type': 'max_tokens', 'error_details': {'reason': 'MAX_TOKENS'}}), 400

                if finish_reason == 'RECITATION':
                    save_error_log('recitation', req_info, response_data, '生成内容与已知内容重复度过高')
                    return jsonify({'success': False, 'error': '生成内容与已知内容重复度过高，请修改提示词',
                        'error_type': 'recitation', 'error_details': {'reason': 'RECITATION'}}), 400

                if finish_reason in ('IMAGE_PROHIBITED_CONTENT', 'IMAGE_SAFETY'):
                    finish_message = candidate.get('finishMessage', '图片内容违反了安全策略')
                    save_error_log('image_prohibited', req_info, response_data, f'图片生成被拦截：{finish_message}')
                    return jsonify({'success': False, 'error': f'图片生成被安全过滤器拦截：{finish_message}',
                        'error_type': 'image_safety', 'error_details': {'reason': finish_reason, 'message': finish_message}}), 400

                if 'content' in candidate and 'parts' in candidate['content']:
                    if model_response_content is None:
                        model_response_content = candidate['content']
                    for part in candidate['content']['parts']:
                        if 'text' in part:
                            thinking += part['text']
                        elif 'inlineData' in part:
                            inline_data = part['inlineData']
                            mime_type = inline_data.get('mimeType', 'image/png')
                            image_data = inline_data.get('data', '')
                            images.append(f"data:{mime_type};base64,{image_data}")
    except Exception as e:
        print(f'Error parsing response: {e}')
        import traceback
        traceback.print_exc()

    if not images:
        error_msg = '未能生成图片'
        error_details = {}
        if finish_reason:
            error_details['finish_reason'] = finish_reason
            if finish_reason == 'OTHER':
                error_msg = '图片生成被中断，原因未知。请稍后重试'
            elif finish_reason not in ('STOP', 'SAFETY', 'MAX_TOKENS', 'RECITATION'):
                error_msg = f'图片生成失败 (原因: {finish_reason})，请稍后重试'
        else:
            error_msg = '未能生成图片，API 响应格式不正确'
            error_details['issue'] = 'no_candidates_or_empty_response'
        save_error_log('generation_failed', {**req_info, 'finish_reason': finish_reason}, response_data, error_msg)
        return jsonify({'success': False, 'error': error_msg,
            'error_type': 'generation_failed', 'error_details': error_details}), 500

    # Chat模式：保存对话历史
    if enable_chat and current_session_id and model_response_content:
        add_to_session(current_session_id, {"role": "user", "parts": parts})
        add_to_session(current_session_id, {"role": "model", "parts": model_response_content.get("parts", [])})

    response_payload = {
        'success': True, 'images': images, 'thinking': thinking,
        'safety_ratings': safety_ratings, 'prompt_safety_ratings': prompt_safety_ratings
    }
    if enable_chat:
        response_payload['session_id'] = current_session_id
    return response_payload, 200


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


def resolve_seedream_pro_size(aspect_ratio, resolution, custom_width=None, custom_height=None):
    aspect_ratio = str(aspect_ratio or '1:1').strip().lower()
    if aspect_ratio != 'custom':
        resolution = str(resolution or '1K').strip().upper()
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
    background=None, layer_decomposition=False,
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
            size = resolve_seedream_pro_size(aspect_ratio, resolution, custom_width, custom_height)
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
    if background in {'transparent', 'opaque'}:
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
        response = HTTP.post(url, headers=headers, json=body, timeout=(upload_timeout, request_timeout))
    except requests.exceptions.ConnectTimeout as e:
        save_error_log('ark_request_error', req_info, {}, str(e))
        return jsonify({
            'success': False,
            'error': '连接 Ark API 超时，系统将自动重试',
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
        return jsonify({
            'success': False,
            'error': f'Ark API 网络请求失败: {e}',
            'error_type': 'request_error',
            'retryable': False,
        }), 502
    except Exception as e:
        save_error_log('ark_request_error', req_info, {}, str(e))
        return jsonify({
            'success': False,
            'error': f'Ark API 请求失败: {e}',
            'error_type': 'request_error',
            'retryable': False,
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
            # 下载 url 转 base64
            try:
                source_url = str(item['url'])
                img_resp = HTTP.get(source_url, timeout=(10, DOWNLOAD_TIMEOUT))
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
        'thinking': '',
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


def execute_image_task(task_id):
    """Execute one persisted image task and store only lightweight result metadata."""
    task = task_db.get_task(task_id)
    if not task:
        return {'success': False, 'error': '任务不存在'}, 404
    if task_db.cancellation_requested(task_id):
        task_db.finalize_task_cancel(task_id)
        return {'success': False, 'cancelled': True, 'error': '任务已取消', 'task_id': task_id}, 409

    params = task.get('params') or {}
    provider, provider_config = get_image_provider_config(task.get('provider') or params.get('provider'))
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
        with open(asset['path'], 'rb') as handle:
            encoded = base64.b64encode(handle.read()).decode('utf-8')
        parts.append({'inlineData': {'mimeType': asset.get('mime_type') or 'image/png', 'data': encoded}})
        local_refs.append(f'/api/tasks/{task_id}/file/{os.path.basename(asset["path"])}')
    parts.append({'text': task.get('prompt') or ''})

    try:
        if provider == 'ark':
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
            )
        else:
            response = _parse_and_respond(
                task.get('prompt') or '',
                params.get('aspect_ratio', '1:1'),
                params.get('resolution', '1K'),
                bool(params.get('use_search', False)),
                bool(params.get('enable_chat', False)),
                params.get('session_id'),
                parts,
                params.get('think_level', 'minimal'),
                provider,
                model_id,
            )
        response_data, status_code = _response_payload(response)
    except Exception as e:
        task_db.fail_task(task_id, str(e))
        return {'success': False, 'error': str(e), 'error_type': 'request_error', 'task_id': task_id}, 500

    if task_db.cancellation_requested(task_id):
        task_db.finalize_task_cancel(task_id)
        return {'success': False, 'cancelled': True, 'error': '任务已取消', 'task_id': task_id}, 409

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
    for index, data_url in enumerate(response_data.get('images') or []):
        if task_db.cancellation_requested(task_id):
            storage.remove_task_output_files(task_id)
            task_db.finalize_task_cancel(task_id)
            return {'success': False, 'cancelled': True, 'error': '任务已取消', 'task_id': task_id}, 409
        if not isinstance(data_url, str) or not data_url.startswith('data:'):
            continue
        header = data_url.split(',', 1)[0].lower()
        extension = 'jpg' if 'image/jpeg' in header else 'png'
        mime_type = 'image/jpeg' if extension == 'jpg' else 'image/png'
        filename = f'image_{index}.{extension}'
        path = os.path.join(output_dir, filename)
        storage.save_data_url(data_url, path)
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
        'thinking': response_data.get('thinking', ''),
        'output_format': response_data.get('output_format', params.get('output_format', 'png')),
    }
    if not task_db.complete_task(task_id, result, output_dir):
        storage.remove_task_output_files(task_id)
        task_db.finalize_task_cancel(task_id)
        return {'success': False, 'cancelled': True, 'error': '任务已取消', 'task_id': task_id}, 409

    payload = {
        'success': True,
        'images': local_images,
        'thinking': result['thinking'],
        'task_id': task_id,
        'safety_ratings': response_data.get('safety_ratings'),
        'prompt_safety_ratings': response_data.get('prompt_safety_ratings'),
    }
    if response_data.get('session_id'):
        payload['session_id'] = response_data['session_id']
    return payload, 200


def execute_layer_task(task_id):
    """Run one Seedream layer-decomposition task and initialize its studio document."""
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
        params.get('model'), layer_decomposition=True,
    )
    response_data, status_code = _response_payload(response)
    if not response_data.get('success'):
        task_db.fail_task(task_id, response_data.get('error', '图层分解失败'))
        response_data['task_id'] = task_id
        return response_data, status_code

    output_dir = task.get('output_dir') or storage.task_output_dir('layer', task_id)
    provider_items = response_data.get('items') or [
        {'data_url': data_url, 'z_index': index}
        for index, data_url in enumerate(response_data.get('images') or [])
    ]
    saved = []
    provider_items = sorted(provider_items, key=lambda value: int(value.get('z_index') or 0))
    for index, item in enumerate(provider_items):
        data_url = item.get('data_url')
        if not isinstance(data_url, str) or not data_url.startswith('data:'):
            continue
        z_index = int(item.get('z_index', index) or 0)
        is_base = z_index == 0
        item_format = str(item.get('output_format') or ('png' if not is_base else params.get('output_format', 'png'))).lower()
        extension = 'jpg' if item_format in {'jpg', 'jpeg'} else 'png'
        mime_type = 'image/jpeg' if extension == 'jpg' else 'image/png'
        filename = f'base.{extension}' if is_base else f'layer_{z_index:02d}.png'
        path = os.path.join(output_dir, filename)
        storage.save_data_url(data_url, path)
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


def _queue_layer_task(project, prompt, size):
    normalized_size = 'auto' if str(size).lower() == 'auto' else str(size).upper()
    if normalized_size not in {'auto', '1K', '1.5K', '2K'}:
        raise ValueError('图层分解分辨率仅支持 Auto、1K、1.5K 或 2K')
    provider, provider_config = get_image_provider_config('ark')
    if not get_provider_key(provider, provider_config):
        raise ValueError('Ark 未配置 API Key')
    task_id = task_db.create_task(
        'layer', prompt or '', {
            'project_id': project['id'], 'size': normalized_size,
            'output_format': 'png', 'provider': 'ark',
            'model': get_provider_default_model(provider, provider_config),
            'layer_decomposition': True,
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
    """Queue normal image jobs; keep chat generations synchronous for compatibility."""
    db_task_id = None
    try:
        is_form_request = request.mimetype == 'multipart/form-data'

        if is_form_request:
            prompt = request.form.get('prompt')
            aspect_ratio = request.form.get('aspect_ratio', '3:4')
            resolution = request.form.get('resolution', '1K')
            custom_width = request.form.get('custom_width')
            custom_height = request.form.get('custom_height')
            output_format = request.form.get('output_format', 'png').lower()
            background = request.form.get('background', 'default').lower()
            watermark = request.form.get('watermark', 'false').lower() == 'true'
            use_search = request.form.get('use_search', 'false').lower() == 'true'
            enable_chat = request.form.get('enable_chat', 'false').lower() == 'true'
            session_id = request.form.get('session_id', None)
            think_level = request.form.get('think_level', 'minimal')
            provider = request.form.get('provider', get_session_image_provider())
            model_id = request.form.get('model', None)
            raw_image_urls = request.form.get('image_urls', '[]')
            try:
                image_urls = json.loads(raw_image_urls)
            except (TypeError, json.JSONDecodeError):
                return jsonify({'success': False, 'error': 'image_urls 格式错误'}), 400
        else:
            data = request.get_json(silent=True) or {}
            prompt = data.get('prompt')
            aspect_ratio = data.get('aspect_ratio', '9:16')
            resolution = data.get('resolution', '1K')
            custom_width = data.get('custom_width')
            custom_height = data.get('custom_height')
            output_format = str(data.get('output_format', 'png')).lower()
            background = str(data.get('background', 'default')).lower()
            watermark = as_bool(data.get('watermark', False))
            use_search = as_bool(data.get('use_search', False))
            enable_chat = as_bool(data.get('enable_chat', False))
            session_id = data.get('session_id', None)
            think_level = data.get('think_level', 'minimal')
            provider = data.get('provider', get_session_image_provider())
            model_id = data.get('model')
            image_urls = data.get('image_urls') or []

        if not isinstance(image_urls, list) or any(not isinstance(url, str) for url in image_urls):
            return jsonify({'success': False, 'error': 'image_urls 必须是字符串数组'}), 400

        if not prompt:
            return jsonify({'success': False, 'error': '请提供图片描述'}), 400
        if provider not in API_PROVIDERS:
            return jsonify({'success': False, 'error': f'未知 provider: {provider}'}), 400
        aspect_ratio = str(aspect_ratio or '').strip().lower()
        valid_ratios = (set(ARK_SEEDREAM_PRO_SIZE_MAP['1K']) | {'auto', 'custom'}) if provider == 'ark' else {
            '1:1', '1:4', '4:1', '1:8', '8:1', '2:3', '3:2', '3:4',
            '4:3', '4:5', '5:4', '9:16', '16:9', '21:9',
        }
        valid_resolutions = {'1K', '2K'} if provider == 'ark' else {'0.5K', '1K', '2K', '4K'}
        if aspect_ratio not in valid_ratios:
            return jsonify({'success': False, 'error': f'不支持的图片比例: {aspect_ratio}'}), 400
        if not (provider == 'ark' and aspect_ratio == 'custom') and str(resolution).upper() not in valid_resolutions:
            return jsonify({'success': False, 'error': f'不支持的图片分辨率: {resolution}'}), 400
        resolution = str(resolution).upper()
        resolved_size = None
        if provider == 'ark':
            try:
                resolved_size = resolve_seedream_pro_size(
                    aspect_ratio, resolution, custom_width, custom_height,
                )
            except ValueError as error:
                return jsonify({'success': False, 'error': str(error)}), 400
            if aspect_ratio == 'custom':
                custom_width, custom_height = (int(value) for value in resolved_size.split('x', 1))
        if think_level not in ('minimal', 'high'):
            return jsonify({'success': False, 'error': f'不支持的思考级别: {think_level}'}), 400
        provider, provider_config = get_image_provider_config(provider)
        if not get_provider_key(provider, provider_config):
            return jsonify({'success': False, 'error': f'{provider} 未配置 API Key'}), 400
        if provider == 'ark':
            model_id = get_provider_default_model(provider, provider_config)
        else:
            model_id = model_id or get_provider_default_model(provider, provider_config)

        images_files = request.files.getlist('images') if is_form_request else []
        workspace_image_paths = []
        for image_url in image_urls:
            image_path = storage.resolve_workspace_asset_url('img_tabs', image_url)
            if not image_path:
                return jsonify({'success': False, 'error': '参考图片不存在或不属于当前工作区'}), 400
            workspace_image_paths.append(image_path)
        if images_files or workspace_image_paths:
            max_reference_images = ARK_SEEDREAM_PRO_MAX_REFERENCES if provider == 'ark' else 14
            if len(images_files) + len(workspace_image_paths) > max_reference_images:
                return jsonify({'success': False, 'error': f'当前 Provider 最多只能上传{max_reference_images}张图片'}), 400
        if background not in {'default', 'transparent', 'opaque'}:
            return jsonify({'success': False, 'error': '背景参数仅支持默认、透明或不透明'}), 400
        if background != 'default':
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
            'aspect_ratio': aspect_ratio,
            'use_search': use_search, 'think_level': think_level, 'enable_chat': enable_chat,
            'session_id': session_id,
            'provider': provider,
            'model': model_id,
        }
        if not (provider == 'ark' and aspect_ratio == 'custom'):
            params['resolution'] = resolution
        if provider == 'ark':
            params['output_format'] = output_format
            params['watermark'] = watermark
            params['size'] = resolved_size
            if background != 'default':
                params['background'] = background
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

        if enable_chat and provider != 'ark':
            task_db.update_task(db_task_id, status='processing')
            payload, status_code = execute_image_task(db_task_id)
            return jsonify(payload), status_code

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

VIDEO_CONFIG = config.get('video', {})
ARK_VIDEO_CONFIG = VIDEO_CONFIG.get('ark', {})
CUPSY_VIDEO_CONFIG = VIDEO_CONFIG.get('cupsy', {})
AUDIO_CONFIG = config.get('audio', {})
CUPSY_AUDIO_CONFIG = AUDIO_CONFIG.get('cupsy', {})
SEEDANCE_20 = 'seedance-2.0'
SEEDANCE_25 = 'seedance-2.5'
SEEDANCE_25_MODERATED = 'seedance-2.5-moderated'
CUPSY_SEEDANCE_MODELS = {SEEDANCE_25, SEEDANCE_25_MODERATED}
CUPSY_AUDIO_MODEL = 'seed-audio-1.0'
CUPSY_AUDIO_FORMATS = {'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg_opus': 'audio/ogg'}
CUPSY_AUDIO_SAMPLE_RATES = {8000, 16000, 24000, 32000, 44100, 48000}
CUPSY_AUDIO_SPEAKERS = {'vivi', 'mindy', 'kian', 'jess', 'opal'}
CUPSY_ASSET_SOURCE_MIN_TTL = 7200
SEEDANCE_25_DEFAULT_MODEL = 'ep-20260807145632-xprc6'
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
    model_25 = str(provider_config.get('seedance_2_5_model') or SEEDANCE_25_DEFAULT_MODEL).strip()

    aliases_25 = {SEEDANCE_25, 'dreamina-seedance-2.5', model_25.lower()}
    aliases_20 = {SEEDANCE_20, 'dreamina-seedance-2.0', model_20.lower()}
    if requested in aliases_25:
        model_key = SEEDANCE_25
    elif requested in aliases_20:
        model_key = SEEDANCE_20
    else:
        raise ValueError(f'不支持的视频模型: {requested_model}')

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
            raise ValueError('Ark 快速模式需要配置 video.ark.fast_model endpoint ID')
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
    }


def _cupsy_source_ready(settings=None):
    base_url = (settings or _cupsy_settings()).get('source_base_url', '')
    return base_url.startswith(('http://', 'https://'))


def _cupsy_source_url(asset):
    settings = _cupsy_settings()
    base_url = settings['source_base_url']
    if not _cupsy_source_ready(settings):
        raise ValueError('Cupsy 素材导入需要配置 video.cupsy.source_base_url 公网 HTTP(S) 地址')
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
    sha256 = os.path.basename(local_path).split('.', 1)[0]
    return task_db.create_provider_asset(
        'cupsy', kind, sha256, persisted['name'], persisted['mime_type'],
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
        'cupsy', kind, digest.hexdigest(), original_name or os.path.basename(path),
        mime_type, os.path.getsize(local_path), local_path,
    )


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
                timeout=(10, 60),
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
            headers=_cupsy_headers(), timeout=(10, 30),
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
        return jsonify({
            'success': True,
            'configured': bool(_cupsy_settings()['api_key']),
            'source_ready': _cupsy_source_ready(),
            'assets': [_cupsy_asset_json(asset) for asset in task_db.list_provider_assets('cupsy')],
        })
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'success': False, 'error': '请选择素材文件'}), 400
    try:
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


@app.route('/api/cupsy/source/<token>', methods=['GET', 'HEAD'])
def cupsy_asset_source(token):
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='cupsy-asset-source')
    ttl = max(
        CUPSY_ASSET_SOURCE_MIN_TTL,
        int(_cupsy_settings().get('asset_token_ttl_seconds', CUPSY_ASSET_SOURCE_MIN_TTL)
            or CUPSY_ASSET_SOURCE_MIN_TTL),
    )
    try:
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


@app.route('/api/cupsy/assets/<int:asset_id>', methods=['DELETE'])
def delete_cupsy_asset(asset_id):
    asset = task_db.get_provider_asset(asset_id)
    if not asset or asset.get('deleted_at'):
        return jsonify({'success': False, 'error': '素材不存在'}), 404
    if task_db.provider_asset_has_active_tasks(asset_id):
        return jsonify({'success': False, 'error': '素材正被进行中的任务使用'}), 409
    settings = _cupsy_settings()
    if asset.get('external_asset_id') and settings['api_key']:
        try:
            response = HTTP.delete(
                f'{settings.get("endpoint", "https://cupsy.io").rstrip("/")}/v1/assets/{asset["external_asset_id"]}',
                headers=_cupsy_headers(), timeout=(10, 30),
            )
        except requests.RequestException as error:
            return jsonify({'success': False, 'error': f'Cupsy 素材删除失败: {error}'}), 502
        if response.status_code not in {200, 204, 404}:
            return jsonify({'success': False, 'error': _cupsy_error(response, 'Cupsy 素材删除失败')}), 502
    now = task_db.utcnow()
    task_db.update_provider_asset(
        asset_id, status='deleted', deleted_at=now, next_run_at=None,
        lease_owner=None, lease_until=None, error=None,
    )
    try:
        os.remove(asset['local_path'])
    except FileNotFoundError:
        pass
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
            'ark': {'available': bool(ARK_VIDEO_CONFIG.get('api_key')), 'models': [SEEDANCE_20, SEEDANCE_25]},
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
    prompt = str(data.get('prompt') or data.get('text_prompt') or '').strip()
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
            or asset.get('provider') != 'cupsy' or asset.get('kind') != expected_kind
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
                    raise ValueError('视频参考需要在 config.json 中配置 server.public_host')
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
            or asset.get('provider') != 'cupsy' or asset.get('kind') != allowed_roles[role]
        ):
            return jsonify({'success': False, 'error': 'Cupsy 素材引用或角色无效'}), 400
        pending_links.append((asset, role, position))
        position += 1

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
    task_id = task_db.create_task('video', prompt, params, provider='cupsy', status='pending')
    output_dir = storage.task_output_dir('video', task_id)
    task_db.update_task(task_id, output_dir=output_dir)
    for asset, role, link_position in pending_links:
        task_db.link_task_provider_asset(task_id, asset['id'], role, link_position)
        task_db.link_asset(asset['local_path'], task_id, expires_at=None)
    return jsonify({
        'success': True, 'queued': True, 'db_task_id': task_id,
        'provider': 'cupsy', 'status': 'pending',
    }), 202


@app.route('/api/video/generate', methods=['POST'])
def video_generate():
    """提交视频生成任务，返回 task_id"""
    db_task_id = None
    try:
        has_files = bool(request.content_type and 'multipart' in request.content_type)
        data = {}

        if has_files:
            prompt = request.form.get('prompt', '')
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
            prompt = data.get('prompt', '')
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
        for path in ref_video_paths:
            task_db.link_asset(path, db_task_id, expires_at=None)

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
            task_db.fail_task(db_task_id, message)
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
                task_db.fail_task(db_task_id, message)
                return jsonify({
                    'success': False,
                    'error': message,
                    'error_type': 'upload_timeout',
                    'retryable': False,
                    'result_unknown': True,
                    'error_details': {'timeout_seconds': upload_timeout},
                    'db_task_id': db_task_id,
                }), 504
            message = f'{provider} API 网络请求失败: {error_text}'
            task_db.fail_task(db_task_id, message)
            return jsonify({
                'success': False,
                'error': message,
                'error_type': 'request_error',
                'retryable': False,
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

        if not task_db.activate_video_task(db_task_id, external_id):
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
}

TASK_VIEWS = {'all', 'favorite', 'active', 'trash'}
TASK_SORTS = {'newest', 'oldest', 'updated'}
TASK_FILTER_STATUSES = {
    'submitting', 'preparing', 'pending', 'processing', 'cancel_requested',
    'succeeded', 'failed', 'cancelled',
}
FAVORITE_GROUP_COLORS = {'green', 'cyan', 'blue', 'violet', 'rose', 'amber'}


def _task_download_name(task, filename, original=False):
    extension = os.path.splitext(filename)[1].lower().lstrip('.') or 'bin'
    if extension == 'jpeg':
        extension = 'jpg'
    match = re.search(r'_(\d+)(?:\.[^.]+)?$', filename)
    output_index = int(match.group(1)) + 1 if match else 1
    try:
        created_at = datetime.fromisoformat(str(task.get('created_at') or '').replace('Z', '+00:00'))
    except ValueError:
        created_at = datetime.now(timezone.utc)
    timestamp = created_at.strftime('%Y%m%d%H%M%S')
    name = (
        f'ink-traces-{task.get("type") or "media"}-task-{task["id"]}-'
        f'{timestamp}-output-{output_index:02d}'
    )
    return f'{name}{"-original" if original else ""}.{extension}'


def _task_png_text_entries(task):
    return png_metadata.build_text_entries(task.get('prompt'), task.get('params'))


def _task_output_asset(task_id, filename):
    for asset in task_db.list_assets(task_id):
        if asset['kind'] not in ('output_image', 'output_video', 'output_audio'):
            continue
        if os.path.basename(asset['path']) == filename and os.path.isfile(asset['path']):
            return asset
    return None


def _task_asset_response(task, asset, filename, as_attachment, raw=False):
    original = raw and asset.get('kind') == 'output_image'
    download_name = _task_download_name(task, filename, original=original)
    if filename.lower().endswith('.png') and not raw:
        response = Response(
            storage.iter_png_with_text(
                asset['path'], _task_png_text_entries(task),
            ),
            mimetype='image/png',
        )
        disposition = 'attachment' if as_attachment else 'inline'
        response.headers['Content-Disposition'] = f'{disposition}; filename="{download_name}"'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if as_attachment:
            response.headers['Cache-Control'] = 'no-store'
        else:
            response.cache_control.public = True
            response.cache_control.max_age = 31536000
            response.cache_control.immutable = True
        return response

    response = send_file(
        asset['path'],
        mimetype=asset.get('mime_type'),
        as_attachment=as_attachment,
        download_name=download_name,
        conditional=not as_attachment,
        max_age=0 if as_attachment else 31536000,
    )
    if not as_attachment:
        response.cache_control.public = True
        response.cache_control.immutable = True
    return response


def _attach_task_input_references(tasks):
    missing_ref_tasks = []
    for task in tasks:
        result = task.get('result') if isinstance(task.get('result'), dict) else {}
        if not result.get('local_refs') or len(result.get('local_ref_types') or []) != len(result.get('local_refs') or []):
            missing_ref_tasks.append(task)
    if not missing_ref_tasks:
        return tasks

    refs_by_task = {}
    ref_types_by_task = {}
    task_ids = [task['id'] for task in missing_ref_tasks]
    for asset in task_db.list_assets_for_tasks(task_ids, ('input_image', 'input_audio')):
        if not os.path.isfile(asset['path']):
            continue
        refs_by_task.setdefault(asset['task_id'], []).append(
            f'/api/tasks/{asset["task_id"]}/file/{os.path.basename(asset["path"])}'
        )
        ref_types_by_task.setdefault(asset['task_id'], []).append(
            'audio' if asset['kind'] == 'input_audio' else 'image'
        )
    for asset in task_db.list_task_provider_assets_for_tasks(task_ids, ('image', 'audio', 'video')):
        if asset.get('deleted_at') or not os.path.isfile(asset['local_path']):
            continue
        refs_by_task.setdefault(asset['task_id'], []).append(
            f'/api/cupsy/assets/{asset["id"]}/content'
        )
        ref_types_by_task.setdefault(asset['task_id'], []).append(asset['kind'])
    for task in missing_ref_tasks:
        local_refs = refs_by_task.get(task['id'])
        if not local_refs:
            continue
        result = dict(task['result']) if isinstance(task.get('result'), dict) else {}
        result['local_refs'] = local_refs
        result['local_ref_types'] = ref_types_by_task.get(task['id'], [])
        task['result'] = result
    return tasks


def _task_group_filter():
    raw_group = request.args.get('favorite_group')
    if raw_group is None or raw_group == '':
        return None, None
    try:
        group_id = int(raw_group)
    except (TypeError, ValueError):
        return None, (jsonify({'success': False, 'error': 'favorite_group 必须是正整数'}), 400)
    if group_id <= 0:
        return None, (jsonify({'success': False, 'error': 'favorite_group 必须是正整数'}), 400)
    return group_id, None


def _task_advanced_filters():
    status = request.args.get('status', '').strip().lower()
    provider = request.args.get('provider', '').strip()
    model = request.args.get('model', '').strip()
    created_after = request.args.get('created_after', '').strip()
    if status and status not in TASK_FILTER_STATUSES:
        return None, (jsonify({'success': False, 'error': '未知任务状态'}), 400)
    if len(provider) > 80:
        return None, (jsonify({'success': False, 'error': 'provider 过滤值过长'}), 400)
    if len(model) > 160:
        return None, (jsonify({'success': False, 'error': 'model 过滤值过长'}), 400)
    if created_after:
        try:
            parsed = datetime.fromisoformat(created_after.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            created_after = parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            return None, (jsonify({'success': False, 'error': 'created_after 必须是 ISO 日期时间'}), 400)
    return {
        'status': status or None,
        'provider': provider or None,
        'model': model or None,
        'created_after': created_after or None,
    }, None


def _parse_task_ids(data, maximum=500):
    raw_ids = data.get('ids') if isinstance(data, dict) else None
    if not isinstance(raw_ids, list) or not raw_ids:
        return None, (jsonify({'success': False, 'error': 'ids 必须是非空数组'}), 400)
    if len(raw_ids) > maximum:
        return None, (jsonify({'success': False, 'error': f'单次最多处理 {maximum} 个任务'}), 400)
    task_ids = []
    for raw_id in raw_ids:
        if isinstance(raw_id, bool):
            return None, (jsonify({'success': False, 'error': '任务 ID 必须是正整数'}), 400)
        try:
            task_id = int(raw_id)
        except (TypeError, ValueError):
            return None, (jsonify({'success': False, 'error': '任务 ID 必须是正整数'}), 400)
        if task_id <= 0:
            return None, (jsonify({'success': False, 'error': '任务 ID 必须是正整数'}), 400)
        if task_id not in task_ids:
            task_ids.append(task_id)
    return task_ids, None

@app.route('/api/tasks', methods=['GET'])
def api_list_tasks():
    task_type = request.args.get('type')
    advanced_filters, advanced_error = _task_advanced_filters()
    if advanced_error:
        return advanced_error
    favorite_arg = request.args.get('favorite')
    favorite = None if favorite_arg is None else favorite_arg.lower() in ('1', 'true', 'yes')
    active = request.args.get('active', '').lower() in ('1', 'true', 'yes')
    deleted = request.args.get('deleted', '').lower() in ('1', 'true', 'yes')
    ungrouped = request.args.get('ungrouped', '').lower() in ('1', 'true', 'yes')
    search = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'newest')
    if sort not in TASK_SORTS:
        return jsonify({'success': False, 'error': '未知排序方式'}), 400
    favorite_group, group_error = _task_group_filter()
    if group_error:
        return group_error
    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 100))
        offset = max(0, int(request.args.get('offset', 0)))
    except ValueError:
        return jsonify({'success': False, 'error': 'limit 和 offset 必须是整数'}), 400
    tasks, total = task_db.list_tasks(
        task_type, advanced_filters['status'], limit, offset, summary=True, favorite=favorite, active=active,
        search=search, deleted=deleted, favorite_group=favorite_group,
        ungrouped=ungrouped, sort=sort, provider=advanced_filters['provider'],
        model=advanced_filters['model'], created_after=advanced_filters['created_after'],
    )
    _attach_task_input_references(tasks)
    # 列表接口剥离大字段，只保留缩略图路径
    for t in tasks:
        if isinstance(t.get('result'), dict):
            r = t['result']
            t['result'] = {
                'local_images': r.get('local_images', []),
                'local_thumbnails': r.get('local_thumbnails', []),
                'local_refs': r.get('local_refs', []),
                'source_urls': r.get('source_urls', []),
                'local_video': r.get('local_video'),
                'local_audio': r.get('local_audio'),
                'local_last_frame': r.get('local_last_frame'),
                'local_thumbnail': r.get('local_thumbnail'),
                'local_ref_types': r.get('local_ref_types', []),
                'thinking': r.get('thinking', '')[:100]
            }
    return jsonify({'success': True, 'tasks': tasks, 'total': total})


@app.route('/api/tasks/filter-options', methods=['GET'])
def api_task_filter_options():
    task_type = request.args.get('type')
    deleted = request.args.get('deleted', '').lower() in ('1', 'true', 'yes')
    return jsonify({
        'success': True,
        **task_db.get_task_filter_options(task_type=task_type, deleted=deleted),
    })


@app.route('/api/tasks/status', methods=['GET'])
def api_task_statuses():
    raw_ids = request.args.get('ids', '')
    if not raw_ids:
        return jsonify({'success': False, 'error': '缺少任务 ids'}), 400
    task_ids = []
    for raw_id in raw_ids.split(','):
        try:
            task_id = int(raw_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '任务 ID 必须是正整数'}), 400
        if task_id <= 0:
            return jsonify({'success': False, 'error': '任务 ID 必须是正整数'}), 400
        if task_id not in task_ids:
            task_ids.append(task_id)
    if len(task_ids) > 100:
        return jsonify({'success': False, 'error': '单次最多查询 100 个任务'}), 400
    statuses = task_db.get_task_statuses(task_ids)
    found = {int(task['id']) for task in statuses}
    return jsonify({
        'success': True,
        'tasks': statuses,
        'missing_ids': [task_id for task_id in task_ids if task_id not in found],
    })


@app.route('/api/tasks/navigation', defaults={'task_id': None}, methods=['GET'])
@app.route('/api/tasks/<int:task_id>/navigation', methods=['GET'])
def api_task_navigation(task_id):
    task_type = request.args.get('type')
    view = request.args.get('view', 'all')
    search = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'newest')
    if view not in TASK_VIEWS:
        return jsonify({'success': False, 'error': '未知任务分类'}), 400
    if sort not in TASK_SORTS:
        return jsonify({'success': False, 'error': '未知排序方式'}), 400
    favorite_group, group_error = _task_group_filter()
    if group_error:
        return group_error
    ungrouped = request.args.get('ungrouped', '').lower() in ('1', 'true', 'yes')
    advanced_filters, advanced_error = _task_advanced_filters()
    if advanced_error:
        return advanced_error
    navigation = task_db.get_task_navigation(
        task_id=task_id,
        task_type=task_type,
        favorite=True if view == 'favorite' else None,
        active=view == 'active',
        search=search,
        deleted=view == 'trash',
        favorite_group=favorite_group if view == 'favorite' else None,
        ungrouped=ungrouped if view == 'favorite' else False,
        sort=sort,
        status=advanced_filters['status'], provider=advanced_filters['provider'],
        model=advanced_filters['model'], created_after=advanced_filters['created_after'],
    )
    return jsonify({'success': True, 'navigation': navigation})


@app.route('/api/tasks/selection', methods=['GET'])
def api_task_selection():
    task_type = request.args.get('type')
    view = request.args.get('view', 'all')
    search = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'newest')
    if view not in TASK_VIEWS:
        return jsonify({'success': False, 'error': '未知任务分类'}), 400
    if sort not in TASK_SORTS:
        return jsonify({'success': False, 'error': '未知排序方式'}), 400
    favorite_group, group_error = _task_group_filter()
    if group_error:
        return group_error
    ungrouped = request.args.get('ungrouped', '').lower() in ('1', 'true', 'yes')
    advanced_filters, advanced_error = _task_advanced_filters()
    if advanced_error:
        return advanced_error
    task_ids = task_db.list_task_ids(
        task_type=task_type,
        favorite=True if view == 'favorite' else None,
        active=view == 'active',
        search=search,
        deleted=view == 'trash',
        favorite_group=favorite_group if view == 'favorite' else None,
        ungrouped=ungrouped if view == 'favorite' else False,
        sort=sort,
        status=advanced_filters['status'], provider=advanced_filters['provider'],
        model=advanced_filters['model'], created_after=advanced_filters['created_after'],
    )
    return jsonify({'success': True, 'ids': task_ids, 'total': len(task_ids)})


@app.route('/api/tasks/<int:task_id>', methods=['GET'])
def api_get_task(task_id):
    t = task_db.get_task(task_id)
    if not t:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    _attach_task_input_references([t])
    return jsonify({'success': True, 'task': t})


@app.route('/api/tasks/<int:task_id>/favorite', methods=['PATCH'])
def api_favorite_task(task_id):
    task = task_db.get_task(task_id)
    if not task:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('favorite'), bool):
        return jsonify({'success': False, 'error': 'favorite 必须是布尔值'}), 400
    task_db.set_task_favorite(task_id, data['favorite'])
    return jsonify({'success': True, 'favorite': data['favorite'], 'task': task_db.get_task(task_id)})


@app.route('/api/favorite-groups', methods=['GET'])
def api_list_favorite_groups():
    return jsonify({
        'success': True,
        'groups': task_db.list_favorite_groups(request.args.get('type')),
    })


@app.route('/api/favorite-groups', methods=['POST'])
def api_create_favorite_group():
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()
    color = str(data.get('color') or 'green').strip().lower()
    if not name or len(name) > 40:
        return jsonify({'success': False, 'error': '分组名称长度必须为 1-40 个字符'}), 400
    if color not in FAVORITE_GROUP_COLORS:
        return jsonify({'success': False, 'error': '未知分组颜色'}), 400
    try:
        group = task_db.create_favorite_group(name, color)
    except Exception as error:
        if 'UNIQUE constraint failed' in str(error):
            return jsonify({'success': False, 'error': '收藏分组名称已存在'}), 409
        raise
    return jsonify({'success': True, 'group': group}), 201


@app.route('/api/favorite-groups/<int:group_id>', methods=['PATCH'])
def api_update_favorite_group(group_id):
    if not task_db.get_favorite_group(group_id):
        return jsonify({'success': False, 'error': '收藏分组不存在'}), 404
    data = request.get_json(silent=True) or {}
    name = None
    color = None
    if 'name' in data:
        name = str(data.get('name') or '').strip()
        if not name or len(name) > 40:
            return jsonify({'success': False, 'error': '分组名称长度必须为 1-40 个字符'}), 400
    if 'color' in data:
        color = str(data.get('color') or '').strip().lower()
        if color not in FAVORITE_GROUP_COLORS:
            return jsonify({'success': False, 'error': '未知分组颜色'}), 400
    try:
        group = task_db.update_favorite_group(group_id, name=name, color=color)
    except Exception as error:
        if 'UNIQUE constraint failed' in str(error):
            return jsonify({'success': False, 'error': '收藏分组名称已存在'}), 409
        raise
    return jsonify({'success': True, 'group': group})


@app.route('/api/favorite-groups/<int:group_id>', methods=['DELETE'])
def api_delete_favorite_group(group_id):
    if not task_db.delete_favorite_group(group_id):
        return jsonify({'success': False, 'error': '收藏分组不存在'}), 404
    return jsonify({'success': True})


@app.route('/api/tasks/<int:task_id>/favorite-groups', methods=['PATCH'])
def api_set_task_favorite_groups(task_id):
    if not task_db.get_task(task_id):
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    data = request.get_json(silent=True) or {}
    raw_group_ids = data.get('group_ids')
    if not isinstance(raw_group_ids, list):
        return jsonify({'success': False, 'error': 'group_ids 必须是数组'}), 400
    group_ids = []
    for raw_group_id in raw_group_ids:
        if isinstance(raw_group_id, bool):
            return jsonify({'success': False, 'error': '分组 ID 必须是正整数'}), 400
        try:
            group_id = int(raw_group_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '分组 ID 必须是正整数'}), 400
        if group_id <= 0:
            return jsonify({'success': False, 'error': '分组 ID 必须是正整数'}), 400
        group_ids.append(group_id)
    try:
        task_db.replace_task_favorite_groups(task_id, group_ids)
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    return jsonify({'success': True, 'task': task_db.get_task(task_id)})


@app.route('/api/tasks/bulk-favorite-groups', methods=['POST'])
def api_bulk_favorite_groups():
    data = request.get_json(silent=True) or {}
    task_ids, id_error = _parse_task_ids(data)
    if id_error:
        return id_error
    raw_group_ids = data.get('group_ids')
    if not isinstance(raw_group_ids, list):
        return jsonify({'success': False, 'error': 'group_ids 必须是数组'}), 400
    try:
        group_ids = [int(group_id) for group_id in raw_group_ids]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '分组 ID 必须是整数'}), 400
    if any(group_id <= 0 for group_id in group_ids):
        return jsonify({'success': False, 'error': '分组 ID 必须是正整数'}), 400
    mode = data.get('mode', 'add')
    if mode not in ('add', 'remove', 'replace'):
        return jsonify({'success': False, 'error': '未知分组更新方式'}), 400
    try:
        updated = task_db.update_tasks_favorite_groups(task_ids, group_ids, mode)
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    return jsonify({'success': True, 'updated': len(updated), 'updated_ids': updated})


@app.route('/api/tasks/bulk-delete', methods=['POST'])
def api_bulk_delete_tasks():
    data = request.get_json(silent=True) or {}
    task_ids, id_error = _parse_task_ids(data)
    if id_error:
        return id_error
    permanent = bool(data.get('permanent', False))
    if not permanent:
        moved_ids = task_db.move_tasks_to_trash(task_ids)
        missing_ids = [task_id for task_id in task_ids if task_id not in moved_ids]
        return jsonify({
            'success': True,
            'deleted': len(moved_ids),
            'trashed': len(moved_ids),
            'deleted_ids': moved_ids,
            'trashed_ids': moved_ids,
            'missing_ids': missing_ids,
        })

    deleted_ids = []
    missing_ids = []
    skipped_ids = []
    for task_id in task_ids:
        task = task_db.get_task(task_id)
        if not task:
            missing_ids.append(task_id)
            continue
        if task.get('deleted_at') is None or task.get('status') == 'cancel_requested':
            skipped_ids.append(task_id)
            continue
        storage.remove_task_files(task)
        task_db.delete_task(task_id)
        deleted_ids.append(task_id)

    return jsonify({
        'success': True,
        'deleted': len(deleted_ids),
        'deleted_ids': deleted_ids,
        'missing_ids': missing_ids,
        'skipped_ids': skipped_ids,
    })


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def api_delete_task(task_id):
    t = task_db.get_task(task_id)
    if not t:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    permanent = request.args.get('permanent', '').lower() in ('1', 'true', 'yes')
    if permanent:
        if t.get('deleted_at') is None:
            return jsonify({'success': False, 'error': '任务需要先移入回收站'}), 409
        if t.get('status') == 'cancel_requested':
            return jsonify({'success': False, 'error': '任务仍在取消中，请稍后再彻底删除'}), 409
        storage.remove_task_files(t)
        task_db.delete_task(task_id)
        return jsonify({'success': True, 'permanent': True})
    moved = task_db.move_tasks_to_trash([task_id])
    return jsonify({'success': True, 'trashed': bool(moved)})


@app.route('/api/tasks/<int:task_id>/cancel', methods=['POST'])
def api_cancel_task(task_id):
    task = task_db.get_task(task_id)
    if task and task.get('provider') == 'cupsy' and task.get('external_task_id'):
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
                    headers=_cupsy_headers(), timeout=(10, 30),
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


@app.route('/api/tasks/<int:task_id>/restore', methods=['POST'])
def api_restore_task(task_id):
    task = task_db.get_task(task_id)
    if not task:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    if task.get('deleted_at') is None:
        return jsonify({'success': False, 'error': '任务不在回收站'}), 409
    restored = task_db.restore_tasks([task_id])
    if not restored:
        return jsonify({'success': False, 'error': '任务仍在取消中，请稍后再恢复'}), 409
    return jsonify({'success': True, 'task': task_db.get_task(task_id)})


@app.route('/api/tasks/bulk-restore', methods=['POST'])
def api_bulk_restore_tasks():
    data = request.get_json(silent=True) or {}
    task_ids, id_error = _parse_task_ids(data)
    if id_error:
        return id_error
    restored_ids = task_db.restore_tasks(task_ids)
    return jsonify({
        'success': True,
        'restored': len(restored_ids),
        'restored_ids': restored_ids,
        'skipped_ids': [task_id for task_id in task_ids if task_id not in restored_ids],
    })


@app.route('/api/tasks/<int:task_id>/retry', methods=['POST'])
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

    retry_id = task_db.create_task(
        'image', task.get('prompt') or '', task.get('params') or {},
        provider=task.get('provider'), status='preparing', retry_of=task_id,
    )
    output_dir, _ = storage.clone_image_inputs(task_id, retry_id)
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


@app.route('/api/tasks/bulk-download', methods=['POST'])
def api_bulk_download_tasks():
    data = request.get_json(silent=True) or {}
    task_ids, id_error = _parse_task_ids(data, maximum=5000)
    if id_error:
        return id_error

    raw = as_bool(data.get('raw', False))
    archive = tempfile.NamedTemporaryFile(prefix='ink-traces-', suffix='.zip', delete=False)
    archive_path = archive.name
    archive.close()
    file_count = 0
    try:
        tasks_by_id = {task['id']: task for task in task_db.get_tasks_by_ids(task_ids)}
        assets_by_task = {}
        for asset in task_db.list_assets_for_tasks(task_ids, ('output_image', 'output_video', 'output_audio')):
            assets_by_task.setdefault(asset['task_id'], []).append(asset)
        # Generated media is already compressed; deflating it again wastes CPU.
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
            for task_id in task_ids:
                for asset in assets_by_task.get(task_id, []):
                    if not os.path.isfile(asset['path']):
                        continue
                    task = tasks_by_id.get(task_id)
                    if not task:
                        continue
                    filename = os.path.basename(asset['path'])
                    original = raw and asset.get('kind') == 'output_image'
                    download_name = _task_download_name(task, filename, original=original)
                    archive_name = f'{asset["task_type"]}-task-{task_id}/{download_name}'
                    if filename.lower().endswith('.png') and not raw:
                        with bundle.open(archive_name, 'w') as target:
                            for chunk in storage.iter_png_with_text(
                                asset['path'], _task_png_text_entries(task),
                            ):
                                target.write(chunk)
                    else:
                        bundle.write(asset['path'], arcname=archive_name)
                    file_count += 1
        if file_count == 0:
            os.remove(archive_path)
            return jsonify({'success': False, 'error': '所选任务没有可下载的结果'}), 404
    except Exception:
        if os.path.exists(archive_path):
            os.remove(archive_path)
        raise

    @after_this_request
    def remove_archive(response):
        try:
            os.remove(archive_path)
        except OSError:
            pass
        return response

    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    archive_id = uuid.uuid4().hex[:8]
    return send_file(
        archive_path,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'ink-traces-tasks-{timestamp}-{archive_id}.zip',
        max_age=0,
    )


@app.route('/api/tasks/clear', methods=['DELETE'])
def api_clear_tasks():
    """Move all visible tasks to trash; permanent removal stays explicit."""
    tasks, _ = task_db.list_tasks(limit=None)
    moved = task_db.move_tasks_to_trash([task['id'] for task in tasks])
    return jsonify({'success': True, 'deleted': len(moved), 'trashed': len(moved)})


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
        provider, provider_config = get_image_provider_config('ark')
        if not get_provider_key(provider, provider_config):
            raise ValueError('Ark 未配置 API Key')
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
        task_id = _queue_layer_task(project, request.form.get('prompt', ''), requested_size)
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
        task_id = _queue_layer_task(project, data.get('prompt', ''), data.get('size', 'auto'))
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
    archive = io.BytesIO()
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
    normalized = storage.persist_workspace_value(key, data['value'])
    state = task_db.set_workspace_state(key, normalized)
    # Preserve the request's field order so pre-fix clients do not mistake a
    # semantically identical, reordered response for another local change.
    state['value'] = normalized
    storage.cleanup_workspace_assets(key, normalized)
    return jsonify({'success': True, 'state': state})


@app.route('/api/workspace/assets/<key>', methods=['POST'])
def api_upload_workspace_asset(key):
    if key not in WORKSPACE_STATE_KEYS:
        return jsonify({'success': False, 'error': '未知工作区状态键'}), 404
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'success': False, 'error': '缺少工作区素材文件'}), 400
    try:
        asset = storage.persist_workspace_upload(key, upload, normalize_image=key == 'img_tabs')
        return jsonify({'success': True, 'asset': asset}), 201
    except (OSError, ValueError):
        return jsonify({'success': False, 'error': '工作区图片格式无效或文件已损坏'}), 400
    finally:
        storage.release_process_memory()


@app.route('/api/workspace/assets/<key>/<path:filename>', methods=['GET'])
def api_workspace_asset(key, filename):
    if key not in WORKSPACE_STATE_KEYS:
        return jsonify({'success': False, 'error': '未知工作区状态键'}), 404
    directory = os.path.join(storage.WORKSPACE_ASSET_DIR, key)
    return send_from_directory(directory, filename, max_age=3600)


@app.route('/api/tasks/<int:task_id>/file/<path:filename>', methods=['GET'])
def api_task_file(task_id, filename):
    """提供任务输出文件的访问"""
    t = task_db.get_task(task_id)
    if not t or not t.get('output_dir'):
        return jsonify({'success': False, 'error': '文件不存在'}), 404
    output_dir = os.path.abspath(t['output_dir'])
    filepath = os.path.abspath(os.path.join(output_dir, filename))
    if os.path.commonpath([output_dir, filepath]) != output_dir:
        return jsonify({'success': False, 'error': '文件不存在'}), 404
    if not os.path.isfile(filepath):
        return jsonify({'success': False, 'error': '文件不存在'}), 404
    output_asset = _task_output_asset(task_id, filename)
    if output_asset:
        return _task_asset_response(t, output_asset, filename, as_attachment=False)
    response = send_file(filepath, conditional=True, max_age=31536000)
    response.cache_control.public = True
    response.cache_control.immutable = True
    return response


@app.route('/api/tasks/<int:task_id>/download/<path:filename>', methods=['GET'])
def api_download_task_file(task_id, filename):
    task = task_db.get_task(task_id)
    asset = _task_output_asset(task_id, filename) if task else None
    if not task or not asset:
        return jsonify({'success': False, 'error': '下载文件不存在'}), 404
    return _task_asset_response(
        task,
        asset,
        filename,
        as_attachment=True,
        raw=as_bool(request.args.get('raw', False)),
    )


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
        filepath, public_url = save_temp_file(f, suffix='.mp4')
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    if not public_url:
        return jsonify({'success': False, 'error': '未配置 server.public_host，无法生成公网 URL'}), 500
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
            timeout=(10, DOWNLOAD_TIMEOUT), stream=True,
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
        try:
            response = HTTP.post(
                f'{endpoint}/v1/videos',
                headers=_cupsy_headers(f'nanobanana-video-{task_id}'),
                json=body, timeout=(10, 120),
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
            f'{endpoint}/v1/videos/{external_id}', headers=_cupsy_headers(), timeout=(10, POLL_TIMEOUT)
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
                references.append({'image_url': {'url': asset['asset_uri']}})
            elif asset['role'] == 'reference_audio':
                references.append({'audio_url': {'url': asset['asset_uri']}})

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
                json=body, timeout=(10, 120),
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
            headers=_cupsy_headers(), timeout=(10, POLL_TIMEOUT),
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
            timeout=(10, POLL_TIMEOUT),
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
            with HTTP.get(url, timeout=(10, DOWNLOAD_TIMEOUT), stream=True) as download:
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
            with HTTP.get(url, timeout=(10, DOWNLOAD_TIMEOUT), stream=True) as download:
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
        print(f'Public: NOT CONFIGURED  (set server.public_host in config.json for Ark video reference)')
    print(f'Config Source: config.json (environment variables DISABLED)')
    print()
    print('API Providers:')
    print(f'  Current: {CURRENT_PROVIDER.upper()}')
    current_api = API_PROVIDERS[CURRENT_PROVIDER]
    if CURRENT_PROVIDER == 'vertex':
        print(f'    Provider: Vertex AI')
        print(f'    Endpoint: {current_api.get("endpoint", "")}')
        print(f'    Model: {current_api.get("model_id", CURRENT_MODEL)}')
        print(f'    API Key: {"configured" if current_api.get("key") else "missing"}')
    else:
        print(f'    Provider: BytePlus Ark')
        print(f'    Endpoint: {current_api.get("endpoint", "")}')
        print(f'    Model: {current_api.get("model", "")}')
        print(f'    API Key: {"configured" if current_api.get("api_key") else "missing"}')
    print()
    # 显示备用 provider
    for alt_provider in ['vertex', 'ark']:
        if alt_provider == CURRENT_PROVIDER:
            continue
        alt_cfg = API_PROVIDERS.get(alt_provider, {})
        has_key = bool(alt_cfg.get('key') or alt_cfg.get('api_key'))
        if has_key:
            alt_names = {'vertex': 'Vertex AI', 'ark': 'BytePlus Ark'}
            print(f'  Backup: {alt_provider.upper()} ({alt_names[alt_provider]}) - Available')
    print('=' * 60)
    print(f'Starting server on http://{SERVER_HOST}:{SERVER_PORT}')
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False)
