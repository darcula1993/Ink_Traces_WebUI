import { nextNodeGroupTitle } from './canvasGroups.js'
import { selectedProvider } from './canvasProviderSelection.js'

export const TEMPLATE_NODE_TYPES = Object.freeze(['image', 'video', 'audio', 'text'])
export const TEMPLATE_GROUP_COLORS = Object.freeze(['green', 'cyan', 'blue', 'purple', 'amber', 'rose'])
export const TEMPLATE_MAX_NODES = 40
export const TEMPLATE_NAME_MAX = 80
export const TEMPLATE_API_BASE = '/api/canvas/templates'

const SAFE_PARAM_KEYS = new Set([
  'model', 'ratio', 'resolution', 'duration', 'video_mode', 'omni_reference_task_type', 'generate_audio',
  'watermark', 'lock_aspect_ratio', 'output_format', 'background', 'custom_width', 'custom_height',
  'speaker', 'sample_rate', 'enable_subtitle',
])

const GENERATION_TYPES = new Set(['image', 'video', 'audio'])

function fallbackId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replace(/-/g, '')
  }
  return `t_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}

function cloneValue(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value))
}

function sanitizeParams(nodeType, params) {
  if (nodeType === 'text' || !params || typeof params !== 'object' || Array.isArray(params)) return {}
  const next = {}
  for (const [key, value] of Object.entries(params)) {
    if (!SAFE_PARAM_KEYS.has(key)) continue
    next[key] = cloneValue(value)
  }
  return next
}

function sanitizeProviderSelection(nodeType, selection) {
  if (!GENERATION_TYPES.has(nodeType)) return null
  if (!selection || typeof selection !== 'object' || typeof selection.provider !== 'string' || !selection.provider) {
    return null
  }
  return {
    provider: selection.provider,
    profile_id: typeof selection.profile_id === 'string' && selection.profile_id ? selection.profile_id : null,
  }
}

function sanitizeSize(nodeType, size) {
  if (nodeType === 'text' || !size || typeof size !== 'object') return null
  const scale = Number(size.scale)
  if (!Number.isFinite(scale) || scale < 0.25 || scale > 4) return null
  return { scale }
}

/**
 * Extract a reusable structural template from a node group inside a canvas document.
 * Strips all runtime & media state (task, asset, candidates, references, mentions,
 * characterRefs, upstreamStale). Clears prompt text when includePrompts is false.
 */
export function extractGroupTemplate(doc, groupId, { name, includePrompts = false } = {}) {
  if (!doc || typeof doc !== 'object') throw new Error('画布文档无效')
  const groups = Array.isArray(doc.groups) ? doc.groups : []
  const group = groups.find(item => item?.id === groupId)
  if (!group) throw new Error('未找到指定的节点组')

  const nodesById = new Map((Array.isArray(doc.nodes) ? doc.nodes : []).map(node => [node.id, node]))
  const memberNodes = []
  let skippedAssetCount = 0

  for (const memberId of Array.isArray(group.nodeIds) ? group.nodeIds : []) {
    const node = nodesById.get(memberId)
    if (!node) continue
    if (node.type === 'asset') {
      skippedAssetCount += 1
      continue
    }
    if (!TEMPLATE_NODE_TYPES.includes(node.type)) continue
    memberNodes.push(node)
  }

  if (!memberNodes.length) {
    throw new Error('该节点组内没有可保存的结构节点（素材节点不随结构模板保存）')
  }
  if (memberNodes.length > TEMPLATE_MAX_NODES) {
    throw new Error(`节点组模板最多支持 ${TEMPLATE_MAX_NODES} 个节点`)
  }

  const trimmedName = String(name ?? group.title ?? '').trim()
  if (!trimmedName) throw new Error('模板名称不能为空')
  const finalName = trimmedName.slice(0, TEMPLATE_NAME_MAX)

  const originX = Math.min(...memberNodes.map(node => Number(node.x) || 0))
  const originY = Math.min(...memberNodes.map(node => Number(node.y) || 0))

  const idMap = new Map()
  const templateNodes = memberNodes.map((node, index) => {
    const localId = `n${index}`
    idMap.set(node.id, localId)
    const size = sanitizeSize(node.type, node.size)
    return {
      id: localId,
      dx: Math.round((Number(node.x) || 0) - originX),
      dy: Math.round((Number(node.y) || 0) - originY),
      type: node.type,
      title: String(node.title || '').slice(0, 240),
      params: sanitizeParams(node.type, node.params),
      providerSelection: sanitizeProviderSelection(node.type, node.providerSelection),
      text: includePrompts ? String(node.text || '') : '',
      ...(size ? { size } : {}),
    }
  })

  const seenEdges = new Set()
  const templateEdges = []
  for (const edge of Array.isArray(doc.edges) ? doc.edges : []) {
    const src = idMap.get(edge?.source)
    const dst = idMap.get(edge?.target)
    if (!src || !dst || src === dst) continue
    const key = `${src}->${dst}`
    if (seenEdges.has(key)) continue
    seenEdges.add(key)
    templateEdges.push({ source: src, target: dst })
  }

  const groupTitle = String(group.title || '').trim().slice(0, 100) || finalName
  const payload = {
    groupTitle,
    ...(TEMPLATE_GROUP_COLORS.includes(group.color) ? { groupColor: group.color } : {}),
    nodes: templateNodes,
    edges: templateEdges,
  }

  return {
    name: finalName,
    include_prompts: Boolean(includePrompts),
    payload,
    skippedAssetCount,
  }
}

function resolveGroupTitle(desiredTitle, existingGroups = []) {
  const existing = Array.isArray(existingGroups) ? existingGroups : []
  const used = new Set(existing.map(group => group?.title).filter(Boolean))
  const base = String(desiredTitle || '').trim().slice(0, 100)
  if (!base || /^节点组[1-9]\d*$/.test(base)) {
    return base && !used.has(base) ? base : nextNodeGroupTitle(existing)
  }
  if (!used.has(base)) return base
  let suffix = 2
  while (true) {
    const tag = ` ${suffix}`
    const candidate = `${base.slice(0, Math.max(1, 100 - tag.length))}${tag}`
    if (!used.has(candidate)) return candidate
    suffix += 1
  }
}

/**
 * Instantiate a saved group template at anchorPoint with fresh IDs for all nodes,
 * edges, and the node group. Checks each node's providerSelection against capabilities:
 * - If still available, retains it.
 * - If disabled/deleted/unavailable, retains the original providerSelection AND reports
 *   it in unavailableBindings without EVER silently switching to another paid account.
 */
export function instantiateGroupTemplate(
  template,
  anchorPoint,
  capabilities = null,
  { newId, existingGroups = [] } = {},
) {
  const payload = template?.payload && typeof template.payload === 'object' ? template.payload : template
  if (!payload || !Array.isArray(payload.nodes) || !payload.nodes.length) {
    throw new Error('模板内容无效或不包含任何节点')
  }
  if (payload.nodes.length > TEMPLATE_MAX_NODES) {
    throw new Error(`模板节点数超过上限（最多 ${TEMPLATE_MAX_NODES} 个）`)
  }

  const makeId = typeof newId === 'function' ? newId : fallbackId
  const anchorX = Number.isFinite(Number(anchorPoint?.x)) ? Number(anchorPoint.x) : 0
  const anchorY = Number.isFinite(Number(anchorPoint?.y)) ? Number(anchorPoint.y) : 0
  const keepPrompts = template?.include_prompts !== false

  const indexToNewId = []
  const localIdToNewId = new Map()
  const unavailableBindings = []

  const nodes = payload.nodes.map((tplNode, index) => {
    if (!TEMPLATE_NODE_TYPES.includes(tplNode?.type)) {
      throw new Error('模板包含不支持的节点类型')
    }
    const x = Math.round(anchorX + (Number(tplNode.dx) || 0))
    const y = Math.round(anchorY + (Number(tplNode.dy) || 0))
    if (!Number.isFinite(x) || !Number.isFinite(y) || Math.abs(x) > 1e6 || Math.abs(y) > 1e6) {
      throw new Error('模板套用位置超出画布坐标范围')
    }

    const freshId = makeId()
    indexToNewId[index] = freshId
    if (typeof tplNode.id === 'string' && tplNode.id) {
      localIdToNewId.set(tplNode.id, freshId)
    }

    const title = String(tplNode.title || '').slice(0, 240)
    const selection = sanitizeProviderSelection(tplNode.type, tplNode.providerSelection)

    if (selection && GENERATION_TYPES.has(tplNode.type)) {
      const available = selectedProvider(capabilities, selection, tplNode.type)
      if (!available) {
        unavailableBindings.push({
          nodeId: freshId,
          nodeTitle: title || tplNode.type,
          nodeType: tplNode.type,
          providerSelection: { ...selection },
          reason: '模板节点绑定的接口已停用或已删除，已保留原绑定且未自动切换其他账号，请手动重新选择。',
        })
      }
    }

    const size = sanitizeSize(tplNode.type, tplNode.size)
    return {
      id: freshId,
      type: tplNode.type,
      title,
      x,
      y,
      text: keepPrompts ? String(tplNode.text || '') : '',
      providerSelection: selection,
      params: sanitizeParams(tplNode.type, tplNode.params),
      asset: null,
      candidates: [],
      selectedCandidateId: null,
      task: null,
      ...(size ? { size } : {}),
    }
  })

  const resolveEndpoint = ref => {
    if (typeof ref === 'number' && Number.isInteger(ref) && ref >= 0 && ref < indexToNewId.length) {
      return indexToNewId[ref]
    }
    if (typeof ref === 'string' && localIdToNewId.has(ref)) {
      return localIdToNewId.get(ref)
    }
    return null
  }

  const seenEdges = new Set()
  const edges = []
  for (const tplEdge of Array.isArray(payload.edges) ? payload.edges : []) {
    const rawSrc = 'source' in (tplEdge || {}) ? tplEdge.source : tplEdge?.sourceIndex
    const rawDst = 'target' in (tplEdge || {}) ? tplEdge.target : tplEdge?.targetIndex
    const source = resolveEndpoint(rawSrc)
    const target = resolveEndpoint(rawDst)
    if (!source || !target || source === target) continue
    const key = `${source}->${target}`
    if (seenEdges.has(key)) continue
    seenEdges.add(key)
    edges.push({ id: makeId(), source, target })
  }

  const groupTitle = resolveGroupTitle(payload.groupTitle || template?.name, existingGroups)
  const group = {
    id: makeId(),
    title: groupTitle,
    nodeIds: nodes.map(node => node.id),
    ...(TEMPLATE_GROUP_COLORS.includes(payload.groupColor) ? { color: payload.groupColor } : {}),
  }

  return {
    nodes,
    edges,
    group,
    unavailableBindings,
  }
}

async function parseJsonResponse(response, fallbackError) {
  let data = null
  try {
    data = await response.json()
  } catch {
    data = null
  }
  if (!response.ok || data?.success === false) {
    const error = new Error(data?.error || `${fallbackError}（${response.status}）`)
    error.status = response.status
    error.response = { status: response.status, data }
    throw error
  }
  return data || {}
}

export async function listCanvasTemplates() {
  const response = await fetch(TEMPLATE_API_BASE, {
    method: 'GET',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
  return (await parseJsonResponse(response, '载入模板列表失败')).templates || []
}

export async function createCanvasTemplate({ name, include_prompts = false, payload }) {
  const response = await fetch(TEMPLATE_API_BASE, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ name, include_prompts: Boolean(include_prompts), payload }),
  })
  return (await parseJsonResponse(response, '保存结构模板失败')).template
}

export async function deleteCanvasTemplate(templateId) {
  const response = await fetch(`${TEMPLATE_API_BASE}/${encodeURIComponent(templateId)}`, {
    method: 'DELETE',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
  return parseJsonResponse(response, '删除结构模板失败')
}
