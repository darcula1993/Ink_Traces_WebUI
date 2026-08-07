import React, { useRef, useState } from 'react'
import { GripVertical } from 'lucide-react'

const REFERENCE_DRAG_TYPE = 'application/x-ink-traces-reference-order'

export function moveArrayItem(items, fromIndex, toIndex) {
  const source = Array.isArray(items) ? items : []
  if (
    fromIndex === toIndex
    || fromIndex < 0
    || toIndex < 0
    || fromIndex >= source.length
    || toIndex >= source.length
  ) return source

  const next = [...source]
  const [item] = next.splice(fromIndex, 1)
  next.splice(toIndex, 0, item)
  return next
}

function acceptsReferenceDrag(event) {
  return Array.from(event.dataTransfer?.types || []).includes(REFERENCE_DRAG_TYPE)
}

export default function SortableReferenceItem({
  children,
  className = '',
  index,
  itemCount,
  label = '参考素材',
  listId,
  onMove,
  testId,
}) {
  const itemRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const [dropTarget, setDropTarget] = useState(false)

  const handleDragStart = event => {
    event.stopPropagation()
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData(REFERENCE_DRAG_TYPE, JSON.stringify({ listId, index }))
    const bounds = itemRef.current?.getBoundingClientRect()
    if (itemRef.current && bounds) {
      const offsetX = Math.max(0, Math.min(bounds.width, event.clientX - bounds.left))
      const offsetY = Math.max(0, Math.min(bounds.height, event.clientY - bounds.top))
      event.dataTransfer.setDragImage(itemRef.current, offsetX, offsetY)
    }
    setDragging(true)
  }

  const handleDragOver = event => {
    if (!acceptsReferenceDrag(event)) return
    event.preventDefault()
    event.stopPropagation()
    event.dataTransfer.dropEffect = 'move'
    setDropTarget(true)
  }

  const handleDragLeave = event => {
    if (event.currentTarget.contains(event.relatedTarget)) return
    setDropTarget(false)
  }

  const handleDrop = event => {
    if (!acceptsReferenceDrag(event)) return
    event.preventDefault()
    event.stopPropagation()
    setDropTarget(false)
    try {
      const source = JSON.parse(event.dataTransfer.getData(REFERENCE_DRAG_TYPE))
      if (source.listId === listId) onMove?.(Number(source.index), index)
    } catch {
      // Ignore malformed drag payloads from outside this list.
    }
  }

  const handleKeyDown = event => {
    let destination = null
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') destination = index - 1
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') destination = index + 1
    if (destination === null || destination < 0 || destination >= itemCount) return
    event.preventDefault()
    event.stopPropagation()
    onMove?.(index, destination)
  }

  const state = dragging ? 'dragging' : dropTarget ? 'target' : 'idle'

  return (
    <div
      ref={itemRef}
      className={`reference-sortable-item ${className}`}
      data-reorder-state={state}
      data-testid={testId}
      onDragEnter={handleDragOver}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {children}
      <button
        type="button"
        draggable
        aria-label={`调整${label} ${index + 1} 顺序，当前第 ${index + 1} 位`}
        title="拖拽排序（方向键也可移动）"
        className="reference-sort-handle"
        onClick={event => event.stopPropagation()}
        onDragStart={handleDragStart}
        onDragEnd={() => { setDragging(false); setDropTarget(false) }}
        onKeyDown={handleKeyDown}
      >
        <GripVertical size={12} strokeWidth={2.2} />
      </button>
    </div>
  )
}
