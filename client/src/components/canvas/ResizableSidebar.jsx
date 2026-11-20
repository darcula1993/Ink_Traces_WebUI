import React, {useEffect, useRef, useState} from 'react'

const STORAGE_KEY = 'ink-traces.canvas.sidebar-width.v1'
const BASE_DEFAULT_WIDTH = 300
const clamp = (value, min, max) => Math.max(min, Math.min(max, value))
function readWidth(storageKey, fallback) {
  try {
    const saved = Number(localStorage.getItem(storageKey))
    return Number.isFinite(saved) && saved >= 160 && saved <= 640 ? saved : fallback
  } catch { return fallback }
}

// CANVAS-LAYOUT-2-20261118: also hosts the left rail's pop-out panel (pinned or floating). Without the new
// props it behaves exactly as the old sidebar shell. `minWidth`/`maxWidth` are in px (spec: 240–360),
// `reserve` is the width kept for the rest of the layout, `onWidth` reports the effective width.
export default function ResizableSidebar({children, className = '', storageKey = STORAGE_KEY, minWidth = null, maxWidth = 640,
  defaultWidth = BASE_DEFAULT_WIDTH, reserve = 480, label = '调整左侧栏宽度', onWidth, ...rest}) {
  const shell = useRef(null), gesture = useRef(null), endGuard = useRef(null)
  const fallbackWidth = () => Math.round(defaultWidth)
  const [preferred, setPreferred] = useState(() => readWidth(storageKey, fallbackWidth()))
  const [available, setAvailable] = useState(1440)
  const [dragging, setDragging] = useState(false)
  const floor = minWidth == null ? 160 : minWidth
  const max = Math.min(maxWidth, Math.max(floor, available - reserve)), min = Math.min(minWidth == null ? 280 : floor, max)
  const width = clamp(preferred, min, max)
  useEffect(() => { onWidth?.(width) }, [width])

  useEffect(() => {
    const parent = shell.current.parentElement
    const observer = new ResizeObserver(([entry]) => setAvailable(entry.contentRect.width))
    observer.observe(parent)
    setAvailable(parent.clientWidth)
    return () => observer.disconnect()
  }, [])

  const persist = value => {
    setPreferred(value)
    try { localStorage.setItem(storageKey, String(value)) } catch { /* Layout remains usable without storage. */ }
  }
  const finish = (event, cancel = false) => {
    const current = gesture.current
    if (!current || current.id !== event.pointerId) return
    gesture.current = null
    setDragging(false)
    if (cancel) setPreferred(current.original)
    else persist(current.value)
    if (event.currentTarget.hasPointerCapture(current.id)) event.currentTarget.releasePointerCapture(current.id)
  }
  useEffect(() => {
    if (!dragging) return undefined
    const cancel = () => {
      const current = gesture.current
      if (current) finish({pointerId: current.id, currentTarget: current.element}, true)
    }
    window.addEventListener('blur', cancel)
    return () => window.removeEventListener('blur', cancel)
  }, [dragging])
  useEffect(() => () => endGuard.current?.(), [])

  // A cancelled capture must not deliver its eventual release to a canvas node.
  const guardRelease = (id, element) => {
    endGuard.current?.()
    const cleanup = () => {
      window.removeEventListener('pointerup', end, true)
      window.removeEventListener('pointercancel', end, true)
      window.removeEventListener('pointerdown', cleanup, true)
      endGuard.current = null
    }
    const end = event => {
      if (event.pointerId !== id) return
      event.stopPropagation()
      finish({pointerId: id, currentTarget: element}, event.type === 'pointercancel')
      cleanup()
    }
    window.addEventListener('pointerup', end, true)
    window.addEventListener('pointercancel', end, true)
    window.addEventListener('pointerdown', cleanup, true)
    endGuard.current = cleanup
  }

  return <div ref={shell} {...rest} className={`cv-sidebar-shell${className ? ` ${className}` : ''}${dragging ? ' is-resizing' : ''}`} style={{width, flexBasis: width}}>
    {children}
    <div className="cv-sidebar-resizer" role="separator" aria-label={label} aria-orientation="vertical"
      aria-valuemin={Math.round(min)} aria-valuemax={Math.round(max)} aria-valuenow={Math.round(width)}
      aria-valuetext={`${Math.round(width)} 像素`} tabIndex={0} title="拖动调整宽度；双击恢复默认；方向键微调"
      onPointerDown={event => {
        if (event.button !== 0 || gesture.current) return
        event.preventDefault(); event.stopPropagation(); event.currentTarget.focus()
        gesture.current = {id: event.pointerId, x: event.clientX, start: width, original: preferred, value: width, element: event.currentTarget}
        guardRelease(event.pointerId, event.currentTarget)
        event.currentTarget.setPointerCapture(event.pointerId); setDragging(true)
      }}
      onPointerMove={event => {
        const current = gesture.current
        if (!current || current.id !== event.pointerId) return
        event.preventDefault(); event.stopPropagation()
        current.value = clamp(current.start + event.clientX - current.x, min, max)
        setPreferred(current.value)
      }}
      onPointerUp={event => finish(event)} onPointerCancel={event => finish(event, true)}
      onLostPointerCapture={event => finish(event, true)}
      onDoubleClick={() => persist(fallbackWidth())}
      onKeyDown={event => {
        if (event.key === 'Escape' && gesture.current) {
          event.preventDefault(); event.stopPropagation()
          finish({pointerId: gesture.current.id, currentTarget: event.currentTarget}, true)
        } else if (!gesture.current && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
          event.preventDefault(); event.stopPropagation()
          persist(event.key === 'Home' ? min : event.key === 'End' ? max : clamp(width + (event.key === 'ArrowRight' ? 16 : -16), min, max))
        }
      }} />
  </div>
}
