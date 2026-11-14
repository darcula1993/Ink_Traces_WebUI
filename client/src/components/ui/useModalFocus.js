import { useEffect } from 'react'

// Modal focus contract shared by hand-built dialogs: focus moves into the dialog when it
// opens, Tab / Shift+Tab cycle inside it, and focus returns to the opener when it closes.
// Only the most recently opened modal handles Tab, so nested dialogs do not fight.
const FOCUSABLE = 'button:not(:disabled),[href],input:not(:disabled):not([type=hidden]),select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])'
const stack = []

// True when this dialog is the most recently opened modal (Escape handlers on window use this so a nested
// dialog closes first and its parent stays open).
export function isTopModal(ref) { return !stack.length || stack.at(-1).ref === ref }

export function focusableIn(node) {
  return [...node.querySelectorAll(FOCUSABLE)].filter(el => el.getClientRects().length && !el.closest('[inert]') && !el.hidden)
}

export default function useModalFocus(ref, active = true) {
  useEffect(() => {
    if (!active) return undefined
    const token = { ref }
    stack.push(token)
    const previous = document.activeElement
    const focusInitial = () => {
      const node = ref.current
      if (!node || node.contains(document.activeElement)) return
      const target = node.querySelector('[data-autofocus]') || focusableIn(node)[0] || node
      target.focus({ preventScroll: true })
    }
    focusInitial()
    // Animated dialogs may mount their content a frame later.
    const frame = requestAnimationFrame(focusInitial)
    const onKeyDown = event => {
      if (event.key !== 'Tab' || stack.at(-1) !== token) return
      const node = ref.current
      if (!node) return
      const current = document.activeElement
      // Another modal (e.g. a ConfirmDialog opened on top) owns its own Tab cycle.
      const owner = current?.closest?.('[aria-modal="true"]')
      if (owner && owner !== node) return
      const items = focusableIn(node)
      if (!items.length) { event.preventDefault(); node.focus({ preventScroll: true }); return }
      const first = items[0], last = items.at(-1)
      if (!node.contains(current)) { event.preventDefault(); (event.shiftKey ? last : first).focus(); return }
      if (event.shiftKey && (current === first || current === node)) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && current === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('keydown', onKeyDown, true)
      const index = stack.indexOf(token)
      if (index >= 0) stack.splice(index, 1)
      if (previous?.isConnected && previous !== document.body) previous.focus?.({ preventScroll: true })
    }
  }, [active])
}
