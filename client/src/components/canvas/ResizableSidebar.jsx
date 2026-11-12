import React, {useEffect, useRef, useState} from 'react'

const STORAGE_KEY = 'ink-traces.canvas.sidebar-width.v1'
const DEFAULT_WIDTH = 300
const clamp = (value, min, max) => Math.max(min, Math.min(max, value))
function readWidth() {
  try {
    const saved = Number(localStorage.getItem(STORAGE_KEY))
    return Number.isFinite(saved) && saved >= 160 && saved <= 640 ? saved : DEFAULT_WIDTH
  } catch { return DEFAULT_WIDTH }
}

export default function ResizableSidebar({children}) {
  const shell = useRef(null), gesture = useRef(null), endGuard = useRef(null)
  const [preferred, setPreferred] = useState(readWidth)
  const [available, setAvailable] = useState(1440)
  const [dragging, setDragging] = useState(false)
  const max = Math.min(640, Math.max(160, available - 480)), min = Math.min(280, max)
  const width = clamp(preferred, min, max)

  useEffect(() => {
    const parent = shell.current.parentElement
    const observer = new ResizeObserver(([entry]) => setAvailable(entry.contentRect.width))
    observer.observe(parent)
    setAvailable(parent.clientWidth)
    return () => observer.disconnect()
  }, [])

  const persist = value => {
    setPreferred(value)
    try { localStorage.setItem(STORAGE_KEY, String(value)) } catch { /* Layout remains usable without storage. */ }
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

  return <div ref={shell} className={`cv-sidebar-shell${dragging ? ' is-resizing' : ''}`} style={{width, flexBasis: width}}>
    {children}
    <div className="cv-sidebar-resizer" role="separator" aria-label="调整左侧栏宽度" aria-orientation="vertical"
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
      onDoubleClick={() => persist(DEFAULT_WIDTH)}
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
