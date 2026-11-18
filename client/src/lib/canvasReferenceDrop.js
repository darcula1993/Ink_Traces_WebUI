// Validation for "add as reference" (drag from the asset tree or the keyboard
// menu). New references are appended after the existing ones, so the keyframe
// rule "first image = first frame, second = last frame" stays order based.
import {effectiveVideoModel,videoCapabilities} from './videoGenerationRules.js'
import {imageCapabilities} from './imageGenerationRules.js'

const ACCEPTS = { image: ['image'], video: ['image', 'video', 'audio'], audio: ['image', 'audio'] }
export const ACCEPTED_REFERENCE_KINDS = ACCEPTS
export const AUDIO_REFERENCE_LIMITS = { image: 1, audio: 3 }
const KIND = { image: '图片', video: '视频', audio: '音频' }

export function referenceDropError(node, currentAssets = [], addingKinds = [], provider = null) {
  if (!node || !ACCEPTS[node.type]) return '只能把素材作为参考添加到图像、视频或音频生成节点'
  if (!addingKinds.length) return '没有可添加的素材'
  const wrong = addingKinds.find(kind => !ACCEPTS[node.type].includes(kind))
  if (wrong) return `${node.type === 'image' ? '图像' : node.type === 'video' ? '视频' : '音频'}生成节点不接受${KIND[wrong] || '该类型'}参考`
  const kinds = [...currentAssets.map(asset => asset.kind), ...addingKinds]
  const count = kind => kinds.filter(item => item === kind).length
  if (node.type === 'video' && node.params?.video_mode === 'keyframe') {
    if (kinds.some(kind => kind !== 'image')) return '首尾帧模式只接受图片'
    if (kinds.length > 2) return `首尾帧最多两张图片，当前已有 ${currentAssets.length} 张`
    return null
  }
  if (node.type === 'video') {
    const spec = videoCapabilities(effectiveVideoModel(node.params?.model, provider?.models))
    if (spec) for (const [kind, max] of [['image', spec.maxRefImages], ['video', spec.maxRefVideos], ['audio', spec.maxRefAudios]])
      if (count(kind) > max) return `所选视频模型最多 ${max} 个${KIND[kind]}参考`
    return null
  }
  if (node.type === 'audio') {
    if (count('image') && count('audio')) return '音频参考不能混用图片和音频'
    if (count('image') > AUDIO_REFERENCE_LIMITS.image) return `音频参考最多 ${AUDIO_REFERENCE_LIMITS.image} 张图片`
    if (count('audio') > AUDIO_REFERENCE_LIMITS.audio) return `音频参考最多 ${AUDIO_REFERENCE_LIMITS.audio} 段音频`
  }
  return null
}

// CANVAS-PORTS-LIB-20261117: per-kind reference limits for a generation node, from the
// same capability tables as referenceDropError / canvasApi. A kind the node does not
// accept has limit 0. Returns null when the interface/model is unknown (no limit check).
export function referenceLimits(node, provider = null) {
  if (!node || !ACCEPTS[node.type]) return null
  if (node.type === 'video' && node.params?.video_mode === 'keyframe') return { image: 2, video: 0, audio: 0 }
  if (node.type === 'video') {
    const spec = videoCapabilities(effectiveVideoModel(node.params?.model, provider?.models))
    return spec ? { image: spec.maxRefImages, video: spec.maxRefVideos, audio: spec.maxRefAudios } : null
  }
  if (node.type === 'audio') return { ...AUDIO_REFERENCE_LIMITS, video: 0 }
  if (!provider) return null
  return { image: imageCapabilities(provider.provider || provider.id, provider.capability_model || provider.model).maxReferences, video: 0, audio: 0 }
}
