// TASK-DONE-NOTIFY-20261114 (F3): completion reminders for canvas tasks.
//
// Reminders are raised only from the task-sync patches the polling loop applies
// (the server-written terminal state), and only for tasks this window submitted
// or saw active in a status response (`eligible`). A task that had already
// finished before the window opened -- terminal in the loaded document, or still
// marked active there but terminal on the first poll -- is never reminded, so a
// reload does not replay history. Each task id is reminded at most once per window.
import {isActiveTaskStatus,isTerminalTaskStatus} from './taskStatus.js'

export const SYSTEM_NOTIFY_KEY = 'inkTraces.canvas.systemNotify'
export const MAX_NOTICES = 3

// Record the tasks a status batch reports as still active (they finish while this window is open).
export function noteActiveTasks(batch, eligible) {
  for (const task of batch?.tasks || []) if (isActiveTaskStatus(task?.status)) eligible.add(Number(task.id))
  return batch
}

// succeeded | failed | cancelled | unknown (failed with result_unknown)
export function completionKind(task) {
  if (!task || !isTerminalTaskStatus(task.status)) return null
  if (task.status === 'failed') return task.resultUnknown ? 'unknown' : 'failed'
  return task.status
}

const KIND_TEXT = {
  succeeded: '生成完成',
  failed: '生成失败',
  cancelled: '已取消',
  unknown: '结果未知，可能已计费',
}
export function completionText(kind, title) {
  const name = String(title || '').trim() || '未命名节点'
  return `「${name}」${KIND_TEXT[kind] || '状态已更新'}`
}

/**
 * patches: Map(nodeId -> {task}) returned by taskSyncPatches and applied to the document.
 * notified: Set of task ids already reminded in this window (mutated).
 * eligible: Set of task ids submitted here or reported active to this window.
 * Returns [{key, taskId, nodeId, workflowId, kind, text, error}] in patch order.
 */
export function completionNotices({ patches, document, workflowId, notified, eligible }) {
  const notices = []
  for (const [nodeId, patch] of patches || []) {
    const kind = completionKind(patch?.task)
    const taskId = Number(patch?.task?.id)
    if (!kind || !Number.isFinite(taskId) || notified.has(taskId) || !eligible?.has(taskId)) continue
    notified.add(taskId)
    const node = document?.nodes?.find(item => item.id === nodeId)
    notices.push({ key: `${workflowId}:${taskId}`, taskId, nodeId, workflowId, kind, text: completionText(kind, node?.title), error: kind === 'failed' ? (patch.task.error || null) : null })
  }
  return notices
}

// Newest first, at most MAX_NOTICES kept.
export function mergeNotices(current, added, limit = MAX_NOTICES) {
  if (!added.length) return current
  const keys = new Set(added.map(item => item.key))
  return [...[...added].reverse(), ...current.filter(item => !keys.has(item.key))].slice(0, limit)
}

const PREFIX = /^\(\d+\)\s+/
export const baseTitle = title => String(title || '').replace(PREFIX, '')
export const titleWithCount = (base, count) => count > 0 ? `(${count}) ${baseTitle(base)}` : baseTitle(base)

// The page is "in the foreground" only when visible and focused.
export const pageInForeground = (doc = globalThis.document) => Boolean(doc) && !doc.hidden && (typeof doc.hasFocus !== 'function' || doc.hasFocus())

// Setting: 'on' | 'off' | null (never answered). Storage failures read as null.
export function readSystemSetting(storage = globalThis.localStorage) {
  try { const value = storage?.getItem(SYSTEM_NOTIFY_KEY); return value === 'on' || value === 'off' ? value : null } catch { return null }
}
export function writeSystemSetting(value, storage = globalThis.localStorage) {
  try { storage?.setItem(SYSTEM_NOTIFY_KEY, value) } catch { /* private mode: the choice lasts for this page only */ }
}
export const notificationPermission = (api = globalThis.Notification) => typeof api === 'function' ? api.permission : 'unsupported'

// Ask once, in the page, only while the browser has not decided and the user never answered.
export const shouldAskSystem = ({ setting, permission }) => setting === null && permission === 'default'
// An unanswered setting with permission already granted counts as on; 'off' always wins.
export const systemEnabled = ({ setting, permission }) => permission === 'granted' && setting !== 'off'
