import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import axios from 'axios'
import { AnimatePresence, motion, useDragControls } from 'framer-motion'
import {
  AlertTriangle,
  ArchiveRestore,
  Ban,
  Braces,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Copy,
  Download,
  Film,
  FolderHeart,
  FolderPlus,
  Heart,
  Image as ImageIcon,
  LoaderCircle,
  LayoutGrid,
  ListChecks,
  Pencil,
  RefreshCw,
  RotateCcw,
  Search,
  SortDesc,
  Trash2,
  X,
} from 'lucide-react'
import CodeRainCanvas from './CodeRainCanvas'
import IconButton from './ui/IconButton'
import { useWorkspaceState } from '../lib/useWorkspaceState'

const ACTIVE_STATUSES = new Set(['submitting', 'preparing', 'pending', 'processing', 'cancel_requested'])
const TASK_PAGE_SIZE = 30
const DEFAULT_GALLERY_PREFERENCES = { cardSize: 'standard', cardDetails: 'detailed', sort: 'newest' }
const CARD_SIZE_OPTIONS = [
  { value: 'compact', label: 'Compact' },
  { value: 'standard', label: 'Standard' },
  { value: 'large', label: 'Large' },
]
const CARD_DETAIL_OPTIONS = [
  { value: 'clean', label: 'Clean' },
  { value: 'detailed', label: 'Detailed' },
]
const SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'updated', label: 'Recently updated' },
]
const GROUP_COLORS = ['green', 'cyan', 'blue', 'violet', 'rose', 'amber']
const EMPTY_NAVIGATION = {
  position: 0,
  total: 0,
  previous_id: null,
  next_id: null,
  first_id: null,
  last_id: null,
}
const STATUS = {
  succeeded: { label: '完成', icon: CheckCircle2, tone: 'text-nexus-green border-nexus-green/25 bg-nexus-green/10' },
  failed: { label: '失败', icon: AlertTriangle, tone: 'text-nexus-red border-nexus-red/25 bg-nexus-red/10' },
  processing: { label: '生成中', icon: LoaderCircle, spin: true, tone: 'text-nexus-green border-nexus-green/25 bg-nexus-green/10' },
  preparing: { label: '准备中', icon: LoaderCircle, spin: true, tone: 'text-nexus-cyan border-nexus-cyan/25 bg-nexus-cyan/10' },
  submitting: { label: '提交中', icon: LoaderCircle, spin: true, tone: 'text-nexus-cyan border-nexus-cyan/25 bg-nexus-cyan/10' },
  pending: { label: '排队中', icon: Clock3, tone: 'text-nexus-amber border-nexus-amber/25 bg-nexus-amber/10' },
  cancel_requested: { label: '正在取消', icon: LoaderCircle, spin: true, tone: 'text-nexus-amber border-nexus-amber/25 bg-nexus-amber/10' },
  cancelled: { label: '已取消', icon: Ban, tone: 'text-nexus-muted border-white/15 bg-white/5' },
}

function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value))
}

function downloadExtension(item, url) {
  const configured = String(item.params?.output_format || '').toLowerCase()
  if (configured === 'jpeg') return 'jpg'
  if (['png', 'jpg', 'webp', 'gif'].includes(configured)) return configured
  const dataType = String(url || '').match(/^data:(?:image|video)\/([a-z0-9.+-]+)/i)?.[1]
  if (dataType) return dataType === 'jpeg' ? 'jpg' : dataType.split('+')[0]
  const pathExtension = String(url || '').split('?', 1)[0].match(/\.([a-z0-9]{2,5})$/i)?.[1]
  if (pathExtension) return pathExtension.toLowerCase() === 'jpeg' ? 'jpg' : pathExtension.toLowerCase()
  return item.type === 'video' ? 'mp4' : 'png'
}

function uniqueDownloadName(item, outputIndex, url, openedAt) {
  const identity = `task-${item.taskId}`
  const sourceDate = new Date(item.createdAt || openedAt)
  const safeDate = Number.isNaN(sourceDate.getTime()) ? openedAt : sourceDate
  const timestamp = safeDate.toISOString().replace(/\D/g, '').slice(0, 14)
  const output = item.type === 'image' ? `-output-${String(outputIndex + 1).padStart(2, '0')}` : ''
  return `ink-traces-${item.type}-${identity}-${timestamp}${output}.${downloadExtension(item, url)}`
}

function serverItem(task) {
  const result = task.result || {}
  const params = task.params || {}
  return {
    key: `task-${task.id}`,
    kind: 'history',
    taskId: task.id,
    type: task.type,
    status: task.status || 'pending',
    prompt: task.prompt || '',
    provider: task.provider || '',
    favorite: Boolean(task.favorite),
    favoriteGroups: task.favorite_groups || [],
    createdAt: task.created_at,
    deletedAt: task.deleted_at || null,
    retryOf: task.retry_of || null,
    progress: Number(task.progress) || 0,
    error: task.error || '',
    params,
    images: result.local_images || [],
    thumbnail: result.local_thumbnail || result.local_thumbnails?.[0] || null,
    video: result.local_video || null,
    poster: result.local_last_frame || null,
    refs: result.local_refs || [],
    source: task,
  }
}

function selectionToken(item) {
  return `task-${item.taskId}`
}

function TaskPreview({ item, compact = true }) {
  if (ACTIVE_STATUSES.has(item.status)) {
    return (
      <div className="absolute inset-0 overflow-hidden bg-black">
        <CodeRainCanvas status={item.status} compact={compact} />
        <div className="absolute inset-x-0 bottom-0 z-10 bg-black/80 px-3 py-2">
          <div className="mb-1 flex items-center justify-between font-mono text-[10px] text-[#9fffc2]">
            <span>{STATUS[item.status]?.label || '生成中'}</span>
            {item.progress > 0 && <span>{Math.min(100, item.progress)}%</span>}
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-white/10">
            <div className="h-full rounded-full bg-nexus-green transition-[width]" style={{ width: `${item.progress > 0 ? Math.min(100, item.progress) : 38}%` }} />
          </div>
        </div>
      </div>
    )
  }

  if (item.type === 'video' && (item.thumbnail || item.poster || item.video)) {
    return item.thumbnail || item.poster
      ? <img src={item.thumbnail || item.poster} loading="lazy" decoding="async" className="absolute inset-0 size-full object-contain" alt="视频任务预览" />
      : <video src={item.video} className="absolute inset-0 size-full object-contain" muted preload="metadata" />
  }
  if (item.images?.length) {
    return <img src={item.thumbnail || item.images[0]} loading="lazy" decoding="async" className="absolute inset-0 size-full object-contain" alt="图片任务预览" />
  }
  if (item.status === 'failed') {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-5 text-center text-nexus-red">
        <AlertTriangle size={28} />
        <span className="line-clamp-3 break-all text-xs leading-5">{item.error || '任务执行失败'}</span>
      </div>
    )
  }
  const EmptyIcon = item.type === 'video' ? Film : ImageIcon
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-nexus-muted">
      <EmptyIcon size={30} strokeWidth={1.25} />
      <span className="text-xs">暂无结果</span>
    </div>
  )
}

function TaskCard({
  item,
  detailed,
  selectionMode,
  checked,
  selectionTokenValue,
  onOpen,
  onToggleSelection,
  onFavorite,
  onCancel,
  trash,
}) {
  const status = STATUS[item.status] || STATUS.pending
  const StatusIcon = status.icon
  const activate = () => {
    if (selectionMode) {
      onToggleSelection(selectionTokenValue)
      return
    }
    onOpen(item)
  }
  return (
    <article
      role="button"
      tabIndex={0}
      data-testid="task-gallery-card"
      aria-label={selectionMode
        ? `${checked ? '取消选择' : '选择'}${item.type === 'video' ? '视频' : '图片'}任务`
        : `打开${item.type === 'video' ? '视频' : '图片'}任务`}
      aria-pressed={selectionMode ? checked : undefined}
      onClick={activate}
      onKeyDown={event => {
        if (event.target !== event.currentTarget) return
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          activate()
        }
      }}
      className={`task-gallery-card group relative min-w-0 overflow-hidden border bg-black/35 text-left transition-colors ${checked ? 'task-gallery-card-selected' : 'border-white/10 hover:border-white/25'}`}
    >
      <div className="task-card-preview relative overflow-hidden bg-[#050708]">
        <TaskPreview item={item} />
        <div className="absolute left-2 top-2 z-20 flex items-center gap-1.5">
          <span className={`status-pill min-h-6 px-2 text-[10px] ${status.tone}`}>
            <StatusIcon size={11} className={status.spin ? 'animate-spin' : ''} />
            {status.label}
          </span>
        </div>
        {selectionMode ? (
          <span
            className={`task-selection-check absolute right-2 top-2 z-20 ${checked ? 'task-selection-check-active' : ''}`}
            title={checked ? '已选择' : '选择任务'}
          >
            {checked && <Check size={13} />}
          </span>
        ) : (
          <div className="absolute right-2 top-2 z-20 flex items-center gap-1">
            {item.taskId && ACTIVE_STATUSES.has(item.status) && item.status !== 'cancel_requested' && !trash && (
              <button
                type="button"
                aria-label="取消任务"
                title="取消任务"
                onClick={event => { event.stopPropagation(); onCancel(item) }}
                className="task-card-action hover:text-nexus-amber"
              >
                <Ban size={14} />
              </button>
            )}
            {item.taskId && !trash && (
              <button
                type="button"
                aria-label={item.favorite ? '取消收藏任务' : '收藏任务'}
                title={item.favorite ? '取消收藏' : '收藏'}
                onClick={event => { event.stopPropagation(); onFavorite(item) }}
                className={`task-card-action ${item.favorite ? 'text-[#ff5c7c]' : ''}`}
              >
                <Heart size={14} fill={item.favorite ? 'currentColor' : 'none'} />
              </button>
            )}
          </div>
        )}
      </div>
      {detailed && (
        <div className="task-card-details border-t border-white/8 px-3 py-2.5">
          <p className="line-clamp-2 min-h-10 break-words text-xs leading-5 text-nexus-text-light">{item.prompt || '未填写提示词'}</p>
          {item.favoriteGroups?.length > 0 && (
            <div className="mt-2 flex min-w-0 gap-1 overflow-hidden">
              {item.favoriteGroups.slice(0, 2).map(group => (
                <span key={group.id} className="favorite-group-pill" data-color={group.color}>{group.name}</span>
              ))}
              {item.favoriteGroups.length > 2 && <span className="favorite-group-pill">+{item.favoriteGroups.length - 2}</span>}
            </div>
          )}
          <div className="mt-2 flex min-w-0 items-center gap-2 font-mono text-[10px] text-nexus-muted">
            <span>#{item.taskId}</span>
            {item.provider && <span className="truncate uppercase">{item.provider}</span>}
            {item.createdAt && <time className="ml-auto shrink-0">{formatTime(item.createdAt)}</time>}
          </div>
        </div>
      )}
    </article>
  )
}

function DetailMedia({ item, outputIndex, setOutputIndex }) {
  if (ACTIVE_STATUSES.has(item.status) || item.status === 'failed' || (!item.images?.length && !item.video && !item.poster)) {
    return <div className="relative size-full min-h-0"><TaskPreview item={item} compact={false} /></div>
  }
  if (item.type === 'video') {
    return item.video
      ? <video src={item.video} poster={item.poster || undefined} controls autoPlay={false} className="max-h-full max-w-full object-contain" />
      : <img src={item.poster} className="max-h-full max-w-full object-contain" alt="视频尾帧" />
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

function FavoriteGroupAssignments({ item, groups, onChange }) {
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

function TaskDetailModal({
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
  const [openedAt] = useState(() => new Date())
  const backdropRef = useRef(null)
  const dragControls = useDragControls()
  useEffect(() => {
    setOutputIndex(0)
    setReferenceIndex(null)
  }, [item.key])
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
  const download = item.type === 'video' ? item.video : item.images?.[outputIndex]
  const downloadName = download ? uniqueDownloadName(item, outputIndex, download, openedAt) : ''
  const rows = [
    ['画幅', params.aspect_ratio || params.ratio],
    ['分辨率', params.resolution],
    ['时长', params.duration ? `${params.duration}s` : null],
    ['格式', params.output_format?.toUpperCase()],
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
                <button type="button" aria-label="复制 Prompt" title="复制 Prompt" onClick={() => navigator.clipboard?.writeText(item.prompt || '')} className="icon-button ml-auto size-7"><Copy size={13} /></button>
              </div>
              <p className="whitespace-pre-wrap break-words text-sm leading-6 text-nexus-text">{item.prompt || '未填写提示词'}</p>
            </section>
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
            {item.taskId && !trash && (
              <section className="border-b border-white/8 p-4">
                <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-nexus-text-light">
                  <FolderHeart size={14} className="text-nexus-cyan" /> 收藏分组
                  {!item.favorite && <span className="ml-auto text-[10px] font-normal text-nexus-muted">选择分组将自动收藏</span>}
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
                      <img src={url} className="size-full object-cover" alt={`参考素材 ${index + 1}`} />
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
            {download && <a href={download} download={downloadName} aria-label="下载任务结果" title={downloadName} className="icon-button"><Download size={17} /></a>}
            {item.kind === 'history' && !trash && <IconButton label="复用任务参数" onClick={() => onReuse(item.source)}><RotateCcw size={17} /></IconButton>}
            {item.taskId && ACTIVE_STATUSES.has(item.status) && item.status !== 'cancel_requested' && !trash && (
              <IconButton label="取消任务" onClick={() => onCancel(item)} className="hover:text-nexus-amber"><Ban size={17} /></IconButton>
            )}
            {item.taskId && item.type === 'image' && ['failed', 'cancelled'].includes(item.status) && !trash && (
              <IconButton label="重试任务" onClick={() => onRetry(item)}><RefreshCw size={17} /></IconButton>
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
                <img
                  src={item.refs[referenceIndex]}
                  className="max-h-full max-w-full object-contain"
                  alt={`参考素材全图 ${referenceIndex + 1}`}
                />
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

export default function TaskGallery({
  mode,
  refreshToken,
  onReuseTask,
}) {
  const [tasks, setTasks] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState('all')
  const [favoriteGroup, setFavoriteGroup] = useState('all')
  const [favoriteGroups, setFavoriteGroups] = useState([])
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selectedKey, setSelectedKey] = useState(null)
  const [selectedOverride, setSelectedOverride] = useState(null)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState(() => new Set())
  const [selectionUniverse, setSelectionUniverse] = useState(() => new Set())
  const [selectingAll, setSelectingAll] = useState(false)
  const [navigation, setNavigation] = useState(EMPTY_NAVIGATION)
  const [navigationLoading, setNavigationLoading] = useState(false)
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false)
  const [groupMenuOpen, setGroupMenuOpen] = useState(false)
  const [bulkGroupMenuOpen, setBulkGroupMenuOpen] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')
  const [newGroupColor, setNewGroupColor] = useState('green')
  const [editingGroupId, setEditingGroupId] = useState(null)
  const [editingGroupName, setEditingGroupName] = useState('')
  const [galleryPreferences, setGalleryPreferences] = useWorkspaceState(
    'gallery_preferences',
    DEFAULT_GALLERY_PREFERENCES,
  )
  const layoutMenuRef = useRef(null)
  const groupMenuRef = useRef(null)
  const bulkGroupMenuRef = useRef(null)
  const fetchSequenceRef = useRef(0)
  const handledRefreshTokenRef = useRef(refreshToken)
  const cardSize = CARD_SIZE_OPTIONS.some(option => option.value === galleryPreferences?.cardSize)
    ? galleryPreferences.cardSize
    : DEFAULT_GALLERY_PREFERENCES.cardSize
  const cardDetails = CARD_DETAIL_OPTIONS.some(option => option.value === galleryPreferences?.cardDetails)
    ? galleryPreferences.cardDetails
    : DEFAULT_GALLERY_PREFERENCES.cardDetails
  const cardSort = SORT_OPTIONS.some(option => option.value === galleryPreferences?.sort)
    ? galleryPreferences.sort
    : DEFAULT_GALLERY_PREFERENCES.sort

  useEffect(() => {
    if (!layoutMenuOpen) return undefined
    const closeMenu = event => {
      if (event.type === 'keydown' && event.key !== 'Escape') return
      if (event.type === 'pointerdown' && layoutMenuRef.current?.contains(event.target)) return
      setLayoutMenuOpen(false)
    }
    document.addEventListener('pointerdown', closeMenu)
    document.addEventListener('keydown', closeMenu)
    return () => {
      document.removeEventListener('pointerdown', closeMenu)
      document.removeEventListener('keydown', closeMenu)
    }
  }, [layoutMenuOpen])

  useEffect(() => {
    if (!groupMenuOpen && !bulkGroupMenuOpen) return undefined
    const closeMenus = event => {
      if (event.type === 'keydown' && event.key !== 'Escape') return
      if (event.type === 'pointerdown' && (
        groupMenuRef.current?.contains(event.target) || bulkGroupMenuRef.current?.contains(event.target)
      )) return
      setGroupMenuOpen(false)
      setBulkGroupMenuOpen(false)
      setEditingGroupId(null)
    }
    document.addEventListener('pointerdown', closeMenus)
    document.addEventListener('keydown', closeMenus)
    return () => {
      document.removeEventListener('pointerdown', closeMenus)
      document.removeEventListener('keydown', closeMenus)
    }
  }, [bulkGroupMenuOpen, groupMenuOpen])

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 280)
    return () => window.clearTimeout(timer)
  }, [query])

  const updateGalleryPreference = useCallback((key, value) => {
    setGalleryPreferences(previous => ({
      ...DEFAULT_GALLERY_PREFERENCES,
      ...(previous || {}),
      [key]: value,
    }))
  }, [setGalleryPreferences])

  const buildFilterParams = useCallback((search = debouncedQuery) => ({
    type: mode,
    sort: cardSort,
    ...(view === 'favorite' ? { favorite: true } : {}),
    ...(view === 'active' ? { active: true } : {}),
    ...(view === 'trash' ? { deleted: true } : {}),
    ...(view === 'favorite' && favoriteGroup === 'ungrouped' ? { ungrouped: true } : {}),
    ...(view === 'favorite' && Number.isInteger(Number(favoriteGroup)) && Number(favoriteGroup) > 0
      ? { favorite_group: Number(favoriteGroup) }
      : {}),
    ...(search ? { q: search } : {}),
  }), [cardSort, debouncedQuery, favoriteGroup, mode, view])

  const buildSelectionParams = useCallback((search = query.trim()) => ({
    type: mode,
    view,
    sort: cardSort,
    ...(view === 'favorite' && favoriteGroup === 'ungrouped' ? { ungrouped: true } : {}),
    ...(view === 'favorite' && Number.isInteger(Number(favoriteGroup)) && Number(favoriteGroup) > 0
      ? { favorite_group: Number(favoriteGroup) }
      : {}),
    ...(search ? { q: search } : {}),
  }), [cardSort, favoriteGroup, mode, query, view])

  const fetchFavoriteGroups = useCallback(async () => {
    try {
      const response = await axios.get('/api/favorite-groups', { params: { type: mode } })
      if (response.data.success) setFavoriteGroups(response.data.groups || [])
    } catch (requestError) {
      setError(requestError.response?.data?.error || '收藏分组加载失败')
    }
  }, [mode])

  useEffect(() => {
    fetchFavoriteGroups()
  }, [fetchFavoriteGroups])

  const fetchTasks = useCallback(async ({ append = false, offset = 0, preserveLoaded = false } = {}) => {
    const sequence = ++fetchSequenceRef.current
    if (!preserveLoaded) setLoading(true)
    try {
      const response = await axios.get('/api/tasks', {
        params: {
          ...buildFilterParams(),
          limit: TASK_PAGE_SIZE,
          offset,
        },
      })
      if (sequence !== fetchSequenceRef.current) return
      if (response.data.success) {
        const fetched = response.data.tasks || []
        setTasks(previous => {
          const known = new Set(previous.map(task => Number(task.id)))
          if (preserveLoaded) {
            const previousById = new Map(previous.map(task => [Number(task.id), task]))
            const refreshed = new Set(fetched.map(task => Number(task.id)))
            const merged = [
              ...fetched.map(task => {
                const existing = previousById.get(Number(task.id))
                return existing?.updated_at === task.updated_at ? existing : task
              }),
              ...previous.filter(task => !refreshed.has(Number(task.id))),
            ]
            return merged.length === previous.length && merged.every((task, index) => task === previous[index])
              ? previous
              : merged
          }
          if (!append) return fetched
          return [...previous, ...fetched.filter(task => !known.has(Number(task.id)))]
        })
        setTotal(Number(response.data.total) || 0)
        setError('')
      }
    } catch (requestError) {
      if (sequence === fetchSequenceRef.current) {
        setError(requestError.response?.data?.error || '任务列表加载失败')
      }
    } finally {
      if (!preserveLoaded && sequence === fetchSequenceRef.current) setLoading(false)
    }
  }, [buildFilterParams])

  useEffect(() => {
    setTasks([])
    setTotal(0)
    fetchTasks()
  }, [fetchTasks])
  useEffect(() => {
    if (handledRefreshTokenRef.current === refreshToken) return
    handledRefreshTokenRef.current = refreshToken
    fetchTasks({ preserveLoaded: true })
  }, [fetchTasks, refreshToken])
  useEffect(() => {
    const hasActive = tasks.some(task => ACTIVE_STATUSES.has(task.status))
    if (!hasActive) return undefined
    const refresh = () => {
      if (!document.hidden) fetchTasks({ preserveLoaded: true })
    }
    const timer = window.setInterval(refresh, 4000)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [fetchTasks, tasks])

  const items = useMemo(() => tasks.map(serverItem), [tasks])

  const categoryItems = useMemo(() => items.filter(item => {
    if (view === 'favorite' && !item.favorite) return false
    if (view === 'active' && !ACTIVE_STATUSES.has(item.status)) return false
    if (view === 'favorite' && favoriteGroup === 'ungrouped' && item.favoriteGroups?.length) return false
    if (view === 'favorite' && Number.isInteger(Number(favoriteGroup)) && Number(favoriteGroup) > 0 &&
      !item.favoriteGroups?.some(group => Number(group.id) === Number(favoriteGroup))) return false
    return true
  }), [favoriteGroup, items, view])

  const visibleItems = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return categoryItems.filter(item => {
      if (!needle) return true
      return String(item.taskId).includes(needle) || item.prompt.toLowerCase().includes(needle) || item.provider.toLowerCase().includes(needle)
    })
  }, [categoryItems, query])

  const categoryTotal = total
  const selectedTaskCount = [...selectedKeys].filter(token => token.startsWith('task-')).length
  const activeFavoriteGroup = favoriteGroups.find(group => Number(group.id) === Number(favoriteGroup))
  const favoriteGroupLabel = favoriteGroup === 'ungrouped'
    ? '未分组'
    : (activeFavoriteGroup?.name || '全部收藏')
  const allCategorySelected = selectionUniverse.size > 0 &&
    [...selectionUniverse].every(token => selectedKeys.has(token))

  const visibleSelectedItem = visibleItems.find(item => item.key === selectedKey) || null
  const selectedItem = selectedKey ? (selectedOverride || visibleSelectedItem) : null
  const selectedPosition = Math.max(0, Number(navigation.position || 1) - 1)
  const selectedTotal = Math.max(
    Number(navigation.total || 0),
    selectedItem ? 1 : 0,
  )

  useEffect(() => {
    if (!selectedOverride?.taskId) return
    const summary = tasks.find(task => Number(task.id) === Number(selectedOverride.taskId))
    if (!summary) return
    const normalized = serverItem(summary)
    setSelectedOverride(previous => previous ? {
      ...previous,
      ...normalized,
      key: previous.key,
    } : previous)
  }, [selectedOverride?.taskId, tasks])

  useEffect(() => {
    setSelectedKey(null)
    setSelectedOverride(null)
    setNavigation(EMPTY_NAVIGATION)
  }, [cardSort, debouncedQuery, favoriteGroup, mode, view])

  const loadNavigation = useCallback(async taskId => {
    setNavigationLoading(true)
    try {
      const path = taskId ? `/api/tasks/${taskId}/navigation` : '/api/tasks/navigation'
      const response = await axios.get(path, { params: buildSelectionParams() })
      if (response.data.success) setNavigation({ ...EMPTY_NAVIGATION, ...(response.data.navigation || {}) })
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务导航加载失败')
    } finally {
      setNavigationLoading(false)
    }
  }, [buildSelectionParams])

  const openItem = useCallback(async (item, refreshNavigation = true) => {
    setSelectedKey(item.key)
    setSelectedOverride(item)
    if (refreshNavigation) loadNavigation(item.taskId)
    try {
      const response = await axios.get(`/api/tasks/${item.taskId}`)
      if (response.data.success) {
        const full = serverItem(response.data.task)
        setSelectedOverride({ ...item, ...full, key: item.key })
      }
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务详情加载失败')
    }
  }, [loadNavigation])

  const navigate = useCallback(async direction => {
    if (!selectedItem || selectedTotal <= 1 || navigationLoading) return
    const adjacentId = direction < 0 ? navigation.previous_id : navigation.next_id
    const wrapId = direction < 0 ? navigation.last_id : navigation.first_id
    const taskId = Number(adjacentId || wrapId)
    if (!taskId) return
    const loaded = tasks.find(task => Number(task.id) === taskId)
    if (loaded) {
      openItem(serverItem(loaded))
      return
    }
    try {
      const response = await axios.get(`/api/tasks/${taskId}`)
      if (!response.data.success) return
      const item = serverItem(response.data.task)
      setSelectedKey(item.key)
      setSelectedOverride(item)
      loadNavigation(taskId)
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务详情加载失败')
    }
  }, [
    loadNavigation,
    navigation,
    navigationLoading,
    openItem,
    selectedItem,
    selectedTotal,
    tasks,
  ])

  const toggleFavorite = useCallback(async item => {
    if (!item.taskId) return
    const favorite = !item.favorite
    try {
      const response = await axios.patch(`/api/tasks/${item.taskId}/favorite`, { favorite })
      const updatedTask = response.data.task
      setTasks(previous => view === 'favorite' && !favorite
        ? previous.filter(task => Number(task.id) !== Number(item.taskId))
        : previous.map(task => Number(task.id) === Number(item.taskId)
          ? { ...task, favorite, favorite_groups: updatedTask?.favorite_groups || [] }
          : task))
      if (view === 'favorite' && !favorite) setTotal(previous => Math.max(0, previous - 1))
      if (view === 'favorite' && !favorite) {
        setSelectedKey(null)
        setSelectedOverride(null)
      } else {
        setSelectedOverride(previous => previous && Number(previous.taskId) === Number(item.taskId)
          ? { ...previous, favorite, favoriteGroups: updatedTask?.favorite_groups || [] }
          : previous)
      }
      fetchFavoriteGroups()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '收藏状态更新失败')
    }
  }, [fetchFavoriteGroups, view])

  const createFavoriteGroup = useCallback(async event => {
    event?.preventDefault()
    const name = newGroupName.trim()
    if (!name) return
    try {
      await axios.post('/api/favorite-groups', { name, color: newGroupColor })
      setNewGroupName('')
      await fetchFavoriteGroups()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '收藏分组创建失败')
    }
  }, [fetchFavoriteGroups, newGroupColor, newGroupName])

  const saveFavoriteGroup = useCallback(async groupId => {
    const name = editingGroupName.trim()
    if (!name) return
    try {
      await axios.patch(`/api/favorite-groups/${groupId}`, { name })
      setEditingGroupId(null)
      setEditingGroupName('')
      await fetchFavoriteGroups()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '收藏分组更新失败')
    }
  }, [editingGroupName, fetchFavoriteGroups])

  const removeFavoriteGroup = useCallback(async group => {
    if (!window.confirm(`删除收藏分组“${group.name}”？任务仍会保留在收藏中。`)) return
    try {
      await axios.delete(`/api/favorite-groups/${group.id}`)
      if (Number(favoriteGroup) === Number(group.id)) setFavoriteGroup('all')
      await fetchFavoriteGroups()
      fetchTasks()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '收藏分组删除失败')
    }
  }, [favoriteGroup, fetchFavoriteGroups, fetchTasks])

  const toggleItemGroup = useCallback(async (item, groupId) => {
    if (!item.taskId) return
    const current = new Set((item.favoriteGroups || []).map(group => Number(group.id)))
    if (current.has(Number(groupId))) current.delete(Number(groupId))
    else current.add(Number(groupId))
    try {
      const response = await axios.patch(`/api/tasks/${item.taskId}/favorite-groups`, {
        group_ids: [...current],
      })
      const updated = response.data.task
      setTasks(previous => previous.map(task => Number(task.id) === Number(item.taskId)
        ? { ...task, favorite: true, favorite_groups: updated.favorite_groups || [] }
        : task))
      setSelectedOverride(previous => previous && Number(previous.taskId) === Number(item.taskId)
        ? { ...previous, favorite: true, favoriteGroups: updated.favorite_groups || [] }
        : previous)
      await fetchFavoriteGroups()
      const updatedGroupIds = new Set((updated.favorite_groups || []).map(group => Number(group.id)))
      const noLongerMatches = view === 'favorite' && (
        (favoriteGroup === 'ungrouped' && updatedGroupIds.size > 0) ||
        (Number.isInteger(Number(favoriteGroup)) && Number(favoriteGroup) > 0 && !updatedGroupIds.has(Number(favoriteGroup)))
      )
      if (noLongerMatches) {
        setSelectedKey(null)
        setSelectedOverride(null)
      }
      fetchTasks()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务收藏分组更新失败')
    }
  }, [favoriteGroup, fetchFavoriteGroups, fetchTasks, view])

  const deleteTask = useCallback(async item => {
    const permanent = view === 'trash'
    const message = permanent
      ? '彻底删除此任务及其输出文件？此操作无法撤销。'
      : '将此任务移到回收站？输出文件会保留，之后可以恢复。'
    if (!window.confirm(message)) return
    try {
      await axios.delete(`/api/tasks/${item.taskId}`, { params: permanent ? { permanent: true } : {} })
      setTasks(previous => previous.filter(task => Number(task.id) !== Number(item.taskId)))
      setTotal(previous => Math.max(0, previous - 1))
      setSelectedKey(null)
      setSelectedOverride(null)
      setNavigation(EMPTY_NAVIGATION)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务删除失败')
    }
  }, [view])

  const cancelTask = useCallback(async item => {
    if (!item.taskId || !window.confirm('取消这个任务？已开始的上游请求可能仍会完成，但结果不会写入本地任务。')) return
    try {
      const response = await axios.post(`/api/tasks/${item.taskId}/cancel`)
      const updated = response.data.task
      setTasks(previous => previous.map(task => Number(task.id) === Number(item.taskId) ? updated : task))
      setSelectedOverride(previous => previous && Number(previous.taskId) === Number(item.taskId)
        ? { ...previous, ...serverItem(updated), key: previous.key }
        : previous)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务取消失败')
    }
  }, [])

  const retryTask = useCallback(async item => {
    if (!item.taskId) return
    try {
      const response = await axios.post(`/api/tasks/${item.taskId}/retry`)
      const retried = response.data.task
      setTasks(previous => cardSort === 'oldest'
        ? [...previous.filter(task => Number(task.id) !== Number(retried.id)), retried]
        : [retried, ...previous.filter(task => Number(task.id) !== Number(retried.id))])
      setTotal(previous => previous + 1)
      setSelectedKey(null)
      setSelectedOverride(null)
      fetchFavoriteGroups()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务重试失败')
    }
  }, [cardSort, fetchFavoriteGroups])

  const restoreTask = useCallback(async item => {
    if (!item.taskId) return
    try {
      await axios.post(`/api/tasks/${item.taskId}/restore`)
      setTasks(previous => previous.filter(task => Number(task.id) !== Number(item.taskId)))
      setTotal(previous => Math.max(0, previous - 1))
      setSelectedKey(null)
      setSelectedOverride(null)
      setNavigation(EMPTY_NAVIGATION)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务恢复失败')
    }
  }, [])

  const toggleSelectionMode = useCallback(() => {
    if (selectionMode) {
      setSelectedKeys(new Set())
      setSelectionUniverse(new Set())
      setSelectionMode(false)
      return
    }
    setSelectedKey(null)
    setSelectedOverride(null)
    setSelectionMode(true)
  }, [selectionMode])

  const toggleSelection = useCallback(key => {
    setSelectedKeys(previous => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const toggleSelectAll = useCallback(async () => {
    if (allCategorySelected) {
      setSelectedKeys(new Set())
      setSelectionUniverse(new Set())
      return
    }
    setSelectingAll(true)
    try {
      const response = await axios.get('/api/tasks/selection', {
        params: buildSelectionParams(),
      })
      const next = new Set((response.data.ids || []).map(taskId => `task-${taskId}`))
      setSelectionUniverse(new Set(next))
      setSelectedKeys(next)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '全选任务失败')
    } finally {
      setSelectingAll(false)
    }
  }, [allCategorySelected, buildSelectionParams])

  const deleteSelected = useCallback(async () => {
    if (!selectedKeys.size) return
    const taskIds = [...selectedKeys]
      .filter(token => token.startsWith('task-'))
      .map(token => Number(token.slice(5)))
      .filter(Number.isInteger)
    const label = `${selectedKeys.size} 个任务卡片`
    const permanent = view === 'trash'
    const prompt = permanent
      ? `彻底删除选中的 ${label} 及其输出文件？此操作无法撤销。`
      : `将选中的 ${label} 移到回收站？输出文件会保留。`
    if (!window.confirm(prompt)) return

    try {
      let deletedCount = 0
      const removedTaskIds = new Set()
      for (let offset = 0; offset < taskIds.length; offset += 250) {
        const response = await axios.post('/api/tasks/bulk-delete', {
          ids: taskIds.slice(offset, offset + 250),
          permanent,
        })
        deletedCount += Number(response.data.deleted) || 0
        ;[...(response.data.deleted_ids || []), ...(response.data.missing_ids || [])]
          .forEach(taskId => removedTaskIds.add(Number(taskId)))
      }
      setTasks(previous => previous.filter(task => !removedTaskIds.has(Number(task.id))))
      setTotal(previous => Math.max(0, previous - deletedCount))
      setSelectedKeys(new Set())
      setSelectionUniverse(new Set())
      setSelectionMode(false)
      fetchFavoriteGroups()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '批量删除失败')
    }
  }, [fetchFavoriteGroups, selectedKeys, view])

  const restoreSelected = useCallback(async () => {
    const taskIds = [...selectedKeys]
      .filter(token => token.startsWith('task-'))
      .map(token => Number(token.slice(5)))
      .filter(Number.isInteger)
    if (!taskIds.length) return
    try {
      const restored = new Set()
      for (let offset = 0; offset < taskIds.length; offset += 250) {
        const response = await axios.post('/api/tasks/bulk-restore', { ids: taskIds.slice(offset, offset + 250) })
        ;(response.data.restored_ids || []).forEach(taskId => restored.add(Number(taskId)))
      }
      setTasks(previous => previous.filter(task => !restored.has(Number(task.id))))
      setTotal(previous => Math.max(0, previous - restored.size))
      setSelectedKeys(new Set())
      setSelectionUniverse(new Set())
      setSelectionMode(false)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '批量恢复失败')
    }
  }, [selectedKeys])

  const downloadSelected = useCallback(async () => {
    const taskIds = [...selectedKeys]
      .filter(token => token.startsWith('task-'))
      .map(token => Number(token.slice(5)))
      .filter(Number.isInteger)
    if (!taskIds.length) return
    try {
      const response = await axios.post('/api/tasks/bulk-download', { ids: taskIds }, { responseType: 'blob' })
      const disposition = response.headers['content-disposition'] || ''
      const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
      const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1]
      const timestamp = new Date().toISOString().replace(/\D/g, '').slice(0, 14)
      const filename = encodedName ? decodeURIComponent(encodedName) : (plainName || `ink-traces-tasks-${timestamp}.zip`)
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '批量下载失败')
    }
  }, [selectedKeys])

  const addSelectedToGroup = useCallback(async groupId => {
    const taskIds = [...selectedKeys]
      .filter(token => token.startsWith('task-'))
      .map(token => Number(token.slice(5)))
      .filter(Number.isInteger)
    if (!taskIds.length) return
    try {
      for (let offset = 0; offset < taskIds.length; offset += 250) {
        await axios.post('/api/tasks/bulk-favorite-groups', {
          ids: taskIds.slice(offset, offset + 250),
          group_ids: [groupId],
          mode: 'add',
        })
      }
      setBulkGroupMenuOpen(false)
      await fetchFavoriteGroups()
      fetchTasks()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '批量收藏分组失败')
    }
  }, [fetchFavoriteGroups, fetchTasks, selectedKeys])

  const changeView = useCallback(nextView => {
    if (nextView === view) return
    setTasks([])
    setTotal(0)
    setView(nextView)
    if (nextView !== 'favorite') setFavoriteGroup('all')
  }, [view])

  return (
    <div
      className="task-gallery relative z-10 flex min-h-0 flex-1 flex-col overflow-hidden"
      data-card-size={cardSize}
      data-card-details={cardDetails}
    >
      <div className="task-gallery-toolbar liquid-glass flex h-12 shrink-0 items-center gap-2 px-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-nexus-text-light">
          {mode === 'image' ? <ImageIcon size={15} className="text-nexus-blue" /> : <Film size={15} className="text-nexus-violet" />}
          任务
          <span className="font-mono text-[10px] font-normal text-nexus-muted">{categoryTotal}</span>
        </div>
        {selectionMode ? (
          <div data-testid="selection-summary" className="ml-3 font-mono text-xs text-nexus-text">
            已选 <span className="text-nexus-green">{selectedKeys.size}</span>
            <span className="ml-2 text-[10px] text-nexus-muted">共 {categoryTotal}</span>
          </div>
        ) : (
          <div className="ml-3 flex items-center gap-1" role="group" aria-label="任务视图">
            <button type="button" aria-pressed={view === 'all'} onClick={() => changeView('all')} className={`task-view-button ${view === 'all' ? 'task-view-button-active' : ''}`}>全部</button>
            <button type="button" aria-pressed={view === 'favorite'} onClick={() => changeView('favorite')} className={`task-view-button ${view === 'favorite' ? 'task-view-button-active' : ''}`}><Heart size={12} /> 收藏</button>
            <button type="button" aria-pressed={view === 'active'} onClick={() => changeView('active')} className={`task-view-button ${view === 'active' ? 'task-view-button-active' : ''}`}><LoaderCircle size={12} /> 进行中</button>
            <button type="button" aria-pressed={view === 'trash'} onClick={() => changeView('trash')} className={`task-view-button ${view === 'trash' ? 'task-view-button-active' : ''}`}><Trash2 size={12} /> 回收站</button>
          </div>
        )}
        {!selectionMode && view === 'favorite' && (
          <div ref={groupMenuRef} className="relative">
            <button
              type="button"
              aria-label="筛选收藏分组"
              aria-haspopup="menu"
              aria-expanded={groupMenuOpen}
              onClick={() => setGroupMenuOpen(open => !open)}
              className="favorite-group-filter"
            >
              <FolderHeart size={13} />
              <span className="max-w-24 truncate">{favoriteGroupLabel}</span>
              <ChevronRight size={12} className={`transition-transform ${groupMenuOpen ? 'rotate-90' : ''}`} />
            </button>
            <AnimatePresence>
              {groupMenuOpen && (
                <motion.div
                  role="menu"
                  aria-label="收藏分组"
                  className="task-group-menu absolute left-0 top-[calc(100%+8px)] z-50 w-64 p-2"
                  initial={{ opacity: 0, y: -5, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.98 }}
                >
                  <button type="button" role="menuitemradio" aria-checked={favoriteGroup === 'all'} onClick={() => { setFavoriteGroup('all'); setGroupMenuOpen(false) }} className="task-group-option">
                    <span className="task-layout-check">{favoriteGroup === 'all' && <Check size={12} />}</span>
                    <span className="truncate">全部收藏</span>
                  </button>
                  <button type="button" role="menuitemradio" aria-checked={favoriteGroup === 'ungrouped'} onClick={() => { setFavoriteGroup('ungrouped'); setGroupMenuOpen(false) }} className="task-group-option">
                    <span className="task-layout-check">{favoriteGroup === 'ungrouped' && <Check size={12} />}</span>
                    <span className="truncate">未分组</span>
                  </button>
                  {favoriteGroups.length > 0 && <div className="task-layout-divider" />}
                  <div className="custom-scrollbar max-h-56 overflow-y-auto">
                    {favoriteGroups.map(group => (
                      <div key={group.id} className="task-group-row">
                        {editingGroupId === group.id ? (
                          <form className="flex min-w-0 flex-1 items-center gap-1" onSubmit={event => { event.preventDefault(); saveFavoriteGroup(group.id) }}>
                            <input
                              value={editingGroupName}
                              onChange={event => setEditingGroupName(event.target.value)}
                              aria-label={`重命名分组 ${group.name}`}
                              autoFocus
                              maxLength={40}
                              className="task-group-input min-w-0 flex-1"
                            />
                            <IconButton label="保存分组名称" type="submit" className="size-7"><Check size={12} /></IconButton>
                          </form>
                        ) : (
                          <>
                            <button
                              type="button"
                              role="menuitemradio"
                              aria-checked={Number(favoriteGroup) === Number(group.id)}
                              onClick={() => { setFavoriteGroup(group.id); setGroupMenuOpen(false) }}
                              className="task-group-row-main"
                            >
                              <span className="favorite-group-dot" data-color={group.color} />
                              <span className="min-w-0 flex-1 truncate">{group.name}</span>
                              <span className="font-mono text-[9px] text-nexus-muted">{group.task_count || 0}</span>
                            </button>
                            <IconButton label={`重命名分组 ${group.name}`} onClick={() => { setEditingGroupId(group.id); setEditingGroupName(group.name) }} className="size-7"><Pencil size={11} /></IconButton>
                            <IconButton label={`删除分组 ${group.name}`} onClick={() => removeFavoriteGroup(group)} className="size-7 hover:text-nexus-red"><Trash2 size={11} /></IconButton>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="task-layout-divider" />
                  <div className="favorite-group-swatches" role="radiogroup" aria-label="新分组颜色">
                    {GROUP_COLORS.map(color => (
                      <button
                        key={color}
                        type="button"
                        role="radio"
                        aria-label={`${color} 分组颜色`}
                        aria-checked={newGroupColor === color}
                        onClick={() => setNewGroupColor(color)}
                        className="favorite-group-swatch"
                        data-color={color}
                      >
                        {newGroupColor === color && <Check size={10} />}
                      </button>
                    ))}
                  </div>
                  <form onSubmit={createFavoriteGroup} className="flex items-center gap-1.5 p-1">
                    <input value={newGroupName} onChange={event => setNewGroupName(event.target.value)} maxLength={40} aria-label="新收藏分组名称" placeholder="新分组" className="task-group-input min-w-0 flex-1" />
                    <IconButton label="创建收藏分组" type="submit" disabled={!newGroupName.trim()} className="size-8"><FolderPlus size={13} /></IconButton>
                  </form>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
        {!selectionMode && (
          <div className="relative ml-auto w-44">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-nexus-muted" />
            <input value={query} onChange={event => setQuery(event.target.value)} aria-label="搜索任务画廊" placeholder="搜索任务" className="glass-input h-8 w-full pl-8 pr-2 text-xs outline-none" />
          </div>
        )}
        <div ref={layoutMenuRef} className={`relative ${selectionMode ? 'ml-auto' : ''}`}>
          <IconButton
            label="任务卡片布局"
            aria-haspopup="menu"
            aria-expanded={layoutMenuOpen}
            onClick={() => setLayoutMenuOpen(open => !open)}
            className={layoutMenuOpen ? 'text-nexus-green' : ''}
          >
            <LayoutGrid size={15} />
          </IconButton>
          <AnimatePresence>
            {layoutMenuOpen && (
              <motion.div
                role="menu"
                aria-label="任务卡片布局设置"
                className="task-layout-menu absolute right-0 top-[calc(100%+8px)] z-50 w-48 p-2"
                initial={{ opacity: 0, y: -5, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -4, scale: 0.98 }}
              >
                <div className="task-layout-heading">Card size</div>
                {CARD_SIZE_OPTIONS.map(option => (
                  <button
                    key={option.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={cardSize === option.value}
                    onClick={() => updateGalleryPreference('cardSize', option.value)}
                    className="task-layout-option"
                  >
                    <span className="task-layout-check">{cardSize === option.value && <Check size={12} />}</span>
                    {option.label}
                  </button>
                ))}
                <div className="task-layout-divider" />
                <div className="task-layout-heading">Card details</div>
                {CARD_DETAIL_OPTIONS.map(option => (
                  <button
                    key={option.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={cardDetails === option.value}
                    onClick={() => updateGalleryPreference('cardDetails', option.value)}
                    className="task-layout-option"
                  >
                    <span className="task-layout-check">{cardDetails === option.value && <Check size={12} />}</span>
                    {option.label}
                  </button>
                ))}
                <div className="task-layout-divider" />
                <div className="task-layout-heading flex items-center gap-1.5"><SortDesc size={11} /> Sort by</div>
                {SORT_OPTIONS.map(option => (
                  <button
                    key={option.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={cardSort === option.value}
                    onClick={() => updateGalleryPreference('sort', option.value)}
                    className="task-layout-option"
                  >
                    <span className="task-layout-check">{cardSort === option.value && <Check size={12} />}</span>
                    {option.label}
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <IconButton
          label={selectionMode ? '退出批量选择' : '批量选择任务'}
          aria-pressed={selectionMode}
          onClick={toggleSelectionMode}
          className={selectionMode ? 'text-nexus-green' : ''}
        >
          {selectionMode ? <X size={15} /> : <ListChecks size={15} />}
        </IconButton>
        {selectionMode ? (
          <>
            <IconButton
              label={allCategorySelected ? '取消全选' : '全选当前分类'}
              onClick={toggleSelectAll}
              disabled={selectingAll || categoryTotal === 0}
              className={allCategorySelected ? 'text-nexus-green' : ''}
            >
              <CheckCheck size={15} className={selectingAll ? 'animate-pulse' : ''} />
            </IconButton>
            <IconButton
              label="下载已选任务结果"
              onClick={downloadSelected}
              disabled={selectedTaskCount === 0}
            >
              <Download size={15} />
            </IconButton>
            {view !== 'trash' && favoriteGroups.length > 0 && (
              <div ref={bulkGroupMenuRef} className="relative">
                <IconButton
                  label="将已选任务加入收藏分组"
                  aria-haspopup="menu"
                  aria-expanded={bulkGroupMenuOpen}
                  onClick={() => setBulkGroupMenuOpen(open => !open)}
                  disabled={selectedTaskCount === 0}
                  className={bulkGroupMenuOpen ? 'text-nexus-cyan' : ''}
                >
                  <FolderHeart size={15} />
                </IconButton>
                <AnimatePresence>
                  {bulkGroupMenuOpen && (
                    <motion.div
                      role="menu"
                      aria-label="批量加入收藏分组"
                      className="task-group-menu absolute right-0 top-[calc(100%+8px)] z-50 w-52 p-2"
                      initial={{ opacity: 0, y: -5, scale: 0.98 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: -4, scale: 0.98 }}
                    >
                      <div className="task-layout-heading">加入分组</div>
                      {favoriteGroups.map(group => (
                        <button key={group.id} type="button" role="menuitem" onClick={() => addSelectedToGroup(group.id)} className="task-group-option">
                          <span className="favorite-group-dot" data-color={group.color} />
                          <span className="truncate">{group.name}</span>
                        </button>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}
            {view === 'trash' && (
              <IconButton label="恢复已选任务" onClick={restoreSelected} disabled={selectedTaskCount === 0}>
                <ArchiveRestore size={15} />
              </IconButton>
            )}
            <IconButton
              label={view === 'trash' ? '彻底删除已选任务' : '将已选任务移到回收站'}
              onClick={deleteSelected}
              disabled={!selectedKeys.size}
              className="hover:text-nexus-red"
            >
              <Trash2 size={15} />
            </IconButton>
          </>
        ) : (
          <IconButton label="刷新任务" onClick={() => fetchTasks()}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /></IconButton>
        )}
      </div>

      <div className="custom-scrollbar flex-1 overflow-y-auto p-3">
        {error && (
          <div role="alert" className="mb-3 flex min-h-9 items-center gap-2 rounded border border-nexus-red/25 bg-nexus-red/10 px-3 text-xs text-nexus-red">
            <AlertTriangle size={13} /> {error}
          </div>
        )}
        <div className="task-gallery-grid">
          {visibleItems.map(item => (
            <TaskCard
              key={item.key}
              item={item}
              detailed={cardDetails === 'detailed'}
              selectionMode={selectionMode}
              checked={selectedKeys.has(selectionToken(item))}
              selectionTokenValue={selectionToken(item)}
              onOpen={openItem}
              onToggleSelection={toggleSelection}
              onFavorite={toggleFavorite}
              onCancel={cancelTask}
              trash={view === 'trash'}
            />
          ))}
        </div>
        {visibleItems.length === 0 && (
          <div className="py-20 text-center text-sm text-nexus-muted">没有符合条件的任务</div>
        )}
        {!selectionMode && tasks.length < total && (
          <button
            type="button"
            disabled={loading}
            onClick={() => fetchTasks({ append: true, offset: tasks.length })}
            className="btn-base btn-outline mx-auto mt-3 flex min-w-40 text-xs"
          >
            {loading ? '加载中' : `加载更多 (${tasks.length}/${total})`}
          </button>
        )}
      </div>

      <AnimatePresence>
        {selectedItem && (
          <TaskDetailModal
            item={selectedItem}
            position={selectedPosition}
            total={selectedTotal}
            onPrevious={() => navigate(-1)}
            onNext={() => navigate(1)}
            onClose={() => { setSelectedKey(null); setSelectedOverride(null) }}
            onFavorite={toggleFavorite}
            onDelete={deleteTask}
            onReuse={onReuseTask}
            onCancel={cancelTask}
            onRetry={retryTask}
            onRestore={restoreTask}
            onSetGroup={toggleItemGroup}
            favoriteGroups={favoriteGroups}
            trash={view === 'trash'}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
