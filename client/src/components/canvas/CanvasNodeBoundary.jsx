import React,{memo,useLayoutEffect,useRef} from 'react'
import CanvasNode from './CanvasNode'
import {shareNodeProps} from './nodePropSharing'

const MemoNode=memo(CanvasNode)
MemoNode.displayName='CanvasNodeCard'
// The boundary refreshes callbacks after every committed render, while the expensive card
// receives stable props when only another node moved. Never ignore callbacks in a comparator:
// doing that retains closures from the wrong selection/workflow.
export default function CanvasNodeBoundary(props){
 const live=useRef(props),callbacks=useRef(new Map()),previous=useRef()
 useLayoutEffect(()=>{live.current=props})
 const next=shareNodeProps(props,previous.current,(path)=>{
  const key=JSON.stringify(path)
  if(!callbacks.current.has(key))callbacks.current.set(key,(...args)=>{
   let fn=live.current
   for(const part of path)fn=fn?.[part]
   return typeof fn==='function'?fn(...args):undefined
  })
  return callbacks.current.get(key)
 })
 previous.current=next
 return <MemoNode {...next}/>
}

CanvasNodeBoundary.displayName='CanvasNodeBoundary'
