// LIBRARY-GLOBAL-20261116 S4a: pure helpers for the global media library (node-testable, no React).
// One library for every project; folders only (no tags). System folder “生成历史/图片|视频|音频” is locked.

// Catalog item handed to selection, onApply and the footer. selection.source==='media' is the new
// reference kind; canvas/tool callers resolve it by media id (S5 / S4b).
export const mediaItem=media=>({key:media.id,media_id:media.id,selection:{source:'media',id:media.id},asset:media,thumbnail_url:media.thumbnail_url||null,available:true})

export const ORIGIN_LABELS={upload:'上传',canvas_upload:'画布上传',paste:'粘贴',frame:'截帧',save_as:'另存',generated:'生成结果',legacy_local:'历史素材',legacy_library:'历史素材',legacy_workflow:'历史素材'}
export const originLabel=origin=>ORIGIN_LABELS[origin]||'素材'
export const FOLDER_ICONS={folder:'文件夹',music:'音效',character:'角色',scene:'场景',prop:'物品',style:'风格'}

export const isSystemFolder=folder=>!!folder?.system_key
export const GENERATED='generated'
export const generatedKindKey=kind=>`generated_${kind}`

// Children map keyed by parent id ('' = root); order follows the server (system first, then creation).
export function folderChildren(folders){const map=new Map();for(const f of folders){const key=f.parent_id||'';if(!map.has(key))map.set(key,[]);map.get(key).push(f)}return map}
export function folderPath(folders,id){const byId=new Map(folders.map(f=>[f.id,f])),path=[],seen=new Set();let current=byId.get(id);while(current&&!seen.has(current.id)){seen.add(current.id);path.unshift(current);current=byId.get(current.parent_id)}return path}
export function descendants(folders,id){const children=folderChildren(folders),out=new Set(),stack=[id];while(stack.length){for(const c of children.get(stack.pop())||[])if(!out.has(c.id)){out.add(c.id);stack.push(c.id)}}return out}
// Depth-first list with depth, for indented pickers.
export function flattenFolders(folders,{filter=()=>true}={}){const children=folderChildren(folders),out=[],walk=(parent,depth)=>{for(const f of children.get(parent)||[]){if(!filter(f))continue;out.push({...f,depth});walk(f.id,depth+1)}};walk('',0);return out}
// Count shown beside a folder: its own items, plus the subfolders for the locked “生成历史”.
export function folderCount(folders,folder){if(folder.system_key!==GENERATED)return folder.media_count||0;return (folder.media_count||0)+folders.filter(f=>f.parent_id===folder.id).reduce((n,f)=>n+(f.media_count||0),0)}

const indent=f=>`${'　'.repeat(f.depth)}${f.title}`
// Upload / new-folder targets: root and user folders (system folders only receive generation results).
export const uploadFolderOptions=folders=>[{value:'',label:'根目录'},...flattenFolders(folders,{filter:f=>!f.system_key}).map(f=>({value:f.id,label:indent(f)}))]
// “移动到文件夹”: root, user folders, and the system subfolder matching the kind when every item shares it.
// Labels are full parent paths (“父 / 子”), as in every “移动到文件夹” dialog (V2-FIX F6).
export const folderPathLabel=(folders,id)=>folderPath(folders,id).map(f=>f.title).join(' / ')
export function moveFolderOptions(folders,kinds){
 const unique=[...new Set(kinds)],options=[{value:'',label:'根目录'},...flattenFolders(folders,{filter:f=>!f.system_key}).map(f=>({value:f.id,label:folderPathLabel(folders,f.id)}))]
 if(unique.length===1){const system=folders.find(f=>f.system_key===generatedKindKey(unique[0]));if(system)options.push({value:system.id,label:folderPathLabel(folders,system.id)})}
 return options
}
// The folder every item is in now ('' = root); null when they are in different folders (V2-FIX F7).
export function currentFolderOf(media){const own=[...new Set(media.map(m=>m.folder_id||''))];return own.length===1?own[0]:null}
// Where an upload lands when started from the current view: the current user folder, otherwise root.
export function uploadTargetFor(folders,place){const folder=folders.find(f=>f.id===place);return folder&&!folder.system_key?folder.id:''}
// List filters for a navigation place: 'all' | 'root' | folder id. “生成历史” lists its three subfolders flat.
export function placeFilters(folders,place){if(place==='all')return {};if(place==='root')return {folder_id:'root'};const folder=folders.find(f=>f.id===place);return {folder_id:place,include_subfolders:folder?.system_key===GENERATED}}
export function placeTitle(folders,place){if(place==='all')return '全部素材';if(place==='root')return '根目录';const path=folderPath(folders,place);return path.length?path.map(f=>f.title).join(' / '):'文件夹'}

// Human summary of a delete preview (counts only; the dialog also lists each canvas by name).
export function deletePlanLines(plan){
 const lines=[`将永久删除 ${plan.items.length} 个素材及其文件。`]
 const nodes=plan.affected_workflows.reduce((n,w)=>n+(w.placeholder_nodes||0),0),stripped=plan.affected_workflows.reduce((n,w)=>n+(w.stripped_nodes||0),0)
 lines.push(plan.affected_workflows.length?`涉及 ${plan.affected_workflows.length} 个画布：${nodes} 个节点保留为“已删除”占位，${stripped} 个节点的参考、提及或组引用会移除这些素材。`:'没有画布引用这些素材。')
 if(plan.media_groups.length)lines.push(`素材组 ${plan.media_groups.map(g=>`“${g.title}”`).join('、')} 中的这些成员保留为“已删除”占位，可在素材组中移除。`)
 if(plan.characters.length)lines.push(`角色卡 ${plan.characters.map(c=>c.name).join('、')} 中对应的角色卡图或参考音频会被移除（角色卡本身保留）。`)
 if(plan.task_ids.length)lines.push(`${plan.task_ids.length} 个来源任务的任务卡保留，显示“结果已删除”。`)
 if(plan.missing.length)lines.push(`${plan.missing.length} 项已不存在，将跳过。`)
 return lines
}
