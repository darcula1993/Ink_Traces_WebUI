import React,{useMemo} from 'react'
import {Crosshair,ExternalLink} from 'lucide-react'
import {CanvasTaskEmptyArt} from '../art/CanvasLibraryArt'
import {summarizeCanvasTasks,TASK_GROUPS} from './canvasChrome'
import {isCancellableTask,taskStatusLabel} from '../../lib/taskStatus'
import {requestTaskCenter,requestToolTaskCenter} from '../../lib/taskCenterLink'

const MODE_LABELS={image:'图片',video:'视频',audio:'音频'}
// CANVAS-LAYOUT-2-20261118: rail panel "本画布任务" (user 11-17 rename). Pure frontend: built from this
// canvas document's node tasks, no new endpoint. Each row: locate the node / open "#N" in the tool's task
// center. `onUnhandled(message)` reports a hand-off nobody took (e.g. notify) — same wording as the canvas.
export default function CanvasTaskPanel({nodes=[],onLocate,onOpenTask,onOpenTool,onUnhandled,onCancelTask,cancellingTaskIds}) {
 const groups=useMemo(()=>summarizeCanvasTasks(nodes),[nodes])
 const total=groups.active.length+groups.problem.length+groups.done.length
 const openTask=item=>{
  if(onOpenTask)return onOpenTask(item)
  if(item.taskId&&!requestTaskCenter({taskId:item.taskId,type:item.mode}))onUnhandled?.(`请到${MODE_LABELS[item.mode]||''}工具的任务中心按编号 #${item.taskId} 查找该任务`)
 }
 const openTool=mode=>{if(onOpenTool)return onOpenTool(mode);if(!requestToolTaskCenter(mode))onUnhandled?.(`请到${MODE_LABELS[mode]}工具查看任务中心`)}
 return <div className="cv-panel-tasks">
  {!total&&<div className="cv-panel-empty cv-panel-empty-art"><CanvasTaskEmptyArt/><p>本画布还没有生成任务。点击节点上的“生成”后会在这里列出。</p></div>}
  {TASK_GROUPS.map(group=>groups[group.id].length>0&&<section key={group.id} className={`cv-task-group is-${group.id}`} aria-labelledby={`cv-task-group-${group.id}`}>
   <h3 id={`cv-task-group-${group.id}`}>{group.label}<span className="cv-task-count">{groups[group.id].length}</span></h3>
   <ul>{groups[group.id].map(item=>{
    const cancellable=group.id==='active'&&onCancelTask&&isCancellableTask({id:item.taskId,status:item.status})
    const cancelling=cancellable&&!!cancellingTaskIds?.has(item.taskId)
    return <li key={item.nodeId} className="cv-task-item" data-node-id={item.nodeId} data-status={item.status}>
     <div className="cv-task-main"><span className="cv-task-title" title={item.title}>{item.title}</span><span className="cv-task-status">{MODE_LABELS[item.mode]} · {taskStatusLabel(item.status)}</span></div>
     <div className="cv-task-actions">
      {cancellable&&<button type="button" className="btn btn-ghost btn-sm" data-testid={`task-panel-cancel-${item.nodeId}`} aria-label={`取消任务 ${item.title}`} title={cancelling?'正在发送取消请求…':`取消任务 #${item.taskId}`} disabled={cancelling} onClick={()=>onCancelTask(item.nodeId)}>{cancelling?'取消中…':'取消任务'}</button>}
      <button type="button" className="btn btn-ghost btn-sm btn-icon" aria-label={`定位节点 ${item.title}`} title="定位节点" onClick={()=>onLocate?.(item.nodeId)}><Crosshair size={14} aria-hidden="true"/></button>
      {item.taskId?<button type="button" className="btn btn-ghost btn-sm" aria-label={`在任务中心查看 #${item.taskId}`} title={`在${MODE_LABELS[item.mode]}任务中心查看`} onClick={()=>openTask(item)}>#{item.taskId}</button>:<span className="cv-task-pending" title="任务尚未取得编号">提交中</span>}
     </div>
    </li>})}</ul>
  </section>)}
  <footer className="cv-panel-footer cv-task-links" aria-label="任务中心">
   <button type="button" className="btn btn-ghost btn-sm" onClick={()=>openTool('tasks')}><ExternalLink size={12} aria-hidden="true"/>全局任务中心</button>
   {Object.entries(MODE_LABELS).map(([mode,label])=><button key={mode} type="button" className="btn btn-ghost btn-sm" onClick={()=>openTool(mode)}><ExternalLink size={12} aria-hidden="true"/>{label}任务中心</button>)}
  </footer>
 </div>
}
