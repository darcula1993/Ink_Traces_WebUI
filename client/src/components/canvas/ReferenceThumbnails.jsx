import {Music,Plus,Trash2,X} from 'lucide-react'
import {isMediaAsset,isDeletedMedia,isTrashedMedia} from '../../lib/canvasMediaStatus'
import React,{useState} from 'react'
import './canvasPorts.css'
const KIND={image:'图片',video:'视频',audio:'音频'}
// `onAdd` (CANVAS-LAYOUT-2-WIRE, spec 1.3): trailing “+” on the card's reference row (selected generation node).
// `onRemove` & `onPreview` (P1-CANVAS-WORKFLOW-20261120 P1-1): per-item remove button and click-to-preview in the right panel.
export default function ReferenceThumbnails({assets, compact=false, frames,onReorder,onRemove,onPreview,onAdd,addLabel='添加参考素材'}) {
  const [dragging,setDragging]=useState(null),[dropTarget,setDropTarget]=useState(null)
  const move=(from,to)=>{if(from===to)return;const order=assets.map(asset=>asset.id),[id]=order.splice(from,1);order.splice(to,0,id);onReorder?.(order)}
  if(!assets.length&&!onAdd) return null
  // CANVAS-PORTS-UI-20261118 (user 11-17 Q1): numbered per kind (图片1、视频1…) = port number = @图片N; kind-colour corner.
  const kindNumber=index=>assets.slice(0,index+1).filter(item=>item.kind===assets[index].kind).length
  return <div className={`cv-reference-thumbnails ${compact?'is-compact':''}`} aria-label="接入参考素材">{assets.map((asset,index)=>{
    const deleted=isMediaAsset(asset)&&isDeletedMedia(asset.id),num=kindNumber(index),kindText=KIND[asset.kind]||asset.kind,fallbackName=`${kindText}参考 ${num}`
    const media=deleted?<span className="cv-reference-deleted" title={isTrashedMedia(asset.id)?`${asset.name||''} 所在任务在回收站`:`${asset.name||''} 已在素材库中删除`} role="img" aria-label={`${asset.name||'参考素材'}（${isTrashedMedia(asset.id)?'在回收站':'已删除'}）`}><Trash2 size={14} strokeWidth={1.7} aria-hidden="true"/></span>
      :asset.kind==='image'?<img src={asset.url} alt={asset.name || '图片参考'} loading="lazy" draggable={false}/>
      :asset.kind==='video'?<video src={asset.url} muted preload="metadata" onLoadedMetadata={e=>{const video=e.currentTarget;if(Number.isFinite(video.duration)&&video.duration>0)video.currentTime=Math.min(.05,video.duration/2)}} aria-label={asset.name || '视频参考'}/>
      :<span className="cv-audio-reference" aria-label={asset.name || '音频参考'}><Music size={13} aria-hidden="true"/> 音频</span>
    const previewable=Boolean(onPreview)&&!deleted&&Boolean(asset.url)
    return <span key={asset.id} className={`cv-reference-thumb ${dragging===asset.id?'is-dragging':''} ${dropTarget===asset.id?'is-drop-target':''} ${previewable?'is-previewable':''}`} draggable={Boolean(onReorder)} onDragStart={event=>{if(!onReorder)return;event.stopPropagation();event.dataTransfer.setData('application/x-canvas-reference',asset.id);event.dataTransfer.effectAllowed='move';setDragging(asset.id)}} onDragOver={event=>{if(!onReorder||!event.dataTransfer.types.includes('application/x-canvas-reference'))return;event.preventDefault();event.stopPropagation();event.dataTransfer.dropEffect='move';setDropTarget(asset.id)}} onDrop={event=>{if(!onReorder||!event.dataTransfer.types.includes('application/x-canvas-reference'))return;event.preventDefault();event.stopPropagation();const from=assets.findIndex(item=>item.id===event.dataTransfer.getData('application/x-canvas-reference'));if(from>=0)move(from,index);setDragging(null);setDropTarget(null)}} onDragEnd={()=>{setDragging(null);setDropTarget(null)}} title={`${fallbackName} · ${asset.name || asset.id}`} data-reference-id={asset.id} data-kind={asset.kind}>
      <b className="cv-reference-number" aria-label={fallbackName}>{num}</b>
      {previewable?<button type="button" className="cv-reference-preview-btn" aria-label={`预览参考 ${asset.name||fallbackName}`} title={`点击查看大图：${asset.name||fallbackName}`} onPointerDown={event=>event.stopPropagation()} onClick={event=>{event.stopPropagation();onPreview(asset,assets)}}>{media}</button>:media}
      {(frames?.first?.id===asset.id || frames?.last?.id===asset.id) && <em className="cv-reference-role">{frames?.first?.id===asset.id?'首帧':'尾帧'}</em>}
      {onRemove&&<button type="button" className="cv-reference-remove" data-testid="reference-remove" aria-label={`移除参考 ${asset.name||fallbackName}`} title={`移除此参考：${asset.name||fallbackName}`} onPointerDown={event=>event.stopPropagation()} onClick={event=>{event.stopPropagation();onRemove(asset)}}><X size={11} aria-hidden="true"/></button>}
      {onReorder&&<span className="cv-reference-order-tools"><button type="button" disabled={index===0} aria-label={`前移 ${asset.name||asset.id}`} title="向前移动参考素材" onClick={()=>move(index,index-1)}>‹</button><button type="button" disabled={index===assets.length-1} aria-label={`后移 ${asset.name||asset.id}`} title="向后移动参考素材" onClick={()=>move(index,index+1)}>›</button></span>}
    </span>
  })}{onAdd&&<button type="button" className="cv-reference-add" aria-label={addLabel} title={addLabel} onPointerDown={event=>event.stopPropagation()} onClick={event=>{event.stopPropagation();onAdd()}}><Plus size={14} aria-hidden="true"/></button>}</div>
}
