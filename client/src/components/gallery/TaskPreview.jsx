import { AlertTriangle, AudioLines, CircleHelp, Film, Image as ImageIcon } from 'lucide-react'
import CodeRainCanvas from '../CodeRainCanvas'
import { ACTIVE_STATUSES, STATUS } from './taskModel.js'

export function TaskTypeIcon({ type, size = 15 }) {
  if (type === 'video') return <Film size={size} className="text-nexus-violet" />
  if (type === 'audio') return <AudioLines size={size} className="text-nexus-cyan" />
  return <ImageIcon size={size} className="text-nexus-blue" />
}

export function AudioArtwork({ compact = false }) {
  const bars = compact ? 18 : 36
  return (
    <div className="audio-task-artwork absolute inset-0 flex flex-col items-center justify-center gap-4 px-7">
      <AudioLines size={compact ? 26 : 38} className="text-nexus-cyan" strokeWidth={1.4} />
      <div className="audio-task-waveform" aria-hidden="true">
        {Array.from({ length: bars }, (_, index) => <span key={index} style={{ '--wave-index': index }} />)}
      </div>
    </div>
  )
}

export function TaskPreview({ item, compact = true }) {
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
  if (item.type === 'audio' && item.audio) return <AudioArtwork compact={compact} />
  if (item.images?.length) {
    return <img src={item.thumbnail || item.images[0]} loading="lazy" decoding="async" className="absolute inset-0 size-full object-contain" alt="图片任务预览" />
  }
  if (item.status === 'failed') {
    return (
      <div className={`absolute inset-0 flex flex-col items-center justify-center gap-3 p-5 text-center ${item.resultUnknown ? 'text-nexus-amber' : 'text-nexus-red'}`}>
        {item.resultUnknown ? <CircleHelp size={28} /> : <AlertTriangle size={28} />}
        {item.resultUnknown && <strong className="text-xs">结果未知，可能已计费</strong>}
        <span className="line-clamp-3 break-all text-xs leading-5">{item.error || '任务执行失败'}</span>
      </div>
    )
  }
  const EmptyIcon = item.type === 'video' ? Film : item.type === 'audio' ? AudioLines : ImageIcon
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-nexus-muted">
      <EmptyIcon size={30} strokeWidth={1.25} />
      <span className="text-xs">暂无结果</span>
    </div>
  )
}
