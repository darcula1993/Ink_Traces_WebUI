export const KINDS = { image: '图像生成', video: '视频生成', audio: '音频生成' }
export const ADAPTERS = { ark: 'Ark', cupsy: 'Cupsy' }
export const ARK_IMAGE_CAPABILITY_OPTIONS = [
  { value: '', label: '自动识别（按模型名 / 部署配置判断）' },
  { value: 'dola-seedream-5-5-261028', label: 'Seedream 5.5（支持 1.5K / 原生透明背景）' },
  { value: 'seedream-5-0-pro', label: 'Seedream 5.0 Pro' },
]
export const adaptersFor = kind => kind === 'audio' ? ['cupsy'] : ['ark', 'cupsy']
const defaults = (kind, adapter) => ({
  endpoint: adapter === 'ark' ? 'https://ark.ap-southeast.bytepluses.com' : 'https://cupsy.io',
  model: kind === 'audio' ? 'seed-audio-1.0' : kind === 'video' ? adapter === 'cupsy' ? 'seedance-2.5' : '' : adapter === 'ark' ? 'dola-seedream-5-5-261028' : 'seedream-5.0-pro',
  ...(kind === 'image' && adapter === 'ark' ? { capability_model: '' } : {}),
})
export const blankForm = (kind = 'image', adapter = 'ark') => ({ name: '', kind, adapter, enabled: true, is_default: false, settings: defaults(kind, adapter), api_key: '', clear_api_key: false, sync_adapter_api_key: false })
export const profileForm = profile => ({
  name: profile.name,
  kind: profile.kind,
  adapter: profile.adapter,
  enabled: profile.enabled,
  is_default: Boolean(profile.is_default),
  settings: {
    ...profile.settings,
    ...(profile.kind === 'image' && profile.adapter === 'ark' ? { capability_model: profile.settings?.capability_model || '' } : {}),
  },
  api_key: '',
  clear_api_key: false,
  sync_adapter_api_key: false,
})
export const ADVANCED_NUMBERS = [
  ['request_timeout_seconds', '请求超时（秒）'],
  ['upload_timeout_seconds', '连接超时（秒）'],
  ['poll_timeout_seconds', '轮询请求超时（秒）'],
  ['download_timeout_seconds', '下载超时（秒）'],
  ['poll_interval_seconds', '查询间隔（秒）'],
  ['poll_max_attempts', '最多查询次数'],
]
export function payloadFor(form, revision, includeSync = false) {
  const settings = { ...form.settings }
  if (form.kind === 'image' && form.adapter === 'ark') {
    settings.capability_model = typeof settings.capability_model === 'string' ? settings.capability_model.trim() : ''
  } else {
    delete settings.capability_model
  }
  for (const [key] of [...ADVANCED_NUMBERS, ['asset_token_ttl_seconds']]) if (key in settings) { if (settings[key] === '' || settings[key] == null) settings[key] = null; else settings[key] = Number(settings[key]) }
  const payload = { name: form.name.trim(), kind: form.kind, adapter: form.adapter, enabled: form.enabled, is_default: form.enabled && form.is_default, settings }
  if (revision != null) payload.revision = revision
  const hasKeyChange = Boolean(form.clear_api_key || form.api_key.trim())
  if (form.clear_api_key) payload.clear_api_key = true
  else if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  if (includeSync && form.sync_adapter_api_key && hasKeyChange) payload.sync_adapter_api_key = true
  return payload
}
