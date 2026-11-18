// CANVAS-PORTS-UI-20261118: where the dynamic reference ports of a node sit (spec §4.2 item 6) and the texts
// built from deriveNodePorts. Pure: geometry is passed in, nothing reads or writes the document.
export const PORT_GAP = 20
export const PORT_GROUP_GAP = 8
export const PORT_TOP = 52 // below the 40px node head
export const PORT_BOTTOM = 12
const KIND = {image:'图片',video:'视频',audio:'音频'}
const NODE = {image:'图像',video:'视频',audio:'音频'}

function stack(sizes, geometry) {
  const height = sizes.reduce((sum,count,i) => sum + Math.max(0,count-1)*PORT_GAP + (i ? PORT_GAP+PORT_GROUP_GAP : 0), 0)
  // Few ports stay centred on the old single-port height; a stack that would leave the card starts at the top.
  let start = Math.max(PORT_TOP, geometry.portY - height/2)
  if (start + height > geometry.height - PORT_BOTTOM) start = PORT_TOP
  return {start,height}
}

/**
 * Port positions (node coordinates, y of the port centre).
 * expanded: node selected / hovered / under a connection drag. A stack taller than the card collapses to one
 * port per group when not expanded (edges then meet the group port); expanded stacks may run past the card.
 * Returns {collapsed, overflow, items:[{type:'port',port,y}|{type:'group',group,y}], edgeY:Map(edgeId→y)}.
 */
export function portLayout(derived, geometry, {expanded=false}={}) {
  const groups = (derived?.groups || []).filter(group => group.ports.length)
  const full = stack(groups.map(group => group.ports.length), geometry)
  const overflow = full.start + full.height > geometry.height - PORT_BOTTOM
  const collapsed = overflow && !expanded
  const items = [], edgeY = new Map()
  if (collapsed) {
    const {start} = stack(groups.map(() => 1), geometry)
    groups.forEach((group,i) => {
      const y = start + i*(PORT_GAP+PORT_GROUP_GAP)
      // A group with nothing connected keeps its single empty port; occupied groups fold to one group port.
      if (!group.count) { items.push({type:'port',port:group.ports[0],y}); return }
      items.push({type:'group',group,y})
      for (const port of group.ports) if (port.edgeId) edgeY.set(port.edgeId,y)
    })
  } else {
    let y = full.start
    groups.forEach((group,g) => {
      if (g) y += PORT_GROUP_GAP + PORT_GAP
      group.ports.forEach((port,i) => {
        if (i) y += PORT_GAP
        items.push({type:'port',port,y})
        if (port.edgeId) edgeY.set(port.edgeId,y)
      })
    })
  }
  return {collapsed,overflow,items,edgeY}
}

// "当前模型最多 N 个图片参考，已接入 M 个" per over-limit group (spec §4.2 换模型后超限).
export function overLimitMessages(derived) {
  return (derived?.groups || []).filter(group => group.overLimit).map(group => {
    if (!group.limit) return group.ports.find(port => port.overLimit)?.reason || `当前设置不接受${KIND[group.kind]}参考`
    const reason = group.ports.find(port => port.overLimit)?.reason || ''
    return reason.startsWith('首尾帧') ? `首尾帧最多两张图片，已接入 ${group.count} 张` : `当前模型最多 ${group.limit} 个${KIND[group.kind]}参考，已接入 ${group.count} 个`
  })
}

export function overLimitBlock(derived) {
  const messages = overLimitMessages(derived)
  return messages.length ? `参考超出上限：${messages.join('；')}。可在参考分区移除超出的参考` : ''
}

export function portAriaLabel(node, port) {
  const owner = `${NODE[node.type] || ''}节点 ${node.title || ''}`
  const over = port.overLimit ? `，${port.reason || '超出上限'}` : ''
  if (port.source === 'empty') return `${owner}：${port.label}（空口）`
  if (port.source === 'pending') return `${owner}：待生成${KIND[port.kind]}参考（${port.name || '上游节点'}，来自连线，计入上限）${over}`
  return `${owner}：${port.label}（已接入 ${port.name || '素材'}，${port.source === 'edge' ? '来自连线' : '来自素材库'}）${over}`
}

export function groupAriaLabel(node, group) {
  return `${NODE[node.type] || ''}节点 ${node.title || ''}：${KIND[group.kind]}参考组，共 ${group.count} 个，按 Enter 展开`
}

// Screen-reader text while a connection is dragged over / aimed at a node: "可接入：图片参考，剩余 N 个".
export function portDropAnnouncement(derived, kind) {
  const group = derived?.groups?.find(item => item.kind === kind)
  if (!group) return ''
  return group.limit == null ? `可接入：${KIND[kind]}参考（${'请先选择接口以确定参考上限'}）` : `可接入：${KIND[kind]}参考，剩余 ${Math.max(0,group.limit-group.count)} 个`
}
