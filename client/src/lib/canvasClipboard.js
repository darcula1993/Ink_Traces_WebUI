// CANVAS-INPUT-20261114 #1: files carried by a paste event (copied files or a
// screenshot bitmap). Text-only clipboards yield no files and are ignored by the
// canvas; unsupported types are still returned so the upload path can explain why.
const EXTENSIONS = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif', 'video/mp4': 'mp4', 'video/webm': 'webm', 'audio/mpeg': 'mp3', 'audio/wav': 'wav' }
const pad = value => String(value).padStart(2, '0')
export function pastedFileName(file, now = new Date()) {
  if (file.name && file.name !== 'image.png') return file.name
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  const extension = EXTENSIONS[file.type] || (file.type.split('/')[1] || 'bin').replace(/[^a-z0-9]/gi, '').slice(0, 8) || 'bin'
  return `粘贴-${stamp}.${extension}`
}
export function clipboardFiles(data, now = new Date()) {
  if (!data) return []
  const found = []
  for (const item of [...(data.items || [])]) if (item.kind === 'file') { const file = item.getAsFile?.(); if (file) found.push(file) }
  if (!found.length) found.push(...[...(data.files || [])])
  const named = found.map(file => { const name = pastedFileName(file, now); return name === file.name || typeof File === 'undefined' ? file : new File([file], name, { type: file.type, lastModified: file.lastModified }) })
  return named
}
