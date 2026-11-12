export const SEEDREAM_MIN_PIXELS = 1280 * 720

export const SEEDREAM_MAX_PIXELS = 4_624_220

export const SEEDANCE_20 = 'seedance-2.0'

export const SEEDANCE_25 = 'seedance-2.5'

export const SEEDANCE_25_MODERATED = 'seedance-2.5-moderated'

export const CUPSY_VIDEO_MODELS = [SEEDANCE_25, SEEDANCE_25_MODERATED]

export const CUPSY_AUDIO_MODEL = 'seed-audio-1.0'

export const AUDIO_SAMPLE_RATES = [8000, 16000, 24000, 32000, 44100, 48000]

export const AUDIO_SPEAKERS = [
  { value: '', label: '模型自动' },
  { value: 'vivi', label: 'Vivi' },
  { value: 'mindy', label: 'Mindy' },
  { value: 'kian', label: 'Kian' },
  { value: 'jess', label: 'Jess' },
  { value: 'opal', label: 'Opal' },
]

export const VIDEO_MODEL_CAPABILITIES = {
  [SEEDANCE_20]: {
    label: 'Dreamina Seedance 2.0',
    resolutions: ['480p', '720p', '1080p'],
    minDuration: 4,
    maxDuration: 15,
    maxRefImages: 9,
    maxRefVideos: 3,
    maxRefAudios: 3,
  },
  [SEEDANCE_25]: {
    label: 'Dreamina Seedance 2.5',
    resolutions: ['480p', '720p', '1080p'],
    minDuration: 4,
    maxDuration: 30,
    maxRefImages: 30,
    maxRefVideos: 10,
    maxRefAudios: 10,
  },
}

export const SEEDREAM_SIZE_PRESETS = {
  '1.5K': {'1:1':[1536,1536],'4:3':[1792,1344],'3:4':[1344,1792],'16:9':[2048,1152],'9:16':[1152,2048],'3:2':[1872,1248],'2:3':[1248,1872],'21:9':[2352,1008]},
  '1K': {
    '1:1': [1024, 1024], '4:3': [1152, 864], '3:4': [864, 1152],
    '16:9': [1424, 800], '9:16': [800, 1424], '3:2': [1248, 832],
    '2:3': [832, 1248], '21:9': [1568, 672],
  },
  '2K': {
    '1:1': [2048, 2048], '4:3': [2368, 1776], '3:4': [1776, 2368],
    '16:9': [2816, 1584], '9:16': [1584, 2816], '3:2': [2496, 1664],
    '2:3': [1664, 2496], '21:9': [3136, 1344],
  },
}

export function alignSeedreamDimension(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return value
  return Math.max(16, Math.round(numeric / 16) * 16)
}

export function formatDimensionRatio(widthValue, heightValue) {
  const width = Number(widthValue)
  const height = Number(heightValue)
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return '--'
  const ratio = width / height
  return ratio >= 1 ? `${ratio.toFixed(2).replace(/\.00$/, '')}:1` : `1:${(1 / ratio).toFixed(2).replace(/\.00$/, '')}`
}

export function validateSeedreamCustomSize(widthValue, heightValue) {
  const width = Number(widthValue)
  const height = Number(heightValue)
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) {
    return '宽度和高度必须是正整数'
  }
  if (width % 16 !== 0 || height % 16 !== 0) return '宽度和高度必须是 16 的倍数'
  const pixels = width * height
  if (pixels < SEEDREAM_MIN_PIXELS || pixels > SEEDREAM_MAX_PIXELS) {
    return '总像素必须在 921600 到 4624220 之间'
  }
  const ratio = width / height
  if (ratio < 1 / 16 || ratio > 16) return '宽高比必须在 1:16 到 16:1 之间'
  return ''
}

export function fitSeedreamSizeToReference(widthValue, heightValue) {
  const sourceWidth = Number(widthValue)
  const sourceHeight = Number(heightValue)
  if (!Number.isFinite(sourceWidth) || !Number.isFinite(sourceHeight) || sourceWidth <= 0 || sourceHeight <= 0) {
    return { error: '无法读取参考素材尺寸' }
  }
  const sourceRatio = sourceWidth / sourceHeight
  if (sourceRatio < 1 / 16 || sourceRatio > 16) {
    return { error: '参考素材宽高比超出 1:16 到 16:1 的范围' }
  }

  const sourceArea = sourceWidth * sourceHeight
  const targetArea = Math.min(SEEDREAM_MAX_PIXELS, Math.max(SEEDREAM_MIN_PIXELS, sourceArea))
  const targetScale = Math.sqrt(targetArea / sourceArea)
  const targetWidth = sourceWidth * targetScale
  const maxDimension = Math.ceil(Math.sqrt(SEEDREAM_MAX_PIXELS * 16) / 16) * 16
  let best = null

  for (let width = 16; width <= maxDimension; width += 16) {
    const idealHeight = width / sourceRatio
    const heightCandidates = new Set([
      Math.floor(idealHeight / 16) * 16,
      Math.round(idealHeight / 16) * 16,
      Math.ceil(idealHeight / 16) * 16,
    ])
    for (const height of heightCandidates) {
      if (height < 16 || validateSeedreamCustomSize(width, height)) continue
      const area = width * height
      const ratioError = Math.abs(Math.log((width / height) / sourceRatio))
      const areaError = Math.abs(Math.log(area / targetArea))
      const scaleError = Math.abs(Math.log(width / targetWidth))
      const score = ratioError * 8 + areaError + scaleError * 0.02
      if (!best || score < best.score) best = { width, height, score }
    }
  }

  if (!best) return { error: '无法将参考素材适配到有效的输出尺寸' }
  return {
    width: best.width,
    height: best.height,
    adjusted: best.width !== sourceWidth || best.height !== sourceHeight,
  }
}
