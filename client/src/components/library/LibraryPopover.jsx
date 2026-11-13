import React,{useEffect,useRef} from 'react'
// Floating panel anchored to its trigger. It overlays the grid instead of
// pushing it down; Escape and outside clicks close it and focus returns to the trigger.
export default function LibraryPopover({label,role='group',trigger,onClose,children}){
 const ref=useRef(null),closeRef=useRef(onClose)
 closeRef.current=onClose
 useEffect(()=>{
  ref.current?.querySelector('button:not(:disabled),select:not(:disabled),input:not(:disabled)')?.focus({preventScroll:true})
  const outside=e=>{if(e.target.closest?.('.ui-select-menu'))return;if(!ref.current?.contains(e.target)&&!trigger?.current?.contains(e.target))closeRef.current()}
  document.addEventListener('pointerdown',outside)
  return()=>document.removeEventListener('pointerdown',outside)
 },[trigger])
 const close=()=>{closeRef.current();trigger?.current?.focus({preventScroll:true})}
 return <div ref={ref} className="ul-popover" role={role} aria-label={label} onKeyDown={e=>{
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();return}
  if(role==='menu'&&['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const items=[...ref.current.querySelectorAll('button:not(:disabled)')],i=items.indexOf(document.activeElement);items[e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus()}
 }} onClick={e=>{if(role==='menu'&&e.target.closest('button:not(:disabled)'))closeRef.current()}}>{children}</div>
}
