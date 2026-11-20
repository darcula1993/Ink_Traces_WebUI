// LIBRARY-GLOBAL-20261116 S4b: task center ↔ global media library (S1 contract: /api/canvas/media/*).
// Moving changes folder_id; results still in 生成历史 are copied (GEN-RESULT-LIFECYCLE-20261119). Pure helpers are node-testable.
import axios from 'axios'

export const MOVE_BATCH = 500
export const ROOT = 'root'

export async function listMediaFolders(signal) {
  const response = await axios.get('/api/canvas/media/folders', { signal })
  return Array.isArray(response.data?.folders) ? response.data.folders : []
}

export async function createMediaFolder(title, parentId = null) {
  const response = await axios.post('/api/canvas/media/folders', { title, ...(parentId ? { parent_id: parentId } : {}) })
  return response.data.folder
}

export async function moveMediaToFolder(ids, folderId) {
  const unique = [...new Set(ids)]
  let moved = 0
  for (let offset = 0; offset < unique.length; offset += MOVE_BATCH) {
    const response = await axios.post('/api/canvas/media/move', { ids: unique.slice(offset, offset + MOVE_BATCH), folder_id: folderId === ROOT ? null : folderId })
    moved += Array.isArray(response.data?.media) ? response.data.media.length : 0
  }
  return moved
}

// Depth-first order with depth for an indented tree; orphans (parent missing) become top level.
export function folderTree(folders) {
  const ids = new Set(folders.map(folder => folder.id))
  const children = new Map()
  for (const folder of folders) {
    const parent = folder.parent_id && ids.has(folder.parent_id) ? folder.parent_id : ''
    if (!children.has(parent)) children.set(parent, [])
    children.get(parent).push(folder)
  }
  // System folders first (生成历史, then 图片/视频/音频 in that order), then user folders in stable server order.
  const rank = folder => folder.system_key ? ['generated', 'generated_image', 'generated_video', 'generated_audio'].indexOf(folder.system_key) + 1 || 9 : 99
  const order = (a, b) => rank(a) - rank(b)
  const out = []
  const seen = new Set()
  const walk = (parent, depth) => {
    for (const folder of (children.get(parent) || []).sort(order)) {
      if (seen.has(folder.id)) continue
      seen.add(folder.id)
      out.push({ folder, depth })
      walk(folder.id, depth + 1)
    }
  }
  walk('', 0)
  return out
}

// Mirrors the server rule: 生成历史 and its type subfolders receive only new generation results, nothing is moved
// into them (GEN-RESULT-LIFECYCLE-20261119); root and user folders take anything.
export function folderTargetIssue(folder, kinds) {
  if (!folder) return null
  if (folder.system_key === 'generated') return '“生成历史”只接收新生成的结果'
  if (folder.system_key?.startsWith('generated_')) return `“${folder.title}”只接收新生成的结果`
  return null
}

// Results still in 生成历史 are copied by “复制到文件夹” (the original stays with its task).
export const isGeneratedFolderId = (folders, id) => folders.some(folder => folder.id === id && folder.system_key?.startsWith('generated_'))

export const canCreateIn = folder => !folder?.system_key

export function systemFolderId(folders, kind) {
  return folders.find(folder => folder.system_key === `generated_${kind}`)?.id || null
}

// Full parent path (“父 / 子”), as in every “移动到文件夹” dialog (V2-FIX F6).
export function folderLabel(folders, folderId) {
  if (!folderId || folderId === ROOT) return '根目录'
  const byId = new Map(folders.map(folder => [folder.id, folder]))
  const path = []
  const seen = new Set()
  for (let folder = byId.get(folderId); folder && !seen.has(folder.id); folder = byId.get(folder.parent_id)) { seen.add(folder.id); path.unshift(folder.title) }
  return path.length ? path.join(' / ') : '所选文件夹'
}

// The folder every result is in now (ROOT for the root); null when they differ or a folder is unknown (V2-FIX F7).
export function currentTarget(media, folders = []) {
  if (!media.length || media.some(entry => entry.folderId === undefined)) return null
  const own = [...new Set(media.map(entry => entry.folderId || ROOT))]
  return own.length === 1 && !isGeneratedFolderId(folders, own[0]) ? own[0] : null
}

// Library results of the given task items (deleted ones excluded), de-duplicated.
export function collectMedia(items) {
  const seen = new Map()
  for (const item of items) for (const media of item?.libraryMedia || []) if (!seen.has(media.id)) seen.set(media.id, media)
  return [...seen.values()]
}
