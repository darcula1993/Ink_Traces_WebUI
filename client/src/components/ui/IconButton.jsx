import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { computeTooltipPosition } from './tooltipPosition.js'

export { computeTooltipPosition }

function cleanTooltipClassName(className) {
  return String(className || '')
    .split(/\s+/)
    .filter(token => token && !/^!?(left|right|top|bottom|mt|mb|-?translate-x|icon-tooltip-above)/.test(token))
    .join(' ')
}

export default function IconButton({
  label,
  children,
  className = '',
  tooltipClassName = '',
  tooltipAlign,
  tooltipPlacement,
  onClick,
  onPointerDown,
  onMouseEnter,
  onMouseLeave,
  onFocus,
  onBlur,
  onKeyDown,
  ...props
}) {
  const buttonRef = useRef(null)
  const tipRef = useRef(null)
  const suppressedRef = useRef(false)
  const tooltipId = useId()
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState(null)

  const expanded = props['aria-expanded'] === true || props['aria-expanded'] === 'true'
  const disabled = Boolean(props.disabled || props['aria-disabled'] === true || props['aria-disabled'] === 'true')
  const effectivePlacement = tooltipPlacement || (/\bicon-tooltip-above\b/.test(tooltipClassName) ? 'top' : 'bottom')
  const effectiveAlign = tooltipAlign || (/\bright-0\b/.test(tooltipClassName) ? 'end' : /\bleft-0\b/.test(tooltipClassName) ? 'start' : 'center')

  const hide = useCallback(() => {
    setOpen(false)
    setCoords(null)
  }, [])

  const show = useCallback(() => {
    if (!label || disabled || expanded || suppressedRef.current) return
    setOpen(true)
  }, [disabled, expanded, label])

  useEffect(() => {
    if (disabled || expanded) hide()
  }, [disabled, expanded, hide])

  const updatePosition = useCallback(() => {
    const anchor = buttonRef.current
    const tip = tipRef.current
    if (!anchor || !tip || !anchor.isConnected) {
      hide()
      return
    }
    const rect = anchor.getBoundingClientRect()
    if (rect.width === 0 && rect.height === 0) {
      hide()
      return
    }
    const tipRect = tip.getBoundingClientRect()
    const pos = computeTooltipPosition(
      rect,
      { width: tipRect.width, height: tipRect.height },
      { width: window.innerWidth, height: window.innerHeight },
      { preferredPlacement: effectivePlacement, align: effectiveAlign },
    )
    setCoords(prev => (prev && prev.top === pos.top && prev.left === pos.left && prev.placement === pos.placement ? prev : pos))
  }, [effectiveAlign, effectivePlacement, hide])

  useLayoutEffect(() => {
    if (!open) return undefined
    updatePosition()
    const frame = requestAnimationFrame(updatePosition)
    return () => cancelAnimationFrame(frame)
  }, [open, label, updatePosition])

  useEffect(() => {
    if (!open) return undefined
    const onGlobalDismiss = event => {
      if (event.type === 'keydown' && event.key !== 'Escape') return
      if (event.type === 'focusin' && buttonRef.current?.contains(event.target)) return
      hide()
    }
    const onDialogCheck = () => {
      const anchor = buttonRef.current
      if (!anchor || !anchor.isConnected) {
        hide()
        return
      }
      const dialogs = document.querySelectorAll('[role="dialog"], [role="alertdialog"], .drawer-panel')
      for (const dlg of dialogs) {
        if (!dlg.contains(anchor)) {
          hide()
          return
        }
      }
    }
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', updatePosition)
    window.addEventListener('blur', hide)
    document.addEventListener('pointerdown', onGlobalDismiss, true)
    document.addEventListener('keydown', onGlobalDismiss, true)
    document.addEventListener('focusin', onGlobalDismiss, true)
    const observer = new MutationObserver(onDialogCheck)
    observer.observe(document.body, { childList: true, subtree: true })
    return () => {
      window.removeEventListener('scroll', hide, true)
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('blur', hide)
      document.removeEventListener('pointerdown', onGlobalDismiss, true)
      document.removeEventListener('keydown', onGlobalDismiss, true)
      document.removeEventListener('focusin', onGlobalDismiss, true)
      observer.disconnect()
    }
  }, [hide, open, updatePosition])

  const extraTipClasses = cleanTooltipClassName(tooltipClassName)

  return (
    <span className="relative inline-flex shrink-0">
      <button
        ref={buttonRef}
        type="button"
        aria-label={label}
        aria-describedby={open ? tooltipId : undefined}
        className={`btn btn-icon ${className}`}
        onMouseEnter={event => {
          show()
          onMouseEnter?.(event)
        }}
        onMouseLeave={event => {
          suppressedRef.current = false
          hide()
          onMouseLeave?.(event)
        }}
        onFocus={event => {
          if (!suppressedRef.current) show()
          onFocus?.(event)
        }}
        onBlur={event => {
          suppressedRef.current = false
          hide()
          onBlur?.(event)
        }}
        onPointerDown={event => {
          suppressedRef.current = true
          hide()
          onPointerDown?.(event)
        }}
        onClick={event => {
          suppressedRef.current = true
          hide()
          onClick?.(event)
        }}
        onKeyDown={event => {
          if (event.key === 'Escape' || event.key === 'Enter' || event.key === ' ') {
            suppressedRef.current = true
            hide()
          }
          onKeyDown?.(event)
        }}
        {...props}
      >
        {children}
      </button>
      {open && typeof document !== 'undefined' && ReactDOM.createPortal(
        <span
          ref={tipRef}
          id={tooltipId}
          role="tooltip"
          data-placement={coords?.placement || effectivePlacement}
          style={coords ? { position: 'fixed', top: `${coords.top}px`, left: `${coords.left}px`, visibility: 'visible' } : { position: 'fixed', top: 0, left: 0, visibility: 'hidden' }}
          className={`pointer-events-none z-[9999] max-w-[calc(100vw-16px)] whitespace-nowrap rounded-[var(--r-sm)] border border-[var(--border-strong)] bg-[var(--surface-raised)] px-2 py-1 text-xs text-[var(--text)] shadow-[var(--shadow-2)] ${extraTipClasses}`}
        >
          {label}
        </span>,
        document.body,
      )}
    </span>
  )
}
