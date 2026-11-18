import React, { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { Trash2 } from 'lucide-react'
import ConfirmDialog from '../ui/ConfirmDialog'
import { taskTypeLabel } from './taskModel.js'

// EMPTY-TRASH-20261118: one-click "清空回收站" for the image/video/audio task center.
// The count comes from the server (all trashed tasks of this type, independent of the
// gallery's paging, search and filters); the server applies the permanent-delete rules.
const SKIP_LABELS = { cancel_requested: '取消中', leased: '执行中', not_in_trash: '已恢复' }

export function emptyTrashSummary(result) {
  const deleted = Number(result?.deleted) || 0
  const skipped = Number(result?.skipped) || 0
  if (!skipped) return `已彻底删除 ${deleted} 个任务`
  const reasons = Object.entries(result?.skipped_reasons || {})
    .filter(([, count]) => Number(count) > 0)
    .map(([reason, count]) => `${SKIP_LABELS[reason] || reason} ${count}`)
  return `已彻底删除 ${deleted} 个任务，跳过 ${skipped} 个${reasons.length ? `（${reasons.join('，')}）` : ''}`
}

export default function EmptyTrashButton({ mode, revision, onEmptied }) {
  const [count, setCount] = useState(null)
  const [countFailed, setCountFailed] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [notice, setNotice] = useState('')
  const noticeTimer = useRef(null)
  const typeLabel = taskTypeLabel(mode)

  const loadCount = useCallback(async signal => {
    const response = await axios.get('/api/tasks', { params: { type: mode, deleted: true, limit: 1 }, signal })
    const total = Number(response.data.total) || 0
    setCountFailed(false)
    setCount(total)
    return total
  }, [mode])

  useEffect(() => {
    const controller = new AbortController()
    loadCount(controller.signal).catch(() => { if (!controller.signal.aborted) { setCount(null); setCountFailed(true) } })
    return () => controller.abort()
  }, [loadCount, revision])

  useEffect(() => () => window.clearTimeout(noticeTimer.current), [])

  function showNotice(text) {
    window.clearTimeout(noticeTimer.current)
    setNotice(text)
    noticeTimer.current = window.setTimeout(() => setNotice(''), 8000)
  }

  async function open() {
    // Re-read the count so the dialog states the server's current number.
    try { if (await loadCount() > 0) setConfirming(true) } catch { showNotice('回收站数量读取失败，请重试') }
  }

  async function confirm() {
    const response = await axios.post('/api/tasks/trash/empty', { type: mode })
    setConfirming(false)
    showNotice(emptyTrashSummary(response.data))
    await onEmptied?.()
    loadCount().catch(() => {})
  }

  return (
    <>
      <button
        type="button"
        className="btn btn-danger btn-sm"
        disabled={!count}
        title={count === null ? (countFailed ? '回收站数量读取失败' : '正在读取回收站数量') : count ? `彻底删除回收站中的 ${count} 个${typeLabel}任务` : '回收站为空'}
        aria-label={count === null ? (countFailed ? '清空回收站（数量读取失败）' : '清空回收站（正在读取数量）') : count ? `清空回收站（${count} 个${typeLabel}任务）` : '清空回收站（回收站为空）'}
        data-testid="empty-trash-button"
        onClick={open}
      >
        <Trash2 size={13} aria-hidden="true" /> 清空回收站
      </button>
      <span role="status" aria-live="polite" className="text-xs text-nexus-text" data-testid="empty-trash-status">{notice}</span>
      {confirming && (
        <ConfirmDialog title="清空回收站" confirmLabel="彻底删除" danger onConfirm={confirm} onClose={() => setConfirming(false)}>
          将彻底删除 {count} 个{typeLabel}任务，不可恢复；素材库中的文件不受影响。
        </ConfirmDialog>
      )}
    </>
  )
}
