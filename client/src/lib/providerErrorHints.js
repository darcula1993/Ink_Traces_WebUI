// V24-W1-VIDEO-ERROR-20261121 AC3:
// Strict whitelist decoder for deterministic Provider parameter / config errors.
// Safety redlines (from FAILURE-CLASS-20261115 lessons):
// 1. NEVER guess or recommend "重新生成 / 重试" for unknown errors, async failures, timeouts or result_unknown.
// 2. ALWAYS return null for anything outside the deterministic whitelist; caller keeps raw error text viewable.
// 3. NEVER leak API keys, bearer tokens, signed query tokens, or unmasked Ark endpoint IDs (ep-...).

const NON_DETERMINISTIC_GUARD = /\b(?:result[_\s-]?unknown|poll\s+timeout|timed?\s*out|timeout|gateway\s+timeout|rate\s+limit|too\s+many\s+requests|internal\s+server\s+error|server\s+error|service\s+unavailable|temporarily\s+unavailable|bad\s+gateway|network\s+error|fetch\s+failed|socket\s+hang\s+up|getaddrinfo|connection\s+(?:reset|refused|aborted|closed|lost|dropped|error|timed?\s*out)|econnreset|econnrefused|econnaborted|etimedout|enotfound|ehostunreach|enetunreach|dns|ssl|tls|proxy|500|502|503|504|429)\b|轮询超时|结果未知|请求超时|连接超时|读超时|写超时|网络异常|网络错误|连接中断|服务暂不可用|暂时不可用/i

const SECRET_JSON_KEY_NAMES = 'api[_-]?key|x-api-key|access[_-]?key(?:[_-]?id)?|secret(?:[_-]?key)?|client[_-]?secret|authorization|auth[_-]?token|access[_-]?token|refresh[_-]?token|security[_-]?token|session[_-]?token|token|password|passwd|credential'
const SECRET_UNQUOTED_KEY_NAMES = 'api[_-]?key|x-api-key|access[_-]?key(?:[_-]?id)?|secret(?:[_-]?key)?|client[_-]?secret|authorization|auth[_-]?token|access[_-]?token|refresh[_-]?token|security[_-]?token|session[_-]?token|password|passwd|credential'
const SECRET_QUOTED_KV_RE = new RegExp(`(\\b(?:${SECRET_JSON_KEY_NAMES})["']?\\s*[:=]\\s*["'])[^"']+(["'])`, 'gi')
const SECRET_UNQUOTED_KV_RE = new RegExp(`(\\b(?:${SECRET_UNQUOTED_KEY_NAMES})\\s*[:=]\\s*)(?!["']|Bearer\\s+\\*{3}(?:$|[\\s"',;)&}])|\\*{3}(?:$|[\\s"',;)&}]))[^\\s"',;)&}]+`, 'gi')
const SECRET_QUERY_PARAM_RE = /([?&;](?:api[_-]?key|access[_-]?key(?:[_-]?id)?|secret(?:[_-]?key)?|token|auth[_-]?token|security[_-]?token|signature|sig|x-signature|x-tos-signature|x-tos-security-token|x-tos-credential|x-amz-signature|x-amz-security-token|x-amz-credential|x-goog-signature|x-goog-credential|awsaccesskeyid|ossaccesskeyid)=)[^&\s"'#)]+/gi

/**
 * Redact API keys, Bearer tokens, JSON/header secrets, signed URL query secrets, and unmasked Ark endpoint IDs (ep-...).
 * Safe to run on any user-facing error text before rendering or copying to clipboard.
 */
export function sanitizeErrorText(raw) {
  if (typeof raw !== 'string') return ''
  return raw
    // Authorization: Bearer <token> or standalone Bearer <token>
    .replace(/\b(Bearer\s+)[A-Za-z0-9._~+/=-]{6,}/gi, '$1***')
    // Query string secrets (TOS/S3/OSS/GCS signatures, security tokens, credentials, api_key, token)
    .replace(SECRET_QUERY_PARAM_RE, '$1***')
    // JSON / quoted key-value pairs: {"api_key": "<uuid>"}, {"token": "..."}, {"authorization": "..."}, {"secret": "..."}, {"password": "..."}
    .replace(SECRET_QUOTED_KV_RE, '$1***$2')
    // Unquoted key=value or header: value (e.g. api_key=..., x-api-key: ..., password=...)
    .replace(SECRET_UNQUOTED_KV_RE, '$1***')
    // Common key prefixes (sk-..., ak-...)
    .replace(/\b(sk|ak)-[A-Za-z0-9_-]{8,}\b/g, '$1-***')
    // Unmasked Ark endpoint IDs like ep-<id> (preserve already-masked ep-***)
    .replace(/\bep-(?!\*{3}(?:[^A-Za-z0-9_-]|$))[A-Za-z0-9][A-Za-z0-9_-]{3,}/gi, 'ep-***')
}

/**
 * Decode a raw Provider error string using a STRICT whitelist of deterministic parameter/config errors.
 *
 * @param {string} errorText
 * @param {object} [context]
 * @param {boolean} [context.resultUnknown=false]
 * @param {string}  [context.status='']
 * @param {string}  [context.failureCategory='']
 * @param {string}  [context.nodeType=''] - 'video' | 'image' | 'audio'
 * @param {string}  [context.ratio='']    - current effective ratio of the node
 * @param {object}  [context.params={}]   - node params (fallback for ratio)
 * @returns {null | {
 *   code: string,
 *   title: string,
 *   suggestion: string,
 *   targetField: 'ratio' | 'resolution' | 'model' | 'provider' | 'references',
 *   quickFix: null | { label: string, field: string, value: string, patch: Record<string, unknown> },
 * }}
 */
export function decodeProviderError(errorText, context = {}) {
  if (!errorText || typeof errorText !== 'string') return null
  const { resultUnknown = false, status = '', failureCategory = '', nodeType = '', ratio, params = {} } = context || {}

  // Hard safety bailout: never decode result_unknown, unknown status, or async timeout/5xx/rate-limit errors.
  if (resultUnknown === true || status === 'unknown' || failureCategory === 'result_unknown') return null
  const text = sanitizeErrorText(errorText).trim()
  if (!text || NON_DETERMINISTIC_GUARD.test(text)) return null

  const currentRatio = ratio ?? params?.ratio ?? '16:9'
  const canApplyAdaptive = nodeType !== 'image' && nodeType !== 'audio' && currentRatio !== 'adaptive'

  // 1. ratio must be adaptive / ratio is not valid
  if (/\bratio\b[^.\n]{0,80}\badaptive\b/i.test(text) || /\badaptive\b[^.\n]{0,60}\bratio\b/i.test(text)) {
    return {
      code: 'ratio_must_be_adaptive',
      title: '画幅需设为“自动匹配 (adaptive)”',
      suggestion: '该任务被识别为视频延长，需将画幅改为“自动匹配 (adaptive)”',
      targetField: 'ratio',
      quickFix: canApplyAdaptive
        ? { label: '一键改为自动匹配', field: 'ratio', value: 'adaptive', patch: { ratio: 'adaptive' } }
        : null,
    }
  }
  if (
    /\bratio\b[^.\n]{0,60}(?:is\s+not\s+valid|not\s+valid|invalid|not\s+supported|unsupported)/i.test(text) ||
    /(?:invalid|unsupported)\s+(?:parameter\s+)?(?:aspect[_\s-]?)?ratio\b/i.test(text)
  ) {
    return {
      code: 'ratio_invalid',
      title: '画幅参数不被当前模型支持',
      suggestion: '请将画幅调整为当前模型支持的选项（视频延长/续镜需选择“自动匹配 (adaptive)”）',
      targetField: 'ratio',
      quickFix: nodeType === 'video' && currentRatio !== 'adaptive'
        ? { label: '一键改为自动匹配', field: 'ratio', value: 'adaptive', patch: { ratio: 'adaptive' } }
        : null,
    }
  }

  // 2. Reference video duration or count exceeded
  if (
    /(?:reference\s+videos?|ref_videos?|video\s+references?|input\s+videos?|参考视频|视频参考)[^.\n]{0,80}(?:duration|length|too\s+long|exceed(?:s|ed)?\s+(?:the\s+)?(?:max|limit|allowed)?\s*duration|时长|超过.*秒|时长超限)/i.test(text) ||
    /(?:total\s+)?video\s+duration[^.\n]{0,60}(?:exceed|limit|max|too\s+long|out\s+of\s+range)/i.test(text) ||
    /(?:duration|时长)[^.\n]{0,60}(?:reference\s+videos?|ref_videos?|参考视频|视频参考)[^.\n]{0,40}(?:exceed|max|limit|too\s+long|超过|上限|超限)/i.test(text)
  ) {
    return {
      code: 'video_ref_duration_exceeded',
      title: '参考视频时长超出限制',
      suggestion: '请缩短参考视频时长或减少参考视频数量，以满足当前模型的参考时长上限',
      targetField: 'references',
      quickFix: null,
    }
  }
  if (
    /(?:reference\s+videos?|ref_videos?|video\s+references?|video\s+inputs?|参考视频|视频参考)[^.\n]{0,80}(?:count|number|at\s+most|max|exceed|too\s+many|limit|数量|最多|超过|上限)/i.test(text) ||
    /too\s+many\s+(?:reference\s+)?videos?\b/i.test(text)
  ) {
    return {
      code: 'video_ref_count_exceeded',
      title: '参考视频数量超出模型上限',
      suggestion: '请移除多余的视频参考素材，确保数量在当前模型允许范围内',
      targetField: 'references',
      quickFix: null,
    }
  }

  // 3. Reference image count exceeded
  if (
    /(?:reference\s+images?|ref_images?|image\s+references?|input\s+images?|参考图|图片参考)[^.\n]{0,80}(?:count|number|at\s+most|max|exceed|too\s+many|limit|数量|最多|超过|上限)/i.test(text) ||
    /too\s+many\s+(?:reference\s+)?images?\b/i.test(text) ||
    /\bimages?\s+(?:count|number)\s+(?:exceed|must\s+not\s+exceed|cannot\s+exceed)/i.test(text)
  ) {
    return {
      code: 'image_ref_count_exceeded',
      title: '参考图片数量超出模型上限',
      suggestion: '请移除多余的图片参考素材，确保参考图数量不超过当前接口与模型上限',
      targetField: 'references',
      quickFix: null,
    }
  }

  // 4. Unsupported resolution or model / endpoint
  if (
    /(?:resolution|分辨率)[^.\n]{0,60}(?:not\s+supported|unsupported|invalid|not\s+valid|不支持|无效)/i.test(text) ||
    /(?:unsupported|invalid)\s+(?:video\s+|image\s+)?resolution\b/i.test(text)
  ) {
    return {
      code: 'unsupported_resolution',
      title: '所选分辨率不受当前模型支持',
      suggestion: '请在输出参数中切换为当前模型支持的分辨率档位',
      targetField: 'resolution',
      quickFix: null,
    }
  }
  if (
    /(?:\bmodel\b|\bendpoint\b|模型|接入点)[^.\n]{0,60}(?:not\s+supported|unsupported|not\s+found|does\s+not\s+exist|invalid|disabled|unavailable|不支持|不存在|未开通|不可用)/i.test(text) ||
    /(?:unsupported|invalid|unknown)\s+(?:video\s+|image\s+|audio\s+)?model\b/i.test(text) ||
    /\b(?:ModelNotOpen|InvalidEndpointOrModel)\b/i.test(text)
  ) {
    return {
      code: 'unsupported_model',
      title: '所选模型或接入点不可用',
      suggestion: '请检查节点所选接口与模型，或在「接口管理」中核对接入点配置是否已开通',
      targetField: 'model',
      quickFix: null,
    }
  }

  // 5. API Key missing / invalid / disabled
  if (
    /(?:api[_\s-]?key|密钥)[^.\n]{0,60}(?:missing|empty|required|invalid|expired|disabled|revoked|unauthorized|not\s+configured|未配置|缺失|无效|停用|过期)/i.test(text) ||
    /(?:invalid|missing|expired|disabled|revoked)\s+api[_\s-]?key\b/i.test(text) ||
    /\b(?:AuthenticationError|InvalidApiKey)\b/i.test(text) ||
    /(?:请先配置.*(?:API\s*Key|密钥)|接口已停用)/i.test(text)
  ) {
    return {
      code: 'api_key_invalid',
      title: '接口密钥缺失、无效或已停用',
      suggestion: '请前往「接口管理」检查该配置的 API Key 是否有效并已启用，或切换至其他可用接口',
      targetField: 'provider',
      quickFix: null,
    }
  }

  return null
}
