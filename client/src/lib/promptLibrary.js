// Canvas prompt library helpers (shares the legacy /api/prompts library; text only).
export function filterPrompts(prompts, query) {
  const needle = String(query || '').trim().toLowerCase()
  const list = Array.isArray(prompts) ? prompts : []
  return needle ? list.filter(item => String(item?.text || '').toLowerCase().includes(needle)) : list
}

export function promptPreview(text, limit = 120) {
  const flat = String(text || '').replace(/\s+/g, ' ').trim()
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat
}

export function canSavePrompt(text) {
  return String(text || '').trim().length > 0
}

export function nextActiveIndex(index, count, key) {
  if (!count) return 0
  if (key === 'ArrowDown') return (index + 1) % count
  if (key === 'ArrowUp') return (index - 1 + count) % count
  return index
}

// Insert plain text at the textarea's selection through the native edit pipeline so Ctrl+Z undoes it in one step.
// Returns false when the browser refuses (caller falls back to a state update).
export function insertTextNatively(textarea, text, start, end) {
  if (!textarea) return false
  textarea.focus()
  const length = textarea.value.length
  const from = Math.max(0, Math.min(start ?? length, length))
  const to = Math.max(from, Math.min(end ?? from, length))
  textarea.setSelectionRange(from, to)
  try { return document.execCommand('insertText', false, text) } catch { return false }
}
