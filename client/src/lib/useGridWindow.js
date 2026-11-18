import {useLayoutEffect, useRef, useState} from 'react'
import {columnCount, gridWindow} from './listWindow'

// Keep focused cards and their keyboard neighbours mounted separately from the viewport.
export default function useGridWindow(count, threshold=200) {
 const ref=useRef(null), [window,setWindow]=useState({start:0,end:Math.min(count,60),padTop:0,padBottom:0})
 useLayoutEffect(()=>{
  const grid=ref.current;if(!grid)return
  let parent=grid.parentElement
  while(parent && !/(auto|scroll)/.test(getComputedStyle(parent).overflowY))parent=parent.parentElement
  const scroller=parent||document.documentElement
  let frame=0
  const measure=()=>{
   frame=0
   const card=grid.querySelector('[data-window-card]');if(!card)return
   const style=getComputedStyle(grid), columns=columnCount(style.gridTemplateColumns)
   const stride=card.getBoundingClientRect().height+(parseFloat(style.rowGap)||0)
   const rect=grid.getBoundingClientRect(), viewport=scroller.getBoundingClientRect()
   const active=document.activeElement?.closest('[data-window-card]')
   const next=gridWindow({count,columns,stride,offset:viewport.top-rect.top,height:scroller.clientHeight,pin:-1})
   const pin=active&&grid.contains(active)?Number(active.dataset.windowCard):-1
   if(pin>=0 && (pin<next.start||pin>=next.end))next.pinned={index:pin,top:Math.floor(pin/columns)*stride,width:card.getBoundingClientRect().width,columns,stride,gap:parseFloat(style.columnGap)||0}
   setWindow(old=>old.start===next.start&&old.end===next.end&&old.padTop===next.padTop&&old.padBottom===next.padBottom&&JSON.stringify(old.pinned)===JSON.stringify(next.pinned)?old:next)
  }
  const schedule=()=>{if(!frame)frame=requestAnimationFrame(measure)}
  const observer=new ResizeObserver(schedule);observer.observe(grid);observer.observe(scroller)
  scroller.addEventListener('scroll',schedule,{passive:true});grid.addEventListener('focusin',schedule)
  measure()
  return()=>{cancelAnimationFrame(frame);observer.disconnect();scroller.removeEventListener('scroll',schedule);grid.removeEventListener('focusin',schedule)}
 },[count])
 const start=window.start>=count?0:window.start
 if(count<threshold)return {ref,start:0,end:count,padTop:0,padBottom:0}
 return {ref,...window,start,end:Math.min(count,window.end<=start?start+60:window.end),padTop:start===window.start?window.padTop:0}
}
