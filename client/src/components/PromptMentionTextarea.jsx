import React, { useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { AudioLines, Film, Image as ImageIcon } from 'lucide-react'
import { referenceTokenRanges, referenceDeletionRange } from '../lib/referenceMedia.js'
import { arrowSelection, snapSelection, referenceAt } from '../lib/referenceCaret.js'

const MENU_WIDTH = 288
const MENU_MAX_HEIGHT = 280

export function findPromptMention(value, cursor) {
  const safeValue = String(value || '')
  const safeCursor = Math.max(0, Math.min(Number(cursor) || 0, safeValue.length))
  const atIndex = safeValue.lastIndexOf('@', safeCursor - 1)
  if (atIndex < 0) return null

  const candidate = safeValue.slice(atIndex, safeCursor)
  // V140 #15: Chinese queries (@图 / @图片1 / @视频) as well as the English alias.
  const match = candidate.match(/^@([a-zA-Z\u4e00-\u9fff]*\d*)$/)
  if (!match) return null
  return { start: atIndex, end: safeCursor, query: match[1].toLowerCase() }
}

export function insertPromptMention(value, mention, token) {
  const safeValue = String(value || '')
  if (!mention || !token) return { value: safeValue, cursor: mention?.end || 0 }
  const nextValue = `${safeValue.slice(0, mention.start)}${token}${safeValue.slice(mention.end)}`
  return { value: nextValue, cursor: mention.start + token.length }
}

function caretViewportPosition(textarea) {
  const style = window.getComputedStyle(textarea)
  const rect = textarea.getBoundingClientRect()
  const mirror = document.createElement('div')
  const copiedProperties = [
    'boxSizing', 'borderLeftWidth', 'borderRightWidth', 'borderTopWidth', 'borderBottomWidth',
    'fontFamily', 'fontSize', 'fontStyle', 'fontWeight', 'letterSpacing', 'lineHeight',
    'paddingLeft', 'paddingRight', 'paddingTop', 'paddingBottom', 'textAlign', 'textIndent',
    'textTransform', 'wordSpacing', 'tabSize',
  ]

  mirror.style.position = 'fixed'
  mirror.style.left = `${rect.left}px`
  mirror.style.top = `${rect.top}px`
  mirror.style.width = `${rect.width}px`
  mirror.style.height = `${rect.height}px`
  mirror.style.visibility = 'hidden'
  mirror.style.overflow = 'hidden'
  mirror.style.whiteSpace = 'pre-wrap'
  mirror.style.wordWrap = 'break-word'
  copiedProperties.forEach(property => { mirror.style[property] = style[property] })
  mirror.textContent = textarea.value.slice(0, textarea.selectionStart)

  const marker = document.createElement('span')
  marker.textContent = textarea.value.slice(textarea.selectionStart) || '.'
  mirror.appendChild(marker)
  document.body.appendChild(mirror)

  const markerRect = marker.getBoundingClientRect()
  const lineHeight = Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.5
  const position = {
    left: markerRect.left - textarea.scrollLeft,
    top: markerRect.top - textarea.scrollTop,
    lineHeight,
  }
  mirror.remove()
  return position
}

// Text index of the reference token under a viewport point, via a mirror of the textarea's text layout.
function tokenAtPoint(textarea, ranges, clientX, clientY) {
  if (!ranges.length) return null
  const style = window.getComputedStyle(textarea), rect = textarea.getBoundingClientRect()
  const mirror = document.createElement('div')
  for (const property of ['boxSizing', 'borderLeftWidth', 'borderRightWidth', 'borderTopWidth', 'borderBottomWidth', 'borderStyle', 'fontFamily', 'fontSize', 'fontStyle', 'fontWeight', 'letterSpacing', 'lineHeight', 'paddingLeft', 'paddingRight', 'paddingTop', 'paddingBottom', 'textAlign', 'textIndent', 'textTransform', 'wordSpacing', 'tabSize', 'overflowWrap', 'wordBreak']) mirror.style[property] = style[property]
  Object.assign(mirror.style, { position: 'fixed', left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`, visibility: 'hidden', overflowX: 'hidden', overflowY: textarea.scrollHeight > textarea.clientHeight ? 'scroll' : 'hidden', whiteSpace: 'pre-wrap', wordWrap: 'break-word', borderColor: 'transparent' })
  const value = textarea.value, spans = []
  let cursor = 0
  for (const range of ranges) {
    mirror.appendChild(document.createTextNode(value.slice(cursor, range.start)))
    const span = document.createElement('span'); span.textContent = value.slice(range.start, range.end); mirror.appendChild(span); spans.push([span, range]); cursor = range.end
  }
  mirror.appendChild(document.createTextNode(value.slice(cursor) || ' '))
  document.body.appendChild(mirror)
  mirror.scrollTop = textarea.scrollTop
  let hit = null
  for (const [span, range] of spans) if ([...span.getClientRects()].some(box => clientX >= box.left && clientX <= box.right && clientY >= box.top && clientY <= box.bottom)) { hit = { range, box: span.getBoundingClientRect() }; break }
  mirror.remove()
  return hit
}

// V140 #18: a mirror layer above the textarea tints valid references green and stale ones amber.
// It copies the textarea's font, padding, wrapping and scroll, is aria-hidden and never takes pointer
// events, so typing, IME, selection and screen readers keep working on the textarea itself.
const MIRROR_PROPERTIES = ['boxSizing', 'borderLeftWidth', 'borderRightWidth', 'borderTopWidth', 'borderBottomWidth', 'fontFamily', 'fontSize', 'fontStyle', 'fontWeight', 'fontVariantLigatures', 'letterSpacing', 'lineHeight', 'paddingLeft', 'paddingRight', 'paddingTop', 'paddingBottom', 'textAlign', 'textIndent', 'textTransform', 'wordSpacing', 'tabSize', 'overflowWrap', 'wordBreak', 'whiteSpace']
function ReferenceHighlight({ textareaRef, value, tokenState }) {
  const layerRef = useRef(null), [box, setBox] = useState(null)
  const ranges = useMemo(() => referenceTokenRanges(value), [value])
  useLayoutEffect(() => {
    const textarea = textareaRef.current
    if (!textarea || !ranges.length) return undefined
    const sync = () => {
      const style = window.getComputedStyle(textarea), copied = {}
      for (const property of MIRROR_PROPERTIES) copied[property] = style[property]
      const borders = parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth)
      const scrollbar = Math.max(0, textarea.offsetWidth - textarea.clientWidth - borders)
      setBox({ ...copied, left: textarea.offsetLeft, top: textarea.offsetTop, width: textarea.offsetWidth - scrollbar, height: textarea.offsetHeight })
      if (layerRef.current) layerRef.current.scrollTop = textarea.scrollTop
    }
    sync()
    const scroll = () => { if (layerRef.current) layerRef.current.scrollTop = textarea.scrollTop }
    const observer = new ResizeObserver(sync)
    observer.observe(textarea)
    textarea.addEventListener('scroll', scroll)
    return () => { observer.disconnect(); textarea.removeEventListener('scroll', scroll) }
  }, [textareaRef, ranges])
  useLayoutEffect(() => { if (layerRef.current && textareaRef.current) layerRef.current.scrollTop = textareaRef.current.scrollTop })
  if (!ranges.length || !box) return null
  const parts = []
  let cursor = 0
  for (const range of ranges) {
    parts.push(value.slice(cursor, range.start))
    parts.push(<mark key={range.start} className={`prompt-reference-token is-${tokenState(range.token)}`}>{value.slice(range.start, range.end)}</mark>)
    cursor = range.end
  }
  parts.push(`${value.slice(cursor)}\u200b`)
  const { left, top, width, height, ...font } = box
  return <div ref={layerRef} aria-hidden="true" className="prompt-reference-highlight" data-testid="prompt-reference-highlight" style={{ ...font, position: 'absolute', left, top, width, height, overflow: 'hidden', pointerEvents: 'none', color: 'transparent', borderStyle: 'solid', borderColor: 'transparent', background: 'transparent', margin: 0, zIndex: 1 }}>{parts}</div>
}

function MentionThumbnail({ item }) {
  if (item.type === 'image' && item.preview) {
    return <img src={item.preview} alt="" className="size-full object-cover" />
  }
  if (item.type === 'video' && item.thumbnail) {
    return <img src={item.thumbnail} alt="" className="size-full object-cover" />
  }
  if (item.type === 'video') return <Film size={16} />
  if (item.type === 'audio') return <AudioLines size={16} />
  return <ImageIcon size={16} />
}

export default function PromptMentionTextarea({
  value,
  onValueChange,
  onMentionSelect,
  mentionItems = [],
  wrapperClassName = '',
  menuClassName = '',
  className = '',
  onKeyDown,
  onChange,
  referenceTokenState,
  ...textareaProps
}) {
  const textareaRef = useRef(null), dismissedMention = useRef(null), composing = useRef(false)
  const menuId = useId()
  const [mention, setMention] = useState(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [menuPosition, setMenuPosition] = useState({ left: 8, top: 8 })
  // V140 #12: hovering a reference (or putting the caret on it) previews the referenced item; no inline thumbnails.
  const [peek, setPeek] = useState(null), peekFrame = useRef(0), peekId = useId()
  const itemsByToken = useMemo(() => new Map(mentionItems.map(item => [item.token, item])), [mentionItems])
  const showPeek = (range, anchor, source) => {
    if (!range) { setPeek(current => current?.source === source ? null : current); return }
    const item = itemsByToken.get(range.token)
    setPeek({ source, token: range.token, item, left: Math.max(8, Math.min(anchor.left, window.innerWidth - 248)), top: anchor.top })
  }
  const peekAtCaret = textarea => {
    if (!textarea || textarea.selectionStart !== textarea.selectionEnd) { showPeek(null, null, 'caret'); return }
    const range = referenceTokenRanges(textarea.value).find(item => textarea.selectionStart > item.start && textarea.selectionStart <= item.end)
    if (!range) { showPeek(null, null, 'caret'); return }
    const caret = caretViewportPosition(textarea)
    showPeek(range, { left: caret.left, top: caret.top + caret.lineHeight + 6 }, 'caret')
  }

  const filteredItems = useMemo(() => {
    if (!mention?.query) return mentionItems
    return mentionItems.filter(item => (
      item.label.toLowerCase().includes(mention.query)
      || String(item.alias || '').toLowerCase().includes(mention.query)
      || String(item.name || '').toLowerCase().includes(mention.query)
    ))
  }, [mention?.query, mentionItems])

  const updateMention = (nextValue, cursor) => {
    if(dismissedMention.current===`${nextValue}\u0000${cursor}`){setMention(null);return}
    dismissedMention.current=null
    let nextMention = findPromptMention(nextValue, cursor)
    // A complete reference (just inserted or typed out) does not reopen the menu.
    if (nextMention?.query && mentionItems.some(item => item.label.toLowerCase() === nextMention.query)) nextMention = null
    // Ordinary Chinese text after @ (not a reference query) does not open an empty menu.
    if (nextMention?.query && /[\u4e00-\u9fff]/.test(nextMention.query) && !mentionItems.some(item => [item.label, item.alias, item.name].some(text => String(text || '').toLowerCase().includes(nextMention.query)))) nextMention = null
    // A repeated select event for the same query keeps the highlighted option.
    if (nextMention && mention && nextMention.start === mention.start && nextMention.query === mention.query) return
    setMention(nextMention)
    setActiveIndex(0)
  }

  const updateMenuPosition = () => {
    const textarea = textareaRef.current
    if (!textarea || !mention) return
    const caret = caretViewportPosition(textarea)
    const estimatedHeight = Math.min(MENU_MAX_HEIGHT, Math.max(54, filteredItems.length * 52 + 8))
    const below = caret.top + caret.lineHeight + 6
    const top = below + estimatedHeight <= window.innerHeight - 8
      ? below
      : Math.max(8, caret.top - estimatedHeight - 6)
    setMenuPosition({
      left: Math.max(8, Math.min(caret.left, window.innerWidth - MENU_WIDTH - 8)),
      top,
    })
  }

  useLayoutEffect(() => {
    if (!mention) return undefined
    updateMenuPosition()
    window.addEventListener('resize', updateMenuPosition)
    window.addEventListener('scroll', updateMenuPosition, true)
    return () => {
      window.removeEventListener('resize', updateMenuPosition)
      window.removeEventListener('scroll', updateMenuPosition, true)
    }
  }, [mention, filteredItems.length])

  const selectItem = item => {
    if (!mention || onMentionSelect?.(item)===false) return
    const inserted = insertPromptMention(value, mention, item.token)
    onValueChange(inserted.value)
    setMention(null)
    requestAnimationFrame(() => {
      textareaRef.current?.focus()
      textareaRef.current?.setSelectionRange(inserted.cursor, inserted.cursor)
    })
  }

  const handleChange = event => {
    onChange?.(event)
    onValueChange(event.target.value)
    updateMention(event.target.value, event.target.selectionStart)
  }

  const isComposing = event => composing.current || event.nativeEvent?.isComposing || event.key === 'Process'
  // V140 #17: after clicks, Ctrl+arrows, ↑/↓ etc. a caret inside a reference snaps to its nearest boundary.
  const snapCaret = textarea => {
    if (!textarea) return
    const next = snapSelection(textarea.value, textarea.selectionStart, textarea.selectionEnd)
    if (next.start !== textarea.selectionStart || next.end !== textarea.selectionEnd) textarea.setSelectionRange(next.start, next.end, textarea.selectionDirection)
  }
  const handleKeyDown = event => {
    if (!isComposing(event) && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const textarea = event.currentTarget, range = referenceDeletionRange(textarea.value, textarea.selectionStart, textarea.selectionEnd, event.key)
      // Select the whole reference and let the browser delete it natively (native undo keeps working).
      if (range) textarea.setSelectionRange(range.start, range.end, event.key === 'Backspace' ? 'backward' : 'forward')
      // ←/→ jump over a whole reference; Shift+←/→ extend over it. Selection only, the text is unchanged.
      const jump = arrowSelection(textarea.value, textarea.selectionStart, textarea.selectionEnd, textarea.selectionDirection, event.key, event.shiftKey)
      if (jump) { event.preventDefault(); textarea.setSelectionRange(jump.start, jump.end, jump.direction) }
    }
    if (mention) {
      if (event.key === 'Escape') {
        dismissedMention.current=`${event.currentTarget.value}\u0000${event.currentTarget.selectionStart}`
        event.preventDefault()
        event.stopPropagation()
        setMention(null)
        return
      }
      if (filteredItems.length && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
        event.preventDefault()
        const direction = event.key === 'ArrowDown' ? 1 : -1
        setActiveIndex(index => (index + direction + filteredItems.length) % filteredItems.length)
        return
      }
      if (filteredItems.length && ['Enter', 'Tab'].includes(event.key)) {
        event.preventDefault()
        selectItem(filteredItems[activeIndex] || filteredItems[0])
        return
      }
    }
    onKeyDown?.(event)
  }

  const menu = mention && ReactDOM.createPortal(
    <div
      id={menuId}
      role="listbox"
      aria-label="参考素材"
      data-testid="prompt-mention-menu"
      className={`prompt-mention-menu ${menuClassName}`}
      style={{ left: menuPosition.left, top: menuPosition.top, width: MENU_WIDTH }}
    >
      {filteredItems.length ? filteredItems.map((item, index) => (
        <button
          key={item.id || item.token}
          type="button"
          role="option"
          aria-selected={index === activeIndex}
          className="prompt-mention-option"
          onMouseEnter={() => setActiveIndex(index)}
          onMouseDown={event => {
            event.preventDefault()
            selectItem(item)
          }}
        >
          <span className={`prompt-mention-thumbnail prompt-mention-thumbnail-${item.type}`}>
            <MentionThumbnail item={item} />
          </span>
          <span className="min-w-0 flex-1 text-left">
            <span className="block font-mono text-xs font-semibold text-nexus-text-light">{item.label}</span>
            <span className="block truncate text-xs text-nexus-muted">{item.name || item.label}</span>
          </span>
          <span className="font-mono text-xs text-nexus-green">{item.token}</span>
        </button>
      )) : (
        <div className="px-3 py-4 text-center text-xs text-nexus-muted">
          {mentionItems.length ? '没有匹配的参考素材' : '暂无参考素材'}
        </div>
      )}
    </div>,
    document.body,
  )

  return (
    <div className={wrapperClassName} style={{ position: 'relative' }}>
      <textarea
        {...textareaProps}
        ref={textareaRef}
        value={value}
        className={className}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onClick={event => { if (!composing.current && event.detail < 2) snapCaret(event.currentTarget); updateMention(event.currentTarget.value, event.currentTarget.selectionStart); peekAtCaret(event.currentTarget) }}
        onSelect={event => {
          if (document.activeElement === event.currentTarget) {
            updateMention(event.currentTarget.value, event.currentTarget.selectionStart)
          }
        }}
        onScroll={() => { updateMenuPosition(); setPeek(null) }}
        onBlur={() => { setMention(null); setPeek(null) }}
        onKeyUp={event => { if (!isComposing(event) && !event.shiftKey && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(event.key)) snapCaret(event.currentTarget); peekAtCaret(event.currentTarget) }}
        onMouseUp={event => { const textarea = event.currentTarget; if (!composing.current) requestAnimationFrame(() => { if (document.activeElement === textarea && event.detail < 2) snapCaret(textarea) }) }}
        onDoubleClick={event => { const textarea = event.currentTarget, range = referenceAt(textarea.value, textarea.selectionStart, textarea.selectionEnd); if (range) textarea.setSelectionRange(range.start, range.end, 'forward') }}
        onCompositionStart={() => { composing.current = true }}
        onCompositionEnd={() => { composing.current = false }}
        onMouseMove={event => {
          const textarea = event.currentTarget, x = event.clientX, y = event.clientY
          cancelAnimationFrame(peekFrame.current)
          peekFrame.current = requestAnimationFrame(() => {
            const hit = tokenAtPoint(textarea, referenceTokenRanges(textarea.value), x, y)
            showPeek(hit?.range, hit && { left: hit.box.left, top: hit.box.bottom + 6 }, 'pointer')
          })
        }}
        onMouseLeave={() => { cancelAnimationFrame(peekFrame.current); showPeek(null, null, 'pointer') }}
        aria-describedby={[textareaProps['aria-describedby'], peek && !mention ? peekId : null].filter(Boolean).join(' ') || undefined}
        aria-autocomplete="list"
        aria-controls={mention ? menuId : undefined}
        aria-expanded={Boolean(mention)}
      />
      <ReferenceHighlight textareaRef={textareaRef} value={String(value || '')} tokenState={referenceTokenState || (token => itemsByToken.has(token) ? 'valid' : 'invalid')} />
      {menu}
      {peek && !mention && ReactDOM.createPortal(
        <div id={peekId} role="tooltip" data-testid="prompt-reference-preview" className={`prompt-mention-menu prompt-reference-preview ${menuClassName}`} style={{ left: peek.left, top: peek.top, width: 240 }}>
          {peek.item ? <div className="prompt-mention-option">
            <span className={`prompt-mention-thumbnail prompt-mention-thumbnail-${peek.item.type}`}><MentionThumbnail item={peek.item} /></span>
            <span className="min-w-0 flex-1 text-left"><span className="block font-mono text-xs font-semibold text-nexus-text-light">{peek.token}</span><span className="block truncate text-xs text-nexus-muted" title={peek.item.name}>{peek.item.name || peek.item.label}</span></span>
          </div> : <div className="px-3 py-2 text-xs text-nexus-muted">{peek.token}：没有对应的参考素材</div>}
        </div>,
        document.body,
      )}
    </div>
  )
}
