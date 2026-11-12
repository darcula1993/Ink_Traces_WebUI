// Validation for "add as reference" (drag from the asset tree or the keyboard
// menu). New references are appended after the existing ones, so the keyframe
// rule "first image = first frame, second = last frame" stays order based.
import {effectiveVideoModel,videoCapabilities} from './videoGenerationRules.js'

const ACCEPTS = { image: ['image'], video: ['image', 'video', 'audio'], audio: ['image', 'audio'] }
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
    if (count('image') > 1) return '音频参考最多 1 张图片'
    if (count('audio') > 3) return '音频参考最多 3 段音频'
  }
  return null
}
