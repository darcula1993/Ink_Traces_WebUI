import React,{useEffect,useRef,useState} from 'react'

// Menus own navigation keys; explicit save remains available through the studio handler.
export default function SidebarMenu({label,position,onClose,children,className='',focusKey='root'}) {
 const ref=useRef(null),closeRef=useRef(onClose),[style,setStyle]=useState({left:position.x,top:position.y})
 closeRef.current=onClose
 useEffect(()=>{
  const previous=document.activeElement,menu=ref.current
  const dismiss=e=>{if(!menu.contains(e.target))closeRef.current()}
  document.addEventListener('pointerdown',dismiss)
  return()=>{document.removeEventListener('pointerdown',dismiss);if(previous?.isConnected)previous.focus({preventScroll:true})}
 },[])
 useEffect(()=>{
  const menu=ref.current,box=menu.getBoundingClientRect()
  setStyle({left:Math.max(8,Math.min(position.x,window.innerWidth-box.width-8)),top:Math.max(8,Math.min(position.y,window.innerHeight-box.height-8))})
  const first=menu.querySelector('button:not(:disabled),input:not(:disabled),select:not(:disabled)');(first||menu).focus({preventScroll:true})
 },[focusKey])
 return <div ref={ref} tabIndex={-1} className={`cv-sidebar-menu ${className}`} style={style} role="menu" aria-label={label} onContextMenu={e=>e.preventDefault()} onPointerDown={e=>e.stopPropagation()} onKeyDown={e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s')return;e.stopPropagation();if(e.key==='Escape'){e.preventDefault();onClose()}if(['ArrowDown','ArrowUp','Tab','Home','End'].includes(e.key)&&!['INPUT','SELECT'].includes(e.target.tagName)){e.preventDefault();const items=[...ref.current.querySelectorAll('button:not(:disabled),input,select')],index=items.indexOf(document.activeElement);items[e.key==='Home'?0:e.key==='End'?items.length-1:(index+(e.key==='ArrowUp'||e.shiftKey?-1:1)+items.length)%items.length]?.focus()}}}>{children}</div>
}
export const menuPosition = event => {const rect=event.currentTarget.getBoundingClientRect();return event.type==='contextmenu'?{x:event.clientX,y:event.clientY}:{x:rect.left,y:rect.bottom+5}}
