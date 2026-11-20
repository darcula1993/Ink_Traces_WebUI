import React from 'react'
import useGridWindow from '../../lib/useGridWindow'
import { ArchiveRestore, Ban, Check, FolderInput, FolderSearch, Heart, Trash2 } from 'lucide-react'
import { ACTIVE_STATUSES, STATUS, taskStatusInfo, formatTime, providerLabel, taskTypeLabel, selectionToken } from './taskModel.js'
import { TaskPreview, TaskTypeIcon } from './TaskPreview.jsx'

export const TaskCard = React.memo(function TaskCard({
  item,
  windowIndex,
  windowStyle,
  detailed,
  showTypeBadge = false,
  selectionMode,
  checked,
  selectionTokenValue,
  onOpen,
  onToggleSelection,
  onFavorite,
  onCancel,
  onDelete,
  onRestore,
  onReveal,
  onMove,
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
    <article style={{contentVisibility:"visible",...windowStyle}} data-window-card={windowIndex}
      role="button"
      tabIndex={0}
      data-testid="task-gallery-card"
      data-task-type={item.type || 'image'}
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
      className={`task-gallery-card group relative flex min-w-0 flex-col overflow-hidden border text-left transition-colors ${checked ? 'task-gallery-card-selected' : 'border-white/10 hover:border-white/25'}`}
    >
      <div className="task-card-preview relative overflow-hidden bg-[#050708]">
        <TaskPreview item={item} trash={trash} />
        {(showTypeBadge || item.status !== 'succeeded') && (
          <div className="absolute left-2 top-2 z-20 flex items-center gap-1.5">
            {showTypeBadge && (
              <span
                className={`task-type-badge task-type-badge-${item.type || 'image'}`}
                data-testid="task-card-type-badge"
                data-task-type={item.type || 'image'}
              >
                <TaskTypeIcon type={item.type} size={11} />
                {taskTypeLabel(item.type)}
              </span>
            )}
            {item.status !== 'succeeded' && (
              <span className={`status-pill min-h-6 px-2 text-xs ${status.tone}`}>
                <StatusIcon size={11} className={status.spin ? 'animate-spin' : ''} />
                {status.label}
              </span>
            )}
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
            {item.libraryMedia?.length > 0 && onReveal && (
              <button
                type="button"
                aria-label="在素材库中显示"
                title="在素材库中定位这项任务的结果"
                onClick={event => { event.stopPropagation(); onReveal(item) }}
                className="task-card-action"
              >
                <FolderSearch size={14} />
              </button>
            )}
            {item.libraryMedia?.length > 0 && onMove && (
              <button
                type="button"
                aria-label="复制到文件夹"
                title="把任务结果复制到素材库中的其他文件夹（原结果留在生成历史，随任务删除；复制出的不受影响）"
                onClick={event => { event.stopPropagation(); onMove(item) }}
                className="task-card-action"
              >
                <FolderInput size={14} />
              </button>
            )}
            {item.taskId && trash && onRestore && (
              <button
                type="button"
                aria-label="恢复任务"
                title="恢复任务"
                onClick={event => { event.stopPropagation(); onRestore(item) }}
                className="task-card-action hover:text-nexus-green"
              >
                <ArchiveRestore size={14} />
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
        <div className="task-card-details flex flex-1 flex-col border-t border-white/8 px-3 py-2.5">
          <p className="line-clamp-2 min-h-10 break-words text-xs leading-5 text-nexus-text-light">{item.prompt || '未填写提示词'}</p>
          {item.favoriteGroups?.length > 0 && (
            <div className="mt-2 flex min-w-0 gap-1 overflow-hidden">
              {item.favoriteGroups.slice(0, 2).map(group => (
                <span key={group.id} className="favorite-group-pill" data-color={group.color}>{group.name}</span>
              ))}
              {item.favoriteGroups.length > 2 && <span className="favorite-group-pill">+{item.favoriteGroups.length - 2}</span>}
            </div>
          )}
          <div className="mt-auto flex min-w-0 items-center gap-2 pt-2 font-mono text-xs text-nexus-muted">
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
  const window = useGridWindow(items.length)
  const indices=Array.from({length:Math.max(0,window.end-window.start)},(_,i)=>i+window.start)
  if(window.pinned)for(const index of [window.pinned.index-1,window.pinned.index,window.pinned.index+1])if(index>=0&&index<items.length&&!indices.includes(index))indices.push(index)
  indices.sort((a,b)=>a-b)
  return (
    <div className="task-gallery-grid" ref={window.ref} style={{position:"relative",paddingTop:window.padTop,paddingBottom:window.padBottom}}>
      {loading && items.length === 0 && Array.from({ length: 8 }, (_, index) => (
        <div key={`skeleton-${index}`} className="task-card-skeleton" aria-hidden="true">
          <div className="task-card-skeleton-media" />
          {detailed && <div className="task-card-skeleton-lines"><span /><span /></div>}
        </div>
      ))}
      {indices.map(index => {const item=items[index];return (
        <TaskCard
          windowIndex={index}
          windowStyle={window.pinned&&(index<window.start||index>=window.end)?{position:"absolute",top:Math.floor(index/window.pinned.columns)*window.pinned.stride,left:(index%window.pinned.columns)*(window.pinned.width+window.pinned.gap),width:window.pinned.width}:undefined}
          key={item.key}
          item={item}
          detailed={detailed}
          checked={selectedKeys.has(selectionToken(item))}
          selectionTokenValue={selectionToken(item)}
          {...props}
        />
      )})}
    </div>
  )
})
