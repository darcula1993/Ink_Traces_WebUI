// FIX-B2B-20261114: stage wording for in-flight canvas tasks.
//
// The server reports only status words; video providers give no reliable percentage
// (Cupsy reports a fixed placeholder for minutes), so video nodes show the stage instead
// of a number. "下载写回" is never claimed as current: the server downloads the result and
// writes it back inside the final poll, after which the node shows the result itself.
export const TASK_STAGES = Object.freeze(['排队', '生成', '下载写回'])

// Index into TASK_STAGES for an in-flight status, or -1.
export function taskStageIndex(status) {
  if (['submitting', 'pending', 'preparing'].includes(status)) return 0
  if (status === 'processing') return 1
  return -1
}

// Appended after the status word (e.g. "生成中 · 完成后自动下载并写回画布"), so they never repeat it.
const HINTS = {
  pending: '服务商排队中',
  preparing: '正在上传参考素材',
  processing: '完成后自动下载并写回画布',
}
export const taskStageHint = status => HINTS[status] || ''

// A percentage is shown only for non-video nodes and only when the server reports 1–99.
export function taskProgressPercent(nodeType, progress) {
  if (nodeType === 'video') return null
  const value = Number(progress)
  return Number.isFinite(value) && value > 0 && value < 100 ? Math.round(value) : null
}
