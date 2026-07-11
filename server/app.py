from flask import Flask, request, jsonify, send_file, session, g
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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from PIL import Image
import uuid
from datetime import datetime, timezone
import tasks as task_db
import storage
from http_client import HTTP
from logging_config import configure_logging

configure_logging()

app = Flask(__name__)


@app.teardown_appcontext
def close_database_connection(_error=None):
    task_db.close_db()

# Flask配置 - 文件上传限制
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# 加载配置文件
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
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
        'ai_studio': {
            'key': '',
            'model_id': 'gemini-3.1-flash-image-preview',
            'endpoint': 'generativelanguage.googleapis.com',
        },
        'ark': {
            'api_key': '',
            'model': 'seedream-5-0-pro',
            'endpoint': 'https://ark.ap-southeast.bytepluses.com',
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
        'default_provider': 'ark',
        'poll_interval_seconds': 4,
        'poll_max_attempts': 1800,
        'jiekou': {'api_key': '', 'endpoint': ''},
        'ark': {
            'api_key': '',
            'endpoint': 'https://ark.ap-southeast.bytepluses.com',
            'model': '',
        },
    },
    'openai': {
        'api_key': '',
        'endpoint': 'https://api.openai.com',
        'model': 'gpt-5',
        'rewriter_prompt_file': 'video_prompt_rewriter.md',
        'agent_prompt_file': 'video_prompt_optimizer.md',
        'prompt_file': 'video_prompt_optimizer.md',
        'max_output_tokens': 1600,
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
    if request.path.startswith('/api/upload_video/'):
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
    app.logger.info(
        'request_completed',
        extra={
            'request_id': getattr(g, 'request_id', None),
            'method': request.method,
            'path': request.path,
            'status': response.status_code,
            'duration_ms': duration_ms,
        },
    )
    return response

# API Provider 配置
CURRENT_PROVIDER = config['api'].get('default_provider', 'ark')
API_PROVIDERS = {
    'vertex': config['api'].get('vertex', {}),
    'ai_studio': config['api'].get('ai_studio', {}),
    'ark': config['api'].get('ark', {})
}

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

# 动态获取当前 provider 的配置
def get_current_api_config():
    """获取当前 API provider 的配置"""
    return API_PROVIDERS.get(CURRENT_PROVIDER, API_PROVIDERS['ark'])


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

# 初始化 API 配置（使用默认 provider）
current_api = get_current_api_config()
API_KEY = current_api.get('key', '')
MODEL_ID = CURRENT_MODEL  # 使用全局的当前模型
API_ENDPOINT = current_api.get('endpoint', 'aiplatform.googleapis.com')
PROJECT_ID = current_api.get('project_id', '')

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
ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm'}
ALLOWED_VIDEO_MIMES = {'video/mp4', 'video/quicktime', 'video/x-m4v', 'video/webm'}

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

def build_api_url(model_id, endpoint=None, provider=None, api_key=None):
    """
    根据当前 provider 构建 API URL

    Vertex AI: https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent?key={key}
    AI Studio: https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}
    """
    provider = provider or CURRENT_PROVIDER
    api_key = API_KEY if api_key is None else api_key
    endpoint = endpoint or API_ENDPOINT

    if provider == 'vertex':
        # Vertex AI format
        return f"https://{endpoint}/v1/publishers/google/models/{model_id}:generateContent?key={api_key}"
    else:
        # Google AI Studio format - also uses query parameter for key
        return f"https://{endpoint}/v1beta/models/{model_id}:generateContent?key={api_key}"

def build_api_headers():
    """
    根据当前 provider 构建 API headers

    Both providers only need Content-Type header
    """
    return {'Content-Type': 'application/json'}


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
video_prompt_agent_sessions = {}

# Prompt收藏存储文件路径
PROMPTS_FILE = os.path.join(os.path.dirname(__file__), 'prompts.json')
PROMPTS_EXAMPLE_FILE = os.path.join(os.path.dirname(__file__), 'prompts.json.example')
SYSTEM_PROMPTS_DIR = os.path.join(PROJECT_ROOT, 'prompts')
OPENAI_CONFIG = config.get('openai', {})

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

def load_system_prompt(filename):
    """Load a versioned system prompt from the repository prompt directory."""
    safe_name = os.path.basename(filename or '')
    if not safe_name:
        raise ValueError('System prompt file is not configured')
    path = os.path.abspath(os.path.join(SYSTEM_PROMPTS_DIR, safe_name))
    prompt_dir = os.path.abspath(SYSTEM_PROMPTS_DIR)
    if os.path.commonpath([prompt_dir, path]) != prompt_dir or not os.path.isfile(path):
        raise FileNotFoundError('System prompt file not found')
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().strip()


def extract_response_text(response_data):
    """Extract plain text from the OpenAI Responses API payload."""
    if isinstance(response_data, dict):
        text = response_data.get('output_text')
        if isinstance(text, str) and text.strip():
            return text.strip()

        chunks = []
        for item in response_data.get('output', []) or []:
            for content in item.get('content', []) or []:
                if content.get('type') in ('output_text', 'text') and isinstance(content.get('text'), str):
                    chunks.append(content['text'])
        if chunks:
            return ''.join(chunks).strip()
    return ''


def openai_config_values():
    """Return OpenAI client settings without exposing secrets in logs."""
    api_key = OPENAI_CONFIG.get('api_key') or os.environ.get('OPENAI_API_KEY', '')
    model = OPENAI_CONFIG.get('model') or 'gpt-5'
    endpoint = (OPENAI_CONFIG.get('endpoint') or 'https://api.openai.com').rstrip('/')
    max_output_tokens = int(OPENAI_CONFIG.get('max_output_tokens', 1600) or 1600)
    return api_key, model, endpoint, max_output_tokens


def call_openai_response(system_prompt, input_payload, error_context):
    """Call the configured OpenAI Responses API and return extracted text."""
    api_key, model, endpoint, max_output_tokens = openai_config_values()
    if not api_key:
        return None, jsonify({'success': False, 'error': 'OpenAI API Key 未配置'}), 400

    body = {
        'model': model,
        'instructions': system_prompt,
        'input': input_payload,
        'max_output_tokens': max_output_tokens,
        'store': False,
    }
    response = HTTP.post(
        f'{endpoint}/v1/responses',
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
        json=body,
        timeout=(10, REQUEST_TIMEOUT),
    )
    response_data = response.json() if response.text else {}
    if response.status_code >= 400:
        err = response_data.get('error', {}) if isinstance(response_data, dict) else {}
        err_msg = err.get('message') if isinstance(err, dict) else ''
        save_error_log(
            error_context.get('error_type', 'openai_response_error'),
            {'model': model, **error_context.get('request', {})},
            response_data,
            err_msg or f'OpenAI API 错误 {response.status_code}',
        )
        return None, jsonify({'success': False, 'error': err_msg or f'OpenAI API 错误 {response.status_code}'}), response.status_code

    text = extract_response_text(response_data)
    if not text:
        save_error_log(
            error_context.get('empty_type', 'openai_response_empty'),
            {'model': model, **error_context.get('request', {})},
            response_data,
            'Empty OpenAI response',
        )
        return None, jsonify({'success': False, 'error': 'OpenAI 未返回有效文本'}), 500
    return text, None, None


def build_video_prompt_context(data, prompt=None):
    """Build shared context for video prompt rewriter and prompt agent."""
    return {
        'current_prompt': (prompt if prompt is not None else data.get('prompt', '')) or '',
        'video_mode': data.get('mode', ''),
        'ratio': data.get('ratio', ''),
        'duration': data.get('duration', ''),
        'resolution': data.get('resolution', ''),
        'fast': bool(data.get('fast', False)),
        'generate_audio': bool(data.get('generate_audio', True)),
        'return_last_frame': bool(data.get('return_last_frame', False)),
        'has_first_frame': bool(data.get('has_first_frame', False)),
        'has_last_frame': bool(data.get('has_last_frame', False)),
        'ref_image_count': int(data.get('ref_image_count', 0) or 0),
        'ref_video_count': int(data.get('ref_video_count', 0) or 0),
        'ref_audio_count': int(data.get('ref_audio_count', 0) or 0),
    }


def get_or_create_video_prompt_agent_session(session_id=None):
    if session_id and session_id in video_prompt_agent_sessions:
        video_prompt_agent_sessions[session_id]['last_used'] = datetime.now().isoformat()
        return session_id, video_prompt_agent_sessions[session_id]

    new_session_id = str(uuid.uuid4())
    video_prompt_agent_sessions[new_session_id] = {
        'history': [],
        'created_at': datetime.now().isoformat(),
        'last_used': datetime.now().isoformat(),
    }
    return new_session_id, video_prompt_agent_sessions[new_session_id]


def extract_optimized_video_prompt(agent_text):
    """Extract the final prompt section from the skill-style agent output."""
    if not agent_text:
        return ''

    patterns = [
        r'####\s*优化后提示词\s*\n(?P<prompt>.*?)(?:\n####\s*(?:优化问题|相关原则)|\Z)',
        r'###\s*优化后提示词\s*\n(?P<prompt>.*?)(?:\n###\s*(?:优化问题|相关原则)|\Z)',
        r'优化后提示词[:：]\s*(?P<prompt>.*?)(?:\n(?:优化问题|相关原则)[:：]|\Z)',
    ]
    for pattern in patterns:
        match = re.search(pattern, agent_text, re.S)
        if match:
            prompt = match.group('prompt').strip()
            return prompt.strip('`').strip()
    return ''

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
            'ai_studio': {
                'name': 'Google AI Studio',
                'model': API_PROVIDERS['ai_studio'].get('model_id', ''),
                'available': bool(API_PROVIDERS['ai_studio'].get('key'))
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

        if new_provider not in ['vertex', 'ai_studio', 'ark']:
            return jsonify({
                'success': False,
                'error': 'Invalid provider. Must be "vertex", "ai_studio", or "ark"'
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

        provider_names = {'vertex': 'Vertex AI', 'ai_studio': 'Google AI Studio', 'ark': 'BytePlus Ark'}
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


@app.route('/api/video/optimize-prompt', methods=['POST'])
def optimize_video_prompt():
    """One-click rewrite for the current video prompt."""
    try:
        data = request.get_json(silent=True) or {}
        prompt = (data.get('prompt') or '').strip()
        if not prompt:
            return jsonify({'success': False, 'error': '请先输入视频 prompt'}), 400

        prompt_file = OPENAI_CONFIG.get('rewriter_prompt_file') or 'video_prompt_rewriter.md'
        system_prompt = load_system_prompt(prompt_file)
        context = build_video_prompt_context(data, prompt)
        input_payload = json.dumps(context, ensure_ascii=False, indent=2)
        optimized, error_response, status_code = call_openai_response(
            system_prompt,
            input_payload,
            {
                'error_type': 'video_prompt_optimize_error',
                'empty_type': 'video_prompt_optimize_empty',
                'request': {'prompt': prompt},
            },
        )
        if error_response:
            return error_response, status_code

        return jsonify({'success': True, 'prompt': optimized})

    except requests.RequestException as e:
        save_error_log('video_prompt_optimize_request_error', {'prompt': (request.get_json(silent=True) or {}).get('prompt', '')}, {}, str(e))
        return jsonify({'success': False, 'error': f'OpenAI 请求失败: {e}'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/video/prompt-agent/session', methods=['POST'])
def create_video_prompt_agent_session():
    """Create an interactive video prompt optimization session."""
    session_id, agent_session = get_or_create_video_prompt_agent_session()
    return jsonify({
        'success': True,
        'session_id': session_id,
        'history': agent_session['history'],
    })


@app.route('/api/video/prompt-agent/session/<session_id>', methods=['DELETE'])
def delete_video_prompt_agent_session(session_id):
    """Delete an interactive video prompt optimization session."""
    if session_id in video_prompt_agent_sessions:
        del video_prompt_agent_sessions[session_id]
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '会话不存在'}), 404


@app.route('/api/video/prompt-agent/message', methods=['POST'])
def video_prompt_agent_message():
    """Run one turn of the skill-backed video prompt agent."""
    try:
        data = request.get_json(silent=True) or {}
        message = (data.get('message') or '').strip()
        prompt = (data.get('prompt') or '').strip()
        session_id, agent_session = get_or_create_video_prompt_agent_session(data.get('session_id'))

        if not message and not prompt and not agent_session['history']:
            return jsonify({'success': False, 'error': '请先输入视频 prompt 或发送消息'}), 400

        system_prompt = load_system_prompt(OPENAI_CONFIG.get('agent_prompt_file') or OPENAI_CONFIG.get('prompt_file') or 'video_prompt_optimizer.md')
        context = build_video_prompt_context(data, prompt)

        user_turn = {
            'role': 'user',
            'content': message or '请根据当前视频 prompt 和参数开始优化。',
        }
        agent_session['history'].append(user_turn)
        agent_session['last_used'] = datetime.now().isoformat()

        input_payload = json.dumps({
            'video_context': context,
            'conversation': agent_session['history'],
            'instruction': 'Continue this prompt optimization session. Ask clarifying questions when required by the skill, or produce the final optimized prompt when enough information is available.',
        }, ensure_ascii=False, indent=2)

        reply, error_response, status_code = call_openai_response(
            system_prompt,
            input_payload,
            {
                'error_type': 'video_prompt_agent_error',
                'empty_type': 'video_prompt_agent_empty',
                'request': {'prompt': prompt, 'session_id': session_id},
            },
        )
        if error_response:
            agent_session['history'].pop()
            return error_response, status_code

        assistant_turn = {'role': 'assistant', 'content': reply}
        agent_session['history'].append(assistant_turn)
        agent_session['last_used'] = datetime.now().isoformat()
        optimized_prompt = extract_optimized_video_prompt(reply)

        return jsonify({
            'success': True,
            'session_id': session_id,
            'message': reply,
            'optimized_prompt': optimized_prompt,
            'history': agent_session['history'],
        })

    except requests.RequestException as e:
        save_error_log('video_prompt_agent_request_error', {'session_id': (request.get_json(silent=True) or {}).get('session_id', '')}, {}, str(e))
        return jsonify({'success': False, 'error': f'OpenAI 请求失败: {e}'}), 500
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
    endpoint = provider_config.get('endpoint') or API_ENDPOINT

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

    api_url = build_api_url(model_id, endpoint=endpoint, provider=provider, api_key=api_key)
    headers = build_api_headers()
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
    return jsonify(response_payload)


ARK_SEEDREAM_PRO_MAX_REFERENCES = 10
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


def _generate_ark_image(prompt, aspect_ratio, resolution, parts, output_format='png', watermark=False, provider_config=None, model_id=None):
    """调用 BytePlus Ark Seedream 5.0 Pro API 生成单张图片。"""
    ark_cfg = provider_config or API_PROVIDERS.get('ark', {})
    api_key = ark_cfg.get('api_key', '')
    endpoint = ark_cfg.get('endpoint', '').rstrip('/')
    model = model_id or ark_cfg.get('model') or 'seedream-5-0-pro'
    request_timeout = max(30, int(ark_cfg.get('request_timeout_seconds', ARK_IMAGE_TIMEOUT) or ARK_IMAGE_TIMEOUT))
    resolution = str(resolution or '1K').upper()
    output_format = str(output_format or 'png').lower()

    if resolution not in ARK_SEEDREAM_PRO_SIZE_MAP:
        return jsonify({'success': False, 'error': 'Seedream 5.0 Pro 仅支持 1K 或 2K', 'error_type': 'invalid_resolution'}), 400
    if aspect_ratio not in ARK_SEEDREAM_PRO_SIZE_MAP[resolution]:
        return jsonify({'success': False, 'error': f'Seedream 5.0 Pro 不支持当前比例: {aspect_ratio}', 'error_type': 'invalid_aspect_ratio'}), 400
    if output_format not in ARK_SEEDREAM_OUTPUT_MIMES:
        return jsonify({'success': False, 'error': '输出格式仅支持 png 或 jpeg', 'error_type': 'invalid_output_format'}), 400

    size = ARK_SEEDREAM_PRO_SIZE_MAP[resolution][aspect_ratio]

    body = {
        'model': model,
        'prompt': prompt,
        'size': size,
        'response_format': 'b64_json',
        'watermark': bool(watermark),
        'output_format': output_format,
        'optimize_prompt_options': {'mode': 'standard'},
    }

    # 参考图（取 parts 中的 inlineData）
    ref_images = [p['inlineData']['data'] for p in parts if 'inlineData' in p]
    if len(ref_images) > ARK_SEEDREAM_PRO_MAX_REFERENCES:
        return jsonify({'success': False, 'error': 'Seedream 5.0 Pro 最多支持10张参考图', 'error_type': 'too_many_images'}), 400
    if len(ref_images) == 1:
        body['image'] = f"data:image/png;base64,{ref_images[0]}"
    elif len(ref_images) > 1:
        body['image'] = [f"data:image/png;base64,{d}" for d in ref_images]

    url = f'{endpoint}/api/v3/images/generations'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}

    print(f'Using API: ARK, URL: {url}, Model: {model}, Size: {size}')

    req_info = {
        'prompt': prompt, 'aspect_ratio': aspect_ratio, 'resolution': resolution,
        'size': size, 'output_format': output_format, 'watermark': bool(watermark),
    }

    try:
        response = HTTP.post(url, headers=headers, json=body, timeout=(10, request_timeout))
    except requests.exceptions.ConnectTimeout as e:
        save_error_log('ark_request_error', req_info, {}, str(e))
        return jsonify({
            'success': False,
            'error': '连接 Ark API 超时，系统将自动重试',
            'error_type': 'connect_timeout',
            'retryable': True,
            'error_details': {'message': str(e), 'timeout_seconds': 10},
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
    for item in resp_data.get('data', []):
        if 'error' in item:
            continue
        item_format = str(item.get('output_format') or output_format).lower()
        mime_type = ARK_SEEDREAM_OUTPUT_MIMES.get(item_format, ARK_SEEDREAM_OUTPUT_MIMES[output_format])
        if item.get('b64_json'):
            images.append(f"data:{mime_type};base64,{item['b64_json']}")
        elif item.get('url'):
            # 下载 url 转 base64
            try:
                img_resp = HTTP.get(item['url'], timeout=(10, 60))
                if img_resp.status_code == 200:
                    b64 = base64.b64encode(img_resp.content).decode('utf-8')
                    response_mime = img_resp.headers.get('Content-Type', '').split(';', 1)[0]
                    images.append(f"data:{response_mime or mime_type};base64,{b64}")
            except Exception:
                pass

    if not images:
        save_error_log('ark_generation_failed', req_info, resp_data, '未能生成图片')
        return jsonify({'success': False, 'error': '未能生成图片', 'error_type': 'generation_failed'}), 500

    return jsonify({'success': True, 'images': images, 'thinking': '', 'output_format': output_format})


def _response_payload(response):
    if isinstance(response, tuple):
        response_obj, status_code = response
    else:
        response_obj, status_code = response, 200
    return response_obj.get_json(), status_code


def execute_image_task(task_id):
    """Execute one persisted image task and store only lightweight result metadata."""
    task = task_db.get_task(task_id)
    if not task:
        return {'success': False, 'error': '任务不存在'}, 404

    params = task.get('params') or {}
    provider, provider_config = get_image_provider_config(task.get('provider') or params.get('provider'))
    model_id = params.get('model') or get_provider_default_model(provider, provider_config)
    output_dir = task.get('output_dir') or storage.task_output_dir('image', task_id)
    input_assets = [
        asset for asset in task_db.list_assets(task_id)
        if asset['kind'] == 'input_image' and os.path.isfile(asset['path'])
    ]
    input_assets.sort(key=lambda asset: asset['path'])

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
    for index, data_url in enumerate(response_data.get('images') or []):
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

    if not local_images:
        task_db.fail_task(task_id, '未能保存生成图片')
        return {'success': False, 'error': '未能保存生成图片', 'error_type': 'generation_failed', 'task_id': task_id}, 500

    result = {
        'local_images': local_images,
        'local_refs': local_refs,
        'thinking': response_data.get('thinking', ''),
        'output_format': response_data.get('output_format', params.get('output_format', 'png')),
    }
    task_db.complete_task(task_id, result, output_dir)

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


@app.route('/api/generate', methods=['POST'])
@app.route('/api/generate/text-to-image', methods=['POST'])
@app.route('/api/generate/image-to-image', methods=['POST'])
def generate():
    """Queue normal image jobs; keep chat generations synchronous for compatibility."""
    db_task_id = None
    try:
        has_images = bool(request.files.getlist('images'))

        if has_images:
            prompt = request.form.get('prompt')
            aspect_ratio = request.form.get('aspect_ratio', '3:4')
            resolution = request.form.get('resolution', '1K')
            output_format = request.form.get('output_format', 'png').lower()
            watermark = request.form.get('watermark', 'false').lower() == 'true'
            use_search = request.form.get('use_search', 'false').lower() == 'true'
            enable_chat = request.form.get('enable_chat', 'false').lower() == 'true'
            session_id = request.form.get('session_id', None)
            think_level = request.form.get('think_level', 'minimal')
            provider = request.form.get('provider', get_session_image_provider())
            model_id = request.form.get('model', None)
        else:
            data = request.get_json(silent=True) or {}
            prompt = data.get('prompt')
            aspect_ratio = data.get('aspect_ratio', '9:16')
            resolution = data.get('resolution', '1K')
            output_format = str(data.get('output_format', 'png')).lower()
            watermark = as_bool(data.get('watermark', False))
            use_search = as_bool(data.get('use_search', False))
            enable_chat = as_bool(data.get('enable_chat', False))
            session_id = data.get('session_id', None)
            think_level = data.get('think_level', 'minimal')
            provider = data.get('provider', get_session_image_provider())
            model_id = data.get('model')

        if not prompt:
            return jsonify({'success': False, 'error': '请提供图片描述'}), 400
        if provider not in API_PROVIDERS:
            return jsonify({'success': False, 'error': f'未知 provider: {provider}'}), 400
        valid_ratios = set(ARK_SEEDREAM_PRO_SIZE_MAP['1K']) if provider == 'ark' else {
            '1:1', '1:4', '4:1', '1:8', '8:1', '2:3', '3:2', '3:4',
            '4:3', '4:5', '5:4', '9:16', '16:9', '21:9',
        }
        valid_resolutions = {'1K', '2K'} if provider == 'ark' else {'0.5K', '1K', '2K', '4K'}
        if aspect_ratio not in valid_ratios:
            return jsonify({'success': False, 'error': f'不支持的图片比例: {aspect_ratio}'}), 400
        if str(resolution).upper() not in valid_resolutions:
            return jsonify({'success': False, 'error': f'不支持的图片分辨率: {resolution}'}), 400
        resolution = str(resolution).upper()
        if think_level not in ('minimal', 'high'):
            return jsonify({'success': False, 'error': f'不支持的思考级别: {think_level}'}), 400
        provider, provider_config = get_image_provider_config(provider)
        if not get_provider_key(provider, provider_config):
            return jsonify({'success': False, 'error': f'{provider} 未配置 API Key'}), 400
        if provider == 'ark':
            model_id = get_provider_default_model(provider, provider_config)
        else:
            model_id = model_id or get_provider_default_model(provider, provider_config)

        images_files = request.files.getlist('images') if has_images else []
        if has_images:
            max_reference_images = ARK_SEEDREAM_PRO_MAX_REFERENCES if provider == 'ark' else 14
            if len(images_files) > max_reference_images:
                return jsonify({'success': False, 'error': f'当前 Provider 最多只能上传{max_reference_images}张图片'}), 400

        params = {
            'aspect_ratio': aspect_ratio, 'resolution': resolution,
            'use_search': use_search, 'think_level': think_level, 'enable_chat': enable_chat,
            'session_id': session_id,
            'provider': provider,
            'model': model_id,
        }
        if provider == 'ark':
            params['output_format'] = output_format
            params['watermark'] = watermark
            params['prompt_optimization'] = 'standard'
        db_task_id = task_db.create_task('image', prompt, params, provider=provider, status='preparing')
        output_dir = storage.task_output_dir('image', db_task_id)
        task_db.update_task(db_task_id, output_dir=output_dir)

        for index, image_file in enumerate(images_files):
            path = os.path.join(output_dir, f'ref_{index}.png')
            storage.save_uploaded_image(image_file, path)
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


# ============================================================
# Video Generation (Seedance 2.0 — dual provider: jiekou / ark)
# ============================================================

VIDEO_CONFIG = config.get('video', {})
CURRENT_VIDEO_PROVIDER = VIDEO_CONFIG.get('default_provider', 'jiekou')
VIDEO_PROVIDERS = {
    'jiekou': VIDEO_CONFIG.get('jiekou', {}),
    'ark': VIDEO_CONFIG.get('ark', {})
}


def get_session_video_provider():
    provider = session.get('video_provider', CURRENT_VIDEO_PROVIDER)
    return provider if provider in VIDEO_PROVIDERS else CURRENT_VIDEO_PROVIDER

def get_video_provider():
    return VIDEO_PROVIDERS.get(get_session_video_provider(), {})


def get_video_provider_config(provider=None):
    provider = provider if provider in VIDEO_PROVIDERS else get_session_video_provider()
    return provider, VIDEO_PROVIDERS.get(provider, {})


@app.route('/api/video/provider', methods=['GET'])
def get_video_provider_info():
    return jsonify({'success': True, 'current': get_session_video_provider(), 'providers': list(VIDEO_PROVIDERS.keys())})


@app.route('/api/video/provider', methods=['POST'])
def switch_video_provider():
    data = request.get_json(silent=True) or {}
    p = data.get('provider', '')
    if p not in VIDEO_PROVIDERS:
        return jsonify({'success': False, 'error': f'未知 provider: {p}'}), 400
    if not VIDEO_PROVIDERS[p].get('api_key'):
        return jsonify({'success': False, 'error': f'{p} 未配置 API Key'}), 400
    session['video_provider'] = p
    return jsonify({'success': True, 'current': p})


def _build_jiekou_body(prompt, ratio, duration, resolution, fast, generate_audio, return_last_frame, web_search, video_mode, files_data):
    """构建 jiekou.ai 请求体"""
    body = {
        'prompt': prompt, 'ratio': ratio, 'duration': duration, 'resolution': resolution,
        'fast': fast, 'generate_audio': generate_audio, 'watermark': False,
        'return_last_frame': return_last_frame, 'web_search': web_search
    }
    if video_mode == 'keyframe':
        if files_data.get('first_frame'):
            body['image'] = files_data['first_frame']
        if files_data.get('last_frame'):
            body['last_image'] = files_data['last_frame']
    else:
        if files_data.get('ref_images'):
            body['reference_images'] = files_data['ref_images']
        if files_data.get('ref_videos'):
            body['reference_videos'] = files_data['ref_videos']
        if files_data.get('ref_audios'):
            body['reference_audios'] = files_data['ref_audios']
    return body


def _build_ark_body(prompt, ratio, duration, resolution, fast, generate_audio, return_last_frame, web_search, video_mode, files_data, provider_config=None):
    """构建 Ark (BytePlus) 请求体"""
    prov = provider_config or get_video_provider()
    model = prov.get('model', 'dreamina-seedance-2-0-260128')
    if fast and not model.endswith('-fast'):
        model = model.replace('260128', '260128-fast') if '260128' in model else model

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
    return body


def _parse_files(has_files, video_mode, provider=None):
    """从请求中提取文件数据，统一为 base64 data URI"""
    files_data = {}
    if not has_files:
        return files_data

    if video_mode == 'keyframe':
        img_files = request.files.getlist('image')
        if img_files:
            f = img_files[0]
            f.seek(0)
            raw = f.read()
            image = Image.open(io.BytesIO(raw))
            image = image.convert('RGB')
            files_data['first_frame'] = f'data:image/png;base64,{image_to_base64(image)}'
        last_files = request.files.getlist('last_image')
        if last_files:
            f = last_files[0]
            f.seek(0)
            raw = f.read()
            image = Image.open(io.BytesIO(raw))
            image = image.convert('RGB')
            files_data['last_frame'] = f'data:image/png;base64,{image_to_base64(image)}'
    else:
        ref_imgs = request.files.getlist('ref_images')
        if ref_imgs:
            files_data['ref_images'] = []
            for f in ref_imgs[:9]:
                f.seek(0)
                raw = f.read()
                img = Image.open(io.BytesIO(raw))
                img = img.convert('RGB')
                files_data['ref_images'].append(f'data:image/png;base64,{image_to_base64(img)}')
        ref_vids = request.files.getlist('ref_videos')
        if ref_vids:
            files_data['ref_videos'] = []
            files_data['ref_video_paths'] = []
            for f in ref_vids[:3]:
                if provider == 'ark':
                    filepath, public_url = save_temp_file(f, suffix='.mp4')
                    if not public_url:
                        raise ValueError('视频参考需要在 config.json 中配置 server.public_host')
                    files_data['ref_videos'].append(public_url)
                    files_data['ref_video_paths'].append(filepath)
                else:
                    vid_b64 = base64.b64encode(f.read()).decode('utf-8')
                    mime = f.content_type or 'video/mp4'
                    files_data['ref_videos'].append(f'data:{mime};base64,{vid_b64}')
        # 支持前端预上传的视频 URL
        ref_video_urls_raw = request.form.get('ref_video_urls')
        if ref_video_urls_raw:
            urls = json.loads(ref_video_urls_raw)
            if not isinstance(urls, list):
                raise ValueError('ref_video_urls 必须是数组')
            if urls:
                files_data.setdefault('ref_videos', []).extend(urls[:3])
        ref_auds = request.files.getlist('ref_audios')
        if ref_auds:
            files_data['ref_audios'] = []
            for f in ref_auds[:3]:
                aud_b64 = base64.b64encode(f.read()).decode('utf-8')
                mime = f.content_type or 'audio/wav'
                files_data['ref_audios'].append(f'data:{mime};base64,{aud_b64}')
    return files_data


@app.route('/api/video/generate', methods=['POST'])
def video_generate():
    """提交视频生成任务，返回 task_id"""
    db_task_id = None
    try:
        has_files = bool(request.content_type and 'multipart' in request.content_type)

        if has_files:
            prompt = request.form.get('prompt', '')
            ratio = request.form.get('ratio', 'adaptive')
            duration = request.form.get('duration', '5')
            resolution = request.form.get('resolution', '720p')
            fast = request.form.get('fast', 'false').lower() == 'true'
            generate_audio = request.form.get('generate_audio', 'true').lower() == 'true'
            return_last_frame = request.form.get('return_last_frame', 'false').lower() == 'true'
            web_search = request.form.get('web_search', 'false').lower() == 'true'
            video_mode = request.form.get('video_mode', 'keyframe')
            provider = request.form.get('provider', get_session_video_provider())
        else:
            data = request.get_json(silent=True) or {}
            prompt = data.get('prompt', '')
            ratio = data.get('ratio', 'adaptive')
            duration = data.get('duration', 5)
            resolution = data.get('resolution', '720p')
            fast = as_bool(data.get('fast', False))
            generate_audio = as_bool(data.get('generate_audio', True), default=True)
            return_last_frame = as_bool(data.get('return_last_frame', False))
            web_search = as_bool(data.get('web_search', False))
            video_mode = data.get('video_mode', 'keyframe')
            provider = data.get('provider', get_session_video_provider())

        if provider not in VIDEO_PROVIDERS:
            return jsonify({'success': False, 'error': f'未知 provider: {provider}'}), 400
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'duration 必须是整数'}), 400
        if duration not in {-1, *range(4, 16)}:
            return jsonify({'success': False, 'error': f'不支持的视频时长: {duration}'}), 400
        if ratio not in {'adaptive', '16:9', '4:3', '1:1', '3:4', '9:16', '21:9'}:
            return jsonify({'success': False, 'error': f'不支持的视频比例: {ratio}'}), 400
        if resolution not in {'480p', '720p', '1080p'}:
            return jsonify({'success': False, 'error': f'不支持的视频分辨率: {resolution}'}), 400
        if video_mode not in {'keyframe', 'reference'}:
            return jsonify({'success': False, 'error': f'不支持的视频模式: {video_mode}'}), 400
        provider, prov = get_video_provider_config(provider)
        app.logger.warning(f'Video generate [{provider}]: ratio={ratio}, duration={duration}, resolution={resolution}, fast={fast}, audio={generate_audio}, return_last_frame={return_last_frame}, mode={video_mode}')

        try:
            files_data = _parse_files(has_files, video_mode, provider)
        except ValueError as ve:
            return jsonify({'success': False, 'error': str(ve)}), 400

        # JSON body 中的预上传视频 URL
        if not has_files:
            data = request.get_json(silent=True) or {}
            ref_video_urls = data.get('ref_video_urls', [])
            if not isinstance(ref_video_urls, list):
                return jsonify({'success': False, 'error': 'ref_video_urls 必须是数组'}), 400
            if ref_video_urls:
                files_data['ref_videos'] = ref_video_urls[:3]

        if not prompt and not files_data:
            return jsonify({'success': False, 'error': '请提供 prompt 或参考素材'}), 400

        api_key = prov.get('api_key', '')
        endpoint = prov.get('endpoint', '')
        if not api_key:
            return jsonify({'success': False, 'error': f'{provider} 未配置 API Key'}), 400

        if provider == 'ark':
            body = _build_ark_body(prompt, ratio, duration, resolution, fast, generate_audio, return_last_frame, web_search, video_mode, files_data, prov)
            url = f'{endpoint}/api/v3/contents/generations/tasks'
        else:
            body = _build_jiekou_body(prompt, ratio, duration, resolution, fast, generate_audio, return_last_frame, web_search, video_mode, files_data)
            url = f'{endpoint}/v3/async/seedance-2.0'

        params = {'ratio': ratio, 'duration': duration, 'resolution': resolution, 'fast': fast, 'generate_audio': generate_audio, 'return_last_frame': return_last_frame, 'video_mode': video_mode}
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

        resp = HTTP.post(url, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}, json=body, timeout=(10, REQUEST_TIMEOUT))
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

        task_db.update_task(
            db_task_id,
            status='processing',
            external_task_id=external_id,
            progress=0,
            next_run_at=task_db.utcnow(),
        )

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


@app.route('/api/video/task', methods=['GET'])
def video_task_status():
    """Compatibility endpoint backed by the local task database."""
    external_task_id = request.args.get('task_id')
    provider = request.args.get('provider', get_session_video_provider())
    if not external_task_id:
        return jsonify({'success': False, 'error': '缺少 task_id'}), 400
    task = task_db.get_task_by_external(provider, external_task_id)
    if not task:
        return jsonify({'success': False, 'error': '本地任务不存在'}), 404

    status_map = {
        'pending': 'TASK_STATUS_QUEUED',
        'processing': 'TASK_STATUS_PROCESSING',
        'succeeded': 'TASK_STATUS_SUCCEED',
        'failed': 'TASK_STATUS_FAILED',
    }
    stored_result = task.get('result') or {}
    videos = stored_result.get('videos') or []
    images = stored_result.get('images') or []
    if stored_result.get('local_video'):
        videos = [{'video_url': stored_result['local_video'], 'video_type': 'mp4'}]
    if stored_result.get('local_last_frame'):
        images = [{'image_url': stored_result['local_last_frame']}]
    return jsonify({
        'success': True,
        'db_task_id': task['id'],
        'status': status_map.get(task['status'], task['status']),
        'reason': task.get('error') or '',
        'progress': task.get('progress') or 0,
        'eta': 0,
        'videos': videos,
        'images': images,
    })


# ============================================================
# Task Management API
# ============================================================

@app.route('/api/tasks', methods=['GET'])
def api_list_tasks():
    task_type = request.args.get('type')
    status = request.args.get('status')
    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 100))
        offset = max(0, int(request.args.get('offset', 0)))
    except ValueError:
        return jsonify({'success': False, 'error': 'limit 和 offset 必须是整数'}), 400
    tasks, total = task_db.list_tasks(task_type, status, limit, offset, summary=True)
    # 列表接口剥离大字段，只保留缩略图路径
    for t in tasks:
        if isinstance(t.get('result'), dict):
            r = t['result']
            t['result'] = {
                'local_images': r.get('local_images', []),
                'local_refs': r.get('local_refs', []),
                'local_video': r.get('local_video'),
                'local_last_frame': r.get('local_last_frame'),
                'thinking': r.get('thinking', '')[:100]
            }
    return jsonify({'success': True, 'tasks': tasks, 'total': total})


@app.route('/api/tasks/<int:task_id>', methods=['GET'])
def api_get_task(task_id):
    t = task_db.get_task(task_id)
    if not t:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    return jsonify({'success': True, 'task': t})


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def api_delete_task(task_id):
    t = task_db.get_task(task_id)
    if not t:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    storage.remove_task_files(t)
    task_db.delete_task(task_id)
    return jsonify({'success': True})


@app.route('/api/tasks/clear', methods=['DELETE'])
def api_clear_tasks():
    """清空所有任务及其输出文件"""
    tasks, _ = task_db.list_tasks(limit=None)
    for t in tasks:
        storage.remove_task_files(t)
    deleted = task_db.delete_all_tasks()
    return jsonify({'success': True, 'deleted': deleted})


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
    return send_file(filepath)


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

def poll_video_task_once(task_id):
    """Poll one provider task once and persist terminal results."""
    task = task_db.get_task(task_id)
    if not task:
        return {'state': 'failed', 'error': '任务不存在'}

    external_task_id = task.get('external_task_id')
    provider = task.get('provider') or 'ark'
    prov = VIDEO_PROVIDERS.get(provider, {})
    api_key = prov.get('api_key', '')
    endpoint = prov.get('endpoint', '')

    try:
        if provider == 'ark':
            response = HTTP.get(
                f'{endpoint}/api/v3/contents/generations/tasks/{external_task_id}',
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=(10, POLL_TIMEOUT),
            )
        else:
            response = HTTP.get(
                f'{endpoint}/v3/async/task-result',
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                params={'task_id': external_task_id},
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

    if provider == 'ark':
        mapped_status = ARK_STATUS_MAP.get(response_data.get('status', ''), response_data.get('status', ''))
        content = response_data.get('content') or {}
        videos = [{'video_url': content['video_url'], 'video_type': 'mp4'}] if content.get('video_url') else []
        images = [{'image_url': content['last_frame_url']}] if content.get('last_frame_url') else []
        error_obj = response_data.get('error', {})
        reason = error_obj.get('message', '') if isinstance(error_obj, dict) else str(error_obj or '')
        progress = 0
    else:
        task_info = response_data.get('task') or {}
        mapped_status = task_info.get('status', '')
        videos = response_data.get('videos') or []
        images = response_data.get('images') or []
        reason = task_info.get('reason', '')
        progress = int(task_info.get('progress_percent', 0) or 0)

    if mapped_status == 'TASK_STATUS_FAILED':
        task_db.fail_task(task_id, reason or '视频生成失败')
        return {'state': 'failed', 'error': reason or '视频生成失败'}

    if mapped_status != 'TASK_STATUS_SUCCEED':
        return {'state': 'pending', 'progress': progress}

    output_dir = task.get('output_dir') or storage.task_output_dir('video', task_id)
    result = {'videos': videos, 'images': images, 'local_videos': [], 'local_images': []}
    try:
        for index, video in enumerate(videos):
            url = video.get('video_url')
            if not url:
                continue
            filename = 'video.mp4' if index == 0 else f'video_{index}.mp4'
            path = os.path.join(output_dir, filename)
            with HTTP.get(url, timeout=(10, DOWNLOAD_TIMEOUT), stream=True) as download:
                if download.status_code >= 400:
                    return {'state': 'retry', 'error': f'视频下载失败 {download.status_code}'}
                storage.stream_response_to_file(download, path)
            storage.register_file(task_id, 'output_video', path, 'video/mp4')
            result['local_videos'].append(f'/api/tasks/{task_id}/file/{filename}')

        for index, image in enumerate(images):
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
    except requests.RequestException as e:
        return {'state': 'retry', 'error': str(e)}

    if result['local_videos']:
        result['local_video'] = result['local_videos'][0]
    if result['local_images']:
        result['local_last_frame'] = result['local_images'][0]
    task_db.complete_task(task_id, result, output_dir)
    return {'state': 'succeeded', 'result': result}

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
    if CURRENT_PROVIDER == 'vertex':
        print(f'    Provider: Vertex AI')
        print(f'    Endpoint: {API_ENDPOINT}')
        print(f'    Model: {MODEL_ID}')
        print(f'    Project ID: {PROJECT_ID}')
        print(f'    API Key: {"configured" if API_KEY else "missing"}')
    elif CURRENT_PROVIDER == 'ark':
        print(f'    Provider: BytePlus Ark')
        print(f'    Endpoint: {API_PROVIDERS["ark"].get("endpoint", "")}')
        print(f'    Model: {API_PROVIDERS["ark"].get("model", "")}')
        print(f'    API Key: {"configured" if API_PROVIDERS["ark"].get("api_key", "") else "missing"}')
    else:
        print(f'    Provider: Google AI Studio')
        print(f'    Endpoint: {API_ENDPOINT}')
        print(f'    Model: {MODEL_ID}')
        print(f'    API Key: {"configured" if API_KEY else "missing"}')
    print()
    # 显示备用 provider
    for alt_provider in ['vertex', 'ai_studio', 'ark']:
        if alt_provider == CURRENT_PROVIDER:
            continue
        alt_cfg = API_PROVIDERS.get(alt_provider, {})
        has_key = bool(alt_cfg.get('key') or alt_cfg.get('api_key'))
        if has_key:
            alt_names = {'vertex': 'Vertex AI', 'ai_studio': 'Google AI Studio', 'ark': 'BytePlus Ark'}
            print(f'  Backup: {alt_provider.upper()} ({alt_names[alt_provider]}) - Available')
    print('=' * 60)
    print(f'Starting server on http://{SERVER_HOST}:{SERVER_PORT}')
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False)
