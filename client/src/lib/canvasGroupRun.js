// GROUP-RUN-20261115 B5: "运行组内全部" client. The server (canvas_group_run, contract in the task log)
// owns the run: topological order, submission, blocking and stop decisions. This module only calls the API
// and turns run/preview payloads into display text. It never edits node params/referenceOrder (the server
// fingerprints those to detect manual edits, rule 6).
import axios from 'axios'
import {formatUsd} from './canvasBatchRun.js'

const workflowUrl = id => `/api/canvas/workflows/${encodeURIComponent(id)}`
const data = async promise => (await promise).data

export const previewGroupRun = async (workflowId, groupId, revision) => (await data(axios.post(`${workflowUrl(workflowId)}/groups/${encodeURIComponent(groupId)}/run-preview`, {revision}))).preview
export const createGroupRun = async (workflowId, {groupId, revision, previewToken}) => (await data(axios.post(`${workflowUrl(workflowId)}/group-runs`, {group_id: groupId, revision, preview_token: previewToken}))).run
export const listActiveGroupRuns = async workflowId => (await data(axios.get(`${workflowUrl(workflowId)}/group-runs`, {params: {active: 1}}))).runs || []
export const getGroupRun = async (workflowId, runId) => (await data(axios.get(`${workflowUrl(workflowId)}/group-runs/${encodeURIComponent(runId)}`))).run
export const cancelGroupRun = async (workflowId, runId) => (await data(axios.post(`${workflowUrl(workflowId)}/group-runs/${encodeURIComponent(runId)}/cancel`, {}))).run
export const confirmGroupRun = async (workflowId, runId, confirmToken) => (await data(axios.post(`${workflowUrl(workflowId)}/group-runs/${encodeURIComponent(runId)}/confirm`, {confirm_token: confirmToken}))).run

export const ACTIVE_RUN_STATUSES = new Set(['running', 'awaiting_confirm'])
export const isActiveRun = run => !!run && ACTIVE_RUN_STATUSES.has(run.status)
// Node states that still belong to the run (the server's manual-generation guard uses the same set).
const OWNED_NODE_STATUSES = new Set(['waiting', 'submitting', 'submitted'])

export const RUN_STATUS_LABELS = {running: '运行中', awaiting_confirm: '等待确认新预估', completed: '已完成', stopped: '已停止', cancelled: '已取消'}
export const NODE_STATUS_LABELS = {waiting: '等待上游', submitting: '提交中', submitted: '已提交', succeeded: '成功', failed: '失败', cancelled: '已取消', unknown: '结果未知', blocked: '已阻断'}
export const REASON_LABELS = {
  upstream_failed: '上游失败', upstream_cancelled: '上游已取消', upstream_blocked: '上游被阻断', upstream_no_result: '上游没有写回结果',
  node_modified: '上游或本节点在运行中被修改，已阻断', upstream_modified: '上游或本节点在运行中被修改，已阻断', node_removed: '节点被删除或移出组',
  run_stopped: '整组已停止', user_cancelled: '整组已取消，未提交', submit_rejected: '提交前被服务端拒绝',
  task_failed: '任务失败', task_cancelled: '任务已取消', result_unknown: '结果未知',
}
export const STOP_REASON_LABELS = {result_unknown: '结果未知，已停整组，不自动重试', user_cancelled: '未提交的节点不再提交'}
export const SKIP_REASON_LABELS = {not_generation: '非生成节点，不运行'}
export const skipReasonText = reason => SKIP_REASON_LABELS[reason] || estimateReasonText(reason) || '原因未知'

const ERROR_HINTS = {
  revision_mismatch: '画布已有更新的保存版本，请重新运行以获取新预估',
  preview_stale: '组内节点或费用预估已变化，已刷新为新预估，请核对后重新确认',
  run_active: '该节点组已有进行中的运行，已显示其进度',
  node_busy: '组内有节点已有进行中的任务，请等其完成后再运行整组',
  group_empty: '组内没有图像、视频或音频生成节点',
  cycle: '组内连线存在循环依赖，无法确定运行顺序',
  upstream_missing: '有组外上游节点还没有结果，请先为其生成或选择结果',
  not_awaiting_confirm: '该运行当前无需确认',
  confirm_stale: '待确认的预估已变化，已刷新，请核对后重新确认',
  run_finished: '该运行已结束，无需取消',
  submit_unavailable: '服务端组运行提交尚未接入，未提交任何任务',
  group_not_found: '节点组不存在，请保存画布后重试',
  run_not_found: '运行记录不存在',
  invalid_request: '请求无效',
}

// {code, message, body}: server error text (already Chinese) plus our guidance for the known codes.
export function groupRunError(failure) {
  const body = failure?.response?.data || {}, code = body.code || null
  const server = typeof body.error === 'string' ? body.error : '', hint = code ? ERROR_HINTS[code] : ''
  const message = [server, hint && hint !== server ? hint : ''].filter(Boolean).join('：') || failure?.message || '操作失败，请重试'
  return {code, message, body}
}

// Unknown is never shown as zero.
// estimate.reason is a server code (canvas_group_run / canvas_group_submit / cost_estimate); never show the raw code.
export const ESTIMATE_REASON_LABELS = {
  no_price_data: '无价格资料', invalid_node: '节点配置无效，提交前会被拒绝', estimator_unavailable: '估价服务未接入',
  estimate_failed: '估价出错', invalid_estimate: '估价结果无效', no_estimate_snapshot: '缺少估价所需的尺寸参数',
  below_price_floor: '输出尺寸低于价格表下限', above_price_ceiling: '输出尺寸超出价格表上限', not_generation: '非生成节点', unknown: '原因未知',
}
export const estimateReasonText = reason => !reason ? '' : ESTIMATE_REASON_LABELS[reason] || (/^[a-z0-9_]+$/.test(reason) ? '原因未知' : reason)
export const estimateText = estimate => estimate?.known && Number.isFinite(Number(estimate.usd)) ? formatUsd(estimate.usd) : `费用未知${estimate?.reason ? `（${estimateReasonText(estimate.reason)}）` : ''}`
export function totalText(total = {}) {
  const known = Number(total.known_count) || 0, unknown = Number(total.unknown_count) || 0
  const base = known ? `${formatUsd(total.usd || 0)} USD` : '—'
  return unknown ? `${base}（另有 ${unknown} 个节点费用未知，未计入，不按零计）` : base
}

// Short header badge (detail goes to the tooltip): 运行中 2/5 · 等待确认 2/5 · 已完成 5/5 · 有失败 · 已停止 · 结果未知 · 已取消 1/3
export const BADGE_STOP_LABELS = {result_unknown: '结果未知'}
export function runBadgeText(run) {
  if (!run) return ''
  const done = run.progress?.done ?? 0, all = run.progress?.total ?? run.nodes?.length ?? 0, counts = run.counts || {}
  if (run.status === 'stopped') return `已停止 · ${BADGE_STOP_LABELS[run.stop_reason] || '见详情'}`
  if (run.status === 'awaiting_confirm') return `等待确认 ${done}/${all}`
  if (run.status === 'completed') return `已完成 ${done}/${all}${counts.failed || counts.unknown || counts.blocked ? ' · 有失败' : ''}`
  return `${RUN_STATUS_LABELS[run.status] || run.status} ${done}/${all}`
}
export function runProgressText(run) {
  if (!run) return ''
  const label = RUN_STATUS_LABELS[run.status] || run.status, done = run.progress?.done ?? 0, all = run.progress?.total ?? run.nodes?.length ?? 0
  const counts = run.counts || {}, issues = [['failed', '失败'], ['unknown', '结果未知'], ['blocked', '阻断']].filter(([key]) => counts[key]).map(([key, text]) => `${counts[key]} ${text}`)
  const stop = run.status === 'stopped' || run.status === 'cancelled' ? STOP_REASON_LABELS[run.stop_reason] || run.stop_reason || '' : ''
  return `${label} ${done}/${all}${issues.length ? ` · ${issues.join('，')}` : ''}${stop ? ` · ${stop}` : ''}`
}

export const nodeReasonText = node => node?.message || REASON_LABELS[node?.reason] || ''

// node_id -> {status,label,detail}: waiting/submitting marks for active runs, blocked marks for any tracked run.
export function nodeRunMarks(runs = []) {
  const marks = new Map()
  for (const run of runs) for (const node of run?.nodes || []) {
    const active = isActiveRun(run)
    if (node.status === 'blocked' || (active && (node.status === 'waiting' || node.status === 'submitting'))) {
      const reason = nodeReasonText(node).replace(/，已阻断$/, '')
      marks.set(node.node_id, {status: node.status, label: node.status === 'blocked' ? '已阻断' : node.status === 'submitting' ? '组运行：提交中' : '组运行：等待上游', detail: reason})
    }
  }
  return marks
}

// The active run that still owns this node (manual generation is refused by the server, so the UI disables it).
export const owningRun = (runs = [], nodeId) => runs.find(run => isActiveRun(run) && run.nodes?.some(node => node.node_id === nodeId && OWNED_NODE_STATUSES.has(node.status))) || null

// awaiting_confirm: per node confirmed vs. new estimate. delta is null when either side is unknown.
export function confirmRows(run) {
  if (!run?.confirm?.nodes) return []
  return run.confirm.nodes.map(item => {
    const node = run.nodes?.find(entry => entry.node_id === item.node_id), confirmed = item.confirmed || node?.estimate, next = item.estimate || node?.pending_estimate
    const delta = confirmed?.known && next?.known ? Number(next.usd) - Number(confirmed.usd) : null
    return {nodeId: item.node_id, confirmed, next, delta, deltaText: delta == null ? '差额未知（新预估或原预估为未知）' : `${delta >= 0 ? '+' : '-'}${formatUsd(Math.abs(delta))}`}
  })
}

// Keep one run per group: the newest by created_at/id.
export function latestRunsByGroup(runs = []) {
  const by = new Map()
  for (const run of runs) { const old = by.get(run.group_id); if (!old || String(run.created_at || '') > String(old.created_at || '') || (run.created_at === old.created_at && Number(run.id) > Number(old.id))) by.set(run.group_id, run) }
  return by
}

// D-L1: nodes submitted by the server while this page is open carry the task only in the server document.
// Point the local node at the run's task (runtime only: status 'pending'); the existing task poll then reads the
// real status and, when terminal, pulls the written-back result through task-sync. Never touches params/text/
// references (fingerprinted by the server), never replaces a newer local task or a local submission in flight.
export function adoptGroupRunTasks(document, runs = []) {
  const tasks = new Map()
  for (const run of runs) for (const node of run?.nodes || []) { const id = Number(node.task_id); if (Number.isInteger(id) && id > 0 && id > (tasks.get(node.node_id) || 0)) tasks.set(node.node_id, id) }
  if (!tasks.size) return document
  let changed = false
  const nodes = document.nodes.map(node => {
    const id = tasks.get(node.id), local = Number(node.task?.id) || 0
    if (!id || local >= id || node.task?.status === 'submitting') return node
    changed = true
    return {...node, task: {id, status: 'pending', error: null}}
  })
  return changed ? {...document, nodes} : document
}
