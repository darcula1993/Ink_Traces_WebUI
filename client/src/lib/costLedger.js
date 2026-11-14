// Project cost ledger: estimates only (never actual charges). Unknown is never zero.
import axios from 'axios'
import { formatImageUsd } from './byteplusPricing.js'

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
  below_price_floor: '输出像素低于官方定价下限',
  above_price_ceiling: '输出像素超出官方定价档',
  layer_count_unknown: '图层数量未知（按实际层数计）',
  layer_outputs_unknown: '图层输出尺寸不可读',
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

// Three decimals at every amount (ESTIMATE-DEBT-20261115), the same rule as the
// "运行所选节点" dialog (canvasBatchRun.formatUsd): $0.410, $4.731. Unknown is never '$0'.
export function formatUsd(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `$${n.toFixed(3)}`
}

export function formatUsdRange(min, max) {
  const a = formatUsd(min), b = formatUsd(max)
  return a === b ? a : `${a}~${b}`
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
  if (task.type === 'image' || task.type === 'layer') {
    // Per-image prices have sub-cent precision (e.g. $0.0225); keep up to 4 decimals.
    const a = formatImageUsd(task.estimate_usd.min), b = formatImageUsd(task.estimate_usd.max)
    return a === b ? a : `${a}~${b}`
  }
  return formatUsdRange(task.estimate_usd.min, task.estimate_usd.max)
}

export const basisLabel = task => ((task.basis === 'derived' || task.assumption) && task.estimate_usd ? '推算' : task.basis === 'snapshot' ? '提交时快照' : '')

// Hover text for the basis tag: why the amount is 推算 (or that it is the submission snapshot).
export function basisTitle(task) {
  if (!task.estimate_usd) return ''
  const parts = []
  if (task.basis === 'derived') parts.push('历史任务未存估算，按任务参数推算')
  if (task.basis === 'snapshot') parts.push('按提交时冻结的估算口径计算')
  const small = task.assumptions?.below_floor_layers
  if (task.assumption === 'below_floor_min_tier') parts.push(`${small || '部分'} 层低于 921,600 像素（官方无价），按最低档 $0.02 推算`)
  return parts.join('；')
}

export const typeLabel = type => TYPE_LABELS[type] || type || '未知类型'

// Failed/cancelled tasks are usually not billed: shown as 不计费 and never mixed into
// any "未知 N 条" count (display only; the estimate rules are unchanged).
export const NOT_BILLED_BUCKETS = ['failed', 'cancelled']
export const NOT_BILLED_LABEL = '不计费'

export function describeNotBilled(...buckets) {
  const count = buckets.reduce((sum, bucket) => sum + (bucket?.count || 0), 0)
  if (!count) return { amount: '—', empty: true, count: 0, text: '无任务' }
  return { amount: NOT_BILLED_LABEL, empty: false, count, text: `${count} 条` }
}

export function ledgerTaskAmount(task) {
  return NOT_BILLED_BUCKETS.includes(task?.bucket) ? NOT_BILLED_LABEL : taskAmount(task)
}

const pad = value => String(value).padStart(2, '0')

// Local submit time for the detail table; falls back to the server's local date.
export function taskTime(task) {
  const raw = task?.created_at
  const moment = raw ? new Date(/([zZ]|[+-]\d{2}:?\d{2})$/.test(raw) ? raw : `${raw}Z`) : null
  if (!moment || Number.isNaN(moment.getTime())) return task?.date ? `${task.date} —` : '—'
  return `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())} ${pad(moment.getHours())}:${pad(moment.getMinutes())}`
}

// Project / canvas names for detail rows, from the grouped projects the ledger already returns.
export function placeIndex(data) {
  const projects = new Map(), workflows = new Map()
  for (const project of data?.projects || []) {
    projects.set(project.id, project.title)
    for (const workflow of project.workflows || []) workflows.set(workflow.id, workflow.title)
  }
  return { projects, workflows }
}

export function taskPlace(task, index) {
  if (!task?.project_id || task.project_id === UNASSIGNED_PROJECT) return '未归属项目'
  const project = index?.projects.get(task.project_id) || '画布已删除'
  const workflow = task.workflow_id ? index?.workflows.get(task.workflow_id) : null
  return workflow ? `${project} / ${workflow}` : project
}
