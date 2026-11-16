// LIBRARY-GLOBAL-20261116 S5: the canvas side of the global media library (S1 contract,
// task log "S1 接口契约"). Canvas uploads, pastes, frame captures and image "save as" go into the
// library; nodes store the media id and never a canvas copy.
import axios from 'axios'
import {MEDIA_PREFIX,isMediaAsset,isMediaId,mediaNodeAsset,markDeletedMedia,deletedReferenceIssue} from './canvasMediaStatus.js'

const base = '/api/canvas/media'
const data = async promise => (await promise).data
export const CANVAS_UPLOAD_ORIGINS = ['canvas_upload', 'paste', 'frame', 'save_as']
const codeOf = error => error?.response?.data?.code

// Upload into the library root or a chosen folder. A folder deleted meanwhile falls back to the
// root once (folderFallback) instead of losing the file.
export async function uploadCanvasLibraryMedia(file, { origin = 'canvas_upload', folderId = null } = {}) {
  if (!CANVAS_UPLOAD_ORIGINS.includes(origin)) throw new Error('上传来源无效')
  const send = async folder => {
    const body = new FormData()
    body.append('file', file, file.name || 'media')
    body.append('origin', origin)
    if (folder) body.append('folder_id', folder)
    return data(axios.post(base, body))
  }
  let result, folderFallback = false
  try { result = await send(folderId) } catch (error) {
    if (!folderId || codeOf(error) !== 'folder_not_found') throw error
    result = await send(null); folderFallback = true
  }
  return { asset: mediaNodeAsset(result.media), media: result.media, deduplicated: !!result.deduplicated, folderFallback }
}

export const LOOKUP_BATCH = 500
// ref → {ref,status:'ok'|'deleted'|'missing',media_id,media?}; refs may be media ids, "scope:old_id" or old URLs.
export async function lookupMedia(refs) {
  const unique = [...new Set(refs.filter(ref => typeof ref === 'string' && ref))], found = new Map()
  for (let index = 0; index < unique.length; index += LOOKUP_BATCH) {
    const result = await data(axios.post(`${base}/lookup`, { refs: unique.slice(index, index + LOOKUP_BATCH) }))
    for (const item of result.items || []) found.set(item.ref, item)
  }
  return found
}
// Ids of the given media the library reports as deleted (also recorded in the runtime registry).
export async function deletedAmong(ids) {
  const media = [...new Set(ids.filter(isMediaId))]
  if (!media.length) return []
  const found = await lookupMedia(media), deleted = media.filter(id => found.get(id)?.status === 'deleted')
  if (deleted.length) markDeletedMedia(deleted)
  return deleted
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
    else if (entry?.status === 'deleted') deleted.push(item.asset?.name || entry.media?.name || '素材')
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
