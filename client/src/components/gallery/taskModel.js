import { AlertTriangle, Ban, CheckCircle2, CircleHelp, Clock3, LoaderCircle } from 'lucide-react'

import { CLIENT_IN_FLIGHT_TASK_STATUSES, TASK_STATUS_LABELS } from '../../lib/taskStatus.js'

// Server in-flight statuses plus the task center's optimistic "submitting" placeholder.
export const ACTIVE_STATUSES = new Set(CLIENT_IN_FLIGHT_TASK_STATUSES)

export const TASK_PAGE_SIZE = 30

export const STATUS_BATCH_SIZE = 100

export const STATUS_POLL_DELAY = 4000

export function sameValue(left, right) {
  if (left === right) return true
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false
  const keys = Object.keys(left)
  return keys.length === Object.keys(right).length && keys.every(key =>
    Object.prototype.hasOwnProperty.call(right, key) && sameValue(left[key], right[key]))
}

export function mergeTaskStatus(task, update) {
  const next = { ...task }
  for (const field of ['status', 'progress', 'error', 'updated_at', 'deleted_at', 'provider']) {
    if (Object.prototype.hasOwnProperty.call(update, field)) next[field] = update[field]
  }
  if (update.result) next.result = { ...task.result, ...update.result }
  return sameValue(task, next) ? task : next
}

export const DEFAULT_GALLERY_PREFERENCES = { cardSize: 'standard', cardDetails: 'detailed', sort: 'newest' }

export const CARD_SIZE_OPTIONS = [
  { value: 'compact', label: '紧凑' },
  { value: 'standard', label: '标准' },
  { value: 'large', label: '大卡片' },
]

export const CARD_DETAIL_OPTIONS = [
  { value: 'clean', label: '纯预览' },
  { value: 'detailed', label: '显示详情' },
]

export const SORT_OPTIONS = [
  { value: 'newest', label: '最新创建' },
  { value: 'oldest', label: '最早创建' },
  { value: 'updated', label: '最近更新' },
]

export const DEFAULT_TASK_FILTERS = { status: '', provider: '', model: '', dateRange: '' }

export const STATUS_FILTER_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'succeeded', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
  { value: 'pending', label: TASK_STATUS_LABELS.pending },
  { value: 'preparing', label: '准备中' },
  { value: 'processing', label: '生成中' },
]

export const DATE_FILTER_OPTIONS = [
  { value: '', label: '全部时间' },
  { value: '1', label: '最近 24 小时' },
  { value: '7', label: '最近 7 天' },
  { value: '30', label: '最近 30 天' },
  { value: '90', label: '最近 90 天' },
]

export const GROUP_COLORS = ['green', 'cyan', 'blue', 'violet', 'rose', 'amber']

export const EMPTY_NAVIGATION = {
  position: 0,
  total: 0,
  previous_id: null,
  next_id: null,
  first_id: null,
  last_id: null,
}

export const STATUS = {
  succeeded: { label: '完成', icon: CheckCircle2, tone: 'text-nexus-green border-nexus-green/25 bg-nexus-green/10' },
  failed: { label: '失败', icon: AlertTriangle, tone: 'text-nexus-red border-nexus-red/25 bg-nexus-red/10' },
  processing: { label: '生成中', icon: LoaderCircle, spin: true, tone: 'text-nexus-green border-nexus-green/25 bg-nexus-green/10' },
  preparing: { label: '准备中', icon: LoaderCircle, spin: true, tone: 'text-nexus-cyan border-nexus-cyan/25 bg-nexus-cyan/10' },
  submitting: { label: '提交中', icon: LoaderCircle, spin: true, tone: 'text-nexus-cyan border-nexus-cyan/25 bg-nexus-cyan/10' },
  pending: { label: TASK_STATUS_LABELS.pending, icon: Clock3, tone: 'text-nexus-amber border-nexus-amber/25 bg-nexus-amber/10' },
  cancel_requested: { label: '正在取消', icon: LoaderCircle, spin: true, tone: 'text-nexus-amber border-nexus-amber/25 bg-nexus-amber/10' },
  cancelled: { label: '已取消', icon: Ban, tone: 'text-nexus-muted border-white/15 bg-white/5' },
}

// A failed task whose provider request may already have been accepted. It is
// shown separately from ordinary failures because a retry may bill twice.
export const RESULT_UNKNOWN_STATUS = { label: '结果未知，可能已计费', icon: CircleHelp, tone: 'text-nexus-amber border-nexus-amber/25 bg-nexus-amber/10' }

export function isResultUnknown(task) {
  return task?.result?.result_unknown === true || task?.resultUnknown === true
}

export function taskStatusInfo(item) {
  if (item?.status === 'failed' && item.resultUnknown) return RESULT_UNKNOWN_STATUS
  return STATUS[item?.status] || null
}

const UNKNOWN_REASONS = {
  worker_lost: 'Worker 异常退出，请求可能已发出',
  upstream_timeout: '供应商未在超时前返回结果',
  upload_timeout: '参考素材上传超时，请求可能已到达供应商',
}
export const resultUnknownReason = task => UNKNOWN_REASONS[task?.result?.error_type] || ''

export const RETRY_CONFIRM_CODE = 'result_unknown_confirm_required'
export const needsRetryConfirmation = error => error?.response?.status === 409 && error.response.data?.code === RETRY_CONFIRM_CODE

export function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value))
}

export function providerLabel(provider) {
  return ({ ark: 'BytePlus Ark', cupsy: 'Cupsy' })[provider] || provider
}

export function createdAfterForRange(value) {
  const days = Number(value)
  if (!Number.isFinite(days) || days <= 0) return ''
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString()
}

export function downloadExtension(item, url) {
  const configured = String(item.params?.output_format || '').toLowerCase()
  if (configured === 'jpeg') return 'jpg'
  if (['png', 'jpg', 'webp', 'gif'].includes(configured)) return configured
  const dataType = String(url || '').match(/^data:(?:image|video|audio)\/([a-z0-9.+-]+)/i)?.[1]
  if (dataType) return dataType === 'jpeg' ? 'jpg' : dataType.split('+')[0]
  const pathExtension = String(url || '').split('?', 1)[0].match(/\.([a-z0-9]{2,5})$/i)?.[1]
  if (pathExtension) return pathExtension.toLowerCase() === 'jpeg' ? 'jpg' : pathExtension.toLowerCase()
  return item.type === 'video' ? 'mp4' : item.type === 'audio' ? 'mp3' : 'png'
}

export function uniqueDownloadName(item, outputIndex, url, openedAt, original = false) {
  const identity = `task-${item.taskId}`
  const sourceDate = new Date(item.createdAt || openedAt)
  const safeDate = Number.isNaN(sourceDate.getTime()) ? openedAt : sourceDate
  const timestamp = safeDate.toISOString().replace(/\D/g, '').slice(0, 14)
  const output = item.type === 'image' ? `-output-${String(outputIndex + 1).padStart(2, '0')}` : ''
  return `ink-traces-${item.type}-${identity}-${timestamp}${output}${original ? '-original' : ''}.${downloadExtension(item, url)}`
}

export function taskDownloadUrl(item, url, original = false) {
  const prefix = `/api/tasks/${item.taskId}/file/`
  if (!item.taskId || !String(url || '').startsWith(prefix)) return url
  const filename = String(url).slice(prefix.length).split('?', 1)[0]
  return `/api/tasks/${item.taskId}/download/${encodeURIComponent(filename)}${original ? '?raw=1' : ''}`
}

export function taskDisplayUrl(taskId, url) {
  const value = String(url || '')
  const prefix = `/api/tasks/${taskId}/file/`
  if (!taskId || !value.startsWith(prefix) || !value.split('?', 1)[0].toLowerCase().endsWith('.png') || value.includes('png_info=1')) return url
  return `${value}${value.includes('?') ? '&' : '?'}png_info=1`
}

// FIX-B1-20261114: Provider result URLs may be pre-signed (credential/signature in
// the query). The detail view only names the remote host; the server already
// masks them, this is a defensive second layer for stale or mocked payloads.
export function remoteResultHost(url) {
  const value = String(url || '')
  if (!/^https?:\/\//i.test(value)) return ''
  try {
    return new URL(value).host
  } catch {
    return ''
  }
}

// LIBRARY-GLOBAL-20261116 S4b: generation results live in the global media library (生成历史).
// Provisional S3 contract (task log “S4b 实现”): task.result.media = [{output_url, media_id,
// status:'ok'|'deleted', kind, url?, thumbnail_url?, folder_id?, name?}], one entry per output that
// entered the library. Outputs without an entry are not in the library (legacy) and keep their
// output URL. A deleted entry hides that output (“结果已删除”); task records stay viewable.
const outputKey = url => String(url || '').split('?', 1)[0]

export function taskMediaEntries(result) {
  const list = Array.isArray(result?.media) ? result.media : []
  return list.filter(entry => entry && typeof entry === 'object' && typeof entry.media_id === 'string' && entry.media_id)
    .map(entry => ({
      outputUrl: entry.output_url || '',
      id: entry.media_id,
      deleted: entry.status === 'deleted',
      kind: entry.kind || '',
      url: entry.url || '',
      thumbnailUrl: entry.thumbnail_url || '',
      folderId: entry.folder_id === undefined ? undefined : (entry.folder_id || null),
      name: entry.name || '',
    }))
}

// Pair output URLs with library entries; library-only entries (no output URL left) are appended.
export function taskOutputs(urls, entries) {
  const byOutput = new Map(entries.filter(entry => entry.outputUrl).map(entry => [outputKey(entry.outputUrl), entry]))
  const used = new Set()
  const outputs = urls.filter(Boolean).map(url => {
    const media = byOutput.get(outputKey(url)) || null
    if (media) used.add(media)
    return { url, media, deleted: Boolean(media?.deleted) }
  })
  for (const media of entries) {
    if (used.has(media)) continue
    if (!media.deleted && !media.url) continue
    outputs.push({ url: media.deleted ? '' : media.url, media, deleted: media.deleted })
  }
  return outputs
}

export function serverItem(task) {
  const result = task.result || {}
  const params = task.params || {}
  const entries = taskMediaEntries(result)
  const rawLayerUrls = task.type === 'layer'
    ? [...new Set([
        ...(result.local_images || []),
        ...(result.base_image ? [result.base_image] : []),
        ...(Array.isArray(result.layers) ? result.layers.map(layer => layer?.local_url) : []),
      ].filter(Boolean))]
    : []
  const imageOutputs = task.type === 'image' || !task.type
    ? taskOutputs((result.local_images || []).map(url => taskDisplayUrl(task.id, url)), entries.filter(entry => !entry.kind || entry.kind === 'image'))
    : task.type === 'layer'
      ? taskOutputs(rawLayerUrls.map(url => taskDisplayUrl(task.id, url)), entries.filter(entry => !entry.kind || entry.kind === 'image'))
      : []
  const mainUrl = task.type === 'video' ? taskDisplayUrl(task.id, result.local_video) : task.type === 'audio' ? result.local_audio : null
  const mainOutputs = task.type === 'video' || task.type === 'audio'
    ? taskOutputs([mainUrl], entries.filter(entry => !entry.kind || entry.kind === task.type))
    : []
  const outputs = task.type === 'video' || task.type === 'audio' ? mainOutputs : imageOutputs
  const libraryMedia = outputs.filter(output => output.media && !output.deleted).map(output => output.media)
  const deletedCount = outputs.filter(output => output.deleted).length
  const resultDeleted = outputs.length > 0 && deletedCount === outputs.length
  const liveMain = mainOutputs.find(output => !output.deleted)
  const layers = Array.isArray(result.layers) ? result.layers : []
  const layerCount = Number.isFinite(Number(result.layer_count)) ? Number(result.layer_count) : layers.length
  return {
    key: `task-${task.id}`,
    kind: 'history',
    taskId: task.id,
    type: task.type,
    status: task.status || 'pending',
    prompt: task.prompt || '',
    provider: task.provider || '',
    favorite: Boolean(task.favorite),
    favoriteGroups: task.favorite_groups || [],
    createdAt: task.created_at,
    deletedAt: task.deleted_at || null,
    retryOf: task.retry_of || null,
    progress: Number(task.progress) || 0,
    error: task.error || '',
    resultUnknown: task.status === 'failed' && isResultUnknown(task),
    resultUnknownReason: task.status === 'failed' && isResultUnknown(task) ? resultUnknownReason(task) : '',
    params,
    images: imageOutputs.filter(output => !output.deleted).map(output => output.url),
    layers,
    layerCount,
    layerProjectId: result.project_id ?? params.project_id ?? null,
    outputs,
    libraryMedia,
    deletedCount,
    resultDeleted,
    remoteHosts: Array.isArray(result.source_urls) ? result.source_urls.map(remoteResultHost) : [],
    thumbnail: resultDeleted ? null : (imageOutputs.length && imageOutputs[0].deleted ? null : (result.local_thumbnail || result.local_thumbnails?.[0] || (task.type === 'layer' ? result.base_image : null) || null)),
    video: task.type === 'video' ? (liveMain?.url || null) : (taskDisplayUrl(task.id, result.local_video) || null),
    audio: task.type === 'audio' ? (liveMain?.url || null) : (result.local_audio || null),
    poster: task.type === 'video' && resultDeleted ? null : (taskDisplayUrl(task.id, result.local_last_frame) || null),
    refs: result.local_refs || [],
    refTypes: result.local_ref_types || [],
    canvasSource: task.canvas_source || null,
    source: task,
  }
}

export function taskTypeLabel(type) {
  if (type === 'all') return '全部'
  if (type === 'video') return '视频'
  if (type === 'audio') return '音频'
  if (type === 'layer') return '图层'
  return '图片'
}

export function selectionToken(item) {
  return `task-${item.taskId}`
}

// 在素材库中显示: the folder holding the first library result (root = 'root'); undefined → 生成历史 by kind.
export function revealTarget(item) {
  const media = item?.libraryMedia || []
  if (!media.length) return null
  const first = media[0]
  return {
    mediaIds: media.map(entry => entry.id),
    folderId: first.folderId === undefined ? undefined : (first.folderId || 'root'),
    kind: first.kind || item.type || 'image',
  }
}
