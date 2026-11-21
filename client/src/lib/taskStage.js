// FIX-B2B-20261114 / VIDEO-SIGNAL-20261115 / V24-W3-STAGE-ETA-20261121:
// Stage wording and local historical P50 duration references for in-flight tasks.
//
// Video providers give no reliable percentage (Cupsy reports a fixed placeholder for
// minutes), so video nodes show the stage instead of a number. Never fabricate a
// percentage progress bar.
export const TASK_STAGES = Object.freeze(['排队', '生成', '下载写回'])
export const SERVER_STAGE_UPLOADING = 'uploading'
export const SERVER_STAGE_QUEUED = 'queued'
export const SERVER_STAGE_GENERATING = 'generating'
export const SERVER_STAGE_DOWNLOADING = 'downloading'
export const SERVER_STAGE_LABELS = Object.freeze({
  [SERVER_STAGE_UPLOADING]: '上传参考',
  [SERVER_STAGE_QUEUED]: '远端排队',
  [SERVER_STAGE_GENERATING]: '渲染生成',
  [SERVER_STAGE_DOWNLOADING]: '下载写回',
})
export const FINE_TASK_STAGES = Object.freeze(['上传参考', '渲染生成', '下载写回'])
const QUEUED_FINE_TASK_STAGES = Object.freeze(['远端排队', '渲染生成', '下载写回'])

// Index into TASK_STAGES for an in-flight status (and optional server stage), or -1.
export function taskStageIndex(status, stage = null) {
  if (['submitting', 'pending', 'preparing'].includes(status)) return 0
  if (status === 'processing') {
    if (stage === SERVER_STAGE_DOWNLOADING) return 2
    if (stage === SERVER_STAGE_UPLOADING || stage === SERVER_STAGE_QUEUED) return 0
    return 1
  }
  return -1
}

// Human-readable fine-grained stage label for an active task, or '' when terminal / none.
export function taskStageLabel(status, stage = null) {
  if (status === 'processing') {
    return typeof stage === 'string' && SERVER_STAGE_LABELS[stage] ? SERVER_STAGE_LABELS[stage] : ''
  }
  if (status === 'preparing') return SERVER_STAGE_LABELS[SERVER_STAGE_UPLOADING]
  if (status === 'pending') return SERVER_STAGE_LABELS[SERVER_STAGE_QUEUED]
  return ''
}

// Stepper model for CanvasNode: keeps legacy ['排队', '生成', '下载写回'] when no
// fine-grained stage is present, and switches to fine-grained labels when reported.
export function taskStageSteps(status, stage = null) {
  const index = taskStageIndex(status, stage)
  if (index < 0) return null
  if (status === 'processing' && typeof stage === 'string' && SERVER_STAGE_LABELS[stage]) {
    const steps = stage === SERVER_STAGE_QUEUED ? QUEUED_FINE_TASK_STAGES : FINE_TASK_STAGES
    return { steps, index, currentLabel: steps[index] }
  }
  if (status === 'preparing') {
    return { steps: FINE_TASK_STAGES, index: 0, currentLabel: FINE_TASK_STAGES[0] }
  }
  return { steps: TASK_STAGES, index, currentLabel: TASK_STAGES[index] }
}

// Appended after the status word (e.g. "生成中 · 完成后自动下载并写回画布"), so they never repeat it.
const HINTS = {
  pending: '服务商排队中',
  preparing: '正在上传参考素材',
  processing: '完成后自动下载并写回画布',
}
const PROCESSING_STAGE_HINTS = {
  [SERVER_STAGE_UPLOADING]: '正在上传参考素材',
  [SERVER_STAGE_QUEUED]: '服务商远端排队中',
  [SERVER_STAGE_GENERATING]: '正在渲染生成，完成后自动下载并写回画布',
  [SERVER_STAGE_DOWNLOADING]: '服务商已完成，正在下载并写回画布',
}
export const taskStageHint = (status, stage = null) =>
  status === 'processing' && typeof stage === 'string' && PROCESSING_STAGE_HINTS[stage]
    ? PROCESSING_STAGE_HINTS[stage]
    : HINTS[status] || ''

// A percentage is shown only for non-video nodes and only when the server reports 1–99.
export function taskProgressPercent(nodeType, progress) {
  if (nodeType === 'video') return null
  const value = Number(progress)
  return Number.isFinite(value) && value > 0 && value < 100 ? Math.round(value) : null
}

// Format local historical P25–P75 / P50 duration stat into a non-binding reference hint.
// Never returns a fake percentage; returns '' when there are no valid samples.
export function formatDurationHint(stat) {
  if (!stat || typeof stat !== 'object') return ''
  const sampleCount = Number(stat.sample_count)
  if (!Number.isFinite(sampleCount) || sampleCount <= 0) return ''
  const p50 = Number(stat.p50_seconds)
  if (!Number.isFinite(p50) || p50 <= 0) return ''
  const rawP25 = Number(stat.p25_seconds)
  const rawP75 = Number(stat.p75_seconds)
  const low = Number.isFinite(rawP25) && rawP25 > 0 ? Math.min(rawP25, p50) : p50
  const high = Number.isFinite(rawP75) && rawP75 > 0 ? Math.max(rawP75, p50) : p50

  if (high < 90) {
    const loSec = Math.max(1, Math.round(low))
    const hiSec = Math.max(loSec, Math.round(high))
    return loSec === hiSec
      ? `通常约 ${loSec} 秒（仅供参考）`
      : `通常约 ${loSec}–${hiSec} 秒（仅供参考）`
  }
  const loMin = Math.max(1, Math.round(low / 60))
  const hiMin = Math.max(loMin, Math.round(high / 60))
  return loMin === hiMin
    ? `通常约 ${loMin} 分钟（仅供参考）`
    : `通常约 ${loMin}–${hiMin} 分钟（仅供参考）`
}

const ENDPOINT_ID_RE = /(?:^|[^a-z0-9])ep-(?:m-)?[0-9]{6,}/i
const SAFE_MODEL_SLUG_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/

export function normalizeDurationModel(taskType, model = null, params = null) {
  const raw = String(model ?? params?.model ?? '').trim()
  const lower = raw.toLowerCase()
  const looksLikeEndpoint = !raw || lower.startsWith('ep-') || ENDPOINT_ID_RE.test(lower)
  const seedream55 = Boolean(params?.seedream55)

  if (taskType === 'image' || taskType === 'layer') {
    if (seedream55 || lower.includes('5-5') || lower.includes('5.5')) return 'seedream-5.5'
    if (lower.includes('5-0') || lower.includes('5.0') || lower.includes('seedream') || looksLikeEndpoint) {
      return 'seedream-5.0-pro'
    }
  } else if (taskType === 'video') {
    if (lower.includes('2.5-moderated') || lower.includes('2-5-moderated')) return 'seedance-2.5-moderated'
    if (lower.includes('seedance-2.5') || lower.includes('seedance-2-5') || lower.includes('2.5')) return 'seedance-2.5'
    if (lower.includes('seedance-2.0') || lower.includes('seedance-2-0') || lower.includes('2.0')) return 'seedance-2.0'
    if (looksLikeEndpoint) return null
  } else if (taskType === 'audio') {
    if (lower.includes('seed-audio') || lower.includes('audio-1.0') || lower.includes('audio-1-0') || !raw) {
      return 'seed-audio-1.0'
    }
    if (looksLikeEndpoint) return null
  }

  if (looksLikeEndpoint || lower.includes('://')) return null
  return SAFE_MODEL_SLUG_RE.test(lower) ? lower : null
}

export function lookupDurationStat(stats, taskType, model = null, params = null) {
  if (!stats || typeof stats !== 'object' || !taskType) return null
  const normalized = normalizeDurationModel(taskType, model, params)
  if (normalized) {
    const modelStat = stats.by_model?.[`${taskType}:${normalized}`]
    if (modelStat && Number(modelStat.sample_count) >= 2) return modelStat
  }
  const typeStat = stats.by_type?.[taskType]
  if (typeStat && Number(typeStat.sample_count) >= 1) return typeStat
  return null
}

const STATS_CACHE_TTL_MS = 60_000
let cachedStats = null
let cachedAt = 0
let inflightStats = null

export function resetDurationStatsCache() {
  cachedStats = null
  cachedAt = 0
  inflightStats = null
}

export function getCachedDurationStats() {
  return cachedStats
}

export function fetchDurationStats({ force = false, fetcher = null } = {}) {
  const now = Date.now()
  if (!force && cachedStats && now - cachedAt < STATS_CACHE_TTL_MS) {
    return Promise.resolve(cachedStats)
  }
  if (!force && inflightStats) return inflightStats
  const fn = fetcher || (typeof window !== 'undefined' && typeof globalThis.fetch === 'function' ? globalThis.fetch.bind(globalThis) : null)
  if (!fn) return Promise.resolve(cachedStats)
  inflightStats = Promise.resolve()
    .then(() => fn('/api/tasks/duration-stats', { credentials: 'same-origin' }))
    .then(res => (res && res.ok ? res.json() : null))
    .then(data => {
      if (data && data.success) {
        cachedStats = data
        cachedAt = Date.now()
      }
      return cachedStats
    })
    .catch(() => cachedStats)
    .finally(() => { inflightStats = null })
  return inflightStats
}
