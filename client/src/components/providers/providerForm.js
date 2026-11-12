export const KINDS = { image: '图像生成', video: '视频生成', audio: '音频生成' }
export const ADAPTERS = { ark: 'Ark', cupsy: 'Cupsy' }
export const adaptersFor = kind => kind === 'audio' ? ['cupsy'] : ['ark', 'cupsy']
const defaults = (kind, adapter) => ({
  endpoint: adapter === 'ark' ? 'https://ark.ap-southeast.bytepluses.com' : 'https://cupsy.io',
  model: kind === 'audio' ? 'seed-audio-1.0' : kind === 'video' ? adapter === 'cupsy' ? 'seedance-2.5' : '' : adapter === 'ark' ? 'dola-seedream-5-5-261028' : 'seedream-5.0-pro',
})
export const blankForm = (kind = 'image', adapter = 'ark') => ({ name: '', kind, adapter, enabled: true, is_default: false, settings: defaults(kind, adapter), api_key: '', clear_api_key: false })
export const profileForm = profile => ({ name: profile.name, kind: profile.kind, adapter: profile.adapter, enabled: profile.enabled, is_default: profile.is_default, settings: { ...profile.settings }, api_key: '', clear_api_key: false })
export const ADVANCED_NUMBERS = [
  ['request_timeout_seconds', '请求超时（秒）'],
  ['upload_timeout_seconds', '连接超时（秒）'],
  ['poll_timeout_seconds', '轮询请求超时（秒）'],
  ['download_timeout_seconds', '下载超时（秒）'],
  ['poll_interval_seconds', '查询间隔（秒）'],
  ['poll_max_attempts', '最多查询次数'],
]
export function payloadFor(form, revision) {
  const settings = { ...form.settings }
  for (const [key] of [...ADVANCED_NUMBERS, ['asset_token_ttl_seconds']]) if (key in settings) { if (settings[key] === '' || settings[key] == null) settings[key] = null; else settings[key] = Number(settings[key]) }
  const payload = { name: form.name.trim(), kind: form.kind, adapter: form.adapter, enabled: form.enabled, is_default: form.enabled && form.is_default, settings }
  if (revision != null) payload.revision = revision
  if (form.clear_api_key) payload.clear_api_key = true
  else if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  return payload
}
