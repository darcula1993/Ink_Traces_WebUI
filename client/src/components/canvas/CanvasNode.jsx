import React, {useEffect,useRef,useState} from 'react'
import {mediaKind} from '../../lib/canvasReferences'
import ReferenceThumbnails from './ReferenceThumbnails'
import CodeRainCanvas from '../CodeRainCanvas'
import {isGeneratingTaskStatus,isFailureTaskStatus,taskStatusLabel,INVALID_STATUS_LABEL} from '../../lib/taskStatus'
import { nodeGeometry } from './canvasGeometry'
import { mediaSize, recordMediaSize } from './mediaSizes'
import MediaPlayer from './MediaPlayer'
import { FileText, Image, Film, Music, Play, History, AlertTriangle, LoaderCircle } from 'lucide-react'

const kinds = { text: ['文本', FileText], image: ['画面', Image], video: ['视频', Film], audio: ['音频', Music] }

const formatElapsed=sec=>sec>=3600?`${Math.floor(sec/3600)}:${String(Math.floor(sec%3600/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`:`${Math.floor(sec/60)}:${String(sec%60).padStart(2,'0')}`
// Elapsed time is client-side runtime state counted from when this node first showed the active task.
function useTaskElapsed(task){
  const active=task?.id&&isGeneratingTaskStatus(task.status),taskId=task?.id,start=useRef({id:null,at:0}),[now,setNow]=useState(Date.now())
  if(active&&start.current.id!==taskId)start.current={id:taskId,at:Date.now()}
  useEffect(()=>{if(!active)return;setNow(Date.now());const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer)},[active,taskId])
  return active?Math.max(0,Math.floor((now-start.current.at)/1000)):null
}
export default function CanvasNode({ node, selected, pendingConnection, onSelect, onDrag, onChange, onPort, references=[], frames, onMenu, onPreview, onHistory, onLocate, onRightDrag,provider,onSelectComplete,resultUnknown=false,statusAnomaly }) {
  const geometry=nodeGeometry(node)
  const kind = mediaKind(node)
  const [baseLabel, Icon] = kinds[kind] || kinds.text
  const label = node.type === 'asset' ? `${baseLabel}素材` : baseLabel
  const asset = node.asset
  // UI-ITER-R2A #2: measured sizes live in the shared runtime cache (drives node geometry).
  const dimensions=mediaSize(asset?.id),mediaNode=geometry.mediaHeight!=null
  const measure=(width,height)=>recordMediaSize(asset?.id,width,height)
  const task = node.task
  const elapsed=useTaskElapsed(task)
  const generating=['image','video'].includes(node.type)&&isGeneratingTaskStatus(task?.status)
  // UI-ITER-R1: the media area itself carries failure / in-progress state (no "waiting" copy while a task runs or failed).
  const failed=!!task&&isFailureTaskStatus(task.status),busy=!!task&&isGeneratingTaskStatus(task.status)
  const failureTitle=failed&&(resultUnknown&&task.status==='failed'?'结果未知':task.status==='unknown'?'提交结果未知':'生成失败')
  const preview=node.type === 'text' ? <div className="cv-node-text">{node.text || '选择节点，输入故事、对白或提示词'}</div> : asset?.url ? kind === 'image' ? <img className="cv-media" src={asset.url} alt={node.title} loading="lazy" draggable={false} onLoad={e=>measure(e.currentTarget.naturalWidth,e.currentTarget.naturalHeight)} /> : node.type==='asset' ? <button className={`cv-play-asset${kind==='video'?'':' is-audio'}`} aria-label={`播放${kind==='video'?'视频':'音频'} ${node.title}`} onClick={onPreview}>{kind==='video'?<video className="cv-media" src={asset.url} muted preload="metadata" onLoadedMetadata={e=>{const v=e.currentTarget;measure(v.videoWidth,v.videoHeight);if(Number.isFinite(v.duration)&&v.duration>0)v.currentTime=Math.min(.05,v.duration/2)}}/>:<span><Music size={16} aria-hidden="true"/> {node.title}</span>}<b><Play size={13} aria-hidden="true"/> 播放</b></button> : <MediaPlayer kind={kind==='video'?'video':'audio'} src={asset.url} title={node.title} onMetadata={element=>kind==='video'&&measure(element.videoWidth,element.videoHeight)}/> : failed ? <div className="cv-media-empty cv-media-state is-failed"><AlertTriangle size={24} aria-hidden="true"/><strong>{failureTitle}</strong><span className="cv-media-state-reason" title={task.error||undefined}>{task.error||'服务端未返回失败原因'}</span><button type="button" className="btn btn-ghost btn-sm" aria-label={`查看失败详情 ${node.title}`} onClick={onLocate}>查看详情</button></div> : busy ? <div className="cv-media-empty cv-media-state is-busy"><LoaderCircle size={24} className="cv-spin" aria-hidden="true"/><strong>{taskStatusLabel(task.status)}</strong>{elapsed!=null&&<span className="cv-media-state-elapsed">已用 {formatElapsed(elapsed)}</span>}</div> : <div className="cv-media-empty"><Icon size={27} /><span>{node.type === 'image' ? '等待生成画面' : node.type === 'video' ? '等待生成视频' : '等待生成音频'}</span></div>
  const statusLabel=task&&(task.status==='failed'&&resultUnknown?'结果未知，可能已计费':taskStatusLabel(task.status))
  const progressText=generating?[Number.isFinite(task.progress)&&task.progress>0?`${Math.min(100,Math.round(task.progress))}%`:'',elapsed==null?'':`已用 ${formatElapsed(elapsed)}`].filter(Boolean).join(' · '):''
  const statusText=task&&`${statusLabel}${progressText?` · ${progressText}`:''}${statusAnomaly?` · ${INVALID_STATUS_LABEL}（服务端返回“${statusAnomaly}”，已保留原状态）`:''}${task.error ? ` · ${task.error}` : ''}`
  const status=task && <div className={`cv-node-status ${isFailureTaskStatus(task.status) ? 'error' : ''} ${resultUnknown&&task.status==='failed'?'is-unknown':''}`} role="status" tabIndex={0} title={statusText} data-result-unknown={resultUnknown&&task.status==='failed'?'true':undefined}>{statusText}</div>
  const stale=node.upstreamStale&&<div className="cv-node-stale" role="status" title="上游的选定结果或输入已变化，此节点结果可能已过期；不会自动重新生成">上游已更新</div>
  // Selecting on pointerdown can mount a panel over this port before pointerup.
  // Keep left-click connection gestures intact; right drag still bubbles to pan.
  const portPointerDown = event => { if(event.button===0)event.stopPropagation() }
  const overlays=<>{failed&&asset?.url&&<span className="cv-media-badge is-failed" aria-hidden="true"><AlertTriangle size={14} aria-hidden="true"/>{failureTitle}</span>}{busy&&asset?.url&&<span className="cv-media-badge is-busy" aria-hidden="true"><LoaderCircle size={14} className="cv-spin" aria-hidden="true"/>{taskStatusLabel(task.status)}{elapsed!=null?` · ${formatElapsed(elapsed)}`:''}</span>}{generating&&<div className="cv-generation-rain" data-testid="generation-code-rain"><CodeRainCanvas status={task.status} compact useLayoutSize/></div>}</>
  return <article className={`cv-node ${mediaNode?'cv-node-sized':''} ${generating?'is-generating':''} ${failed?(resultUnknown||task.status==='unknown'?'is-unknown':'is-failed'):''} ${selected ? 'is-selected' : ''} ${references.length?'has-references':''}`} style={{ left: node.x, top: node.y,width:geometry.width,height:geometry.height,...(mediaNode?{'--cv-media-h':`${geometry.mediaHeight}px`}:{}) }} data-media-kind={mediaNode?kind:undefined} data-node-id={node.id} data-node-type={node.type} aria-label={`${label}节点：${node.title}`} tabIndex={0} onFocus={event=>{if(event.target===event.currentTarget){onSelect(event);if(event.currentTarget.matches(':focus-visible'))requestAnimationFrame(()=>onSelectComplete?.())}}} onDoubleClick={event=>{if(!event.target.closest('button,input,textarea,select,video,audio')){event.stopPropagation();onLocate()}}} onPointerUp={event=>{if(event.button===0&&!event.target.closest('button,input,textarea,select,video,audio'))onSelectComplete?.()}} onContextMenu={event=>event.preventDefault()} onKeyDown={event => { if (event.target !== event.currentTarget) return; if(event.key==='ContextMenu'||(event.shiftKey&&event.key==='F10')){event.preventDefault();onMenu(event);return} const delta = { ArrowLeft: [-10,0], ArrowRight: [10,0], ArrowUp: [0,-10], ArrowDown: [0,10] }[event.key]; if (delta) { event.preventDefault(); onChange({ x: node.x + delta[0], y: node.y + delta[1] }) } }} onPointerDown={event => {event.stopPropagation();if(event.button===2){onRightDrag(event);return}const play=event.target.closest('.cv-play-asset');if(!play&&event.target.closest('button,input,textarea,select,video[controls],audio[controls],[contenteditable=true],a'))return;onDrag(event,play?{activate:onPreview}:undefined)}}>
    <header className="cv-node-head"><Icon size={15} /><span className="cv-node-title">{node.title}</span><span className="cv-node-kind">{node.type==='asset'&&kind==='image' ? dimensions ? `${dimensions.width} × ${dimensions.height}` : '读取尺寸…' : label}</span></header>
    {node.type !== 'text' && node.type !== 'asset' && <button className="cv-port cv-port-in" style={{top:geometry.portY - 13}} aria-label={`连接到${node.title}`} title="接入参考" onPointerDown={portPointerDown} onClick={() => onPort('input')} />}
    <button className={`cv-port cv-port-out ${pendingConnection === node.id ? 'is-pending' : ''}`} aria-label={`从${node.title}连接`} style={{top:geometry.portY - 13}} title="连接到下游节点" onPointerDown={portPointerDown} onClick={() => onPort('output')} />
    <div className="cv-node-body">
      {node.type==='asset'&&kind==='image'&&<button className="cv-history-button" aria-label={`历史版本 ${node.title}`} title="历史版本" onClick={onHistory}><History size={14}/></button>}
      {mediaNode?<div className={`cv-node-media ${['image','video'].includes(node.type)?'cv-generation-preview':''}`}>{kind==='audio'&&<ReferenceThumbnails assets={references} frames={frames} compact/>}{preview}{overlays}{kind!=='audio'&&<ReferenceThumbnails assets={references} frames={frames} compact/>}</div>:<>{preview}<ReferenceThumbnails assets={references} frames={frames} compact/></>}
      {stale}
      {!mediaNode&&status}
    </div>
    {mediaNode&&status&&<footer className="cv-node-footer">{status}</footer>}
  </article>
}
