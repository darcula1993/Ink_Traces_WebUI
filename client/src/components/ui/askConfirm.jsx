import React from 'react'
import { createRoot } from 'react-dom/client'
import ConfirmDialog from './ConfirmDialog'

// Promise-based replacement for window.confirm(): same call shape, but rendered with the
// site's ConfirmDialog (focus trapped, Escape cancels, focus returns to the opener).
export default function askConfirm({ title = '请确认', message, confirmLabel = '确认', cancelLabel = '取消', danger = false } = {}) {
  return new Promise(resolve => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    let settled = false
    const finish = value => {
      if (settled) return
      settled = true
      resolve(value)
      root.unmount()
      host.remove()
    }
    root.render(
      <ConfirmDialog title={title} confirmLabel={confirmLabel} cancelLabel={cancelLabel} danger={danger} className="ink-confirm-top" onConfirm={() => finish(true)} onClose={() => finish(false)}>
        {typeof message === 'string' ? <p>{message}</p> : message}
      </ConfirmDialog>,
    )
  })
}
