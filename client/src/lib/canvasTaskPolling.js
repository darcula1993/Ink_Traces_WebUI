// Canvas task polling: one batch status request per cycle (max 100 ids per
// request), per-node error isolation, and identity checks so a response that
// arrives after the user switched canvases never writes into another graph.
import {ACTIVE_TASK_STATUSES,isActiveTaskStatus,isServerTaskStatus,isTerminalTaskStatus,sanitizeDocumentTasks} from './taskStatus.js'
import {serializableDocument} from './canvasStaleness.js'
export {ACTIVE_TASK_STATUSES}
export const isActiveTask = isActiveTaskStatus

export function activeTaskNodes(document) {
  return (document?.nodes || []).filter(node => node.task?.id && isActiveTask(node.task.status))
}

export function sameTaskState(task, next) {
  return task?.status === next.status && (task?.error || null) === (next.error || null) && Boolean(task?.resultUnknown) === Boolean(next.resultUnknown) && (task?.progress ?? null) === (next.progress ?? null)
}

/**
 * Collect runtime patches for active canvas tasks (CANVAS-WRITEBACK-20261114 D).
 *
 * The server writes task results back into the canvas document; the client no
 * longer imports or saves them. Non-terminal changes (status words, progress)
 * only update the interface. Terminal transitions are returned in `terminal`
 * so the caller asks the server (task-sync) for the written-back node fields.
 *
 * fetchStatuses(ids) -> {tasks, missing, failed}
 * fetchDetail(taskId) -> {id,status,error,resultUnknown}  (failed tasks on servers whose status preview lacks result_unknown)
 * isCurrent() -> false once the workflow changed or the component unmounted
 * getDocument() -> latest document (read after each await)
 *
 * Returns {patches: Map(nodeId -> {task, additions:[]}), terminal: Map(nodeId -> {id,status,error,resultUnknown}), failed, stale, anomalies}
 * anomalies: Map(nodeId -> raw status) for responses outside the server vocabulary;
 * those nodes keep their previous task state and are never patched.
 */
export async function collectTaskUpdates({ document, fetchStatuses, fetchDetail, isCurrent, getDocument }) {
  const pending = activeTaskNodes(document), patches = new Map(), terminal = new Map(), anomalies = new Map()
  if (!pending.length) return { patches, terminal, failed: 0, stale: false, anomalies }
  const ids = [...new Set(pending.map(node => Number(node.task.id)))]
  const batch = await fetchStatuses(ids)
  if (!isCurrent()) return { patches, terminal, failed: 0, stale: true, anomalies }
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
      let next = { id: taskId, status: status.status, error: status.error || null, progress: Number.isFinite(Number(status.progress)) ? Number(status.progress) : null, resultUnknown: status.status === 'failed' && status.result?.result_unknown === true }
      const knowsUnknown = status.result && Object.hasOwn(status.result, 'result_unknown')
      if (status.status === 'failed' && !knowsUnknown) {
        const detail = await fetchDetail(taskId)
        if (!isCurrent()) return { patches, terminal, failed, stale: true, anomalies }
        if (!isServerTaskStatus(detail.status)) { anomalies.set(node.id, String(detail.status)); continue }
        next = { id: taskId, status: detail.status, error: detail.error || null, resultUnknown: Boolean(detail.resultUnknown) }
      }
      const latest = getDocument().nodes.find(item => item.id === node.id)
      if (!latest || Number(latest.task?.id) !== taskId) continue
      if (isTerminalTaskStatus(next.status)) terminal.set(node.id, next)
      else if (!sameTaskState(latest.task, next)) patches.set(node.id, { task: next, additions: [] })
    } catch {
      if (!isCurrent()) return { patches, terminal, failed, stale: true, anomalies }
      failed++
    }
  }
  return { patches, terminal, failed, stale: false, anomalies }
}

/**
 * Turn a task-sync response into applyTaskUpdates patches (field rules F3–F8 of
 * the canvas write-back spec).
 *
 * serverNodes: {node_id: {task, asset, candidates, selectedCandidateId}} written back by the server
 * terminal: Map(nodeId -> status-batch task) for resultUnknown (runtime only)
 * known: last server document this window saw; its candidates are not "new"
 *   (keeps a version deleted locally but not yet saved from coming back).
 * Returns {patches, missing:[nodeIds requested but not written back]}
 */
export function taskSyncPatches({ document, serverNodes, terminal, known = null }) {
  const patches = new Map(), missing = []
  const knownNodes = new Map((known?.nodes || []).map(node => [node.id, node]))
  for (const [nodeId, status] of terminal) {
    const local = document.nodes.find(item => item.id === nodeId), remote = serverNodes?.[nodeId]
    if (!local || Number(local.task?.id) !== Number(status.id)) continue
    const task = remote?.task
    if (!task || Number(task.id) !== Number(status.id) || !isTerminalTaskStatus(task.status)) { missing.push(nodeId); continue }
    const seen = new Set([...(local.candidates || []), ...(knownNodes.get(nodeId)?.candidates || [])].map(asset => asset.id))
    const additions = (Array.isArray(remote.candidates) ? remote.candidates : []).filter(asset => asset?.id && !seen.has(asset.id))
    const next = { id: Number(task.id), status: task.status, error: task.error || null, resultUnknown: task.status === 'failed' && Boolean(status.resultUnknown) }
    const selected = additions.find(asset => asset.id === remote.selectedCandidateId)
    if (!sameTaskState(local.task, next) || additions.length) patches.set(nodeId, { task: next, additions, ...(selected ? { selected } : {}) })
  }
  return { patches, missing }
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
        ...(patch.additions.length ? { asset: patch.selected || patch.additions[0], selectedCandidateId: (patch.selected || patch.additions[0]).id } : {}),
      }
    }),
  }
}

// V140 #14 / CANVAS-WRITEBACK-20261114: polling never saves the canvas. Progress
// and status words are runtime-only; terminal results are written by the server.

// Canonical JSON (object keys sorted) of what the server stores: runtime-only
// task fields and invalid markers are removed exactly as before a save.
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().filter(key => value[key] !== undefined).map(key => [key, canonical(value[key])])) : value
const same = (a, b) => JSON.stringify(canonical(a ?? null)) === JSON.stringify(canonical(b ?? null))
export const serverDocument = document => sanitizeDocumentTasks(serializableDocument(document))
export function sameServerDocument(local, remote) { return same(serverDocument(local), remote) }

/**
 * Merged save (contract C): the server took the sent document and overlaid the
 * written-back fields of some nodes. Rebuild the local document from the
 * returned one while keeping whatever the user typed after the PUT was sent.
 *
 * Per node field: when the returned value differs from the sent one, take it
 * unless the user changed that field locally since sending (then keep the local
 * value; for candidates keep local and append the returned additions). Nodes
 * deleted locally stay deleted; returned nodes the client never sent are ignored.
 */
export function mergeSavedDocument({ sent, returned, local }) {
  if (!returned?.nodes || !sent?.nodes) return local
  const sentNodes = new Map(sent.nodes.map(node => [node.id, node])), returnedNodes = new Map(returned.nodes.map(node => [node.id, node]))
  const current = serverDocument(local), currentNodes = new Map(current.nodes.map(node => [node.id, node]))
  let changed = false
  const nodes = local.nodes.map(node => {
    const was = sentNodes.get(node.id), server = returnedNodes.get(node.id), mine = currentNodes.get(node.id)
    if (!was || !server) return node
    let next = node
    for (const key of new Set([...Object.keys(was), ...Object.keys(server)])) {
      if (same(server[key], was[key])) continue
      if (key === 'task' && Number(mine.task?.id) !== Number(was.task?.id)) continue
      if (same(mine[key], was[key])) {
        next = { ...next }
        if (server[key] === undefined) delete next[key]; else next[key] = server[key]
      } else if (key === 'candidates' && Array.isArray(server.candidates)) {
        const ids = new Set([...(was.candidates || []), ...(mine.candidates || [])].map(asset => asset.id))
        const additions = server.candidates.filter(asset => !ids.has(asset.id))
        if (additions.length) next = { ...next, candidates: [...(next.candidates || []), ...additions] }
      } else continue
      changed = true
    }
    // A selection must point at an existing version (server schema).
    if (next !== node && next.selectedCandidateId && !(next.candidates || []).some(asset => asset.id === next.selectedCandidateId)) next = { ...next, selectedCandidateId: node.selectedCandidateId }
    return next
  })
  return changed ? { ...local, nodes } : local
}

// Contract C response shape: {merged:true, revision, document} at the top level or inside `workflow`.
export function normalizeSavedWorkflow(id, result) {
  const workflow = result.workflow || {}
  const merged = result.merged === true || workflow.merged === true
  const { merged: _merged, ...rest } = workflow
  return { ...rest, id: rest.id ?? id, revision: rest.revision ?? result.revision, ...(merged ? { merged: true, document: rest.document ?? result.document } : {}) }
}
