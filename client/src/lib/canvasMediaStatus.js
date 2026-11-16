// LIBRARY-GLOBAL-20261116 S5: canvas nodes reference the global media library directly.
// Pure helpers (node-testable, no network): which node assets are library media, and the runtime
// registry of media the library reports as deleted ("已删除" placeholders; never saved).
export const MEDIA_PREFIX = '/api/canvas/media/'
const MEDIA_ID = /^[0-9a-f]{32}$/
export const isMediaId = value => typeof value === 'string' && MEDIA_ID.test(value)
export const isMediaAsset = asset => typeof asset?.url === 'string' && asset.url.startsWith(MEDIA_PREFIX) && isMediaId(asset.id)
export const mediaUrl = id => `${MEDIA_PREFIX}${id}`
// Node asset shape: the same fields the canvas document validator accepts for any asset
// ({id,name,mime_type,kind,size_bytes,url}); the URL is the library route of the media id.
export function mediaNodeAsset(media) {
  if (!isMediaId(media?.id) || !['image', 'video', 'audio'].includes(media.kind)) throw new Error('素材库返回的素材无效')
  return { id: media.id, name: String(media.name || '素材'), mime_type: String(media.mime_type || ''), kind: media.kind, ...(Number.isInteger(media.size_bytes) ? { size_bytes: media.size_bytes } : {}), url: mediaUrl(media.id) }
}
// Every media id a document references (results, kept versions, direct references).
export function documentMediaIds(document) {
  const ids = new Set()
  for (const node of document?.nodes || []) {
    for (const asset of [node.asset, ...(node.candidates || []), ...(node.referenceAssets || [])]) if (isMediaAsset(asset)) ids.add(asset.id)
  }
  return [...ids]
}

let deleted = new Set()
const listeners = new Set()
export const isDeletedMedia = id => deleted.has(id)
export const deletedMediaIds = () => [...deleted]
export function setDeletedMedia(ids) {
  const next = new Set(ids)
  if (next.size === deleted.size && [...next].every(id => deleted.has(id))) return false
  deleted = next
  for (const listener of listeners) listener()
  return true
}
export function markDeletedMedia(ids) { return setDeletedMedia([...deleted, ...ids]) }
export function onDeletedMediaChange(listener) { listeners.add(listener); return () => listeners.delete(listener) }

export const deletedReferenceIssue = asset => `参考素材“${asset?.name || '未命名'}”已在素材库中删除，请替换或移除后再生成`
// Inputs whose media was deleted in the library block generation (checked again against the
// server right before submit; see canvasMedia.assertMediaAvailable).
export const deletedInputIssues = assets => assets.filter(asset => isMediaAsset(asset) && deleted.has(asset.id)).map(deletedReferenceIssue)
