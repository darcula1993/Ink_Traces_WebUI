// Project cost ledger: estimates only (never actual charges). Unknown is never zero.
import axios from 'axios'

export const UNASSIGNED_PROJECT = '__unassigned__'
export const LEDGER_DISCLAIMER = '估算，非实际扣费'
export const BUCKET_ORDER = ['billable', 'result_unknown', 'failed', 'cancelled', 'active']
export const BUCKET_LABELS = {
  billable: '已完成（估算计入）',
  result_unknown: '结果未知（可能已计费）',
  failed: '失败（通常不计费）',
  cancelled: '已取消（通常不计费）',
  active: '进行中（尚未结束）',
}
export const TYPE_LABELS = { video: '视频', image: '图像', audio: '音频', layer: '图层分解' }
export const REASON_LABELS = {
  no_price_data: '无价格资料',
  no_estimate_snapshot: '历史任务未存估算',
  unknown_provider: 'Provider 未知',
}

export async function fetchCostLedger({ projectId, workflowId, from, to, tzOffsetMinutes } = {}, signal) {
  const params = {}
  if (projectId) params.project_id = projectId
  if (workflowId) params.workflow_id = workflowId
  if (from) params.from = from
  if (to) params.to = to
  params.tz_offset_minutes = tzOffsetMinutes ?? -new Date().getTimezoneOffset()
  return (await axios.get('/api/cost-ledger', { params, signal })).data
}

export function formatUsdRange(min, max) {
  const a = Number(min).toFixed(2), b = Number(max).toFixed(2)
  return a === b ? `$${a}` : `$${a}~$${b}`
}

// One bucket's figure: known sum plus a separate unknown count; never "$0.00" for unknown-only.
export function describeBucket(bucket) {
  const total = bucket || { count: 0, known_count: 0, unknown_count: 0, known_usd_min: 0, known_usd_max: 0 }
  if (!total.count) return { amount: '—', unknown: '', empty: true, text: '无任务' }
  const amount = total.known_count ? formatUsdRange(total.known_usd_min, total.known_usd_max) : '—'
  const unknown = total.unknown_count ? `未知 ${total.unknown_count} 条` : ''
  const text = [total.known_count ? `估算 ${amount}` : '无可估算任务', unknown].filter(Boolean).join(' + ')
  return { amount, unknown, empty: false, text }
}

export function taskAmount(task) {
  if (!task.estimate_usd) return `未知（${REASON_LABELS[task.unknown_reason] || task.unknown_reason_label || '未知原因'}）`
  return formatUsdRange(task.estimate_usd.min, task.estimate_usd.max)
}

export const basisLabel = task => (task.basis === 'derived' && task.estimate_usd ? '推算' : task.basis === 'snapshot' ? '提交时快照' : '')

export const typeLabel = type => TYPE_LABELS[type] || type || '未知类型'
