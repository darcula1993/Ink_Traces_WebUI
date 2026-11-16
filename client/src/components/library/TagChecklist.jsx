import React,{useState} from 'react'
import {Plus} from 'lucide-react'
import {createLibraryTag} from '../../lib/libraryApi'
// LOCAL-FROM-RESULT-20261116: shared tag picker; every tag-selection dialog can create a tag on the spot.
// A typed name that already exists selects that tag instead of creating a duplicate.
export default function TagChecklist({tags,checked,onChange,onCreated,busy=false}){
 const [name,setName]=useState(''),[creating,setCreating]=useState(false),[error,setError]=useState('')
 const toggle=id=>onChange(checked.includes(id)?checked.filter(v=>v!==id):[...checked,id])
 async function create(){const title=name.trim();if(!title||creating)return;setError('')
  const existing=tags.find(t=>t.title===title);if(existing){if(!checked.includes(existing.id))onChange([...checked,existing.id]);setName('');return}
  setCreating(true);try{const tag=await createLibraryTag(title);onCreated?.(tag);onChange([...checked,tag.id]);setName('')}catch(e){setError(e?.response?.data?.error||e?.message||'新建标签失败')}finally{setCreating(false)}}
 return <fieldset className="ul-tag-picker" disabled={busy}><legend>标签</legend>
  {tags.length?<div className="ul-tag-checks">{tags.map(t=><label key={t.id}><input type="checkbox" checked={checked.includes(t.id)} onChange={()=>toggle(t.id)}/>{t.title}</label>)}</div>:<p className="ul-muted">还没有标签，可在下方直接新建。</p>}
  <div className="ul-tag-new"><input aria-label="新标签名称" placeholder="输入新标签名称" maxLength={100} value={name} disabled={creating} onChange={e=>setName(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();create()}}}/><button type="button" disabled={!name.trim()||creating} onClick={create}><Plus size={14} aria-hidden="true"/>{creating?'新建中…':'新建并选中'}</button></div>
  {error&&<p role="alert" className="ul-error">{error}</p>}
 </fieldset>
}
