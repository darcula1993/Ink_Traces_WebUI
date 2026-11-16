"""Server-side assembly of canvas generation requests (GROUP-RUN-20261115 A1).

A line-by-line port of the browser submission path so that a group run can build a
downstream node's request on the server after its upstream finished:

* client/src/lib/canvasReferences.js  resolveNodeInputs / resolveKeyframeRoles /
  canvasMentionItems / positionalMentionRebinds / referenceMentionIssues
* client/src/lib/canvasApi.js          getCanvasCapabilities / submitCanvasGeneration
  (everything up to, but not including, the POST)
* imageGenerationRules.js, videoGenerationRules.js, generationSettings.js (rules used there)

This module only assembles. It never creates a task, never posts to a generation route and
never calls a Provider. Parity with the browser is pinned by the shared cases in
server/tests/data/canvas_submit_cases.json, run by both test_canvas_submit.py and
client/tests/canvasSubmitParity.test.js. A rule change on either side must update both.

Public API (for A2 / B stage callers):

    capabilities_from_sources(image_info, video_info, audio_info, profiles) -> dict
    live_capabilities() -> dict                      # needs an active Flask request context
    resolve_node_inputs(node, nodes, edges) -> dict  # {'assets', 'prompt', 'issues', 'frames'}
    build_request(workflow, node_id, capabilities, *, read_metadata=None, resolve_file=None) -> dict
    assemble(workflow_id, node_id, capabilities) -> dict
    form_fields(fields) -> dict[str, str]            # multipart values, JS String() semantics
    CanvasSubmitError(ValueError)                    # .message is the same Chinese reason the browser shows
"""
import math
import re

CUPSY_AUDIO_MODEL = 'seed-audio-1.0'
SEEDANCE_20, SEEDANCE_25, SEEDANCE_25_MODERATED = 'seedance-2.0', 'seedance-2.5', 'seedance-2.5-moderated'
VIDEO_MODEL_LABELS = {SEEDANCE_20: 'Seedance 2.0', SEEDANCE_25: 'Seedance 2.5',
                      SEEDANCE_25_MODERATED: 'Seedance 2.5 Enhanced Moderation'}
VIDEO_MODEL_CAPABILITIES = {
    SEEDANCE_20: {'resolutions': ['480p', '720p', '1080p'], 'minDuration': 4, 'maxDuration': 15,
                  'maxRefImages': 9, 'maxRefVideos': 3, 'maxRefAudios': 3},
    SEEDANCE_25: {'resolutions': ['480p', '720p', '1080p'], 'minDuration': 4, 'maxDuration': 30,
                  'maxRefImages': 30, 'maxRefVideos': 10, 'maxRefAudios': 10},
}
VIDEO_RATIOS = ['adaptive', '16:9', '4:3', '1:1', '3:4', '9:16', '21:9']
VIDEO_AUTO_DURATION = -1
SEEDREAM_MIN_PIXELS, SEEDREAM_MAX_PIXELS = 1280 * 720, 4_624_220
SEEDREAM_1K_RATIOS = ['1:1', '4:3', '3:4', '16:9', '9:16', '3:2', '2:3', '21:9']
IMAGE_RATIOS = {'ark': ['auto', *SEEDREAM_1K_RATIOS, 'custom'], 'cupsy': ['1:1', '4:3', '3:4', '16:9', '9:16', 'custom']}
SEEDREAM_55_MODELS = ('dola-seedream-5-5-261028', 'dola-seedream-5-5', 'seedream-5-5', 'seedream-5.5')
AUDIO_SPEAKERS = ['', 'vivi', 'mindy', 'kian', 'jess', 'opal']
AUDIO_OUTPUT_FORMATS = ['mp3', 'wav', 'ogg_opus']
AUDIO_SAMPLE_RATES = [8000, 16000, 24000, 32000, 44100, 48000]
CANVAS_AUDIO_DEFAULTS = {'speaker': '', 'output_format': 'mp3', 'sample_rate': 48000, 'enable_subtitle': True}
KIND_LABELS = {'image': '图片', 'video': '视频', 'audio': '音频'}
# JS \d is ASCII only; greedy digits as in referenceMedia.js.
REFERENCE_TOKEN = re.compile(r'@(图片|视频|音频)([1-9][0-9]*)')
ROUTES = {'image': '/api/generate', 'video': '/api/video/generate', 'audio': '/api/audio/generate'}

# String.prototype.trim(): WhiteSpace + LineTerminator (differs from str.strip()).
_JS_SPACE = '\t\n\v\f\r              ' \
            '    　﻿'
_JS_DECIMAL = re.compile(r'[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)')


class CanvasSubmitError(ValueError):
    """A request the browser would also refuse; message is shown to the user as is."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _invalid(message):
    raise CanvasSubmitError(message)


# ---------- JS value semantics ----------

def js_trim(value):
    return value.strip(_JS_SPACE)


def _truthy(value):
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0 and not (isinstance(value, float) and math.isnan(value))
    if isinstance(value, str):
        return value != ''
    return True


def _or(value, default):
    return value if _truthy(value) else default


def _coalesce(value, default):
    """JS `??`: only null/undefined fall back."""
    return default if value is None else value


def js_number(value):
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = js_trim(value)
        if text == '':
            return 0
        if _JS_DECIMAL.fullmatch(text):
            number = float(text)
            return int(number) if number.is_integer() else number
        for prefix, base in (('0x', 16), ('0o', 8), ('0b', 2)):
            if text[:2].lower() == prefix:
                try:
                    return int(text[2:], base)
                except ValueError:
                    return math.nan
        return math.nan
    return math.nan


def _is_integer(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and float(value).is_integer()


def js_string(value):
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if value is None:
        return 'null'
    if isinstance(value, float):
        if math.isnan(value):
            return 'NaN'
        if math.isinf(value):
            return 'Infinity' if value > 0 else '-Infinity'
        if value.is_integer():
            return str(int(value))
        return repr(value)
    return str(value)


def form_fields(fields):
    """Multipart text parts exactly as FormData.append(name, String(value)) produces them."""
    return {name: js_string(value) for name, value in fields.items() if value is not None}


def _utf16_length(text):
    return len(text.encode('utf-16-le')) // 2


def _get(mapping, key, default=None):
    return mapping.get(key, default) if isinstance(mapping, dict) else default


# ---------- canvasProviderSelection.js / getCanvasCapabilities ----------

def _video_label(model):
    return VIDEO_MODEL_LABELS.get(model, '' if model is None else str(model))


def capabilities_from_sources(image_info, video_info, audio_info, profiles):
    """Port of getCanvasCapabilities: the four GET payloads -> {kind: [provider option]}."""
    def available(info):
        return [(key, value) for key, value in (_get(info, 'providers') or {}).items() if _get(value, 'available')]
    image_providers = _get(image_info, 'providers') or {}
    video_providers = _get(video_info, 'providers') or {}
    legacy = {
        'image': [{'id': key, 'provider': key, 'name': f"{_get(p, 'name') or key}（原配置）", 'model': _get(p, 'model'),
                   'capability_model': _get(p, 'capability_model')} for key, p in available(image_info)],
        'video': [{'id': key, 'provider': key, 'name': f"{'BytePlus Ark' if key == 'ark' else 'Cupsy'}（原配置）",
                   'models': [{'id': m, 'name': _video_label(m)} for m in (_get(p, 'models') or [])]}
                  for key, p in available(video_info)],
        'audio': [{'id': key, 'provider': key, 'name': 'Cupsy（原配置）', 'model': _or((_get(p, 'models') or [None])[0], CUPSY_AUDIO_MODEL)}
                  for key, p in available(audio_info)],
    }
    saved = [p for p in (profiles or []) if _truthy(_get(p, 'enabled')) and _truthy(_get(p, 'has_api_key'))]
    saved.sort(key=lambda p: -int(bool(_get(p, 'is_default'))))  # stable, like Array.sort
    result = {}
    for kind in ('image', 'video', 'audio'):
        options = []
        for p in saved:
            if p.get('kind') != kind:
                continue
            adapter, settings = p.get('adapter'), p.get('settings') or {}
            model_setting = settings.get('model')
            ark = _get(image_providers, 'ark')
            option = {
                'id': f"profile:{p.get('id')}", 'provider': adapter, 'profile_id': p.get('id'), 'is_default': bool(p.get('is_default')),
                'name': f"{p.get('name')}{' · 默认' if p.get('is_default') else ''}", 'revision': p.get('revision'),
                'capability_model': _get(ark, 'capability_model') if adapter == 'ark' and model_setting == _get(ark, 'model') else model_setting,
            }
            if kind == 'video':
                option['model'] = _or(model_setting, SEEDANCE_25) if adapter == 'cupsy' else SEEDANCE_20
                models = _get(_get(video_providers, adapter), 'models') or (
                    [SEEDANCE_25, SEEDANCE_25_MODERATED] if adapter == 'cupsy' else [SEEDANCE_20, SEEDANCE_25])
                option['models'] = [{'id': m, 'name': _video_label(m)} for m in models]
            else:
                option['model'] = _or(model_setting, CUPSY_AUDIO_MODEL if kind == 'audio' else _get(_get(image_providers, adapter), 'model'))
            options.append(option)
        result[kind] = options + legacy[kind]
    return result


def live_capabilities():
    """The same capabilities the browser reads, from the running app. Needs a request context
    (the provider views read the session); B stage calls it inside its submission context."""
    import app
    import provider_profiles
    return capabilities_from_sources(app.get_provider().get_json(), app.get_video_provider_info().get_json(),
                                     app.get_audio_provider_info().get_json(), provider_profiles.list_profiles())


def _selection_key(choice):
    return f"{choice.get('provider')}:{choice.get('profile_id') or ''}" if choice else 'none'


def selected_provider(capabilities, choice, kind):
    if not choice:
        return None
    for option in _get(capabilities, kind) or []:
        if option.get('provider') == choice.get('provider') and (option.get('profile_id') or None) == (choice.get('profile_id') or None):
            return option
    return None


# ---------- canvasReferences.js ----------

def media_kind(node):
    if not node:
        return None
    return _get(node.get('asset'), 'kind') if node.get('type') == 'asset' else node.get('type')


def can_connect(source, target):
    if not source or not target or source.get('id') == target.get('id') or target.get('type') not in ('image', 'video', 'audio'):
        return False
    kind = media_kind(source)
    if kind == 'text':
        return True
    return kind in {'image': ['image'], 'video': ['image', 'video', 'audio'], 'audio': ['image', 'audio']}.get(target.get('type'), [])


def resolve_keyframe_roles(node, assets):
    if node.get('type') != 'video' or _get(node.get('params'), 'video_mode') != 'keyframe':
        return {'first': None, 'last': None, 'issues': []}
    images, issues = [a for a in assets if a.get('kind') == 'image'], []
    if any(a.get('kind') != 'image' for a in assets):
        issues.append('首尾帧模式只接受图片，请移除视频和音频参考')
    if not images:
        issues.append('首尾帧模式请接入一张首帧图片；纯文本生成请选择全能参考')
    if len(images) > 2:
        issues.append('首尾帧模式最多接入两张图片')
    return {'first': images[0] if images else None, 'last': images[1] if len(images) > 1 else None, 'issues': issues}


def reference_tokens(text):
    return list(dict.fromkeys(match.group(0) for match in REFERENCE_TOKEN.finditer(text or '')))


def canvas_mention_items(node, assets):
    """token -> asset id, in the order the browser numbers @图片N/@视频N/@音频N."""
    frames = resolve_keyframe_roles(node, assets)
    keyframe = node.get('type') == 'video' and _get(node.get('params'), 'video_mode') == 'keyframe'
    ordered = [a for a in (frames['first'], frames['last']) if a] if keyframe else assets
    counts, items = {'image': 0, 'video': 0, 'audio': 0}, []
    for asset in ordered:
        kind = asset.get('kind')
        if kind in counts:
            counts[kind] += 1
            items.append({'token': f'@{KIND_LABELS[kind]}{counts[kind]}', 'assetId': asset.get('id')})
    return items


def _mentions(node, mentions):
    return mentions if isinstance(mentions, dict) else {}


def positional_mention_rebinds(node, assets, mentions, text):
    items = canvas_mention_items(node, assets)
    current = {item['token']: item for item in items}
    ids = {a.get('id') for a in assets}
    mentions = _mentions(node, mentions)
    used = {value for value in mentions.values() if value in ids}
    rebinds = []
    for token in reference_tokens(text):
        bound, target = mentions.get(token), current.get(token)
        if not _truthy(bound) or bound in ids or not target or target['assetId'] in used:
            continue
        used.add(target['assetId'])
        rebinds.append({'token': token, 'from': bound, 'to': target['assetId']})
    return rebinds


def reference_mention_issues(node, assets, upstream_text=''):
    current = {item['token']: item['assetId'] for item in canvas_mention_items(node, assets)}
    ids = {a.get('id') for a in assets}
    mentions = _mentions(node, node.get('referenceMentions'))
    text = f"{upstream_text}\n{node.get('text') or ''}"
    positional = {item['token'] for item in positional_mention_rebinds(node, assets, node.get('referenceMentions'), text)}
    issues = []
    for token in reference_tokens(text):
        bound = mentions.get(token)
        if token in positional:
            continue
        if _truthy(bound) and bound not in ids:
            issues.append(f'提及 {token} 的素材已移除，请删除该提及后重新选择素材')
        elif _truthy(bound) and current.get(token) != bound:
            issues.append(f'提及 {token} 的编号已变化，请调整或移除该提及后重新选择')
        elif token not in current:
            issues.append(f'提及 {token} 没有对应素材，请删除或重新选择')
    return issues


def resolve_node_inputs(node, nodes, edges):
    by_id = {item.get('id'): item for item in nodes}
    assets, texts, issues = [], [], []
    for edge in edges:
        if edge.get('target') != node.get('id'):
            continue
        source = by_id.get(edge.get('source'))
        if not can_connect(source, node):
            issues.append('连接的上游节点不存在或类型不兼容')
            continue
        if source.get('type') == 'text':
            text = js_trim(source['text']) if isinstance(source.get('text'), str) else ''
            if text:
                texts.append(text)
            continue
        if not source.get('asset'):
            title = source.get('title')
            issues.append(f"请先为“{'undefined' if title is None else title}”生成或选择一个结果")
            continue
        assets.append(source['asset'])
    assets.extend(node.get('referenceAssets') or [])
    unique = {}
    for asset in assets:  # Map semantics: first position, last value
        unique[asset.get('id')] = asset
    rank = {asset_id: index for index, asset_id in enumerate(node.get('referenceOrder') or [])}
    ordered = sorted(unique.values(), key=lambda a: rank.get(a.get('id'), math.inf))
    frames = resolve_keyframe_roles(node, ordered)
    own = js_trim(node['text']) if isinstance(node.get('text'), str) else ''
    prompt = '\n\n'.join(item for item in [*texts, own] if item)
    return {'assets': ordered, 'prompt': prompt, 'frames': frames,
            'issues': [*issues, *frames['issues'], *reference_mention_issues(node, ordered, '\n'.join(texts))]}


# ---------- imageGenerationRules.js ----------

def is_seedream55(model):
    return model in SEEDREAM_55_MODELS


def _image_capabilities(provider, model=None):
    return {'ratios': IMAGE_RATIOS.get(provider, []),
            'resolutions': ['1K', '1.5K', '2K'] if provider == 'ark' and is_seedream55(model) else ['1K', '2K'],
            'formats': ['png', 'jpeg'], 'custom': provider in ('ark', 'cupsy'), 'maxReferences': 10}


def _image_effective(params):
    defaults = {'ratio': '1:1', 'resolution': '1K', 'custom_width': 1024, 'custom_height': 1024, 'lock_aspect_ratio': False,
                'output_format': 'png', 'background': 'default', 'watermark': False}
    return {**defaults, **params, 'ratio': _or(params.get('ratio'), '1:1'), 'resolution': _or(params.get('resolution'), '1K')}


def validate_custom_size(width_value, height_value):
    width, height = js_number(_custom(width_value)), js_number(_custom(height_value))
    if not _is_integer(width) or not _is_integer(height) or width <= 0 or height <= 0:
        return '宽度和高度必须是正整数'
    if width % 16 != 0 or height % 16 != 0:
        return '宽度和高度必须是 16 的倍数'
    pixels = width * height
    if pixels < SEEDREAM_MIN_PIXELS or pixels > SEEDREAM_MAX_PIXELS:
        return '总像素必须在 921600 到 4624220 之间'
    ratio = width / height
    if ratio < 1 / 16 or ratio > 16:
        return '宽高比必须在 1:16 到 16:1 之间'
    return ''


_MISSING = object()


def _custom(value):
    return math.nan if value is _MISSING else value


def image_parameter_issues(provider, params, references, model):
    if provider not in IMAGE_RATIOS:
        return ['请选择可用的图片接口']
    p, spec, issues = _image_effective(params), _image_capabilities(provider, model), []
    if p['ratio'] not in spec['ratios']:
        issues.append(f"当前接口不支持画幅 {js_string(p['ratio'])}")
    if p['ratio'] == 'custom' and spec['custom']:
        issue = validate_custom_size(params.get('custom_width', _MISSING), params.get('custom_height', _MISSING))
        if issue:
            issues.append(issue)
    elif p['resolution'] not in spec['resolutions']:
        issues.append(f"当前接口不支持分辨率 {js_string(p['resolution'])}")
    if p['output_format'] not in spec['formats']:
        issues.append(f"当前接口不支持 {js_string(p['output_format'])} 格式")
    modern = provider == 'ark' and is_seedream55(model)
    if p['background'] not in (['default', 'auto', 'transparent', 'opaque'] if modern else ['default', 'transparent', 'opaque']):
        issues.append('背景设置无效')
    if not isinstance(p['watermark'], bool):
        issues.append('水印设置必须为布尔值')
    if p['background'] != 'default':
        if provider != 'ark':
            issues.append('背景控制仅支持 Ark')
        elif not is_seedream55(model) and len(references) != 1:
            issues.append('背景控制需要且只能使用一张带 Alpha 通道的参考图')
        elif not is_seedream55(model) and _get(references[0], 'has_alpha') is not True:
            issues.append('正在读取参考图片 Alpha 信息' if _truthy(references[0].get('metadataLoading'))
                          else '参考图片没有可确认的 Alpha 通道，请更换参考或使用默认背景')
        if p['background'] == 'transparent' and p['output_format'] != 'png':
            issues.append('透明背景必须使用 PNG 格式')
    if len(references) > spec['maxReferences']:
        issues.append(f"当前接口最多支持 {spec['maxReferences']} 张参考图")
    return list(dict.fromkeys(issues))


def image_request_fields(provider, params, model):
    p = _image_effective(params)
    custom = p['ratio'] == 'custom' and _image_capabilities(provider)['custom']
    fields = {'aspect_ratio': p['ratio']}
    fields.update({'custom_width': p['custom_width'], 'custom_height': p['custom_height']} if custom else {'resolution': p['resolution']})
    fields.update(output_format=p['output_format'], background=p['background'], watermark=p['watermark'])
    if _truthy(model):
        fields['model'] = model
    return fields


# ---------- videoGenerationRules.js ----------

def video_capabilities(model):
    return VIDEO_MODEL_CAPABILITIES.get(SEEDANCE_25 if model == SEEDANCE_25_MODERATED else model)


def video_parameter_error(model, duration, resolution, ratio):
    spec = video_capabilities(model)
    if not spec:
        return '当前视频模型能力未知，请选择受支持的模型'
    seconds = js_number(duration)
    if not _is_integer(seconds) or (seconds != VIDEO_AUTO_DURATION and (seconds < spec['minDuration'] or seconds > spec['maxDuration'])):
        return f"视频时长应为 {spec['minDuration']}–{spec['maxDuration']} 秒的整数或 Auto"
    if resolution not in spec['resolutions']:
        return '所选视频分辨率不受支持'
    if ratio not in VIDEO_RATIOS:
        return '所选视频画幅不受支持'
    return ''


# ---------- generationSettings.js (audio) ----------

def canvas_audio_params(params):
    return {key: _coalesce(params.get(key), default) for key, default in CANVAS_AUDIO_DEFAULTS.items()}


def _strict_in(value, choices):
    """Array.includes (===) for primitives: a bool never equals a number, a str never a number."""
    def same(a, b):
        if isinstance(a, bool) or isinstance(b, bool):
            return type(a) is type(b) and a == b
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a == b
        return type(a) is type(b) and a == b
    return any(same(value, choice) for choice in choices)


def canvas_audio_issue(params, image_count, audio_count):
    audio = canvas_audio_params(params)
    if not _strict_in(audio['speaker'], AUDIO_SPEAKERS):
        return '不支持的预设声线，请重新选择'
    if not _strict_in(audio['output_format'], AUDIO_OUTPUT_FORMATS):
        return '不支持的音频格式，请重新选择'
    if not _strict_in(audio['sample_rate'], AUDIO_SAMPLE_RATES):
        return '不支持的采样率，请重新选择'
    if not isinstance(audio['enable_subtitle'], bool):
        return '字幕开关无效，请重新设置'
    if _truthy(audio['speaker']) and image_count:
        return '预设声线不能与图片参考同时使用：请改为“模型自动”或移除图片参考'
    if _truthy(audio['speaker']) and audio_count > 2:
        return '使用预设声线时最多再接入 2 段音频参考'
    return None


# ---------- canvasApi.js submitCanvasGeneration (without the POST) ----------

def _reference_field(node_type, kind):
    if node_type == 'image':
        return 'images'
    if node_type == 'audio':
        return 'references'
    return {'image': 'ref_images', 'video': 'ref_videos', 'audio': 'ref_audios'}.get(kind)


def build_request(workflow, node_id, capabilities, *, read_metadata=None, resolve_file=None):
    """Assemble one node's generation request from a saved workflow, without submitting.

    workflow: {'id', 'revision', 'document': {'nodes', 'edges', ...}} as canvas_store.workflow returns.
    capabilities: capabilities_from_sources()/live_capabilities() output.
    read_metadata(asset) -> dict with 'has_alpha'; raise to signal an unreadable image.
    resolve_file(asset) -> opaque file handle (e.g. a Path); raise to signal an unreadable reference.

    Returns {'path', 'fields', 'files': [{'field', 'asset_id', 'kind', 'filename', 'file'}], 'multipart'}.
    `fields` keep JSON types (the JSON body when there are no files); use form_fields() for multipart.
    Raises CanvasSubmitError with the browser's message when the browser would refuse.
    """
    workflow_id = workflow['id']
    document = workflow.get('document') or {}
    nodes, edges = document.get('nodes') or [], document.get('edges') or []
    node = next((item for item in nodes if item.get('id') == node_id), None)
    if node is None:
        _invalid('节点已不存在或类型已改变，请重新载入画布')
    inputs = resolve_node_inputs(node, nodes, edges)
    if inputs['issues']:
        _invalid(inputs['issues'][0])
    prompt, assets, frames = inputs['prompt'], inputs['assets'], inputs['frames']
    if not prompt:
        _invalid('请填写生成提示词')
    if capabilities is None:
        _invalid('无法读取生成服务配置，尚未提交生成')
    params = node.get('params') or {}
    if not node.get('providerSelection'):
        _invalid('请先为节点选择接口')
    provider = selected_provider(capabilities, node.get('providerSelection'), node.get('type'))
    if not provider:
        _invalid('节点所选接口已停用或不可用，请重新选择')
    images = [a for a in assets if a.get('kind') == 'image']
    videos = [a for a in assets if a.get('kind') == 'video']
    audios = [a for a in assets if a.get('kind') == 'audio']
    if any(a.get('kind') not in ('image', 'video', 'audio') for a in assets):
        _invalid('不支持的参考素材类型')
    adapter = _or(provider.get('provider'), provider.get('id'))
    fields = {'prompt': prompt, 'canvas_workflow_id': workflow_id, 'canvas_node_id': node['id']}
    if _truthy(node.get('title')):
        fields['result_name'] = js_string(node['title'])
    fields.update(canvas_workflow_revision=workflow['revision'], provider=adapter)
    if _truthy(provider.get('profile_id')):
        fields['profile_id'] = provider['profile_id']
    node_type = node.get('type')
    capability_model = _or(provider.get('capability_model'), provider.get('model'))
    if node_type == 'image':
        if videos or audios:
            _invalid('图像生成只接受图片参考；请调整素材或素材组')
        references = images
        if _truthy(params.get('background')) and params.get('background') != 'default' and adapter == 'ark' \
                and not is_seedream55(capability_model) and len(images) == 1:
            try:
                metadata = read_metadata(images[0]) if read_metadata else None
                if not isinstance(metadata, dict):
                    raise ValueError('metadata')
            except Exception:
                _invalid('无法读取参考图片 Alpha 信息，尚未提交生成')
            references = [{**images[0], **metadata}]
        issues = image_parameter_issues(adapter, params, references, capability_model)
        if issues:
            _invalid('；'.join(issues))
        fields.update(image_request_fields(adapter, params, provider.get('model')))
    elif node_type == 'video':
        if 'generate_audio' in params and not isinstance(params['generate_audio'], bool):
            _invalid('输出音频必须是布尔值，请重新设置')
        models = provider.get('models') or []
        model = _or(params.get('model'), _or(models[0].get('id') if models else None, ''))
        if not any(m.get('id') == model for m in models):
            _invalid('当前服务不支持所选视频模型')
        spec = video_capabilities(model)
        locked = model in (SEEDANCE_25, SEEDANCE_25_MODERATED) and params.get('video_mode') == 'keyframe' and bool(images)
        ratio = 'adaptive' if locked else _or(params.get('ratio'), '16:9')
        resolution = _or(params.get('resolution'), '720p')
        error = video_parameter_error(model, _coalesce(params.get('duration'), 5), resolution, ratio)
        if error:
            _invalid(error)
        duration = js_number(_coalesce(params.get('duration'), 5))
        if len(images) > spec['maxRefImages'] or len(videos) > spec['maxRefVideos'] or len(audios) > spec['maxRefAudios']:
            _invalid('参考素材数量超过所选视频模型上限')
        if model == SEEDANCE_20 and audios and not images and not videos:
            _invalid('Seedance 2.0 使用音频参考时还需要图片或视频')
        fields.update(model=model, ratio=ratio, resolution=resolution, duration=duration,
                      video_mode=_or(params.get('video_mode'), 'reference'),
                      generate_audio=_coalesce(params.get('generate_audio'), True), output_format='mp4')
        if fields['video_mode'] not in ('reference', 'keyframe'):
            _invalid('不支持的视频模式')
        if adapter == 'cupsy' and fields['video_mode'] == 'reference':
            fields['omni_reference_task_type'] = _or(params.get('omni_reference_task_type'), 'auto')
            if fields['omni_reference_task_type'] not in ('auto', 'reference', 'edit', 'extend'):
                _invalid('不支持的任务类型')
    elif node_type == 'audio':
        if videos or (images and audios) or len(images) > 1 or len(audios) > 3:
            _invalid('音频参考支持 1 张图片或最多 3 段音频，不能混用；请调整素材组')
        if _utf16_length(prompt) > 3000:
            _invalid('音频提示词不能超过 3000 个字符')
        audio = canvas_audio_params(params)
        issue = canvas_audio_issue(params, len(images), len(audios))
        if issue:
            _invalid(issue)
        fields.update(model=provider.get('model'), output_format=audio['output_format'], sample_rate=audio['sample_rate'],
                      enable_subtitle=audio['enable_subtitle'],
                      reference_mode='image' if images else 'audio' if audios or _truthy(audio['speaker']) else 'none')
        if _truthy(audio['speaker']):
            fields['speaker'] = audio['speaker']
    else:
        _invalid('该节点不支持生成')

    # LIBRARY-GLOBAL-20261116 S2: references come from the global library (/api/canvas/media/<id>);
    # legacy canvas copies of this canvas stay accepted until migrated.
    from canvas_media_refs import ReferenceDeleted, is_reference_url
    handles = []
    for asset in assets:
        if not is_reference_url(workflow_id, asset.get('url')) or asset.get('kind') not in ('image', 'video', 'audio'):
            _invalid('参考素材必须先保存到当前画布')
        try:
            handle = resolve_file(asset) if resolve_file else None
        except ReferenceDeleted:
            _invalid(f"参考素材“{_or(asset.get('name'), asset.get('id'))}”已从素材库删除，尚未提交生成")
        except Exception:
            _invalid(f"无法读取参考素材“{_or(asset.get('name'), asset.get('id'))}”，尚未提交生成")
        handles.append((asset, handle))
    files = []
    keyframe = node_type == 'video' and fields.get('video_mode') == 'keyframe'
    for asset, handle in handles:
        if keyframe:
            for role, name in (('first', 'image'), ('last', 'last_image')):
                if _get(frames[role], 'id') == asset.get('id'):
                    files.append({'field': name, 'asset_id': asset.get('id'), 'kind': asset.get('kind'),
                                  'filename': _or(asset.get('name'), 'frame.png'), 'file': handle})
            continue
        extension = {'image': 'png', 'video': 'mp4'}.get(asset.get('kind'), 'wav')
        files.append({'field': _reference_field(node_type, asset.get('kind')), 'asset_id': asset.get('id'), 'kind': asset.get('kind'),
                      'filename': _or(asset.get('name'), f'reference.{extension}'), 'file': handle})
    # The browser switches to multipart whenever any reference exists, even if (keyframe) none is appended.
    return {'path': ROUTES[node_type], 'fields': fields, 'files': files, 'multipart': bool(handles)}


def assemble(workflow_id, node_id, capabilities):
    """build_request against the saved workflow and canvas files on disk (still no submission).

    Each `files[i]['file']` is the Path of the persisted canvas asset; open it in binary mode
    and stream it when submitting. Raises CanvasSubmitError (browser message) or
    canvas_store.CanvasError (workflow missing, 404) like the browser's workflow fetch.
    """
    import canvas_media_refs
    import canvas_store as store
    from canvas_image_params import _metadata

    saved = store.workflow(workflow_id)

    def resolve_file(asset):
        return canvas_media_refs.reference_of(workflow_id, asset)[0]

    def read_metadata(asset):
        path, mime_type, kind = canvas_media_refs.reference_of(workflow_id, asset)
        if kind != 'image':
            raise ValueError('not an image')
        stat = path.stat()
        return {**_metadata(str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size), 'mime_type': mime_type}

    return build_request({'id': workflow_id, 'revision': saved['revision'], 'document': saved['document']}, node_id,
                         capabilities, read_metadata=read_metadata, resolve_file=resolve_file)
