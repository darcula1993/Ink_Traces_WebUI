// NODE-ECHO-20261115: hand-off from the canvas to the task center ("go to task #N").
// The canvas dispatches a cancelable window event and leaves the request in sessionStorage;
// the app shell switches tool on the event (calling preventDefault to say it handled it) and
// the task center of that tool takes the pending id once and opens that task.
export const TASK_CENTER_EVENT = 'nb:open-task-center'
export const TASK_CENTER_FOCUS_KEY = 'nb:task-center-focus'
export const TASK_CENTER_MODES = Object.freeze(['image', 'video', 'audio'])
const MAX_AGE_MS = 60_000

const storage = () => { try { return globalThis.sessionStorage || null } catch { return null } }

// Returns true when a listener (the app shell) took over the navigation.
export function requestTaskCenter({ taskId, type } = {}) {
  const id = Number(taskId)
  if (!Number.isInteger(id) || id <= 0) return false
  const detail = { taskId: id, type: TASK_CENTER_MODES.includes(type) ? type : null, at: Date.now() }
  try { storage()?.setItem(TASK_CENTER_FOCUS_KEY, JSON.stringify(detail)) } catch { /* private mode: event only */ }
  const target = globalThis.window || globalThis
  if (typeof target.dispatchEvent !== 'function' || typeof globalThis.CustomEvent !== 'function') return false
  const event = new globalThis.CustomEvent(TASK_CENTER_EVENT, { detail, cancelable: true })
  target.dispatchEvent(event)
  return event.defaultPrevented
}

// Task center side: the pending task id for this tool (taken once), else null.
export function takeTaskCenterFocus(mode, now = Date.now()) {
  const store = storage()
  if (!store) return null
  let pending = null
  try { pending = JSON.parse(store.getItem(TASK_CENTER_FOCUS_KEY) || 'null') } catch { pending = null }
  if (!pending || (pending.type && pending.type !== mode)) return null
  store.removeItem(TASK_CENTER_FOCUS_KEY)
  if (!(now - Number(pending.at) <= MAX_AGE_MS)) return null
  const id = Number(pending.taskId)
  return Number.isInteger(id) && id > 0 ? id : null
}
