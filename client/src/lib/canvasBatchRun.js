// "运行所选节点": pick the selected generation nodes whose inputs are ready.
// Each one later becomes its own real task; nothing chains to downstream nodes.
import {resolveNodeInputs} from './canvasReferences.js'
import {BUSY_TASK_STATUSES} from './taskStatus.js'
import {estimateBytePlusVideoCost} from './byteplusPricing.js'
import {effectiveVideoModel,videoRatio,videoParameterError} from './videoGenerationRules.js'

const GENERATION = new Set(['image', 'video', 'audio'])
const BUSY = new Set(BUSY_TASK_STATUSES)

// Returns {known:true,min,max} or {known:false,reason}. Never a zero for unknown prices.
export function estimateNodeCost(node, provider, references = []) {
  if (node.type !== 'video') return { known: false, reason: `暂无${node.type === 'image' ? '图像' : '音频'}接口价格资料` }
  if (!provider) return { known: false, reason: '接口未配置' }
  const params = node.params || {}, model = effectiveVideoModel(params.model, provider.models)
  if (!provider.models?.some(item => item.id === model)) return { known: false, reason: '接口不支持此模型' }
  const ratio = videoRatio(model, params.video_mode, references.some(asset => asset.kind === 'image'), params.ratio || '16:9').value
  const error = videoParameterError({ model, ratio, resolution: params.resolution || '720p', duration: params.duration ?? 5 })
  if (error) return { known: false, reason: error }
  const videos = params.video_mode === 'keyframe' ? [] : references.filter(asset => asset.kind === 'video').map(asset => ({ ...asset, duration: Number(asset.duration) > 0 ? Number(asset.duration) : undefined }))
  const estimate = estimateBytePlusVideoCost({ model, provider: provider.provider, resolution: params.resolution || '720p', ratio, duration: params.duration ?? 5, referenceVideos: videos })
  return { known: true, min: estimate.minimumCost, max: estimate.maximumCost, assumed: estimate.inputDurationAssumed || estimate.ratioAssumed }
}

export function batchRunPlan(document, ids, { providerFor, isUnknownResult = () => false, isLocked = () => false }) {
  const ready = [], skipped = []
  for (const id of ids) {
    const node = document.nodes.find(item => item.id === id)
    if (!node || !GENERATION.has(node.type)) continue
    const reason = (() => {
      if (isLocked(node.id) || BUSY.has(node.task?.status)) return node.task?.status === 'unknown' ? '上次提交结果未知，请先核查' : '任务进行中'
      if (isUnknownResult(node)) return '上次结果未知，可能已计费；请单独确认后再生成'
      if (!providerFor(node)) return '未配置可用接口'
      const inputs = resolveNodeInputs(node, document.nodes, document.edges)
      if (inputs.issues.length) return inputs.issues[0]
      if (!inputs.prompt) return '未填写提示词'
      return null
    })()
    if (reason) { skipped.push({ node, reason }); continue }
    const inputs = resolveNodeInputs(node, document.nodes, document.edges)
    ready.push({ node, cost: estimateNodeCost(node, providerFor(node), inputs.assets) })
  }
  return { ready, skipped, total: summarizeCosts(ready.map(item => item.cost)) }
}

export function summarizeCosts(costs) {
  const known = costs.filter(cost => cost.known), unknown = costs.length - known.length
  const min = known.reduce((sum, cost) => sum + cost.min, 0), max = known.reduce((sum, cost) => sum + cost.max, 0)
  const range = !known.length ? '' : min.toFixed(2) === max.toFixed(2) ? `$${min.toFixed(2)}` : `$${min.toFixed(2)}~$${max.toFixed(2)}`
  const text = !known.length ? '费用待估' : `${range} USD${unknown ? ` + ${unknown} 个节点费用待估` : ''}`
  return { knownCount: known.length, unknownCount: unknown, min, max, text }
}
