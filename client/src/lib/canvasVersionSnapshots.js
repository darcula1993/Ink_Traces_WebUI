// VERSION-SNAPSHOT-20261123: pure helpers for per-version generation snapshots
// (prompt + params + providerSelection) on canvas generation nodes.
import { videoModelLabel } from './generationSettings.js'

export const GENERATION_TYPES = new Set(['image', 'video', 'audio'])

export const MAX_VERSION_SNAPSHOTS = 100
export const MAX_CREATED_AT_LENGTH = 40

export const LEGACY_PARAM_KEYS = new Set([
  'provider',
  'profile_id',
  'profile_revision',
  'first_frame',
  'last_frame',
])

const HEX32_RE = /^[0-9a-f]{32}$/
const ADAPTERS = {
  image: new Set(['ark', 'cupsy']),
  video: new Set(['ark', 'cupsy']),
  audio: new Set(['cupsy']),
}
const AUDIO_SPEAKER_LABELS = {
  '': '模型自动',
  vivi: 'Vivi',
  mindy: 'Mindy',
  kian: 'Kian',
  jess: 'Jess',
  opal: 'Opal',
}
const AUDIO_FORMAT_LABELS = {
  mp3: 'MP3',
  wav: 'WAV',
  ogg_opus: 'OGG Opus',
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

/**
 * Return a clean shallow copy of `params`, omitting legacy interface/frame keys
 * and `undefined` values.
 */
export function sanitizeSnapshotParams(params) {
  if (!isPlainObject(params)) return {}
  const clean = {}
  for (const [key, value] of Object.entries(params)) {
    if (LEGACY_PARAM_KEYS.has(key) || value === undefined) continue
    clean[key] = value
  }
  return clean
}

/**
 * Normalize a snapshot's providerSelection into the persisted canvas node shape
 * `{ provider, profile_id }` accepted by server `validate_node_selection`.
 * Never substitutes another account when a profile is disabled or missing.
 */
export function sanitizeSnapshotProviderSelection(selection, nodeType = null, capabilities = null) {
  if (!isPlainObject(selection)) return null
  const allowed = nodeType && ADAPTERS[nodeType] ? ADAPTERS[nodeType] : null

  if (typeof selection.provider === 'string' && selection.provider.trim()) {
    const provider = selection.provider.trim()
    if (allowed && !allowed.has(provider)) return null
    const rawProfile = selection.profile_id
    if (rawProfile == null || rawProfile === '') return { provider, profile_id: null }
    if (typeof rawProfile === 'string' && HEX32_RE.test(rawProfile)) {
      return { provider, profile_id: rawProfile }
    }
    return null
  }

  // Tolerate `{ kind: 'profile', id: '<32-hex>' }` if capabilities can map it to an adapter.
  if (selection.kind === 'profile' && typeof selection.id === 'string' && HEX32_RE.test(selection.id)) {
    const options = nodeType && Array.isArray(capabilities?.[nodeType]) ? capabilities[nodeType] : []
    const match = options.find(option => option?.profile_id === selection.id)
    if (match?.provider && (!allowed || allowed.has(match.provider))) {
      return { provider: match.provider, profile_id: selection.id }
    }
    return null
  }

  if (typeof selection.id === 'string' && allowed && allowed.has(selection.id)) {
    return { provider: selection.id, profile_id: null }
  }

  return null
}

/**
 * Strip invalid or legacy fields from a version snapshot so it always passes
 * server document validation.
 */
export function sanitizeVersionSnapshot(snapshot, nodeType = null, capabilities = null) {
  if (!isPlainObject(snapshot)) return null
  const clean = {}
  if (typeof snapshot.text === 'string') {
    clean.text = snapshot.text.length > 50000 ? snapshot.text.slice(0, 50000) : snapshot.text
  }
  if (isPlainObject(snapshot.params)) {
    clean.params = sanitizeSnapshotParams(snapshot.params)
  }
  const providerSelection = sanitizeSnapshotProviderSelection(snapshot.providerSelection, nodeType, capabilities)
  if (providerSelection) {
    clean.providerSelection = providerSelection
  }
  if (Number.isInteger(snapshot.taskId) && snapshot.taskId > 0) {
    clean.taskId = snapshot.taskId
  }
  if (typeof snapshot.createdAt === 'string') {
    const trimmed = snapshot.createdAt.trim()
    if (trimmed.length >= 1 && trimmed.length <= MAX_CREATED_AT_LENGTH) {
      clean.createdAt = trimmed
    }
  }
  return Object.keys(clean).length > 0 ? clean : null
}

/**
 * Merge version snapshots onto `existing` while capping total entries at `limit`
 * (mirroring server `_merge_version_snapshots`):
 *   1. Merge `existing` + sanitized `additions`.
 *   2. If over `limit`, first evict orphan keys not in `candidates` and not in `additions`.
 *   3. If still over `limit`, evict oldest keys (preferring keys not in `additions`)
 *      until `Object.keys(merged).length <= limit`.
 */
export function mergeVersionSnapshots(existing, additions, candidates = [], limit = MAX_VERSION_SNAPSHOTS) {
  const maxEntries = Number.isInteger(limit) && limit >= 0 ? limit : MAX_VERSION_SNAPSHOTS
  const merged = isPlainObject(existing) ? { ...existing } : {}
  const addedKeys = new Set()
  if (isPlainObject(additions)) {
    for (const [key, value] of Object.entries(additions)) {
      if (!key) continue
      const clean = sanitizeVersionSnapshot(value)
      if (!clean) continue
      merged[key] = clean
      addedKeys.add(key)
    }
  }

  let keys = Object.keys(merged)
  if (keys.length <= maxEntries) return merged

  const candidateOrder = new Map()
  for (const item of Array.isArray(candidates) ? candidates : []) {
    const id = typeof item === 'string' ? item : item?.id
    if (id && !candidateOrder.has(id)) candidateOrder.set(id, candidateOrder.size)
  }

  // Pass 1: evict orphan keys (not in candidates and not newly added).
  for (const key of keys) {
    if (Object.keys(merged).length <= maxEntries) break
    if (!candidateOrder.has(key) && !addedKeys.has(key)) {
      delete merged[key]
    }
  }

  // Pass 2: if still over limit, evict oldest keys (preferring non-newly-added keys first).
  keys = Object.keys(merged)
  if (keys.length > maxEntries) {
    const insertionOrder = new Map(keys.map((key, index) => [key, index]))
    const compareAge = (a, b) => {
      const aCand = candidateOrder.has(a) ? candidateOrder.get(a) : -1
      const bCand = candidateOrder.has(b) ? candidateOrder.get(b) : -1
      if (aCand !== bCand) return aCand - bCand
      const aTime = typeof merged[a]?.createdAt === 'string' ? merged[a].createdAt : ''
      const bTime = typeof merged[b]?.createdAt === 'string' ? merged[b].createdAt : ''
      if (aTime && bTime && aTime !== bTime) return aTime < bTime ? -1 : 1
      return (insertionOrder.get(a) ?? 0) - (insertionOrder.get(b) ?? 0)
    }

    const evictOrder = [
      ...keys.filter(key => !addedKeys.has(key)).sort(compareAge),
      ...keys.filter(key => addedKeys.has(key)).sort(compareAge),
    ]
    let excess = keys.length - maxEntries
    for (const key of evictOrder) {
      if (excess <= 0) break
      delete merged[key]
      excess -= 1
    }
  }

  return merged
}

/**
 * Return unique 32-hex candidate IDs of a generation node that do not yet have
 * an entry in `node.versionSnapshots`. Returns `[]` for asset/text nodes.
 */
export function missingSnapshotIds(node) {
  if (!node || !GENERATION_TYPES.has(node.type)) return []
  const existing = isPlainObject(node.versionSnapshots) ? node.versionSnapshots : {}
  const seen = new Set()
  const missing = []
  for (const candidate of node.candidates || []) {
    const id = candidate?.id
    if (typeof id !== 'string' || !HEX32_RE.test(id) || seen.has(id)) continue
    seen.add(id)
    if (!existing[id]) missing.push(id)
  }
  return missing
}

/**
 * Build the patched generation node for switching to `asset`, automatically
 * restoring prompt (`text`), generation `params`, and `providerSelection` from
 * `snapshot` when available, while caching the sanitized snapshot on the node.
 */
export function applyVersionSnapshot(node, asset, snapshot, options = {}) {
  if (!node || !asset?.id) {
    return { node, restoredPrompt: false, restoredParams: false, restoredProvider: false, restoredAny: false }
  }
  const nextNode = {
    ...node,
    asset,
    selectedCandidateId: asset.id,
  }
  let restoredPrompt = false
  let restoredParams = false
  let restoredProvider = false

  if (GENERATION_TYPES.has(node.type) && isPlainObject(snapshot)) {
    const clean = sanitizeVersionSnapshot(snapshot, node.type, options.capabilities || null)
    if (clean) {
      if (typeof clean.text === 'string') {
        nextNode.text = clean.text
        restoredPrompt = true
      }
      if (isPlainObject(clean.params)) {
        if (Object.keys(clean.params).length > 0) {
          nextNode.params = clean.params
          restoredParams = true
        } else if (node.params?.model) {
          nextNode.params = { model: node.params.model }
        } else {
          nextNode.params = {}
        }
      }
      if (clean.providerSelection) {
        nextNode.providerSelection = clean.providerSelection
        restoredProvider = true
      }
      nextNode.versionSnapshots = mergeVersionSnapshots(
        node.versionSnapshots,
        { [asset.id]: clean },
        node.candidates,
      )
    }
  }

  return {
    node: nextNode,
    restoredPrompt,
    restoredParams,
    restoredProvider,
    restoredAny: restoredPrompt || restoredParams || restoredProvider,
  }
}

/**
 * Return up to 5 compact human-readable generation parameter chips for a version
 * snapshot (`image`, `video`, or `audio`).
 */
export function formatVersionParamChips(snapshot, nodeType) {
  const params = snapshot?.params
  if (!isPlainObject(params)) return []
  const chips = []
  const push = value => {
    if (!value || chips.length >= 5) return
    const text = String(value).trim()
    if (text && !chips.includes(text)) chips.push(text)
  }

  if (nodeType === 'image') {
    if (params.ratio === 'custom' && params.custom_width && params.custom_height) {
      push(`${params.custom_width}×${params.custom_height}`)
    } else if (typeof params.ratio === 'string' && params.ratio) {
      push(params.ratio === 'auto' ? 'Auto' : params.ratio)
    } else if (params.width && params.height) {
      push(`${params.width}×${params.height}`)
    } else if (typeof params.size === 'string' && params.size) {
      push(params.size)
    }

    if (params.ratio !== 'custom') {
      const res = params.resolution || params.image_size
      if (typeof res === 'string' && res) push(res)
    }

    if (typeof params.output_format === 'string' && params.output_format) {
      push(params.output_format.toUpperCase())
    }

    if (params.background === 'transparent') push('透明背景')
    else if (params.background === 'opaque') push('不透明背景')

    if (params.watermark === false) push('无水印')
    else if (params.watermark === true) push('含水印')
  } else if (nodeType === 'video') {
    if (typeof params.model === 'string' && params.model) {
      push(videoModelLabel(params.model))
    }
    if (params.video_mode === 'keyframe') push('首尾帧')
    else if (params.video_mode === 'reference') push('参考模式')

    if (typeof params.ratio === 'string' && params.ratio) {
      push(params.ratio === 'adaptive' ? '自动匹配' : params.ratio)
    }
    if (typeof params.resolution === 'string' && params.resolution) {
      push(params.resolution)
    }
    if (params.duration !== undefined && params.duration !== null && params.duration !== '') {
      const numeric = Number(params.duration)
      if (numeric === -1) push('自动时长')
      else if (Number.isFinite(numeric) && numeric > 0) push(`${numeric}s`)
      else push(String(params.duration))
    }
    if (params.generate_audio === true) push('含音频')
    else if (params.generate_audio === false) push('静音')
  } else if (nodeType === 'audio') {
    if (typeof params.output_format === 'string' && params.output_format) {
      push(AUDIO_FORMAT_LABELS[params.output_format] || params.output_format.toUpperCase())
    }
    if (params.sample_rate !== undefined && params.sample_rate !== null) {
      const rate = Number(params.sample_rate)
      if (Number.isFinite(rate) && rate > 0) push(`${Math.round(rate / 1000)}kHz`)
    }
    if (typeof params.speaker === 'string' && params.speaker.trim()) {
      push(AUDIO_SPEAKER_LABELS[params.speaker] || params.speaker.trim())
    }
    if (params.enable_subtitle === true) push('含字幕')
    else if (params.enable_subtitle === false) push('无字幕')
  }

  return chips.slice(0, 5)
}

/**
 * Collapse whitespace and cleanly truncate a snapshot's prompt for preview.
 */
export function formatVersionPromptPreview(snapshot, maxLen = 72) {
  if (typeof snapshot?.text !== 'string') return ''
  const collapsed = snapshot.text.replace(/\s+/g, ' ').trim()
  if (!collapsed) return ''
  const limit = Number.isInteger(maxLen) && maxLen > 1 ? maxLen : 72
  if (collapsed.length <= limit) return collapsed
  return `${collapsed.slice(0, limit - 1).trimEnd()}…`
}
