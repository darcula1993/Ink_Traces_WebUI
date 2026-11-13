import React, { useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'

// Small modal confirmation shared by the task center and the canvas. It keeps
// focus inside, restores it on close and never runs the action on Escape.
export default function ConfirmDialog({ title, children, confirmLabel = '确认', cancelLabel = '取消', danger = false, onConfirm, onClose, className = '' }) {
  const ref = useRef(null), previous = useRef(null), [busy, setBusy] = useState(false), [error, setError] = useState('')
  useEffect(() => {
    previous.current = document.activeElement
    ref.current?.querySelector('[data-autofocus]')?.focus()
    return () => { if (previous.current?.isConnected) previous.current.focus?.({ preventScroll: true }) }
  }, [])
  async function confirm() {
    if (busy) return
    setBusy(true); setError('')
    try { await onConfirm() } catch (failure) { setError(failure?.response?.data?.error || failure?.message || '操作失败，请重试'); setBusy(false) }
  }
  function keydown(event) {
    event.stopPropagation()
    if (event.key === 'Escape' && !busy) { event.preventDefault(); onClose(); return }
    if (event.key !== 'Tab') return
    const items = [...ref.current.querySelectorAll('button:not(:disabled)')]
    if (!items.length) return
    if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1).focus() }
    else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus() }
  }
  return ReactDOM.createPortal(
    <div className={`ink-confirm-backdrop ${className}`} onPointerDown={event => { event.stopPropagation(); if (event.target === event.currentTarget && !busy) onClose() }}>
      <section ref={ref} className="ink-confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="ink-confirm-title" aria-describedby="ink-confirm-body" onKeyDown={keydown}>
        <h2 id="ink-confirm-title">{title}</h2>
        <div id="ink-confirm-body" className="ink-confirm-body">{children}</div>
        {error && <p role="alert" className="ink-confirm-error">{error}</p>}
        <footer>
          <button type="button" className="btn btn-secondary" data-autofocus disabled={busy} onClick={onClose}>{cancelLabel}</button>
          <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} disabled={busy} onClick={confirm}>{busy ? '处理中…' : confirmLabel}</button>
        </footer>
      </section>
    </div>,
    document.body,
  )
}
