import React, { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, Check, CheckSquare, Plus, Trash2, X } from 'lucide-react'
import { previewBulkDeleteProjects } from '../../lib/canvasApi'
import { localDate } from '../../lib/localDate'
import BrandMark from '../ui/BrandMark'
import { ProjectCardCornerArt, ProjectEmptyArt } from '../art/ShellEmptyArt'
import './projectOverview.css'

export function projectCardMeta(project) {
  const workflowCount = project?.workflow_count
  const countLabel = Number.isFinite(Number(workflowCount)) && workflowCount !== null && workflowCount !== ''
    ? `${Number(workflowCount)} 个画布`
    : ''
  const updatedDate = localDate(project?.updated_at || project?.created_at)
  const dateLabel = updatedDate ? `更新于 ${updatedDate}` : ''
  return { countLabel, dateLabel }
}

// P0-7: prefer the server's specific reason (e.g. active group run) when active_task_count is 0.
export function blockedPreviewLabel(item) {
  if (item?.has_active_tasks && Number(item.active_task_count) > 0) {
    return `存在活动任务（${item.active_task_count}），将跳过`
  }
  if (item?.reason) {
    return `${item.reason}，将跳过`
  }
  return item?.has_active_tasks ? '存在活动任务，将跳过' : '无法删除，将跳过'
}

// Navigation stays in the studio: its save/operation guards own every project switch.
export default function ProjectOverview({
  projects,
  currentProjectId,
  disabled,
  onClose,
  onSelect,
  onCreate,
  onBulkDelete,
  navigationError = '',
}) {
  const ref = useRef(null)
  const confirmRef = useRef(null)
  const bulkDeleteBtnRef = useRef(null)
  const operation = useRef(false)
  const previewSeq = useRef(0)

  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [preview, setPreview] = useState(null)
  const [cleanupAssets, setCleanupAssets] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [summary, setSummary] = useState(null)

  const locked = busy || disabled || deleting

  useEffect(() => {
    const previous = document.activeElement
    const protectBackground = event => {
      if (['historyUndo', 'historyRedo'].includes(event.inputType) && !ref.current?.contains(event.target)) {
        event.preventDefault()
      }
    }
    document.addEventListener('beforeinput', protectBackground, true)
    ref.current?.focus({ preventScroll: true })
    return () => {
      document.removeEventListener('beforeinput', protectBackground, true)
      if (previous?.isConnected) previous.focus({ preventScroll: true })
    }
  }, [])

  useEffect(() => {
    const live = new Set(projects.map(item => item.id))
    setSelectedIds(prev => {
      if (!prev.size) return prev
      const next = new Set([...prev].filter(id => live.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [projects])

  useEffect(() => {
    if (!confirmOpen) return
    const frame = requestAnimationFrame(() => confirmRef.current?.focus({ preventScroll: true }))
    return () => cancelAnimationFrame(frame)
  }, [confirmOpen])

  const sorted = [...projects].sort((a, b) =>
    String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')),
  )
  const items = sorted.filter(item => item.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  const allVisibleSelected = items.length > 0 && items.every(item => selectedIds.has(item.id))

  async function navigate(fn) {
    if (locked || operation.current) return
    operation.current = true
    ref.current?.focus({ preventScroll: true })
    setBusy(true)
    setError('')
    try {
      const result = await fn()
      if (result === false) {
        setError('未能切换项目，请先处理画布中的保存错误后重试。')
        return
      }
      onClose()
    } catch (failure) {
      setError(failure.message || '操作失败，请重试')
    } finally {
      operation.current = false
      setBusy(false)
    }
  }

  function toggleSelectMode() {
    if (locked) return
    setError('')
    setSelectMode(current => {
      if (current) setSelectedIds(new Set())
      return !current
    })
  }

  function toggleProject(id) {
    if (locked) return
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAllVisible() {
    if (locked || !items.length) return
    setSelectedIds(prev => {
      const next = new Set(prev)
      for (const item of items) next.add(item.id)
      return next
    })
  }

  function clearSelection() {
    if (locked) return
    setSelectedIds(new Set())
  }

  async function openDeleteConfirm() {
    if (locked || !selectedIds.size || !onBulkDelete) return
    const orderedIds = sorted.filter(p => selectedIds.has(p.id)).map(p => p.id)
    for (const id of selectedIds) {
      if (!orderedIds.includes(id)) orderedIds.push(id)
    }
    const seq = ++previewSeq.current
    setCleanupAssets(false)
    setDeleteError('')
    setPreview({ loading: true, items: [], error: '' })
    setConfirmOpen(true)
    try {
      const result = await previewBulkDeleteProjects(orderedIds)
      if (previewSeq.current !== seq) return
      setPreview({ loading: false, items: result.projects || [], error: '' })
    } catch (failure) {
      if (previewSeq.current !== seq) return
      setPreview({
        loading: false,
        items: [],
        error: failure?.response?.data?.error || failure?.message || '检查所选项目失败，请重试',
      })
    }
  }

  function closeDeleteConfirm() {
    if (deleting) return
    previewSeq.current += 1
    setConfirmOpen(false)
    setPreview(null)
    setDeleteError('')
    requestAnimationFrame(() => {
      if (bulkDeleteBtnRef.current?.isConnected && !bulkDeleteBtnRef.current.disabled) {
        bulkDeleteBtnRef.current.focus({ preventScroll: true })
      } else {
        ref.current?.focus({ preventScroll: true })
      }
    })
  }

  async function executeBulkDelete() {
    if (deleting || operation.current || !preview || preview.loading || preview.error || !onBulkDelete) return
    const ids = preview.items.map(item => item.id)
    if (!ids.length) return
    operation.current = true
    setDeleting(true)
    setDeleteError('')
    setError('')
    try {
      const result = await onBulkDelete(ids, cleanupAssets)
      const deleted = result?.deleted || []
      const skipped = result?.skipped || []
      setSummary({ deleted, skipped, cleanupAssets })
      setConfirmOpen(false)
      setPreview(null)
      setCleanupAssets(false)
      setSelectedIds(new Set())
      setSelectMode(false)
      requestAnimationFrame(() => ref.current?.focus({ preventScroll: true }))
    } catch (failure) {
      setDeleteError(failure?.response?.data?.error || failure?.message || '批量删除失败，请重试')
    } finally {
      operation.current = false
      setDeleting(false)
    }
  }

  const keys = event => {
    event.stopPropagation()
    const editable = ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName) || event.target.isContentEditable
    if (!editable && (event.ctrlKey || event.metaKey) && ['z', 'y', 'c', 'v', 'x'].includes(event.key.toLowerCase())) {
      event.preventDefault()
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') event.preventDefault()
    if (event.key === 'Escape') {
      event.preventDefault()
      if (!locked && !confirmOpen) onClose()
    }
    if (event.key === 'Tab') {
      const focusables = [...ref.current.querySelectorAll('button:not(:disabled),input:not(:disabled)')]
      if (!focusables.length) {
        event.preventDefault()
        ref.current.focus()
      } else if (event.shiftKey && [ref.current, focusables[0]].includes(document.activeElement)) {
        event.preventDefault()
        focusables.at(-1).focus()
      } else if (!event.shiftKey && [ref.current, focusables.at(-1)].includes(document.activeElement)) {
        event.preventDefault()
        focusables[0].focus()
      }
    }
  }

  const confirmKeys = event => {
    event.stopPropagation()
    if (event.key === 'Escape') {
      event.preventDefault()
      closeDeleteConfirm()
      return
    }
    if (event.key === 'Tab') {
      const focusables = [...confirmRef.current.querySelectorAll('button:not(:disabled),input:not(:disabled)')]
      if (!focusables.length) {
        event.preventDefault()
        confirmRef.current.focus()
      } else if (event.shiftKey && [confirmRef.current, focusables[0]].includes(document.activeElement)) {
        event.preventDefault()
        focusables.at(-1).focus()
      } else if (!event.shiftKey && [confirmRef.current, focusables.at(-1)].includes(document.activeElement)) {
        event.preventDefault()
        focusables[0].focus()
      }
    }
  }

  const previewItems = preview?.items || []
  const deletableCount = previewItems.filter(item => item.can_delete).length
  const blockedCount = previewItems.length - deletableCount

  return createPortal(
    <div className="cv-project-overview-backdrop">
      <section
        className="cv-project-overview"
        role="dialog"
        aria-modal="true"
        aria-label="全部项目"
        ref={ref}
        tabIndex={-1}
        onKeyDown={keys}
      >
        <header>
          <div>
            <p className="cv-project-brand-eyebrow">
              <span className="brand-mark brand-mark-sm">
                <BrandMark size={14} variant="compact" />
              </span>
              <span>Ink Traces</span>
            </p>
            <h1>全部项目</h1>
          </div>
          <button
            type="button"
            className="btn btn-icon btn-outlined btn-lg"
            aria-label="返回画布"
            title="返回画布"
            disabled={locked}
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>

        <div className="cv-project-overview-tools">
          <input
            aria-label="搜索项目"
            placeholder="搜索项目"
            value={query}
            disabled={locked}
            onChange={event => setQuery(event.target.value)}
          />
          {onBulkDelete && (
            <button
              type="button"
              className={`btn btn-secondary btn-lg${selectMode ? ' is-active' : ''}`}
              aria-pressed={selectMode}
              disabled={locked || (!selectMode && !projects.length)}
              onClick={toggleSelectMode}
            >
              <CheckSquare size={16} />
              {selectMode ? '退出多选' : '多选管理'}
            </button>
          )}
          <button type="button" className="btn btn-primary btn-lg" disabled={locked} onClick={() => navigate(onCreate)}>
            <Plus size={16} />
            创建新项目
          </button>
        </div>

        {selectMode && (
          <div className="cv-project-bulk-bar" role="toolbar" aria-label="批量管理操作">
            <span className="cv-project-bulk-count" aria-live="polite">
              已选 {selectedIds.size} 项
            </span>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={locked || !items.length || allVisibleSelected}
              onClick={selectAllVisible}
            >
              全选当前
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={locked || !selectedIds.size}
              onClick={clearSelection}
            >
              取消选择
            </button>
            <button
              ref={bulkDeleteBtnRef}
              type="button"
              className="btn btn-danger btn-sm cv-project-bulk-delete-btn"
              disabled={locked || !selectedIds.size}
              onClick={openDeleteConfirm}
            >
              <Trash2 size={14} />
              删除所选 ({selectedIds.size})
            </button>
          </div>
        )}

        {summary && (
          <div
            className={`cv-project-bulk-summary${summary.skipped.length ? ' has-skipped' : ''}`}
            role="status"
            data-testid="bulk-delete-summary"
          >
            <div className="cv-project-bulk-summary-head">
              <strong>
                {summary.deleted.length > 0 && summary.skipped.length > 0
                  ? `已删除 ${summary.deleted.length} 个项目，跳过 ${summary.skipped.length} 个`
                  : summary.deleted.length > 0
                    ? `已删除 ${summary.deleted.length} 个项目`
                    : `未删除项目，跳过 ${summary.skipped.length} 个`}
              </strong>
              {summary.cleanupAssets && summary.deleted.length > 0 && (
                <span className="cv-project-bulk-summary-note">全局素材库文件已保留</span>
              )}
              <button
                type="button"
                className="btn btn-icon btn-sm"
                aria-label="关闭结果摘要"
                title="关闭结果摘要"
                onClick={() => setSummary(null)}
              >
                <X size={14} />
              </button>
            </div>
            {summary.skipped.length > 0 && (
              <ul className="cv-project-bulk-skipped">
                {summary.skipped.map(item => (
                  <li key={item.id}>
                    <span>{item.title || item.id}</span>：{item.error || '已跳过'}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {error && <p role="alert">{navigationError || error}</p>}
        {busy && <p role="status">正在打开项目…</p>}

        <div className="cv-project-overview-grid">
          {items.map(project => {
            const { countLabel, dateLabel } = projectCardMeta(project)
            const metaLine = (countLabel || dateLabel) ? (
              <div className="cv-project-tile-meta">
                {countLabel && <span>{countLabel}</span>}
                {countLabel && dateLabel && <span className="cv-project-tile-meta-sep" aria-hidden="true">·</span>}
                {dateLabel && <span>{dateLabel}</span>}
              </div>
            ) : null
            if (!selectMode) {
              return (
                <button
                  key={project.id}
                  type="button"
                  data-project-id={project.id}
                  className="cv-project-tile"
                  disabled={locked}
                  aria-label={`打开项目 ${project.title}`}
                  aria-current={project.id === currentProjectId ? 'page' : undefined}
                  onClick={() => navigate(() => onSelect(project.id))}
                >
                  <ProjectCardCornerArt seed={project.id} />
                  <div className="cv-project-tile-top">
                    <strong>{project.title}</strong>
                    {metaLine}
                  </div>
                  <span className="cv-project-tile-status">
                    {project.id === currentProjectId ? (
                      <>
                        <Check size={16} />
                        当前项目
                      </>
                    ) : (
                      '打开项目'
                    )}
                  </span>
                </button>
              )
            }
            const isSelected = selectedIds.has(project.id)
            return (
              <button
                key={project.id}
                type="button"
                data-project-id={project.id}
                className={`cv-project-tile is-selectable${isSelected ? ' is-selected' : ''}`}
                disabled={locked}
                aria-pressed={isSelected}
                aria-label={`${isSelected ? '取消选择' : '选择'}项目 ${project.title}`}
                aria-current={project.id === currentProjectId ? 'page' : undefined}
                onClick={() => toggleProject(project.id)}
              >
                <ProjectCardCornerArt seed={project.id} />
                <div className="cv-project-tile-top">
                  <div className="cv-project-tile-head">
                    <span className={`cv-project-checkbox${isSelected ? ' is-checked' : ''}`} aria-hidden="true">
                      {isSelected && <Check size={13} strokeWidth={2.75} />}
                    </span>
                    <strong>{project.title}</strong>
                  </div>
                  {metaLine}
                </div>
                <span className="cv-project-tile-status">
                  {project.id === currentProjectId ? (
                    <>
                      <Check size={16} />
                      当前项目
                    </>
                  ) : isSelected ? (
                    '已选中'
                  ) : (
                    '点击选择'
                  )}
                </span>
              </button>
            )
          })}
        </div>

        {!items.length && (
          <div className="cv-project-empty-state" data-testid="project-overview-empty">
            <ProjectEmptyArt variant={query ? 'search' : 'empty'} />
            <p className="cv-project-empty">{query ? '未找到匹配的项目' : '还没有项目，创建一个项目开始创作。'}</p>
            {query ? (
              <button type="button" className="btn btn-secondary btn-sm" disabled={locked} onClick={() => setQuery('')}>
                清除搜索
              </button>
            ) : (
              <button type="button" className="btn btn-primary btn-sm" disabled={locked} onClick={() => navigate(onCreate)}>
                <Plus size={14} />
                创建新项目
              </button>
            )}
          </div>
        )}
      </section>

      {confirmOpen && (
        <div
          className="cv-project-bulk-confirm-backdrop"
          onPointerDown={event => {
            event.stopPropagation()
            if (event.target === event.currentTarget && !deleting) closeDeleteConfirm()
          }}
        >
          <section
            ref={confirmRef}
            className="cv-project-bulk-confirm"
            role="alertdialog"
            aria-modal="true"
            aria-label="确认批量删除项目"
            tabIndex={-1}
            onKeyDown={confirmKeys}
          >
            <h2>批量删除所选项目</h2>
            {preview?.loading && <p role="status">正在检查所选项目与活动任务…</p>}
            {preview?.error && <p role="alert">{preview.error}</p>}
            {preview && !preview.loading && !preview.error && (
              <>
                <p className="cv-project-bulk-confirm-meta">
                  共选择 <strong>{previewItems.length}</strong> 个项目，可执行删除 <strong>{deletableCount}</strong> 个
                  {blockedCount > 0 ? (
                    <>
                      ，将跳过 <strong className="is-warning">{blockedCount}</strong> 个
                    </>
                  ) : (
                    ''
                  )}
                  。
                </p>
                <ul className="cv-project-bulk-preview-list" aria-label="待删除项目预览列表">
                  {previewItems.map(item => (
                    <li
                      key={item.id}
                      data-preview-project-id={item.id}
                      className={`cv-project-bulk-preview-item${item.can_delete ? '' : ' is-blocked'}`}
                    >
                      <div className="cv-project-bulk-preview-main">
                        <strong>{item.title || item.id}</strong>
                        {item.id === currentProjectId && <span className="cv-project-bulk-tag">当前项目</span>}
                        <span className="cv-project-bulk-wf-count">{item.workflow_count} 个画布</span>
                      </div>
                      {item.can_delete ? (
                        <span className="cv-project-bulk-status is-ok">可删除</span>
                      ) : (
                        <span className="cv-project-bulk-status is-blocked">
                          <AlertTriangle size={13} aria-hidden="true" />
                          {blockedPreviewLabel(item)}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
                <label className="cv-project-bulk-cleanup">
                  <input
                    type="checkbox"
                    checked={cleanupAssets}
                    disabled={deleting || deletableCount === 0}
                    onChange={event => setCleanupAssets(event.target.checked)}
                  />
                  <span>同时清理旧非素材库关联缓存与未入库任务输出（不删除素材库文件）</span>
                </label>
                <p className="cv-project-bulk-hint">
                  {cleanupAssets
                    ? '仅清理已删项目独有的旧缓存与未入库任务输出；全局素材库中的所有媒体文件及其他项目共享引用将完整保留。'
                    : '不勾选时仅从项目列表移除，保留全部旧缓存、任务产物及全局素材库文件。'}
                </p>
              </>
            )}
            {deleteError && <p role="alert">{deleteError}</p>}
            <footer>
              <button type="button" className="btn btn-secondary" disabled={deleting} onClick={closeDeleteConfirm}>
                取消
              </button>
              <button
                type="button"
                className="btn btn-danger"
                disabled={deleting || !preview || preview.loading || !!preview.error || deletableCount === 0}
                onClick={executeBulkDelete}
              >
                {deleting ? '删除中…' : `确认删除 (${deletableCount})`}
              </button>
            </footer>
          </section>
        </div>
      )}
    </div>,
    document.body,
  )
}
