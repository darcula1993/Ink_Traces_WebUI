import React, { useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { AudioLines, Film, Image as ImageIcon } from 'lucide-react'

const MENU_WIDTH = 288
const MENU_MAX_HEIGHT = 280

export function findPromptMention(value, cursor) {
  const safeValue = String(value || '')
  const safeCursor = Math.max(0, Math.min(Number(cursor) || 0, safeValue.length))
  const atIndex = safeValue.lastIndexOf('@', safeCursor - 1)
  if (atIndex < 0) return null

  const candidate = safeValue.slice(atIndex, safeCursor)
  const match = candidate.match(/^@([a-zA-Z]*\d*)$/)
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
  mentionItems = [],
  wrapperClassName = '',
  className = '',
  onKeyDown,
  onChange,
  ...textareaProps
}) {
  const textareaRef = useRef(null)
  const menuId = useId()
  const [mention, setMention] = useState(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [menuPosition, setMenuPosition] = useState({ left: 8, top: 8 })

  const filteredItems = useMemo(() => {
    if (!mention?.query) return mentionItems
    return mentionItems.filter(item => (
      item.label.toLowerCase().includes(mention.query)
      || String(item.name || '').toLowerCase().includes(mention.query)
    ))
  }, [mention?.query, mentionItems])

  const updateMention = (nextValue, cursor) => {
    const nextMention = findPromptMention(nextValue, cursor)
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
    if (!mention) return
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

  const handleKeyDown = event => {
    if (mention) {
      if (event.key === 'Escape') {
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
      className="prompt-mention-menu"
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
            <span className="block truncate text-[10px] text-nexus-muted">{item.name || item.label}</span>
          </span>
          <span className="font-mono text-[10px] text-nexus-green">{item.token}</span>
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
    <div className={wrapperClassName}>
      <textarea
        {...textareaProps}
        ref={textareaRef}
        value={value}
        className={className}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onClick={event => updateMention(event.currentTarget.value, event.currentTarget.selectionStart)}
        onSelect={event => {
          if (document.activeElement === event.currentTarget) {
            updateMention(event.currentTarget.value, event.currentTarget.selectionStart)
          }
        }}
        onScroll={updateMenuPosition}
        onBlur={() => setMention(null)}
        aria-autocomplete="list"
        aria-controls={mention ? menuId : undefined}
        aria-expanded={Boolean(mention)}
      />
      {menu}
    </div>
  )
}
