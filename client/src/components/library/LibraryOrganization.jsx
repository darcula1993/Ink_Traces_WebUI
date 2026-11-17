import React,{useEffect,useState} from 'react'
import axios from 'axios'
import LibraryDialog from './LibraryDialog'
import Select from '../ui/Select'
import {createMediaFolder,updateMediaFolder,deleteMediaFolder,previewMediaDelete,deleteMedia,listMediaGroups,createMediaGroup,updateMediaGroup,deleteMediaGroup} from '../../lib/libraryApi'
import {FOLDER_ICONS,userFolderOptions,descendants,deletePlanLines,folderNameIssue,libraryErrorText} from './mediaLibrary'
// LIBRARY-GLOBAL-20261116 S4a: folder, group and delete dialogs of the global library (no projects, no tags).
const GROUP_LIMIT=100,MEDIA_NAME_MAX=240
// V2-FIX F3: rename a library item (display/download name only; file, folder and references unchanged).
export const renameMedia=async(id,name)=>(await axios.patch(`/api/canvas/media/${encodeURIComponent(id)}`,{name})).data.media
export default function LibraryOrganization({action,folders,selection,onClose,onDone,onBeforeDelete,onDeleted}){
 const kind=action.kind,item=action.item
 const [name,setName]=useState(kind==='newFolder'?'':kind==='renameMedia'?item?.name||'':item?.title||''),[parent,setParent]=useState(item?.parent_id||''),[icon,setIcon]=useState(item?.icon||'folder'),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const [plan,setPlan]=useState(null),[groups,setGroups]=useState(null),[groupMode,setGroupMode]=useState('new'),[groupId,setGroupId]=useState('')
 const ids=selection.map(i=>i.media_id||i.id)
 useEffect(()=>{if(kind!=='remove'||!ids.length)return;let alive=true;previewMediaDelete(ids).then(v=>{if(alive)setPlan(v)}).catch(e=>{if(alive)setError(libraryErrorText(e))});return()=>{alive=false}},[kind])
 useEffect(()=>{if(kind!=='group')return;let alive=true;listMediaGroups().then(v=>{if(alive)setGroups(v)}).catch(e=>{if(alive)setError(libraryErrorText(e))});return()=>{alive=false}},[kind])
 const title={folder:'文件夹属性',newFolder:'新建文件夹',deleteFolder:'删除文件夹',remove:'删除素材',group:'加入素材组',groupEdit:'重命名素材组',renameMedia:'重命名素材',deleteGroup:'删除素材组'}[kind]
 const blocked=kind==='folder'?descendants(folders,item.id).add(item.id):new Set()
 const parentOptions=userFolderOptions(folders,{exclude:blocked})
 // E3: folder names never contain “/” and are unique among siblings (checked again by the server).
 const changed=kind==='newFolder'||kind==='folder'&&(name.trim()!==item.title||(parent||'')!==(item.parent_id||''))
 const nameIssue=['folder','newFolder'].includes(kind)&&changed?folderNameIssue(folders,name,parent,item?.id):''
 const target=groups?.find(g=>g.id===groupId)
 const overLimit=kind==='group'&&(groupMode==='new'?ids.length>GROUP_LIMIT:!!target&&new Set([...target.media_ids,...ids]).size>GROUP_LIMIT)
 async function run(){setBusy(true);setError('');try{
  let result
  if(kind==='newFolder')result=await createMediaFolder({title:name.trim(),parent_id:parent||null,icon})
  if(kind==='folder')result=await updateMediaFolder(item.id,{title:name.trim(),parent_id:parent||null,icon})
  if(kind==='deleteFolder')await deleteMediaFolder(item.id)
  if(kind==='remove'){await onBeforeDelete?.();try{result=await deleteMedia(ids)}catch(e){if(e.partial?.deleted_ids?.length)onDeleted?.(e.partial);throw e}onDeleted?.(result)}
  if(kind==='group')result=groupMode==='new'?await createMediaGroup(name.trim(),ids):await updateMediaGroup(groupId,{add:ids})
  if(kind==='renameMedia')result=await renameMedia(item.id,name.trim())
  if(kind==='groupEdit')result=await updateMediaGroup(item.id,{title:name.trim()})
  if(kind==='deleteGroup')await deleteMediaGroup(item.id)
  onDone(result)
 }catch(e){setError(libraryErrorText(e))}finally{setBusy(false)}}
 const needsName=['folder','newFolder','groupEdit','renameMedia'].includes(kind)||kind==='group'&&groupMode==='new'
 return <LibraryDialog title={title} busy={busy} error={error} onClose={onClose} onConfirm={run} danger={['remove','deleteFolder','deleteGroup'].includes(kind)}
  disabled={(kind==='remove'&&!plan)||(needsName&&!name.trim())||!!nameIssue||(kind==='group'&&(!groups||groupMode==='existing'&&!groupId||overLimit))}
  confirmLabel={kind==='remove'?'确认删除':kind==='deleteFolder'?'删除文件夹':kind==='deleteGroup'?'删除素材组':kind==='group'?(groupMode==='new'?'新建素材组':'加入素材组'):kind==='newFolder'?'创建文件夹':'确认保存'}>
  {kind==='group'&&<><p>将所选 {ids.length} 项加入素材组。素材组是全局的，只记录对库内素材的引用，不复制文件；所有项目都可以引用。</p><div className="ul-segment" role="radiogroup" aria-label="加入方式"><label><input type="radio" name="group-mode" checked={groupMode==='new'} onChange={()=>setGroupMode('new')}/>新建素材组</label><label><input type="radio" name="group-mode" checked={groupMode==='existing'} disabled={!groups?.length} onChange={()=>setGroupMode('existing')}/>加入已有素材组</label></div>
   {groupMode==='existing'&&<label>素材组<Select ariaLabel="已有素材组" disabled={busy} value={groupId} options={[{value:'',label:'请选择素材组'},...(groups||[]).map(g=>({value:g.id,label:`${g.title}（${g.member_count} 项）`}))]} onChange={setGroupId}/></label>}
   {overLimit&&<p role="alert" className="ul-error">每个素材组最多 {GROUP_LIMIT} 个素材</p>}</>}
  {needsName&&<label>名称<input aria-label="名称" value={name} maxLength={kind==='renameMedia'?MEDIA_NAME_MAX:120} disabled={busy} autoFocus aria-invalid={nameIssue?'true':undefined} aria-describedby={nameIssue?'ul-name-issue':undefined} onChange={e=>setName(e.target.value)}/></label>}
  {nameIssue&&<p id="ul-name-issue" className="ul-error" role="status">{nameIssue}</p>}
  {['folder','newFolder'].includes(kind)&&<><label>位置<Select ariaLabel="上级文件夹" disabled={busy} value={parent} options={parentOptions} onChange={setParent}/></label><label>图标<Select ariaLabel="文件夹图标" disabled={busy} value={icon} options={Object.entries(FOLDER_ICONS).map(([value,label])=>({value,label}))} onChange={setIcon}/></label></>}
  {kind==='renameMedia'&&<p className="ul-muted">只改变素材显示与下载时的名称；文件、所在文件夹及画布、任务中的引用保持不变。名称不能包含“/”或换行。</p>}
  {kind==='deleteFolder'&&<p>删除文件夹“{item.title}”？只能删除空文件夹，请先移出其中的素材和子文件夹。素材不会因删除文件夹而删除。</p>}
  {kind==='deleteGroup'&&<p>删除素材组“{item.title}”？只删除组本身，组内素材保留在素材库中。</p>}
  {kind==='remove'&&(plan?<DeletePlan plan={plan}/>:!error&&<p role="status">正在统计受影响的画布…</p>)}
 </LibraryDialog>
}

// Delete preview: every affected canvas is named; nodes keep an “已删除” placeholder.
function DeletePlan({plan}){
 return <div className="ul-delete-plan" role="status" data-testid="media-delete-plan">
  {deletePlanLines(plan).map((line,i)=><p key={i}>{line}</p>)}
  {plan.affected_workflows.length>0&&<ul className="ul-delete-workflows" aria-label="受影响的画布">{plan.affected_workflows.map(w=><li key={w.workflow_id} data-workflow-id={w.workflow_id}><b>{w.project_title||'项目已删除'}</b> / <b>{w.workflow_title||w.workflow_id}</b>：{w.placeholder_nodes||0} 个“已删除”占位，{w.stripped_nodes||0} 个节点移除引用</li>)}</ul>}
  <p className="ul-muted">“已删除”：节点保留原位置和名称并显示为“已删除”，可重新选择素材替换；归档的画布不改写。</p>
  <p><strong>此操作不可恢复。</strong>Cupsy 远端素材不受影响。</p>
 </div>
}
