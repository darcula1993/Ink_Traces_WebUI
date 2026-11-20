import React, { useState } from 'react'
import { AlertTriangle, AudioLines, CircleHelp, Film, Image as ImageIcon, Layers3, LayoutList } from 'lucide-react'
import CodeRainCanvas from '../CodeRainCanvas'
import AudioWaveformArt from '../art/AudioWaveformArt'
import { TaskPlaceholderArt } from '../art/ShellEmptyArt'
import { ACTIVE_STATUSES, STATUS } from './taskModel.js'

export function TaskTypeIcon({ type, size = 15 }) {
  if (type === 'all') return <LayoutList size={size} className="text-nexus-text-light" />
  if (type === 'video') return <Film size={size} className="text-[var(--kind-video)]" />
  if (type === 'audio') return <AudioLines size={size} className="text-[var(--kind-audio)]" />
  if (type === 'layer') return <Layers3 size={size} className="text-[var(--kind-image)]" />
  return <ImageIcon size={size} className="text-[var(--kind-image)]" />
}

export function AudioArtwork({ compact = false }) {
  return (
    <div className="audio-task-artwork audio-waveform-stage absolute inset-0 flex flex-col items-center justify-center px-5">
      <AudioWaveformArt variant="card" compact={compact} />
    </div>
  )
}

// LIBRARY-GLOBAL-20261116 S4b: the result was deleted from the media library; the task record stays.
export function DeletedResult({ compact = true, label = '结果已删除' }) {
  return (
    <div
      className="task-result-deleted art-hatch-surface absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center text-nexus-muted"
      data-testid="task-result-deleted"
      role="img"
      aria-label={label}
    >
      <TaskPlaceholderArt kind="deleted" compact={compact} />
      <span className="text-xs font-medium text-nexus-text">{label}</span>
      {!compact && <span className="max-w-64 text-xs leading-5">已从素材库删除；任务记录（提示词、参数与时间）仍可查看。</span>}
    </div>
  )
}

// P0-3: when a trashed or unreadable thumbnail fails to load (e.g. 410 hidden in trash), show a semantic placeholder instead of a broken <img>.
export function UnavailableResult({ compact = true, trashed = false }) {
  const label = trashed ? '结果已隐藏' : '预览暂不可用'
  const detail = trashed
    ? '任务在回收站，恢复后可重新查看结果。'
    : '结果缩略图暂时无法读取；任务记录仍可查看。'
  return (
    <div
      className="task-result-unavailable art-hatch-surface absolute inset-0 flex flex-col items-center justify-center gap-1.5 p-4 text-center text-nexus-muted"
      data-testid="task-result-unavailable"
      data-trashed={trashed ? 'true' : undefined}
      role="img"
      aria-label={trashed ? '任务在回收站，结果已隐藏' : label}
    >
      <TaskPlaceholderArt kind={trashed ? 'trashed' : 'unavailable'} compact={compact} />
      <span className="text-xs font-medium text-nexus-text">{label}</span>
      <span className={`${compact ? 'max-w-44 text-[11px] leading-4' : 'max-w-64 text-xs leading-5'} text-nexus-muted`}>{detail}</span>
    </div>
  )
}

export function TaskPreview({ item, compact = true, trash = false }) {
  const [failedSrc, setFailedSrc] = useState(null)
  const isTrashed = Boolean(trash || item.deletedAt)

  if (ACTIVE_STATUSES.has(item.status)) {
    return (
      <div className="absolute inset-0 overflow-hidden bg-black">
        <CodeRainCanvas status={item.status} compact={compact} />
        <div className="absolute inset-x-0 bottom-0 z-10 bg-black/80 px-3 py-2">
          <div className="mb-1 flex items-center justify-between font-mono text-xs text-[#9fffc2]">
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

  if (item.resultDeleted) return <DeletedResult compact={compact} />
  if (item.type === 'video' && (item.thumbnail || item.poster || item.video)) {
    const posterSrc = item.thumbnail || item.poster
    if (posterSrc) {
      if (failedSrc === posterSrc) return <UnavailableResult compact={compact} trashed={isTrashed} />
      return (
        <img
          src={posterSrc}
          loading="lazy"
          decoding="async"
          onError={() => setFailedSrc(posterSrc)}
          className="absolute inset-0 size-full object-contain"
          alt="视频任务预览"
        />
      )
    }
    if (failedSrc === item.video) return <UnavailableResult compact={compact} trashed={isTrashed} />
    return (
      <video
        src={item.video}
        onError={() => setFailedSrc(item.video)}
        className="absolute inset-0 size-full object-contain"
        muted
        preload="metadata"
      />
    )
  }
  if (item.type === 'audio' && item.audio) return <AudioArtwork compact={compact} />
  if (item.type === 'layer' && (item.thumbnail || item.images?.length)) {
    const layerSrc = item.thumbnail || item.images[0]
    if (failedSrc === layerSrc) return <UnavailableResult compact={compact} trashed={isTrashed} />
    return (
      <>
        <img
          src={layerSrc}
          loading="lazy"
          decoding="async"
          onError={() => setFailedSrc(layerSrc)}
          className="absolute inset-0 size-full object-contain"
          alt="图层分解任务预览"
        />
        {item.layerCount > 0 && (
          <span className="task-layer-count-badge" data-testid="task-layer-count">
            <Layers3 size={11} aria-hidden="true" />
            {item.layerCount} 图层
          </span>
        )}
      </>
    )
  }
  if (item.images?.length) {
    const imageSrc = item.thumbnail || item.images[0]
    if (failedSrc === imageSrc) return <UnavailableResult compact={compact} trashed={isTrashed} />
    return (
      <img
        src={imageSrc}
        loading="lazy"
        decoding="async"
        onError={() => setFailedSrc(imageSrc)}
        className="absolute inset-0 size-full object-contain"
        alt="图片任务预览"
      />
    )
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
  const EmptyIcon = item.type === 'all' ? LayoutList : item.type === 'video' ? Film : item.type === 'audio' ? AudioLines : item.type === 'layer' ? Layers3 : ImageIcon
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-nexus-muted">
      <EmptyIcon size={30} strokeWidth={1.25} />
      <span className="text-xs">暂无结果</span>
    </div>
  )
}
