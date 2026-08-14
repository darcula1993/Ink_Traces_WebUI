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
  },
}

const STANDARD_UNIT_PRICE_CNY = {
  '480p': { withoutVideo: 46, withVideo: 28 },
  '720p': { withoutVideo: 46, withVideo: 28 },
  '1080p': { withoutVideo: 51, withVideo: 31 },
}

const FAST_UNIT_PRICE_CNY = {
  '480p': { withoutVideo: 37, withVideo: 22 },
  '720p': { withoutVideo: 37, withVideo: 22 },
}

// BytePlus Seedance 2.5 official rates are USD 10.70/M tokens without video
// input and USD 6.40/M tokens with video input. Preserve the existing CNY
// display basis used by the corresponding Seedance 2.0 rates.
const SEEDANCE_25_UNIT_PRICE_CNY = {
  '480p': {
    withoutVideo: STANDARD_UNIT_PRICE_CNY['480p'].withoutVideo * (10.70 / 7.00),
    withVideo: STANDARD_UNIT_PRICE_CNY['480p'].withVideo * (6.40 / 4.30),
  },
  '720p': {
    withoutVideo: STANDARD_UNIT_PRICE_CNY['720p'].withoutVideo * (10.70 / 7.00),
    withVideo: STANDARD_UNIT_PRICE_CNY['720p'].withVideo * (6.40 / 4.30),
  },
}

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
  resolution = '720p',
  ratio = 'adaptive',
  duration = 5,
  fast = false,
  referenceVideos = [],
} = {}) {
  const normalizedModel = model === 'seedance-2.5' ? 'seedance-2.5' : 'seedance-2.0'
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
    ? SEEDANCE_25_UNIT_PRICE_CNY
    : useFastPrice
      ? FAST_UNIT_PRICE_CNY
      : STANDARD_UNIT_PRICE_CNY
  const priceRow = priceTable[resolution] || priceTable['720p']
  const unitPrice = hasVideo ? priceRow.withVideo : priceRow.withoutVideo
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
    unitPrice,
    minimumCost: minimumTokens / 1_000_000 * unitPrice,
    maximumCost: maximumTokens / 1_000_000 * unitPrice,
  }
}

export function formatCnyEstimate(estimate) {
  const minimum = estimate.minimumCost.toFixed(2)
  const maximum = estimate.maximumCost.toFixed(2)
  return minimum === maximum ? `¥${minimum}` : `¥${minimum}~¥${maximum}`
}

export function formatWanTokens(minimumTokens, maximumTokens) {
  const minimum = (minimumTokens / 10_000).toFixed(1)
  const maximum = (maximumTokens / 10_000).toFixed(1)
  return minimum === maximum ? `${minimum}万 tokens` : `${minimum}~${maximum}万 tokens`
}
