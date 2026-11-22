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
export const CHARACTERS='characters'
export const generatedKindKey=kind=>`generated_${kind}`
export const isGeneratedFolder=folder=>folder?.system_key===GENERATED||!!folder?.system_key?.startsWith(`${GENERATED}_`)
export const isCharacterFolder=folder=>folder?.system_key===CHARACTERS||!!folder?.system_key?.startsWith('character:')
export const characterFolderIds=folders=>new Set(folders.filter(f=>f.system_key?.startsWith('character:')).map(f=>f.id))
export const isInCharacterFolder=(folders,item)=>{const fid=mediaFolderId(item);return !!fid&&characterFolderIds(folders).has(fid)}
export const CHARACTER_DUPLICATE_MOVE_DISABLED_TITLE='角色卡文件夹中的素材由角色卡管理，不可手动移出；如需使用可直接引用或点「定位」查看'
export const canMoveDuplicates=(folders,items)=>Array.isArray(items)&&items.length>0&&!items.some(m=>isInCharacterFolder(folders,m))
// CHAR-FOLDERS-20261122 D3: resolve affected workflow IDs from DELETE /api/characters/<id>?delete_media=1,
// preferring server-returned workflow_ids or post-flush affected_workflows over the pre-delete preview.
export function characterDeleteWorkflowIds(res,preview=null){
 const raw=Array.isArray(res?.workflow_ids)
  ?res.workflow_ids
  :(Array.isArray(res?.affected_workflows)?res.affected_workflows:preview?.affected_workflows||[]).map(w=>w?.workflow_id)
 return [...new Set(raw.filter(Boolean))]
}
export const LIBRARY_MEDIA_DRAG='application/x-ink-library-move'

export const MEDIA_SORT_OPTIONS=[
 {value:'newest',label:'时间：最新优先'},
 {value:'oldest',label:'时间：最早优先'},
 {value:'name_asc',label:'名称：A–Z'},
 {value:'name_desc',label:'名称：Z–A'},
 {value:'size_desc',label:'大小：从大到小'},
 {value:'size_asc',label:'大小：从小到大'},
]

export function formatMediaDimensions(asset){
 const w=Number(asset?.width),h=Number(asset?.height)
 return Number.isInteger(w)&&w>0&&Number.isInteger(h)&&h>0?`${w}×${h}`:''
}

export function formatMediaDuration(seconds){
 const value=Number(seconds)
 if(!Number.isFinite(value)||value<=0)return ''
 if(value<60){
  const rounded=value<10?Number(value.toFixed(1)):Math.round(value)
  return `${rounded}s`
 }
 const total=Math.round(value),mins=Math.floor(total/60),secs=total%60
 return `${mins}:${String(secs).padStart(2,'0')}`
}

export function formatFileSize(bytes){
 const n=Number(bytes)
 if(!Number.isFinite(n)||n<0)return ''
 if(n<1024)return `${Math.round(n)} B`
 if(n<1024*1024)return `${(n/1024).toFixed(n<10*1024?1:0)} KB`
 if(n<1024*1024*1024)return `${(n/(1024*1024)).toFixed(n<10*1024*1024?1:0)} MB`
 return `${(n/(1024*1024*1024)).toFixed(2)} GB`
}

export function formatMediaSpec(asset){
 if(!asset)return ''
 const dims=asset.kind==='image'||asset.kind==='video'?formatMediaDimensions(asset):''
 const dur=asset.kind==='video'||asset.kind==='audio'?formatMediaDuration(asset.duration_seconds):''
 return [dims,dur].filter(Boolean).join(' · ')
}

// P1-TASK-LIBRARY-FLOW-20261120: drag-to-folder transfer plan enforcing 2026-11-19 lifecycle rules
// and CHAR-FOLDERS-20261122 managed character folder rules.
export function validateDragDrop(folders,items,targetFolder){
 if(!Array.isArray(items)||!items.length)return {allowed:false,code:'empty',message:'没有可移动的素材'}
 if(targetFolder?.system_key){
  if(isCharacterFolder(targetFolder)){
   return {allowed:false,code:'folder_character_managed',message:'角色卡文件夹由角色卡自动管理，请在角色卡界面添加素材'}
  }
  return {allowed:false,code:'folder_generated_only',message:'生成历史只接收新生成的结果，上传素材不可移入生成历史'}
 }
 if(items.some(item=>isInCharacterFolder(folders,item))){
  return {allowed:false,code:'folder_character_managed',message:'角色卡文件夹中的素材由角色卡管理，请在角色卡界面移除后自动回到根目录'}
 }
 const targetId=targetFolder?targetFolder.id:null
 const targetName=targetFolder?targetFolder.title:'根目录'
 const movable=items.filter(item=>(mediaFolderId(item)||null)!==targetId)
 if(!movable.length){
  return {allowed:true,noop:true,targetId,targetName,message:`所选素材已在「${targetName}」中`}
 }
 const mode=transferMode(folders,movable)
 return {allowed:true,noop:false,mode,items:movable,targetId,targetName}
}

export function formatDragDropNotice(plan,moved=[]){
 const sourceIds=new Set((plan.items||[]).map(item=>item.id))
 const copied=moved.filter(item=>!sourceIds.has(item.id)).length
 if(plan.mode==='copy'||(moved.length>0&&copied===moved.length)){
  return `已复制到「${plan.targetName}」（生成历史原项保留）`
 }
 if(copied>0){
  return `已整理 ${moved.length} 项到「${plan.targetName}」（其中 ${copied} 项生成结果为复制，生成历史原项保留）`
 }
 return `已移动到「${plan.targetName}」`
}

// Children map keyed by parent id ('' = root); orphans (missing parent) attach to root; order follows the server (system first, then creation).
export function folderChildren(folders){const ids=new Set(folders.map(f=>f.id)),map=new Map();for(const f of folders){const key=f.parent_id&&ids.has(f.parent_id)?f.parent_id:'';if(!map.has(key))map.set(key,[]);map.get(key).push(f)}return map}
export function folderPath(folders,id){const byId=new Map(folders.map(f=>[f.id,f])),path=[],seen=new Set();let current=byId.get(id);while(current&&!seen.has(current.id)){seen.add(current.id);path.unshift(current);current=byId.get(current.parent_id)}return path}
export function descendants(folders,id){const children=folderChildren(folders),out=new Set(),stack=[id];while(stack.length){for(const c of children.get(stack.pop())||[])if(!out.has(c.id)){out.add(c.id);stack.push(c.id)}}return out}
// Depth-first list with depth, for indented pickers (stable hierarchy order, cycle-safe).
export function flattenFolders(folders,{filter=()=>true}={}){const children=folderChildren(folders),out=[],seen=new Set(),walk=(parent,depth)=>{for(const f of children.get(parent)||[]){if(seen.has(f.id)||!filter(f))continue;seen.add(f.id);out.push({...f,depth});walk(f.id,depth+1)}};walk('',0);return out}
// Count shown beside a folder: its own items, plus the direct subfolders for locked “生成历史” and “角色卡”.
export function folderCount(folders,folder){if(folder.system_key!==GENERATED&&folder.system_key!==CHARACTERS)return folder.media_count||0;return (folder.media_count||0)+folders.filter(f=>f.parent_id===folder.id).reduce((n,f)=>n+(f.media_count||0),0)}

// Upload / new-folder / parent targets: root and user folders (system folders only receive generation results).
// Labels are full parent paths (“父 / 子”) so same-named folders in different places stay distinguishable (LIBRARY-OPS-FIX E9).
export const folderPathLabel=(folders,id)=>folderPath(folders,id).map(f=>f.title).join(' / ')
export const userFolderOptions=(folders,{exclude=new Set()}={})=>[{value:'',label:'根目录'},...flattenFolders(folders,{filter:f=>!f.system_key&&!exclude.has(f.id)}).map(f=>({value:f.id,label:folderPathLabel(folders,f.id)}))]
export const uploadFolderOptions=folders=>userFolderOptions(folders)
// “生成历史” and its 图片/视频/音频 subfolders only receive new generation results (E4; GEN-RESULT-LIFECYCLE-20261119:
// nothing is moved or copied into them, and a result moved out is copied — the original stays with its task).
export const GENERATED_ONLY_HINT='“生成历史”只接收新生成的结果，不能移入；从生成历史移到其他文件夹会复制一份独立素材，原结果仍留在生成历史并随任务删除，复制出的不受影响。'
// “移动到文件夹”: root and user folders; the system subfolder matching the kind is listed disabled with the reason.
export function moveFolderOptions(folders,kinds){
 const unique=[...new Set(kinds)],options=userFolderOptions(folders)
 if(unique.length===1){const system=folders.find(f=>f.system_key===generatedKindKey(unique[0]));if(system)options.push({value:system.id,label:`${folderPathLabel(folders,system.id)}（只接收新生成的结果）`,disabled:true})}
 return options
}
// GEN-RESULT-LIFECYCLE-20261119: items of “生成历史” (or task results whose folder is unknown) are copied, other items moved.
export const generatedFolderIds=folders=>new Set(folders.filter(f=>f.system_key?.startsWith(GENERATED+'_')).map(f=>f.id))
export const mediaFolderId=item=>item&&('folder_id' in item?item.folder_id:item.folderId)
export function transferMode(folders,media){const gen=generatedFolderIds(folders),n=media.filter(m=>{const fid=mediaFolderId(m);return fid===undefined||gen.has(fid)}).length;return !n?'move':n===media.length?'copy':'mixed'}
export const TRANSFER_TITLES={move:'移动到文件夹',copy:'复制到文件夹',mixed:'移动/复制到文件夹'}
export const transferLabel=(folders,media)=>TRANSFER_TITLES[transferMode(folders,media)]
// Client-side mirror of the server folder-name rules (E3, new folders and renames only): no “/”, unique among siblings
// (trimmed, case-insensitive, as the server). The server message is still shown verbatim when it rejects.
export function folderNameIssue(folders,title,parentId,selfId=null){
 const name=(title||'').trim()
 if(!name)return ''
 if(name.includes('/'))return '文件夹名称不能包含“/”'
 const key=name.toLowerCase()
 if(folders.some(f=>f.id!==selfId&&(f.parent_id||'')===(parentId||'')&&(f.title||'').trim().toLowerCase()===key))return `同一位置已有名为“${name}”的文件夹`
 return ''
}
// Chinese text for library API errors: the server message when present, else a fallback by error code.
const ERROR_CODES={folder_generated_only:'生成历史只接收生成结果，上传素材不能移入',folder_target_invalid:'生成历史下的图片/视频/音频只接收对应类型的生成结果',folder_character_managed:'角色卡文件夹由角色卡自动管理，请在角色卡界面增删素材',folder_name_conflict:'同一位置已有同名文件夹',invalid_name:'名称无效',folder_cycle:'文件夹不能移动到自身或子文件夹中',folder_not_empty:'文件夹非空，请先移出素材和子文件夹'}
export function libraryErrorText(e,fallback='操作失败'){const data=e?.response?.data;if(data?.error)return data.error;if(data?.code&&ERROR_CODES[data.code])return ERROR_CODES[data.code];if(e?.response?.status===409)return fallback;return e?.message||fallback}
// The folder every item is in now ('' = root); null when they are in different folders or unknown (V2-FIX F7).
export function currentFolderOf(media){if(!media.length||media.some(m=>mediaFolderId(m)===undefined))return null;const own=[...new Set(media.map(m=>mediaFolderId(m)||''))];return own.length===1?own[0]:null}
// Where an upload lands when started from the current view: the current user folder, otherwise root.
export function uploadTargetFor(folders,place){const folder=folders.find(f=>f.id===place);return folder&&!folder.system_key?folder.id:''}
// List filters for a navigation place: 'all' | 'root' | folder id. “生成历史” and “角色卡” list their subfolders flat.
export function placeFilters(folders,place){if(place==='all')return {};if(place==='root')return {folder_id:'root'};const folder=folders.find(f=>f.id===place);return {folder_id:place,include_subfolders:folder?.system_key===GENERATED||folder?.system_key===CHARACTERS}}
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
