import React from 'react'
import {ChevronRight,ChevronDown,Folder,Lock,Music,Users,Mountain,Box,Palette,Library,Inbox,History,FolderPlus} from 'lucide-react'
import LibraryMore from './LibraryMore'
import {folderChildren,folderCount,GENERATED} from './mediaLibrary'
const ICONS={music:Music,character:Users,scene:Mountain,prop:Box,style:Palette}
export const folderIcon=folder=>folder?.system_key===GENERATED?History:ICONS[folder?.icon]||Folder
// Left navigation of the global library: 全部素材, the folder tree (locked system “生成历史” first,
// then user folders and subfolders) and 根目录 (items not in any folder).
export default function MediaFolderTree({folders,place,active,onPlace,expanded,onToggle,onAction,counts,busy}){
 const children=folderChildren(folders)
 const row=(folder,depth)=>{const kids=children.get(folder.id)||[],open=expanded.has(folder.id),system=!!folder.system_key,Icon=folderIcon(folder),current=active&&place===folder.id
  return <li key={folder.id} role="none">
   <div className={`ul-tree-row${current?' is-current':''}`} style={{'--depth':depth}}>
    {kids.length?<button className="ul-tree-toggle" aria-label={`${open?'收起':'展开'} ${folder.title}`} aria-expanded={open} disabled={busy} onClick={()=>onToggle(folder.id)}>{open?<ChevronDown size={14} aria-hidden="true"/>:<ChevronRight size={14} aria-hidden="true"/>}</button>:<span className="ul-tree-toggle" aria-hidden="true"/>}
    <button className="ul-tree-item" aria-current={current?'true':undefined} aria-label={`文件夹 ${folder.title}${system?'（系统文件夹）':''}`} title={system?`${folder.title}：系统文件夹，不可重命名或删除；内部结果可移走或删除`:folder.title} disabled={busy} onClick={()=>onPlace(folder.id)}>
     <Icon size={15} strokeWidth={1.7} aria-hidden="true"/><span>{folder.title}</span>{system&&<Lock className="ul-tree-lock" size={12} aria-label="已锁定"/>}<small>{folderCount(folders,folder)}</small>
    </button>
    {!system&&<LibraryMore name={`文件夹 ${folder.title}`}><button onClick={()=>onAction({kind:'newFolder',item:{parent_id:folder.id}})}>新建子文件夹</button><button onClick={()=>onAction({kind:'folder',item:folder})}>重命名／移动</button><button className="is-danger" onClick={()=>onAction({kind:'deleteFolder',item:folder})}>删除文件夹</button></LibraryMore>}
   </div>
   {kids.length>0&&open&&<ul role="group">{kids.map(k=>row(k,depth+1))}</ul>}
  </li>}
 return <nav className="ul-tree" aria-label="素材文件夹">
  <button className={`ul-tree-top${active&&place==='all'?' is-current':''}`} aria-current={active&&place==='all'?'true':undefined} disabled={busy} onClick={()=>onPlace('all')}><Library size={15} strokeWidth={1.7} aria-hidden="true"/><span>全部素材</span><small>{counts.all??''}</small></button>
  <ul className="ul-tree-list">{(children.get('')||[]).map(f=>row(f,0))}</ul>
  <button className={`ul-tree-top${active&&place==='root'?' is-current':''}`} aria-current={active&&place==='root'?'true':undefined} title="不在任何文件夹中的素材" disabled={busy} onClick={()=>onPlace('root')}><Inbox size={15} strokeWidth={1.7} aria-hidden="true"/><span>根目录</span><small>{counts.root??''}</small></button>
  <button className="ul-tree-new" disabled={busy} onClick={()=>onAction({kind:'newFolder',item:{parent_id:''}})}><FolderPlus size={14} aria-hidden="true"/>新建文件夹</button>
 </nav>
}
