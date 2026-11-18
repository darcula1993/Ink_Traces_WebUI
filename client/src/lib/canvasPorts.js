// CANVAS-PORTS-LIB-20261117: dynamic reference ports, derived only (spec §4, user rulings §8).
// Ports consume resolveNodeInputs output and never sort on their own, so port N of a kind
// is @图片N / @视频N / @音频N and the submission order. Nothing here writes the document:
// old canvases are read from referenceOrder (or the resolveNodeInputs fallback) as is.
import {resolveNodeInputs,mediaKind,canConnect} from './canvasReferences.js'
import {ACCEPTED_REFERENCE_KINDS,referenceLimits} from './canvasReferenceDrop.js'

export const PORT_KINDS = ['image','video','audio']
const KIND = {image:'图片',video:'视频',audio:'音频'}
const NODE = {image:'图像',video:'视频',audio:'音频'}
export const UNKNOWN_LIMIT_HINT = '请先选择接口以确定参考上限'

// Connected sources that have no result yet: they count toward the limit (user 11-17 Q8)
// but get no number and no @ mention.
export function pendingReferenceEdges(node, nodes, edges) {
  const byId = new Map(nodes.map(item => [item.id,item]))
  return edges.filter(edge => edge.target === node.id).map(edge => ({edge,source:byId.get(edge.source)}))
    .filter(({source}) => source && source.type !== 'text' && !source.asset && canConnect(source,node))
    .map(({edge,source}) => ({edgeId:edge.id,sourceId:source.id,kind:mediaKind(source),title:source.title||''}))
}

function overReason(node, kind, limits) {
  if (!(ACCEPTED_REFERENCE_KINDS[node.type] || []).includes(kind)) return `${NODE[node.type]}生成节点不接受${KIND[kind]}参考`
  if (node.type === 'video' && node.params?.video_mode === 'keyframe') return kind === 'image' ? '首尾帧最多两张图片' : '首尾帧模式只接受图片'
  if (!limits[kind]) return `当前设置不接受${KIND[kind]}参考`
  return node.type === 'video' ? `所选视频模型最多 ${limits[kind]} 个${KIND[kind]}参考` : node.type === 'audio' ? `音频参考最多 ${limits[kind]} ${kind==='image'?'张图片':'段音频'}` : `图像节点最多 ${limits[kind]} 张参考图`
}

/**
 * Ports of one generation node, grouped image → video → audio.
 * Group: {kind, limit (number|null when unknown), count (occupied+pending), overLimit (number of over-limit ports), conflict, ports}
 * Port: {kind, index (per-kind number, null for pending/empty), assetId, edgeId, source ('edge'|'library'|'pending'|'empty'),
 *        label, role ('first'|'last'|null), overLimit, reason, name}
 * Accepted groups are always listed; a group the node/mode does not accept is listed only when occupied (all over-limit).
 */
export function deriveNodePorts(node, nodes, edges, {provider=null,inputs=null}={}) {
  const accepted = ACCEPTED_REFERENCE_KINDS[node?.type]
  if (!accepted) return {groups:[],limitsKnown:false,overLimitCount:0,hint:''}
  const resolved = inputs || resolveNodeInputs(node,nodes,edges), limits = referenceLimits(node,provider)
  const keyframe = node.type === 'video' && node.params?.video_mode === 'keyframe'
  const incoming = edges.filter(edge => edge.target === node.id), byId = new Map(nodes.map(item => [item.id,item]))
  const edgeFor = assetId => incoming.find(edge => byId.get(edge.source)?.asset?.id === assetId)?.id || null
  const pending = pendingReferenceEdges(node,nodes,edges)
  const shown = PORT_KINDS.filter(kind => (accepted.includes(kind) && !(keyframe && kind !== 'image')) || resolved.assets.some(asset => asset.kind === kind) || pending.some(item => item.kind === kind))
  const occupiedKinds = new Set([...resolved.assets.map(asset => asset.kind),...pending.map(item => item.kind)])
  const audioConflict = node.type === 'audio' && occupiedKinds.has('image') && occupiedKinds.has('audio')
  const groups = shown.map(kind => {
    const limit = limits ? limits[kind] ?? 0 : (accepted.includes(kind) ? null : 0)
    const reason = overReason(node,kind,limits || {})
    const ports = []
    resolved.assets.filter(asset => asset.kind === kind).forEach((asset,i) => {
      const edgeId = edgeFor(asset.id), index = i+1
      const role = keyframe && kind === 'image' ? (index === 1 ? 'first' : index === 2 ? 'last' : null) : null
      ports.push({kind,index,assetId:asset.id,edgeId,source:edgeId?'edge':'library',name:asset.name||'',role,label:role==='first'?'首帧':role==='last'?'尾帧':`${KIND[kind]}参考 ${index}`})
    })
    for (const item of pending.filter(item => item.kind === kind)) ports.push({kind,index:null,assetId:null,edgeId:item.edgeId,sourceId:item.sourceId,source:'pending',name:item.title,role:null,label:'待生成'})
    ports.forEach((port,i) => { port.overLimit = limit !== null && i+1 > limit; port.reason = port.overLimit ? reason : '' })
    const count = ports.length
    // Audio node: image and audio are exclusive, so an occupied kind blocks the other's empty port.
    const blockedByOther = node.type === 'audio' && PORT_KINDS.some(other => other !== kind && occupiedKinds.has(other))
    if ((limit === null || count < limit) && !blockedByOther) ports.push({kind,index:null,assetId:null,edgeId:null,source:'empty',name:'',role:null,label:`添加${KIND[kind]}参考`,overLimit:false,reason:limit===null?UNKNOWN_LIMIT_HINT:''})
    return {kind,limit,count,overLimit:ports.filter(port => port.overLimit).length,conflict:audioConflict&&occupiedKinds.has(kind),ports}
  })
  return {groups,limitsKnown:!!limits,overLimitCount:groups.reduce((sum,group) => sum+group.overLimit,0),hint:limits?'':UNKNOWN_LIMIT_HINT}
}

// User 11-17 Q2: nothing is removed automatically; this is the explicit "移除超出的 K 个参考"
// result (group tail first, by port order). Returns the same document when nothing is over.
// Mentions are reconciled by the caller's normal edit path (reconcileReferenceMentions).
export function removeOverLimitReferences(document, nodeId, options={}) {
  const node = document.nodes.find(item => item.id === nodeId)
  if (!node) throw new Error('节点已不存在，请重新选择')
  const over = deriveNodePorts(node,document.nodes,document.edges,options).groups.flatMap(group => group.ports.filter(port => port.overLimit))
  if (!over.length) return {document,removed:[]}
  const assetIds = new Set(over.map(port => port.assetId).filter(Boolean)), pendingEdges = new Set(over.filter(port => port.source === 'pending').map(port => port.edgeId))
  const byId = new Map(document.nodes.map(item => [item.id,item]))
  const edges = document.edges.filter(edge => !(edge.target === nodeId && (pendingEdges.has(edge.id) || assetIds.has(byId.get(edge.source)?.asset?.id))))
  const next = {...node}
  if (node.referenceAssets) next.referenceAssets = node.referenceAssets.filter(asset => !assetIds.has(asset.id))
  if (node.referenceOrder) next.referenceOrder = node.referenceOrder.filter(id => !assetIds.has(id))
  return {document:{...document,edges,nodes:document.nodes.map(item => item.id === nodeId ? next : item)},removed:over.map(({kind,index,assetId,edgeId,source,label}) => ({kind,index,assetId,edgeId,source,label}))}
}

// Why a new reference of `kind` cannot go onto the node (drop on node body / empty port), or null.
// Pending connections count (Q8); unknown limits never block. Reason wording follows referenceDropError.
export function portAddError(node, nodes, edges, kind, options={}) {
  const accepted = ACCEPTED_REFERENCE_KINDS[node?.type]
  if (!accepted) return '只能把素材作为参考添加到图像、视频或音频生成节点'
  const keyframe = node.type === 'video' && node.params?.video_mode === 'keyframe'
  if (!accepted.includes(kind)) return `${NODE[node.type]}生成节点不接受${KIND[kind] || '该类型'}参考`
  if (keyframe && kind !== 'image') return '首尾帧模式只接受图片'
  const {groups} = deriveNodePorts(node,nodes,edges,options), group = groups.find(item => item.kind === kind)
  if (node.type === 'audio' && groups.some(other => other.kind !== kind && other.count)) return '音频参考不能混用图片和音频'
  if (group && group.limit !== null && group.count >= group.limit) return keyframe ? `首尾帧最多两张图片，当前已有 ${group.count} 张` : overReason(node,kind,referenceLimits(node,options.provider))
  return null
}
