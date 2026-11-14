import React, { useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'
import { Library, BookmarkPlus, Search } from 'lucide-react'
import { filterPrompts, promptPreview, canSavePrompt, nextActiveIndex, insertTextNatively } from '../../lib/promptLibrary'

// Prompt-library entry for the node panel. `getTextarea` returns the prompt textarea; `value` is its current text.
export default function PromptLibraryPicker({ getTextarea, value, onInsertFallback }) {
  const [open, setOpen] = useState(false)
  const [prompts, setPrompts] = useState([])
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const selection = useRef({ start: null, end: null })
  const searchRef = useRef(null), triggerRef = useRef(null)
  const visible = useMemo(() => filterPrompts(prompts, query), [prompts, query])

  const load = async () => {
    setLoading(true); setStatus('')
    try {
      const response = await axios.get('/api/prompts')
      if (response.data?.success) setPrompts(response.data.prompts || [])
      else setStatus('提示词库同步失败')
    } catch { setStatus('无法加载提示词库') } finally { setLoading(false) }
  }

  const openPicker = () => {
    const textarea = getTextarea()
    selection.current = textarea ? { start: textarea.selectionStart, end: textarea.selectionEnd } : { start: null, end: null }
    setQuery(''); setActive(0); setOpen(true); load()
  }
  useEffect(() => { if (open) searchRef.current?.focus() }, [open])
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
    <div className="cv-prompt-library" data-testid="prompt-library">
      <button type="button" ref={triggerRef} className="btn btn-ghost btn-sm" aria-haspopup="dialog" aria-expanded={open} title="从提示词库插入" aria-label="从提示词库插入" onClick={() => (open ? close() : openPicker())}><Library size={13} aria-hidden="true" /><span>提示词库</span></button>
      <button type="button" className="btn btn-ghost btn-sm" disabled={!canSavePrompt(value)} title="把当前提示词存入提示词库" aria-label="存入提示词库" onClick={save}><BookmarkPlus size={13} aria-hidden="true" /><span>存入提示词库</span></button>
      <span className="cv-prompt-library-status" role="status" aria-live="polite" data-testid="prompt-library-status">{status}</span>
      {open && (
        <div className="cv-prompt-library-popover" role="dialog" aria-label="提示词库" onKeyDown={onKeyDown}>
          <label className="cv-prompt-library-search"><Search size={13} aria-hidden="true" /><input ref={searchRef} role="combobox" aria-expanded="true" aria-controls="cv-prompt-library-list" aria-activedescendant={visible[active] ? `cv-prompt-option-${visible[active].id}` : undefined} aria-label="搜索提示词" placeholder="搜索提示词" value={query} onChange={event => setQuery(event.target.value)} /></label>
          <div id="cv-prompt-library-list" role="listbox" aria-label="提示词列表" className="cv-prompt-library-list">
            {loading && !prompts.length ? <div className="cv-prompt-library-empty" role="status">加载中…</div>
              : visible.length === 0 ? <div className="cv-prompt-library-empty" role="status">{query ? '没有匹配的提示词' : '提示词库为空'}</div>
              : visible.map((prompt, index) => (
                <button type="button" key={prompt.id} id={`cv-prompt-option-${prompt.id}`} role="option" aria-selected={index === active} tabIndex={-1} className={`cv-prompt-library-option ${index === active ? 'is-active' : ''}`} title="插入到光标处" onMouseEnter={() => setActive(index)} onMouseDown={event => { event.preventDefault(); insert(prompt) }}>{promptPreview(prompt.text)}</button>
              ))}
          </div>
        </div>
      )}
    </div>
  )
}
