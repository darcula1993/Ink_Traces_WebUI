import React from 'react'
import CanvasGroupColors from './CanvasGroupColors'
import {resolveNodeInputs} from '../../lib/canvasReferences'
import {groupBounds} from '../../lib/canvasGroups'
import './canvasFeedback.css'

// INTEG-FIX-GROUPS-20261114: below 100% the counter-scaled button bar (FIX-B2B) covers most of the group
// header, so the controls double as drag handles: a press that moves >=4px drags the group, a press
// that does not move stays a normal click (no selection change, native focus and keyboard unchanged).
export function groupControlPointerDown(event,startDrag){
  event.stopPropagation()
  if(event.button!==0||!event.isPrimary)return
  const start=event,id=event.pointerId
  const cleanup=()=>{window.removeEventListener('pointermove',move,true);window.removeEventListener('pointerup',cleanup,true);window.removeEventListener('pointercancel',cleanup,true)}
  function move(e){if(e.pointerId!==id||Math.hypot(e.clientX-start.clientX,e.clientY-start.clientY)<4)return;cleanup();startDrag(start)}
  window.addEventListener('pointermove',move,true);window.addEventListener('pointerup',cleanup,true);window.addEventListener('pointercancel',cleanup,true)
}
export default function CanvasGroups({groups=[],nodes,onDrag,onLocate,onRename,onColor,onUngroup,onCopy,onUpload,onLibrary,onLocateSource,edges=[],disabled}){return groups.map(group=>{const bounds=groupBounds(group,nodes);if(!bounds)return null;const owner=nodes.find(node=>node.id===group.keyframeNodeId),frames=owner?resolveNodeInputs(owner,nodes,edges).frames:null;const control=event=>groupControlPointerDown(event,start=>onDrag(start,group));return <section key={group.id} data-group-id={group.id} data-color={group.color||'green'} className="cv-node-group" style={{left:bounds.x,top:bounds.y,width:bounds.width,height:bounds.height}}><header onPointerDown={event=>onDrag(event,group)}><button aria-label={`定位节点组 ${group.title}`} onPointerDown={control} onClick={()=>onLocate(group)}>{group.title}</button><span/><CanvasGroupColors group={group} disabled={disabled} onChange={onColor} onSummaryPointerDown={control}/><button disabled={disabled} onPointerDown={control} onClick={()=>onRename(group)}>命名</button><button disabled={disabled} onPointerDown={control} onClick={()=>onCopy(group)}>复制组</button><button disabled={disabled} onPointerDown={control} onClick={()=>onUngroup(group)}>解组</button></header>{owner&&['first','last'].map((role,index)=>{const asset=frames?.[role],source=asset&&nodes.find(node=>group.nodeIds.includes(node.id)&&node.asset?.id===asset?.id);const original=owner&&edges.filter(edge=>edge.target===owner.id).map(edge=>nodes.find(node=>node.id===edge.source)).find(node=>asset&&node?.asset?.id===asset.id);return source?<span key={role} className="cv-frame-label" style={{left:source.x-bounds.x+12,top:source.y-bounds.y+30}}>{index?'尾帧':'首帧'}</span>:<div key={role} className="cv-frame-slot" onPointerDown={e=>e.stopPropagation()} style={{left:owner.x-350-bounds.x,top:owner.y+index*280-bounds.y}}><strong>{index?(asset?'尾帧':'尾帧（可选）'):'首帧'}</strong>{asset?<><img src={asset.url} alt={asset.name||'外部参考'} title={asset.name||undefined}/><small title={asset.name||undefined}>外部引用</small>{original&&<button onClick={()=>onLocateSource(original.id)}>定位原节点</button>}</>:<><button disabled={disabled} onClick={()=>onUpload(owner.id)}>上传{index?'尾帧':'首帧'}</button><button disabled={disabled} onClick={()=>onLibrary(owner.id)}>选择{index?'尾帧':'首帧'}素材</button></>}</div>})}</section>})}
