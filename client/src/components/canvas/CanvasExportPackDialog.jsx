import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Download,
  Film,
  Image as ImageIcon,
  Loader2,
  Music,
  Package,
  RefreshCw,
  X,
} from 'lucide-react'
import './canvasExportPack.css'

export const EXPORT_SCOPES = [
  { id: 'finalized', label: '仅定稿节点', hint: '仅打包已标为定稿且有结果的镜头' },
  { id: 'selected', label: '当前选中节点', hint: '仅打包画布上当前选中的节点' },
  { id: 'all', label: '全部有结果节点', hint: '打包本画布所有已有结果的图片、视频与音频节点' },
]

const FOCUSABLE_SELECTOR = 'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])'
const MEDIA_LABELS = { image: '图片', video: '视频', audio: '音频' }

export function formatPackBytes(bytes) {
  const num = Number(bytes)
  if (!Number.isFinite(num) || num < 0) return '0 B'
  if (num < 1024) return `${Math.round(num)} B`
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`
  if (num < 1024 * 1024 * 1024) return `${(num / (1024 * 1024)).toFixed(2)} MB`
  return `${(num / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

export function buildDownloadFilename(workflowTitle) {
  const cleaned = String(workflowTitle || '')
    .replace(/[\u0000-\u001f\u007f\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g, '')
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\.\.+/g, '_')
    .replace(/[\s_]+/g, '_')
    .replace(/^[ ._-]+|[ ._-]+$/g, '')
    .slice(0, 48)
  return `ink-traces-${cleaned || 'canvas'}-pack.zip`
}

export function parseFilenameFromDisposition(headerValue, fallback) {
  if (typeof headerValue !== 'string' || !headerValue) return fallback
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(headerValue)
  if (star?.[1]) {
    try {
      const decoded = decodeURIComponent(star[1].trim())
      if (decoded && !/[\\/]/.test(decoded)) return decoded
    } catch { /* ignore malformed encoding */ }
  }
  const quoted = /filename\s*=\s*"([^"]+)"/i.exec(headerValue)
  if (quoted?.[1] && !/[\\/]/.test(quoted[1])) return quoted[1]
  const plain = /filename\s*=\s*([^;\s]+)/i.exec(headerValue)
  if (plain?.[1] && !/[\\/]/.test(plain[1])) return plain[1]
  return fallback
}

export function formatEstimateLabel(item) {
  if (!item || item.estimate_status !== 'estimate' || item.estimated_cost_usd === 'unknown') {
    return '未知'
  }
  if (typeof item.estimate_display === 'string' && item.estimate_display) {
    return item.estimate_display
  }
  return `$${item.estimated_cost_usd}`
}

export function formatSummaryCost(summary) {
  if (!summary) return '未知'
  const min = Number(summary.known_cost_usd_min || 0)
  const max = Number(summary.known_cost_usd_max || 0)
  const unknown = Number(summary.unknown_cost_count || 0)
  const total = Number(summary.total_items || 0)
  if (total === 0) return '—'
  if (unknown === total) return '未知'
  const range = Math.abs(min - max) < 1e-9
    ? `$${min.toFixed(3)}`
    : `$${min.toFixed(3)}-$${max.toFixed(3)}`
  return unknown > 0 ? `${range}（另有 ${unknown} 项未知）` : range
}

export function reorderItems(items, fromIndex, toIndex) {
  if (!Array.isArray(items)) return []
  if (fromIndex < 0 || toIndex < 0 || fromIndex >= items.length || toIndex >= items.length || fromIndex === toIndex) {
    return items
  }
  const next = items.slice()
  const [moved] = next.splice(fromIndex, 1)
  next.splice(toIndex, 0, moved)
  const padWidth = Math.max(2, String(next.length).length)
  return next.map((item, idx) => {
    const seq = String(idx + 1).padStart(padWidth, '0')
    const filename = typeof item.filename === 'string'
      ? item.filename.replace(/^(media\/)\d+_/, `$1${seq}_`)
      : item.filename
    return { ...item, shot_no: idx + 1, filename }
  })
}

export function buildExportPayload({ scope, selectedNodeIds = [], items = [] }) {
  const payload = { scope }
  if (scope === 'selected') {
    payload.node_ids = Array.isArray(selectedNodeIds) ? selectedNodeIds : []
  }
  if (Array.isArray(items) && items.length > 0) {
    payload.ordered_node_ids = items.map(item => item.node_id)
  }
  return payload
}

function MediaIcon({ kind }) {
  if (kind === 'video') return <Film size={14} aria-hidden="true" />
  if (kind === 'audio') return <Music size={14} aria-hidden="true" />
  return <ImageIcon size={14} aria-hidden="true" />
}

async function readErrorMessage(response, fallback) {
  try {
    const data = await response.json()
    if (data && typeof data.error === 'string' && data.error.trim()) return data.error.trim()
  } catch { /* ignore non-JSON body */ }
  return fallback
}

export default function CanvasExportPackDialog({
  open = true,
  workflowId,
  workflowTitle = '',
  selectedNodeIds = [],
  onClose,
  notify,
}) {
  const normalizedSelected = useMemo(
    () => (Array.isArray(selectedNodeIds) ? [...new Set(selectedNodeIds.filter(id => typeof id === 'string' && id))] : []),
    [selectedNodeIds],
  )
  const [scope, setScope] = useState('finalized')
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState(null)
  const [items, setItems] = useState([])
  const [reloadTick, setReloadTick] = useState(0)
  const dialogRef = useRef(null)

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
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const onWinKeyDown = (event) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      if (!exporting) onClose?.()
    }
    window.addEventListener('keydown', onWinKeyDown)
    return () => window.removeEventListener('keydown', onWinKeyDown)
  }, [open, exporting, onClose])

  const loadPreview = useCallback(async (signal) => {
    if (!workflowId) {
      setError('当前画布未就绪，无法预览素材包')
      return
    }
    setLoading(true)
    setError('')
    try {
      const payload = {
        scope,
        ...(scope === 'selected' ? { node_ids: normalizedSelected } : {}),
      }
      const response = await fetch(`/api/canvas/workflows/${encodeURIComponent(workflowId)}/export-pack/preview`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload),
        signal,
      })
      if (!response.ok) {
        const message = await readErrorMessage(response, `预览素材包失败（${response.status}）`)
        throw new Error(message)
      }
      const data = await response.json()
      if (signal?.aborted) return
      setPreview(data)
      setItems(Array.isArray(data.items) ? data.items : [])
    } catch (err) {
      if (err?.name === 'AbortError') return
      setPreview(null)
      setItems([])
      setError(err?.message || '预览素材包失败')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [workflowId, scope, normalizedSelected])

  useEffect(() => {
    if (!open) return undefined
    const controller = new AbortController()
    loadPreview(controller.signal)
    return () => controller.abort()
  }, [open, loadPreview, reloadTick])

  function handleKeyDown(event) {
    event.stopPropagation()
    if (event.key === 'Escape') {
      event.preventDefault()
      if (!exporting) onClose?.()
      return
    }
    if (event.key === 'Tab' && dialogRef.current) {
      const focusable = [...dialogRef.current.querySelectorAll(FOCUSABLE_SELECTOR)]
        .filter(el => el.getClientRects().length > 0)
      if (!focusable.length) {
        event.preventDefault()
        dialogRef.current.focus()
      } else if (event.shiftKey && (document.activeElement === dialogRef.current || document.activeElement === focusable[0])) {
        event.preventDefault()
        focusable[focusable.length - 1].focus()
      } else if (!event.shiftKey && document.activeElement === focusable[focusable.length - 1]) {
        event.preventDefault()
        focusable[0].focus()
      }
    }
  }

  function moveItem(index, delta) {
    setItems(current => reorderItems(current, index, index + delta))
  }

  async function handleExport() {
    if (exporting || loading || !workflowId || items.length === 0 || preview?.over_limit) return
    setExporting(true)
    setError('')
    try {
      const payload = buildExportPayload({ scope, selectedNodeIds: normalizedSelected, items })
      const response = await fetch(`/api/canvas/workflows/${encodeURIComponent(workflowId)}/export-pack`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) {
        const message = await readErrorMessage(response, `导出素材包失败（${response.status}）`)
        throw new Error(message)
      }
      const blob = await response.blob()
      const fallbackName = buildDownloadFilename(workflowTitle || preview?.workflow_title)
      const filename = parseFilenameFromDisposition(response.headers.get('Content-Disposition'), fallbackName)
      const url = URL.createObjectURL(blob)
      try {
        const link = document.createElement('a')
        link.href = url
        link.download = filename
        link.style.display = 'none'
        document.body.appendChild(link)
        link.click()
        link.remove()
      } finally {
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      }
      notify?.(`已导出素材包 ${filename}`, 'success')
    } catch (err) {
      const message = err?.message || '导出素材包失败'
      setError(message)
      notify?.(message, 'error')
    } finally {
      setExporting(false)
    }
  }

  if (!open) return null

  const skipped = Array.isArray(preview?.skipped) ? preview.skipped : []
  const overLimit = Boolean(preview?.over_limit)
  const totalBytes = Number(preview?.total_bytes || 0)
  const padWidth = Math.max(2, String(Math.max(items.length, 1)).length)
  const canExport = !loading && !exporting && items.length > 0 && !overLimit

  const content = (
    <div
      className="cv-ep-overlay"
      onPointerDown={event => {
        event.stopPropagation()
        if (event.target === event.currentTarget && !exporting) onClose?.()
      }}
    >
      <section
        ref={dialogRef}
        className="cv-ep-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cv-ep-title"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <header className="cv-ep-header">
          <div className="cv-ep-title-group">
            <Package size={16} aria-hidden="true" />
            <div className="cv-ep-title-text">
              <h3 id="cv-ep-title">导出本场素材包 (ZIP)</h3>
              <p className="cv-ep-subtitle">
                {workflowTitle || preview?.workflow_title || '当前画布'} · 仅打包原始素材与镜头表（不拼接、不转码）
              </p>
            </div>
          </div>
          <button
            type="button"
            className="cv-ep-icon-btn"
            aria-label="关闭导出弹窗"
            disabled={exporting}
            onClick={onClose}
          >
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="cv-ep-body">
          <div className="cv-ep-scope-bar" role="radiogroup" aria-label="筛选导出范围">
            {EXPORT_SCOPES.map(option => {
              const active = scope === option.id
              const suffix = option.id === 'selected' ? ` (${normalizedSelected.length})` : ''
              return (
                <button
                  key={option.id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  className={`cv-ep-scope-btn ${active ? 'is-active' : ''}`}
                  disabled={exporting}
                  title={option.hint}
                  onClick={() => setScope(option.id)}
                >
                  {option.label}{suffix}
                </button>
              )
            })}
            <button
              type="button"
              className="cv-ep-icon-btn cv-ep-refresh-btn"
              aria-label="刷新预览清单"
              title="刷新预览清单"
              disabled={loading || exporting}
              onClick={() => setReloadTick(n => n + 1)}
            >
              <RefreshCw size={14} className={loading ? 'cv-ep-spin' : ''} aria-hidden="true" />
            </button>
          </div>

          {error && (
            <div className="cv-ep-alert is-error" role="alert">
              <AlertTriangle size={15} aria-hidden="true" />
              <span>{error}</span>
            </div>
          )}

          {overLimit && (
            <div className="cv-ep-alert is-warning" role="alert">
              <AlertTriangle size={15} aria-hidden="true" />
              <span>
                预计体积 {formatPackBytes(totalBytes)} 超过单包上限 {formatPackBytes(preview?.max_pack_bytes)}，请改选“仅定稿”或分批选中导出。
              </span>
            </div>
          )}

          <div className="cv-ep-section">
            <div className="cv-ep-section-head">
              <span>待打包镜头（{items.length}）</span>
              <span className="cv-ep-hint">可用上下按钮调整导出镜号顺序；包内附带 shotlist.csv 与 shotlist.json</span>
            </div>

            {loading ? (
              <div className="cv-ep-empty" aria-live="polite">
                <Loader2 size={16} className="cv-ep-spin" aria-hidden="true" />
                <span>正在扫描本场素材…</span>
              </div>
            ) : items.length === 0 ? (
              <div className="cv-ep-empty">
                <p>
                  {scope === 'finalized'
                    ? '当前画布暂无已定稿且包含可用结果的节点。'
                    : scope === 'selected'
                      ? (normalizedSelected.length === 0 ? '画布中未选中任何节点。' : '所选节点均无可导出的有效素材。')
                      : '当前画布暂无可导出的有效结果。'}
                </p>
                {scope !== 'all' && (
                  <button
                    type="button"
                    className="btn btn-secondary cv-ep-switch-btn"
                    disabled={exporting}
                    onClick={() => setScope('all')}
                  >
                    切换为「全部有结果节点」
                  </button>
                )}
              </div>
            ) : (
              <ol className="cv-ep-list" aria-label="导出镜头列表">
                {items.map((item, index) => {
                  const seq = String(index + 1).padStart(padWidth, '0')
                  return (
                    <li key={item.node_id} className="cv-ep-row" data-node-id={item.node_id}>
                      <span className="cv-ep-seq" aria-label={`镜号 ${seq}`}>#{seq}</span>
                      <div className="cv-ep-row-main">
                        <div className="cv-ep-row-top">
                          <span className={`cv-ep-kind is-${item.media_type}`}>
                            <MediaIcon kind={item.media_type} />
                            {MEDIA_LABELS[item.media_type] || item.media_type}
                          </span>
                          <strong className="cv-ep-row-title" title={item.title}>{item.title}</strong>
                          {item.finalized && (
                            <span className="cv-ep-final-badge">
                              <CheckCircle2 size={11} aria-hidden="true" />
                              定稿
                            </span>
                          )}
                        </div>
                        <div className="cv-ep-row-meta">
                          <span className="cv-ep-filename" title={item.filename}>{item.filename}</span>
                          <span>{item.model || '未知模型'}</span>
                          {item.spec && item.spec !== '-' && <span>{item.spec}</span>}
                          <span>{formatPackBytes(item.size_bytes)}</span>
                          <span title="估算费用，非实际扣费">估算 {formatEstimateLabel(item)}</span>
                        </div>
                      </div>
                      <div className="cv-ep-order-actions">
                        <button
                          type="button"
                          className="cv-ep-icon-btn"
                          aria-label={`上移镜头 ${item.title}`}
                          title="上移"
                          disabled={exporting || index === 0}
                          onClick={() => moveItem(index, -1)}
                        >
                          <ArrowUp size={14} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="cv-ep-icon-btn"
                          aria-label={`下移镜头 ${item.title}`}
                          title="下移"
                          disabled={exporting || index === items.length - 1}
                          onClick={() => moveItem(index, 1)}
                        >
                          <ArrowDown size={14} aria-hidden="true" />
                        </button>
                      </div>
                    </li>
                  )
                })}
              </ol>
            )}
          </div>

          {skipped.length > 0 && (
            <details className="cv-ep-skipped" open={items.length === 0}>
              <summary>已自动跳过 {skipped.length} 个节点</summary>
              <ul>
                {skipped.map(entry => (
                  <li key={`${entry.node_id}-${entry.reason}`}>
                    <span className="cv-ep-skip-title">{entry.title}</span>
                    <span className="cv-ep-skip-reason">{entry.message}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>

        <footer className="cv-ep-footer">
          <div className="cv-ep-summary" aria-live="polite">
            <span>共 <strong>{items.length}</strong> 个素材 · 预计 <strong>{formatPackBytes(totalBytes)}</strong></span>
            <span className="cv-ep-cost-note">估算费用：{formatSummaryCost(preview?.summary)}（非实际扣费）</span>
          </div>
          <div className="cv-ep-footer-actions">
            <button type="button" className="btn btn-secondary" disabled={exporting} onClick={onClose}>
              关闭
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!canExport}
              onClick={handleExport}
            >
              {exporting ? (
                <>
                  <Loader2 size={14} className="cv-ep-spin" aria-hidden="true" />
                  <span>正在打包导出…</span>
                </>
              ) : (
                <>
                  <Download size={14} aria-hidden="true" />
                  <span>导出素材包 (ZIP)</span>
                </>
              )}
            </button>
          </div>
        </footer>
      </section>
    </div>
  )

  return typeof document !== 'undefined' ? createPortal(content, document.body) : content
}
