// VIDEO-SPLIT-UI-20261122: pure helpers for video splitting (timeline cut points & equal duration).
// Kept strictly aligned with the backend /api/canvas/media/<id>/split algorithm.
// No React, no DOM: unit tested in client/tests/videoSplit.test.js.

export const MIN_SEGMENT_SECONDS = 0.2
export const MAX_SEGMENTS = 20
const EPSILON = 1e-6

export function roundTime(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return NaN
  const rounded = Math.round(num * 1000) / 1000
  return rounded === 0 ? 0 : rounded
}

export function formatSplitTime(seconds) {
  const num = Number(seconds)
  if (!Number.isFinite(num) || num <= 0) return '00:00.0'
  const totalTenths = Math.round(num * 10)
  const tenths = totalTenths % 10
  const totalSec = Math.floor(totalTenths / 10)
  const sec = totalSec % 60
  const totalMin = Math.floor(totalSec / 60)
  const min = totalMin % 60
  const hr = Math.floor(totalMin / 60)
  if (hr > 0) {
    return `${hr}:${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}.${tenths}`
  }
  return `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}.${tenths}`
}

export function normalizeCutPoints(cutPoints, duration) {
  if (!Array.isArray(cutPoints)) return []
  const maxDuration = Number.isFinite(Number(duration)) && Number(duration) > 0
    ? roundTime(duration)
    : null
  const unique = new Set()
  for (const raw of cutPoints) {
    const rounded = roundTime(raw)
    if (!Number.isFinite(rounded) || rounded <= 0) continue
    if (maxDuration !== null && rounded >= maxDuration) continue
    unique.add(rounded)
  }
  return [...unique].sort((a, b) => a - b)
}

export function computeTimelineSegments(duration, cutPoints) {
  const total = roundTime(duration)
  if (!Number.isFinite(total) || total <= 0) {
    return { segments: [], valid: false, error: '无法读取视频时长', cutPoints: [] }
  }
  if (total < MIN_SEGMENT_SECONDS * 2 - EPSILON) {
    return { segments: [], valid: false, error: '视频时长不足 0.4 秒，无法分割', cutPoints: [] }
  }
  const points = normalizeCutPoints(cutPoints, total)
  if (points.length === 0) {
    return { segments: [], valid: false, error: '请至少添加一个位于视频时长内的分割点', cutPoints: [] }
  }
  const bounds = [0, ...points, total]
  const segments = []
  for (let i = 0; i < bounds.length - 1; i += 1) {
    const start = bounds[i]
    const end = bounds[i + 1]
    segments.push({
      index: i + 1,
      start,
      end,
      duration: roundTime(end - start),
    })
  }
  if (segments.length < 2) {
    return { segments, valid: false, error: '至少需要分割为 2 个片段', cutPoints: points }
  }
  if (segments.length > MAX_SEGMENTS) {
    return {
      segments,
      valid: false,
      error: `最多支持分割为 ${MAX_SEGMENTS} 个片段（当前 ${segments.length} 段）`,
      cutPoints: points,
    }
  }
  const tooShort = segments.find(seg => seg.duration < MIN_SEGMENT_SECONDS - EPSILON)
  if (tooShort) {
    return {
      segments,
      valid: false,
      error: `片段 ${tooShort.index} 时长（${tooShort.duration.toFixed(2)}s）小于最小时长 ${MIN_SEGMENT_SECONDS}s`,
      cutPoints: points,
    }
  }
  return { segments, valid: true, error: null, cutPoints: points }
}

export function computeEqualSegments(duration, segmentDuration) {
  const total = roundTime(duration)
  if (!Number.isFinite(total) || total <= 0) {
    return { segments: [], valid: false, error: '无法读取视频时长', cutPoints: [] }
  }
  if (total < MIN_SEGMENT_SECONDS * 2 - EPSILON) {
    return { segments: [], valid: false, error: '视频时长不足 0.4 秒，无法分割', cutPoints: [] }
  }
  const step = roundTime(segmentDuration)
  if (!Number.isFinite(step) || step < MIN_SEGMENT_SECONDS - EPSILON) {
    return { segments: [], valid: false, error: `单段时长不能小于 ${MIN_SEGMENT_SECONDS} 秒`, cutPoints: [] }
  }
  if (step >= total - EPSILON) {
    return { segments: [], valid: false, error: '单段时长必须小于视频总时长', cutPoints: [] }
  }

  const segments = []
  const cutPoints = []
  let start = 0
  while (start < total - EPSILON) {
    let end = Math.min(total, roundTime(start + step))
    const remaining = roundTime(total - end)
    if (remaining > 0 && remaining < MIN_SEGMENT_SECONDS - EPSILON) {
      end = total
    }
    const segDuration = roundTime(end - start)
    segments.push({
      index: segments.length + 1,
      start,
      end,
      duration: segDuration,
    })
    if (end < total - EPSILON) {
      cutPoints.push(end)
    }
    if (segments.length > MAX_SEGMENTS) {
      return {
        segments: segments.slice(0, MAX_SEGMENTS),
        valid: false,
        error: `均分后超过最多 ${MAX_SEGMENTS} 个片段上限，请增大单段时长`,
        cutPoints: cutPoints.slice(0, MAX_SEGMENTS - 1),
      }
    }
    if (end <= start + EPSILON) break
    start = end
  }

  if (segments.length < 2) {
    return {
      segments,
      valid: false,
      error: '按该时长均分后仅产生 1 个片段，请调小单段时长',
      cutPoints: [],
    }
  }
  return { segments, valid: true, error: null, cutPoints }
}
