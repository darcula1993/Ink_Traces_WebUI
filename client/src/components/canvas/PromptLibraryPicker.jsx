import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import axios from 'axios'
import { Library, BookmarkPlus, Search } from 'lucide-react'
import { filterPrompts, promptPreview, canSavePrompt, nextActiveIndex, insertTextNatively } from '../../lib/promptLibrary'

// CANVAS-LAYOUT-2-20261118: the library loading and the search + listbox are reusable (rail panel
// CanvasPromptPanel); the picker keeps its DOM, ids and behaviour.
export function usePromptLibrary() {
  const [prompts, setPrompts] = useState([])
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const load = async () => {
    setLoading(true); setStatus('')
    try {
      const response = await axios.get('/api/prompts')
      if (response.data?.success) setPrompts(response.data.prompts || [])
      else setStatus('提示词库同步失败')
    } catch { setStatus('无法加载提示词库') } finally { setLoading(false) }
  }
  return { prompts, status, setStatus, loading, load }
}

// Inserts at the given (or the textarea's own) selection with native undo; falls back to `onFallback(next)`.
export function insertPromptText(textarea, text, { value = '', start, end, onFallback } = {}) {
  const from = start ?? textarea?.selectionStart ?? null, to = end ?? textarea?.selectionEnd ?? null
  if (insertTextNatively(textarea, text, from, to)) return true
  const base = String(value || ''), at = from ?? base.length, until = to ?? at
  onFallback?.(`${base.slice(0, at)}${text}${base.slice(until)}`)
  textarea?.focus()
  return false
}

// Search box + listbox. `pickOn` is 'mousedown' (popover: keeps the prompt textarea selection) or 'click'.
export function PromptLibraryList({ listId, optionPrefix, inputRef, query, onQuery, prompts, visible, active, onActive, onPick, loading, pickOn = 'mousedown', optionTitle = '插入到光标处' }) {
  return <>
    <label className="cv-prompt-library-search"><Search size={13} aria-hidden="true" /><input ref={inputRef} role="combobox" aria-expanded="true" aria-controls={listId} aria-activedescendant={visible[active] ? `${optionPrefix}${visible[active].id}` : undefined} aria-label="搜索提示词" placeholder="搜索提示词" value={query} onChange={event => onQuery(event.target.value)} /></label>
    <div id={listId} role="listbox" aria-label="提示词列表" className="cv-prompt-library-list">
      {loading && !prompts.length ? <div className="cv-prompt-library-empty" role="status">加载中…</div>
        : visible.length === 0 ? <div className="cv-prompt-library-empty" role="status">{query ? '没有匹配的提示词' : '提示词库为空'}</div>
        : visible.map((prompt, index) => (
          <button type="button" key={prompt.id} id={`${optionPrefix}${prompt.id}`} role="option" aria-selected={index === active} tabIndex={-1} className={`cv-prompt-library-option ${index === active ? 'is-active' : ''}`} title={optionTitle} onMouseEnter={pickOn === 'mousedown' ? () => onActive(index) : undefined}
            {...(pickOn === 'mousedown' ? { onMouseDown: event => { event.preventDefault(); onPick(prompt, index) } } : { onClick: () => onPick(prompt, index) })}>{promptPreview(prompt.text)}</button>
        ))}
    </div>
  </>
}

// Prompt-library entry for the node panel. `getTextarea` returns the prompt textarea; `value` is its current text.
// `compact`: icon-only trigger (card prompt, CANVAS-LAYOUT-2-WIRE) without the save button and status text.
export default function PromptLibraryPicker({ getTextarea, value, onInsertFallback, compact = false, label = '从提示词库插入' }) {
  const [open, setOpen] = useState(false)
  const { prompts, status, setStatus, loading, load } = usePromptLibrary()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [anchor, setAnchor] = useState(null)
  const selection = useRef({ start: null, end: null })
  const searchRef = useRef(null), triggerRef = useRef(null)
  const visible = useMemo(() => filterPrompts(prompts, query), [prompts, query])

  const openPicker = () => {
    const textarea = getTextarea()
    selection.current = textarea ? { start: textarea.selectionStart, end: textarea.selectionEnd } : { start: null, end: null }
    const rect = triggerRef.current?.getBoundingClientRect()
    if (rect) setAnchor({ left: Math.max(8, Math.min(rect.left, window.innerWidth - 368)), bottom: Math.max(8, window.innerHeight - rect.top + 4) })
    setQuery(''); setActive(0); setOpen(true); load()
  }
  useEffect(() => { if (open) searchRef.current?.focus() }, [open])
  // FIX-B2-20261114 #3: the popover is portalled out of the scrolling node panel (which clipped it) and
  // placed in viewport coordinates next to the trigger: above when it fits, else below, clamped on screen.
  const popoverRef = useRef(null), [place, setPlace] = useState(null)
  useLayoutEffect(() => {
    if (!open) { setPlace(null); return undefined }
    const position = () => {
      const trigger = triggerRef.current?.getBoundingClientRect(), popover = popoverRef.current
      if (!trigger || !popover) return
      const margin = 8, gap = 4, vw = window.innerWidth, vh = window.innerHeight, width = Math.min(360, vw - 2 * margin), height = popover.offsetHeight
      const left = Math.max(margin, Math.min(vw - width - margin, trigger.left)), above = trigger.top - gap - margin, below = vh - trigger.bottom - gap - margin
      const up = height <= above || above >= below, maxHeight = Math.max(120, up ? above : below)
      setPlace({ left, width, maxHeight, ...(up ? { bottom: vh - trigger.top + gap } : { top: trigger.bottom + gap }) })
    }
    position()
    window.addEventListener('resize', position); window.addEventListener('scroll', position, true)
    return () => { window.removeEventListener('resize', position); window.removeEventListener('scroll', position, true) }
  }, [open, loading, visible.length])
  useEffect(() => { setActive(0) }, [query])

  const close = () => { setOpen(false); (getTextarea() || triggerRef.current)?.focus() }

  const insert = prompt => {
    if (!prompt) return
    const textarea = getTextarea()
    const { start, end } = selection.current
    setOpen(false)
    if (!insertTextNatively(textarea, prompt.text, start, end)) {
      const base = String(value || ''), from = start ?? base.length, to = end ?? from
      onInsertFallback(`${base.slice(0, from)}${prompt.text}${base.slice(to)}`)
      textarea?.focus()
    }
  }

  const save = async () => {
    if (!canSavePrompt(value)) return
    setStatus('')
    try {
      const response = await axios.post('/api/prompts', { text: String(value).trim() })
      setStatus(response.data?.success ? '已存入提示词库' : '存入失败')
      if (response.data?.success && open) load()
    } catch { setStatus('存入失败') }
  }

  const onKeyDown = event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close() }
    else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setActive(index => nextActiveIndex(index, visible.length, event.key)) }
    else if (event.key === 'Enter' && !event.nativeEvent?.isComposing) { event.preventDefault(); insert(visible[active]) }
  }

  return (
    <div className={`cv-prompt-library${compact ? ' is-compact' : ''}`} data-testid={compact ? 'card-prompt-library' : 'prompt-library'} onPointerDown={compact ? event => event.stopPropagation() : undefined}>
      <button type="button" ref={triggerRef} className={compact ? 'cv-card-prompt-library' : 'btn btn-ghost btn-sm'} aria-haspopup="dialog" aria-expanded={open} title={label} aria-label={label} onMouseDown={compact ? event => event.preventDefault() : undefined} onClick={event => { if (compact) event.stopPropagation(); open ? close() : openPicker() }}><Library size={compact ? 16 : 13} aria-hidden="true" />{!compact && <span>提示词库</span>}</button>
      {!compact && <button type="button" className="btn btn-ghost btn-sm" disabled={!canSavePrompt(value)} title="把当前提示词存入提示词库" aria-label="存入提示词库" onClick={save}><BookmarkPlus size={13} aria-hidden="true" /><span>存入提示词库</span></button>}
      {!compact && <span className="cv-prompt-library-status" role="status" aria-live="polite" data-testid="prompt-library-status">{status}</span>}
      {open && createPortal(
        <div ref={popoverRef} className="cv-prompt-library-popover is-floating" role="dialog" aria-label="提示词库" onKeyDown={onKeyDown} onPointerDown={event => event.stopPropagation()} style={place ? { position: 'fixed', ...place } : { position: 'fixed', left: 0, top: 0, opacity: 0 }}>
          <PromptLibraryList listId="cv-prompt-library-list" optionPrefix="cv-prompt-option-" inputRef={searchRef} query={query} onQuery={setQuery} prompts={prompts} visible={visible} active={active} onActive={setActive} onPick={insert} loading={loading} />
        </div>, triggerRef.current?.closest('.canvas-studio') || document.body
      )}
    </div>
  )
}
