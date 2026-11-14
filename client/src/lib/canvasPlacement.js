import {nodeGeometry} from '../components/canvas/canvasGeometry.js'
import {groupBounds} from './canvasGroups.js'

// V140 #5: a newly added node starts at the requested point and moves to the
// nearest free slot (right first, then the next rows) so it never lands on an
// existing node or node group. Existing nodes are never moved.
const GAP = 40
const intersects = (a, b) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y
export function occupiedRects(document) {
  const nodes = document?.nodes || []
  return [
    ...nodes.map(node => ({ x: node.x, y: node.y, ...nodeGeometry(node) })),
    ...(document?.groups || []).map(group => groupBounds(group, nodes)).filter(Boolean),
  ]
}
export function freeNodePosition(document, node, start, { gap = GAP, columns = 12, rows = 40 } = {}) {
  const size = nodeGeometry(node), rects = occupiedRects(document)
  const blocked = point => rects.some(rect => intersects({ x: point.x - gap / 2, y: point.y - gap / 2, width: size.width + gap, height: size.height + gap }, rect))
  if (!blocked(start)) return { x: start.x, y: start.y }
  const stepX = size.width + gap, stepY = size.height + gap
  for (let row = 0; row < rows; row++) for (let column = 0; column < columns; column++) {
    if (!row && !column) continue
    const point = { x: start.x + column * stepX, y: start.y + row * stepY }
    if (!blocked(point)) return point
  }
  return { x: start.x, y: start.y }
}

// FIX-B2-20261114 #3: a node added from the toolbar must land inside the visible area. Search free slots
// inside `visible` (world rect) nearest to `start`; when the visible area has no free slot, fall back to
// freeNodePosition (the caller then pans to the node).
export function freeNodePositionInView(document, node, start, visible, { gap = GAP, step = 40 } = {}) {
  const size = nodeGeometry(node), rects = occupiedRects(document)
  const blocked = point => rects.some(rect => intersects({ x: point.x - gap / 2, y: point.y - gap / 2, width: size.width + gap, height: size.height + gap }, rect))
  const inside = point => point.x >= visible.x && point.y >= visible.y && point.x + size.width <= visible.x + visible.width && point.y + size.height <= visible.y + visible.height
  if (!blocked(start) && inside(start)) return { x: start.x, y: start.y }
  const unit = Math.max(step, Math.min(size.width, size.height) / 4), candidates = []
  for (let y = visible.y; y + size.height <= visible.y + visible.height; y += unit)
    for (let x = visible.x; x + size.width <= visible.x + visible.width; x += unit) candidates.push({ x, y })
  if (candidates.length > 20000) return freeNodePosition(document, node, start)
  candidates.sort((a, b) => Math.hypot(a.x - start.x, a.y - start.y) - Math.hypot(b.x - start.x, b.y - start.y))
  const found = candidates.find(point => !blocked(point))
  return found ? { x: Math.round(found.x), y: Math.round(found.y) } : freeNodePosition(document, node, start)
}
