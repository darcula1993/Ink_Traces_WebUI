import React, { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, Check } from 'lucide-react'
import './select.css'

// Themed single-select dropdown (replaces native <select>). Focus stays on the trigger; the
// listbox uses aria-activedescendant. Keys: Arrow/Home/End move, Enter/Space choose, Esc closes,
// letters jump to a matching label. The menu is portalled and positioned from the trigger rect so
// popovers and dialogs with overflow/backdrop-filter never clip it.
export default function Select({ value, onChange, options, ariaLabel, placeholder = '请选择', disabled = false, className = '', id }) {
  const uid = useId()
  const triggerRef = useRef(null)
  const menuRef = useRef(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [pos, setPos] = useState(null)
  const list = useMemo(() => options.map(o => (typeof o === 'string' ? { value: o, label: o } : o)), [options])
  const selectedIndex = list.findIndex(o => o.value === value)
  const selected = list[selectedIndex]

  const place = () => {
    const r = triggerRef.current?.getBoundingClientRect()
    if (!r) return
    const maxH = 280
    const below = window.innerHeight - r.bottom - 8
    const up = below < Math.min(maxH, list.length * 34 + 12) && r.top > below
    setPos({ left: r.left, width: Math.max(r.width, 160), top: up ? undefined : r.bottom + 4, bottom: up ? window.innerHeight - r.top + 4 : undefined, maxH: Math.max(120, Math.min(maxH, (up ? r.top : below) - 8)) })
  }
  useLayoutEffect(() => { if (open) place() }, [open])
  useEffect(() => {
    if (!open) return
    const outside = e => { if (!menuRef.current?.contains(e.target) && !triggerRef.current?.contains(e.target)) setOpen(false) }
    const reflow = e => { if (menuRef.current?.contains(e.target)) return; setOpen(false) }
    document.addEventListener('pointerdown', outside, true)
    window.addEventListener('resize', reflow)
    window.addEventListener('scroll', reflow, true)
    return () => { document.removeEventListener('pointerdown', outside, true); window.removeEventListener('resize', reflow); window.removeEventListener('scroll', reflow, true) }
  }, [open])
  useEffect(() => { if (open) menuRef.current?.querySelector('[data-active="true"]')?.scrollIntoView?.({ block: 'nearest' }) }, [open, active])

  const openMenu = () => { if (disabled) return; setActive(selectedIndex >= 0 ? selectedIndex : 0); setOpen(true) }
  const choose = i => { const o = list[i]; if (o && !o.disabled && o.value !== value) onChange(o.value); setOpen(false); triggerRef.current?.focus({ preventScroll: true }) }
  const move = step => { if (!list.length) return; let i = active; for (let n = 0; n < list.length; n++) { i = (i + step + list.length) % list.length; if (!list[i].disabled) break } setActive(i) }

  const onKeyDown = e => {
    if (disabled) return
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) { e.preventDefault(); openMenu() }
      return
    }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setOpen(false); return }
    if (e.key === 'ArrowDown') { e.preventDefault(); move(1) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1) }
    else if (e.key === 'Home') { e.preventDefault(); setActive(0) }
    else if (e.key === 'End') { e.preventDefault(); setActive(list.length - 1) }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); choose(active) }
    else if (e.key === 'Tab') setOpen(false)
    else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
      const k = e.key.toLowerCase(), start = active + 1
      const hit = [...list.keys()].map(n => (n + start) % list.length).find(n => String(list[n].label).toLowerCase().startsWith(k))
      if (hit !== undefined) setActive(hit)
    }
  }

  return (
    <span className={`ui-select ${className}`}>
      <button ref={triggerRef} id={id} type="button" role="combobox" className="ui-select-trigger" aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? `${uid}-list` : undefined} aria-activedescendant={open && active >= 0 ? `${uid}-o${active}` : undefined} data-value={value ?? ''} disabled={disabled} onClick={() => (open ? setOpen(false) : openMenu())} onKeyDown={onKeyDown}>
        <span className={selected ? 'ui-select-value' : 'ui-select-value is-placeholder'}>{selected ? selected.label : placeholder}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && pos && createPortal(
        <ul ref={menuRef} id={`${uid}-list`} role="listbox" aria-label={ariaLabel} className="ui-select-menu" style={{ left: pos.left, minWidth: pos.width, top: pos.top, bottom: pos.bottom, maxHeight: pos.maxH }} onPointerDown={e => e.preventDefault()}>
          {list.map((o, i) => (
            <li key={o.value} id={`${uid}-o${i}`} role="option" aria-selected={o.value === value} aria-disabled={o.disabled || undefined} data-value={o.value} data-active={i === active} className="ui-select-option" onPointerEnter={() => setActive(i)} onClick={() => choose(i)}>
              <span>{o.label}</span>{o.value === value && <Check size={14} aria-hidden="true" />}
            </li>
          ))}
        </ul>, document.body)}
    </span>
  )
}
