// CANVAS-LAYOUT-2-20261118: pure helpers for the canvas chrome (left icon rail, "本画布任务" panel,
// selected-node toolbar, bottom-left minimap). No React, no DOM: unit tested in client/tests/canvasChrome.test.js.
// Interface preferences only (pinned panel, minimap switch) live in localStorage, always behind try/catch.
import {nodeGeometry} from './canvasGeometry.js'
import {isGeneratingTaskStatus} from '../../lib/taskStatus.js'

// ---- Left rail -------------------------------------------------------------------------------------------
// `kind: 'panel'` opens a pop-out panel; `kind: 'action'` runs a callback (角色卡 opens the existing dialog).
export const RAIL_ITEMS = Object.freeze([
  {id: 'project', label: '项目/画布', kind: 'panel'},
  {id: 'assets', label: '素材库', kind: 'panel'},
  {id: 'characters', label: '角色卡', kind: 'action'},
  {id: 'prompts', label: '提示词库', kind: 'panel'},
  {id: 'tasks', label: '本画布任务', kind: 'panel'},
])
export const RAIL_PANEL_IDS = Object.freeze(RAIL_ITEMS.filter(item => item.kind === 'panel').map(item => item.id))
export const RAIL_WIDTH = 48
export const RAIL_PANEL_MIN = 240
export const RAIL_PANEL_MAX = 360
export const RAIL_PANEL_DEFAULT = 280
export const RAIL_STORAGE_KEY = 'ink-traces.canvas.rail.v1'
export const MINIMAP_STORAGE_KEY = 'ink-traces.canvas.minimap.v1'

// Spec 1.5: default pinned/floating width per viewport (264 below 1440, 280 at 1440, 320 from 1920).
export function railPanelDefaultWidth(viewportWidth) {
  const w = Number(viewportWidth) || 0
  return w >= 1920 ? 320 : w >= 1440 ? 280 : 264
}
// Spec 1.5: pinning must leave the canvas at least 640 wide (after the right panel was pressed to 288).
export const PIN_MIN_CANVAS = 640
export const RIGHT_PANEL_MIN = 288
export function pinnedCanvasWidth({viewport, panel, rightPanel = RIGHT_PANEL_MIN}) {
  return Number(viewport) - RAIL_WIDTH - Number(panel) - Number(rightPanel)
}
export const PIN_REFUSED_MESSAGE = '窗口较窄，弹出面板以浮层显示'
export function pinAllowed(layout) { return pinnedCanvasWidth(layout) >= PIN_MIN_CANVAS }

const storageOf = storage => {
  if (storage !== undefined) return storage
  try { return globalThis.localStorage || null } catch { return null }
}

// Default (spec Q6, user 11-17): not pinned. An unpinned (floating) panel is never restored after a reload.
export function readRailPreference(storage) {
  const fallback = {panel: null, pinned: false}
  try {
    const raw = storageOf(storage)?.getItem(RAIL_STORAGE_KEY)
    if (!raw) return fallback
    const value = JSON.parse(raw)
    const pinned = value?.pinned === true && RAIL_PANEL_IDS.includes(value?.panel)
    return pinned ? {panel: value.panel, pinned: true} : fallback
  } catch { return fallback }
}
export function writeRailPreference({panel, pinned}, storage) {
  try { storageOf(storage)?.setItem(RAIL_STORAGE_KEY, JSON.stringify({panel: RAIL_PANEL_IDS.includes(panel) ? panel : null, pinned: !!pinned})) } catch { /* preference only */ }
}

// Default: on when the canvas surface is at least 1000px wide, unless the user switched it.
export function readMinimapPreference(canvasWidth, storage) {
  try {
    const raw = storageOf(storage)?.getItem(MINIMAP_STORAGE_KEY)
    if (raw === '1') return true
    if (raw === '0') return false
  } catch { /* fall through to the default */ }
  return Number(canvasWidth) >= 1000
}
export function writeMinimapPreference(open, storage) {
  try { storageOf(storage)?.setItem(MINIMAP_STORAGE_KEY, open ? '1' : '0') } catch { /* preference only */ }
}

// Next focus index for the vertical toolbar (Up/Down wrap, Home/End jump). Returns null for other keys.
export function railFocusIndex(index, count, key) {
  if (!count) return null
  if (key === 'ArrowDown') return (index + 1) % count
  if (key === 'ArrowUp') return (index - 1 + count) % count
  if (key === 'Home') return 0
  if (key === 'End') return count - 1
  return null
}

// ---- "本画布任务" panel ------------------------------------------------------------------------------------
const NODE_LABELS = {image: '图像', video: '视频', audio: '音频'}
export const TASK_GROUPS = Object.freeze([
  {id: 'active', label: '进行中'},
  {id: 'problem', label: '失败与结果未知'},
  {id: 'done', label: '最近完成'},
])
export const RECENT_DONE_LIMIT = 20

// Only the current document: each generation node's `task` (id/status/error) plus the runtime
// `resultUnknown` flag. No server request; the panel re-renders from the document.
export function summarizeCanvasTasks(nodes = [], {recentLimit = RECENT_DONE_LIMIT} = {}) {
  const groups = {active: [], problem: [], done: []}
  for (const node of nodes || []) {
    const task = node?.task
    if (!task || !NODE_LABELS[node.type]) continue
    const unknown = task.status === 'unknown' || task.resultUnknown === true
    const group = unknown || task.status === 'failed' ? 'problem'
      : isGeneratingTaskStatus(task.status) ? 'active'
      : task.status === 'succeeded' || task.status === 'cancelled' ? 'done' : null
    if (!group) continue
    const id = Number(task.id)
    groups[group].push({
      nodeId: node.id,
      title: String(node.title || '').trim() || `${NODE_LABELS[node.type]}节点`,
      mode: node.type,
      taskId: Number.isInteger(id) && id > 0 ? id : null,
      status: unknown ? 'unknown' : task.status,
      error: task.error || null,
    })
  }
  // Newer tasks have larger ids; tasks still without an id (submitting) come first.
  const newest = (a, b) => (b.taskId ?? Infinity) - (a.taskId ?? Infinity)
  for (const key of Object.keys(groups)) groups[key].sort(newest)
  groups.done = groups.done.slice(0, recentLimit)
  return groups
}

// ---- Selected node toolbar --------------------------------------------------------------------------------
// User decision 11-17 (Q5): image asset nodes AND image generation nodes with an image result get the full
// image tool set; results are saved as new library assets (handled by the caller).
// NODE-TOOLBAR-VERSIONS-20261118 (user 11-18): video generation nodes with a video result get their own set
// (版本切换、截取当前帧/尾帧、预览、下载、更多). Audio/text: none. 历史版本 is always listed when its handler is
// supplied and is disabled (with the reason) while the node keeps only one version.
export const NODE_TOOLBAR_ACTIONS = Object.freeze([
  {id: 'edit', label: '编辑', title: '编辑（裁剪/涂抹），另存为新素材', handler: 'onEdit'},
  {id: 'rotate', label: '旋转', title: '旋转 90°，另存为新素材', handler: 'onRotate'},
  {id: 'annotate', label: '标注', title: '标注，另存为新素材', handler: 'onAnnotate'},
  {id: 'layer', label: '在图层中分解', title: '在图层中分解（切换到图层工作台载入此图）', handler: 'onDecomposeLayer'},
  {id: 'download', label: '下载', title: '下载图片', handler: 'onDownload'},
  {id: 'preview', label: '预览', title: '预览', handler: 'onPreview'},
  {id: 'history', label: '历史版本', title: '历史版本', handler: 'onHistory'},
  {id: 'more', label: '更多', title: '更多操作', handler: 'onMore'},
])
export const VIDEO_ASSET_TOOLBAR_ACTIONS = Object.freeze([
  {id: 'splitVideo', label: '视频分割', title: '按时间轴或时长分割视频素材', handler: 'onSplitVideo'},
  {id: 'download', label: '下载', title: '下载视频', handler: 'onDownload'},
  {id: 'preview', label: '预览', title: '预览', handler: 'onPreview'},
  {id: 'history', label: '历史版本', title: '历史版本', handler: 'onHistory'},
  {id: 'more', label: '更多', title: '更多操作', handler: 'onMore'},
])
export const VIDEO_TOOLBAR_ACTIONS = Object.freeze([
  {id: 'history', label: '历史版本', title: '历史版本', handler: 'onHistory'},
  {id: 'extendVideo', label: '延长此视频', title: '创建已连线的下游视频延长节点（不自动生成）', handler: 'onExtendVideo'},
  {id: 'editVideo', label: '编辑此视频', title: '创建已连线的下游视频编辑节点（不自动生成）', handler: 'onEditVideo'},
  {id: 'captureCurrent', label: '截取当前帧', title: '截取播放器当前帧，存为右侧的图片素材节点', handler: 'onCaptureCurrent'},
  {id: 'captureTail', label: '截取尾帧', title: '截取视频最后一帧，存为右侧的图片素材节点', handler: 'onCaptureTail'},
  {id: 'preview', label: '预览', title: '预览', handler: 'onPreview'},
  {id: 'download', label: '下载', title: '下载视频', handler: 'onDownload'},
  {id: 'more', label: '更多', title: '更多操作', handler: 'onMore'},
])
export const AUDIO_TOOLBAR_ACTIONS = Object.freeze([
  {id: 'preview', label: '播放预览', title: '播放／预览音频', handler: 'onPreview'},
  {id: 'download', label: '下载', title: '下载音频', handler: 'onDownload'},
  {id: 'history', label: '历史版本', title: '历史版本', handler: 'onHistory'},
  {id: 'more', label: '更多', title: '更多操作', handler: 'onMore'},
])
export const SINGLE_VERSION_REASON = '只有 1 个版本，暂无可切换的历史版本'

export function nodeHasImage(node) {
  if (!node) return false
  if (node.type === 'asset') return node.asset?.kind === 'image' && !!node.asset?.url
  return node.type === 'image' && !!node.asset?.url && (node.asset.kind == null || node.asset.kind === 'image')
}

export function nodeHasVideoAsset(node) {
  return node?.type === 'asset' && node.asset?.kind === 'video' && !!node.asset?.url
}

export function nodeHasAudio(node) {
  if (!node) return false
  if (node.type === 'asset') return node.asset?.kind === 'audio' && !!node.asset?.url
  return node.type === 'audio' && !!node.asset?.url && (node.asset.kind == null || node.asset.kind === 'audio')
}

// 'image' | 'videoAsset' | 'video' | 'audio' | null: which toolbar the node gets.
export function nodeToolbarKind(node) {
  if (nodeHasImage(node)) return 'image'
  if (nodeHasVideoAsset(node)) return 'videoAsset'
  if (node?.type === 'video' && node.asset?.url && (node.asset.kind == null || node.asset.kind === 'video')) return 'video'
  if (nodeHasAudio(node)) return 'audio'
  return null
}

// Hidden for multi-select, drag, connection, annotation or a deleted library item.
export function nodeToolbarVisible({node, selectedCount = 1, dragging = false, connecting = false, annotating = false, deleted = false} = {}) {
  return selectedCount === 1 && !dragging && !connecting && !annotating && !deleted && !!nodeToolbarKind(node)
}

// Actions shown for the handlers the caller supplies; `history` is disabled (with a reason) for a single version.
export function nodeToolbarActions(node, handlers = {}) {
  const kind = nodeToolbarKind(node)
  const list = kind === 'videoAsset'
    ? VIDEO_ASSET_TOOLBAR_ACTIONS
    : kind === 'video'
      ? VIDEO_TOOLBAR_ACTIONS
      : kind === 'audio'
        ? AUDIO_TOOLBAR_ACTIONS
        : NODE_TOOLBAR_ACTIONS
  return list.filter(action => typeof handlers[action.handler] === 'function').map(action => {
    if (action.id !== 'history' || (node?.candidates?.length || 0) > 1) return action
    return {...action, disabled: true, reason: SINGLE_VERSION_REASON, title: `历史版本（${SINGLE_VERSION_REASON}）`}
  })
}

export function nodeScreenRect(node, view, geometry = nodeGeometry) {
  const size = geometry(node), zoom = view?.zoom || 1
  return {left: node.x * zoom + (view?.x || 0), top: node.y * zoom + (view?.y || 0), width: size.width * zoom, height: size.height * zoom}
}

// Screen rect of a node group's header bar (accounting for the CSS counter-scale below 100% zoom,
// which uses transform-origin: left bottom so the header grows upwards from bounds.y + headerHeight).
export function groupHeaderScreenRect(bounds, view, {headerHeight = 40, headerWidth = 0} = {}) {
  if (!bounds) return null
  const zoom = view?.zoom || 1
  const scale = Math.min(5, Math.max(1, 1 / zoom))
  const bottom = (bounds.y + headerHeight) * zoom + (view?.y || 0)
  const height = headerHeight * scale * zoom
  const left = bounds.x * zoom + (view?.x || 0)
  const width = Math.max(bounds.width * zoom, headerWidth * scale * zoom)
  return {left, top: bottom - height, width, height}
}

// Centered 8px above the node, clamped inside the surface. Not enough room above: stick to the top edge
// (never flip below, which would cover the in-card prompt). Node fully outside the surface: null (hide).
// P1-CANVAS-WORKFLOW-20261120 (P1-1): when `avoid` rects (e.g. node-group header bars) overlap the default
// position, lift the toolbar clear above the header; if the header itself sits at the very top of the
// surface with no space above, drop just below the header so group title and buttons remain unobstructed.
export function nodeToolbarPlacement(rect, surface, toolbar, {gap = 8, margin = 8, avoid = []} = {}) {
  if (!rect || !surface) return null
  if (rect.left + rect.width < 0 || rect.left > surface.width || rect.top + rect.height < 0 || rect.top > surface.height) return null
  const width = toolbar?.width || 0, height = toolbar?.height || 0
  const left = Math.max(margin, Math.min(surface.width - width - margin, rect.left + rect.width / 2 - width / 2))
  let top = Math.max(margin, rect.top - gap - height)
  const overlaps = box => box && left < box.left + box.width && left + width > box.left && top < box.top + box.height && top + height > box.top
  for (const box of avoid || []) {
    if (!overlaps(box)) continue
    if (box.top - gap - height >= margin) {
      top = box.top - gap - height
    } else if (box.top - height >= margin) {
      top = margin
    } else {
      top = Math.min(surface.height - height - margin, box.top + box.height + 4)
    }
  }
  return {left: Math.round(left), top: Math.round(top)}
}

// ---- Minimap ------------------------------------------------------------------------------------------------
export function minimapSize(viewportWidth) {
  return Number(viewportWidth) >= 1920 ? {width: 200, height: 124} : {width: 160, height: 100}
}

// The visible world rectangle of the surface. Screen = world * zoom + view offset.
export function viewportWorldRect(view, surface) {
  const zoom = view?.zoom || 1
  return {x: -(view?.x || 0) / zoom, y: -(view?.y || 0) / zoom, width: (surface?.width || 0) / zoom, height: (surface?.height || 0) / zoom}
}

// Fits the nodes and the current viewport into the minimap box (with padding), keeping the aspect ratio.
export function minimapTransform(nodes = [], view, surface, size, geometry = nodeGeometry, padding = 6) {
  const visible = viewportWorldRect(view, surface)
  let minX = visible.x, minY = visible.y, maxX = visible.x + visible.width, maxY = visible.y + visible.height
  for (const node of nodes || []) {
    const g = geometry(node)
    minX = Math.min(minX, node.x); minY = Math.min(minY, node.y)
    maxX = Math.max(maxX, node.x + g.width); maxY = Math.max(maxY, node.y + g.height)
  }
  const worldW = Math.max(1, maxX - minX), worldH = Math.max(1, maxY - minY)
  const innerW = Math.max(1, size.width - 2 * padding), innerH = Math.max(1, size.height - 2 * padding)
  const scale = Math.min(innerW / worldW, innerH / worldH)
  return {
    scale,
    offsetX: padding + (innerW - worldW * scale) / 2 - minX * scale,
    offsetY: padding + (innerH - worldH * scale) / 2 - minY * scale,
  }
}
export const worldToMinimap = (t, point) => ({x: point.x * t.scale + t.offsetX, y: point.y * t.scale + t.offsetY})
export const minimapToWorld = (t, point) => ({x: (point.x - t.offsetX) / t.scale, y: (point.y - t.offsetY) / t.scale})

// New view whose surface centre shows `world` (zoom unchanged).
export function viewCenteredOn(world, view, surface) {
  const zoom = view?.zoom || 1
  return {...view, zoom, x: surface.width / 2 - world.x * zoom, y: surface.height / 2 - world.y * zoom}
}

// Keyboard pan from the minimap: 10% of the visible area per arrow press.
export function viewPannedBy(view, surface, key) {
  const dx = {ArrowLeft: 1, ArrowRight: -1}[key] || 0, dy = {ArrowUp: 1, ArrowDown: -1}[key] || 0
  if (!dx && !dy) return null
  return {...view, x: (view?.x || 0) + dx * surface.width * .1, y: (view?.y || 0) + dy * surface.height * .1}
}

// Port colour token per media kind (CSS custom properties defined in canvasChrome.css).
export const PORT_TOKENS = Object.freeze({image: '--cv-port-image', video: '--cv-port-video', audio: '--cv-port-audio', prompt: '--cv-port-prompt'})
export const portToken = kind => PORT_TOKENS[kind] || null
