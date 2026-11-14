// FIX-B2B-20261114: stage wording for in-flight canvas tasks.
//
// Video providers give no reliable percentage (Cupsy reports a fixed placeholder for
// minutes), so video nodes show the stage instead of a number.
// VIDEO-SIGNAL-20261115: "下载写回" is shown only when the server says so: while the
// Provider has succeeded and the worker downloads the result, /api/tasks/status and
// /api/tasks/<id> return status 'processing' with stage 'downloading'. The server
// reports stage null in every other state, so a terminal status always wins.
export const TASK_STAGES = Object.freeze(['排队', '生成', '下载写回'])
export const SERVER_STAGE_DOWNLOADING = 'downloading'

// Index into TASK_STAGES for an in-flight status (and optional server stage), or -1.
export function taskStageIndex(status, stage = null) {
  if (['submitting', 'pending', 'preparing'].includes(status)) return 0
  if (status === 'processing') return stage === SERVER_STAGE_DOWNLOADING ? 2 : 1
  return -1
}

// Appended after the status word (e.g. "生成中 · 完成后自动下载并写回画布"), so they never repeat it.
const HINTS = {
  pending: '服务商排队中',
  preparing: '正在上传参考素材',
  processing: '完成后自动下载并写回画布',
}
const DOWNLOADING_HINT = '服务商已完成，正在下载并写回画布'
export const taskStageHint = (status, stage = null) =>
  status === 'processing' && stage === SERVER_STAGE_DOWNLOADING ? DOWNLOADING_HINT : HINTS[status] || ''

// A percentage is shown only for non-video nodes and only when the server reports 1–99.
export function taskProgressPercent(nodeType, progress) {
  if (nodeType === 'video') return null
  const value = Number(progress)
  return Number.isFinite(value) && value > 0 && value < 100 ? Math.round(value) : null
}
