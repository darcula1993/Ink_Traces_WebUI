import React,{useEffect,useRef,useState} from 'react'
import LibraryDialog from './LibraryDialog'
import FolderSelect from './FolderSelect'
import {listMediaFolders,lookupMedia,moveMedia} from '../../lib/libraryApi'
import {moveFolderOptions,currentFolderOf,folderPathLabel,libraryErrorText,GENERATED_ONLY_HINT,transferMode,TRANSFER_TITLES,generatedFolderIds} from './mediaLibrary'
import './library.css'
// “移动到文件夹” (replaces “加入本地素材”): changes the folder of library items. GEN-RESULT-LIFECYCLE-20261119: items
// of “生成历史” are copied instead (new independent item, hard link; the original stays with its task) and the
// dialog then reads “复制到文件夹”.
// media: [{id, kind?, folder_id?}] — kinds are looked up when missing (task cards / canvas results pass ids).
// Reusable by the task center (S4b) and canvas (S5).
export default function MoveToFolderDialog({media,overlay=false,onClose,onDone}){
 const [folders,setFolders]=useState(null),[kinds,setKinds]=useState(()=>media.every(m=>m.kind)?media.map(m=>m.kind):null),[known,setKnown]=useState(()=>media.every(m=>m.kind&&m.origin&&'folder_id' in m)?media:null),[target,setTarget]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),alive=useRef(true)
 const ids=media.map(m=>m.id)
 async function loadFolders(){const list=await listMediaFolders();if(alive.current)setFolders(list);return list}
 useEffect(()=>{alive.current=true;loadFolders().catch(e=>{if(alive.current)setError(libraryErrorText(e))});if(!known)lookupMedia(ids).then(items=>{if(!alive.current)return;const gone=items.filter(i=>i.status!=='ok');if(gone.length)setError(`${gone.length} 项已删除或不存在，无法移动`);const found=items.filter(i=>i.status==='ok').map(i=>i.media);setKinds(found.map(m=>m.kind));setKnown(found)}).catch(e=>{if(alive.current)setError(libraryErrorText(e))});return()=>{alive.current=false}},[])
 // V2-FIX F7: start from the folder the items are in now (a user folder); items from different folders, or in
 // “生成历史” (which takes nothing), start empty and must pick one.
 const options=folders&&kinds?moveFolderOptions(folders,kinds):null,current=known&&currentFolderOf(known)
 const mode=folders&&known?transferMode(folders,known):'move',copies=folders&&known?known.filter(m=>generatedFolderIds(folders).has(m.folder_id)).length:0
 useEffect(()=>{if(options&&current!==undefined&&target===null&&options.some(o=>o.value===current&&!o.disabled))setTarget(current)},[!!options,current])
 async function run(){if(target===null)return;setBusy(true);setError('');try{const moved=await moveMedia(ids,target||null);if(!alive.current)return;const folder=folders.find(f=>f.id===target),where=folder?`“${folderPathLabel(folders,folder.id)}”`:'根目录';onDone?.({moved,folder:folder||null,text:mode==='copy'?`已复制 ${moved.length} 项到${where}`:mode==='mixed'?`已移动 ${moved.length-copies} 项、复制 ${copies} 项到${where}`:`已移动 ${moved.length} 项到${where}`})}catch(e){if(alive.current)setError(libraryErrorText(e,mode==='copy'?'复制失败':'移动失败'))}finally{if(alive.current)setBusy(false)}}
 return <LibraryDialog title={TRANSFER_TITLES[mode]} className={overlay?'ul-subdialog-top':''} busy={busy} error={error} onClose={onClose} onConfirm={run} disabled={!folders||!kinds||!ids.length||target===null} confirmLabel={mode==='copy'?'复制':mode==='mixed'?'移动/复制':'移动'}>
  {mode==='copy'?<p data-testid="transfer-copy-note">将所选 {ids.length} 项生成结果复制到目标文件夹：生成独立的新素材（硬链接，不额外占空间），原结果仍留在“生成历史”并随任务删除，复制出的不受影响。</p>
   :mode==='mixed'?<p data-testid="transfer-mixed-note">所选 {ids.length} 项中，{copies} 项生成结果复制到目标文件夹（原结果留在“生成历史”），其余 {ids.length-copies} 项移动过去。</p>
   :<p>将所选 {ids.length} 项移动到目标文件夹。只改变素材所在文件夹，不复制文件；画布与任务中的引用保持不变。</p>}
  {folders&&kinds?<FolderSelect label="目标文件夹" folders={folders} options={options} value={target} placeholder="请选择目标文件夹" onChange={setTarget} onCreated={loadFolders} disabled={busy}/>:!error&&<p role="status">正在载入文件夹…</p>}
  {options&&target===null&&<p className="ul-muted" role="status">{current===null?'所选素材位于不同文件夹，请选择目标文件夹。':'请选择目标文件夹。'}</p>}
  <p className="ul-muted">{GENERATED_ONLY_HINT}</p>
 </LibraryDialog>
}
