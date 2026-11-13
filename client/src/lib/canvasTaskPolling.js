// Canvas task polling: one batch status request per cycle (max 100 ids per
// request), per-node error isolation, and identity checks so a response that
// arrives after the user switched canvases never writes into another graph.
import {ACTIVE_TASK_STATUSES,isActiveTaskStatus,isServerTaskStatus} from './taskStatus.js'
export {ACTIVE_TASK_STATUSES}
export const isActiveTask = isActiveTaskStatus

export function activeTaskNodes(document) {
  return (document?.nodes || []).filter(node => node.task?.id && isActiveTask(node.task.status))
}

export function sameTaskState(task, next) {
  return task?.status === next.status && (task?.error || null) === (next.error || null) && Boolean(task?.resultUnknown) === Boolean(next.resultUnknown) && (task?.progress ?? null) === (next.progress ?? null)
}

/**
 * Collect runtime patches for active canvas tasks.
 *
 * fetchStatuses(ids) -> {tasks, missing, failed}
 * fetchDetail(taskId) -> {id,status,error,resultUnknown,assets}  (terminal transitions only)
 * isCurrent() -> false once the workflow changed or the component unmounted
 * getDocument() -> latest document (read after each await)
 *
 * Returns {patches: Map(nodeId -> {task, additions}), failed, stale, anomalies}
 * anomalies: Map(nodeId -> raw status) for responses outside the server vocabulary;
 * those nodes keep their previous task state and are never patched.
 */
export async function collectTaskUpdates({ document, fetchStatuses, fetchDetail, isCurrent, getDocument }) {
  const pending = activeTaskNodes(document), patches = new Map(), anomalies = new Map()
  if (!pending.length) return { patches, failed: 0, stale: false, anomalies: new Map() }
  const ids = [...new Set(pending.map(node => Number(node.task.id)))]
  const batch = await fetchStatuses(ids)
  if (!isCurrent()) return { patches, failed: 0, stale: true, anomalies }
  const statuses = new Map((batch.tasks || []).map(task => [Number(task.id), task]))
  const unavailable = new Set([...(batch.missing || []), ...(batch.failed || [])].map(Number))
  let failed = 0
  for (const node of pending) {
    const taskId = Number(node.task.id)
    if (unavailable.has(taskId)) { failed++; continue }
    const status = statuses.get(taskId)
    if (!status) { failed++; continue }
    if (!isServerTaskStatus(status.status)) { anomalies.set(node.id, String(status.status)); continue }
    try {
      let next = { id: taskId, status: status.status, error: status.error || null, progress: Number.isFinite(Number(status.progress)) ? Number(status.progress) : null, resultUnknown: status.status === 'failed' && status.result?.result_unknown === true }, assets = []
      const knowsUnknown = status.result && Object.hasOwn(status.result, 'result_unknown')
      if (status.status === 'succeeded' || (status.status === 'failed' && !knowsUnknown)) {
        const detail = await fetchDetail(taskId)
        if (!isCurrent()) return { patches, failed, stale: true, anomalies }
        if (!isServerTaskStatus(detail.status)) { anomalies.set(node.id, String(detail.status)); continue }
        next = { id: taskId, status: detail.status, error: detail.error || null, resultUnknown: Boolean(detail.resultUnknown) }
        assets = detail.assets || []
      }
      const latest = getDocument().nodes.find(item => item.id === node.id)
      if (!latest || Number(latest.task?.id) !== taskId) continue
      const additions = assets.filter(asset => !latest.candidates?.some(old => old.id === asset.id))
      if (!sameTaskState(latest.task, next) || additions.length) patches.set(node.id, { task: next, additions })
    } catch {
      if (!isCurrent()) return { patches, failed, stale: true, anomalies }
      failed++
    }
  }
  return { patches, failed, stale: false, anomalies }
}

export function applyTaskUpdates(document, patches) {
  if (!patches.size) return document
  return {
    ...document,
    nodes: document.nodes.map(item => {
      const patch = patches.get(item.id)
      if (!patch || Number(item.task?.id) !== Number(patch.task.id)) return item
      // resultUnknown is runtime-only (the server document schema keeps task to id/status/error).
      const task = { id: patch.task.id, status: patch.task.status, error: patch.task.error || null, ...(patch.task.progress != null ? { progress: patch.task.progress } : {}) }
      const { upstreamStale, ...rest } = item
      // A successful regeneration clears the "上游已更新" marker.
      return {
        ...(patch.additions.length ? rest : item), task, candidates: [...(item.candidates || []), ...patch.additions],
        ...(patch.additions.length ? { asset: patch.additions[0], selectedCandidateId: patch.additions[0].id } : {}),
      }
    }),
  }
}

// V140 #14: progress is runtime-only (sanitized before every save). A poll whose
// patches only move progress must not write the canvas: each write bumps the
// revision, and a second window open on the same canvas would then be forced
// into the conflict flow by pure progress ticks.
export function patchesNeedSave(document, patches) {
  for (const [id, patch] of patches) {
    const node = document.nodes.find(item => item.id === id)
    if (!node || Number(node.task?.id) !== Number(patch.task.id)) continue
    if (patch.additions.length || node.task?.status !== patch.task.status || (node.task?.error || null) !== (patch.task.error || null)) return true
  }
  return false
}
