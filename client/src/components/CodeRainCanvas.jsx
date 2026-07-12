import React, { useEffect, useRef } from 'react'

const KATAKANA = 'ｦｧｨｩｪｫｬｭｮｯｰｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ'
const LATIN = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
const DIGITS = '0123456789'
const SYMBOLS = ':・.=*+-<>¦｜'
function randomBetween(min, max) {
  return min + Math.random() * (max - min)
}

function randomCharacter(source) {
  return source[Math.floor(Math.random() * source.length)]
}

function makeGlyph() {
  const roll = Math.random()
  if (roll < 0.62) return { character: randomCharacter(KATAKANA), mirrored: false }
  if (roll < 0.8) return { character: randomCharacter(DIGITS), mirrored: Math.random() < 0.28 }
  if (roll < 0.95) return { character: randomCharacter(LATIN), mirrored: Math.random() < 0.42 }
  return { character: randomCharacter(SYMBOLS), mirrored: false }
}

function makeStream(x, rowCount, speedScale, startOnScreen = true, compact = false) {
  const length = Math.floor(randomBetween(compact ? 8 : 10, compact ? 19 : 29))
  const initialHead = startOnScreen
    ? compact
      ? randomBetween(0, rowCount + length * 0.72)
      : randomBetween(-length, rowCount + length)
    : -randomBetween(length, rowCount * 2.2)

  return {
    x,
    head: initialHead,
    length,
    speed: randomBetween(compact ? 6.4 : 5.2, compact ? 12.2 : 10.8) * speedScale,
    intensity: randomBetween(0.78, 1),
    glyphs: Array.from({ length }, makeGlyph),
    mutationElapsed: 0,
    nextMutation: randomBetween(55, 150),
  }
}

function resetStream(stream, rowCount, speedScale, compact) {
  const replacement = makeStream(stream.x, rowCount, speedScale, false, compact)
  Object.assign(stream, replacement)
}

function drawGlyph(context, glyph, x, y) {
  if (!glyph.mirrored) {
    context.fillText(glyph.character, x, y)
    return
  }

  context.save()
  context.translate(x, y)
  context.scale(-1, 1)
  context.fillText(glyph.character, 0, 0)
  context.restore()
}

function mutateStream(stream, elapsedMs) {
  stream.mutationElapsed += elapsedMs
  if (stream.mutationElapsed < stream.nextMutation) return

  stream.mutationElapsed = 0
  stream.nextMutation = randomBetween(55, 150)
  stream.glyphs[0] = makeGlyph()
  const mutations = Math.random() < 0.3 ? 3 : 2
  for (let index = 0; index < mutations; index += 1) {
    stream.glyphs[Math.floor(Math.random() * stream.glyphs.length)] = makeGlyph()
  }
}

function drawStream(context, stream, viewport) {
  const headRow = Math.floor(stream.head)

  for (let offset = stream.length - 1; offset >= 0; offset -= 1) {
    const row = headRow - offset
    if (row < -1 || row > viewport.rowCount + 1) continue

    const y = row * viewport.cellHeight
    const fade = Math.max(0, 1 - offset / stream.length)
    const glyph = stream.glyphs[offset]

    if (offset === 0) {
      context.globalAlpha = 1
      context.fillStyle = '#effff4'
      context.shadowColor = 'rgba(205, 255, 220, 0.98)'
      context.shadowBlur = viewport.fontSize * 0.95
      drawGlyph(context, glyph, stream.x, y)
      context.shadowBlur = 0
      continue
    }

    let alpha = Math.pow(fade, 1.18) * stream.intensity
    if (offset > stream.length * 0.76) alpha *= 0.46
    context.globalAlpha = Math.max(0.06, alpha)
    context.fillStyle = offset <= 2 ? '#83ffa1' : '#00f044'
    context.shadowColor = offset <= 2 ? 'rgba(60, 255, 110, 0.72)' : 'transparent'
    context.shadowBlur = offset <= 2 ? 4 : 0
    drawGlyph(context, glyph, stream.x, y)
  }

  context.globalAlpha = 1
  context.shadowBlur = 0
}

export default function CodeRainCanvas({ status = 'processing', compact = false, className = '' }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const container = canvas?.parentElement
    if (!canvas || !container) return undefined

    const context = canvas.getContext('2d', { alpha: false })
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const speedScale = status === 'pending' ? 0.62 : status === 'submitting' ? 0.72 : status === 'preparing' ? 0.86 : 1
    const frameInterval = 1000 / (compact ? 10 : 24)
    let viewport = null
    let streams = []
    let frameId = null
    let previousFrame = performance.now()
    let pageVisible = !document.hidden
    let inViewport = true
    let visible = pageVisible

    const configureText = () => {
      context.font = `600 ${viewport.fontSize}px "MS Gothic", "Noto Sans Mono CJK JP", "Yu Gothic", monospace`
      context.textAlign = 'center'
      context.textBaseline = 'top'
    }

    const buildStreams = () => {
      const columnCount = Math.ceil(viewport.width / viewport.columnWidth)
      streams = Array.from({ length: columnCount }, (_, index) => {
        const x = viewport.fontSize * 0.7 + index * viewport.columnWidth + randomBetween(-2, 2)
        const stream = makeStream(x, viewport.rowCount, speedScale, compact ? true : Math.random() > 0.18, compact)
        if (compact) {
          const phase = (index * 0.618 + Math.random() * 0.1) % 1
          stream.head = phase * (viewport.rowCount + stream.length)
        }
        return stream
      })
    }

    const resize = () => {
      const rect = container.getBoundingClientRect()
      const ratio = compact ? 1 : Math.min(window.devicePixelRatio || 1, 1.5)
      const fontSize = compact ? (rect.width < 230 ? 10 : 11) : (rect.width < 520 ? 18 : 20)
      const cellHeight = fontSize * 1.02
      const pixelWidth = Math.max(1, Math.round(rect.width * ratio))
      const pixelHeight = Math.max(1, Math.round(rect.height * ratio))

      if (viewport && canvas.width === pixelWidth && canvas.height === pixelHeight) return

      canvas.width = pixelWidth
      canvas.height = pixelHeight
      canvas.style.width = `${rect.width}px`
      canvas.style.height = `${rect.height}px`
      context.setTransform(ratio, 0, 0, ratio, 0, 0)

      viewport = {
        width: rect.width,
        height: rect.height,
        fontSize,
        cellHeight,
        columnWidth: fontSize * (compact ? 1.16 : 1.3),
        rowCount: Math.ceil(rect.height / cellHeight),
      }

      context.fillStyle = '#000301'
      context.fillRect(0, 0, viewport.width, viewport.height)
      configureText()
      buildStreams()
      render(0, false)
    }

    const render = (elapsedMs, advance) => {
      context.globalAlpha = 1
      context.shadowBlur = 0
      context.fillStyle = advance ? 'rgba(0, 3, 1, 0.3)' : '#000301'
      context.fillRect(0, 0, viewport.width, viewport.height)
      configureText()

      streams.forEach(stream => {
        if (advance) {
          stream.head += stream.speed * (elapsedMs / 1000)
          mutateStream(stream, elapsedMs)
          if (stream.head - stream.length > viewport.rowCount + 2) {
            resetStream(stream, viewport.rowCount, speedScale, compact)
          }
        }
        drawStream(context, stream, viewport)
      })
    }

    const animate = (time) => {
      if (!visible) return
      const elapsed = time - previousFrame
      if (elapsed >= frameInterval) {
        previousFrame = time - (elapsed % frameInterval)
        render(Math.min(elapsed, 100), true)
      }
      frameId = requestAnimationFrame(animate)
    }

    const syncAnimation = () => {
      visible = pageVisible && inViewport
      cancelAnimationFrame(frameId)
      frameId = null
      if (visible && !reducedMotion) {
        previousFrame = performance.now()
        frameId = requestAnimationFrame(animate)
      }
    }

    const onVisibilityChange = () => {
      pageVisible = !document.hidden
      syncAnimation()
    }

    const observer = new ResizeObserver(resize)
    observer.observe(container)
    const intersectionObserver = new IntersectionObserver(entries => {
      inViewport = entries[0]?.isIntersecting !== false
      syncAnimation()
    }, { rootMargin: '80px' })
    intersectionObserver.observe(canvas)
    resize()

    if (!reducedMotion) syncAnimation()
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      observer.disconnect()
      intersectionObserver.disconnect()
      document.removeEventListener('visibilitychange', onVisibilityChange)
      cancelAnimationFrame(frameId)
    }
  }, [compact, status])

  return <canvas ref={canvasRef} className={`absolute inset-0 size-full ${className}`} aria-hidden="true" />
}
