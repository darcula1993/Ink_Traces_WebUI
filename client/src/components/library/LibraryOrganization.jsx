import React,{useEffect,useState} from 'react'
import LibraryDialog from './LibraryDialog'
import Select from '../ui/Select'
import {listProjectFolders,createProjectFolder,updateProjectFolder,deleteProjectFolder,updateProjectAsset,createProjectAssetGroup,listProjectAssets} from '../../lib/canvasApi'
import {createLibraryTag,updateLibraryTag,deleteLibraryTag,setLibraryItemTags,saveLibraryItems,previewLocalDelete,deleteLocalItems} from '../../lib/libraryApi'
import axios from 'axios'
import askConfirm from '../ui/askConfirm'
const icons={folder:'文件夹',character:'角色',scene:'场景',prop:'物品',style:'风格',music:'音效'}
export default function LibraryOrganization({action,projects,projectId,currentProjectId=null,tags,selection,onClose,onDone,onSelectGroup,onBeforeDelete,onDeleted}){
 const [name,setName]=useState(action.item?.title||action.item?.asset?.name||''),[destination,setDestination]=useState(projectId||''),[folder,setFolder]=useState(action.item?.folder_id||action.item?.parent_id||''),[folders,setFolders]=useState([]),[icon,setIcon]=useState(action.item?.icon||'folder'),[checked,setChecked]=useState(action.item?.tags?.map(t=>t.id)||[]),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const [plan,setPlan]=useState(null)
 useEffect(()=>{if(action.kind!=='remove'||!selection.length)return;let alive=true;previewLocalDelete(selection.map(i=>i.key),currentProjectId).then(v=>{if(alive)setPlan(v)}).catch(e=>{if(alive)setError(e?.response?.data?.error||e.message)});return()=>{alive=false}},[action.kind,selection,currentProjectId])
 useEffect(()=>{let alive=true;setFolders([]);if(destination)listProjectFolders(destination).then(v=>{if(alive)setFolders(v)}).catch(e=>{if(alive)setError(e.message)});return()=>{alive=false}},[destination])
 const kind=action.kind,title={folder:'文件夹属性',newFolder:'新建文件夹',deleteFolder:'删除空文件夹',asset:'素材属性',newTag:'新建标签',tag:'标签管理',assignTags:'设置素材标签',remove:'删除本地素材',recycle:'移入任务回收站',group:'新建素材组',selectGroup:'选择素材组'}[kind]
 const requiresProject=['folder','newFolder','asset','group'].includes(kind)
 function forbiddenFolder(id){if(kind!=='folder')return false;const seen=new Set();while(id&&!seen.has(id)){if(id===action.item.id)return true;seen.add(id);id=folders.find(f=>f.id===id)?.parent_id}return false}
 async function run(){setBusy(true);setError('');try{
  if(requiresProject&&!destination)throw new Error('请明确选择目标项目')
  if(kind==='newFolder')await createProjectFolder(destination,name.trim(),folder||null)
  if(kind==='folder')await updateProjectFolder(destination,action.item.id,{title:name.trim(),parent_id:folder||null,icon})
  if(kind==='deleteFolder')await deleteProjectFolder(action.projectId,action.item.id)
  if(kind==='asset')await updateProjectAsset(destination,action.item.asset.id,{name:name.trim(),folder_id:folder||null})
  if(kind==='newTag')await createLibraryTag(name.trim())
  if(kind==='tag')await updateLibraryTag(action.item.id,name.trim())
  if(kind==='assignTags')for(const item of selection)await setLibraryItemTags(item.key,checked)
  if(kind==='remove'){await onBeforeDelete?.();let result;try{result=await deleteLocalItems(selection.map(i=>i.key))}catch(e){if(e.partial?.deleted_keys?.length)onDeleted?.(e.partial);throw e}onDeleted?.(result);if(result.rejected.length)throw new Error(`已删除 ${result.items} 个，${result.rejected.length} 个不在本地删除范围：${result.rejected.map(r=>r.error).filter((v,i,a)=>a.indexOf(v)===i).join('；')}`)}
  if(kind==='recycle')for(const id of new Set(selection.map(i=>i.task_id)))await axios.delete(`/api/tasks/${id}`)
  if(kind==='group'){const copied=await saveLibraryItems(destination,selection.map(i=>i.selection),folder||null);await createProjectAssetGroup(destination,name.trim(),copied.assets.map(a=>a.id))}
  if(kind==='selectGroup'){const assets=await listProjectAssets(action.projectId),ids=new Set(action.item.asset_ids);await onSelectGroup(assets.filter(a=>ids.has(a.id)).map(asset=>({key:`library:${asset.id}`,selection:{source:'library',id:asset.id},asset,project_id:action.projectId,project_title:projects.find(p=>p.id===action.projectId)?.title})));}
  onDone()
 }catch(e){setError(e?.response?.data?.error||e.message)}finally{setBusy(false)}}
 return <LibraryDialog title={title} busy={busy} error={error} onClose={onClose} onConfirm={run} danger={['remove','recycle','deleteFolder','deleteTag','deleteGroup'].includes(kind)} disabled={(kind==='remove'&&!plan)||(requiresProject&&!destination)||(['folder','newFolder','newTag','tag','asset','group'].includes(kind)&&!name.trim())} confirmLabel={kind==='remove'?'确认删除':kind==='recycle'?'确认移入回收站':kind==='selectGroup'?'选择组内素材':'确认保存'}>
 {requiresProject&&<label>目标项目<Select ariaLabel="目标项目" disabled={busy||['folder','asset'].includes(kind)} value={destination} options={[{value:'',label:'请选择项目'},...projects.map(p=>({value:p.id,label:p.title}))]} onChange={v=>{setDestination(v);setFolder('')}}/></label>}
 {['folder','newFolder','newTag','tag','asset','group'].includes(kind)&&<label>名称<input aria-label="名称" value={name} maxLength={kind==='asset'?240:100} disabled={busy} onChange={e=>setName(e.target.value)}/></label>}
 {['folder','newFolder','asset'].includes(kind)&&<label>文件夹<Select ariaLabel="目标文件夹" disabled={busy||!destination} value={folder} options={[{value:'',label:'根目录'},...folders.filter(f=>!forbiddenFolder(f.id)).map(f=>({value:f.id,label:f.title}))]} onChange={setFolder}/></label>}
 {kind==='folder'&&<label>图标<Select ariaLabel="文件夹图标" value={icon} options={Object.entries(icons).map(([key,value])=>({value:key,label:value}))} onChange={setIcon}/></label>}
 {kind==='deleteFolder'&&<p>删除“{action.item.title}”？仅可删除空文件夹，请先移出其中素材和子文件夹。</p>}
 {kind==='remove'&&(plan?<div className="ul-delete-plan" role="status"><p>将永久删除 <b>{plan.items}</b> 个本地素材及其原文件。</p><p>{plan.canvas_copies?<>同时删除由其复制到画布的 <b>{plan.canvas_copies}</b> 个画布副本，涉及 {plan.workflows} 个画布、<b>{plan.affected_nodes}</b> 个受影响节点{plan.removed_nodes?`（其中 ${plan.removed_nodes} 个素材节点将被移除）`:''}，节点内对这些副本的参考与提及会被清除。</>:'没有画布副本引用这些素材（无画布引用）。'}</p>{plan.affected_workflows?.length>0&&<DeleteImpact workflows={plan.affected_workflows}/>}{plan.characters?.length>0&&<p data-testid="delete-plan-characters">被角色 <b>{plan.characters.map(c=>c.name).join('、')}</b> 使用；确认删除后会从这些角色中移除对应的角色图或参考音频（角色本身保留）。</p>}{plan.archived_copies_retained>0&&<p>已归档画布中的 {plan.archived_copies_retained} 个副本按归档保留规则不删除。</p>}{plan.rejected.length>0&&<p>{plan.rejected.length} 项（生成历史或 Cupsy 远端）不在本地删除范围，将跳过。</p>}{plan.missing.length>0&&<p>{plan.missing.length} 项已不存在。</p>}<p><strong>此操作不可恢复。</strong>生成历史与 Cupsy 远端素材不受影响。</p></div>:!error&&<p role="status">正在统计将删除的画布副本…</p>)}
 {kind==='recycle'&&<p>将所选产物所属的 {new Set(selection.map(i=>i.task_id)).size} 个完整任务移入回收站；同任务的其他产物也会受影响。已有画布引用保留，不永久删除文件。</p>}
 {kind==='assignTags'&&<><p>为所选 {selection.length} 项设置标签（替换原标签，不移动文件夹）。</p>{tags.map(t=><label key={t.id}><input type="checkbox" checked={checked.includes(t.id)} disabled={busy} onChange={()=>setChecked(v=>v.includes(t.id)?v.filter(id=>id!==t.id):[...v,t.id])}/>{t.title}</label>)}</>}
 {kind==='tag'&&<button disabled={busy} onClick={async()=>{if(!await askConfirm({title:'删除标签',message:`删除标签“${action.item.title}”？素材与文件夹将保留。`,confirmLabel:'删除标签',danger:true}))return;setBusy(true);try{await deleteLibraryTag(action.item.id);onDone()}catch(e){setError(e?.response?.data?.error||e.message)}finally{setBusy(false)}}}>删除标签（保留素材）</button>}
 {kind==='selectGroup'&&<p>“{action.item.title}”将展开为 {action.item.asset_ids?.length||0} 个素材，确认后加入当前选择。</p>}
 </LibraryDialog>
}

// FIX-B1B-20261114: name every canvas the deletion rewrites; canvases outside the current project are called out first.
function workflowLine(w){const parts=[];if(w.canvas_copies)parts.push(`${w.canvas_copies} 个画布副本`);if(w.direct_assets)parts.push(`${w.direct_assets} 个画布直传素材`);parts.push(`${w.affected_nodes} 个受影响节点${w.removed_nodes?`（移除 ${w.removed_nodes} 个）`:''}`);return parts.join('，')}
function WorkflowList({items,label}){return <ul className="ul-delete-workflows" aria-label={label}>{items.map(w=><li key={w.workflow_id} data-workflow-id={w.workflow_id}><b>{w.project_title||'项目已删除'}</b> / <b>{w.workflow_title||w.workflow_id}</b>：{workflowLine(w)}</li>)}</ul>}
function DeleteImpact({workflows}){const other=workflows.filter(w=>w.other_project),own=workflows.filter(w=>!w.other_project),projects=new Set(other.map(w=>w.project_id))
 return <>{other.length>0&&<div className="ul-delete-warning" role="alert" data-testid="delete-plan-other-projects"><p><strong>注意：将影响其他项目的画布</strong>（{projects.size} 个项目、{other.length} 个画布）。这些画布中引用的副本会被一并删除，节点内的参考与提及会被清除。</p><WorkflowList items={other} label="受影响的其他项目画布"/></div>}
 {own.length>0&&<div data-testid="delete-plan-workflows"><p>受影响的本项目画布：</p><WorkflowList items={own} label="受影响的本项目画布"/></div>}</>}
