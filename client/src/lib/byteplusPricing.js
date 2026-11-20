import { imageCapabilities, imageEffectiveParams, imageParameterIssues, isSeedream55 } from './imageGenerationRules.js'

const FPS = 24
const UNKNOWN_REFERENCE_VIDEO_SECONDS = 5

const OUTPUT_DIMENSIONS = {
  'seedance-2.0': {
    '480p': {
      '16:9': [864, 496],
      '4:3': [752, 560],
      '1:1': [640, 640],
      '3:4': [560, 752],
      '9:16': [496, 864],
      '21:9': [992, 432],
    },
    '720p': {
      '16:9': [1280, 720],
      '4:3': [1112, 834],
      '1:1': [960, 960],
      '3:4': [834, 1112],
      '9:16': [720, 1280],
      '21:9': [1470, 630],
    },
    '1080p': {
      '16:9': [1920, 1080],
      '4:3': [1664, 1248],
      '1:1': [1440, 1440],
      '3:4': [1248, 1664],
      '9:16': [1080, 1920],
      '21:9': [2206, 946],
    },
  },
  'seedance-2.5': {
    '480p': {
      '16:9': [854, 480],
      '4:3': [752, 560],
      '1:1': [640, 640],
      '3:4': [560, 752],
      '9:16': [480, 854],
      '21:9': [992, 432],
    },
    '720p': {
      '16:9': [1280, 720],
      '4:3': [1112, 834],
      '1:1': [960, 960],
      '3:4': [834, 1112],
      '9:16': [720, 1280],
      '21:9': [1470, 630],
    },
    '1080p': {
      '16:9': [1920, 1080],
      '4:3': [1664, 1248],
      '1:1': [1440, 1440],
      '3:4': [1248, 1664],
      '9:16': [1080, 1920],
      '21:9': [2206, 946],
    },
  },
}

const STANDARD_UNIT_PRICE_USD = {
  '480p': { withoutVideo: 7.0, withVideo: 4.3 },
  '720p': { withoutVideo: 7.0, withVideo: 4.3 },
  '1080p': { withoutVideo: 7.7, withVideo: 4.7 },
}

const FAST_UNIT_PRICE_USD = {
  '480p': { withoutVideo: 5.6, withVideo: 3.3 },
  '720p': { withoutVideo: 5.6, withVideo: 3.3 },
}

const SEEDANCE_25_UNIT_PRICE_USD = {
  '480p': { withoutVideo: 10.70, withVideo: 6.40 },
  '720p': { withoutVideo: 10.70, withVideo: 6.40 },
  '1080p': { withoutVideo: 11.70, withVideo: 7.00 },
}
const SEEDANCE_25_1080P_PROMOTION_FACTOR = 0.72
const SEEDANCE_25_1080P_PROMOTION_START = Date.parse('2026-08-14T06:00:00Z')
const SEEDANCE_25_1080P_PROMOTION_END = Date.parse('2026-09-17T06:00:00Z')

function outputDurationRange(model, duration) {
  if (Number(duration) !== -1) {
    const seconds = Number(duration)
    return [seconds, seconds]
  }
  return model === 'seedance-2.5' ? [4, 30] : [4, 15]
}

function referenceVideoSeconds(model, videos) {
  if (!videos.length) return { seconds: 0, assumed: false }

  let assumed = false
  const total = videos.reduce((sum, video) => {
    const duration = Number(video?.duration)
    if (Number.isFinite(duration) && duration > 0) return sum + duration
    assumed = true
    return sum + UNKNOWN_REFERENCE_VIDEO_SECONDS
  }, 0)
  const maxSeconds = model === 'seedance-2.5' ? 30 : 15

  // Seedance 2.0 bills video-input jobs against a minimum usage equivalent
  // to four input seconds. Apply the same baseline to the requested 2.5 rule.
  return {
    seconds: Math.min(maxSeconds, Math.max(4, total)),
    assumed,
  }
}

function tokensForSeconds(seconds, width, height) {
  return seconds * width * height * FPS / 1024
}

export function estimateBytePlusVideoCost({
  model = 'seedance-2.0',
  provider = 'ark',
  resolution = '720p',
  ratio = 'adaptive',
  duration = 5,
  fast = false,
  referenceVideos = [],
  now = Date.now(),
} = {}) {
  const normalizedModel = ['seedance-2.5', 'seedance-2.5-moderated'].includes(model)
    ? 'seedance-2.5'
    : 'seedance-2.0'
  const dimensionsByRatio = OUTPUT_DIMENSIONS[normalizedModel][resolution]
    || OUTPUT_DIMENSIONS[normalizedModel]['720p']
  const ratioAssumed = !dimensionsByRatio[ratio]
  const billedRatio = ratioAssumed ? '16:9' : ratio
  const [width, height] = dimensionsByRatio[billedRatio]
  const readyVideos = (referenceVideos || []).filter(video => video?.url && !video.uploading)
  const input = referenceVideoSeconds(normalizedModel, readyVideos)
  const hasVideo = readyVideos.length > 0
  const useFastPrice = normalizedModel === 'seedance-2.0' && Boolean(fast)
  const priceTable = normalizedModel === 'seedance-2.5'
    ? SEEDANCE_25_UNIT_PRICE_USD
    : useFastPrice
      ? FAST_UNIT_PRICE_USD
      : STANDARD_UNIT_PRICE_USD
  const priceRow = priceTable[resolution] || priceTable['720p']
  const listUnitPrice = hasVideo ? priceRow.withVideo : priceRow.withoutVideo
  const promotionActive = normalizedModel === 'seedance-2.5'
    && provider === 'ark'
    && resolution === '1080p'
    && Number(now) >= SEEDANCE_25_1080P_PROMOTION_START
    && Number(now) < SEEDANCE_25_1080P_PROMOTION_END
  const discountFactor = promotionActive ? SEEDANCE_25_1080P_PROMOTION_FACTOR : 1
  const unitPrice = listUnitPrice * discountFactor
  const [minimumOutputSeconds, maximumOutputSeconds] = outputDurationRange(normalizedModel, duration)
  const minimumTokens = tokensForSeconds(input.seconds + minimumOutputSeconds, width, height)
  const maximumTokens = tokensForSeconds(input.seconds + maximumOutputSeconds, width, height)

  return {
    model: normalizedModel,
    width,
    height,
    fps: FPS,
    billedRatio,
    ratioAssumed,
    hasVideo,
    referenceVideoCount: readyVideos.length,
    inputVideoSeconds: input.seconds,
    inputDurationAssumed: input.assumed,
    minimumOutputSeconds,
    maximumOutputSeconds,
    minimumTokens,
    maximumTokens,
    currency: 'USD',
    listUnitPrice,
    unitPrice,
    discountFactor,
    promotionActive,
    minimumCost: minimumTokens / 1_000_000 * unitPrice,
    maximumCost: maximumTokens / 1_000_000 * unitPrice,
    minimumListCost: minimumTokens / 1_000_000 * listUnitPrice,
    maximumListCost: maximumTokens / 1_000_000 * listUnitPrice,
  }
}

export function formatUsdEstimate(estimate) {
  const minimum = estimate.minimumCost.toFixed(3)
  const maximum = estimate.maximumCost.toFixed(3)
  return minimum === maximum ? `$${minimum}` : `$${minimum}~$${maximum}`
}

export function formatWanTokens(minimumTokens, maximumTokens) {
  const minimum = (minimumTokens / 10_000).toFixed(1)
  const maximum = (maximumTokens / 10_000).toFixed(1)
  return minimum === maximum ? `${minimum}万 tokens` : `${minimum}~${maximum}万 tokens`
}

// ---- Images (IMAGE-COST-20261114). USD per image; P = pixels of one output image.
// BytePlus model pricing read 2026-11-14; mirrored by server/cost_estimate.py
// (`estimate_image_cost`, `estimate_layer_unit_price`). Cupsy seedream-5.0-pro is
// billed at the BytePlus 5.0 pro rate (user 2026-11-12).
export const SEEDREAM_55 = 'seedream-5.5'
export const SEEDREAM_50_PRO = 'seedream-5.0-pro'
export const IMAGE_PRICING = {
  [SEEDREAM_55]: {
    label: 'Seedream 5.5',
    inputUnitPrice: 0.008,
    freeInputImages: 0,
    single: [[921_600, 2_601_123.84, 0.020], [2_601_123.84, 4_624_220.16, 0.035]],
    // No separate 5.5 layer row: each layer is billed by its actual output tier.
    layer: [[921_600, 2_601_123.84, 0.020], [2_601_123.84, 4_624_220.16, 0.035]],
  },
  [SEEDREAM_50_PRO]: {
    label: 'Seedream 5.0 pro',
    inputUnitPrice: 0.003,
    freeInputImages: 1,
    single: [[0, 2_610_000, 0.045], [2_610_000, null, 0.09]],
    layer: [[0, 2_610_000, 0.0225], [2_610_000, null, 0.045]],
  },
}
export const IMAGE_UNKNOWN_REASONS = {
  below_price_floor: '输出像素低于官方定价下限',
  above_price_ceiling: '输出像素超出官方定价档',
}
// Assumption tag when layers below the lowest tier are billed at that tier (shown as 推算).
export const LAYER_BELOW_FLOOR_ASSUMPTION = 'below_floor_min_tier'
const imageFamily = family => (family === SEEDREAM_55 ? SEEDREAM_55 : SEEDREAM_50_PRO)

export function imageOutputUnitPrice(family, pixels, layer = false) {
  const tiers = IMAGE_PRICING[imageFamily(family)][layer ? 'layer' : 'single']
  if (pixels < tiers[0][0]) return { price: null, reason: 'below_price_floor' }
  for (let index = 0; index < tiers.length; index += 1) {
    const [low, high, price] = tiers[index]
    if ((index === 0 || pixels > low) && (high === null || pixels <= high)) return { price, tier: index }
  }
  return { price: null, reason: 'above_price_ceiling' }
}

export function imageInputCost(family, referenceCount) {
  const pricing = IMAGE_PRICING[imageFamily(family)]
  return Math.max(0, Math.trunc(referenceCount) - pricing.freeInputImages) * pricing.inputUnitPrice
}

export function estimateBytePlusImageCost({ family = SEEDREAM_50_PRO, width = 1024, height = 1024, referenceCount = 0, sizeAssumed = false } = {}) {
  const model = imageFamily(family), pricing = IMAGE_PRICING[model]
  const pixels = Math.trunc(width) * Math.trunc(height)
  const base = {
    model, width: Math.trunc(width), height: Math.trunc(height), pixels, sizeAssumed: Boolean(sizeAssumed),
    referenceCount: Math.trunc(referenceCount), inputUnitPrice: pricing.inputUnitPrice,
    freeInputImages: pricing.freeInputImages, currency: 'USD',
  }
  const unit = imageOutputUnitPrice(model, pixels)
  if (unit.price === null) return { ...base, known: false, reason: unit.reason }
  const inputCost = imageInputCost(model, referenceCount)
  const total = inputCost + unit.price
  return {
    ...base, known: true, tier: unit.tier, outputUnitPrice: unit.price, outputCount: 1,
    inputCost, outputCost: unit.price, minimumCost: total, maximumCost: total,
  }
}

// Per-layer price before submission: 1K/1.5K fix the low tier, 2K/Auto may span both tiers.
export function estimateBytePlusLayerUnitPrice({ family = SEEDREAM_50_PRO, size = 'auto' } = {}) {
  const model = imageFamily(family), tiers = IMAGE_PRICING[model].layer
  const low = tiers[0][2], high = tiers[tiers.length - 1][2]
  const fixedLow = ['1K', '1.5K'].includes(String(size).toUpperCase())
  return { model, size, perLayerMin: low, perLayerMax: fixedLow ? low : high, inputCost: imageInputCost(model, 1), currency: 'USD' }
}

// Actual layer outputs (base image included): Σ per-layer tier price + the source image.
export function estimateBytePlusLayerOutputsCost({ family = SEEDREAM_50_PRO, outputSizes = [], referenceCount = 1 } = {}) {
  const model = imageFamily(family), floorPrice = IMAGE_PRICING[model].layer[0][2]
  let outputCost = 0, belowFloorLayers = 0
  for (const [width, height] of outputSizes) {
    const unit = imageOutputUnitPrice(model, Math.trunc(width) * Math.trunc(height), true)
    // User 2026-11-14: a layer below the lowest listed tier is billed at that tier (推算).
    if (unit.price === null && unit.reason === 'below_price_floor') { unit.price = floorPrice; belowFloorLayers += 1 }
    if (unit.price === null) return { known: false, reason: unit.reason, model, outputCount: outputSizes.length }
    outputCost += unit.price
  }
  const inputCost = imageInputCost(model, referenceCount)
  const total = inputCost + outputCost
  return {
    known: true, model, outputCount: outputSizes.length, inputCost, outputCost, minimumCost: total, maximumCost: total,
    belowFloorLayers, ...(belowFloorLayers ? { assumption: LAYER_BELOW_FLOOR_ASSUMPTION } : {}),
  }
}

export function imageTierLabel(family, tier, layer = false) {
  const [low, high] = IMAGE_PRICING[imageFamily(family)][layer ? 'layer' : 'single'][tier]
  const m = value => `${Number((value / 1_000_000).toFixed(2))}M`
  if (tier === 0) return low ? `${m(low)}–${m(high)} 像素档` : `≤${m(high)} 像素档`
  return high === null ? `>${m(low)} 像素档` : `>${m(low)}–${m(high)} 像素档`
}

const NOMINAL_IMAGE_SIZE = { '1K': [1024, 1024], '1.5K': [1536, 1536], '2K': [2048, 2048] }

// Canvas/tool image estimate from node params. Returns {known:true,estimate,...} or
// {known:false,reason}; never a zero for unknown prices. `issue` is a pre-computed
// parameter problem (e.g. a draft size error) that blocks estimating.
// The model the backend will actually call for this interface (ESTIMATE-DEBT-20261115).
// A saved interface profile runs on its own settings only: without its own model the
// backend uses seedream-5-0-pro (app.get_provider_default_model), never the deployment
// default, so the deployment `model` fallback must not decide the price family.
export const BACKEND_PROFILE_DEFAULT_IMAGE_MODEL = 'seedream-5-0-pro'
export function imagePricingModel(provider) {
  if (!provider) return ''
  if (provider.profile_id) return provider.capability_model || BACKEND_PROFILE_DEFAULT_IMAGE_MODEL
  return provider.capability_model || provider.model
}
export const imagePricingFamily = provider => ((provider?.provider || provider?.id) === 'ark' && isSeedream55(imagePricingModel(provider)) ? SEEDREAM_55 : SEEDREAM_50_PRO)

export function estimateImageParamsCost({ provider, params = {}, references = [], issue = '' } = {}) {
  if (!provider) return { known: false, reason: '接口未配置或尚未就绪' }
  const adapter = provider.provider || provider.id, model = imagePricingModel(provider)
  if (!['ark', 'cupsy'].includes(adapter)) return { known: false, reason: '当前接口暂无价格资料' }
  const images = references.filter(asset => !asset.kind || asset.kind === 'image')
  const problem = issue || imageParameterIssues(adapter, params, images, model)[0]
  if (problem) return { known: false, reason: problem }
  const p = imageEffectiveParams(adapter, params)
  let size, sizeAssumed = false
  if (p.ratio === 'custom') size = [Number(p.custom_width), Number(p.custom_height)]
  else if (p.ratio === 'auto') { size = NOMINAL_IMAGE_SIZE[p.resolution]; sizeAssumed = true }
  else size = imageCapabilities(adapter, model).sizeMap[p.resolution]?.[p.ratio]
  if (!size) return { known: false, reason: '无法确定输出尺寸' }
  const family = imagePricingFamily(provider)
  const estimate = estimateBytePlusImageCost({ family, width: size[0], height: size[1], referenceCount: images.length, sizeAssumed })
  if (!estimate.known) return { known: false, reason: IMAGE_UNKNOWN_REASONS[estimate.reason], estimate }
  return { known: true, estimate, min: estimate.minimumCost, max: estimate.maximumCost, assumed: sizeAssumed }
}

export function describeImageEstimate(estimate) {
  const pricing = IMAGE_PRICING[estimate.model]
  const input = estimate.referenceCount
    ? `参考图 ${estimate.referenceCount} 张 × ${formatImageUsd(pricing.inputUnitPrice)}${pricing.freeInputImages ? `（首张免费，计 ${Math.max(0, estimate.referenceCount - pricing.freeInputImages)} 张）` : ''} = ${formatImageUsd(estimate.inputCost)}`
    : '无参考图'
  return [
    `${pricing.label} · 输出 ${estimate.width}×${estimate.height}（${estimate.pixels.toLocaleString('en-US')} 像素，${imageTierLabel(estimate.model, estimate.tier)}）× ${formatImageUsd(estimate.outputUnitPrice)}`,
    estimate.sizeAssumed ? 'Auto 画幅按同分辨率 1:1 像素估算，实际尺寸由接口决定' : '',
    input,
    '按官方费率估算，非实际扣费',
  ].filter(Boolean).join('；')
}

// Layer tool label: per-layer unit price; the count is only known after the run.
export function describeLayerEstimate({ modern = false, size = 'auto' } = {}) {
  const family = modern ? SEEDREAM_55 : SEEDREAM_50_PRO, pricing = IMAGE_PRICING[family]
  const unit = estimateBytePlusLayerUnitPrice({ family, size })
  const fixed = unit.perLayerMin === unit.perLayerMax
  const perLayer = fixed ? formatImageUsd(unit.perLayerMin) : `${formatImageUsd(unit.perLayerMin)}–${formatImageUsd(unit.perLayerMax)}`
  const detail = [
    `${pricing.label} 图层分解 · 分辨率 ${size === 'auto' ? 'Auto' : size}`,
    fixed ? `每层 ${perLayer}（${imageTierLabel(family, 0, true)}）` : `每层 ${perLayer}，按每层实际像素档计`,
    modern ? '层数按实际输出计（含底图，不超过设定的输出上限）' : '层数按实际输出计（含底图）',
    `源图 1 张：${unit.inputCost ? formatImageUsd(unit.inputCost) : '首张免费'}`,
    modern ? `单层低于 921,600 像素时官方无价，按最低档 ${formatImageUsd(unit.perLayerMin)} 推算` : '',
    '按官方费率估算，非实际扣费',
  ].filter(Boolean).join('；')
  return { text: `每层 ${perLayer} USD · 按实际层数计`, detail, unit }
}

// Image prices have sub-cent precision (e.g. 0.0225), so keep up to 4 decimals.
export const formatImageUsd = value => `$${Number(value).toFixed(4).replace(/(\.\d{2}\d*?)0+$/, '$1')}`
