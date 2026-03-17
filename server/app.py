from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.exceptions import ClientDisconnected, RequestEntityTooLarge
import os
import base64
import requests
import io
import json
from PIL import Image
import uuid
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Flask配置 - 文件上传限制
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# 加载配置文件
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')

def load_config():
    """加载配置文件"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load config.json: {e}")
        print("Using default configuration")
        return {
            'server': {'host': '0.0.0.0', 'port': 5000},
            'client': {'host': '0.0.0.0', 'port': 4545},
            'api': {
                'key': '',
                'model_id': 'gemini-3-pro-image-preview',
                'endpoint': 'aiplatform.googleapis.com'
            },
            'safety': {
                'hate_speech': 'BLOCK_NONE',
                'dangerous_content': 'BLOCK_NONE',
                'sexually_explicit': 'BLOCK_NONE',
                'harassment': 'BLOCK_NONE'
            }
        }

config = load_config()

# API Provider 配置
CURRENT_PROVIDER = config['api'].get('default_provider', 'vertex')
API_PROVIDERS = {
    'vertex': config['api'].get('vertex', {}),
    'ai_studio': config['api'].get('ai_studio', {})
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

# 动态获取当前 provider 的配置
def get_current_api_config():
    """获取当前 API provider 的配置"""
    return API_PROVIDERS.get(CURRENT_PROVIDER, API_PROVIDERS['vertex'])

# 初始化 API 配置（使用默认 provider）
current_api = get_current_api_config()
API_KEY = current_api.get('key', '')
MODEL_ID = CURRENT_MODEL  # 使用全局的当前模型
API_ENDPOINT = current_api.get('endpoint', 'aiplatform.googleapis.com')
PROJECT_ID = current_api.get('project_id', '')

# 服务器配置
SERVER_HOST = config['server']['host']
SERVER_PORT = config['server']['port']

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

def build_api_url(model_id, endpoint=None):
    """
    根据当前 provider 构建 API URL

    Vertex AI: https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent?key={key}
    AI Studio: https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}
    """
    global CURRENT_PROVIDER, API_KEY, API_ENDPOINT

    endpoint = endpoint or API_ENDPOINT

    if CURRENT_PROVIDER == 'vertex':
        # Vertex AI format
        return f"https://{endpoint}/v1/publishers/google/models/{model_id}:generateContent?key={API_KEY}"
    else:
        # Google AI Studio format - also uses query parameter for key
        return f"https://{endpoint}/v1beta/models/{model_id}:generateContent?key={API_KEY}"

def build_api_headers():
    """
    根据当前 provider 构建 API headers

    Both providers only need Content-Type header
    """
    return {'Content-Type': 'application/json'}

# Chat会话存储 (内存中存储，重启后会丢失)
# 格式: {session_id: {'history': [contents], 'created_at': timestamp, 'last_used': timestamp}}
chat_sessions = {}

# Prompt收藏存储文件路径
PROMPTS_FILE = os.path.join(os.path.dirname(__file__), 'prompts.json')

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
            'request': request_data,
            'response': response_data
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
    if os.path.exists(PROMPTS_FILE):
        try:
            with open(PROMPTS_FILE, 'r', encoding='utf-8') as f:
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
    global CURRENT_PROVIDER
    return jsonify({
        'success': True,
        'current_provider': CURRENT_PROVIDER,
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
            }
        }
    })

@app.route('/api/provider', methods=['POST'])
def switch_provider():
    """切换 API provider"""
    global CURRENT_PROVIDER, API_KEY, MODEL_ID, API_ENDPOINT, PROJECT_ID

    try:
        data = request.get_json()
        new_provider = data.get('provider')

        if new_provider not in ['vertex', 'ai_studio']:
            return jsonify({
                'success': False,
                'error': 'Invalid provider. Must be "vertex" or "ai_studio"'
            }), 400

        if new_provider not in API_PROVIDERS or not API_PROVIDERS[new_provider].get('key'):
            return jsonify({
                'success': False,
                'error': f'Provider "{new_provider}" is not configured'
            }), 400

        # 切换 provider
        CURRENT_PROVIDER = new_provider
        current_api = API_PROVIDERS[new_provider]

        # 更新全局变量
        API_KEY = current_api.get('key', '')
        MODEL_ID = current_api.get('model_id', '')
        API_ENDPOINT = current_api.get('endpoint', '')
        PROJECT_ID = current_api.get('project_id', '')

        provider_name = 'Vertex AI' if new_provider == 'vertex' else 'Google AI Studio'

        return jsonify({
            'success': True,
            'message': f'Switched to {provider_name}',
            'provider': new_provider,
            'model': MODEL_ID
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
    global CURRENT_MODEL
    return jsonify({
        'success': True,
        'current_model': CURRENT_MODEL,
        'available_models': AVAILABLE_MODELS
    })

@app.route('/api/model', methods=['POST'])
def switch_model():
    """切换模型"""
    global CURRENT_MODEL, MODEL_ID

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

        # 切换模型
        CURRENT_MODEL = new_model
        MODEL_ID = new_model

        # 获取模型信息
        model_info = next((m for m in AVAILABLE_MODELS if m['id'] == new_model), None)
        model_name = model_info['name'] if model_info else new_model

        return jsonify({
            'success': True,
            'message': f'Switched to {model_name}',
            'model': CURRENT_MODEL
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

def _parse_and_respond(prompt, aspect_ratio, resolution, use_search, enable_chat, session_id, parts, think_level='minimal'):
    """统一的 Gemini API 调用和响应解析"""
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
    if CURRENT_PROVIDER == 'vertex':
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

    api_url = build_api_url(MODEL_ID)
    headers = build_api_headers()
    print(f'Using API: {CURRENT_PROVIDER.upper()}, URL: {api_url}')

    response = requests.post(api_url, headers=headers, json=request_body)

    response_data = None
    if response.text:
        try: response_data = response.json()
        except: pass

    req_info = {
        'prompt': prompt, 'aspect_ratio': aspect_ratio, 'resolution': resolution,
        'use_search': use_search, 'enable_chat': enable_chat, 'session_id': session_id
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
        else:
            data = request.json or {}
            prompt = data.get('prompt')
            aspect_ratio = data.get('aspect_ratio', '9:16')
            resolution = data.get('resolution', '2K')
            use_search = data.get('use_search', False)
            enable_chat = data.get('enable_chat', False)
            session_id = data.get('session_id', None)
            think_level = data.get('think_level', 'minimal')

        if not prompt:
            return jsonify({'success': False, 'error': '请提供图片描述'}), 400

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
                image = Image.open(img_file)
                image_b64 = image_to_base64(image)
                parts.append({"inlineData": {"mimeType": "image/png", "data": image_b64}})
        parts.append({"text": prompt})

        return _parse_and_respond(prompt, aspect_ratio, resolution, use_search, enable_chat, session_id, parts, think_level)

    except ClientDisconnected:
        return jsonify({'success': False, 'error': '连接断开，请重试'}), 400
    except RequestEntityTooLarge:
        return jsonify({'success': False, 'error': '上传文件总大小超过100MB限制'}), 413
    except Exception as e:
        print(f'Error generating image: {str(e)}')
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print('=' * 60)
    print('Nanobanana Server - Configuration')
    print('=' * 60)
    print(f'Server: http://{SERVER_HOST}:{SERVER_PORT}')
    print(f'Config Source: config.json (environment variables DISABLED)')
    print()
    print('API Providers:')
    print(f'  Current: {CURRENT_PROVIDER.upper()}')
    if CURRENT_PROVIDER == 'vertex':
        print(f'    Provider: Vertex AI')
        print(f'    Endpoint: {API_ENDPOINT}')
        print(f'    Model: {MODEL_ID}')
        print(f'    Project ID: {PROJECT_ID}')
        print(f'    API Key: {API_KEY[:10]}...{API_KEY[-6:] if len(API_KEY) > 16 else ""}')
    else:
        print(f'    Provider: Google AI Studio')
        print(f'    Endpoint: {API_ENDPOINT}')
        print(f'    Model: {MODEL_ID}')
        print(f'    API Key: {API_KEY[:10]}...{API_KEY[-6:] if len(API_KEY) > 16 else ""}')
    print()
    # 显示备用 provider
    alt_provider = 'ai_studio' if CURRENT_PROVIDER == 'vertex' else 'vertex'
    if API_PROVIDERS.get(alt_provider, {}).get('key'):
        alt_name = 'Google AI Studio' if alt_provider == 'ai_studio' else 'Vertex AI'
        print(f'  Backup: {alt_provider.upper()} ({alt_name}) - Available')
    print('=' * 60)
    print(f'Starting server on http://{SERVER_HOST}:{SERVER_PORT}')
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=True)
