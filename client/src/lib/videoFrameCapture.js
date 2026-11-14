// FRAME-CAPTURE-20261114: browser-side still capture from a canvas video node.
// A detached same-origin <video> seeks to the requested time, the frame is drawn
// onto a canvas at the native size (videoWidth x videoHeight) and exported as PNG.
// The caller uploads the PNG through the normal canvas material upload path.

// #3: the tail frame is taken one 30fps frame before the end so the seek stays
// inside the stream (seeking to `duration` exactly can land past the last
// decodable frame and paint black or fail in some browsers).
export const FRAME_STEP = 1 / 30
export const CAPTURE_TIMEOUT_MS = 20000

export function tailFrameTime(duration) {
  if (!Number.isFinite(duration) || duration <= 0) return null
  return Math.max(0, duration - FRAME_STEP)
}

// Clamp a requested time into the decodable range [0, tail].
export function clampFrameTime(time, duration) {
  const tail = tailFrameTime(duration)
  const value = Number.isFinite(time) && time > 0 ? time : 0
  return tail == null ? value : Math.min(value, tail)
}

const two = value => String(value).padStart(2, '0')
// mm:ss.mmm (minutes keep counting past 59 so long clips stay unambiguous).
export function formatFrameTime(seconds) {
  const ms = Math.max(0, Math.round((Number.isFinite(seconds) ? seconds : 0) * 1000))
  return `${two(Math.floor(ms / 60000))}:${two(Math.floor(ms / 1000) % 60)}.${String(ms % 1000).padStart(3, '0')}`
}

const VIDEO_EXTENSION = /\.(mp4|webm|mov|m4v|mkv|ogv|avi)$/i
export function frameBaseName(title) {
  const base = String(title || '').trim().replace(VIDEO_EXTENSION, '').replace(/[\\/\u0000-\u001f]+/g, '_').trim().slice(0, 80)
  return base || '视频'
}
export function frameFileName(title, { tail = false, time = 0 } = {}) {
  // Windows forbids ':' in file names, so the stored name uses mm-ss.mmm; the menu still shows mm:ss.mmm.
  return `${frameBaseName(title)}_${tail ? '尾帧' : formatFrameTime(time).replace(':', '-')}.png`
}

const MEDIA_ERRORS = { 1: '视频读取被中止', 2: '视频加载失败（网络错误）', 3: '视频解码失败', 4: '视频格式不受浏览器支持或地址不可用，无法解码' }
const mediaError = video => new Error(MEDIA_ERRORS[video.error?.code] || '视频无法加载或解码')

function once(video, events, timeoutMs, timeoutMessage) {
  return new Promise((resolve, reject) => {
    const handlers = {}
    const done = (fn, value) => { clearTimeout(timer); for (const [name, handler] of Object.entries(handlers)) video.removeEventListener(name, handler); fn(value) }
    for (const name of events) { handlers[name] = () => done(resolve, name); video.addEventListener(name, handlers[name]) }
    handlers.error = () => done(reject, mediaError(video)); video.addEventListener('error', handlers.error)
    const timer = setTimeout(() => done(reject, new Error(timeoutMessage)), timeoutMs)
  })
}

const HAVE_CURRENT_DATA = 2
/**
 * Capture one frame. `tail: true` takes the last decodable frame; otherwise `time`
 * (seconds) is clamped into the playable range. Resolves {blob, width, height, time}.
 * Rejects with a user-facing reason for undecodable video, cross-origin taint or
 * export failure; never resolves with an empty image.
 */
export async function captureVideoFrame(src, { tail = false, time = 0, timeoutMs = CAPTURE_TIMEOUT_MS, createElement = tag => document.createElement(tag) } = {}) {
  if (!src) throw new Error('节点没有可截取的视频')
  const video = createElement('video')
  video.muted = true; video.playsInline = true; video.preload = 'auto'
  try {
    const loaded = once(video, ['loadeddata'], timeoutMs, '视频加载超时，无法截帧')
    video.src = src
    await loaded
    if (!(video.videoWidth > 0 && video.videoHeight > 0)) throw new Error('视频没有可解码的画面，无法截帧')
    const target = tail ? tailFrameTime(video.duration) : clampFrameTime(time, video.duration)
    if (target == null) throw new Error('无法读取视频时长，不能截取尾帧')
    if (!(target <= 0.001 && video.currentTime <= 0.001 && video.readyState >= HAVE_CURRENT_DATA)) {
      const seeked = once(video, ['seeked'], timeoutMs, '视频定位超时，无法截帧')
      video.currentTime = target
      await seeked
    }
    const width = video.videoWidth, height = video.videoHeight
    const canvas = createElement('canvas')
    canvas.width = width; canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('浏览器无法创建截帧画布')
    context.drawImage(video, 0, 0, width, height)
    let blob
    try {
      blob = await new Promise((resolve, reject) => { try { canvas.toBlob(resolve, 'image/png') } catch (error) { reject(error) } })
    } catch (error) {
      if (error?.name === 'SecurityError') throw new Error('视频来自其他域名且未允许跨域读取，浏览器禁止导出画面')
      throw error
    }
    if (!blob || !blob.size) throw new Error('浏览器未能导出 PNG 图片')
    return { blob, width, height, time: target }
  } finally {
    video.removeAttribute?.('src')
    try { video.load?.() } catch { /* detached element */ }
  }
}
