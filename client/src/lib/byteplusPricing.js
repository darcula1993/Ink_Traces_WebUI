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
  const minimum = estimate.minimumCost.toFixed(2)
  const maximum = estimate.maximumCost.toFixed(2)
  return minimum === maximum ? `$${minimum}` : `$${minimum}~$${maximum}`
}

export function formatWanTokens(minimumTokens, maximumTokens) {
  const minimum = (minimumTokens / 10_000).toFixed(1)
  const maximum = (maximumTokens / 10_000).toFixed(1)
  return minimum === maximum ? `${minimum}万 tokens` : `${minimum}~${maximum}万 tokens`
}
