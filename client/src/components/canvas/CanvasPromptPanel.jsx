import React,{useEffect,useMemo,useRef,useState} from 'react'
import {CornerDownLeft,RefreshCw} from 'lucide-react'
import {filterPrompts,nextActiveIndex} from '../../lib/promptLibrary'
import {PromptLibraryList,usePromptLibrary} from './PromptLibraryPicker'

// CANVAS-LAYOUT-2-20261118: rail panel "提示词库" (search, list, preview, insert into the selected node).
// The caller decides the target: `insertDisabledReason` (string) disables the button and is read out;
// `onInsert(text)` inserts at the card prompt's caret (see insertPromptText in PromptLibraryPicker).
export default function CanvasPromptPanel({onInsert,insertDisabledReason='请先选中一个生成节点',targetLabel=''}) {
 const {prompts,status,loading,load}=usePromptLibrary()
 const [query,setQuery]=useState(''),[active,setActive]=useState(0),[notice,setNotice]=useState('')
 const searchRef=useRef(null)
 const visible=useMemo(()=>filterPrompts(prompts,query),[prompts,query])
 useEffect(()=>{load()},[])
 useEffect(()=>{setActive(0)},[query])
 const current=visible[Math.min(active,visible.length-1)]||null
 const disabled=!!insertDisabledReason||!current||typeof onInsert!=='function'
 const reason=insertDisabledReason||(!current?'没有可插入的提示词':'')
 const insert=prompt=>{if(!prompt||insertDisabledReason||typeof onInsert!=='function')return;onInsert(prompt.text);setNotice(targetLabel?`已插入到「${targetLabel}」`:'已插入到选中节点')}
 const onKeyDown=event=>{
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();setActive(index=>nextActiveIndex(index,visible.length,event.key))}
  else if(event.key==='Enter'&&!event.nativeEvent?.isComposing&&event.target===searchRef.current){event.preventDefault();insert(current)}
 }
 return <div className="cv-panel-prompts" onKeyDown={onKeyDown}>
  <div className="cv-panel-prompts-search"><PromptLibraryList listId="cv-prompt-panel-list" optionPrefix="cv-prompt-panel-option-" inputRef={searchRef} query={query} onQuery={setQuery} prompts={prompts} visible={visible} active={active} onActive={setActive} onPick={(prompt,index)=>setActive(index)} loading={loading} pickOn="click" optionTitle="选择以预览"/></div>
  {current&&<section className="cv-panel-prompts-preview" aria-label="提示词预览"><p>{current.text}</p></section>}
  <div className="cv-panel-prompts-actions">
   <button type="button" className="btn btn-primary btn-sm" disabled={disabled} aria-describedby={reason?'cv-prompt-panel-reason':undefined} title={reason||'插入到选中节点提示词的光标处'} onClick={()=>insert(current)}><CornerDownLeft size={13} aria-hidden="true"/>插入到选中节点</button>
   <button type="button" className="btn btn-ghost btn-sm btn-icon" aria-label="刷新提示词库" title="刷新提示词库" disabled={loading} onClick={load}><RefreshCw size={13} aria-hidden="true"/></button>
  </div>
  {reason&&<small id="cv-prompt-panel-reason" className="cv-panel-hint">{reason}</small>}
  <span className="cv-panel-status" role="status" aria-live="polite">{status||notice}</span>
 </div>
}
