import { nodeGeometry } from '../components/canvas/canvasGeometry.js'
import { freeNodePosition } from './canvasPlacement.js'
import { defaultProviderSelection, selectedProvider, toSelection } from './canvasProviderSelection.js'
import { VIDEO_AUTO_DURATION, VIDEO_RATIOS, defaultVideoResolution, videoCapabilities } from './videoGenerationRules.js'

export const VIDEO_FOLLOW_UP_MODES = Object.freeze(['extend', 'edit'])
export const VIDEO_FOLLOW_UP_GAP = 120
const MAX_TITLE_LENGTH = 240

function fallbackId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replace(/-/g, '')
  }
  return `n_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}

export function canBuildVideoFollowUp(sourceNode) {
  if (!sourceNode || typeof sourceNode !== 'object' || !sourceNode.id) return false
  if (sourceNode.type !== 'video' && sourceNode.type !== 'asset') return false
  const asset = sourceNode.asset
  if (!asset || typeof asset !== 'object') return false
  if (!asset.id || asset.kind !== 'video' || asset.deleted === true) return false
  return true
}

function buildFollowUpTitle(sourceTitle, mode) {
  const suffix = mode === 'extend' ? ' · 延长' : ' · 编辑'
  const base = String(sourceTitle || '').trim() || '视频'
  const maxBase = Math.max(1, MAX_TITLE_LENGTH - suffix.length)
  return `${base.slice(0, maxBase)}${suffix}`
}

function resolveValidDuration(model, rawDuration) {
  const numeric = Number(rawDuration)
  if (!Number.isInteger(numeric)) return 5
  if (numeric === VIDEO_AUTO_DURATION) return VIDEO_AUTO_DURATION
  const spec = videoCapabilities(model)
  if (!spec) return numeric > 0 ? numeric : 5
  return numeric >= spec.minDuration && numeric <= spec.maxDuration ? numeric : 5
}

/**
 * Pure engine for creating a downstream video generation node (extend / edit)
 * connected to an existing video generation node or video asset node.
 * Never mutates inputs and never triggers paid generation requests.
 */
export function buildVideoFollowUpNode(
  sourceNode,
  mode,
  capabilities = null,
  preferences = null,
  { newId, existingNodes = [] } = {},
) {
  if (!VIDEO_FOLLOW_UP_MODES.includes(mode)) {
    throw new Error('不支持的视频后续模式，仅支持 extend 或 edit')
  }
  if (!canBuildVideoFollowUp(sourceNode)) {
    throw new Error('源节点没有可用的视频结果，请先生成或绑定有效视频后再操作')
  }

  const makeId = typeof newId === 'function' ? newId : fallbackId
  const isVideoGenSource = sourceNode.type === 'video'

  let providerSelection = null
  let provider = null
  let sourceProviderUnavailable = false
  let warning = null

  if (isVideoGenSource && sourceNode.providerSelection) {
    const matched = selectedProvider(capabilities, sourceNode.providerSelection, 'video')
    if (matched) {
      provider = matched
      providerSelection = toSelection(matched)
    } else {
      sourceProviderUnavailable = true
      providerSelection = defaultProviderSelection(capabilities, 'video', preferences)
      provider = selectedProvider(capabilities, providerSelection, 'video')
      warning = providerSelection
        ? '源视频节点所选接口已停用或不可用，新节点已按当前默认视频接口预选，请确认后再生成。'
        : '源视频节点所选接口已停用或不可用，且当前无可用视频接口，请先配置或手动选择。'
    }
  } else {
    providerSelection = defaultProviderSelection(capabilities, 'video', preferences)
    provider = selectedProvider(capabilities, providerSelection, 'video')
  }

  const adapter = provider?.provider || providerSelection?.provider || null
  const sourceParams = isVideoGenSource && sourceNode.params && typeof sourceNode.params === 'object'
    ? sourceNode.params
    : {}

  const supportedModels = Array.isArray(provider?.models) ? provider.models : []
  const inheritedModel =
    isVideoGenSource && !sourceProviderUnavailable && typeof sourceParams.model === 'string' && sourceParams.model
      ? (!supportedModels.length || supportedModels.some(item => item.id === sourceParams.model)
          ? sourceParams.model
          : '')
      : ''
  const model = inheritedModel || provider?.model || supportedModels[0]?.id || ''

  const modelSpec = videoCapabilities(model)
  const inheritedResolution =
    isVideoGenSource && typeof sourceParams.resolution === 'string' && modelSpec?.resolutions?.includes(sourceParams.resolution)
      ? sourceParams.resolution
      : ''
  const resolution = inheritedResolution || defaultVideoResolution(model, supportedModels)
  const duration = isVideoGenSource ? resolveValidDuration(model, sourceParams.duration) : 5

  const ratio =
    mode === 'extend'
      ? 'adaptive'
      : (isVideoGenSource && VIDEO_RATIOS.includes(sourceParams.ratio) ? sourceParams.ratio : '16:9')

  const params = {
    model,
    ratio,
    resolution,
    duration,
    video_mode: 'reference',
    ...(typeof sourceParams.generate_audio === 'boolean' ? { generate_audio: sourceParams.generate_audio } : {}),
    ...(adapter === 'cupsy' ? { omni_reference_task_type: mode } : {}),
  }

  const nodeId = makeId()
  const edgeId = makeId()
  const title = buildFollowUpTitle(sourceNode.title, mode)

  const draftNode = {
    id: nodeId,
    type: 'video',
    title,
    x: 0,
    y: 0,
    text: '',
    providerSelection,
    params,
    asset: null,
    candidates: [],
    selectedCandidateId: null,
    task: null,
  }

  const sourceGeo = nodeGeometry(sourceNode)
  const start = {
    x: Math.round((Number(sourceNode.x) || 0) + sourceGeo.width + VIDEO_FOLLOW_UP_GAP),
    y: Math.round(Number(sourceNode.y) || 0),
  }

  const normalizedExisting = Array.isArray(existingNodes) ? existingNodes : []
  const collisionNodes = normalizedExisting.some(item => item?.id === sourceNode.id)
    ? normalizedExisting
    : [sourceNode, ...normalizedExisting]

  const position = freeNodePosition(
    { nodes: collisionNodes, groups: [] },
    draftNode,
    start,
    { gap: VIDEO_FOLLOW_UP_GAP },
  )

  const node = {
    ...draftNode,
    x: Math.round(position.x),
    y: Math.round(position.y),
  }

  const edge = {
    id: edgeId,
    source: sourceNode.id,
    target: node.id,
  }

  return {
    node,
    edge,
    warning,
    sourceProviderUnavailable,
  }
}
