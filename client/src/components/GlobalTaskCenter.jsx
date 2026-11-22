import React from 'react'
import { AudioLines, Film, Image as ImageIcon, Layers3, LayoutList, ListTodo } from 'lucide-react'
import TaskGallery from './TaskGallery'

export const GLOBAL_TASK_TYPE_TABS = Object.freeze([
  { value: 'all', label: '全部', icon: LayoutList },
  { value: 'image', label: '图片', icon: ImageIcon },
  { value: 'video', label: '视频', icon: Film },
  { value: 'audio', label: '音频', icon: AudioLines },
  { value: 'layer', label: '图层', icon: Layers3 },
])

export default function GlobalTaskCenter({
  activeType = 'all',
  onTypeChange,
  refreshToken,
  onReuseTask,
}) {
  const safeType = GLOBAL_TASK_TYPE_TABS.some(tab => tab.value === activeType) ? activeType : 'all'
  return (
    <section
      className="global-task-center"
      data-testid="global-task-center"
      data-active-type={safeType}
      aria-label="全局任务中心"
    >
      <div className="global-task-center-bar" data-testid="global-task-center-bar">
        <div className="global-task-center-heading">
          <ListTodo size={14} className="shrink-0 text-nexus-green" aria-hidden="true" />
          <span>全局任务中心</span>
        </div>
        <div className="global-task-type-tabs" role="tablist" aria-label="任务类型">
          {GLOBAL_TASK_TYPE_TABS.map(tab => {
            const Icon = tab.icon
            const selected = safeType === tab.value
            return (
              <button
                key={tab.value}
                type="button"
                role="tab"
                aria-selected={selected}
                data-testid={`task-type-tab-${tab.value}`}
                onClick={() => onTypeChange?.(tab.value)}
                className={`global-task-type-tab ${selected ? 'is-active' : ''}`}
              >
                <Icon size={13} aria-hidden="true" />
                <span>{tab.label}</span>
              </button>
            )
          })}
        </div>
      </div>
      <div className="global-task-center-body">
        <TaskGallery
          mode={safeType}
          allowTrash
          showTypeBadge={safeType === 'all'}
          refreshToken={refreshToken}
          onReuseTask={onReuseTask}
        />
      </div>
    </section>
  )
}
