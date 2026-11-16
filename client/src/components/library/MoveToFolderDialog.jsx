import React,{useEffect,useRef,useState} from 'react'
import LibraryDialog from './LibraryDialog'
import FolderSelect from './FolderSelect'
import {listMediaFolders,lookupMedia,moveMedia} from '../../lib/libraryApi'
import {moveFolderOptions,currentFolderOf,folderPathLabel} from './mediaLibrary'
import './library.css'
// “移动到文件夹” (replaces “加入本地素材”): only changes the folder of library items; no copy.
// media: [{id, kind?, folder_id?}] — kinds are looked up when missing (task cards / canvas results pass ids).
// Reusable by the task center (S4b) and canvas (S5).
export default function MoveToFolderDialog({media,overlay=false,onClose,onDone}){
 const [folders,setFolders]=useState(null),[kinds,setKinds]=useState(()=>media.every(m=>m.kind)?media.map(m=>m.kind):null),[known,setKnown]=useState(()=>media.every(m=>m.kind&&'folder_id' in m)?media:null),[target,setTarget]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),alive=useRef(true)
 const ids=media.map(m=>m.id)
 async function loadFolders(){const list=await listMediaFolders();if(alive.current)setFolders(list);return list}
 useEffect(()=>{alive.current=true;loadFolders().catch(e=>{if(alive.current)setError(e?.response?.data?.error||e.message)});if(!known)lookupMedia(ids).then(items=>{if(!alive.current)return;const gone=items.filter(i=>i.status!=='ok');if(gone.length)setError(`${gone.length} 项已删除或不存在，无法移动`);const found=items.filter(i=>i.status==='ok').map(i=>i.media);setKinds(found.map(m=>m.kind));setKnown(found)}).catch(e=>{if(alive.current)setError(e?.response?.data?.error||e.message)});return()=>{alive.current=false}},[])
 // V2-FIX F7: start from the folder the items are in now; items from different folders start empty and must pick one.
 const options=folders&&kinds?moveFolderOptions(folders,kinds):null,current=known&&currentFolderOf(known)
 useEffect(()=>{if(options&&current!==undefined&&target===null&&options.some(o=>o.value===current))setTarget(current)},[!!options,current])
 async function run(){if(target===null)return;setBusy(true);setError('');try{const moved=await moveMedia(ids,target||null);if(!alive.current)return;const folder=folders.find(f=>f.id===target);onDone?.({moved,folder:folder||null,text:`已移动 ${moved.length} 项到${folder?`“${folderPathLabel(folders,folder.id)}”`:'根目录'}`})}catch(e){if(alive.current)setError(e?.response?.data?.error||e.message||'移动失败')}finally{if(alive.current)setBusy(false)}}
 return <LibraryDialog title="移动到文件夹" className={overlay?'ul-subdialog-top':''} busy={busy} error={error} onClose={onClose} onConfirm={run} disabled={!folders||!kinds||!ids.length||target===null} confirmLabel="移动">
  <p>将所选 {ids.length} 项移动到目标文件夹。只改变素材所在文件夹，不复制文件；画布与任务中的引用保持不变。</p>
  {folders&&kinds?<FolderSelect label="目标文件夹" folders={folders} options={options} value={target} placeholder="请选择目标文件夹" onChange={setTarget} onCreated={loadFolders} disabled={busy}/>:!error&&<p role="status">正在载入文件夹…</p>}
  {options&&target===null&&<p className="ul-muted" role="status">{current===null?'所选素材位于不同文件夹，请选择目标文件夹。':'请选择目标文件夹。'}</p>}
  <p className="ul-muted">“生成历史”下的图片／视频／音频只接收对应类型的生成结果；可移出到任意文件夹。</p>
 </LibraryDialog>
}
