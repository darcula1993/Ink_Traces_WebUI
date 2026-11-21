import React, { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Layers, Play, Trash2, X } from 'lucide-react'
import { TEMPLATE_NAME_MAX } from '../../lib/canvasGroupTemplates.js'
import './canvasTemplates.css'

const FOCUSABLE_SELECTOR = 'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])'

function useModalAccessibility(dialogRef, { open, busy, onClose }) {
  useEffect(() => {
    if (!open) return undefined
    const previous = document.activeElement
    if (dialogRef.current && !dialogRef.current.contains(document.activeElement)) {
      dialogRef.current.focus()
    }
    return () => {
      if (previous && previous.isConnected && typeof previous.focus === 'function') {
        previous.focus()
      }
    }
  }, [open, dialogRef])

  function handleKeyDown(event) {
    event.stopPropagation()
    if (event.key === 'Escape') {
      event.preventDefault()
      if (!busy) onClose?.()
      return
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault()
      return
    }
    if (event.key === 'Tab' && dialogRef.current) {
      const items = [...dialogRef.current.querySelectorAll(FOCUSABLE_SELECTOR)]
        .filter(el => el.getClientRects().length > 0)
      if (!items.length) {
        event.preventDefault()
        dialogRef.current.focus()
      } else if (event.shiftKey && (document.activeElement === dialogRef.current || document.activeElement === items[0])) {
        event.preventDefault()
        items[items.length - 1].focus()
      } else if (!event.shiftKey && document.activeElement === items[items.length - 1]) {
        event.preventDefault()
        items[0].focus()
      }
    }
  }

  return handleKeyDown
}

function formatUpdatedAt(value) {
  if (!value || typeof value !== 'string') return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  const pad = n => String(n).padStart(2, '0')
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`
}

/**
 * Controlled dialog for saving a canvas node group as a reusable structural template.
 * "同时保留提示词文本" defaults to unchecked (false).
 */
export function SaveGroupTemplateDialog({
  open = true,
  defaultName = '',
  nodeCount = null,
  edgeCount = null,
  skippedAssetCount = 0,
  busy = false,
  error = '',
  onSubmit,
  onConfirm,
  onClose,
}) {
  const [name, setName] = useState(() => String(defaultName || '').slice(0, TEMPLATE_NAME_MAX))
  const [includePrompts, setIncludePrompts] = useState(false)
  const [localError, setLocalError] = useState('')
  const dialogRef = useRef(null)

  useEffect(() => {
    if (open) {
      setName(String(defaultName || '').slice(0, TEMPLATE_NAME_MAX))
      setIncludePrompts(false)
      setLocalError('')
    }
  }, [open, defaultName])

  const handleKeyDown = useModalAccessibility(dialogRef, { open, busy, onClose })
  if (!open) return null

  const trimmed = name.trim()
  const submitHandler = onSubmit || onConfirm
  const displayedError = localError || error

  function submit() {
    if (busy) return
    if (!trimmed) {
      setLocalError('请输入模板名称')
      return
    }
    if (trimmed.length > TEMPLATE_NAME_MAX) {
      setLocalError(`模板名称不能超过 ${TEMPLATE_NAME_MAX} 个字符`)
      return
    }
    setLocalError('')
    submitHandler?.({ name: trimmed, includePrompts })
  }

  const content = (
    <div
      className="cv-tpl-overlay"
      onPointerDown={event => {
        event.stopPropagation()
        if (event.target === event.currentTarget && !busy) onClose?.()
      }}
    >
      <section
        ref={dialogRef}
        className="cv-tpl-dialog cv-tpl-save-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cv-tpl-save-title"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <header className="cv-tpl-header">
          <div className="cv-tpl-title-group">
            <Layers size={16} aria-hidden="true" />
            <h3 id="cv-tpl-save-title">存为结构模板</h3>
          </div>
          <button
            type="button"
            className="cv-tpl-icon-btn"
            aria-label="关闭"
            disabled={busy}
            onClick={onClose}
          >
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="cv-tpl-body">
          {(nodeCount != null || edgeCount != null) && (
            <p className="cv-tpl-summary">
              结构摘要：共 {nodeCount ?? 0} 个节点、{edgeCount ?? 0} 条连线
              {skippedAssetCount > 0 ? `（已自动跳过 ${skippedAssetCount} 个素材节点）` : ''}
            </p>
          )}

          <label className="cv-tpl-field">
            <span className="cv-tpl-label-row">
              <span>模板名称</span>
              <small className="cv-tpl-counter">{trimmed.length}/{TEMPLATE_NAME_MAX}</small>
            </span>
            <input
              type="text"
              autoFocus
              value={name}
              maxLength={TEMPLATE_NAME_MAX}
              disabled={busy}
              placeholder="例如：图生视频分镜结构"
              onChange={event => {
                setName(event.target.value)
                if (localError) setLocalError('')
              }}
              onKeyDown={event => {
                if (event.key === 'Enter' && !event.nativeEvent.isComposing && event.keyCode !== 229) {
                  event.preventDefault()
                  submit()
                }
              }}
            />
          </label>

          <label className="cv-tpl-checkbox">
            <input
              type="checkbox"
              checked={includePrompts}
              disabled={busy}
              onChange={event => setIncludePrompts(event.target.checked)}
            />
            <span>
              <strong>同时保留提示词文本</strong>
              <small>默认不勾选，仅保存节点布局、连线、参数与接口绑定；不会保存运行任务、生成结果或任何媒体文件。</small>
            </span>
          </label>

          {displayedError && (
            <p className="cv-tpl-error" role="alert">{displayedError}</p>
          )}
        </div>

        <footer className="cv-tpl-footer">
          <button type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || !trimmed}
            onClick={submit}
          >
            {busy ? '保存中…' : '保存模板'}
          </button>
        </footer>
      </section>
    </div>
  )

  return typeof document !== 'undefined' ? createPortal(content, document.body) : content
}

/**
 * Controlled dialog for browsing, applying, or deleting user-saved group templates.
 * Shows an explicit empty state explaining how to create a template.
 */
export function ApplyGroupTemplateDialog({
  open = true,
  templates = [],
  loading = false,
  busyId = null,
  error = '',
  onApply,
  onDelete,
  onClose,
}) {
  const dialogRef = useRef(null)
  const isBusy = Boolean(busyId)
  const handleKeyDown = useModalAccessibility(dialogRef, { open, busy: isBusy, onClose })

  if (!open) return null

  const items = Array.isArray(templates) ? templates : []

  const content = (
    <div
      className="cv-tpl-overlay"
      onPointerDown={event => {
        event.stopPropagation()
        if (event.target === event.currentTarget && !isBusy) onClose?.()
      }}
    >
      <section
        ref={dialogRef}
        className="cv-tpl-dialog cv-tpl-apply-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cv-tpl-apply-title"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <header className="cv-tpl-header">
          <div className="cv-tpl-title-group">
            <Layers size={16} aria-hidden="true" />
            <h3 id="cv-tpl-apply-title">套用结构模板</h3>
          </div>
          <button
            type="button"
            className="cv-tpl-icon-btn"
            aria-label="关闭"
            disabled={isBusy}
            onClick={onClose}
          >
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="cv-tpl-body">
          {error && (
            <p className="cv-tpl-error" role="alert">{error}</p>
          )}

          {loading ? (
            <p className="cv-tpl-status" role="status">正在载入结构模板…</p>
          ) : items.length === 0 ? (
            <div className="cv-tpl-empty" role="status">
              <Layers size={24} aria-hidden="true" />
              <strong>暂无已保存的结构模板</strong>
              <p>右键任意节点组即可存为结构模板</p>
            </div>
          ) : (
            <ul className="cv-tpl-list" aria-label="已保存的结构模板列表">
              {items.map(tpl => {
                const nodeCount = tpl.node_count ?? tpl.payload?.nodes?.length ?? 0
                const edgeCount = tpl.edge_count ?? tpl.payload?.edges?.length ?? 0
                const color = tpl.payload?.groupColor || 'green'
                const itemBusy = busyId === tpl.id
                const updatedLabel = formatUpdatedAt(tpl.updated_at)

                return (
                  <li key={tpl.id} className="cv-tpl-item">
                    <div className="cv-tpl-item-main">
                      <div className="cv-tpl-item-title">
                        <span className="cv-tpl-color-dot" data-color={color} aria-hidden="true" />
                        <strong title={tpl.name}>{tpl.name}</strong>
                        <span className={`cv-tpl-badge ${tpl.include_prompts ? 'is-prompt' : ''}`}>
                          {tpl.include_prompts ? '含提示词' : '仅结构'}
                        </span>
                      </div>
                      <div className="cv-tpl-item-meta">
                        <span>{nodeCount} 个节点</span>
                        <span aria-hidden="true">·</span>
                        <span>{edgeCount} 条连线</span>
                        {updatedLabel && (
                          <>
                            <span aria-hidden="true">·</span>
                            <span>{updatedLabel}</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="cv-tpl-item-actions">
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={isBusy}
                        aria-label={`套用模板 ${tpl.name}`}
                        onClick={() => onApply?.(tpl)}
                      >
                        <Play size={13} aria-hidden="true" />
                        <span>{itemBusy ? '处理中…' : '套用到画布'}</span>
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger btn-sm"
                        disabled={isBusy}
                        aria-label={`删除模板 ${tpl.name}`}
                        onClick={() => onDelete?.(tpl)}
                      >
                        <Trash2 size={13} aria-hidden="true" />
                        <span>删除</span>
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <footer className="cv-tpl-footer">
          <button type="button" className="btn btn-secondary" disabled={isBusy} onClick={onClose}>
            关闭
          </button>
        </footer>
      </section>
    </div>
  )

  return typeof document !== 'undefined' ? createPortal(content, document.body) : content
}

export default { SaveGroupTemplateDialog, ApplyGroupTemplateDialog }
