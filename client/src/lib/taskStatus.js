// Single source of truth for task status words used by the canvas.
// Server tasks only produce SERVER_TASK_STATUSES (server/tasks.py); canvas
// documents additionally allow the two local states (server/canvas_store.py).
// Anything else must never be written into a canvas document: the whole
// workflow save would be rejected.
export const SERVER_TASK_STATUSES = Object.freeze(['pending', 'preparing', 'processing', 'cancel_requested', 'succeeded', 'failed', 'cancelled'])
export const CANVAS_LOCAL_TASK_STATUSES = Object.freeze(['submitting', 'unknown'])
export const DOCUMENT_TASK_STATUSES = Object.freeze([...CANVAS_LOCAL_TASK_STATUSES, ...SERVER_TASK_STATUSES])

// In flight on the server: polled until they reach a terminal state.
export const ACTIVE_TASK_STATUSES = Object.freeze(['pending', 'preparing', 'processing', 'cancel_requested'])
// Shows the generating animation and disables "生成".
export const GENERATING_TASK_STATUSES = Object.freeze(['submitting', ...ACTIVE_TASK_STATUSES])
// Blocks delete, regenerate and batch submission (an unknown submission may already exist upstream).
export const BUSY_TASK_STATUSES = Object.freeze([...GENERATING_TASK_STATUSES, 'unknown'])
export const TERMINAL_TASK_STATUSES = Object.freeze(['succeeded', 'failed', 'cancelled'])
// Shown as an error state on the canvas (a failed task, or a submission whose outcome is unknown).
export const FAILURE_TASK_STATUSES = Object.freeze(['failed', 'unknown'])
// Task center / layer tool: server in-flight statuses plus the client-only
// optimistic "submitting" placeholder those views create before a task id exists.
export const CLIENT_IN_FLIGHT_TASK_STATUSES = GENERATING_TASK_STATUSES

const set = values => new Set(values)
const SERVER = set(SERVER_TASK_STATUSES), DOCUMENT = set(DOCUMENT_TASK_STATUSES), ACTIVE = set(ACTIVE_TASK_STATUSES), GENERATING = set(GENERATING_TASK_STATUSES), BUSY = set(BUSY_TASK_STATUSES), TERMINAL = set(TERMINAL_TASK_STATUSES), FAILURE = set(FAILURE_TASK_STATUSES)
export const isServerTaskStatus = status => SERVER.has(status)
export const isDocumentTaskStatus = status => DOCUMENT.has(status)
export const isActiveTaskStatus = status => ACTIVE.has(status)
export const isGeneratingTaskStatus = status => GENERATING.has(status)
export const isBusyTaskStatus = status => BUSY.has(status)
export const isTerminalTaskStatus = status => TERMINAL.has(status)
export const isFailureTaskStatus = status => FAILURE.has(status)

export const TASK_STATUS_LABELS = Object.freeze({
  submitting: '正在提交', pending: '等待生成', preparing: '准备中', processing: '生成中', cancel_requested: '取消中',
  succeeded: '生成完成', failed: '生成失败', cancelled: '已取消', unknown: '提交结果未知，请到任务中心核查',
})
export const INVALID_STATUS_LABEL = '状态异常'
// Read-only display for values older builds may have shown; they are never written.
const LEGACY_LABELS = Object.freeze({ queued: '排队中', running: '生成中', completed: '生成完成', success: '生成完成' })
export const taskStatusLabel = status => TASK_STATUS_LABELS[status] || LEGACY_LABELS[status] || INVALID_STATUS_LABEL

// A task object is safe to store only with a document status.
export function documentTask(task) {
  if (!task) return null
  if (!isDocumentTaskStatus(task.status)) return null
  return { id: task.id ?? null, status: task.status, error: task.error ?? null }
}

// Final safety net before a save: an invalid status (should never happen)
// becomes "unknown" so the node is held for manual checking and the rest of
// the canvas still saves.
const DOCUMENT_TASK_KEYS = new Set(['id', 'status', 'error'])
const hasRuntimeTaskKeys = task => Object.keys(task).some(key => !DOCUMENT_TASK_KEYS.has(key))
const needsTaskSanitize = task => Boolean(task) && (!isDocumentTaskStatus(task.status) || hasRuntimeTaskKeys(task))

export function sanitizeDocumentTasks(document) {
  if (!document.nodes.some(node => needsTaskSanitize(node.task))) return document
  return { ...document, nodes: document.nodes.map(node => {
    if (!needsTaskSanitize(node.task)) return node
    // Runtime-only fields (progress, resultUnknown, ...) never reach the server: its schema keeps task to id/status/error.
    if (isDocumentTaskStatus(node.task.status)) return { ...node, task: documentTask(node.task) }
    return { ...node, task: { id: node.task.id ?? null, status: 'unknown', error: `${INVALID_STATUS_LABEL}：${String(node.task.status).slice(0, 40)}，请到任务记录核查` } }
  }) }
}
