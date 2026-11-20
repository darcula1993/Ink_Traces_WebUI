// V2-REAL-USE F4: lightweight cross-canvas / task-center / cross-tab media library refresh bus.
// Producers call notifyLibraryChanged() after generation completion, upload, move, rename or delete;
// subscribers (e.g. canvas sidebar AssetTree) quietly reload folders and counts without closing dialogs.

export const LIBRARY_CHANGED_EVENT = 'ink-library-changed'
const STORAGE_KEY = 'ink-traces.library-changed.v1'

export function notifyLibraryChanged(detail = {}) {
  if (typeof window === 'undefined') return
  const payload = { at: Date.now(), ...detail }
  try {
    window.dispatchEvent(new CustomEvent(LIBRARY_CHANGED_EVENT, { detail: payload }))
  } catch { /* ignore */ }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  } catch { /* storage unavailable */ }
}

export function subscribeLibraryChanged(onChange, { minFocusIntervalMs = 2000 } = {}) {
  if (typeof window === 'undefined') return () => {}
  let lastFocusRefresh = Date.now()
  const fire = detail => {
    lastFocusRefresh = Date.now()
    onChange(detail)
  }
  const onEvent = event => fire(event?.detail || { source: 'event' })
  const onStorage = event => {
    if (event.key !== STORAGE_KEY || !event.newValue) return
    let detail = { source: 'storage' }
    try { detail = { ...detail, ...JSON.parse(event.newValue) } } catch { /* ignore */ }
    fire(detail)
  }
  const onFocus = () => {
    if (typeof document !== 'undefined' && document.hidden) return
    const now = Date.now()
    if (now - lastFocusRefresh < minFocusIntervalMs) return
    fire({ source: 'focus', at: now })
  }
  const onVisibility = () => {
    if (typeof document !== 'undefined' && !document.hidden) onFocus()
  }
  window.addEventListener(LIBRARY_CHANGED_EVENT, onEvent)
  window.addEventListener('storage', onStorage)
  window.addEventListener('focus', onFocus)
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibility)
  return () => {
    window.removeEventListener(LIBRARY_CHANGED_EVENT, onEvent)
    window.removeEventListener('storage', onStorage)
    window.removeEventListener('focus', onFocus)
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility)
  }
}
