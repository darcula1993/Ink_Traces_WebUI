// GEN-RESULT-LIFECYCLE-20261119: permanently deleting tasks (single, bulk, empty trash) also deletes their
// results in the library's “生成历史”; the server previews what goes and which canvases, groups and character
// cards reference it, and the confirm dialog lists it before anything is deleted. Pure helpers, node-testable.
import axios from 'axios'
import { MEDIA_STATUS_EVENT } from '../../lib/canvasMediaStatus.js'

export const PREVIEW_BATCH = 5000
const SKIP_LABELS = { cancel_requested: '取消中', leased: '执行中', not_in_trash: '不在回收站' }
const KIND_LABELS = { image: '图片', video: '视频', audio: '音频', layer: '图层' }

export function mergeTaskDeletePreviews(results) {
  const workflows = new Map(), groups = new Map(), characters = new Map()
  const merged = { tasks: 0, types_breakdown: {}, skipped: {}, missing_ids: [], media: { count: 0, kinds: { image: 0, video: 0, audio: 0 }, copies_kept: 0, affected_workflows: [], media_groups: [], characters: [] } }
  for (const result of results) {
    merged.tasks += Number(result?.tasks) || 0
    for (const [taskType, n] of Object.entries(result?.types_breakdown || {})) {
      const count = Number(n) || 0
      if (count > 0) merged.types_breakdown[taskType] = (merged.types_breakdown[taskType] || 0) + count
    }
    Object.assign(merged.skipped, result?.skipped || {})
    merged.missing_ids.push(...(result?.missing_ids || []))
    const media = result?.media || {}
    merged.media.count += Number(media.count) || 0
    merged.media.copies_kept += Number(media.copies_kept) || 0
    for (const kind of Object.keys(merged.media.kinds)) merged.media.kinds[kind] += Number(media.kinds?.[kind]) || 0
    for (const w of media.affected_workflows || []) {
      const prev = workflows.get(w.workflow_id)
      workflows.set(w.workflow_id, prev ? { ...prev, placeholder_nodes: (prev.placeholder_nodes || 0) + (w.placeholder_nodes || 0), stripped_nodes: (prev.stripped_nodes || 0) + (w.stripped_nodes || 0) } : { ...w })
    }
    for (const g of media.media_groups || []) groups.set(g.id, g)
    for (const c of media.characters || []) characters.set(c.id ?? c.name, c)
  }
  merged.media.affected_workflows = [...workflows.values()]
  merged.media.media_groups = [...groups.values()]
  merged.media.characters = [...characters.values()]
  return merged
}

export async function previewTaskDelete({ ids, type }) {
  if (type) return mergeTaskDeletePreviews([(await axios.post('/api/tasks/delete-preview', { type })).data])
  const results = []
  for (let offset = 0; offset < ids.length; offset += PREVIEW_BATCH) results.push((await axios.post('/api/tasks/delete-preview', { ids: ids.slice(offset, offset + PREVIEW_BATCH) })).data)
  return mergeTaskDeletePreviews(results)
}

// count/label: the empty-trash dialog states the server's trash count for its task type.
export function taskDeletePlanLines(preview, { count = preview.tasks, label = '', scope = '' } = {}) {
  const media = preview.media
  let headline
  if (scope === 'all') {
    const breakdown = Object.entries(preview.types_breakdown || {})
      .filter(([, n]) => Number(n) > 0)
      .map(([type, n]) => `${KIND_LABELS[type] || type} ${n}`)
    headline = breakdown.length
      ? `将彻底删除全部类型回收站中的 ${count} 个任务（${breakdown.join('、')}），不可恢复。`
      : `将彻底删除全部类型回收站中的 ${count} 个任务（覆盖图片、视频、音频、图层），不可恢复。`
  } else {
    headline = `将彻底删除 ${count} 个${label}任务，不可恢复。`
  }
  const lines = [headline]
  if (media.count) {
    const kinds = Object.entries(media.kinds || {}).filter(([, n]) => n > 0).map(([kind, n]) => `${KIND_LABELS[kind] || kind} ${n}`)
    lines.push(`同时删除这些任务在素材库“生成历史”中的 ${media.count} 个结果${kinds.length ? `（${kinds.join('、')}）` : ''}及其文件。`)
    const nodes = media.affected_workflows.reduce((n, w) => n + (w.placeholder_nodes || 0), 0), stripped = media.affected_workflows.reduce((n, w) => n + (w.stripped_nodes || 0), 0)
    lines.push(media.affected_workflows.length ? `涉及 ${media.affected_workflows.length} 个画布：${nodes} 个节点保留为“已删除”占位，${stripped} 个节点的参考、提及或组引用会移除这些结果。` : '没有画布引用这些结果。')
    if (media.media_groups.length) lines.push(`素材组 ${media.media_groups.map(g => `“${g.title}”`).join('、')} 中的这些成员保留为“已删除”占位。`)
    if (media.characters.length) lines.push(`角色卡 ${media.characters.map(c => c.name).join('、')} 中对应的角色卡图或参考音频会被移除（角色卡本身保留）。`)
  } else lines.push('这些任务在“生成历史”中没有需要删除的结果。')
  if (media.copies_kept) lines.push(`已复制到其他文件夹的 ${media.copies_kept} 项是独立素材，不受影响。`)
  const skipped = Object.values(preview.skipped || {})
  if (skipped.length) {
    const counts = {}
    for (const reason of skipped) counts[reason] = (counts[reason] || 0) + 1
    lines.push(`${skipped.length} 个任务将跳过（${Object.entries(counts).map(([r, n]) => `${SKIP_LABELS[r] || r} ${n}`).join('，')}）。`)
  }
  return lines
}

// Tell open canvases to re-check their “结果在回收站” / “已删除” placeholders.
export function announceMediaStatusChange() {
  try { globalThis.window?.dispatchEvent(new globalThis.Event(MEDIA_STATUS_EVENT)) } catch { /* no window in tests */ }
}
