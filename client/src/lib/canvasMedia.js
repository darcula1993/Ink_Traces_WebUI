// LIBRARY-GLOBAL-20261116 S5: the canvas side of the global media library (S1 contract,
// task log "S1 接口契约"). Canvas uploads, pastes, frame captures and image "save as" go into the
// library; nodes store the media id and never a canvas copy.
import axios from 'axios'
import {MEDIA_PREFIX,isMediaAsset,isMediaId,mediaNodeAsset,markDeletedMedia,markTrashedMedia,unmarkMedia,deletedReferenceIssue} from './canvasMediaStatus.js'

const base = '/api/canvas/media'
const data = async promise => (await promise).data
export const CANVAS_UPLOAD_ORIGINS = ['canvas_upload', 'paste', 'frame', 'save_as']
const codeOf = error => error?.response?.data?.code

export function formatUploadBytes(bytes) {
  const value = Number(bytes)
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  if (value < 1024) return `${Math.round(value)} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

export function computeBatchUploadProgress({
  totalFiles = 1,
  currentIndex = 1,
  fileName = '素材',
  completedBytes = 0,
  totalBytes = 0,
  fileLoaded = 0,
  fileTotal = 0,
  phase = 'uploading',
} = {}) {
  const safeFiles = Math.max(1, Number(totalFiles) || 1)
  const safeIndex = Math.min(safeFiles, Math.max(1, Number(currentIndex) || 1))
  const safeTotalBytes = Math.max(0, Number(totalBytes) || 0)
  const safeCompleted = Math.max(0, Number(completedBytes) || 0)
  const safeFileTotal = Math.max(0, Number(fileTotal) || 0)
  const safeFileLoaded = safeFileTotal > 0
    ? Math.min(safeFileTotal, Math.max(0, Number(fileLoaded) || 0))
    : Math.max(0, Number(fileLoaded) || 0)

  if (phase === 'saving') {
    return {
      totalFiles: safeFiles,
      currentIndex: safeFiles,
      fileName: String(fileName || '素材'),
      filePercent: 100,
      overallPercent: 100,
      loadedBytes: safeTotalBytes,
      totalBytes: safeTotalBytes,
      phase: 'saving',
    }
  }

  const filePercent = safeFileTotal > 0
    ? Math.min(100, Math.round((safeFileLoaded / safeFileTotal) * 100))
    : (phase === 'processing' ? 100 : null)

  let loadedBytes = safeCompleted + safeFileLoaded
  if (safeTotalBytes > 0) loadedBytes = Math.min(safeTotalBytes, loadedBytes)

  let overallPercent = null
  if (safeTotalBytes > 0) {
    overallPercent = Math.min(100, Math.round((loadedBytes / safeTotalBytes) * 100))
  } else if (filePercent !== null) {
    overallPercent = Math.min(100, Math.round((((safeIndex - 1) + (filePercent / 100)) / safeFiles) * 100))
  }

  return {
    totalFiles: safeFiles,
    currentIndex: safeIndex,
    fileName: String(fileName || '素材'),
    filePercent,
    overallPercent,
    loadedBytes,
    totalBytes: safeTotalBytes,
    phase: phase === 'processing' ? 'processing' : 'uploading',
  }
}

// Upload into the library root or a chosen folder. A folder deleted meanwhile falls back to the
// root once (folderFallback) instead of losing the file.
export async function uploadCanvasLibraryMedia(file, { origin = 'canvas_upload', folderId = null, onProgress = null } = {}) {
  if (!CANVAS_UPLOAD_ORIGINS.includes(origin)) throw new Error('上传来源无效')
  const fileSize = Number(file?.size) > 0 ? Number(file.size) : 0
  const send = async folder => {
    const body = new FormData()
    body.append('file', file, file.name || 'media')
    body.append('origin', origin)
    if (folder) body.append('folder_id', folder)
    if (typeof onProgress !== 'function') return data(axios.post(base, body))
    return data(axios.post(base, body, {
      onUploadProgress: event => {
        const rawTotal = Number(event?.total) > 0 ? Number(event.total) : fileSize
        const loaded = Math.max(0, Number(event?.loaded) || 0)
        const clampedLoaded = rawTotal > 0 ? Math.min(rawTotal, loaded) : loaded
        const percent = rawTotal > 0 ? Math.min(100, Math.round((clampedLoaded / rawTotal) * 100)) : null
        const phase = rawTotal > 0 && clampedLoaded >= rawTotal ? 'processing' : 'uploading'
        onProgress({ loaded: clampedLoaded, total: rawTotal, percent, phase })
      },
    }))
  }
  let result, folderFallback = false
  try { result = await send(folderId) } catch (error) {
    if (!folderId || codeOf(error) !== 'folder_not_found') throw error
    if (typeof onProgress === 'function') onProgress({ loaded: 0, total: fileSize, percent: 0, phase: 'uploading' })
    result = await send(null); folderFallback = true
  }
  return { asset: mediaNodeAsset(result.media), media: result.media, deduplicated: !!result.deduplicated, folderFallback }
}

export const LOOKUP_BATCH = 500
// ref → {ref,status:'ok'|'deleted'|'trashed'|'missing',media_id,media?}; refs may be media ids, "scope:old_id" or old URLs.
export async function lookupMedia(refs) {
  const unique = [...new Set(refs.filter(ref => typeof ref === 'string' && ref))], found = new Map()
  for (let index = 0; index < unique.length; index += LOOKUP_BATCH) {
    const result = await data(axios.post(`${base}/lookup`, { refs: unique.slice(index, index + LOOKUP_BATCH) }))
    for (const item of result.items || []) found.set(item.ref, item)
  }
  return found
}
// Ids of the given media the library reports as unavailable (also recorded in the runtime registry):
// deleted, or 'trashed' (a 生成历史 result whose task is in the trash, GEN-RESULT-LIFECYCLE-20261119).
// Trashed ids that are 'ok' again (task restored) are unmarked.
export async function deletedAmong(ids) {
  const media = [...new Set(ids.filter(isMediaId))]
  if (!media.length) return []
  const found = await lookupMedia(media), status = id => found.get(id)?.status
  const deleted = media.filter(id => status(id) === 'deleted'), trashed = media.filter(id => status(id) === 'trashed')
  if (deleted.length) markDeletedMedia(deleted)
  if (trashed.length) markTrashedMedia(trashed)
  unmarkMedia(media.filter(id => status(id) === 'ok'))
  return [...deleted, ...trashed]
}
// Right before a generation request: a deleted reference is refused with a Chinese reason.
export async function assertMediaAvailable(assets, invalid) {
  const media = assets.filter(isMediaAsset)
  if (!media.length) return
  let deleted
  try { deleted = new Set(await deletedAmong(media.map(asset => asset.id))) } catch { invalid('无法确认参考素材是否仍在素材库中，尚未提交生成') }
  const first = media.find(asset => deleted.has(asset.id))
  if (first) invalid(deletedReferenceIssue(first))
}

// A selection from the library dialog: a library media item, or (until migration) an old catalog
// item that the server resolves through its alias (scope:old_id).
export function libraryItemRef(item) {
  const selection = item?.selection || {}, asset = item?.asset || {}
  if (selection.source === 'media' && isMediaId(String(selection.id))) return String(selection.id)
  if (isMediaAsset(asset)) return asset.id
  if (typeof asset.url === 'string' && asset.url.startsWith(MEDIA_PREFIX)) return asset.url
  if (['local', 'library', 'workflow', 'task'].includes(selection.source) && selection.id != null) return `${selection.source}:${selection.id}`
  return null
}
// Direct references for library items: no canvas copy. Items the library does not know yet
// (not migrated) are returned in `legacy` so the caller may keep the old import for them.
export async function resolveLibraryMedia(items) {
  const refs = items.map(libraryItemRef), found = await lookupMedia(refs.filter(Boolean))
  const assets = [], legacy = [], deleted = []
  items.forEach((item, index) => {
    const entry = refs[index] && found.get(refs[index])
    if (entry?.status === 'ok' && entry.media) assets.push({ index, asset: mediaNodeAsset(entry.media) })
    else if (entry?.status === 'deleted' || entry?.status === 'trashed') deleted.push(item.asset?.name || entry.media?.name || '素材')
    else legacy.push({ index, item })
  })
  return { assets, legacy, deleted }
}

// Library folders (global, S1). The "生成历史" system folders only take results of their kind.
export const listMediaFolders = async () => (await data(axios.get(`${base}/folders`))).folders || []
export const createMediaFolder = async (title, parentId = null) => (await data(axios.post(`${base}/folders`, { title, parent_id: parentId }))).folder
export const updateMediaFolder = async (id, value) => (await data(axios.patch(`${base}/folders/${encodeURIComponent(id)}`, value))).folder
export const deleteMediaFolder = id => data(axios.delete(`${base}/folders/${encodeURIComponent(id)}`))
export const moveMedia = async (ids, folderId) => (await data(axios.post(`${base}/move`, { ids, folder_id: folderId || null }))).media || []
export const listMedia = (params, signal) => data(axios.get(base, { params, signal }))
export const getMediaInfo = async id => (await data(axios.get(`${base}/${encodeURIComponent(id)}/info`))).media
export const splitCanvasLibraryVideo = (mediaId, payload) =>
  data(axios.post(`${base}/${encodeURIComponent(mediaId)}/split`, payload, { timeout: 300000 }))

// Folder labels ("生成历史 / 图片") and the folders a set of media may move into.
export function folderPath(folders, id) {
  const path = [], seen = new Set()
  while (id && !seen.has(id)) { seen.add(id); const folder = folders.find(item => item.id === id); if (!folder) break; path.unshift(folder.title); id = folder.parent_id }
  return path.join(' / ')
}
export function moveTargets(folders, kinds = []) {
  const byKey = new Map(folders.filter(f => f.system_key).map(f => [f.id, f.system_key]))
  return folders.filter(folder => {
    const key = byKey.get(folder.id)
    if (key === 'generated') return false
    if (key?.startsWith('generated_')) return kinds.length > 0 && kinds.every(kind => key === `generated_${kind}`)
    return true
  })
}
export const isSystemFolder = folder => !!folder?.system_key

// Per-viewer convenience: where canvas uploads go (library root when unset or unavailable).
const UPLOAD_FOLDER_KEY = 'ink.canvas.uploadFolder'
export function readUploadFolder() { try { return globalThis.localStorage?.getItem(UPLOAD_FOLDER_KEY) || null } catch { return null } }
export function writeUploadFolder(id) { try { if (id) globalThis.localStorage?.setItem(UPLOAD_FOLDER_KEY, id); else globalThis.localStorage?.removeItem(UPLOAD_FOLDER_KEY) } catch { /* storage is optional */ } }
