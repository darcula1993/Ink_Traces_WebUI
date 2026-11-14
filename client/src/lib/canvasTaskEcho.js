// NODE-ECHO-20261115: what a generation node echoes about its latest task (task number,
// duration, cost estimate, failure class). Pure helpers; runtime only, never written to the
// canvas document. Unknown cost is shown as "未知", never as zero.
import { isActiveTaskStatus, isGeneratingTaskStatus, isTerminalTaskStatus } from './taskStatus.js'
import { taskAmount, REASON_LABELS } from './costLedger.js'

// FAILURE-CLASS-20261115 contract: task.failure = {category, label, hint, action}.
export const FAILURE_ACTIONS = Object.freeze(['regenerate_confirm', 'edit_params', 'check_task', 'none'])
export const FAILURE_ACTION_LABELS = Object.freeze({
  regenerate_confirm: '确认后重新生成',
  edit_params: '修改参数',
  check_task: '到任务中心核查',
})

// Server times are ISO strings; a value without an offset is UTC (tasks.utcnow / legacy rows).
export function parseServerTime(raw) {
  if (typeof raw !== 'string' || !raw.trim()) return null
  const text = raw.trim().replace(' ', 'T')
  const time = Date.parse(/([zZ]|[+-]\d{2}:?\d{2})$/.test(text) ? text : `${text}Z`)
  return Number.isFinite(time) ? time : null
}

export function formatDuration(seconds) {
  const sec = Math.max(0, Math.floor(Number(seconds) || 0))
  if (sec >= 3600) return `${Math.floor(sec / 3600)}:${String(Math.floor(sec % 3600 / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`
}

// Submit → completion for a finished task; null when the server times are missing or unreadable.
export function taskDurationSeconds(detail) {
  if (!detail || !isTerminalTaskStatus(detail.status)) return null
  const start = parseServerTime(detail.created_at), end = parseServerTime(detail.completed_at) ?? parseServerTime(detail.updated_at)
  if (start == null || end == null) return null
  return Math.max(0, Math.round((end - start) / 1000))
}

// Server submit time of a task that is still running (used as the elapsed-time origin).
export function taskStartedAt(detail) {
  return detail && !isTerminalTaskStatus(detail.status) ? parseServerTime(detail.created_at) : null
}

/**
 * Cost estimate echo from the submission snapshot (params.cost_estimate).
 * Returns {text, title, known} or null when there is no detail yet.
 */
export function taskCostEcho(detail, { resultUnknown = false } = {}) {
  if (!detail) return null
  const status = detail.status
  if ((status === 'failed' && !resultUnknown) || status === 'cancelled')
    return { text: '不计费', title: `${status === 'cancelled' ? '已取消' : '失败'}的任务通常不计费（估算口径，非实际扣费）`, known: true }
  const snapshot = detail.params?.cost_estimate
  const min = Number(snapshot?.minimum_cost), max = Number(snapshot?.maximum_cost ?? snapshot?.minimum_cost)
  if (snapshot?.status === 'estimate' && Number.isFinite(min) && Number.isFinite(max)) {
    const amount = taskAmount({ type: detail.type, estimate_usd: { min, max } })
    const notes = ['提交时估算，非实际扣费']
    if (resultUnknown) notes.push('结果未知，可能已计费')
    else if (isActiveTaskStatus(status)) notes.push('任务尚未结束')
    return { text: amount, title: `费用 ${amount} USD：${notes.join('；')}`, known: true }
  }
  const reason = snapshot?.reason ? REASON_LABELS[snapshot.reason] || snapshot.reason : '该任务未存提交时估算'
  return { text: '未知', title: `费用未知：${reason}；未知不代表免费`, known: false }
}

/**
 * Validate the server failure class. Missing or malformed → null (nothing shown).
 * A result-unknown task only ever offers the check entry, whatever the server action says.
 */
export function taskFailure(raw, { resultUnknown = false, status } = {}) {
  if (!raw || typeof raw !== 'object') return null
  const text = value => (typeof value === 'string' ? value.trim() : '')
  const category = text(raw.category), label = text(raw.label), hint = text(raw.hint)
  if (!label && !hint) return null
  let action = FAILURE_ACTIONS.includes(raw.action) ? raw.action : 'none'
  if (category === 'result_unknown' || resultUnknown || status === 'unknown') action = 'check_task'
  return { category, label, hint, action }
}

// When the cached detail answers for the node's current task state (otherwise refetch).
export const echoPhase = status => isTerminalTaskStatus(status) ? status : isGeneratingTaskStatus(status) ? 'active' : status || ''
