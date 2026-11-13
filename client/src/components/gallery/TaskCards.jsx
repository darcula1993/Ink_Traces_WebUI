import React from 'react'
import { Ban, Check, Heart, Trash2 } from 'lucide-react'
import { ACTIVE_STATUSES, STATUS, taskStatusInfo, formatTime, providerLabel, taskTypeLabel, selectionToken } from './taskModel.js'
import { TaskPreview } from './TaskPreview.jsx'

export const TaskCard = React.memo(function TaskCard({
  item,
  detailed,
  selectionMode,
  checked,
  selectionTokenValue,
  onOpen,
  onToggleSelection,
  onFavorite,
  onCancel,
  onDelete,
  trash,
}) {
  const status = taskStatusInfo(item) || STATUS.pending
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
        ? `${checked ? '取消选择' : '选择'}${taskTypeLabel(item.type)}任务`
        : `打开${taskTypeLabel(item.type)}任务`}
      aria-pressed={selectionMode ? checked : undefined}
      onClick={activate}
      onKeyDown={event => {
        if (event.target !== event.currentTarget) return
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          activate()
        }
      }}
      data-status={item.status}
      data-result-unknown={item.resultUnknown ? 'true' : undefined}
      className={`task-gallery-card group relative min-w-0 overflow-hidden border bg-black/35 text-left transition-colors ${checked ? 'task-gallery-card-selected' : 'border-white/10 hover:border-white/25'}`}
    >
      <div className="task-card-preview relative overflow-hidden bg-[#050708]">
        <TaskPreview item={item} />
        {item.status !== 'succeeded' && (
          <div className="absolute left-2 top-2 z-20 flex items-center gap-1.5">
            <span className={`status-pill min-h-6 px-2 text-xs ${status.tone}`}>
              <StatusIcon size={11} className={status.spin ? 'animate-spin' : ''} />
              {status.label}
            </span>
          </div>
        )}
        {selectionMode ? (
          <span
            className={`task-selection-check absolute right-2 top-2 z-20 ${checked ? 'task-selection-check-active' : ''}`}
            title={checked ? '已选择' : '选择任务'}
          >
            {checked && <Check size={13} />}
          </span>
        ) : (
          <div className={`task-card-actions absolute right-2 top-2 z-20 flex items-center gap-1 ${item.favorite ? 'task-card-actions-pinned' : ''}`}>
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
                className={`task-card-action ${item.favorite ? 'task-card-favorite-active text-[#ff5c7c]' : ''}`}
              >
                <Heart size={14} fill={item.favorite ? 'currentColor' : 'none'} />
              </button>
            )}
            {item.taskId && (
              <button
                type="button"
                aria-label={trash ? '彻底删除任务' : '删除任务'}
                title={trash ? '彻底删除' : '移到回收站'}
                onClick={event => { event.stopPropagation(); onDelete(item) }}
                className="task-card-action hover:border-nexus-red/40 hover:text-nexus-red"
              >
                <Trash2 size={14} />
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
          <div className="mt-2 flex min-w-0 items-center gap-2 font-mono text-xs text-nexus-muted">
            <span>#{item.taskId}</span>
            {item.provider && <span className="truncate">{providerLabel(item.provider)}</span>}
            {item.createdAt && <time className="ml-auto shrink-0">{formatTime(item.createdAt)}</time>}
          </div>
        </div>
      )}
    </article>
  )
})

export const TaskCardList = React.memo(function TaskCardList({ items, loading, detailed, selectedKeys, ...props }) {
  return (
    <div className="task-gallery-grid">
      {loading && items.length === 0 && Array.from({ length: 8 }, (_, index) => (
        <div key={`skeleton-${index}`} className="task-card-skeleton" aria-hidden="true">
          <div className="task-card-skeleton-media" />
          {detailed && <div className="task-card-skeleton-lines"><span /><span /></div>}
        </div>
      ))}
      {items.map(item => (
        <TaskCard
          key={item.key}
          item={item}
          detailed={detailed}
          checked={selectedKeys.has(selectionToken(item))}
          selectionTokenValue={selectionToken(item)}
          {...props}
        />
      ))}
    </div>
  )
})
