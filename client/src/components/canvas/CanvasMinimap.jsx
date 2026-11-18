import React,{useEffect,useMemo,useRef,useState} from 'react'
import {Map as MapIcon,Undo2,Redo2,Minus,Plus,LayoutGrid,CircleHelp,ChevronUp} from 'lucide-react'
import {nodeGeometry,nodeMediaKind} from './canvasGeometry'
import {minimapSize,minimapToWorld,minimapTransform,portToken,viewCenteredOn,viewPannedBy,viewportWorldRect,worldToMinimap} from './canvasChrome'
import {canvasModifier} from './CanvasShortcutHelp'
import './canvasChrome.css'

const cssVar=(el,name,fallback)=>{try{return getComputedStyle(el).getPropertyValue(name).trim()||fallback}catch{return fallback}}

// CANVAS-LAYOUT-2-20261118: bottom-left minimap (spec 3.2). Drawn with canvas 2D only when the document or the
// view changes, at most once per frame; nothing is drawn while closed (the caller unmounts it).
// Props: nodes, groups, view {x,y,zoom}, surface {width,height} (canvas surface px), selectedIds,
// onViewChange(nextView) (pan; zoom unchanged), onFit() (Enter), viewportWidth (window width, picks 160×100/200×124).
export default function CanvasMinimap({nodes=[],groups=[],view,surface,selectedIds=[],onViewChange,onFit,viewportWidth,geometry=nodeGeometry}) {
 const canvasRef=useRef(null),frame=useRef(0),drag=useRef(null)
 const size=minimapSize(viewportWidth??(typeof window!=='undefined'?window.innerWidth:0))
 const transform=useMemo(()=>minimapTransform(nodes,view,surface,size,geometry),[nodes,view,surface,size.width,size.height,geometry])
 const selected=useMemo(()=>new Set(selectedIds),[selectedIds])
 const frameRect=useMemo(()=>{const world=viewportWorldRect(view,surface),a=worldToMinimap(transform,world);return {x:a.x,y:a.y,width:world.width*transform.scale,height:world.height*transform.scale}},[transform,view,surface])
 useEffect(()=>{
  cancelAnimationFrame(frame.current)
  frame.current=requestAnimationFrame(()=>{
   const canvas=canvasRef.current;if(!canvas)return
   const ratio=window.devicePixelRatio||1,ctx=canvas.getContext('2d');if(!ctx)return
   if(canvas.width!==size.width*ratio)canvas.width=size.width*ratio;if(canvas.height!==size.height*ratio)canvas.height=size.height*ratio;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,size.width,size.height)
   const colors=Object.fromEntries(['image','video','audio'].map(kind=>[kind,cssVar(canvas,portToken(kind),'')]))
   const neutral=cssVar(canvas,'--cv-minimap-node','rgba(255,255,255,.35)'),focus=cssVar(canvas,'--cv-green','#45c088'),groupFill=cssVar(canvas,'--cv-minimap-group','rgba(255,255,255,.06)')
   const byId=new Map(nodes.map(node=>[node.id,node]))
   ctx.fillStyle=groupFill
   for(const group of groups||[]){const members=(group.nodeIds||[]).map(id=>byId.get(id)).filter(Boolean);if(!members.length)continue
    let x1=Infinity,y1=Infinity,x2=-Infinity,y2=-Infinity;for(const node of members){const g=geometry(node);x1=Math.min(x1,node.x);y1=Math.min(y1,node.y);x2=Math.max(x2,node.x+g.width);y2=Math.max(y2,node.y+g.height)}
    const a=worldToMinimap(transform,{x:x1-12,y:y1-12});ctx.fillRect(a.x,a.y,(x2-x1+24)*transform.scale,(y2-y1+24)*transform.scale)}
   for(const node of nodes){const g=geometry(node),a=worldToMinimap(transform,node),w=Math.max(2,g.width*transform.scale),h=Math.max(2,g.height*transform.scale)
    ctx.fillStyle=colors[nodeMediaKind(node)]||neutral;ctx.globalAlpha=.85;ctx.fillRect(a.x,a.y,w,h);ctx.globalAlpha=1
    if(selected.has(node.id)){ctx.strokeStyle=focus;ctx.lineWidth=1.5;ctx.strokeRect(a.x-1,a.y-1,w+2,h+2)}}
  })
  return ()=>cancelAnimationFrame(frame.current)
 },[nodes,groups,transform,selected,size.width,size.height,geometry])

 const local=event=>{const box=event.currentTarget.getBoundingClientRect();return {x:event.clientX-box.left,y:event.clientY-box.top}}
 const centerAt=point=>onViewChange?.(viewCenteredOn(minimapToWorld(transform,point),view,surface))
 const onPointerDown=event=>{
  if(event.button!==0)return
  event.preventDefault();event.stopPropagation()
  const point=local(event),inside=point.x>=frameRect.x&&point.x<=frameRect.x+frameRect.width&&point.y>=frameRect.y&&point.y<=frameRect.y+frameRect.height
  // Dragging the frame keeps the grab offset; a click elsewhere first centres the view on that point.
  const offset=inside?{x:point.x-(frameRect.x+frameRect.width/2),y:point.y-(frameRect.y+frameRect.height/2)}:{x:0,y:0}
  if(!inside)centerAt(point)
  drag.current={id:event.pointerId,offset,transform}
  event.currentTarget.setPointerCapture?.(event.pointerId)
 }
 const onPointerMove=event=>{const current=drag.current;if(!current||current.id!==event.pointerId)return;event.preventDefault();const point=local(event)
  // Use the transform from the gesture start so the map does not rescale under the pointer.
  onViewChange?.(viewCenteredOn(minimapToWorld(current.transform,{x:point.x-current.offset.x,y:point.y-current.offset.y}),view,surface))}
 const end=event=>{if(drag.current?.id===event.pointerId)drag.current=null}
 const onKeyDown=event=>{
  if(event.key==='Enter'){event.preventDefault();event.stopPropagation();onFit?.();return}
  const next=viewPannedBy(view,surface,event.key)
  if(next){event.preventDefault();event.stopPropagation();onViewChange?.(next)}
 }
 const summary=`画布小地图，${nodes.length} 个节点，当前显示区域约 ${Math.round(Math.min(100,(frameRect.width*frameRect.height)/(size.width*size.height)*100))}%。方向键平移，回车适配全部`
 return <div className="cv-minimap" style={{width:size.width,height:size.height}} role="application" aria-label="画布小地图" aria-description={summary} title="画布小地图：点击或拖动视口框平移" tabIndex={0}
  onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end} onKeyDown={onKeyDown}>
  <canvas ref={canvasRef} aria-hidden="true" style={{width:size.width,height:size.height}}/>
  <div className="cv-minimap-frame" aria-hidden="true" style={{left:frameRect.x,top:frameRect.y,width:frameRect.width,height:frameRect.height}}/>
 </div>
}

const PRESETS=[['适配全部','fit'],['50%',.5],['100%',1],['200%',2]]
// Bottom-left cluster (spec 3.2): minimap switch, undo, redo, zoom out, percentage (presets), zoom in,
// organize, shortcut help. Undo/redo keep their described-by text, shortcuts and disabled rules (caller).
// `children` is the minimap, rendered above the cluster when `minimapOpen`.
export function CanvasViewportTools({zoom=1,onZoomIn,onZoomOut,onZoomTo,onFit,onOrganize,organizeDisabled=false,canUndo=false,canRedo=false,undoDescription='',redoDescription='',onUndo,onRedo,onShortcuts,minimapOpen=false,onToggleMinimap,children}) {
 const [presets,setPresets]=useState(false),root=useRef(null)
 const percent=Math.round(zoom*100),modifier=canvasModifier()
 useEffect(()=>{if(!presets)return undefined;const close=event=>{if(!root.current?.contains(event.target))setPresets(false)};window.addEventListener('pointerdown',close,true);return ()=>window.removeEventListener('pointerdown',close,true)},[presets])
 const choose=value=>{setPresets(false);if(value==='fit')onFit?.();else onZoomTo?.(value)}
 return <div ref={root} className="cv-viewport-tools" onPointerDown={e=>e.stopPropagation()}>
  {minimapOpen&&children}
  <div className="cv-viewport-bar" role="toolbar" aria-label="画布视图">
   <button type="button" aria-label="小地图" title={minimapOpen?'隐藏小地图':'显示小地图'} aria-pressed={minimapOpen} onClick={()=>onToggleMinimap?.(!minimapOpen)}><MapIcon size={14}/></button>
   <span id="cv-undo-description" className="cv-sr-only">{undoDescription?`可撤销：${undoDescription}`:'可撤销：无'}</span><span id="cv-redo-description" className="cv-sr-only">{redoDescription?`可重做：${redoDescription}`:'可重做：无'}</span>
   <button type="button" aria-label="撤销画布编辑" aria-describedby="cv-undo-description" title={`${undoDescription?'撤销：'+undoDescription:'暂无可撤销操作'} (${modifier}+Z)`} disabled={!canUndo} onClick={onUndo}><Undo2 size={14}/></button>
   <button type="button" aria-label="重做画布编辑" aria-describedby="cv-redo-description" title={`${redoDescription?'重做：'+redoDescription:'暂无可重做操作'} (${modifier}+Shift+Z)`} disabled={!canRedo} onClick={onRedo}><Redo2 size={14}/></button>
   <span className="cv-viewport-sep" aria-hidden="true"/>
   <button type="button" aria-label="缩小画布" title="缩小画布" onClick={onZoomOut}><Minus size={14}/></button>
   <span className="cv-zoom-presets"><button type="button" className="cv-zoom-value" aria-label={`画布缩放 ${percent}%`} title="缩放预设" aria-haspopup="menu" aria-expanded={presets} onClick={()=>setPresets(open=>!open)}>{percent}%<ChevronUp size={11} aria-hidden="true"/></button>
    {presets&&<div className="cv-zoom-menu" role="menu" aria-label="缩放预设" onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();setPresets(false)}}}>{PRESETS.map(([label,value])=><button key={label} type="button" role="menuitem" onClick={()=>choose(value)}>{label}</button>)}</div>}</span>
   <button type="button" aria-label="放大画布" title="放大画布" onClick={onZoomIn}><Plus size={14}/></button>
   <span className="cv-viewport-sep" aria-hidden="true"/>
   <button type="button" aria-label="整理画布" title="按依赖从左到右整理，保留组内布局；可撤销" disabled={organizeDisabled} onClick={onOrganize}><LayoutGrid size={14}/></button>
   <button type="button" aria-label="画布快捷键帮助" title="画布快捷键帮助 (?)" onClick={onShortcuts}><CircleHelp size={14}/></button>
  </div>
 </div>
}
