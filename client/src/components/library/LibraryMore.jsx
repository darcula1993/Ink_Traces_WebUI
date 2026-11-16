import React,{useEffect,useLayoutEffect,useRef,useState} from 'react'
import {MoreHorizontal} from 'lucide-react'
// The menu is position:fixed so the grid's scroll container cannot clip it. It opens below
// the trigger when there is room, otherwise above, and is clamped inside the dialog (or viewport).
// Scrolling re-places it next to its trigger (a scroll-into-view right after opening must not close it,
// LIBRARY-GLOBAL S7); it closes when the trigger leaves its scroll container, or on resize.
const GAP=4,MARGIN=8
function scrollParent(node){for(let el=node?.parentElement;el;el=el.parentElement){const {overflowY}=getComputedStyle(el);if(/(auto|scroll)/.test(overflowY)&&el.scrollHeight>el.clientHeight)return el}return null}
// True while the trigger is still visible inside its scroll container.
export function triggerVisible(trigger){const t=trigger.getBoundingClientRect(),box=scrollParent(trigger)?.getBoundingClientRect();if(!t.width&&!t.height)return false;return !box||t.bottom>box.top&&t.top<box.bottom&&t.right>box.left&&t.left<box.right}
function placeMenu(trigger,menu){
 const t=trigger.getBoundingClientRect(),dialog=trigger.closest('[role=dialog]')?.getBoundingClientRect()
 const bounds={top:Math.max(MARGIN,(dialog?.top??0)+MARGIN),bottom:Math.min(window.innerHeight,dialog?.bottom??window.innerHeight)-MARGIN,left:Math.max(MARGIN,(dialog?.left??0)+MARGIN),right:Math.min(window.innerWidth,dialog?.right??window.innerWidth)-MARGIN}
 menu.style.maxHeight='';menu.style.left='0px';menu.style.top='0px'
 // A transformed / backdrop-filtered ancestor becomes the containing block of fixed elements; measure its offset.
 // A zoomed ancestor (.ul-library is zoom:1.2 on wide screens) scales style px: measure that factor too.
 const origin=menu.getBoundingClientRect()
 menu.style.left='100px';menu.style.top='100px'
 const probe=menu.getBoundingClientRect(),sx=(probe.left-origin.left)/100||1,sy=(probe.top-origin.top)/100||1
 const w=origin.width,h=origin.height
 const below=bounds.bottom-(t.bottom+GAP),above=(t.top-GAP)-bounds.top
 const down=below>=h||below>=above,room=Math.max(0,down?below:above)
 if(h>room)menu.style.maxHeight=`${Math.floor(room/sy)}px`
 const height=Math.min(h,room),top=down?t.bottom+GAP:t.top-GAP-height
 const left=Math.min(Math.max(t.right-w,bounds.left),Math.max(bounds.left,bounds.right-w))
 menu.style.left=`${Math.round((left-origin.left)/sx)}px`;menu.style.top=`${Math.round((top-origin.top)/sy)}px`
 menu.dataset.placement=down?'bottom':'top'
}
export default function LibraryMore({name,editKey,children}){
 const [open,setOpen]=useState(false),root=useRef(null),trigger=useRef(null),menu=useRef(null)
 const close=()=>{setOpen(false);trigger.current?.focus({preventScroll:true})}
 useLayoutEffect(()=>{if(open&&trigger.current&&menu.current)placeMenu(trigger.current,menu.current)},[open])
 useEffect(()=>{if(!open)return;menu.current?.querySelector('button:not(:disabled)')?.focus({preventScroll:true});const outside=e=>{if(!root.current?.contains(e.target))setOpen(false)},dismiss=e=>{if(menu.current?.contains(e.target))return;if(trigger.current&&menu.current&&triggerVisible(trigger.current))placeMenu(trigger.current,menu.current);else setOpen(false)},resize=()=>setOpen(false);document.addEventListener('pointerdown',outside);document.addEventListener('scroll',dismiss,true);window.addEventListener('resize',resize);return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('scroll',dismiss,true);window.removeEventListener('resize',resize)}},[open])
 return <span className="ul-more" ref={root} onBlur={e=>{if(e.relatedTarget&&!e.currentTarget.contains(e.relatedTarget))setOpen(false)}}><button data-library-edit={editKey} ref={trigger} aria-label={`更多操作 ${name}`} title={`更多操作 ${name}`} aria-haspopup="true" aria-expanded={open} onClick={()=>setOpen(!open)}><MoreHorizontal size={16}/></button>{open&&<div ref={menu} className="ul-more-menu" role="group" aria-label={`${name}操作`} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close()}if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const buttons=[...menu.current.querySelectorAll('button:not(:disabled)')],i=buttons.indexOf(document.activeElement);buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus()}}} onClick={e=>{if(e.target.closest('button')&&!e.target.closest('button').disabled)close()}}>{children}</div>}</span>
}
