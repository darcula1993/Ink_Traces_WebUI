import React,{useEffect,useRef,useState} from 'react'
import LibraryDialog from './LibraryDialog'
import FolderSelect from './FolderSelect'
import {listMediaFolders,lookupMedia,moveMedia} from '../../lib/libraryApi'
import {notifyLibraryChanged} from '../../lib/librarySync'
import {moveFolderOptions,currentFolderOf,folderPathLabel,libraryErrorText,transferMode,TRANSFER_TITLES,generatedFolderIds,mediaFolderId} from './mediaLibrary'
import './library.css'
// Unified “移动到文件夹 / 复制到文件夹” dialog shared by the global library, canvas sidebar, canvas node menu
// and task center. Items in “生成历史” (or task results without a known user folder) are copied (hard link;
// original stays with its task), others moved.
// media: [{id, kind?, folder_id? | folderId?}] — kinds/folders are looked up when missing (canvas node menu).
const normalizeEntry=entry=>({...entry,folder_id:'folder_id' in entry?entry.folder_id:entry.folderId})
const hasFolderMeta=entry=>Boolean(entry?.kind)&&('folder_id' in entry||'folderId' in entry)

export default function MoveToFolderDialog({media,overlay=false,showOutcome=false,onClose,onDone}){
 const normalized=media.map(normalizeEntry)
 const [folders,setFolders]=useState(null),[kinds,setKinds]=useState(()=>normalized.every(m=>m.kind)?normalized.map(m=>m.kind):null),[known,setKnown]=useState(()=>normalized.every(hasFolderMeta)?normalized:null),[target,setTarget]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[outcome,setOutcome]=useState(''),alive=useRef(true),outcomeRef=useRef(null)
 const ids=normalized.map(m=>m.id)
 async function loadFolders(){const list=await listMediaFolders();if(alive.current)setFolders(list);return list}
 useEffect(()=>{alive.current=true;loadFolders().catch(e=>{if(alive.current)setError(libraryErrorText(e))});if(!known)lookupMedia(ids).then(items=>{if(!alive.current)return;const gone=items.filter(i=>i.status!=='ok');if(gone.length)setError(`${gone.length} 项已删除或不存在，无法移动`);const found=items.filter(i=>i.status==='ok').map(i=>i.media);setKinds(found.map(m=>m.kind));setKnown(found)}).catch(e=>{if(alive.current)setError(libraryErrorText(e))});return()=>{alive.current=false}},[])
 // Keep focus inside the dialog on 完成 when showOutcome keeps the dialog open after moving.
 useEffect(()=>{if(outcome)outcomeRef.current?.closest('[role=dialog]')?.querySelector('footer button')?.focus({preventScroll:true})},[outcome])
 // V2-FIX F7: start from the folder the items are in now (a user folder); items from different folders, unknown
 // folders, or in “生成历史” (which takes nothing), start empty and must pick one.
 const options=folders&&kinds?moveFolderOptions(folders,kinds):null,current=known&&currentFolderOf(known)
 const mode=folders&&known?transferMode(folders,known):'move'
 const copies=folders&&known?known.filter(m=>{const fid=mediaFolderId(m);return fid===undefined||generatedFolderIds(folders).has(fid)}).length:0
 const mixedFolders=known&&known.length>1&&new Set(known.map(m=>mediaFolderId(m)||'')).size>1
 useEffect(()=>{if(options&&current!==null&&current!==undefined&&target===null&&options.some(o=>o.value===current&&!o.disabled))setTarget(current)},[!!options,current])
 async function run(){
  if(target===null)return
  setBusy(true);setError('')
  try{
   const moved=await moveMedia(ids,target||null)
   if(!alive.current)return
   const folder=folders.find(f=>f.id===target)||null,where=folder?`“${folderPathLabel(folders,folder.id)}”`:'“根目录”'
   const text=mode==='copy'?`已复制 ${moved.length} 项到${where}`:mode==='mixed'?`已移动 ${moved.length-copies} 项、复制 ${copies} 项到${where}`:`已移动 ${moved.length} 项到${where}`
   notifyLibraryChanged({source:'move',folderId:target||null})
   const summary={moved,folder,folderId:target||'root',text}
   if(showOutcome)setOutcome(text)
   onDone?.(summary)
  }catch(e){if(alive.current)setError(libraryErrorText(e,mode==='copy'?'复制失败':'移动失败'))}finally{if(alive.current)setBusy(false)}
 }
 return <LibraryDialog title={TRANSFER_TITLES[mode]} className={overlay?'ul-subdialog-top':''} busy={busy} error={error} onClose={onClose} onConfirm={outcome?null:run} disabled={!folders||!kinds||!ids.length||target===null} confirmLabel={mode==='copy'?'复制':mode==='mixed'?'移动/复制':'移动'} cancelLabel={outcome?'完成':'取消'}>
  {outcome?<p ref={outcomeRef} role="status" data-testid="move-to-folder-outcome"><strong>{outcome}</strong></p>:<>
   {mode==='copy'?<p data-testid="transfer-copy-note">将所选 {ids.length} 项生成结果复制到目标文件夹：生成独立的新素材（硬链接，不额外占空间），原结果仍留在“生成历史”并随任务删除，复制出的不受影响。</p>
    :mode==='mixed'?<p data-testid="transfer-mixed-note">所选 {ids.length} 项中，{copies} 项生成结果复制到目标文件夹（原结果仍留在“生成历史”并随任务删除，复制出的不受影响），其余 {ids.length-copies} 项移动过去。</p>
    :<p>将所选 {ids.length} 项移动到目标文件夹。只改变素材所在文件夹，不复制文件；画布与任务中的引用保持不变。</p>}
   {folders&&kinds?<FolderSelect label="目标文件夹" folders={folders} options={options} value={target} placeholder="请选择目标文件夹" onChange={setTarget} onCreated={loadFolders} disabled={busy}/>:!error&&<p role="status">正在载入文件夹…</p>}
   {options&&target===null&&<p className="ul-muted" role="status">{mixedFolders?'所选素材位于不同文件夹，请选择目标文件夹。':'请选择目标文件夹。'}</p>}
   {mode==='move'&&<p className="ul-muted">“生成历史”只接收新生成的结果，不可移入。</p>}
  </>}
 </LibraryDialog>
}
