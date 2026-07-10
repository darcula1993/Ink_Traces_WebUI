import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { Trash2, Film, Cpu, Clock, CheckCircle, XCircle, Loader, RefreshCw, Download } from 'lucide-react'

const STATUS_MAP = {
  succeeded: { icon: CheckCircle, color: 'text-nexus-green', label: 'Done' },
  failed: { icon: XCircle, color: 'text-red-400', label: 'Failed' },
  processing: { icon: Loader, color: 'text-yellow-400', label: 'Running', spin: true },
  pending: { icon: Clock, color: 'text-nexus-text', label: 'Queued' }
}

function TaskHistory({ onLoadTask }) {
  const [tasks, setTasks] = useState([])
  const [total, setTotal] = useState(0)
  const [filter, setFilter] = useState('all') // all | image | video
  const [loading, setLoading] = useState(false)

  const fetchTasks = useCallback(async () => {
    setLoading(true)
    try {
      const params = { limit: 20 }
      if (filter !== 'all') params.type = filter
      const resp = await axios.get('/api/tasks', { params })
      if (resp.data.success) {
        setTasks(resp.data.tasks)
        setTotal(resp.data.total)
      }
    } catch (e) { console.error('Failed to fetch tasks', e) }
    finally { setLoading(false) }
  }, [filter])

  useEffect(() => { fetchTasks() }, [fetchTasks])

  // Auto-refresh every 5s if any task is processing
  useEffect(() => {
    const hasActive = tasks.some(t => t.status === 'processing' || t.status === 'pending')
    if (!hasActive) return
    const timer = setInterval(fetchTasks, 5000)
    return () => clearInterval(timer)
  }, [tasks, fetchTasks])

  const deleteTask = async (id) => {
    if (!confirm('删除此任务及其输出文件？')) return
    try {
      await axios.delete(`/api/tasks/${id}`)
    } catch (e) { /* ignore 404 */ }
    fetchTasks()
  }

  const clearAll = async () => {
    if (!confirm(`清空全部 ${total} 个任务？此操作不可撤销。`)) return
    try {
      await axios.delete('/api/tasks/clear')
      fetchTasks()
    } catch (e) { alert('清空失败') }
  }

  const formatTime = (iso) => {
    if (!iso) return ''
    const d = new Date(iso)
    return `${(d.getMonth()+1).toString().padStart(2,'0')}/${d.getDate().toString().padStart(2,'0')} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`
  }

  return (
    <div className="flex flex-col h-full">
      {/* Filter bar */}
      <div className="flex gap-1 px-3 pt-3 pb-2 shrink-0">
        {['all', 'image', 'video'].map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-2 py-1 text-[10px] font-mono tracking-widest uppercase rounded transition-colors ${filter === f ? 'bg-nexus-green/10 text-nexus-green border border-nexus-green/30' : 'text-nexus-text hover:text-white'}`}>
            {f}
          </button>
        ))}
        <button onClick={fetchTasks} className="ml-auto text-nexus-text hover:text-nexus-green transition-colors p-1">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-2 custom-scrollbar">
        {tasks.length === 0 && !loading && (
          <div className="text-center text-nexus-text/50 text-xs font-mono py-8">No tasks yet</div>
        )}
        {tasks.map(task => {
          const st = STATUS_MAP[task.status] || STATUS_MAP.pending
          const Icon = st.icon
          const isVideo = task.type === 'video'
          const result = task.result || {}
          const hasLocalVideo = result.local_video
          const videoPreviewImage = result.local_last_frame
          const hasLocalImages = result.local_images && result.local_images.length > 0

          return (
            <div key={task.id} className="border border-nexus-border bg-[#111] hover:border-nexus-green/30 transition-colors group cursor-pointer"
              onClick={() => onLoadTask && onLoadTask(task)}>
              {/* Header */}
              <div className="flex items-center gap-2 px-3 py-2 border-b border-nexus-border/50">
                {isVideo ? <Film size={11} className="text-nexus-text shrink-0" /> : <Cpu size={11} className="text-nexus-text shrink-0" />}
                <span className="text-[10px] font-mono text-nexus-text tracking-wider uppercase">{task.type} #{task.id}</span>
                <Icon size={11} className={`${st.color} shrink-0 ${st.spin ? 'animate-spin' : ''}`} />
                <span className={`text-[10px] font-mono ${st.color}`}>{st.label}</span>
                <span className="text-[9px] font-mono text-nexus-text/40 ml-auto">{formatTime(task.created_at)}</span>
              </div>

              {/* Prompt preview */}
              <div className="px-3 py-2">
                <p className="text-xs font-mono text-nexus-text-light line-clamp-2 leading-relaxed">
                  {task.prompt || '(no prompt)'}
                </p>
              </div>

              {/* Result preview */}
              {task.status === 'succeeded' && (
                <div className="px-3 pb-2">
                  {isVideo && (videoPreviewImage || hasLocalVideo) && (
                    videoPreviewImage ? (
                      <img src={videoPreviewImage} loading="lazy" className="w-full h-24 object-cover rounded border border-nexus-border" alt="" />
                    ) : (
                      <video src={result.local_video} className="w-full h-24 object-cover rounded border border-nexus-border" muted preload="none" />
                    )
                  )}
                  {!isVideo && hasLocalImages && (
                    <div className="flex gap-1 overflow-x-auto">
                      {result.local_images.slice(0, 2).map((url, i) => (
                        <img key={i} src={url} loading="lazy" className="h-16 w-16 object-cover rounded border border-nexus-border shrink-0 hover:border-nexus-green transition-colors" alt="" />
                      ))}
                    </div>
                  )}
                </div>
              )}
              {task.status === 'failed' && task.error && (
                <div className="px-3 pb-2">
                  <p className="text-[10px] font-mono text-red-400/70 line-clamp-1">{task.error}</p>
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center justify-end gap-2 px-3 py-1.5 border-t border-nexus-border/30 opacity-0 group-hover:opacity-100 transition-opacity">
                {hasLocalVideo && (
                  <a href={result.local_video} download onClick={e => e.stopPropagation()} className="text-nexus-text hover:text-nexus-green transition-colors">
                    <Download size={11} />
                  </a>
                )}
                <button onClick={e => { e.stopPropagation(); deleteTask(task.id) }} className="text-nexus-text hover:text-red-400 transition-colors">
                  <Trash2 size={11} />
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Footer */}
      <div className="px-3 py-2 border-t border-nexus-border flex items-center justify-between shrink-0">
        <span className="text-[10px] font-mono text-nexus-text/40 tracking-widest">TASKS // {total}</span>
        {total > 0 && (
          <button onClick={clearAll} className="text-[10px] font-mono text-nexus-text/40 hover:text-red-400 transition-colors tracking-widest">
            CLEAR ALL
          </button>
        )}
      </div>
    </div>
  )
}

export default TaskHistory
