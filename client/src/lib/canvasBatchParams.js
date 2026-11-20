// P1-CANVAS-WORKFLOW-20261120 (P1-3): pure helpers for homogeneous multi-select batch parameter editing.
import { nodeProvider, selectionOptionId, toSelection } from './canvasProviderSelection.js'
import { imageCapabilities, imageEffectiveParams, imageSizePatch } from './imageGenerationRules.js'
import { effectiveVideoModel, videoCapabilities, videoDurations, VIDEO_RATIOS } from './videoGenerationRules.js'
import { AUDIO_OUTPUT_FORMATS, AUDIO_SAMPLE_RATES, AUDIO_SPEAKERS, canvasAudioParams } from './generationSettings.js'

export const MIXED_VALUE = '__mixed__'
const GENERATION_KINDS = new Set(['image', 'video', 'audio'])

export const BATCH_FIELD_LABELS = Object.freeze({
  providerSelection: '接口',
  model: '模型',
  video_mode: '模式',
  ratio: '画幅',
  resolution: '分辨率',
  duration: '时长',
  generate_audio: '输出音频',
  output_format: '格式',
  watermark: '水印',
  speaker: '声线',
  sample_rate: '采样率',
  enable_subtitle: '生成字幕',
})

// Returns 'image' | 'video' | 'audio' only when 2+ nodes are selected and ALL share the same generation type.
export function homogeneousGenerationType(nodes = []) {
  if (!Array.isArray(nodes) || nodes.length < 2) return null
  const kind = nodes[0]?.type
  if (!GENERATION_KINDS.has(kind)) return null
  return nodes.every(node => node?.type === kind) ? kind : null
}

// Collapses an array of primitive values into { mixed, value }.
export function commonValue(values = []) {
  if (!values.length) return { mixed: false, value: '' }
  const first = values[0]
  return values.every(value => value === first)
    ? { mixed: false, value: first }
    : { mixed: true, value: MIXED_VALUE }
}

function intersect(lists = []) {
  const nonEmpty = lists.filter(list => Array.isArray(list) && list.length > 0)
  if (!nonEmpty.length) return []
  return nonEmpty.slice(1).reduce((acc, list) => {
    const set = new Set(list)
    return acc.filter(item => set.has(item))
  }, [...nonEmpty[0]])
}

// Compute current shared/mixed field states and safe common option sets for a homogeneous selection.
export function batchParamSummary(nodes = [], capabilities = {}) {
  const kind = homogeneousGenerationType(nodes)
  if (!kind) return null
  const providerOptions = capabilities?.[kind] || []
  const providers = nodes.map(node => nodeProvider(capabilities, node))
  const providerValue = commonValue(nodes.map((node, index) => (
    providers[index] ? providers[index].id : selectionOptionId(node.providerSelection)
  )))

  if (kind === 'video') {
    const modelLists = providers.map(p => (p?.models || []).map(m => m.id))
    const fallbackModels = providerOptions.flatMap(p => (p.models || []).map(m => m.id))
    const commonModelIds = intersect(modelLists.length && modelLists.some(l => l.length) ? modelLists : [fallbackModels])
    const modelCatalog = new Map(providerOptions.flatMap(p => (p.models || []).map(m => [m.id, m])))
    const modelOptions = commonModelIds.map(id => modelCatalog.get(id) || { id, name: id })
    const effectiveModels = nodes.map((node, index) => effectiveVideoModel(node.params?.model, providers[index]?.models))
    const specs = effectiveModels.map(id => videoCapabilities(id)).filter(Boolean)
    const resolutions = intersect(specs.map(s => s.resolutions))
    const durations = intersect(effectiveModels.map(id => videoDurations(id)))
    return {
      kind,
      providerOptions,
      modelOptions,
      ratioOptions: VIDEO_RATIOS,
      resolutionOptions: resolutions.length ? resolutions : ['480p', '720p', '1080p'],
      durationOptions: durations.length ? durations : [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, -1],
      values: {
        providerSelection: providerValue,
        model: commonValue(effectiveModels),
        video_mode: commonValue(nodes.map(n => n.params?.video_mode || 'reference')),
        ratio: commonValue(nodes.map(n => n.params?.ratio || '16:9')),
        resolution: commonValue(nodes.map(n => n.params?.resolution || '720p')),
        duration: commonValue(nodes.map(n => Number(n.params?.duration ?? 5))),
        generate_audio: commonValue(nodes.map(n => (n.params?.generate_audio === undefined || n.params?.generate_audio === true) ? 'true' : 'false')),
      },
    }
  }

  if (kind === 'image') {
    const specs = providers.map(p => {
      const adapter = p?.provider || p?.id || 'ark'
      return imageCapabilities(adapter, p?.capability_model || p?.model)
    })
    const ratios = intersect(specs.map(s => s.ratios.filter(r => r !== 'custom')))
    const resolutions = intersect(specs.map(s => s.resolutions))
    const formats = intersect(specs.map(s => s.formats))
    const effective = nodes.map((node, index) => imageEffectiveParams(providers[index]?.provider || 'ark', node.params || {}))
    return {
      kind,
      providerOptions,
      ratioOptions: ratios.length ? ratios : ['1:1', '4:3', '3:4', '16:9', '9:16'],
      resolutionOptions: resolutions.length ? resolutions : ['1K', '2K'],
      formatOptions: formats.length ? formats : ['png', 'jpeg'],
      values: {
        providerSelection: providerValue,
        ratio: commonValue(effective.map(p => p.ratio)),
        resolution: commonValue(effective.map(p => p.resolution)),
        output_format: commonValue(effective.map(p => p.output_format)),
        watermark: commonValue(effective.map(p => p.watermark === true ? 'true' : 'false')),
      },
    }
  }

  // audio
  const effective = nodes.map(node => canvasAudioParams(node.params || {}))
  return {
    kind,
    providerOptions,
    speakerOptions: AUDIO_SPEAKERS,
    formatOptions: AUDIO_OUTPUT_FORMATS,
    sampleRateOptions: AUDIO_SAMPLE_RATES,
    values: {
      providerSelection: providerValue,
      speaker: commonValue(effective.map(p => p.speaker)),
      output_format: commonValue(effective.map(p => p.output_format)),
      sample_rate: commonValue(effective.map(p => p.sample_rate)),
      enable_subtitle: commonValue(effective.map(p => p.enable_subtitle === true ? 'true' : 'false')),
    },
  }
}

// Applies a single batch change (providerSelection OR one param field) to all target nodes in one document transform.
export function applyBatchParamPatch(document, nodeIds, change, capabilities = {}) {
  const idSet = new Set(nodeIds || [])
  const targets = (document.nodes || []).filter(node => idSet.has(node.id))
  const kind = homogeneousGenerationType(targets)
  if (!kind || !change) return document

  if (change.providerOption) {
    const selection = toSelection(change.providerOption)
    if (!selection) return document
    return {
      ...document,
      nodes: document.nodes.map(node => (
        idSet.has(node.id) ? { ...node, providerSelection: selection } : node
      )),
    }
  }

  const { field, value } = change
  if (!field || value === MIXED_VALUE) return document

  return {
    ...document,
    nodes: document.nodes.map(node => {
      if (!idSet.has(node.id)) return node
      const params = node.params || {}
      if (kind === 'image' && (field === 'ratio' || field === 'resolution')) {
        const provider = nodeProvider(capabilities, node)
        const adapter = provider?.provider || provider?.id || 'ark'
        const patch = imageSizePatch(adapter, params, { [field]: value }, provider?.capability_model || provider?.model)
        return { ...node, params: { ...params, ...patch } }
      }
      return { ...node, params: { ...params, [field]: value } }
    }),
  }
}
