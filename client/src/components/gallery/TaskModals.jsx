import { useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { AnimatePresence, motion, useDragControls } from 'framer-motion'
import { AudioLines, ArchiveRestore, Ban, Braces, Check, ChevronDown, ChevronLeft, ChevronRight, Columns3, Copy, Download, FolderHeart, Heart, Image as ImageIcon, RefreshCw, RotateCcw, Trash2, X, ZoomIn, ZoomOut } from 'lucide-react'
import IconButton from '../ui/IconButton'
import { ACTIVE_STATUSES, STATUS, taskStatusInfo, providerLabel, downloadExtension, uniqueDownloadName, taskDownloadUrl } from './taskModel.js'
import { AudioArtwork, TaskPreview } from './TaskPreview.jsx'

export function DetailMedia({ item, outputIndex, setOutputIndex }) {
  if (ACTIVE_STATUSES.has(item.status) || item.status === 'failed' || (!item.images?.length && !item.video && !item.audio && !item.poster)) {
    return <div className="relative size-full min-h-0"><TaskPreview item={item} compact={false} /></div>
  }
  if (item.type === 'video') {
    return item.video
      ? <video src={item.video} poster={item.poster || undefined} controls autoPlay={false} className="max-h-full max-w-full object-contain" />
      : <img src={item.poster} className="max-h-full max-w-full object-contain" alt="视频尾帧" />
  }
  if (item.type === 'audio') {
    return (
      <div className="audio-detail-player">
        <AudioArtwork compact={false} />
        <audio src={item.audio} controls preload="metadata" className="relative z-10 w-full" />
      </div>
    )
  }
  return (
    <div className="flex size-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1 items-center justify-center p-5">
        <img src={item.images[outputIndex] || item.images[0]} className="max-h-full max-w-full object-contain" alt="任务输出" />
      </div>
      {item.images.length > 1 && (
        <div className="flex h-20 shrink-0 justify-center gap-2 border-t border-white/8 p-2">
          {item.images.map((url, index) => (
            <button key={url} type="button" onClick={() => setOutputIndex(index)} className={`aspect-square overflow-hidden rounded border ${index === outputIndex ? 'border-nexus-green' : 'border-white/10'}`}>
              <img src={url} className="size-full object-cover" alt={`输出 ${index + 1}`} />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export const COMPARE_ROWS = [
  ['模型', item => item.params?.model],
  ['端点', item => providerLabel(item.provider)],
  ['画幅', item => item.params?.aspect_ratio || item.params?.ratio],
  ['尺寸', item => item.params?.size || (
    item.params?.custom_width && item.params?.custom_height
      ? `${item.params.custom_width}×${item.params.custom_height}`
      : null
  )],
  ['分辨率', item => item.params?.resolution],
  ['时长', item => item.params?.duration === -1 ? 'Auto' : (
    item.params?.duration ? `${item.params.duration}s` : null
  )],
  ['格式', item => item.params?.output_format?.toUpperCase()],
  ['状态', item => taskStatusInfo(item)?.label || item.status],
]

export function CompareMedia({ item, zoom }) {
  const style = { transform: `scale(${zoom})` }
  if (item.type === 'video' && item.video) {
    return <video src={item.video} poster={item.poster || undefined} controls preload="metadata" style={style} />
  }
  if (item.type === 'audio' && item.audio) {
    return <div className="relative size-full"><AudioArtwork compact /><audio src={item.audio} controls preload="metadata" className="absolute inset-x-3 bottom-3 z-10 w-[calc(100%-24px)]" /></div>
  }
  const image = item.images?.[0] || item.poster || item.thumbnail
  if (image) return <img src={image} loading="eager" decoding="async" style={style} alt={`任务 ${item.taskId} 输出`} />
  return <div className="relative size-full"><TaskPreview item={item} compact={false} /></div>
}

export function TaskCompareModal({ items, onClose, onReuse }) {
  const [zoom, setZoom] = useState(1)
  useEffect(() => {
    const onKeyDown = event => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const changedRows = new Set(COMPARE_ROWS.filter(([label, getValue]) => {
    const values = new Set(items.map(item => String(getValue(item) || '—')))
    return values.size > 1
  }).map(([label]) => label))

  return ReactDOM.createPortal(
    <motion.div
      className="task-compare-backdrop fixed inset-0 z-[230] flex items-center justify-center p-5"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}
    >
      <motion.section
        role="dialog"
        aria-modal="true"
        aria-label="任务对比"
        className="task-compare-modal liquid-glass-strong flex min-h-0 flex-col overflow-hidden"
        initial={{ opacity: 0, scale: 0.98, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.985, y: 8 }}
      >
        <header className="task-compare-toolbar flex h-13 shrink-0 items-center gap-3 border-b border-white/10 px-4">
          <Columns3 size={16} className="text-nexus-cyan" />
          <div>
            <div className="text-sm font-semibold text-nexus-text-light">任务对比</div>
            <div className="font-mono text-xs text-nexus-muted">{items.length} ITEMS</div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <ZoomOut size={14} className="text-nexus-muted" />
            <input
              type="range"
              min="1"
              max="2.5"
              step="0.1"
              value={zoom}
              onChange={event => setZoom(Number(event.target.value))}
              aria-label="同步缩放"
              className="task-compare-zoom"
            />
            <ZoomIn size={14} className="text-nexus-muted" />
            <span className="w-10 text-right font-mono text-xs text-nexus-text">{Math.round(zoom * 100)}%</span>
            <IconButton label="关闭任务对比" onClick={onClose}><X size={18} /></IconButton>
          </div>
        </header>
        <div className="custom-scrollbar min-h-0 flex-1 overflow-auto p-3">
          <div className="task-compare-grid" style={{ '--compare-columns': items.length }}>
            {items.map(item => (
              <article key={item.key} className="task-compare-column">
                <div className="task-compare-media">
                  <CompareMedia item={item} zoom={zoom} />
                </div>
                <div className="task-compare-heading">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-nexus-text-light">TASK #{item.taskId}</span>
                    <span className={`status-pill ml-auto ${taskStatusInfo(item)?.tone || STATUS.pending.tone}`}>
                      {taskStatusInfo(item)?.label || item.status}
                    </span>
                  </div>
                  <p className="line-clamp-3 mt-2 min-h-15 break-words text-xs leading-5 text-nexus-text">{item.prompt || '未填写提示词'}</p>
                </div>
                <dl className="task-compare-params">
                  {COMPARE_ROWS.map(([label, getValue]) => (
                    <div key={label} className={`task-compare-param ${changedRows.has(label) ? 'task-compare-param-different' : ''}`}>
                      <dt>{label}</dt>
                      <dd title={String(getValue(item) || '—')}>{String(getValue(item) || '—')}</dd>
                    </div>
                  ))}
                </dl>
                <footer className="mt-auto border-t border-white/8 p-2">
                  <button type="button" onClick={() => onReuse(item.source)} className="btn btn-secondary btn-sm btn-block">
                    <RotateCcw size={13} /> 复用参数
                  </button>
                </footer>
              </article>
            ))}
          </div>
        </div>
      </motion.section>
    </motion.div>,
    document.body,
  )
}

export function FavoriteGroupAssignments({ item, groups, onChange }) {
  const selected = new Set((item.favoriteGroups || []).map(group => Number(group.id)))
  if (!groups.length) {
    return <p className="text-xs leading-5 text-nexus-muted">尚未创建收藏分组</p>
  }
  return (
    <div className="grid grid-cols-2 gap-2">
      {groups.map(group => {
        const checked = selected.has(Number(group.id))
        return (
          <button
            key={group.id}
            type="button"
            role="checkbox"
            aria-checked={checked}
            onClick={() => onChange(item, group.id)}
            className={`favorite-group-assignment ${checked ? 'favorite-group-assignment-active' : ''}`}
            data-color={group.color}
          >
            <span className="favorite-group-dot" />
            <span className="truncate">{group.name}</span>
            {checked && <Check size={12} className="ml-auto shrink-0" />}
          </button>
        )
      })}
    </div>
  )
}

export function TaskDetailModal({
  item,
  position,
  total,
  onPrevious,
  onNext,
  onClose,
  onFavorite,
  onDelete,
  onReuse,
  onCancel,
  onRetry,
  onRestore,
  onSetGroup,
  favoriteGroups,
  trash,
}) {
  const [outputIndex, setOutputIndex] = useState(0)
  const [referenceIndex, setReferenceIndex] = useState(null)
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false)
  const [openedAt] = useState(() => new Date())
  const backdropRef = useRef(null)
  const downloadMenuRef = useRef(null)
  const dragControls = useDragControls()
  useEffect(() => {
    setOutputIndex(0)
    setReferenceIndex(null)
    setDownloadMenuOpen(false)
  }, [item.key])
  useEffect(() => {
    if (!downloadMenuOpen) return undefined
    const closeMenu = event => {
      if (event.type === 'keydown' && event.key !== 'Escape') return
      if (event.type === 'pointerdown' && downloadMenuRef.current?.contains(event.target)) return
      setDownloadMenuOpen(false)
    }
    document.addEventListener('pointerdown', closeMenu)
    document.addEventListener('keydown', closeMenu)
    return () => {
      document.removeEventListener('pointerdown', closeMenu)
      document.removeEventListener('keydown', closeMenu)
    }
  }, [downloadMenuOpen])
  useEffect(() => {
    const onKeyDown = event => {
      if (referenceIndex !== null) {
        if (event.key === 'Escape') setReferenceIndex(null)
        if (event.key === 'ArrowLeft') {
          setReferenceIndex(index => (index - 1 + item.refs.length) % item.refs.length)
        }
        if (event.key === 'ArrowRight') {
          setReferenceIndex(index => (index + 1) % item.refs.length)
        }
        return
      }
      if (event.key === 'Escape') onClose()
      if (event.key === 'ArrowLeft') onPrevious()
      if (event.key === 'ArrowRight') onNext()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [item.refs.length, onClose, onNext, onPrevious, referenceIndex])

  const params = item.params || {}
  const download = item.type === 'video' ? item.video : item.type === 'audio' ? item.audio : item.images?.[outputIndex]
  const downloadName = download ? uniqueDownloadName(item, outputIndex, download, openedAt) : ''
  const downloadUrl = download ? taskDownloadUrl(item, download) : ''
  const originalDownloadName = download ? uniqueDownloadName(item, outputIndex, download, openedAt, true) : ''
  const originalDownloadUrl = download ? taskDownloadUrl(item, download, true) : ''
  const supportsPngInfo = download && item.type === 'image' && downloadExtension(item, download) === 'png'
  const aspectRatio = params.aspect_ratio === 'auto'
    ? 'Auto'
    : params.aspect_ratio === 'custom' ? '自定义' : (params.aspect_ratio || params.ratio)
  const rows = [
    ['画幅', aspectRatio],
    ['尺寸', params.size],
    ['分辨率', params.resolution],
    ['时长', params.duration === -1 ? 'Auto' : params.duration ? `${params.duration}s` : null],
    ['格式', params.output_format?.toUpperCase()],
    ['采样率', params.sample_rate ? `${Number(params.sample_rate) / 1000} kHz` : null],
    ['字幕', params.enable_subtitle === undefined ? null : params.enable_subtitle ? '开启' : '关闭'],
    ['声线', params.speaker],
    ['Provider', item.provider],
  ].filter(([, value]) => value !== undefined && value !== null && value !== '')

  return ReactDOM.createPortal(
    <motion.div
      ref={backdropRef}
      className="task-detail-backdrop fixed inset-0 z-[220] flex items-center justify-center p-5"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}
    >
      <motion.section
        role="dialog"
        aria-modal="true"
        aria-label="任务详情"
        className="task-detail-modal liquid-glass-strong grid overflow-hidden"
        drag
        dragConstraints={backdropRef}
        dragControls={dragControls}
        dragElastic={0}
        dragListener={false}
        dragMomentum={false}
        initial={{ opacity: 0, scale: 0.97, y: 12 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.98, y: 8 }}
      >
        <header
          className="task-detail-toolbar col-span-2 flex h-12 items-center border-b border-white/10 px-3"
          data-testid="task-detail-drag-handle"
          onPointerDown={event => {
            if (event.button !== 0 || event.target.closest('button, a')) return
            dragControls.start(event)
          }}
        >
          <IconButton label="上一个任务" onClick={onPrevious}><ChevronLeft size={17} /></IconButton>
          <span className="min-w-16 text-center font-mono text-xs text-nexus-text">{position + 1} / {total}</span>
          <IconButton label="下一个任务" onClick={onNext}><ChevronRight size={17} /></IconButton>
          <span className="ml-3 truncate font-mono text-xs text-nexus-muted">TASK #{item.taskId}</span>
          <span className="ml-auto">
            <IconButton label="关闭任务详情" onClick={onClose}><X size={18} /></IconButton>
          </span>
        </header>

        <div className="task-detail-stage relative flex min-h-0 items-center justify-center overflow-hidden bg-[#030506]">
          <DetailMedia item={item} outputIndex={outputIndex} setOutputIndex={setOutputIndex} />
        </div>

        <aside className="task-detail-inspector flex min-h-0 flex-col border-l border-white/10 bg-black/20">
          <div className="custom-scrollbar flex-1 overflow-y-auto">
            <section className="border-b border-white/8 p-4">
              <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-nexus-text-light">
                <Braces size={14} className="text-nexus-green" /> Prompt
                <button type="button" aria-label="复制 Prompt" title="复制 Prompt" onClick={() => navigator.clipboard?.writeText(item.prompt || '')} className="btn btn-icon btn-sm ml-auto"><Copy size={13} /></button>
              </div>
              <p className="whitespace-pre-wrap break-words text-sm leading-6 text-nexus-text">{item.prompt || '未填写提示词'}</p>
            </section>
            {item.resultUnknown && (
              <section className="border-b border-white/8 p-4" data-testid="task-result-unknown" role="status">
                <div className="mb-2 text-xs font-semibold text-nexus-amber">结果未知，可能已计费</div>
                <p className="text-xs leading-5 text-nexus-text">{item.resultUnknownReason ? `${item.resultUnknownReason}。` : ''}请求已发出但没有收到确认结果。请先到供应商控制台核查{item.type === 'image' ? '；重试需要再次确认，可能重复计费' : '；此类任务不提供重试，请复用参数后自行决定是否重新提交'}。</p>
                {item.error && <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-5 text-nexus-text-light">{item.error}</p>}
              </section>
            )}
            <section className="border-b border-white/8 p-4">
              <div className="mb-3 text-xs font-semibold text-nexus-text-light">输入参数</div>
              <dl className="space-y-3">
                {rows.map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between gap-3 text-xs">
                    <dt className="text-nexus-muted">{label}</dt>
                    <dd className="font-mono text-right text-nexus-text-light">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </section>
            {item.type === 'image' && item.sourceUrls?.length > 0 && (
              <section className="border-b border-white/8 p-4">
                <div className="mb-3 text-xs font-semibold text-nexus-text-light">端点图像 URL</div>
                <div className="space-y-2">
                  {item.sourceUrls.map((url, index) => (
                    <div key={`${url}-${index}`} className="flex min-w-0 items-start gap-2 rounded border border-white/8 bg-black/20 p-2">
                      <a href={url} target="_blank" rel="noreferrer" title={url} className="min-w-0 flex-1 break-all font-mono text-xs leading-4 text-nexus-cyan hover:text-white">
                        {url}
                      </a>
                      <button type="button" aria-label={`复制端点图像 URL ${index + 1}`} title="复制 URL" onClick={() => navigator.clipboard?.writeText(url)} className="btn btn-icon btn-sm shrink-0">
                        <Copy size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            )}
            {item.taskId && !trash && (
              <section className="border-b border-white/8 p-4">
                <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-nexus-text-light">
                  <FolderHeart size={14} className="text-nexus-cyan" /> 收藏分组
                  {!item.favorite && <span className="ml-auto text-xs font-normal text-nexus-muted">选择分组将自动收藏</span>}
                </div>
                <FavoriteGroupAssignments item={item} groups={favoriteGroups} onChange={onSetGroup} />
              </section>
            )}
            {item.refs?.length > 0 && (
              <section className="p-4">
                <div className="mb-3 text-xs font-semibold text-nexus-text-light">参考素材</div>
                <div className="grid grid-cols-4 gap-2">
                  {item.refs.slice(0, 8).map((url, index) => (
                    <button
                      key={url}
                      type="button"
                      aria-label={`打开参考素材 ${index + 1}`}
                      title={`参考素材 ${index + 1}`}
                      onClick={() => setReferenceIndex(index)}
                      className="task-reference-thumbnail aspect-square w-full overflow-hidden"
                    >
                      {item.refTypes?.[index] === 'audio' ? (
                        <span className="flex size-full items-center justify-center bg-black/35"><AudioLines size={18} className="text-nexus-cyan" /></span>
                      ) : item.refTypes?.[index] === 'video' ? (
                        <video src={url} className="size-full object-cover" muted preload="metadata" />
                      ) : (
                        <img src={url} className="size-full object-cover" alt={`参考素材 ${index + 1}`} />
                      )}
                    </button>
                  ))}
                </div>
              </section>
            )}
          </div>
          <footer className="flex h-14 shrink-0 items-center gap-1 border-t border-white/10 px-3">
            {item.taskId && !trash && (
              <IconButton label={item.favorite ? '取消收藏任务' : '收藏任务'} onClick={() => onFavorite(item)} className={item.favorite ? 'text-[#ff5c7c]' : ''}>
                <Heart size={17} fill={item.favorite ? 'currentColor' : 'none'} />
              </IconButton>
            )}
            {supportsPngInfo ? (
              <div ref={downloadMenuRef} className="relative">
                <button
                  type="button"
                  aria-label="下载任务结果"
                  aria-haspopup="menu"
                  aria-expanded={downloadMenuOpen}
                  title="选择下载格式"
                  onClick={() => setDownloadMenuOpen(open => !open)}
                  className={`btn btn-icon ${downloadMenuOpen ? 'is-active' : ''}`}
                >
                  <Download size={17} />
                  <ChevronDown size={10} />
                </button>
                <AnimatePresence>
                  {downloadMenuOpen && (
                    <motion.div
                      role="menu"
                      aria-label="图片下载选项"
                      className="task-layout-menu absolute bottom-[calc(100%+8px)] left-0 z-50 w-48 p-2"
                      initial={{ opacity: 0, y: 5, scale: 0.98 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 4, scale: 0.98 }}
                    >
                      <a role="menuitem" href={downloadUrl} download={downloadName} onClick={() => setDownloadMenuOpen(false)} className="task-group-option">
                        <Download size={14} /> 带生成参数
                      </a>
                      <a role="menuitem" href={originalDownloadUrl} download={originalDownloadName} onClick={() => setDownloadMenuOpen(false)} className="task-group-option">
                        <ImageIcon size={14} /> 原始生成图
                      </a>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            ) : download ? (
              <a href={downloadUrl} download={downloadName} aria-label="下载任务结果" title={downloadName} className="btn btn-icon"><Download size={17} /></a>
            ) : null}
            {item.kind === 'history' && !trash && <IconButton label="复用任务参数" onClick={() => onReuse(item.source)}><RotateCcw size={17} /></IconButton>}
            {item.taskId && ACTIVE_STATUSES.has(item.status) && item.status !== 'cancel_requested' && !trash && (
              <IconButton label="取消任务" onClick={() => onCancel(item)} className="hover:text-nexus-amber"><Ban size={17} /></IconButton>
            )}
            {item.taskId && item.type === 'image' && ['failed', 'cancelled'].includes(item.status) && !trash && (
              <IconButton label={item.resultUnknown ? '重试任务（结果未知，需确认）' : '重试任务'} onClick={() => onRetry(item)}><RefreshCw size={17} /></IconButton>
            )}
            {item.kind === 'history' && trash && (
              <IconButton label="恢复任务" onClick={() => onRestore(item)}><ArchiveRestore size={17} /></IconButton>
            )}
            {item.kind === 'history' && (
              <span className="ml-auto">
                <IconButton label={trash ? '彻底删除任务' : '移到回收站'} onClick={() => onDelete(item)} className="hover:text-nexus-red"><Trash2 size={17} /></IconButton>
              </span>
            )}
          </footer>
        </aside>
      </motion.section>

      <AnimatePresence>
        {referenceIndex !== null && item.refs[referenceIndex] && (
          <motion.div
            className="task-reference-backdrop fixed inset-0 z-[240] flex items-center justify-center p-12"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onMouseDown={event => {
              event.stopPropagation()
              if (event.target === event.currentTarget) setReferenceIndex(null)
            }}
          >
            <motion.section
              role="dialog"
              aria-modal="true"
              aria-label="参考素材预览"
              className="task-reference-modal liquid-glass-strong flex min-h-0 flex-col overflow-hidden"
              initial={{ opacity: 0, scale: 0.97, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.98, y: 6 }}
            >
              <header className="flex h-11 shrink-0 items-center border-b border-white/10 px-3">
                <span className="font-mono text-xs text-nexus-muted">
                  REF {referenceIndex + 1} / {item.refs.length}
                </span>
                <span className="ml-auto">
                  <IconButton label="关闭参考素材预览" onClick={() => setReferenceIndex(null)}><X size={17} /></IconButton>
                </span>
              </header>
              <div className="relative flex min-h-0 flex-1 items-center justify-center bg-black/55 p-5">
                {item.refs.length > 1 && (
                  <IconButton
                    label="上一个参考素材"
                    onClick={() => setReferenceIndex(index => (index - 1 + item.refs.length) % item.refs.length)}
                    className="absolute left-3 z-10 bg-black/65"
                  >
                    <ChevronLeft size={19} />
                  </IconButton>
                )}
                {item.refTypes?.[referenceIndex] === 'audio' ? (
                  <div className="reference-audio-player"><AudioLines size={34} /><audio src={item.refs[referenceIndex]} controls autoPlay /></div>
                ) : item.refTypes?.[referenceIndex] === 'video' ? (
                  <video src={item.refs[referenceIndex]} controls autoPlay className="max-h-full max-w-full object-contain" />
                ) : (
                  <img src={item.refs[referenceIndex]} className="max-h-full max-w-full object-contain" alt={`参考素材全图 ${referenceIndex + 1}`} />
                )}
                {item.refs.length > 1 && (
                  <IconButton
                    label="下一个参考素材"
                    onClick={() => setReferenceIndex(index => (index + 1) % item.refs.length)}
                    className="absolute right-3 z-10 bg-black/65"
                  >
                    <ChevronRight size={19} />
                  </IconButton>
                )}
              </div>
            </motion.section>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>,
    document.body,
  )
}
