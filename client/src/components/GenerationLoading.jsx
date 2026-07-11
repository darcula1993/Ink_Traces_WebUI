import React, { useEffect, useState } from 'react'
import { Braces, Clock3 } from 'lucide-react'
import CodeRainCanvas from './CodeRainCanvas'

const STATUS_COPY = {
  submitting: { label: '正在提交', code: 'SUBMITTING', color: 'text-nexus-blue' },
  pending: { label: '等待调度', code: 'QUEUED', color: 'text-nexus-amber' },
  preparing: { label: '准备素材', code: 'PREPARING', color: 'text-nexus-cyan' },
  processing: { label: '正在生成', code: 'PROCESSING', color: 'text-nexus-green' },
}

function formatElapsed(seconds) {
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

export default function GenerationLoading({ type = 'image', status = 'processing', progress = 0, taskId, provider }) {
  const [elapsed, setElapsed] = useState(0)
  const copy = STATUS_COPY[status] || STATUS_COPY.processing
  const hasProgress = Number(progress) > 0

  useEffect(() => {
    const timer = window.setInterval(() => setElapsed(value => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <div className="relative flex size-full min-h-[280px] items-center justify-center overflow-hidden bg-[#050706]">
      <CodeRainCanvas status={status} />
      <div className="absolute inset-0 bg-black/10" aria-hidden="true" />

      <div className="relative z-10 flex w-[min(360px,82%)] flex-col items-center text-center drop-shadow-[0_2px_8px_rgba(0,0,0,0.95)]" role="status" aria-live="polite">
        <div className="liquid-loader-badge mb-5 flex size-11 items-center justify-center text-nexus-green">
          <Braces size={20} />
        </div>
        <div className={`text-base font-semibold ${copy.color}`}>{copy.label}</div>
        <div className="mt-1 font-mono text-xs text-nexus-text">
          {copy.code} // {type === 'video' ? 'VIDEO' : 'IMAGE'}{taskId ? `_${String(taskId).padStart(4, '0')}` : ''}
        </div>

        <div className="liquid-progress-track mt-6 h-1.5 w-full overflow-hidden rounded-full">
          {hasProgress ? (
            <div className="h-full rounded-full bg-nexus-green transition-[width] duration-500" style={{ width: `${Math.min(100, progress)}%` }} />
          ) : (
            <div className="code-loading-block h-full w-[28%] rounded-full bg-nexus-green" />
          )}
        </div>

        <div className="mt-3 flex items-center gap-3 text-xs text-nexus-text">
          {provider && <span className="font-mono uppercase">{provider}</span>}
          <span className="inline-flex items-center gap-1.5"><Clock3 size={12} />{formatElapsed(elapsed)}</span>
          {hasProgress && <span className="font-mono text-nexus-text-light">{Math.round(progress)}%</span>}
        </div>
      </div>
    </div>
  )
}
