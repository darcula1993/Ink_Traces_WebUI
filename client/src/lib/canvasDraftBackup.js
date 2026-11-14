// FIX-B2-20261114 rework (B2-FLUSH-1/2): local backup of unsaved canvas edits.
// A page-exit flush cannot wait for its keepalive PUT (it may fail or get 409 after the page is gone), so the
// unsaved draft is also kept in localStorage; the next time this canvas opens, a draft the server does not
// contain is offered for restore / discard and never applied automatically. A confirmed save clears it.
import { serverDocument } from './canvasTaskPolling.js'

const PREFIX = 'nanobanana.canvasDraft.'
export const DRAFT_MAX_CHARS = 2 * 1024 * 1024
const key = workflowId => `${PREFIX}${workflowId}`

// `known` is the server document the draft was based on; its version ids per node are kept (knownCandidates)
// so a restore can tell versions written back after the draft from versions the user deleted in the draft.
const candidateIds = document => Object.fromEntries((document?.nodes || []).map(node => [node.id, (node.candidates || []).map(asset => asset?.id).filter(Boolean)]))
export function writeDraft({ workflowId, baseRevision, title, document, known = null }, storage = globalThis.localStorage) {
  if (!workflowId || !storage) return false
  try {
    const value = JSON.stringify({ workflowId, baseRevision, title, document: serverDocument(document), ...(known ? { knownCandidates: candidateIds(known) } : {}), savedAt: Date.now() })
    if (value.length > DRAFT_MAX_CHARS) return false
    storage.setItem(key(workflowId), value)
    return true
  } catch { return false }
}
export function readDraft(workflowId, storage = globalThis.localStorage) {
  if (!workflowId || !storage) return null
  try {
    const draft = JSON.parse(storage.getItem(key(workflowId)) || 'null')
    return draft && draft.workflowId === workflowId && Array.isArray(draft.document?.nodes) ? draft : null
  } catch { return null }
}
export function clearDraft(workflowId, storage = globalThis.localStorage) {
  if (!workflowId || !storage) return
  try { storage.removeItem(key(workflowId)) } catch { /* storage unavailable */ }
}

const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().filter(name => value[name] !== undefined).map(name => [name, canonical(value[name])])) : value
const same = (a, b) => JSON.stringify(canonical(a ?? null)) === JSON.stringify(canonical(b ?? null))
// Fields the server may write back after the draft was taken (task terminal results).
const WRITEBACK = ['task', 'candidates', 'asset', 'selectedCandidateId', 'upstreamStale']
const withoutWriteback = node => Object.fromEntries(Object.entries(node).filter(([name]) => !WRITEBACK.includes(name)))
function nodeIncluded(draft, server) {
  if (!server) return false
  if (same(draft, server)) return true
  if (!same(withoutWriteback(draft), withoutWriteback(server))) return false
  // A write-back only adds versions; every version in the draft must still be on the server.
  const ids = new Set((server.candidates || []).map(asset => asset.id))
  return (draft.candidates || []).every(asset => ids.has(asset.id))
}
/** True when the server workflow already holds the draft's content (viewport ignored). */
export function draftIncluded(draft, workflow) {
  if (!draft || !workflow) return true
  if ((draft.title || '') !== (workflow.title || '')) return false
  const doc = serverDocument({ nodes: [], edges: [], groups: [], ...(workflow.document || {}) }), mine = draft.document
  if (!same(mine.edges || [], doc.edges || []) || !same(mine.groups || [], doc.groups || [])) return false
  if ((mine.nodes || []).length !== (doc.nodes || []).length) return false
  const nodes = new Map(doc.nodes.map(node => [node.id, node]))
  return mine.nodes.every(node => nodeIncluded(node, nodes.get(node.id)))
}

/**
 * DRAFT-MERGE-FIX-20261114: restore a draft onto the latest server-derived document (`base`: the opened
 * server version plus any results this window has already taken from task-sync), field by field.
 * - User fields (text, params, position, references, nodes/edges/groups, title) come from the draft.
 * - For a draft node whose task.id equals the base node's task.id, the server owns the task state: task is
 *   taken from the base; versions on the base that are neither in the draft nor in the draft's known base
 *   (knownCandidates) were written back after the draft and are appended, the written-back selection
 *   becoming current (asset/selectedCandidateId, upstreamStale removed) as in contract C. Versions the
 *   user deleted in the draft (present in knownCandidates) stay deleted. Drafts without knownCandidates
 *   (older format) treat every base-only version as written back, so nothing is lost.
 * - A draft node with another task (or none) than the base, or absent from the base, keeps the draft value.
 * The restore therefore never depends on a later poll to bring results back, and no save sends a stale
 * active task over a terminal one. Returns {document, merged:[nodeIds]}.
 */
export function mergeDraftDocument(draft, base) {
  const mine = draft.document, baseNodes = new Map((base?.nodes || []).map(node => [node.id, node])), known = draft.knownCandidates || null
  const merged = []
  const nodes = (mine.nodes || []).map(node => {
    const server = baseNodes.get(node.id)
    if (!server?.task?.id || Number(node.task?.id) !== Number(server.task.id)) return node
    const own = new Set([...(node.candidates || []), ...(known?.[node.id] || []).map(id => ({ id }))].map(asset => asset.id))
    const additions = (server.candidates || []).filter(asset => asset?.id && !own.has(asset.id))
    const task = { id: server.task.id, status: server.task.status, error: server.task.error || null, ...(server.task.progress != null ? { progress: server.task.progress } : {}) }
    if (!additions.length && same(task, node.task)) return node
    merged.push(node.id)
    if (!additions.length) return { ...node, task }
    const selected = additions.find(asset => asset.id === server.selectedCandidateId) || additions[0]
    const { upstreamStale: _stale, ...rest } = node
    return { ...rest, task, candidates: [...(node.candidates || []), ...additions], asset: selected, selectedCandidateId: selected.id }
  })
  return { document: { ...mine, nodes }, merged }
}
