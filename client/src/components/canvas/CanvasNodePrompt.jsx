import React,{useEffect,useMemo,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import {ArrowUp,AtSign,ChevronDown,ChevronUp,Maximize2,UserRound,X} from 'lucide-react'
import PromptMentionTextarea from '../PromptMentionTextarea'
import PromptLibraryPicker,{insertPromptText} from './PromptLibraryPicker'
import {referenceTokenState} from '../../lib/canvasReferences'
import {referenceTokenRanges} from '../../lib/referenceMedia'
import {splitCharacterPromptBlock,joinCharacterPromptBlock,formatCharacterBadgeLabel} from '../../lib/characterCardCollapse'
import {useCanvasEstimate} from './CanvasVideoEstimate'
import './cardPrompt.css'

// P1-CANVAS-WORKFLOW-20261120 (P2): render @mentions with the same valid/invalid tint in read-only card previews.
export function renderPromptPreviewTokens(text, tokenState) {
 const safe = String(text || '')
 const ranges = referenceTokenRanges(safe)
 if (!ranges.length) return safe
 const parts = []
 let cursor = 0
 for (const range of ranges) {
  if (range.start > cursor) parts.push(safe.slice(cursor, range.start))
  parts.push(<mark key={range.start} className={`prompt-reference-token is-${tokenState(range.token)}`}>{safe.slice(range.start, range.end)}</mark>)
  cursor = range.end
 }
 if (cursor < safe.length) parts.push(safe.slice(cursor))
 return parts
}

// FIX-B2B-20261114: prompt placeholder per node type. CARD-PROMPT-READABLE-20261118 (user 11-18): one short wording
// for image / video / audio (card, read-only preview and the large dialog); text nodes keep their own.
const PROMPT_PLACEHOLDER='输入提示词…'
const PROMPT_PLACEHOLDERS={image:PROMPT_PLACEHOLDER,video:PROMPT_PLACEHOLDER,audio:PROMPT_PLACEHOLDER,text:'输入故事、对白或提示词…'}
export const promptPlaceholder=type=>PROMPT_PLACEHOLDERS[type]||PROMPT_PLACEHOLDERS.text
const promptLabel=node=>`${node.title}的${node.type==='text'?'文本':'提示词'}`

// The @-aware prompt editor (card and dialog share it). Mentions, character inserts and the stale-mention rule
// come from useNodeCharacters; text changes go straight to the node.
function PromptEditor({node,inputAssets,editor,onText,valueOverride,onValueChangeOverride,onMentionSelectOverride,className,onKeyDown,autoFocus,filterMentionItems,onBlur}) {
 const mentions=node.type!=='text'&&editor
 const value=valueOverride!==undefined?valueOverride:(node.text||'')
 const onValueChange=onValueChangeOverride||(text=>{editor?.setMentionError('');onText(text)})
 const onMentionSelect=onMentionSelectOverride!==undefined?onMentionSelectOverride:(mentions?editor.onMentionSelect:undefined)
 return <PromptMentionTextarea wrapperClassName="cv-prompt-mention" menuClassName="cv-mention-menu" className={className} aria-label={promptLabel(node)} aria-describedby={mentions&&(editor.mentionError||editor.mentionIssues.length)?`cv-prompt-issue-${node.id}`:undefined} aria-invalid={mentions&&(editor.mentionError||editor.mentionIssues.length)?true:undefined} value={value} mentionItems={mentions?editor.mentionItems:[]} referenceTokenState={referenceTokenState(node,inputAssets)} placeholder={promptPlaceholder(node.type)} autoFocus={autoFocus} onKeyDown={onKeyDown} onValueChange={onValueChange} onMentionSelect={onMentionSelect} filterMentionItems={filterMentionItems} onBlur={onBlur}/>
}

// CANVAS-LAYOUT-1-20261117 (user decision 11-17): the prompt lives in the node card again. Only the single
// selected node at a readable zoom gets the editable textarea; every other card (and any card below LOD_ZOOM)
// shows read-only text that selects the node and focuses the prompt, or opens the larger dialog when zoomed out.
// A small 生成 button (selected node only) calls the same request as the right panel's button. The prompt-library
// picker inserts at the card caret from the panel's 提示词 section (its compact card icon comes with layout step 2).
// PROMPT-OVERFLOW-20261118 (user 11-18): a 展开编辑 icon on every generation card (any zoom) restores the old panel's
// "扩大" entry: it opens the same dialog, and closing the dialog returns focus to this button.
// CARD-PROMPT-RESIZE-20261118 (user 11-18, scheme A): generation cards get a bottom band — a full-width borderless text
// area plus a tool row (left 提示词库 / @角色卡 on the editable card; right 展开编辑, cost, ↑生成). Same handlers as before.
// V24-W2-CHAR-CARD-20261121: when a generation card starts with a 【人物】/【物件】 character block, fold it by default
// into a 1-line badge above the textarea so the story body is visible immediately; clicking the badge toggles the
// full plaintext inline while keeping the underlying prompt byte-for-byte intact.
export default function CanvasNodePrompt({node,editable,inputAssets=[],editor,onText,onActivate,onExpand,focusRequest=0,generate}) {
 const rootRef=useRef(null),characterAt=useRef(null)
 const [expandedBlock,setExpandedBlock]=useState(false)
 useEffect(()=>{if(editable&&focusRequest)rootRef.current?.querySelector('textarea')?.focus({preventScroll:true})},[focusRequest,editable])
 const text=node.text||'',issue=node.type!=='text'&&editor&&(editor.mentionError||editor.mentionIssues.length>0)
 const split=useMemo(()=>node.type==='text'?{block:'',names:[],body:text}:splitCharacterPromptBlock(text),[node.type,text])
 const hasBlock=Boolean(split.block&&split.names.length)
 useEffect(()=>{setExpandedBlock(false)},[node.id])
 useEffect(()=>{if(!editable)setExpandedBlock(false)},[editable])
 useEffect(()=>{if(!hasBlock&&expandedBlock)setExpandedBlock(false)},[hasBlock,expandedBlock])
 const collapsed=hasBlock&&!expandedBlock
 const displayText=collapsed?split.body:text
 const stop=event=>event.stopPropagation()
 // User 11-18: the menu opened by the card's @角色卡 button lists character cards only; a typed @ keeps the full menu
 // (references + character cards). Only the mention that starts at the button's own "@" is filtered.
 const charactersOnly=(items,mention)=>characterAt.current!=null&&mention.start===characterAt.current?items.filter(item=>item.type==='character'):items
 const handleEditText=nextDisplay=>{editor?.setMentionError('');onText(collapsed?joinCharacterPromptBlock(split.block,nextDisplay):nextDisplay)}
 const handleMentionSelect=node.type!=='text'&&editor?(item,mention)=>{
  const offset=collapsed?split.block.length:0
  const fullMention=offset?{...mention,start:mention.start+offset,end:mention.end+offset}:mention
  const handled=editor.onMentionSelect(item,fullMention)
  if(handled&&typeof handled.then==='function'){
   return handled.then(cursor=>{
    if(!Number.isInteger(cursor))return cursor
    if(item.type==='character'&&!expandedBlock)return mention.start+String(item.token||item.label||'').length
    return cursor
   })
  }
  return handled
 }:undefined
 const previewContent=displayText?(node.type==='text'?displayText:renderPromptPreviewTokens(displayText,referenceTokenState(node,inputAssets))):(node.type==='text'?'点击输入文本':PROMPT_PLACEHOLDER)
 const editorBox=editable?<PromptEditor node={node} inputAssets={inputAssets} editor={editor} onText={onText} valueOverride={displayText} onValueChangeOverride={handleEditText} onMentionSelectOverride={handleMentionSelect} className="cv-card-prompt" filterMentionItems={charactersOnly} onBlur={()=>{characterAt.current=null}} onKeyDown={event=>{if(event.key==='@')characterAt.current=null;if(event.key==='Escape'&&!event.defaultPrevented){event.preventDefault();event.stopPropagation();rootRef.current?.closest('.cv-node')?.focus({preventScroll:true})}}}/>
  :<button type="button" className={`cv-node-prompt-preview ${displayText?'':'is-empty'}`} aria-label={`编辑 ${node.title} ${node.type==='text'?'文本':'提示词'}`} title={text||(node.type==='text'?'点击输入文本':PROMPT_PLACEHOLDER)} onClick={event=>{event.stopPropagation();onActivate?.()}}>{previewContent}</button>
 // Legacy text nodes keep the plain editor (read-only compatibility, no new entry points).
 if(node.type==='text')return <div ref={rootRef} className={`cv-node-prompt ${editable?'is-editable':''}`} data-testid="node-prompt" onWheel={editable?stop:undefined}>{editorBox}</div>
 const textarea=()=>rootRef.current?.querySelector('textarea.cv-card-prompt')
 // @角色卡: types "@" at the caret, which opens the existing mention menu limited to character cards (picking one
 // runs the guarded character import of useNodeCharacters).
 const mentionCharacter=event=>{event.stopPropagation();const field=textarea();if(!field)return;characterAt.current=field.selectionStart??displayText.length;insertPromptText(field,'@',{value:displayText,onFallback:handleEditText})}
 const badgeLabel=hasBlock?formatCharacterBadgeLabel(split.names):'',namesText=split.names.join('、')
 const badgeTitle=collapsed?`已折叠角色卡设定（${namesText}）· 点击展开完整提示词\n\n${split.block.trim()}`:`当前显示完整提示词（含 ${namesText} 设定）· 点击折叠顶部角色块`
 const toggleBlock=event=>{event.stopPropagation();setExpandedBlock(v=>!v);if(editable)requestAnimationFrame(()=>textarea()?.focus({preventScroll:true}))}
 return <div ref={rootRef} className={`cv-node-prompt is-card ${editable?'is-editable':''} ${issue?'has-issue':''} ${hasBlock?'has-char-block':''}`} data-testid="node-prompt" onWheel={editable?stop:undefined}>
  {hasBlock&&<div className={`cv-char-block-bar ${collapsed?'is-collapsed':'is-expanded'}`} data-testid="card-char-block-bar" data-collapsed={collapsed?'true':'false'}>
   <button type="button" className="cv-char-block-toggle" data-testid="card-char-block-toggle" aria-expanded={!collapsed} aria-label={collapsed?`展开角色卡设定 ${namesText}`:`折叠角色卡设定 ${namesText}`} title={badgeTitle} onPointerDown={stop} onClick={toggleBlock}>
    <span className="cv-char-block-pill"><UserRound size={11} aria-hidden="true"/><span className="cv-char-block-name">{badgeLabel}</span></span>
    <span className="cv-char-block-action"><span>{collapsed?'展开设定':'收起设定'}</span>{collapsed?<ChevronDown size={12} aria-hidden="true"/>:<ChevronUp size={12} aria-hidden="true"/>}</span>
   </button>
  </div>}
  <div className="cv-node-prompt-text">{editorBox}</div>
  <div className="cv-node-prompt-tools" data-testid="card-prompt-tools">
   <span className="cv-node-prompt-tools-start">
    {editable&&<PromptLibraryPicker compact label={`提示词库（插入到 ${node.title}）`} getTextarea={textarea} value={displayText} onInsertFallback={handleEditText}/>}
    {editable&&editor&&<button type="button" className="cv-card-tool cv-card-mention" data-testid="card-mention-character" aria-label={`@角色卡（插入到 ${node.title}）`} title="输入 @ 选择角色卡或已接入素材" disabled={!!editor.characterBusy} onPointerDown={stop} onMouseDown={event=>event.preventDefault()} onClick={mentionCharacter}><AtSign size={16} aria-hidden="true"/><span>角色卡</span></button>}
   </span>
   <span className="cv-node-prompt-tools-end">
    {onExpand&&<button type="button" className="cv-card-prompt-expand" data-testid="card-prompt-expand" aria-label={`展开编辑 ${node.title} 提示词`} title="展开编辑提示词（大窗口）" onPointerDown={stop} onClick={event=>{event.stopPropagation();onExpand()}}><Maximize2 size={16} aria-hidden="true"/></button>}
    {generate&&(generate.estimate?<GenerateButton {...generate}/>:<EstimatedGenerateButton node={node} {...generate}/>)}
   </span>
  </div>
 </div>
}

// Unselected cards estimate from their resolved inputs (the selected node uses the panel's exact estimate).
function EstimatedGenerateButton({node,provider,references,...props}) {
 const estimate=useCanvasEstimate({node,provider,references})
 return <GenerateButton {...props} estimate={estimate}/>
}
// Card 生成 button: same handler, same disabled reason as the panel button; the tooltip / name carry the estimate.
function GenerateButton({nodeId,label,disabledReason,estimate,onGenerate}) {
 const cost=estimate?.known?estimate.text:'费用未知',reasonId=`cv-card-generate-reason-${nodeId}`
 const short=estimate?.known?String(estimate.text).replace(/^预估\s*/,''):'未知'
 return <>{disabledReason&&<span id={reasonId} className="cv-sr-only">{disabledReason}</span>}<span className={`cv-card-cost ${estimate?.known?'':'is-unknown'}`} data-testid="card-cost" aria-hidden="true" title={estimate?.known?`${estimate.text}（按现有费率估算，非实际扣费）`:`费用未知${estimate?.title?`：${estimate.title}`:''}`}>{short}</span><button type="button" className="cv-card-generate" data-testid="card-generate" aria-label={`生成${label}（${cost}）`} title={disabledReason?`无法生成：${disabledReason}`:`生成${label} · ${cost}${estimate?.known?'（按现有费率估算，非实际扣费）':''}`} aria-describedby={disabledReason?reasonId:undefined} disabled={!!disabledReason} onPointerDown={event=>event.stopPropagation()} onClick={event=>{event.stopPropagation();onGenerate()}}><ArrowUp size={16} aria-hidden="true"/></button></>
}

// "扩大编辑提示词" dialog: reachable at any zoom (card at low zoom, panel button). Focus trap, Esc, and the undo
// isolation of the old expanded panel are kept: browser undo/redo outside the dialog is blocked while it is open.
export function CanvasPromptDialog({node,inputAssets,editor,onText,onClose}) {
 const ref=useRef(null),characterAt=useRef(null),opener=useRef(typeof document!=='undefined'?document.activeElement:null)
 useEffect(()=>{
  ref.current?.querySelector('textarea')?.focus()
  const guard=event=>{if(['historyUndo','historyRedo'].includes(event.inputType)&&!ref.current?.contains(event.target))event.preventDefault()}
  document.addEventListener('beforeinput',guard,true)
  return()=>document.removeEventListener('beforeinput',guard,true)
 },[])
 const close=()=>{onClose();const card=document.querySelector(`.cv-node[data-node-id="${CSS.escape(node.id)}"]`),fromExpand=!!opener.current?.closest?.('[data-testid=card-prompt-expand]'),back=(fromExpand&&card?.querySelector('[data-testid=card-prompt-expand]'))||card?.querySelector('.cv-node-prompt-preview,textarea.cv-card-prompt')||card||opener.current;requestAnimationFrame(()=>back?.focus?.({preventScroll:true}))}
 const dialogTextarea=()=>ref.current?.querySelector('textarea.cv-dialog-prompt')
 const charactersOnly=(items,mention)=>characterAt.current!=null&&mention.start===characterAt.current?items.filter(item=>item.type==='character'):items
 const mentionCharacter=event=>{event.stopPropagation();const field=dialogTextarea();if(!field)return;const text=node.text||'';characterAt.current=field.selectionStart??text.length;insertPromptText(field,'@',{value:text,onFallback:value=>{editor?.setMentionError('');onText(value)}})}
 const keyDown=event=>{
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s')return
  event.stopPropagation()
  if(event.key==='Escape'&&!event.defaultPrevented){event.preventDefault();close();return}
  if(event.key==='Tab'){const items=[...ref.current.querySelectorAll('button:not(:disabled),textarea,input:not(:disabled)')].filter(el=>el.getClientRects().length);if(event.shiftKey&&[ref.current,items[0]].includes(document.activeElement)){event.preventDefault();items.at(-1)?.focus()}else if(!event.shiftKey&&document.activeElement===items.at(-1)){event.preventDefault();items[0]?.focus()}}
 }
 return createPortal(<div className="canvas-studio cv-expanded-host"><div className="cv-editor-backdrop" onPointerDown={event=>{event.preventDefault();event.stopPropagation()}}/>
  <div ref={ref} className="cv-prompt-dialog" role="dialog" aria-modal="true" aria-label={`编辑${promptLabel(node)}`} tabIndex={-1} onKeyDown={keyDown} onPointerDown={event=>event.stopPropagation()} onWheel={event=>event.stopPropagation()}>
   <header><span>{node.title} · {node.type==='text'?'文本':'提示词'}</span><button type="button" className="btn btn-icon btn-sm" aria-label="关闭提示词编辑" title="关闭 (Esc)" onClick={close}><X size={14}/></button></header>
   <PromptEditor node={node} inputAssets={inputAssets} editor={editor} onText={onText} className="cv-dialog-prompt" filterMentionItems={charactersOnly} onBlur={()=>{characterAt.current=null}} onKeyDown={event=>{if(event.key==='@')characterAt.current=null}}/>
   {node.type!=='text'&&<div className="cv-dialog-prompt-tools">
    <PromptLibraryPicker getTextarea={dialogTextarea} value={node.text||''} onInsertFallback={value=>{editor?.setMentionError('');onText(value)}}/>
    {editor&&<button type="button" className="cv-card-tool cv-card-mention" data-testid="dialog-mention-character" aria-label={`@角色卡（插入到 ${node.title}）`} title="输入 @ 选择角色卡或已接入素材" disabled={!!editor.characterBusy} onPointerDown={event=>event.stopPropagation()} onMouseDown={event=>event.preventDefault()} onClick={mentionCharacter}><AtSign size={15} aria-hidden="true"/><span>角色卡</span></button>}
   </div>}
   {node.type!=='text'&&editor&&(editor.mentionError||editor.mentionIssues.length>0)&&<div className="cv-reference-warning" role="alert">{editor.mentionError||editor.mentionIssues.join('；')}</div>}
  </div></div>,document.body)
}
