import React,{useState} from 'react'
import {FolderPlus} from 'lucide-react'
import Select from '../ui/Select'
import {createMediaFolder} from '../../lib/libraryApi'
// Target-folder picker with “当场新建”: the new folder is created inside the currently chosen user folder
// (or the root) and becomes the selection. Used by upload, “移动到文件夹” and other callers.
export default function FolderSelect({label='目标文件夹',options,value,onChange,folders,onCreated,disabled=false,placeholder}){
 const [adding,setAdding]=useState(false),[title,setTitle]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const parent=folders.find(f=>f.id===value&&!f.system_key)
 async function create(){const name=title.trim();if(!name||busy)return;setBusy(true);setError('');try{const folder=await createMediaFolder({title:name,parent_id:parent?.id||null});await onCreated?.(folder);onChange(folder.id);setTitle('');setAdding(false)}catch(e){setError(e?.response?.data?.error||e?.message||'新建文件夹失败')}finally{setBusy(false)}}
 return <div className="ul-folder-select">
  <label>{label}<Select ariaLabel={label} placeholder={placeholder} disabled={disabled||busy} value={value} options={options} onChange={onChange}/></label>
  {adding?<div className="ul-folder-new"><input aria-label="新文件夹名称" placeholder={parent?`在“${parent.title}”下新建`:'在根目录新建'} maxLength={120} value={title} disabled={busy} autoFocus onChange={e=>setTitle(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();create()}if(e.key==='Escape'){e.preventDefault();e.stopPropagation();setAdding(false)}}}/><button type="button" disabled={busy||!title.trim()} onClick={create}>{busy?'新建中…':'新建并选中'}</button><button type="button" disabled={busy} onClick={()=>setAdding(false)}>取消</button></div>
  :<button type="button" className="ul-folder-add" disabled={disabled} onClick={()=>setAdding(true)}><FolderPlus size={14} aria-hidden="true"/>新建文件夹</button>}
  {error&&<p role="alert" className="ul-error">{error}</p>}
 </div>
}
