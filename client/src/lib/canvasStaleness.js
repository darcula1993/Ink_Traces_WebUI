// "上游已更新" markers. Only the direct consumers of a changed input are marked:
// a downstream node that already has a result becomes stale when the set of
// assets it would consume changes (an upstream selected result, a replaced
// asset, or an added/removed reference). Nothing here ever starts a generation.
const GENERATION = new Set(['image', 'video', 'audio'])

function inputSignatures(document) {
  const byId = new Map(document.nodes.map(node => [node.id, node])), inputs = new Map()
  for (const node of document.nodes) if (GENERATION.has(node.type)) inputs.set(node.id, new Set((node.referenceAssets || []).map(asset => asset.id)))
  for (const edge of document.edges || []) {
    const target = inputs.get(edge.target), source = byId.get(edge.source)
    if (!target || !source) continue
    target.add(source.type === 'text' ? `text:${source.id}:${source.text || ''}` : `asset:${source.id}:${source.asset?.id || ''}`)
  }
  return new Map([...inputs].map(([id, set]) => [id, [...set].sort().join('|')]))
}

// baselines (optional, runtime-only Map nodeId -> input signature) remembers the
// inputs a result was produced from when a node is first marked; returning to
// exactly those inputs (e.g. switching the upstream back to its original
// version) removes the marker again (V140 #7). The map is not persisted, so a
// marker restored from the server can only be cleared by regenerating or dismissing.
export function markStaleDownstream(before, after, baselines = null) {
  if (before === after || !before?.nodes || !after?.nodes) return after
  const previous = inputSignatures(before), next = inputSignatures(after)
  const oldNodes = new Map(before.nodes.map(node => [node.id, node]))
  let changed = false
  const nodes = after.nodes.map(node => {
    const old = oldNodes.get(node.id)
    if (!old || !GENERATION.has(node.type) || !node.asset) { baselines?.delete(node.id); return node }
    if (node.upstreamStale) {
      if (!old.upstreamStale) { baselines?.delete(node.id); return node }
      if (baselines?.has(node.id) && baselines.get(node.id) === next.get(node.id)) {
        baselines.delete(node.id); changed = true
        const { upstreamStale, ...rest } = node
        return rest
      }
      return node
    }
    baselines?.delete(node.id)
    if (previous.get(node.id) === next.get(node.id)) return node
    changed = true
    baselines?.set(node.id, previous.get(node.id))
    return { ...node, upstreamStale: true }
  })
  return changed ? { ...after, nodes } : after
}

export function clearStale(document, id) {
  return { ...document, nodes: document.nodes.map(node => node.id === id && node.upstreamStale ? (({ upstreamStale, ...rest }) => rest)(node) : node) }
}

// Server contract (CANVAS-STALE-20261112): only image/video/audio generation
// nodes may carry a boolean upstreamStale; text/asset nodes must never send it.
export const SERVER_ACCEPTS_STALE_MARKER = true
export function serializableDocument(document) {
  if (!document.nodes.some(node => 'upstreamStale' in node)) return document
  return { ...document, nodes: document.nodes.map(node => {
    if (!('upstreamStale' in node)) return node
    const { upstreamStale, ...rest } = node
    return SERVER_ACCEPTS_STALE_MARKER && GENERATION.has(node.type) && upstreamStale === true ? { ...rest, upstreamStale: true } : rest
  }) }
}
