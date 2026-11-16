import React,{useEffect,useRef,useState} from 'react'
import LibraryDialog from './LibraryDialog'
import TagChecklist from './TagChecklist'
import {listLibraryTags,addResultsToLocal} from '../../lib/libraryApi'
import {summarizeFromResults,refLabel} from './localFromResults'
import './library.css'
// LOCAL-FROM-RESULT-20261116: “加入本地素材” for generation results (生成历史、画布节点结果/版本、任务卡与详情).
// The server copies each result as an independent 本地素材 (no project); task outputs and canvas stay in place.
// Repeats come back as existing (no new copy, tags merged); unusable results come back as skipped with a reason.
export default function AddToLocalDialog({refs,carriedTags=[],overlay=false,onClose,onDone}){
 const [tags,setTags]=useState([]),[checked,setChecked]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[outcome,setOutcome]=useState(null),alive=useRef(true),outcomeRef=useRef(null)
 useEffect(()=>{alive.current=true;listLibraryTags().then(v=>{if(alive.current)setTags(v)}).catch(e=>{if(alive.current)setError(e?.response?.data?.error||e.message)});return()=>{alive.current=false}},[])
 // The confirm button disappears with the outcome: keep focus (and Escape/Tab) inside the dialog on 完成.
 useEffect(()=>{if(outcome)outcomeRef.current?.closest('[role=dialog]')?.querySelector('footer button')?.focus({preventScroll:true})},[outcome])
 async function run(){setBusy(true);setError('');try{const result=await addResultsToLocal(refs,{tag_ids:checked});if(!alive.current)return;const summary=summarizeFromResults(result);setOutcome(summary);onDone?.(summary)}catch(e){if(alive.current)setError(e?.response?.data?.error||e.message||'加入本地素材失败')}finally{if(alive.current)setBusy(false)}}
 return <LibraryDialog title="加入本地素材" className={overlay?'ul-subdialog-top':''} busy={busy} error={error} onClose={onClose} onConfirm={outcome?null:run} disabled={!refs.length} confirmLabel="加入本地素材" cancelLabel={outcome?'完成':'取消'}>
  {outcome?<div ref={outcomeRef} className="ul-local-outcome" role="status" data-testid="local-from-results-outcome">
   <p><strong>{outcome.text}</strong></p>
   {outcome.created.length>0&&<p>新加入的素材不属于任何项目，在素材库“本地素材 · 全部项目”中查看，各项目均可引用。</p>}
   {outcome.existing.length>0&&<><p>以下结果已在本地素材，未重复复制：</p><ul aria-label="已在本地素材">{outcome.existing.map((i,n)=><li key={i.local_id||n}>{i.name||'未命名结果'}</li>)}</ul></>}
   {outcome.skipped.length>0&&<><p>以下结果未加入：</p><ul aria-label="未加入的结果">{outcome.skipped.map((s,n)=><li key={n}>{refLabel(s.ref)}：{s.reason||'无法加入'}</li>)}</ul></>}
  </div>:<>
   <p>将所选 {refs.length} 项生成结果复制为本地素材。本地素材不属于任何项目（不进文件夹），在“全部项目”中查看，各项目均可引用；任务输出与画布保持原位，删除本地副本不影响它们。</p>
   <TagChecklist tags={tags} checked={checked} busy={busy} onChange={setChecked} onCreated={tag=>setTags(v=>[...v,tag])}/>
   <p className="ul-muted">{carriedTags.length?`生成结果已有的标签（${carriedTags.map(t=>t.title).join('、')}）会自动保留并带上。`:'生成结果已有的标签会自动保留并带上；同一结果重复加入不会再复制。'}</p>
  </>}
 </LibraryDialog>
}
