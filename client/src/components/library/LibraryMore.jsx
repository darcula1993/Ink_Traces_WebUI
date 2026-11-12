import React,{useEffect,useRef,useState} from 'react'
import {MoreHorizontal} from 'lucide-react'
export default function LibraryMore({name,editKey,children}){
 const [open,setOpen]=useState(false),root=useRef(null),trigger=useRef(null),menu=useRef(null)
 const close=()=>{setOpen(false);trigger.current?.focus({preventScroll:true})}
 useEffect(()=>{if(!open)return;menu.current?.querySelector('button:not(:disabled)')?.focus();const outside=e=>{if(!root.current?.contains(e.target))setOpen(false)};document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside)},[open])
 return <span className="ul-more" ref={root} onBlur={e=>{if(e.relatedTarget&&!e.currentTarget.contains(e.relatedTarget))setOpen(false)}}><button data-library-edit={editKey} ref={trigger} aria-label={`更多操作 ${name}`} title={`更多操作 ${name}`} aria-expanded={open} onClick={()=>setOpen(!open)}><MoreHorizontal size={16}/></button>{open&&<div ref={menu} className="ul-more-menu" role="group" aria-label={`${name}操作`} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close()}if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const buttons=[...menu.current.querySelectorAll('button:not(:disabled)')],i=buttons.indexOf(document.activeElement);buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus()}}} onClick={e=>{if(e.target.closest('button')&&!e.target.closest('button').disabled)close()}}>{children}</div>}</span>
}
