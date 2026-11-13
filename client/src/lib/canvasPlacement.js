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
