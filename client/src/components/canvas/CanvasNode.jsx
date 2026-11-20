import React, {useEffect,useRef,useState} from 'react'
import {mediaKind} from '../../lib/canvasReferences'
import ReferenceThumbnails from './ReferenceThumbnails'
import CodeRainCanvas from '../CodeRainCanvas'
import {isGeneratingTaskStatus,isFailureTaskStatus,taskStatusLabel,INVALID_STATUS_LABEL} from '../../lib/taskStatus'
import { nodeGeometry, scaleForSize, nodeScale, nodeScaleRange } from './canvasGeometry'
import {TASK_STAGES,taskStageIndex,taskStageHint,taskProgressPercent} from '../../lib/taskStage'
import { mediaSize, recordMediaSize } from './mediaSizes'
import {isTrashedMedia} from '../../lib/canvasMediaStatus'
import MediaPlayer from './MediaPlayer'
import { FileText, Image, Film, Music, AlertTriangle, LoaderCircle } from 'lucide-react'
import { NodeWaitingArt, MediaUnavailableArt } from '../art/CanvasLibraryArt'
import useTaskEcho from './useTaskEcho'
import CanvasNodePorts from './CanvasNodePorts'
import './nodeEcho.css'
import {formatDuration,taskDurationSeconds,taskStartedAt,taskCostEcho,taskFailure,formatTaskError,FAILURE_ACTION_LABELS} from '../../lib/canvasTaskEcho'

const kinds = { text: ['文本', FileText], image: ['画面', Image], video: ['视频', Film], audio: ['音频', Music] }

const formatElapsed=formatDuration
// Elapsed time is client-side runtime state (never saved). NODE-ECHO-20261115: counted from the server
// submit time once the task detail is loaded, else from when this node first showed the active task.
function useTaskElapsed(task,startedAt=null){
  const active=task?.id&&isGeneratingTaskStatus(task.status),taskId=task?.id,start=useRef({id:null,at:0}),[now,setNow]=useState(Date.now())
  if(active&&start.current.id!==taskId)start.current={id:taskId,at:Date.now()}
  useEffect(()=>{if(!active)return;setNow(Date.now());const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer)},[active,taskId])
  return active?Math.max(0,Math.floor((now-(startedAt??start.current.at))/1000)):null
}
// NODE-ECHO-20261115: latest task number (opens the task center), duration and cost estimate.
function TaskEcho({task,detail,resultUnknown,onOpenTask}){
  const cost=taskCostEcho(detail,{resultUnknown}),duration=taskDurationSeconds(detail)
  return <span className="cv-node-echo" data-testid="node-task-echo"><button type="button" className="cv-node-echo-task" title={`任务 #${task.id}：在任务中心查看`} aria-label={`在任务中心查看任务 #${task.id}`} onClick={event=>{event.stopPropagation();onOpenTask?.(task)}}>#{task.id}</button>{duration!=null&&<span className="cv-node-echo-item" data-testid="node-task-duration" title={`耗时 ${formatDuration(duration)}（提交到完成）`}>{formatDuration(duration)}</span>}{cost&&<span className={`cv-node-echo-item ${cost.known?'':'is-unknown'}`} data-testid="node-task-cost" title={cost.title} aria-label={cost.title}>{cost.text}</span>}</span>
}
// FIX-B2B-20261114: stage stepper for in-flight video tasks (排队 → 生成 → 下载写回).
function TaskStages({status,stage}){
  const current=taskStageIndex(status,stage)
  if(current<0)return null
  return <ol className="cv-task-stages" aria-label={`任务阶段：${TASK_STAGES[current]}`} title={taskStageHint(status,stage)}>{TASK_STAGES.map((stage,index)=><li key={stage} className={index<current?'is-done':index===current?'is-current':''} aria-current={index===current?'step':undefined}>{stage}</li>)}</ol>
}
const OUT_KIND={image:'图片',video:'视频',audio:'音频'}
// CARD-PROMPT-RESIZE-20261118 (user 11-18): bottom-right handle resizes the whole node (media keeps its aspect, the
// prompt text area grows with it). The pointer gesture previews live and commits once on release (one save);
// double-click restores the automatic size; keyboard: arrows grow/shrink (Shift = larger steps), Home = automatic.
const RESIZE_STEP=.05,RESIZE_STEP_LARGE=.25
function ResizeHandle({node,geometry,selected,onResize}){
  const gesture=useRef(null)
  const down=event=>{
    if(event.button!==0)return
    event.stopPropagation();event.preventDefault()
    const card=event.currentTarget.closest('.cv-node')?.getBoundingClientRect(),zoom=card&&geometry.width?card.width/geometry.width:1
    gesture.current={pointer:event.pointerId,x:event.clientX,y:event.clientY,width:geometry.width,height:geometry.height,zoom:zoom||1,scale:null}
    event.currentTarget.setPointerCapture?.(event.pointerId)
    onResize(null,'start')
  }
  const move=event=>{
    const state=gesture.current;if(!state||state.pointer!==event.pointerId)return
    event.stopPropagation()
    const dx=(event.clientX-state.x)/state.zoom,dy=(event.clientY-state.y)/state.zoom
    if(state.scale==null&&Math.hypot(dx,dy)*state.zoom<3)return
    const scale=scaleForSize(node,state.width+dx,state.height+dy)
    if(scale!==state.scale){state.scale=scale;onResize(scale,'move')}
  }
  const up=event=>{const state=gesture.current;gesture.current=null;if(!state)return;event.stopPropagation();if(state.scale!=null)onResize(state.scale,'end')}
  const cancel=()=>{const state=gesture.current;gesture.current=null;if(state?.scale!=null)onResize(null,'cancel')}
  const key=event=>{
    const step=event.shiftKey?RESIZE_STEP_LARGE:RESIZE_STEP,delta={ArrowRight:step,ArrowDown:step,ArrowLeft:-step,ArrowUp:-step}[event.key]
    if(event.key==='Home'){event.preventDefault();event.stopPropagation();onResize(null,'reset');return}
    if(delta==null)return
    event.preventDefault();event.stopPropagation()
    const {min,max}=nodeScaleRange(node);onResize(Math.min(max,Math.max(min,nodeScale(node)+delta)),'key')
  }
  const scale=nodeScale(node),percent=Math.round(scale*100)
  return <button type="button" className={`cv-node-resize ${node.size?'is-manual':''}`} data-testid="node-resize" tabIndex={selected?0:-1}
    aria-label={`调整 ${node.title} 大小（当前 ${node.size?`${percent}%`:'自动'}）`} title={`拖动调整节点大小（${node.size?`${percent}%`:'自动大小'}）；双击恢复自动大小；聚焦后方向键调整，Home 恢复自动`}
    onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={cancel} onLostPointerCapture={()=>{if(gesture.current)cancel()}}
    onDoubleClick={event=>{event.stopPropagation();event.preventDefault();onResize(null,'reset')}} onKeyDown={key}/>
}
export default function CanvasNode({ node, selected, highlighted=false, pendingConnection, onSelect, onDrag, onChange, onPort, references=[], frames, onMenu, onPreview, onHistory, onLocate, onRightDrag,provider,onSelectComplete,resultUnknown=false,statusAnomaly,onPortDrag,dropTarget=false,onFocusZoom,onOpenTask,runMark,assetDeleted=false,onMediaError,onReplaceDeleted,onReplaceDeletedFromLibrary,onRemoveDeleted,prompt=null,onPromptKey,ports=null,portLayout=null,dragKind=null,dragReason=null,onPortsHover,onExpandPorts,portWarnings=[],onAddReference,onResize }) {
  const geometry=nodeGeometry(node)
  const kind = mediaKind(node)
  const [baseLabel, Icon] = kinds[kind] || kinds.text
  const label = node.type === 'asset' ? `${baseLabel}素材` : baseLabel
  const asset = node.asset
  // UI-ITER-R2A #2: measured sizes live in the shared runtime cache (drives node geometry).
  const dimensions=mediaSize(asset?.id),mediaNode=geometry.mediaHeight!=null
  const measure=(width,height)=>recordMediaSize(asset?.id,width,height)
  const task = node.task
  const echoed=['image','video','audio'].includes(node.type)&&Number(task?.id)>0,fetched=useTaskEcho(task,echoed),detail=fetched&&{...fetched,status:task.status}
  const elapsed=useTaskElapsed(task,taskStartedAt(detail))
  const generating=['image','video'].includes(node.type)&&isGeneratingTaskStatus(task?.status)
  // UI-ITER-R1: the media area itself carries failure / in-progress state (no "waiting" copy while a task runs or failed).
  const failed=!!task&&isFailureTaskStatus(task.status),busy=!!task&&isGeneratingTaskStatus(task.status)
  const failureClass=failed?taskFailure(task.failure||fetched?.failure,{resultUnknown,status:task.status}):null
  const failureTitle=failed&&(failureClass?.label||(resultUnknown&&task.status==='failed'?'结果未知':task.status==='unknown'?'提交结果未知':'生成失败'))
  const taskError=formatTaskError(task?.error)
  const failureReason=failureClass?.hint||taskError||'服务端未返回失败原因'
  // LIBRARY-GLOBAL S5: the referenced media was deleted in the library — keep the node and its place, offer replace/remove.
  const assetTrashed=assetDeleted&&isTrashedMedia(asset?.id)
  const deletedPlaceholder=assetTrashed?<div className="cv-media-empty cv-media-state is-deleted is-trashed" data-testid="node-asset-trashed"><MediaUnavailableArt variant="trashed"/><strong>结果在回收站</strong><span className="cv-media-state-reason" title={asset?.name}>“{asset?.name||'结果'}”所在的生成任务在回收站，恢复任务后自动显示</span></div>:<div className="cv-media-empty cv-media-state is-deleted" data-testid="node-asset-deleted"><MediaUnavailableArt variant="deleted"/><strong>已删除</strong><span className="cv-media-state-reason" title={asset?.name}>“{asset?.name||'素材'}”已在素材库中删除</span><span className="cv-media-state-actions">{onReplaceDeletedFromLibrary&&<button type="button" className="btn btn-secondary btn-sm" aria-label={`从素材库替换已删除的素材 ${node.title}`} title="从素材库选择同类型素材替换" onClick={event=>{event.stopPropagation();onReplaceDeletedFromLibrary()}}>从素材库替换</button>}{onReplaceDeleted&&<button type="button" className="btn btn-secondary btn-sm" aria-label={`上传替换已删除的素材 ${node.title}`} title="上传本地文件替换" onClick={event=>{event.stopPropagation();onReplaceDeleted()}}>上传替换</button>}<button type="button" className="btn btn-ghost btn-sm" aria-label={`${node.type==='asset'?'移除节点':'移除已删除的结果'} ${node.title}`} onClick={event=>{event.stopPropagation();onRemoveDeleted?.()}}>移除</button></span></div>
  // CANVAS-LAYOUT-1-20261117: legacy text nodes edit their text in the card (no new text nodes can be created).
  const preview=node.type === 'text' ? (prompt || <div className="cv-node-text">{node.text || '选择节点，输入故事、对白或提示词'}</div>) : asset?.url && assetDeleted ? deletedPlaceholder : asset?.url ? kind === 'image' ? <img className="cv-media" src={asset.url} alt={node.title} loading="lazy" draggable={false} onError={()=>onMediaError?.()} onLoad={e=>measure(e.currentTarget.naturalWidth,e.currentTarget.naturalHeight)} /> : <MediaPlayer kind={kind==='video'?'video':'audio'} src={asset.url} title={node.title} onMetadata={element=>kind==='video'&&measure(element.videoWidth,element.videoHeight)}/> : failed ? <div className="cv-media-empty cv-media-state is-failed"><AlertTriangle size={24} aria-hidden="true"/><strong>{failureTitle}</strong><span className="cv-media-state-reason" data-testid={failureClass?'node-failure-hint':undefined} data-failure-category={failureClass?.category||undefined} title={[failureClass?.hint,taskError].filter(Boolean).join('\n')||undefined}>{failureReason}</span><span className="cv-media-state-actions">{failureClass?.action==='check_task'&&task.id&&<button type="button" className="btn btn-secondary btn-sm" data-testid="node-failure-action" aria-label={`${FAILURE_ACTION_LABELS.check_task} ${node.title}`} onClick={event=>{event.stopPropagation();onOpenTask?.(task)}}>核查任务</button>}<button type="button" className="btn btn-ghost btn-sm" aria-label={`查看失败详情 ${node.title}`} onClick={onLocate}>查看详情</button></span></div> : busy ? <div className="cv-media-empty cv-media-state is-busy"><LoaderCircle size={24} className="cv-spin" aria-hidden="true"/><strong>{taskStatusLabel(task.status)}</strong>{node.type==='video'&&<TaskStages status={task.status} stage={task.stage}/>}</div> : <div className="cv-media-empty is-waiting" data-waiting-kind={node.type}><NodeWaitingArt kind={node.type}/><span>{node.type === 'image' ? '等待生成画面' : node.type === 'video' ? '等待生成视频' : '等待生成音频'}</span></div>
  const statusLabel=task&&(task.status==='failed'&&resultUnknown?'结果未知，可能已计费':taskStatusLabel(task.status))
  const percent=generating?taskProgressPercent(node.type,task.progress):null
  // FIX-B2B-20261114: video nodes show the stage, never a provider placeholder percentage.
  const progressText=generating?[percent!=null?`${percent}%`:node.type==='video'?taskStageHint(task.status,task.stage):'',elapsed==null?'':`已用 ${formatElapsed(elapsed)}`].filter(Boolean).join(' · '):''
  const statusText=task&&`${statusLabel}${progressText?` · ${progressText}`:''}${statusAnomaly?` · ${INVALID_STATUS_LABEL}（服务端返回“${statusAnomaly}”，已保留原状态）`:''}${taskError ? ` · ${taskError}` : ''}`
  const echo=echoed&&<TaskEcho task={task} detail={detail} resultUnknown={resultUnknown&&task.status==='failed'} onOpenTask={onOpenTask}/>
  // NODE-ECHO-20261115 (艾达必修1): beside the echo a failed node's footer keeps only the status word; the reason is
  // already in the media area (full text stays in the tooltip). With a result shown, the badge has no reason, so keep it.
  const shortStatus=!!echo&&failed&&mediaNode&&!asset?.url&&!statusAnomaly
  const status=task && <div className={`cv-node-status ${isFailureTaskStatus(task.status) ? 'error' : ''} ${resultUnknown&&task.status==='failed'?'is-unknown':''} ${shortStatus?'is-short':''}`} role="status" tabIndex={0} title={statusText} data-result-unknown={resultUnknown&&task.status==='failed'?'true':undefined}>{shortStatus?statusLabel:statusText}</div>
  const stale=node.upstreamStale&&<div className="cv-node-stale" role="status" title="上游的选定结果或输入已变化，此节点结果可能已过期；不会自动重新生成">上游已更新</div>
  // Selecting on pointerdown can mount a panel over this port before pointerup.
  // Keep left-click connection gestures intact; right drag still bubbles to pan.
  const portPointerDown = event => { if(event.button===0)event.stopPropagation() }
  // FIX-B2B-20261114: while a click-to-connect is pending, a plain click anywhere on a node
  // that accepts inputs completes the connection on press (not only its small input port).
  const connectTarget=!!pendingConnection&&pendingConnection!==node.id&&node.type!=='text'&&node.type!=='asset'
  const overlays=<>{failed&&asset?.url&&!assetDeleted&&<span className="cv-media-badge is-failed" aria-hidden="true"><AlertTriangle size={14} aria-hidden="true"/>{failureTitle}</span>}{busy&&asset?.url&&<span className="cv-media-badge is-busy" aria-hidden="true"><LoaderCircle size={14} className="cv-spin" aria-hidden="true"/>{taskStatusLabel(task.status)}{elapsed!=null?` · ${formatElapsed(elapsed)}`:''}</span>}{generating&&<div className="cv-generation-rain" data-testid="generation-code-rain"><CodeRainCanvas status={task.status} compact useLayoutSize/></div>}</>
  // Card reference row “+” (spec 1.3): only on the selected generation node (opens the library for this node).
  const addReference=selected&&onAddReference&&['image','video','audio'].includes(node.type)?onAddReference:undefined,addLabel=`为 ${node.title} 添加参考素材`
  return <article className={`cv-node ${mediaNode?'cv-node-sized':''} ${generating?'is-generating':''} ${failed?(resultUnknown||task.status==='unknown'?'is-unknown':'is-failed'):''} ${selected ? 'is-selected' : ''} ${highlighted ? 'is-locate-highlight' : ''} ${dropTarget ? 'is-drop-target' : ''} ${references.length?'has-references':''} ${connectTarget?'is-connect-target':''} ${dragKind?(dragReason?'is-port-refused':'is-port-candidate'):''} ${portLayout?.collapsed?'has-collapsed-ports':''}`} style={{ left: node.x, top: node.y,width:geometry.width,height:geometry.height,...(mediaNode?{'--cv-media-h':`${geometry.mediaHeight}px`}:{}),...(geometry.promptHeight?{'--cv-prompt-h':`${geometry.promptHeight}px`}:{}) }} data-media-kind={mediaNode?kind:undefined} data-node-id={node.id} data-node-type={node.type} data-locate-highlighted={highlighted?'true':undefined} aria-label={`${label}节点：${node.title}`} tabIndex={0} onFocus={event=>{if(event.target===event.currentTarget){onSelect(event);if(event.currentTarget.matches(':focus-visible'))requestAnimationFrame(()=>onSelectComplete?.())}}} onDoubleClick={event=>{if(!event.target.closest('button,input,textarea,select,.cv-media-player-bar')){event.stopPropagation();onFocusZoom?.()}}} onPointerUp={event=>{if(event.button===0&&!event.target.closest('button,input,textarea,select,video,audio'))onSelectComplete?.()}} onContextMenu={event=>event.preventDefault()} onPointerEnter={onPortsHover?()=>onPortsHover(true):undefined} onPointerLeave={onPortsHover?()=>onPortsHover(false):undefined} onKeyDown={event => { if (event.target !== event.currentTarget) return; if(event.key==='ContextMenu'||(event.shiftKey&&event.key==='F10')){event.preventDefault();onMenu(event);return}if(event.key==='Enter'&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&onPromptKey){event.preventDefault();onPromptKey(event.shiftKey);return} const delta = { ArrowLeft: [-10,0], ArrowRight: [10,0], ArrowUp: [0,-10], ArrowDown: [0,10] }[event.key]; if (delta) { event.preventDefault(); onChange({ x: node.x + delta[0], y: node.y + delta[1] }) } }} onPointerDown={event => {event.stopPropagation();if(event.button===0&&connectTarget&&!event.target.closest('button,input,textarea,select,a,.cv-media-player-bar')){event.preventDefault();onPort('input');return}if(event.button===2){onRightDrag(event);return}if(event.target.closest('button,input,textarea,select,video[controls],audio[controls],[contenteditable=true],a'))return;onDrag(event)}}>
    <header className="cv-node-head"><Icon size={15} /><span className="cv-node-title">{node.title}</span><span className="cv-node-kind">{assetTrashed ? '在回收站' : assetDeleted ? '已删除' : node.type==='asset'&&kind==='image' ? dimensions ? `${dimensions.width} × ${dimensions.height}` : '读取尺寸…' : label}</span></header>
    {node.type !== 'text' && node.type !== 'asset' && (ports&&portLayout ? <CanvasNodePorts node={node} ports={ports} layout={portLayout} dragKind={dragKind} dragReason={dragReason} dropTarget={dropTarget} onPointerDown={portPointerDown} onPort={port=>onPort('input',port)} onExpand={onExpandPorts}/> : <button className="cv-port cv-port-in" style={{top:geometry.portY - 13}} aria-label={`连接到${node.title}`} title="接入参考" onPointerDown={portPointerDown} onClick={() => onPort('input')} />)}
    {portWarnings.length>0&&<div className="cv-port-warning" role="status" data-testid="node-port-warning" title={portWarnings.join('\n')}>{portWarnings.join('；')}</div>}
    <button className={`cv-port cv-port-out ${pendingConnection === node.id ? 'is-pending' : ''}`} data-kind={OUT_KIND[kind]?kind:undefined} aria-label={`从${node.title}连接`} aria-description={OUT_KIND[kind]?`${OUT_KIND[kind]}输出口`:undefined} style={{top:geometry.portY - 13}} title={`${OUT_KIND[kind]?`${OUT_KIND[kind]}输出口 · `:''}连接到下游节点（点击后点目标，或按住拖到目标节点）`} onPointerDown={event=>{portPointerDown(event);if(event.button===0)onPortDrag?.(event)}} onClick={() => onPort('output')} />
    <div className="cv-node-body">
      {mediaNode?<div className={`cv-node-media ${['image','video'].includes(node.type)?'cv-generation-preview':''}`}>{kind==='audio'&&<ReferenceThumbnails assets={references} frames={frames} compact onAdd={addReference} addLabel={addLabel}/>}{preview}{overlays}{kind!=='audio'&&<ReferenceThumbnails assets={references} frames={frames} compact onAdd={addReference} addLabel={addLabel}/>}</div>:<>{preview}<ReferenceThumbnails assets={references} frames={frames} compact/></>}
      {stale}
      {runMark&&<div className="cv-node-run-mark" role="status" data-run-status={runMark.status} title={runMark.detail||runMark.label}>{runMark.label}{runMark.detail?` · ${runMark.detail}`:''}</div>}
      {!mediaNode&&status}{!mediaNode&&echo}
    </div>
    {mediaNode&&status&&<footer className="cv-node-footer">{status}{echo}</footer>}
    {mediaNode&&node.type!=='asset'&&prompt}
    {mediaNode&&onResize&&<ResizeHandle node={node} geometry={geometry} selected={selected} onResize={onResize}/>}
  </article>
}
