// P0-UI-FIXES-20261120 (P0-4): lightweight shell ↔ canvas bridge for prompt-panel toggle and PNG Info hand-off.
import { imageCapabilities } from './imageGenerationRules.js'

export const CANVAS_TOGGLE_PROMPTS_EVENT = 'nb:canvas-toggle-prompts'
export const CANVAS_RAIL_STATE_EVENT = 'nb:canvas-rail-state'
export const CANVAS_APPLY_PNG_INFO_EVENT = 'nb:canvas-apply-png-info'
export const LAYER_OPEN_SOURCE_EVENT = 'nb:layer-open-source'
export const CANVAS_LOCATE_NODE_EVENT = 'nb:canvas-locate-node'
export const CANVAS_ADD_LAYER_ASSET_EVENT = 'ink-traces:canvas-add-layer-asset'
export const LAYER_RETURN_STORAGE_KEY = 'ink-traces.canvas-layer-return.v1'

let pendingPngInfo = null
let pendingLayerSource = null
let pendingLocateNode = null
let pendingCanvasAssetFromLayer = null

function dispatchBridgeEvent(name, detail) {
  const target = globalThis.window || globalThis
  if (typeof target.dispatchEvent !== 'function' || typeof globalThis.CustomEvent !== 'function') return false
  const event = new globalThis.CustomEvent(name, { detail, cancelable: true })
  target.dispatchEvent(event)
  return event.defaultPrevented
}

export function requestCanvasTogglePrompts() {
  return dispatchBridgeEvent(CANVAS_TOGGLE_PROMPTS_EVENT, { at: Date.now() })
}

export function announceCanvasRailPanel(panel) {
  dispatchBridgeEvent(CANVAS_RAIL_STATE_EVENT, { panel: panel || null })
}

export function queueCanvasPngInfo(metadata) {
  if (!metadata || typeof metadata !== 'object') return false
  pendingPngInfo = metadata
  return true
}

export function takePendingCanvasPngInfo() {
  const value = pendingPngInfo
  pendingPngInfo = null
  return value
}

// Dispatches live to a mounted CanvasStudio; if none handled it (e.g. switching from another mode), queues it once.
export function requestCanvasPngInfo(metadata) {
  if (!metadata || typeof metadata !== 'object') return false
  pendingPngInfo = null
  if (dispatchBridgeEvent(CANVAS_APPLY_PNG_INFO_EVENT, { metadata })) return true
  pendingPngInfo = metadata
  return false
}

const HEX_MEDIA_ID = /^[0-9a-f]{32}$/

function normalizeCanvasContext(canvasContext) {
  if (!canvasContext || typeof canvasContext !== 'object') return null
  const projectId = typeof (canvasContext.projectId ?? canvasContext.project_id) === 'string'
    ? String(canvasContext.projectId ?? canvasContext.project_id).trim()
    : ''
  const workflowId = typeof (canvasContext.workflowId ?? canvasContext.workflow_id) === 'string'
    ? String(canvasContext.workflowId ?? canvasContext.workflow_id).trim()
    : ''
  const nodeId = typeof (canvasContext.nodeId ?? canvasContext.node_id) === 'string'
    ? String(canvasContext.nodeId ?? canvasContext.node_id).trim()
    : ''
  if (!projectId && !workflowId && !nodeId) return null
  return {
    ...(projectId ? { projectId } : {}),
    ...(workflowId ? { workflowId } : {}),
    ...(nodeId ? { nodeId } : {}),
  }
}

// Extract a safe library media id or server-resolvable local URL from a canvas image node asset.
export function buildLayerSourceRequest(asset, title = '', canvasContext = null) {
  if (!asset || typeof asset !== 'object') return null
  const id = typeof asset.id === 'string' ? asset.id.trim() : ''
  const url = typeof asset.url === 'string' ? asset.url.trim() : ''
  let ref = ''
  if (HEX_MEDIA_ID.test(id)) ref = id
  else if (url.startsWith('/')) ref = url
  else if (id) ref = id
  if (!ref) return null
  const name = String(asset.name || title || '').trim()
  const context = normalizeCanvasContext(canvasContext)
  return context ? { ref, name, canvasContext: context } : { ref, name }
}

export function queueLayerSource(payload) {
  if (!payload || typeof payload !== 'object' || !payload.ref) return false
  const context = normalizeCanvasContext(payload.canvasContext)
  pendingLayerSource = {
    ref: String(payload.ref),
    name: String(payload.name || ''),
    ...(context ? { canvasContext: context } : {}),
  }
  return true
}

export function takePendingLayerSource() {
  const value = pendingLayerSource
  pendingLayerSource = null
  return value
}

// Hands an image ref to LayerStudio (switching mode via App.jsx if needed); never triggers decomposition.
export function requestLayerSource(payload) {
  if (!queueLayerSource(payload)) return false
  return dispatchBridgeEvent(LAYER_OPEN_SOURCE_EVENT, { source: pendingLayerSource })
}

function readLayerReturnStorage() {
  try {
    const storage = globalThis.sessionStorage
    if (!storage) return null
    const raw = storage.getItem(LAYER_RETURN_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch (_) {
    return null
  }
}

function writeLayerReturnStorage(value) {
  try {
    const storage = globalThis.sessionStorage
    if (!storage) return
    if (value == null) storage.removeItem(LAYER_RETURN_STORAGE_KEY)
    else storage.setItem(LAYER_RETURN_STORAGE_KEY, JSON.stringify(value))
  } catch (_) {}
}

// Sends a saved layer/composite library asset back to its originating canvas workflow as a new asset node.
export function requestCanvasAssetFromLayer(payload) {
  if (!payload || typeof payload !== 'object') return false
  const workflowId = typeof payload.workflowId === 'string' ? payload.workflowId.trim() : ''
  const asset = payload.asset && typeof payload.asset === 'object' ? { ...payload.asset } : null
  if (!workflowId || !asset || (!asset.id && !asset.url)) return false
  const projectId = typeof payload.projectId === 'string' ? payload.projectId.trim() : ''
  const sourceNodeId = typeof payload.sourceNodeId === 'string' ? payload.sourceNodeId.trim() : ''
  const normalized = {
    workflowId,
    ...(projectId ? { projectId } : {}),
    ...(sourceNodeId ? { sourceNodeId } : {}),
    asset,
    at: Date.now(),
  }
  pendingCanvasAssetFromLayer = normalized
  writeLayerReturnStorage(normalized)
  const handled = dispatchBridgeEvent(CANVAS_ADD_LAYER_ASSET_EVENT, normalized)
  if (!handled) {
    // Ask App shell to switch back to canvas mode without queueing a conflicting pendingLocateNode.
    dispatchBridgeEvent(CANVAS_LOCATE_NODE_EVENT, {
      target: {
        workflowId,
        ...(projectId ? { projectId } : {}),
        ...(sourceNodeId ? { nodeId: sourceNodeId } : {}),
      },
    })
  }
  return handled
}

export function takePendingCanvasAssetFromLayer() {
  const value = pendingCanvasAssetFromLayer || readLayerReturnStorage()
  pendingCanvasAssetFromLayer = null
  writeLayerReturnStorage(null)
  return value || null
}

export function queueCanvasLocateNode(target) {
  if (!target || typeof target !== 'object' || !target.workflowId) return false
  pendingLocateNode = { ...target }
  return true
}

export function takePendingCanvasLocateNode() {
  const value = pendingLocateNode
  pendingLocateNode = null
  return value
}

// Dispatches live to the app shell (switches to canvas mode) and mounted CanvasStudio;
// also queues once so a newly mounted CanvasStudio picks it up after loading.
export function requestCanvasLocateNode(target) {
  if (!target || typeof target !== 'object' || !target.workflowId) return false
  pendingLocateNode = { ...target }
  return dispatchBridgeEvent(CANVAS_LOCATE_NODE_EVENT, { target: { ...target } })
}

// Pure mapper from PNG Info metadata to a canvas image generation node's prompt + params patch (never triggers generation).
export function buildCanvasPngInfoPatch(metadata, provider = null) {
  const params = metadata?.params && typeof metadata.params === 'object' ? metadata.params : {}
  const providerId = provider?.provider === 'cupsy' ? 'cupsy' : 'ark'
  const modelId = provider?.capability_model || provider?.model || ''
  const spec = imageCapabilities(providerId, modelId)
  const paramsPatch = {}
  const skipped = []
  let text = null

  if (typeof metadata?.prompt === 'string' && metadata.prompt.trim()) {
    text = metadata.prompt
  }

  if (params.aspect_ratio !== undefined) {
    const ratio = String(params.aspect_ratio)
    if (spec.ratios.includes(ratio)) paramsPatch.ratio = ratio
    else skipped.push('画幅')
  }
  if (params.resolution !== undefined) {
    const resolution = String(params.resolution).toUpperCase()
    if (spec.resolutions.includes(resolution)) paramsPatch.resolution = resolution
    else skipped.push('分辨率')
  }

  const sizeMatch = String(params.size || '').match(/^(\d+)x(\d+)$/i)
  const customWidth = params.custom_width ?? sizeMatch?.[1]
  const customHeight = params.custom_height ?? sizeMatch?.[2]
  if (customWidth !== undefined && customHeight !== undefined) {
    const width = Number(customWidth)
    const height = Number(customHeight)
    if (Number.isInteger(width) && Number.isInteger(height) && width > 0 && height > 0) {
      paramsPatch.custom_width = width
      paramsPatch.custom_height = height
    }
  }

  if (params.output_format !== undefined) {
    const format = String(params.output_format).toLowerCase().replace('jpg', 'jpeg')
    if (spec.formats.includes(format)) paramsPatch.output_format = format
    else skipped.push('格式')
  }
  if (typeof params.watermark === 'boolean') {
    paramsPatch.watermark = params.watermark
  }

  return { text, paramsPatch, skipped }
}
