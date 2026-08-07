import React, { useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import axios from 'axios'
import { AnimatePresence, motion } from 'framer-motion'
import { Braces, Copy, FileImage, Send, SlidersHorizontal, Trash2, Upload, X } from 'lucide-react'
import IconButton from './ui/IconButton'

const PARAM_LABELS = {
  aspect_ratio: '画幅',
  resolution: '分辨率',
  size: '输出尺寸',
  custom_width: '自定义宽度',
  custom_height: '自定义高度',
  output_format: '格式',
  watermark: '水印',
  use_search: '联网搜索',
  think_level: '思考深度',
}

function formatBytes(value) {
  const bytes = Number(value) || 0
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatValue(key, value) {
  if (typeof value === 'boolean') return value ? '开启' : '关闭'
  if (key === 'aspect_ratio') return value === 'auto' ? 'Auto' : value === 'custom' ? '自定义' : String(value)
  if (key === 'think_level') return value === 'high' ? '深入' : value === 'minimal' ? '快速' : String(value)
  if (key === 'output_format') return String(value).toUpperCase()
  return String(value)
}

export default function PngInfoModal({ open, onClose, onApply }) {
  const inputRef = useRef(null)
  const previewUrlRef = useRef('')
  const requestRef = useRef(null)
  const [file, setFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [payload, setPayload] = useState(null)
  const [loading, setLoading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')

  const releasePreview = () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
    previewUrlRef.current = ''
  }

  const clear = () => {
    requestRef.current?.abort()
    requestRef.current = null
    releasePreview()
    setFile(null)
    setPreviewUrl('')
    setPayload(null)
    setError('')
    setDragging(false)
    setLoading(false)
    if (inputRef.current) inputRef.current.value = ''
  }

  const close = () => {
    clear()
    onClose()
  }

  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = event => {
      if (event.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  useEffect(() => () => {
    requestRef.current?.abort()
    releasePreview()
  }, [])

  const readFile = async selectedFile => {
    if (!selectedFile) return
    if (selectedFile.type !== 'image/png' && !selectedFile.name.toLowerCase().endsWith('.png')) {
      setError('请选择 PNG 文件')
      return
    }
    releasePreview()
    const nextPreview = URL.createObjectURL(selectedFile)
    previewUrlRef.current = nextPreview
    setPreviewUrl(nextPreview)
    setFile(selectedFile)
    setPayload(null)
    setError('')
    setLoading(true)
    const formData = new FormData()
    formData.append('file', selectedFile, selectedFile.name)
    requestRef.current?.abort()
    const controller = new AbortController()
    requestRef.current = controller
    try {
      const response = await axios.post('/api/png-info', formData, { signal: controller.signal })
      setPayload(response.data)
    } catch (requestError) {
      if (requestError.code === 'ERR_CANCELED') return
      setError(requestError.response?.data?.error || 'PNG Info 读取失败')
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null
        setLoading(false)
      }
    }
  }

  const metadata = payload?.metadata || null
  const params = metadata?.params || {}
  const canApply = Boolean(metadata?.prompt || Object.keys(params).length)

  return ReactDOM.createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="png-info-backdrop fixed inset-0 z-[1000] flex items-center justify-center p-10"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={event => { if (event.target === event.currentTarget) close() }}
        >
          <motion.section
            role="dialog"
            aria-modal="true"
            aria-label="PNG Info"
            className="png-info-modal liquid-glass-strong grid min-h-0 overflow-hidden"
            initial={{ opacity: 0, scale: 0.97, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 8 }}
          >
            <header className="col-span-2 flex h-12 items-center border-b border-white/10 px-3">
              <FileImage size={16} className="text-nexus-green" />
              <span className="ml-2 text-sm font-semibold text-nexus-text-light">PNG Info</span>
              {file && (
                <span className="ml-3 min-w-0 truncate font-mono text-[11px] text-nexus-muted">
                  {file.name} · {payload?.image ? `${payload.image.width}×${payload.image.height}` : ''} · {formatBytes(file.size)}
                </span>
              )}
              <div className="ml-auto flex items-center gap-1">
                {payload && (
                  <IconButton
                    label="复制 PNG Info"
                    onClick={() => navigator.clipboard?.writeText(JSON.stringify(metadata, null, 2))}
                  >
                    <Copy size={15} />
                  </IconButton>
                )}
                {file && <IconButton label="清除 PNG" onClick={clear}><Trash2 size={15} /></IconButton>}
                <IconButton label="关闭 PNG Info" onClick={close}><X size={17} /></IconButton>
              </div>
            </header>

            <div
              className={`png-info-preview relative flex min-h-0 items-center justify-center overflow-hidden ${dragging ? 'png-info-preview-dragging' : ''}`}
              onDragEnter={event => { event.preventDefault(); setDragging(true) }}
              onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy' }}
              onDragLeave={event => {
                event.preventDefault()
                if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false)
              }}
              onDrop={event => {
                event.preventDefault()
                setDragging(false)
                readFile(event.dataTransfer.files?.[0])
              }}
            >
              <input
                ref={inputRef}
                type="file"
                accept="image/png,.png"
                aria-label="选择 PNG 文件"
                className="hidden"
                onChange={event => readFile(event.target.files?.[0])}
              />
              {previewUrl ? (
                <img src={previewUrl} className="max-h-full max-w-full object-contain p-5" alt="PNG Info 预览" />
              ) : (
                <button
                  type="button"
                  onClick={() => inputRef.current?.click()}
                  className="flex min-h-44 min-w-64 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-white/15 bg-black/20 text-nexus-muted transition-colors hover:border-nexus-green/45 hover:text-nexus-green"
                >
                  <Upload size={24} />
                  <span className="text-sm">选择 PNG</span>
                </button>
              )}
              {previewUrl && (
                <button type="button" onClick={() => inputRef.current?.click()} className="btn-base btn-outline absolute bottom-3 left-3 min-h-8 px-3 text-xs">
                  <Upload size={13} /> 更换 PNG
                </button>
              )}
            </div>

            <aside className="png-info-data custom-scrollbar min-h-0 overflow-y-auto border-l border-white/10">
              {loading && (
                <div className="flex h-full items-center justify-center font-mono text-xs text-nexus-green">READING PNG CHUNKS...</div>
              )}
              {!loading && error && <div role="alert" className="m-4 rounded border border-nexus-red/30 bg-nexus-red/10 p-3 text-sm text-nexus-red">{error}</div>}
              {!loading && !payload && !error && (
                <div className="flex h-full items-center justify-center text-sm text-nexus-muted">未载入 PNG</div>
              )}
              {!loading && payload && (
                <>
                  <section className="border-b border-white/8 p-4">
                    <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-nexus-text-light"><Braces size={14} className="text-nexus-green" /> Prompt</div>
                    <p className="whitespace-pre-wrap break-words text-sm leading-6 text-nexus-text">{metadata.prompt || '未找到 Prompt'}</p>
                  </section>
                  <section className="border-b border-white/8 p-4">
                    <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-nexus-text-light"><SlidersHorizontal size={14} className="text-nexus-cyan" />生成参数</div>
                    {Object.keys(params).length ? (
                      <dl className="space-y-3">
                        {Object.entries(params).map(([key, value]) => (
                          <div key={key} className="flex items-center justify-between gap-4 text-xs">
                            <dt className="text-nexus-muted">{PARAM_LABELS[key] || key}</dt>
                            <dd className="font-mono text-right text-nexus-text-light">{formatValue(key, value)}</dd>
                          </div>
                        ))}
                      </dl>
                    ) : <p className="text-xs text-nexus-muted">未找到可复用参数</p>}
                  </section>
                  {Object.keys(metadata.chunks || {}).length > 0 && (
                    <section className="p-4">
                      <div className="mb-3 text-xs font-semibold text-nexus-text-light">文本块</div>
                      <div className="space-y-3">
                        {Object.entries(metadata.chunks).map(([key, value]) => (
                          <div key={key}>
                            <div className="mb-1 font-mono text-[10px] uppercase text-nexus-muted">{key}</div>
                            <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-md border border-white/8 bg-black/25 p-2 font-mono text-[10px] leading-4 text-nexus-text custom-scrollbar">{value}</pre>
                          </div>
                        ))}
                      </div>
                    </section>
                  )}
                </>
              )}
            </aside>

            <footer className="col-span-2 flex h-14 items-center border-t border-white/10 px-3">
              <span className="font-mono text-[10px] uppercase text-nexus-muted">{metadata?.source || 'PNG'}</span>
              <button
                type="button"
                disabled={!canApply}
                onClick={() => { onApply(metadata); close() }}
                className="btn-base btn-primary ml-auto min-h-9 px-4 text-xs"
              >
                <Send size={14} /> 发送到图片生成
              </button>
            </footer>
          </motion.section>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
