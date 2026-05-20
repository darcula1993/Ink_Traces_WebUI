from flask import Flask, request, jsonify, send_file, session
from flask_cors import CORS
from werkzeug.exceptions import ClientDisconnected, RequestEntityTooLarge
import os
import base64
import requests
import io
import json
import threading
import copy
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from PIL import Image
import uuid
from datetime import datetime
import tasks as task_db

app = Flask(__name__)

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
    },
    'client': {'host': '0.0.0.0', 'port': 4545},
    'api': {
        'default_provider': 'ai_studio',
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
            'model': '',
            'endpoint': 'https://ark.ap-southeast.bytepluses.com',
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
def require_login():
    # 不需要认证的路径
    open_paths = ['/api/login', '/api/auth/check', '/api/health']
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

# API Provider 配置
CURRENT_PROVIDER = config['api'].get('default_provider', 'vertex')
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
    provider = session.get('image_provider', CURRENT_PROVIDER)
    return provider if provider in API_PROVIDERS else CURRENT_PROVIDER


def get_session_image_model():
    model = session.get('image_model', CURRENT_MODEL)
    valid_models = {m['id'] for m in AVAILABLE_MODELS}
    return model if model in valid_models else CURRENT_MODEL

# 动态获取当前 provider 的配置
def get_current_api_config():
    """获取当前 API provider 的配置"""
    return API_PROVIDERS.get(CURRENT_PROVIDER, API_PROVIDERS['vertex'])


def get_image_provider_config(provider):
    provider = provider if provider in API_PROVIDERS else CURRENT_PROVIDER
    return provider, API_PROVIDERS.get(provider, API_PROVIDERS['vertex'])


def get_provider_key(provider, provider_config):
    if provider == 'ark':
        return provider_config.get('api_key', '')
    return provider_config.get('key', '')


def get_provider_default_model(provider, provider_config):
    if provider == 'ark':
        return provider_config.get('model') or 'seedream-5-0-lite'
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
UPLOAD_VIDEO_DIR = os.path.join(PROJECT_ROOT, 'upload_video')
if not os.path.exists(UPLOAD_VIDEO_DIR):
    os.makedirs(UPLOAD_VIDEO_DIR)

REQUEST_TIMEOUT = int(config.get('server', {}).get('request_timeout_seconds', 120) or 120)
POLL_TIMEOUT = int(config.get('server', {}).get('poll_timeout_seconds', 30) or 30)
DOWNLOAD_TIMEOUT = int(config.get('server', {}).get('download_timeout_seconds', 120) or 120)
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
    with open(filepath, 'wb') as f:
        f.write(file_storage.read())
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
            elif key_lower in ('api_url', 'url') and isinstance(item, str):
                redacted[key] = redact_url(item)
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str) and value.lower().startswith('bearer '):
        return 'Bearer ***REDACTED***'
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
    """从文件加载prompts"""
    source_file = PROMPTS_FILE if os.path.exists(PROMPTS_FILE) else PROMPTS_EXAMPLE_FILE
    if os.path.exists(source_file):
        try:
            with open(source_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading prompts: {e}")
            return []
    return []

def save_prompts(prompts):
    """保存prompts到文件"""
    try:
        with open(PROMPTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(prompts, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error saving prompts: {e}")
        return False

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

    # HTTP状态码错误
    if status_code == 400:
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
            error_obj = response_data['error']
            if isinstance(error_obj, dict):
                error_info['message'] = error_obj.get('message', '')
                error_info['details']['code'] = error_obj.get('code', status_code)
                error_info['details']['status'] = error_obj.get('status', '')

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

        prompts = load_prompts()
        new_prompt = {
            'id': int(datetime.now().timestamp() * 1000),  # 使用时间戳作为ID
            'text': text.strip(),
            'createdAt': datetime.now().isoformat()
        }
        prompts.insert(0, new_prompt)  # 添加到列表开头

        if save_prompts(prompts):
            return jsonify({'success': True, 'prompt': new_prompt})
        else:
            return jsonify({'success': False, 'error': 'Failed to save prompt'}), 500
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

        prompts = load_prompts()
        updated = False

        for prompt in prompts:
            if prompt['id'] == prompt_id:
                prompt['text'] = new_text.strip()
                updated = True
                break

        if not updated:
            return jsonify({'success': False, 'error': 'Prompt not found'}), 404

        if save_prompts(prompts):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Failed to save prompt'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/prompts/<int:prompt_id>', methods=['DELETE'])
def delete_prompt(prompt_id):
    """删除prompt"""
    try:
        prompts = load_prompts()
        original_length = len(prompts)
        prompts = [p for p in prompts if p['id'] != prompt_id]

        if len(prompts) == original_length:
            return jsonify({'success': False, 'error': 'Prompt not found'}), 404

        if save_prompts(prompts):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Failed to delete prompt'}), 500
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
        response = requests.post(api_url, headers=headers, json=request_body, timeout=REQUEST_TIMEOUT)
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


def _generate_ark_image(prompt, aspect_ratio, resolution, parts, provider_config=None, model_id=None):
    """调用 BytePlus Ark Seedream API 生成图片"""
    ark_cfg = provider_config or API_PROVIDERS.get('ark', {})
    api_key = ark_cfg.get('api_key', '')
    endpoint = ark_cfg.get('endpoint', '').rstrip('/')
    model = model_id or ark_cfg.get('model', 'seedream-5-0-lite')

    # seedream-5-0-lite 只支持 2K / 3K
    SIZE_MAP = {
        '2K': {
            '1:1': '2048x2048', '4:3': '2304x1728', '3:4': '1728x2304',
            '16:9': '2848x1600', '9:16': '1600x2848', '3:2': '2496x1664',
            '2:3': '1664x2496', '21:9': '3136x1344',
        },
        '3K': {
            '1:1': '3072x3072', '4:3': '3456x2592', '3:4': '2592x3456',
            '16:9': '4096x2304', '9:16': '2304x4096', '3:2': '3744x2496',
            '2:3': '2496x3744', '21:9': '4704x2016',
        },
    }
    # 不支持的分辨率降级到 2K
    res_map = SIZE_MAP.get(resolution, SIZE_MAP['2K'])
    size = res_map.get(aspect_ratio, res_map.get('1:1', '2048x2048'))

    body = {
        'model': model,
        'prompt': prompt,
        'size': size,
        'response_format': 'b64_json',
        'watermark': False,
        'output_format': 'png',
        'sequential_image_generation': 'disabled',
    }

    # 参考图（取 parts 中的 inlineData）
    ref_images = [p['inlineData']['data'] for p in parts if 'inlineData' in p]
    if len(ref_images) == 1:
        body['image'] = f"data:image/png;base64,{ref_images[0]}"
    elif len(ref_images) > 1:
        body['image'] = [f"data:image/png;base64,{d}" for d in ref_images]

    url = f'{endpoint}/api/v3/images/generations'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}

    print(f'Using API: ARK, URL: {url}, Model: {model}, Size: {size}')

    req_info = {'prompt': prompt, 'aspect_ratio': aspect_ratio, 'resolution': resolution, 'size': size}

    try:
        response = requests.post(url, headers=headers, json=body, timeout=120)
    except Exception as e:
        save_error_log('ark_request_error', req_info, {}, str(e))
        return jsonify({'success': False, 'error': f'Ark API 请求失败: {e}', 'error_type': 'request_error'}), 500

    resp_data = response.json() if response.text else {}

    if response.status_code != 200:
        err_msg = resp_data.get('error', {}).get('message', f'Ark API 错误 {response.status_code}') if isinstance(resp_data.get('error'), dict) else resp_data.get('error', f'Ark API 错误 {response.status_code}')
        save_error_log('ark_api_error', req_info, resp_data, err_msg)
        return jsonify({'success': False, 'error': err_msg, 'error_type': 'api_error'}), response.status_code

    # 解析返回的图片
    images = []
    for item in resp_data.get('data', []):
        if 'error' in item:
            continue
        if item.get('b64_json'):
            images.append(f"data:image/jpeg;base64,{item['b64_json']}")
        elif item.get('url'):
            # 下载 url 转 base64
            try:
                img_resp = requests.get(item['url'], timeout=60)
                if img_resp.status_code == 200:
                    b64 = base64.b64encode(img_resp.content).decode('utf-8')
                    images.append(f"data:image/jpeg;base64,{b64}")
            except Exception:
                pass

    if not images:
        save_error_log('ark_generation_failed', req_info, resp_data, '未能生成图片')
        return jsonify({'success': False, 'error': '未能生成图片', 'error_type': 'generation_failed'}), 500

    return jsonify({'success': True, 'images': images, 'thinking': ''})


@app.route('/api/generate', methods=['POST'])
@app.route('/api/generate/text-to-image', methods=['POST'])
@app.route('/api/generate/image-to-image', methods=['POST'])
def generate():
    """统一生成接口：自动判断文生图/图生图"""
    try:
        # 判断是否有文件上传（图生图）
        has_images = bool(request.files.getlist('images'))

        if has_images:
            prompt = request.form.get('prompt')
            aspect_ratio = request.form.get('aspect_ratio', '3:4')
            resolution = request.form.get('resolution', '2K')
            use_search = request.form.get('use_search', 'false').lower() == 'true'
            enable_chat = request.form.get('enable_chat', 'false').lower() == 'true'
            session_id = request.form.get('session_id', None)
            think_level = request.form.get('think_level', 'minimal')
            provider = request.form.get('provider', get_session_image_provider())
            model_id = request.form.get('model', None)
        else:
            data = request.json or {}
            prompt = data.get('prompt')
            aspect_ratio = data.get('aspect_ratio', '9:16')
            resolution = data.get('resolution', '2K')
            use_search = data.get('use_search', False)
            enable_chat = data.get('enable_chat', False)
            session_id = data.get('session_id', None)
            think_level = data.get('think_level', 'minimal')
            provider = data.get('provider', get_session_image_provider())
            model_id = data.get('model')

        if not prompt:
            return jsonify({'success': False, 'error': '请提供图片描述'}), 400
        if provider not in API_PROVIDERS:
            return jsonify({'success': False, 'error': f'未知 provider: {provider}'}), 400
        provider, provider_config = get_image_provider_config(provider)
        if not get_provider_key(provider, provider_config):
            return jsonify({'success': False, 'error': f'{provider} 未配置 API Key'}), 400
        if provider == 'ark':
            model_id = get_provider_default_model(provider, provider_config)
        else:
            model_id = model_id or get_provider_default_model(provider, provider_config)

        print(f'Generating image with prompt: {prompt}')
        print(f'Chat mode: {enable_chat}, Session ID: {session_id}')
        if has_images:
            images_files = request.files.getlist('images')
            if len(images_files) > 14:
                return jsonify({'success': False, 'error': '最多只能上传14张图片'}), 400
            print(f'Number of reference images: {len(images_files)}')

        # 构建 parts
        parts = []
        if has_images:
            for img_file in request.files.getlist('images'):
                img_file.seek(0)
                raw = img_file.read()
                image = Image.open(io.BytesIO(raw))
                image = image.convert('RGB')
                image_b64 = image_to_base64(image)
                parts.append({"inlineData": {"mimeType": "image/png", "data": image_b64}})
        parts.append({"text": prompt})

        # 记录任务
        params = {'aspect_ratio': aspect_ratio, 'resolution': resolution, 'use_search': use_search, 'think_level': think_level, 'enable_chat': enable_chat}
        params['provider'] = provider
        params['model'] = model_id
        db_task_id = task_db.create_task('image', prompt, params, provider=provider)
        task_db.update_task(db_task_id, status='processing')

        # Ark 走独立的 Seedream API
        if provider == 'ark':
            resp = _generate_ark_image(prompt, aspect_ratio, resolution, parts, provider_config, model_id)
        else:
            resp = _parse_and_respond(prompt, aspect_ratio, resolution, use_search, enable_chat, session_id, parts, think_level, provider, model_id)
        if isinstance(resp, tuple):
            resp_obj, status_code = resp
            resp_data = resp_obj.get_json()
        else:
            resp_obj = resp
            status_code = 200
            resp_data = resp.get_json()

        if resp_data.get('success'):
            # 保存图片到本地
            output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'output', 'image', str(db_task_id))
            os.makedirs(output_dir, exist_ok=True)

            # 保存上传的参考图
            local_refs = []
            for i, part in enumerate(parts):
                if 'inlineData' in part:
                    fname = f'ref_{i}.png'
                    with open(os.path.join(output_dir, fname), 'wb') as f:
                        f.write(base64.b64decode(part['inlineData']['data']))
                    local_refs.append(f'/api/tasks/{db_task_id}/file/{fname}')

            # 保存生成的图片
            local_images = []
            for i, img_b64 in enumerate(resp_data.get('images', [])):
                if img_b64.startswith('data:'):
                    b64_data = img_b64.split(',', 1)[1]
                    fname = f'image_{i}.png'
                    with open(os.path.join(output_dir, fname), 'wb') as f:
                        f.write(base64.b64decode(b64_data))
                    local_images.append(f'/api/tasks/{db_task_id}/file/{fname}')
            task_db.update_task(db_task_id, status='succeeded', result={'images': resp_data.get('images', []), 'local_images': local_images, 'local_refs': local_refs, 'thinking': resp_data.get('thinking', '')}, output_dir=output_dir, completed_at=datetime.now().isoformat())
        else:
            task_db.update_task(db_task_id, status='failed', error=resp_data.get('error', ''), completed_at=datetime.now().isoformat())

        # 在响应中附加 task_id
        resp_data['task_id'] = db_task_id
        return jsonify(resp_data), status_code

    except ClientDisconnected:
        return jsonify({'success': False, 'error': '连接断开，请重试'}), 400
    except RequestEntityTooLarge:
        return jsonify({'success': False, 'error': '上传文件总大小超过100MB限制'}), 413
    except Exception as e:
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
    data = request.json or {}
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
    try:
        has_files = bool(request.content_type and 'multipart' in request.content_type)

        if has_files:
            prompt = request.form.get('prompt', '')
            ratio = request.form.get('ratio', 'adaptive')
            duration = int(request.form.get('duration', '5'))
            resolution = request.form.get('resolution', '720p')
            fast = request.form.get('fast', 'false').lower() == 'true'
            generate_audio = request.form.get('generate_audio', 'true').lower() == 'true'
            return_last_frame = request.form.get('return_last_frame', 'false').lower() == 'true'
            web_search = request.form.get('web_search', 'false').lower() == 'true'
            video_mode = request.form.get('video_mode', 'keyframe')
            provider = request.form.get('provider', get_session_video_provider())
        else:
            data = request.json or {}
            prompt = data.get('prompt', '')
            ratio = data.get('ratio', 'adaptive')
            duration = data.get('duration', 5)
            resolution = data.get('resolution', '720p')
            fast = data.get('fast', False)
            generate_audio = data.get('generate_audio', True)
            return_last_frame = data.get('return_last_frame', False)
            web_search = data.get('web_search', False)
            video_mode = data.get('video_mode', 'keyframe')
            provider = data.get('provider', get_session_video_provider())

        if provider not in VIDEO_PROVIDERS:
            return jsonify({'success': False, 'error': f'未知 provider: {provider}'}), 400
        provider, prov = get_video_provider_config(provider)
        app.logger.warning(f'Video generate [{provider}]: ratio={ratio}, duration={duration}, resolution={resolution}, fast={fast}, audio={generate_audio}, return_last_frame={return_last_frame}, mode={video_mode}')

        try:
            files_data = _parse_files(has_files, video_mode, provider)
        except ValueError as ve:
            return jsonify({'success': False, 'error': str(ve)}), 400

        # JSON body 中的预上传视频 URL
        if not has_files:
            data = request.json or {}
            ref_video_urls = data.get('ref_video_urls', [])
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

        resp = requests.post(url, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}, json=body, timeout=REQUEST_TIMEOUT)
        resp_data = resp.json() if resp.text else {}

        if resp.status_code != 200:
            err_msg = resp_data.get('message') or resp_data.get('error', {}).get('message', f'API 错误 {resp.status_code}')
            return jsonify({'success': False, 'error': err_msg}), resp.status_code

        # jiekou returns task_id, ark returns id
        external_id = resp_data.get('task_id') or resp_data.get('id')

        # 记录任务并启动后台轮询
        params = {'ratio': ratio, 'duration': duration, 'resolution': resolution, 'fast': fast, 'generate_audio': generate_audio, 'return_last_frame': return_last_frame, 'video_mode': video_mode}
        # 记录上传的参考视频路径，便于删除任务时清理
        ref_video_paths = list(files_data.get('ref_video_paths', []))
        # 从预上传 URL 反推本地路径（/api/upload_video/<filename>）
        for url in files_data.get('ref_videos', []):
            if isinstance(url, str) and '/api/upload_video/' in url:
                fname = url.rsplit('/api/upload_video/', 1)[-1]
                fp = os.path.join(UPLOAD_VIDEO_DIR, os.path.basename(fname))
                if fp not in ref_video_paths and os.path.isfile(fp):
                    ref_video_paths.append(fp)
        if ref_video_paths:
            params['ref_video_paths'] = ref_video_paths
        if files_data.get('ref_videos'):
            params['ref_video_urls'] = files_data['ref_videos']
        db_task_id = task_db.create_task('video', prompt, params, provider=provider, external_task_id=external_id)
        threading.Thread(target=_poll_video_task_bg, args=(db_task_id, external_id, provider), daemon=True).start()

        return jsonify({'success': True, 'task_id': external_id, 'db_task_id': db_task_id, 'provider': provider})

    except Exception as e:
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


# 视频输出保存目录
VIDEO_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'output', 'video')


@app.route('/api/video/task', methods=['GET'])
def video_task_status():
    """查询视频生成任务状态"""
    task_id = request.args.get('task_id')
    provider = request.args.get('provider', get_session_video_provider())
    if not task_id:
        return jsonify({'success': False, 'error': '缺少 task_id'}), 400

    try:
        prov = VIDEO_PROVIDERS.get(provider, get_video_provider())
        api_key = prov.get('api_key', '')
        endpoint = prov.get('endpoint', '')

        if provider == 'ark':
            resp = requests.get(
                f'{endpoint}/api/v3/contents/generations/tasks/{task_id}',
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=POLL_TIMEOUT
            )
            resp_data = resp.json() if resp.text else {}
            if resp.status_code != 200:
                err_msg = resp_data.get('error', {}).get('message', f'查询失败 {resp.status_code}')
                return jsonify({'success': False, 'error': err_msg}), resp.status_code

            ark_status = resp_data.get('status', '')
            content = resp_data.get('content', {})
            result = {
                'success': True,
                'status': ARK_STATUS_MAP.get(ark_status, ark_status),
                'reason': resp_data.get('error', {}).get('message', '') if isinstance(resp_data.get('error'), dict) else resp_data.get('error', ''),
                'progress': 0,
                'eta': 0,
                'videos': [],
                'images': []
            }
            if content.get('video_url'):
                result['videos'] = [{'video_url': content['video_url'], 'video_type': 'mp4'}]
            if content.get('last_frame_url'):
                result['images'] = [{'image_url': content['last_frame_url']}]

        else:
            resp = requests.get(
                f'{endpoint}/v3/async/task-result',
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                params={'task_id': task_id},
                timeout=POLL_TIMEOUT
            )
            resp_data = resp.json() if resp.text else {}
            if resp.status_code != 200:
                return jsonify({'success': False, 'error': resp_data.get('message', f'查询失败 {resp.status_code}')}), resp.status_code

            task = resp_data.get('task', {})
            result = {
                'success': True,
                'status': task.get('status', ''),
                'reason': task.get('reason', ''),
                'progress': task.get('progress_percent', 0),
                'eta': task.get('eta', 0),
                'videos': resp_data.get('videos', []),
                'images': resp_data.get('images', [])
            }

        return jsonify(result)

    except Exception as e:
        print(f'Error querying video task: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# Task Management API
# ============================================================

@app.route('/api/tasks', methods=['GET'])
def api_list_tasks():
    task_type = request.args.get('type')
    status = request.args.get('status')
    limit = int(request.args.get('limit', 50))
    offset = int(request.args.get('offset', 0))
    tasks, total = task_db.list_tasks(task_type, status, limit, offset)
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
    # 删除本地文件
    if t.get('output_dir') and os.path.isdir(t['output_dir']):
        import shutil
        shutil.rmtree(t['output_dir'], ignore_errors=True)
    # 删除上传的参考视频
    for vpath in (t.get('params') or {}).get('ref_video_paths', []):
        if os.path.isfile(vpath):
            os.remove(vpath)
    task_db.delete_task(task_id)
    return jsonify({'success': True})


@app.route('/api/tasks/clear', methods=['DELETE'])
def api_clear_tasks():
    """清空所有任务及其输出文件"""
    import shutil
    tasks, _ = task_db.list_tasks(limit=9999)
    for t in tasks:
        if t.get('output_dir') and os.path.isdir(t['output_dir']):
            shutil.rmtree(t['output_dir'], ignore_errors=True)
        for vpath in (t.get('params') or {}).get('ref_video_paths', []):
            if os.path.isfile(vpath):
                os.remove(vpath)
        task_db.delete_task(t['id'])
    return jsonify({'success': True, 'deleted': len(tasks)})


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
# Background video polling (server-side)
# ============================================================

def _poll_video_task_bg(db_task_id, external_task_id, provider):
    """后台轮询视频任务直到完成"""
    import time
    prov = VIDEO_PROVIDERS.get(provider, {})
    api_key = prov.get('api_key', '')
    endpoint = prov.get('endpoint', '')
    poll_interval = int(VIDEO_CONFIG.get('poll_interval_seconds', 4) or 4)
    max_attempts = int(VIDEO_CONFIG.get('poll_max_attempts', 1800) or 1800)

    task_db.update_task(db_task_id, status='processing')

    for attempt in range(max_attempts):
        try:
            if provider == 'ark':
                resp = requests.get(
                    f'{endpoint}/api/v3/contents/generations/tasks/{external_task_id}',
                    headers={'Authorization': f'Bearer {api_key}'},
                    timeout=POLL_TIMEOUT
                )
                resp_data = resp.json() if resp.text else {}
                if resp.status_code >= 400:
                    reason = resp_data.get('error', {}).get('message', f'查询失败 {resp.status_code}') if isinstance(resp_data.get('error'), dict) else f'查询失败 {resp.status_code}'
                    task_db.update_task(db_task_id, status='failed', error=reason, completed_at=datetime.now().isoformat())
                    return
                ark_status = resp_data.get('status', '')
                mapped = ARK_STATUS_MAP.get(ark_status, ark_status)
                content = resp_data.get('content', {})
                videos = [{'video_url': content['video_url'], 'video_type': 'mp4'}] if content.get('video_url') else []
                images = [{'image_url': content['last_frame_url']}] if content.get('last_frame_url') else []
                reason = resp_data.get('error', {}).get('message', '') if isinstance(resp_data.get('error'), dict) else ''
            else:
                resp = requests.get(
                    f'{endpoint}/v3/async/task-result',
                    headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                    params={'task_id': external_task_id},
                    timeout=POLL_TIMEOUT
                )
                resp_data = resp.json() if resp.text else {}
                if resp.status_code >= 400:
                    task_db.update_task(db_task_id, status='failed', error=resp_data.get('message', f'查询失败 {resp.status_code}'), completed_at=datetime.now().isoformat())
                    return
                task_info = resp_data.get('task', {})
                mapped = task_info.get('status', '')
                videos = resp_data.get('videos', [])
                images = resp_data.get('images', [])
                reason = task_info.get('reason', '')

            if mapped == 'TASK_STATUS_SUCCEED':
                result = {'videos': videos, 'images': images}
                # 保存文件
                output_dir = os.path.join(VIDEO_OUTPUT_DIR, str(db_task_id))
                os.makedirs(output_dir, exist_ok=True)
                for i, vid in enumerate(videos):
                    url = vid.get('video_url')
                    if url:
                        r = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
                        if r.status_code == 200:
                            fname = 'video.mp4' if i == 0 else f'video_{i}.mp4'
                            with open(os.path.join(output_dir, fname), 'wb') as f:
                                f.write(r.content)
                            result['local_video'] = f'/api/tasks/{db_task_id}/file/{fname}'
                for i, img in enumerate(images):
                    url = img.get('image_url')
                    if url:
                        r = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
                        if r.status_code == 200:
                            fname = 'last_frame.png' if i == 0 else f'last_frame_{i}.png'
                            with open(os.path.join(output_dir, fname), 'wb') as f:
                                f.write(r.content)
                            result['local_last_frame'] = f'/api/tasks/{db_task_id}/file/{fname}'

                task_db.update_task(db_task_id, status='succeeded', result=result, output_dir=output_dir, completed_at=datetime.now().isoformat())
                return

            elif mapped == 'TASK_STATUS_FAILED':
                task_db.update_task(db_task_id, status='failed', error=reason or '视频生成失败', completed_at=datetime.now().isoformat())
                return

        except Exception as e:
            print(f'Background poll error for task {db_task_id}: {e}')

        time.sleep(poll_interval)

    task_db.update_task(db_task_id, status='failed', error='视频任务轮询超时', completed_at=datetime.now().isoformat())


def _recover_processing_tasks():
    """服务启动时恢复所有 processing 状态的视频任务轮询"""
    tasks, _ = task_db.list_tasks(task_type='video', status='processing', limit=100)
    for t in tasks:
        ext_id = t.get('external_task_id')
        provider = t.get('provider', 'ark')
        if ext_id:
            print(f'  Recovering task {t["id"]} (external: {ext_id})')
            threading.Thread(target=_poll_video_task_bg, args=(t['id'], ext_id, provider), daemon=True).start()

if __name__ == '__main__':
    _recover_processing_tasks()
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
