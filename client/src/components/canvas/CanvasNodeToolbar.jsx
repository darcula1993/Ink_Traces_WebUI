import React,{forwardRef,useImperativeHandle,useLayoutEffect,useRef,useState} from 'react'
import {Crop,RotateCw,PenLine,Layers3,Download,Eye,Play,History,MoreHorizontal} from 'lucide-react'
import {CaptureCurrentFrameIcon,CaptureTailFrameIcon} from '../art/CanvasLibraryArt'
import {nodeToolbarKind,nodeToolbarActions,nodeToolbarPlacement} from './canvasChrome'
import './canvasChrome.css'

const ICONS={edit:Crop,rotate:RotateCw,annotate:PenLine,layer:Layers3,download:Download,preview:Eye,history:History,more:MoreHorizontal,captureCurrent:CaptureCurrentFrameIcon,captureTail:CaptureTailFrameIcon}

// CANVAS-LAYOUT-2-20261118: icon toolbar above the single selected image node (asset node, or image
// generation node with an image result — user 11-17 Q5). Shows one button per supplied handler
// (onEdit/onRotate/onAnnotate/onDownload/onPreview/onHistory/onMore); `onMore(event)` gets the click event.
// NODE-TOOLBAR-VERSIONS-20261118: also above a video generation node with a result (onHistory/onCaptureCurrent/
// onCaptureTail/onPreview/onDownload/onMore). A disabled action (single version) stays focusable via aria-disabled so
// its reason is readable; `captureNote` describes what 截取当前帧 will take. ref.focusAction(id) refocuses a button.
// Placement: pass the node's screen `rect` and the `surface` size (see nodeScreenRect), or a fixed `style`.
// Visibility rules (multi-select, drag, connect, annotate, deleted) belong to the caller: nodeToolbarVisible.
// The ref exposes focus() (Alt+T); Esc calls onEscape so the caller can return focus to the node.
const CanvasNodeToolbar=forwardRef(function CanvasNodeToolbar({node,rect,surface,avoid,style,label='图片操作',busy=false,onEscape,captureNote,historyOpen=false,...handlers},ref){
 const root=useRef(null),[size,setSize]=useState(null)
 const actions=nodeToolbarActions(node,handlers)
 useLayoutEffect(()=>{const el=root.current;if(el&&!style){const next={width:el.offsetWidth,height:el.offsetHeight};if(!size||size.width!==next.width||size.height!==next.height)setSize(next)}})
 useImperativeHandle(ref,()=>({focus:()=>root.current?.querySelector('button:not(:disabled)')?.focus(),focusAction:id=>root.current?.querySelector(`button[data-action="${id}"]`)?.focus()}),[])
 const kind=nodeToolbarKind(node)
 if(!actions.length||!kind)return null
 const place=style?null:nodeToolbarPlacement(rect,surface,size||{width:0,height:0},{avoid})
 if(!style&&!place)return null
 const position=style||{left:place.left,top:place.top,visibility:size?undefined:'hidden'}
 const onKeyDown=event=>{
  const buttons=[...root.current.querySelectorAll('button:not(:disabled)')],index=buttons.indexOf(document.activeElement)
  if(event.key==='ArrowRight'||event.key==='ArrowLeft'){event.preventDefault();event.stopPropagation();const next=buttons[(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length];next?.focus()}
  else if(event.key==='Home'||event.key==='End'){event.preventDefault();event.stopPropagation();buttons[event.key==='Home'?0:buttons.length-1]?.focus()}
  else if(event.key==='Escape'&&onEscape){event.preventDefault();event.stopPropagation();onEscape()}
 }
 return <div ref={root} className="cv-image-toolbar cv-node-toolbar" style={position} role="toolbar" aria-label={label} aria-orientation="horizontal" onPointerDown={e=>e.stopPropagation()} onKeyDown={onKeyDown}>
  {actions.map(action=>{const Icon=kind==='audio'&&action.id==='preview'?Play:ICONS[action.id],blocked=busy&&action.id!=='more',unavailable=!!action.disabled,title=action.id==='captureCurrent'&&captureNote?`${action.title}（${captureNote}）`:action.title
   return <button key={action.id} type="button" className="cv-node-toolbar-button" data-action={action.id} aria-label={action.label} title={title} aria-description={unavailable?action.reason:action.id==='captureCurrent'?captureNote:undefined} disabled={blocked} aria-disabled={unavailable||undefined} aria-haspopup={action.id==='history'&&!unavailable?'dialog':undefined} aria-expanded={action.id==='history'&&!unavailable?historyOpen:undefined} onClick={event=>{if(!unavailable)handlers[action.handler](event)}}><Icon size={15} aria-hidden="true"/></button>})}
 </div>
})
export default CanvasNodeToolbar
