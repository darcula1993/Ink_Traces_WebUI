import React, { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import {
  CheckCircle2,
  Clock3,
  Download,
  Film,
  Image as ImageIcon,
  LoaderCircle,
  RefreshCw,
  Search,
  Trash2,
  XCircle,
} from 'lucide-react'

const STATUS_MAP = {
  succeeded: { icon: CheckCircle2, tone: 'text-nexus-green border-nexus-green/25 bg-nexus-green/10', label: '完成' },
  failed: { icon: XCircle, tone: 'text-nexus-red border-nexus-red/25 bg-nexus-red/10', label: '失败' },
  processing: { icon: LoaderCircle, tone: 'text-nexus-blue border-nexus-blue/25 bg-nexus-blue/10', label: '生成中', spin: true },
  preparing: { icon: LoaderCircle, tone: 'text-nexus-cyan border-nexus-cyan/25 bg-nexus-cyan/10', label: '准备中', spin: true },
  pending: { icon: Clock3, tone: 'text-nexus-amber border-nexus-amber/25 bg-nexus-amber/10', label: '排队中' },
}

const FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'image', label: '图片' },
  { value: 'video', label: '视频' },
]

function TaskHistory({ onLoadTask }) {
  const [tasks, setTasks] = useState([])
  const [total, setTotal] = useState(0)
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)

  const fetchTasks = useCallback(async ({ append = false, offset = 0 } = {}) => {
    setLoading(true)
    try {
      const params = { limit: 30, offset }
      if (filter !== 'all') params.type = filter
      const response = await axios.get('/api/tasks', { params })
      if (response.data.success) {
        setTasks(previous => append ? [...previous, ...response.data.tasks] : response.data.tasks)
        setTotal(response.data.total)
      }
    } catch (error) {
      console.error('Failed to fetch tasks', error)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { fetchTasks() }, [fetchTasks])

  useEffect(() => {
    const hasActive = tasks.some(task => ['processing', 'preparing', 'pending'].includes(task.status))
    if (!hasActive) return undefined
    const timer = window.setInterval(() => fetchTasks(), 5000)
    return () => window.clearInterval(timer)
  }, [tasks, fetchTasks])

  const visibleTasks = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return tasks
    return tasks.filter(task =>
      String(task.id).includes(needle) ||
      String(task.prompt || '').toLowerCase().includes(needle) ||
      String(task.provider || '').toLowerCase().includes(needle)
    )
  }, [tasks, query])

  const deleteTask = async (id) => {
    if (!window.confirm('删除此任务及其输出文件？')) return
    try {
      await axios.delete(`/api/tasks/${id}`)
    } catch (error) {
      console.error('Failed to delete task', error)
    }
    fetchTasks()
  }

  const clearAll = async () => {
    if (!window.confirm(`清空全部 ${total} 个任务？此操作不可撤销。`)) return
    try {
      await axios.delete('/api/tasks/clear')
      fetchTasks()
    } catch (error) {
      window.alert('清空失败')
    }
  }

  const formatTime = (iso) => {
    if (!iso) return ''
    return new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(new Date(iso))
  }

  return (
    <div className="drawer-content flex h-full flex-col">
      <div className="shrink-0 space-y-3 border-b border-nexus-border p-3">
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-nexus-muted" />
          <input
            value={query}
            onChange={event => setQuery(event.target.value)}
            aria-label="搜索任务"
            placeholder="搜索提示词或任务编号"
            className="h-9 w-full rounded-md border border-nexus-border bg-nexus-bg pl-9 pr-3 text-sm text-nexus-text-light outline-none placeholder:text-nexus-muted focus:border-nexus-blue"
          />
        </div>
        <div className="flex items-center gap-1" role="group" aria-label="任务类型">
          {FILTERS.map(item => (
            <button
              key={item.value}
              type="button"
              aria-pressed={filter === item.value}
              onClick={() => setFilter(item.value)}
              className={`min-h-8 rounded px-3 text-xs font-medium transition-colors ${filter === item.value ? 'bg-nexus-surface-hover text-nexus-text-light' : 'text-nexus-text hover:bg-nexus-surface'}`}
            >
              {item.label}
            </button>
          ))}
          <button type="button" aria-label="刷新任务" title="刷新" onClick={() => fetchTasks()} className="icon-button ml-auto size-8">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-3 custom-scrollbar">
        {visibleTasks.length === 0 && !loading && (
          <div className="py-12 text-center text-sm text-nexus-muted">{query ? '没有匹配的任务' : '暂无生成任务'}</div>
        )}

        {visibleTasks.map(task => {
          const status = STATUS_MAP[task.status] || STATUS_MAP.pending
          const StatusIcon = status.icon
          const isVideo = task.type === 'video'
          const result = task.result || {}
          const localVideo = result.local_video
          const videoPreview = result.local_last_frame
          const localImages = Array.isArray(result.local_images) ? result.local_images : []
          const firstDownload = isVideo ? localVideo : localImages[0]

          return (
            <article
              key={task.id}
              role="button"
              tabIndex={0}
              aria-label={`打开${isVideo ? '视频' : '图片'}任务 ${task.id}`}
              onClick={() => onLoadTask?.(task)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onLoadTask?.(task)
                }
              }}
              className="group overflow-hidden rounded-md border border-nexus-border bg-nexus-surface/55 transition-colors hover:border-nexus-border-hover hover:bg-nexus-surface focus-visible:outline-2 focus-visible:outline-nexus-blue"
            >
              <div className="flex items-center gap-2 border-b border-nexus-border/70 px-3 py-2">
                {isVideo ? <Film size={14} className="shrink-0 text-nexus-violet" /> : <ImageIcon size={14} className="shrink-0 text-nexus-blue" />}
                <span className="font-mono text-xs text-nexus-text-light">#{task.id}</span>
                <span className={`status-pill min-h-5 px-1.5 text-[11px] ${status.tone}`}>
                  <StatusIcon size={11} className={status.spin ? 'animate-spin' : ''} />{status.label}
                </span>
                <time className="ml-auto text-[11px] text-nexus-muted">{formatTime(task.created_at)}</time>
              </div>

              <div className="px-3 py-2.5">
                <p className="line-clamp-2 text-sm leading-5 text-nexus-text-light">{task.prompt || '未填写提示词'}</p>
                {task.provider && <p className="mt-1 font-mono text-[10px] uppercase text-nexus-muted">{task.provider}</p>}
              </div>

              {task.status === 'succeeded' && (videoPreview || localVideo || localImages.length > 0) && (
                <div className="px-3 pb-2.5">
                  {isVideo && (videoPreview || localVideo) && (
                    videoPreview
                      ? <img src={videoPreview} loading="lazy" className="h-28 w-full rounded object-cover" alt="视频任务预览" />
                      : <video src={localVideo} className="h-28 w-full rounded object-cover" muted preload="metadata" />
                  )}
                  {!isVideo && localImages.length > 0 && (
                    <div className="flex gap-1.5 overflow-x-auto">
                      {localImages.slice(0, 3).map((url, index) => (
                        <img key={url} src={url} loading="lazy" className="h-16 w-16 shrink-0 rounded object-cover" alt={`图片结果 ${index + 1}`} />
                      ))}
                    </div>
                  )}
                </div>
              )}

              {Number(task.progress) > 0 && task.status !== 'succeeded' && (
                <div className="mx-3 mb-2.5 h-1 overflow-hidden rounded-full bg-nexus-bg">
                  <div className="h-full rounded-full bg-nexus-blue" style={{ width: `${Math.min(100, task.progress)}%` }} />
                </div>
              )}

              {task.status === 'failed' && task.error && (
                <p className="mx-3 mb-2.5 line-clamp-2 text-xs leading-5 text-nexus-red">{task.error}</p>
              )}

              <div className="flex items-center justify-end gap-1 border-t border-nexus-border/70 px-2 py-1.5">
                {firstDownload && (
                  <a
                    href={firstDownload}
                    download
                    aria-label="下载任务结果"
                    title="下载结果"
                    onClick={event => event.stopPropagation()}
                    onKeyDown={event => event.stopPropagation()}
                    className="icon-button size-8"
                  >
                    <Download size={14} />
                  </a>
                )}
                <button
                  type="button"
                  aria-label="删除任务"
                  title="删除任务"
                  onClick={event => { event.stopPropagation(); deleteTask(task.id) }}
                  className="icon-button size-8 hover:text-nexus-red"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </article>
          )
        })}

        {tasks.length < total && !query && (
          <button
            type="button"
            disabled={loading}
            onClick={() => fetchTasks({ append: true, offset: tasks.length })}
            className="btn-base btn-outline w-full text-xs"
          >
            {loading ? '加载中' : `加载更多 (${tasks.length}/${total})`}
          </button>
        )}
      </div>

      <div className="flex shrink-0 items-center justify-between border-t border-nexus-border px-3 py-2">
        <span className="text-xs text-nexus-muted">共 {total} 个任务</span>
        {total > 0 && <button type="button" onClick={clearAll} className="text-xs text-nexus-muted hover:text-nexus-red">清空全部</button>}
      </div>
    </div>
  )
}

export default TaskHistory
