import React,{useEffect,useState,useRef} from 'react'
import {createPortal} from 'react-dom'
import {Search,ListTree,ArrowDownAZ,Plus,FolderOpen,MoreHorizontal,ChevronRight,ChevronDown,X,Music,Upload,FilterX,UserRound,Lock,FolderInput,Trash2} from 'lucide-react'
import axios from 'axios'
import {uploadBatch,uploadSummary} from '../library/uploadBatch'
import {uploadMedia} from '../../lib/libraryApi'
import {notifyLibraryChanged,subscribeLibraryChanged} from '../../lib/librarySync'
import {listMediaFolders,listMedia,createMediaFolder,updateMediaFolder,deleteMediaFolder,moveMedia,folderPath as pathOf,isSystemFolder,getMediaInfo} from '../../lib/canvasMedia'
import {mediaNodeAsset} from '../../lib/canvasMediaStatus'
import {menuPosition} from './SidebarMenu'
// Portal: the glass sidebar would otherwise clip the fixed menu.
import SidebarMenu from './SidebarNavigationMenu'
import MediaPreview from './MediaPreview'
import {withPreviewPages} from './previewPages'
import MoveToFolderDialog from '../library/MoveToFolderDialog'
import LibraryOrganization from '../library/LibraryOrganization'
import {mediaItem,transferLabel,transferMode,validateDragDrop,formatDragDropNotice} from '../library/mediaLibrary'
import Select from '../ui/Select'
import {downloadAsset} from '../../lib/canvasAssetVersions'
import FolderIcon from './SidebarFolderIcon'
import LibraryThumbnail from '../library/LibraryThumbnail'
import useGridWindow from '../../lib/useGridWindow'
// LIBRARY-GLOBAL-20261116 S5: the sidebar "素材库" is the global local library (not a project
// library). Dragging or adding puts media ids on the canvas directly; nothing is copied.
export const PROJECT_ASSET_DRAG='application/x-ink-library-media'
const PAGE=200,ROOT='root',CANVAS_LIMIT=500
const errorText=e=>e?.response?.data?.error||e?.message||'操作失败'
const MEDIA_NAME_RULE='素材名称须为1至240个字符，不能包含 / 、\\ 或控制字符'
// V2-FIX-20261117 F3: rename a library media (S6b contract: PATCH {name} → {media}); only the
// display/download name changes, the file, id and folder stay.
export async function renameMediaItem(id,name){try{return (await axios.patch(`/api/canvas/media/${encodeURIComponent(id)}`,{name})).data.media}catch(e){if(e?.response?.data?.code==='invalid_name')throw new Error(MEDIA_NAME_RULE);if(e?.response?.status===410)throw new Error('该素材已在素材库中删除');throw e}}
// V2-FIX-20261117 F12: the sidebar library is a library entry, so its uploads are origin "upload"
// (canvas drops/pastes keep canvas_upload). A folder deleted meanwhile falls back to the root once.
async function uploadToLibrary(file,folderId){try{return {...await uploadMedia(file,{folderId}),folderFallback:false}}catch(e){if(!folderId||e?.response?.data?.code!=='folder_not_found')throw e;return {...await uploadMedia(file,{folderId:null}),folderFallback:true}}}
export default function AssetTree({refresh=0,contentRefresh=0,onCount,onManage,onCharacters,onAddAssets,onAddReference,referenceTarget=null,disabled=false,ioBusy=false,reveal=null,uploadFolder=null,onUploadFolder,onBeforeDelete,onDeleted}) {
 const uploadRef=useRef(null),uploadInto=useRef(null),scrollRef=useRef(null),treeRef=useRef(null),menuOpener=useRef(null),dialogOpener=useRef(null),anchorMedia=useRef(null),[notice,setNotice]=useState(''),[loaded,setLoaded]=useState(false)
 const [folders,setFolders]=useState([]),[pages,setPages]=useState({}),[expanded,setExpanded]=useState([]),[query,setQuery]=useState(''),[search,setSearch]=useState(false),[found,setFound]=useState(null),[sort,setSort]=useState(false),[selected,setSelected]=useState(null),[selectedMedia,setSelectedMedia]=useState([]),[editing,setEditing]=useState(null),[menu,setMenu]=useState(null),[preview,setPreview]=useState(null),[moving,setMoving]=useState(null),[deleting,setDeleting]=useState(null),[referencesItem,setReferencesItem]=useState(null),[title,setTitle]=useState(''),[parent,setParent]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[duplicates,setDuplicates]=useState(null),[dropFolder,setDropFolder]=useState(null)
 const pagesRef=useRef(pages),draggingRef=useRef(null),dropFolderRef=useRef(null),lastForbiddenDropRef=useRef(0);pagesRef.current=pages
 async function loadFolder(key){const result=await listMedia({folder_id:key,limit:PAGE});setPages(current=>({...current,[key]:{items:result.items||[],total:result.total||0}}));return result}
 async function load(){const [list,all]=await Promise.all([listMediaFolders(),listMedia({limit:1})]);setFolders(list);onCount?.(all.total||0);await Promise.all([ROOT,...Object.keys(pagesRef.current).filter(key=>key!==ROOT&&list.some(f=>f.id===key))].map(loadFolder))}
 useEffect(()=>{let alive=true;setMenu(null);setError('');load().then(()=>{if(alive)setLoaded(true)}).catch(e=>{if(alive)setError(errorText(e))});return()=>{alive=false}},[refresh])
 // V2-FIX-20261117 F4: a generation finished (results written back) → reload folders, counts and
 // open folders quietly, without closing an open menu or dialog.
 const contentSeen=useRef(contentRefresh)
 useEffect(()=>{if(contentRefresh===contentSeen.current)return;contentSeen.current=contentRefresh;load().catch(()=>{})},[contentRefresh])
 // V2-REAL-USE F4: also refresh quietly when tasks finish in the task center / another canvas / another tab.
 useEffect(()=>subscribeLibraryChanged(()=>{load().catch(()=>{})}),[])
 // Server-side name search across the whole library (not only loaded folders).
 useEffect(()=>{if(!query.trim()){setFound(null);return}const controller=new AbortController(),timer=setTimeout(()=>listMedia({q:query.trim(),limit:PAGE},controller.signal).then(result=>setFound({items:result.items||[],total:result.total||0})).catch(e=>{if(!controller.signal.aborted)setError(errorText(e))}),250);return()=>{clearTimeout(timer);controller.abort()}},[query,refresh,contentRefresh])
 // "在素材库中显示": open the media's folder path, load it, select and scroll to the row.
 async function revealMediaItem(mediaId,alive=()=>true){const media=await getMediaInfo(mediaId),list=await listMediaFolders();if(!alive())return;setFolders(list);setQuery('');setSearch(false);const key=media.folder_id||ROOT,result=await loadFolder(key);if(!alive())return;if(!(result.items||[]).some(item=>item.id===media.id))setPages(current=>({...current,[key]:{...current[key],items:[media,...(current[key]?.items||[])]}}));const chain=[],seen=new Set();let id=media.folder_id;while(id&&!seen.has(id)){seen.add(id);chain.push(id);id=list.find(f=>f.id===id)?.parent_id}setExpanded(current=>[...new Set([...current,...chain])]);setSelected(media.id);requestAnimationFrame(()=>requestAnimationFrame(()=>scrollRef.current?.querySelector(`[data-media-id="${media.id}"]`)?.scrollIntoView?.({block:'nearest'})))}
 useEffect(()=>{if(!reveal?.id)return;let alive=true;revealMediaItem(reveal.id,()=>alive).catch(e=>{if(alive)setError(e?.response?.status===410?'该素材已在素材库中删除':errorText(e))});return()=>{alive=false}},[reveal?.nonce])
 // LIBRARY-OPS-FIX-20261117 E6: a sidebar error can be dismissed and clears itself after a while.
 useEffect(()=>{if(!error||editing)return;const timer=setTimeout(()=>setError(''),8000);return()=>clearTimeout(timer)},[error,editing])
 // LIBRARY-OPS-FIX2-20261117 R4: a success notice clears itself after about 5 seconds (and can be closed).
 useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(''),5000);return()=>clearTimeout(timer)},[notice])
 const focusTreeFallback=()=>{const fallback=treeRef.current?.querySelector('button[aria-label="上传到素材库"]:not(:disabled)')||treeRef.current?.querySelector('.cv-sidebar-tools button:not(:disabled)');fallback?.focus({preventScroll:true})}
 // R2 + BACKLOG-LIBRARY-SIDEBAR: dialogs opened from the sidebar give focus back to the opener; after a move
 // where the row left its source folder, focus returns to the moved item / target folder / tree list (never body or 搜索).
 const opener=()=>menu?menuOpener.current:document.activeElement
 function restoreFocus(hint=null){
  const target=dialogOpener.current;dialogOpener.current=null
  const apply=()=>{
   const active=document.activeElement
   if(active&&active!==document.body&&!active.closest?.('[role=menu]'))return
   if(target?.isConnected&&!target.disabled){target.focus({preventScroll:true});return}
   if(hint?.movedIds?.length){
    for(const id of hint.movedIds){
     const rowBtn=scrollRef.current?.querySelector(`[data-media-id="${CSS.escape(id)}"] .cv-tree-asset`)
     if(rowBtn){rowBtn.focus({preventScroll:true});return}
    }
   }
   if(hint?.folderId){
    const folderBtn=scrollRef.current?.querySelector(`[data-folder-id="${CSS.escape(hint.folderId)}"] .cv-folder-name`)
    if(folderBtn){folderBtn.focus({preventScroll:true});return}
   }
   const listItem=scrollRef.current?.querySelector('.cv-tree-asset, .cv-folder-name')
   if(listItem){listItem.focus({preventScroll:true});return}
   focusTreeFallback()
  }
  requestAnimationFrame(()=>hint?requestAnimationFrame(apply):apply())
 }
 function closeEditor(){setEditing(null);setError('');restoreFocus()}
 function closeMoving(){setMoving(null);restoreFocus()}
 function closeDeleting(){setDeleting(null);restoreFocus()}
 function edit(kind,item,mode='rename'){if(busy)return;dialogOpener.current=opener();setMenu(null);setEditing({kind,id:item?.id,mode,sub:kind==='new'&&!!item});setTitle(kind==='new'?'':kind==='media'?item?.name||'':item?.title||'');setParent(kind==='folder'?item.parent_id||'':kind==='new'?item?.id||'':'');setError('')}
 async function run(operation){const origin=document.activeElement;setBusy(true);setError('');try{await operation();setMenu(null)}catch(e){setError(errorText(e));requestAnimationFrame(()=>{const now=document.activeElement;if(origin?.isConnected&&!origin.disabled&&(!now||now===document.body))origin.focus({preventScroll:true})})}finally{setBusy(false)}}
 async function mutate(operation){setBusy(true);setError('');try{await operation();await load();notifyLibraryChanged({source:'sidebar_mutate'});setEditing(null);setMenu(null);restoreFocus()}catch(e){setError(errorText(e))}finally{setBusy(false)}}
 function openMenu(event,kind,item){event.preventDefault();event.stopPropagation();const trigger=event.currentTarget;menuOpener.current=trigger.matches?.('button')?trigger:trigger.querySelector?.('.cv-tree-more');setSelected(item.id);setError('');const position=menuPosition(event);position.x=Math.min(position.x,event.currentTarget.closest('.cv-sidebar').getBoundingClientRect().right-249);setMenu({kind,item,...position})}
 const asAssets=items=>items.map(mediaNodeAsset)
 const mediaById=new Map()
 for(const page of Object.values(pages))for(const item of page.items||[])mediaById.set(item.id,item)
 for(const item of found?.items||[])mediaById.set(item.id,item)
 const selectedMediaSet=new Set(selectedMedia)
 const selectedMediaItems=selectedMedia.map(id=>mediaById.get(id)).filter(Boolean)
 function dragAssets(event,items){if(!items.length){event.preventDefault();return}const payload=items.length===1&&selectedMediaSet.has(items[0].id)&&selectedMediaItems.length>1?selectedMediaItems:items;draggingRef.current=payload;lastForbiddenDropRef.current=0;event.dataTransfer.setData(PROJECT_ASSET_DRAG,JSON.stringify({media:asAssets(payload)}));event.dataTransfer.effectAllowed='copyMove'}
 function dragAssetsEnd(){if(dropFolderRef.current?.forbidden||(lastForbiddenDropRef.current&&Date.now()-lastForbiddenDropRef.current<350))setError('生成历史只接收新生成的结果，上传素材不可移入生成历史');lastForbiddenDropRef.current=0;draggingRef.current=null;dropFolderRef.current=null;setDropFolder(null)}
 function folderDragOver(event,folder){
  if(busy||!draggingRef.current?.length&&![...(event.dataTransfer?.types||[])].includes(PROJECT_ASSET_DRAG))return
  event.preventDefault()
  if(isSystemFolder(folder)){
   event.dataTransfer.dropEffect='none'
   lastForbiddenDropRef.current=Date.now()
   if(dropFolderRef.current?.id!==folder.id||!dropFolderRef.current?.forbidden){const next={id:folder.id,forbidden:true};dropFolderRef.current=next;setDropFolder(next)}
   return
  }
  lastForbiddenDropRef.current=0
  const mode=draggingRef.current?.length?transferMode(folders,draggingRef.current):'move'
  event.dataTransfer.dropEffect=mode==='copy'?'copy':'move'
  if(dropFolderRef.current?.id!==folder.id||dropFolderRef.current?.forbidden){const next={id:folder.id,forbidden:false};dropFolderRef.current=next;setDropFolder(next)}
 }
 function folderDragLeave(event,folder){
  if(event.currentTarget.contains(event.relatedTarget))return
  if(dropFolderRef.current?.id===folder.id){dropFolderRef.current=null;setDropFolder(null)}
 }
 function folderDrop(event,folder){
  const dragged=draggingRef.current||(()=>{try{const raw=event.dataTransfer?.getData?.(PROJECT_ASSET_DRAG);const parsed=raw?JSON.parse(raw):null;return (parsed?.media||[]).map(a=>mediaById.get(a.id)||a)}catch{return []}})()
  if(!dragged.length)return
  event.preventDefault();event.stopPropagation()
  draggingRef.current=null;lastForbiddenDropRef.current=0;dropFolderRef.current=null;setDropFolder(null)
  const plan=validateDragDrop(folders,dragged,folder)
  if(!plan.allowed){setError(plan.message);return}
  if(plan.noop){setNotice(plan.message);return}
  run(async()=>{
   const moved=await moveMedia(plan.items.map(item=>item.id),plan.targetId)
   setSelectedMedia([])
   setNotice(formatDragDropNotice(plan,moved))
   await load()
   notifyLibraryChanged({source:'sidebar_drag_move'})
  })
 }
 // Folder contents including subfolders, in pages, up to the canvas node limit.
 async function folderMedia(id){const items=[];let page=1,total=Infinity;while(items.length<total&&items.length<CANVAS_LIMIT){const result=await listMedia({folder_id:id,include_subfolders:1,limit:PAGE,page});items.push(...(result.items||[]));total=result.total||0;if(!(result.items||[]).length)break;page++}if(total>CANVAS_LIMIT)throw new Error(`文件夹中有 ${total} 个素材，超过画布 ${CANVAS_LIMIT} 个上限，请选择子文件夹`);if(!items.length)throw new Error('文件夹中没有可添加的素材');return items}
 // LIBRARY-OPS-FIX-20261117 D1 (same rule as the library dialog, user decision 2026-11-17): an upload whose
 // content is already in the library elsewhere names that folder and offers 「定位」/「移到当前文件夹」; never moved automatically.
 async function uploadFiles(files,folderId){setDuplicates(null);await run(async()=>{let fallback=false,repeated=0;const found=[];const result=await uploadBatch(files,async file=>{const out=await uploadToLibrary(file,folderId);fallback=fallback||out.folderFallback;if(out.deduplicated){repeated++;if(out.media)found.push({media:out.media,target:out.folderFallback?null:folderId})}});const elsewhere=[...new Map(found.filter(f=>(f.media.folder_id||null)!==(f.target||null)).map(f=>[f.media.id,f.media])).values()];setNotice(`${uploadSummary(result)}${repeated?`；${repeated} 项内容已在库中，未重复保存`:''}${fallback?'；目标文件夹已不存在，已存到根目录':''}`);setDuplicates(elsewhere.length?{items:elsewhere,target:fallback?null:folderId}:null);await load();notifyLibraryChanged({source:'sidebar_upload'});if(result.error)throw result.error})}
 const placeName=id=>id?folderPath(id)||'文件夹':'根目录'
 function locateDuplicates(){const first=duplicates.items[0];run(()=>revealMediaItem(first.id))}
 function moveDuplicates(){const {items,target}=duplicates;run(async()=>{const ids=items.map(m=>m.id),moved=await moveMedia(ids,target),copied=moved.filter(m=>!ids.includes(m.id)).length;setDuplicates(null);setNotice(copied?`已把 ${moved.length} 项放到「${placeName(target)}」（其中 ${copied} 项生成结果为复制，原结果留在生成历史）`:`已把 ${moved.length} 项移到「${placeName(target)}」`);await load();notifyLibraryChanged({source:'sidebar_move_dup'});if(moved[0])await revealMediaItem(moved[0].id)})}
 const children=id=>folders.filter(f=>(f.parent_id||null)===id)
 const descendants=id=>{const found=new Set([id]);let changed=true;while(changed){changed=false;for(const f of folders)if(found.has(f.parent_id)&&!found.has(f.id)){found.add(f.id);changed=true}}return found}
 const folderPath=id=>pathOf(folders,id)
 const excluded=editing?.kind==='folder'?descendants(editing.id):new Set(),order=items=>items.slice().sort(sort?(a,b)=>(a.title||a.name).localeCompare(b.title||b.name):()=>0)
 const toggle=id=>{setExpanded(items=>items.includes(id)?items.filter(item=>item!==id):[...items,id]);if(!pagesRef.current[id])loadFolder(id).catch(e=>setError(errorText(e)))}
 // V2-REAL-USE F5: flat visible media order for Shift+click range selection.
 function visibleMediaIds(){
  if(found)return order(found.items).map(a=>a.id)
  const ids=[]
  const walk=parentId=>{for(const f of order(children(parentId))){if(!expanded.includes(f.id))continue;walk(f.id);for(const item of order(pages[f.id]?.items||[]))ids.push(item.id)}}
  walk(null)
  for(const item of order(pages[ROOT]?.items||[]))ids.push(item.id)
  return ids
 }
 function selectAsset(item,event){
  const id=item.id
  if(event?.shiftKey){
   const list=visibleMediaIds(),anchor=anchorMedia.current||selected,a=list.indexOf(anchor),b=list.indexOf(id)
   if(a>=0&&b>=0){
    const range=list.slice(Math.min(a,b),Math.max(a,b)+1)
    setSelectedMedia(current=>[...new Set([...(event.ctrlKey||event.metaKey?current:[]),...range])])
   }else{
    setSelectedMedia(current=>[...new Set([...current,id])])
   }
   setSelected(id)
   return
  }
  if(event?.ctrlKey||event?.metaKey){
   setSelectedMedia(current=>{
    const seed=current.length?current:(selected&&mediaById.has(selected)&&selected!==id?[selected]:[])
    return seed.includes(id)?seed.filter(x=>x!==id):[...seed,id]
   })
   anchorMedia.current=id;setSelected(id)
   return
  }
  anchorMedia.current=id;setSelected(id);setSelectedMedia([])
 }
 function toggleAssetCheck(item){
  const id=item.id
  anchorMedia.current=id;setSelected(id)
  setSelectedMedia(current=>current.includes(id)?current.filter(x=>x!==id):[...current,id])
 }
 const openAssetPreview=(item,list)=>{const current=mediaNodeAsset(item),siblings=(list||[]).map(mediaNodeAsset);setPreview(withPreviewPages(current,siblings))}
 const rowActions=useRef(null);rowActions.current={dragAssets,dragAssetsEnd,openMenu,selectAsset,toggleAssetCheck,openPreview:openAssetPreview}
 function assetRows(key,depth=0){const page=pages[key];if(!page)return key===ROOT?null:<p className="cv-sidebar-empty" role="status" key={`${key}-loading`}>正在载入…</p>;return <React.Fragment key={`${key}-items`}>{<WindowedAssets items={order(page.items)} selected={selected} selectedMediaSet={selectedMediaSet} depth={depth} disabled={disabled} actions={rowActions}/>}{page.total>page.items.length&&<p className="cv-sidebar-empty cv-tree-more-note">还有 {page.total-page.items.length} 项，请展开素材库查看全部</p>}</React.Fragment>}
 function branch(parentId,depth=0){return order(children(parentId)).map(f=>{const open=expanded.includes(f.id),system=isSystemFolder(f),count=f.media_count??0,hasChildren=count>0||children(f.id).length>0,dropState=dropFolder?.id===f.id?(dropFolder.forbidden?' is-drop-forbidden':' is-drop-target'):'';return <div key={f.id} className="cv-tree-branch" data-depth={depth}><div className={`cv-tree-folder ${selected===f.id?'is-selected':''}${dropState}`} data-folder-id={f.id} draggable={!disabled&&!!pages[f.id]?.items?.length} onDragStart={e=>{const items=pagesRef.current[f.id]?.items||[];if(!items.length){e.preventDefault();return}dragAssets(e,items)}} onDragEnd={dragAssetsEnd} onDragOver={e=>folderDragOver(e,f)} onDragLeave={e=>folderDragLeave(e,f)} onDrop={e=>folderDrop(e,f)} onContextMenu={e=>openMenu(e,'folder',f)}>{hasChildren?<button className="cv-folder-toggle" aria-label={`${open?'折叠':'展开'}文件夹 ${f.title}`} title={open?'折叠文件夹':'展开文件夹'} aria-expanded={open} onClick={()=>toggle(f.id)}>{open?<ChevronDown size={14}/>:<ChevronRight size={14}/>}</button>:<span className="cv-folder-toggle cv-folder-toggle-empty" aria-hidden="true"/>}<button className="cv-folder-name" aria-current={selected===f.id?'true':undefined} onClick={()=>{setSelected(f.id);setSelectedMedia([]);toggle(f.id)}}><FolderIcon icon={f.icon}/><span>{f.title}</span>{system&&<Lock size={12} className="cv-folder-lock" data-system-lock="true" aria-label="系统文件夹（已锁定）"/>}{uploadFolder===f.id&&<small className="cv-folder-upload-mark" title="画布上传存放在此文件夹">上传位置</small>}{count>0&&<small className="cv-folder-count">{count}</small>}</button><button className="cv-tree-more" aria-label={`管理文件夹 ${f.title}`} title="文件夹操作" onClick={e=>openMenu(e,'folder',f)}><MoreHorizontal size={20}/></button></div>{open&&<div className="cv-tree-children" data-depth={depth+1}>{branch(f.id,depth+1)}{assetRows(f.id,depth+1)}</div>}</div>})}
 const empty=loaded&&!folders.length&&!pages[ROOT]?.items?.length
 const generatedKind=folder=>!!folder?.system_key?.startsWith('generated')
 const menuFolder=menu?.kind==='folder'?menu.item:null
 const openUpload=folderId=>{uploadInto.current=folderId;uploadRef.current?.click()}
 // V2-FIX-20261117 F1: the toolbar upload goes into the folder selected in the tree (not a
 // "生成历史" folder); with no folder selected, into the canvas upload location (or the root).
 const selectedFolder=folders.find(f=>f.id===selected&&!generatedKind(f)),toolbarTarget=selectedFolder?.id||uploadFolder||null
 const dismissError=()=>{setError('');requestAnimationFrame(focusTreeFallback)}
 const dismissDuplicates=()=>{setDuplicates(null);requestAnimationFrame(focusTreeFallback)}
 const dismissNotice=()=>{setNotice('');requestAnimationFrame(focusTreeFallback)}
 return <div className={`cv-asset-tree${selectedMediaItems.length?' has-multi':''}`} ref={treeRef}><div className="cv-sidebar-tools"><button aria-label="搜索素材库" title="搜索素材（全部文件夹）" aria-expanded={search} onClick={()=>setSearch(!search)}><Search size={18}/></button><button aria-label="折叠或展开全部文件夹" title="折叠／展开全部文件夹" onClick={()=>{if(expanded.length)setExpanded([]);else{setExpanded(folders.map(f=>f.id));for(const f of folders)if(!pagesRef.current[f.id])loadFolder(f.id).catch(()=>{})}}}><ListTree size={18}/></button><button aria-label="按名称排序素材" title="按名称排序" aria-pressed={sort} onClick={()=>setSort(!sort)}><ArrowDownAZ size={18}/></button>{(query||sort)&&<button className="cv-clear-filter" aria-label="清除素材搜索与排序" title="清除搜索与排序" onClick={()=>{setQuery('');setSearch(false);setSort(false)}}><FilterX size={16}/>清除筛选</button>}<span className="cv-sidebar-tools-spacer"/><button aria-label="上传到素材库" title={`上传到素材库（${toolbarTarget&&folderPath(toolbarTarget)||'根目录'}）`} data-upload-target={toolbarTarget||''} disabled={busy||disabled} onClick={()=>openUpload(toolbarTarget)}><Upload size={18}/></button><button aria-label="新建文件夹" title="新建文件夹" disabled={busy} onClick={()=>edit('new',null)}><Plus size={21}/></button>{onCharacters&&<button aria-label="打开角色卡库" title="角色卡（全局共用）" onClick={onCharacters}><UserRound size={19}/></button>}<button className="cv-assets-manage" aria-label="展开素材库" title="展开素材库" onClick={onManage}><FolderOpen size={19}/>展开素材库</button></div>
 <div className="cv-upload-target"><span>画布上传存到</span><Select ariaLabel="画布上传存放的文件夹" value={uploadFolder&&folders.some(f=>f.id===uploadFolder)?uploadFolder:''} onChange={value=>onUploadFolder?.(value||null)} options={[{value:'',label:'根目录'},...folders.filter(f=>!generatedKind(f)).map(f=>({value:f.id,label:folderPath(f.id)}))]}/></div>
 {selectedMediaItems.length>0&&<div className="cv-tree-bulk-bar" role="toolbar" aria-label="侧栏素材批量操作" data-testid="sidebar-bulk-bar"><span>已选 {selectedMediaItems.length} 项</span><button disabled={busy} aria-haspopup="dialog" onClick={()=>{dialogOpener.current=document.activeElement;setMoving(selectedMediaItems)}}><FolderInput size={13} aria-hidden="true"/>{transferLabel(folders,selectedMediaItems)}</button><button className="is-danger" disabled={busy} aria-haspopup="dialog" onClick={()=>{dialogOpener.current=document.activeElement;setDeleting(selectedMediaItems.map(mediaItem))}}><Trash2 size={13} aria-hidden="true"/>删除</button><button aria-label="清空多选" title="清空多选" disabled={busy} onClick={()=>{setSelectedMedia([]);requestAnimationFrame(focusTreeFallback)}}>取消</button></div>}
 {search&&<div className="cv-sidebar-search"><Search size={16}/><input autoFocus aria-label="搜索素材库" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索全部素材"/><button aria-label="关闭素材搜索" title="关闭素材搜索" onClick={()=>{setSearch(false);setQuery('')}}><X size={15}/></button></div>}{error&&!editing&&<p role="alert" className="cv-tree-alert"><span>{error}</span><button aria-label="关闭错误提示" title="关闭错误提示" onClick={dismissError}><X size={14}/></button></p>}{duplicates&&<div className="cv-tree-duplicate" role="status" aria-label="内容重复的上传"><p>{duplicates.items.length===1?'上传的内容已在库中：':`${duplicates.items.length} 项上传的内容已在库中：`}{duplicates.items.slice(0,3).map((m,i)=><React.Fragment key={m.id}>{i?'；':''}「{m.name}」已在「{placeName(m.folder_id)}」中</React.Fragment>)}{duplicates.items.length>3&&` 等 ${duplicates.items.length} 项`}。未重复保存，也未自动移动。</p><div><button disabled={busy} title={`在「${placeName(duplicates.items[0].folder_id)}」中显示该素材`} onClick={locateDuplicates}>定位</button><button disabled={busy} title={`移到「${placeName(duplicates.target)}」（只改变所在文件夹；生成历史中的结果会复制一份，原结果留在生成历史）`} onClick={moveDuplicates}>移到当前文件夹</button><button aria-label="关闭重复提示" title="关闭重复提示" disabled={busy} onClick={dismissDuplicates}><X size={14}/></button></div></div>}
 <div className="cv-tree-scroll" ref={scrollRef}>{found?<>{<WindowedAssets items={order(found.items)} selected={selected} selectedMediaSet={selectedMediaSet} depth={0} disabled={disabled} actions={rowActions}/>}{!found.items.length&&<p className="cv-sidebar-empty" role="status">没有匹配的素材</p>}{found.total>found.items.length&&<p className="cv-sidebar-empty">仅显示前 {found.items.length} 项，共 {found.total} 项</p>}</>:<>{branch(null)}{assetRows(ROOT,0)}</>}{!loaded&&!error&&<p className="cv-sidebar-empty" role="status">正在载入素材…</p>}{empty&&!error&&<div className="cv-sidebar-empty cv-tree-empty"><p>素材库还没有素材</p><button className="btn btn-primary" disabled={busy||disabled} onClick={()=>openUpload(uploadFolder)}><Upload size={15}/>上传素材</button></div>}{notice&&<p className="cv-sidebar-empty cv-tree-notice" role="status"><span>{notice}</span><button aria-label="关闭提示" title="关闭提示" onClick={dismissNotice}><X size={14}/></button></p>}</div>
 {menu&&<SidebarMenu maxWidth={260} focusKey={menu.sub||'root'} label={menu.kind==='folder'?'文件夹操作':'素材操作'} position={menu} onClose={()=>!busy&&setMenu(null)}>{menuFolder?<><button role="menuitem" disabled={busy||disabled||!(menuFolder.media_count>0||children(menuFolder.id).length)} onClick={()=>run(()=>onAddAssets(async()=>asAssets(await folderMedia(menuFolder.id))))}>添加到画布</button>{referenceTarget&&<button role="menuitem" disabled={busy||disabled} title={`追加到“${referenceTarget.title}”的参考末尾`} onClick={()=>run(()=>onAddReference(async()=>asAssets(await folderMedia(menuFolder.id)),null))}>作为参考添加到所选节点</button>}<hr/>{!generatedKind(menuFolder)&&<button role="menuitem" disabled={busy||disabled} onClick={()=>{setMenu(null);openUpload(menuFolder.id)}}>上传到此文件夹</button>}{!generatedKind(menuFolder)&&<button role="menuitem" disabled={busy} onClick={()=>{onUploadFolder?.(uploadFolder===menuFolder.id?null:menuFolder.id);setMenu(null)}}>{uploadFolder===menuFolder.id?'取消画布上传位置':'设为画布上传位置'}</button>}{isSystemFolder(menuFolder)?<p className="cv-menu-note" role="note">系统文件夹不可重命名、移动或删除</p>:<><button role="menuitem" disabled={busy} onClick={()=>edit('new',menuFolder)}>新建子文件夹</button><button role="menuitem" disabled={busy} aria-haspopup="dialog" onClick={()=>edit('folder',menuFolder,'move')}>移动到</button><button role="menuitem" disabled={busy} onClick={()=>edit('folder',menuFolder)}>重命名</button>{(()=>{const full=menuFolder.media_count>0||children(menuFolder.id).length>0,reason='文件夹非空，请先移出素材和子文件夹';return <button role="menuitem" className="is-danger" disabled={busy||full} title={full?reason:'仅可删除空文件夹'} aria-label="删除空文件夹" aria-description={full?reason:undefined} onClick={()=>edit('folder',menuFolder,'delete')}>删除{full&&<small className="cv-menu-note">{reason}</small>}</button>})()}</>}</>:<><button role="menuitem" disabled={busy||disabled} onClick={()=>run(()=>onAddAssets(asAssets([menu.item])))}>添加到画布</button>{referenceTarget&&<button role="menuitem" disabled={busy||disabled} title={`追加到“${referenceTarget.title}”的参考末尾`} onClick={()=>run(()=>onAddReference(asAssets([menu.item]),[menu.item.kind]))}>作为参考添加到所选节点</button>}<button role="menuitem" onClick={()=>{const list=found?order(found.items):order(pagesRef.current[menu.item.folder_id||ROOT]?.items||[menu.item]);openAssetPreview(menu.item,list);setMenu(null)}}>预览</button><button role="menuitem" onClick={()=>run(()=>downloadAsset(mediaNodeAsset(menu.item)))}>下载</button><hr/><button role="menuitem" disabled={busy} aria-haspopup="dialog" onClick={()=>{dialogOpener.current=opener();setReferencesItem(menu.item);setMenu(null)}}>查看引用位置</button><button role="menuitem" disabled={busy} aria-haspopup="dialog" onClick={()=>edit('media',menu.item)}>重命名</button><button role="menuitem" disabled={busy} aria-haspopup="dialog" onClick={()=>{dialogOpener.current=opener();setMoving([menu.item]);setMenu(null)}}>{transferLabel(folders,[menu.item])}</button><button role="menuitem" className="is-danger" disabled={busy} aria-haspopup="dialog" onClick={()=>{dialogOpener.current=opener();setDeleting([mediaItem(menu.item)]);setMenu(null)}}>删除</button></>}</SidebarMenu>}
 {busy&&!editing&&!ioBusy&&<p className="cv-sidebar-empty" role="status">正在处理素材…</p>}
 {editing&&<FolderProperties editing={editing} title={title} setTitle={setTitle} parent={parent} setParent={setParent} folders={folders.filter(f=>!excluded.has(f.id)&&!isSystemFolder(f))} folderPath={folderPath} busy={busy} error={error} onClose={closeEditor} onSave={()=>mutate(()=>editing.kind==='media'?renameMediaItem(editing.id,title.trim()).then(media=>setNotice(`已重命名为“${media.name}”`)):editing.mode==='delete'?deleteMediaFolder(editing.id):editing.kind==='new'?createMediaFolder(title.trim(),parent||null):updateMediaFolder(editing.id,{title:title.trim(),parent_id:parent||null}))}/>}
 {moving&&<MoveToFolderDialog media={moving} onClose={closeMoving} onDone={outcome=>{setMoving(null);setSelectedMedia([]);setNotice(outcome.text);load().catch(e=>setError(errorText(e))).finally(()=>restoreFocus({movedIds:(outcome.moved||[]).map(m=>m.id),folderId:outcome.folder?.id||null}))}}/>}
 {deleting&&<LibraryOrganization action={{kind:'remove',items:deleting}} folders={folders} selection={deleting} onBeforeDelete={onBeforeDelete} onDeleted={outcome=>{onDeleted?.(outcome);notifyLibraryChanged({source:'sidebar_delete'})}} onClose={closeDeleting} onDone={outcome=>{setDeleting(null);setSelectedMedia([]);const count=outcome?.deleted_ids?.length||0,missing=outcome?.missing?.length||0;setNotice(`已永久删除 ${count} 个素材${missing?`（${missing} 项已不存在，已跳过）`:''}`);load().catch(e=>setError(errorText(e))).finally(()=>restoreFocus({}))}}/>}
 {referencesItem&&<LibraryOrganization action={{kind:'references',item:referencesItem}} folders={folders} selection={[mediaItem(referencesItem)]} onClose={()=>{setReferencesItem(null);restoreFocus()}} onDone={()=>{setReferencesItem(null);restoreFocus()}}/>}
 {preview&&<MediaPreview key={preview.id||preview.url} asset={preview} onClose={()=>setPreview(null)}/>}
 <input ref={uploadRef} type="file" multiple hidden accept="image/*,video/*,audio/*" aria-label="上传素材库文件" onChange={e=>{const files=[...e.target.files];e.target.value='';if(files.length)uploadFiles(files,uploadInto.current||null)}}/>
 </div>
}
function FolderProperties({editing,title,setTitle,parent,setParent,folders,folderPath,busy,error,onClose,onSave}) {
 const ref=useRef(null);useEffect(()=>{ref.current?.querySelector('input,button')?.focus()},[]);useEffect(()=>{if(busy)ref.current?.focus();else if(!ref.current?.contains(document.activeElement))(ref.current?.querySelector('input:not(:disabled)')||ref.current)?.focus()},[busy])
 // R2: Esc closes the dialog even if focus fell outside it (e.g. after a rejected save).
 useEffect(()=>{const onKey=e=>{if(e.key==='Escape'&&!busy&&!ref.current?.contains(document.activeElement)&&(document.activeElement===document.body||!document.activeElement)){e.preventDefault();onClose()}};document.addEventListener('keydown',onKey);return()=>document.removeEventListener('keydown',onKey)},[busy,onClose])
 const media=editing.kind==='media',heading=media?'重命名素材':editing.mode==='delete'?`删除文件夹“${title}”？`:editing.kind==='new'?(editing.sub?'新建子文件夹':'新建文件夹'):editing.mode==='move'?'移动文件夹':'重命名文件夹'
 const dialogLabel=editing.mode==='delete'?'删除文件夹':heading,confirm=media?'保存名称':editing.mode==='delete'?'确认删除文件夹':editing.kind==='new'?'创建文件夹':editing.mode==='move'?'移动':'保存名称'
 // Portal: the glass sidebar is the containing block for fixed overlays and would clip this dialog.
 return createPortal(<div className="canvas-studio cv-tree-editor-portal"><div className="cv-studio-overlay"><section className="cv-tree-editor" ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={dialogLabel} onKeyDown={e=>{e.stopPropagation();if(e.key==='Escape'&&!busy)onClose();if(editing.mode!=='delete'&&e.key==='Enter'&&e.target.tagName==='INPUT'&&!e.nativeEvent.isComposing&&e.keyCode!==229){e.preventDefault();if(!busy&&title.trim())onSave()}if(e.key==='Tab'){const items=[...e.currentTarget.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled)')];if(!items.length){e.preventDefault();ref.current.focus()}else if(e.shiftKey&&[ref.current,items[0]].includes(document.activeElement)){e.preventDefault();items.at(-1)?.focus()}else if(!e.shiftKey&&document.activeElement===items.at(-1)){e.preventDefault();items[0]?.focus()}}}}><h3>{heading}</h3>{media?<label>素材名称<input autoFocus disabled={busy} aria-label="素材名称" value={title} maxLength={240} onChange={e=>setTitle(e.target.value)}/></label>:editing.mode==='delete'?<p>仅可删除空文件夹。非空文件夹请先移出素材与子文件夹，不会递归删除内容。</p>:<><label>文件夹名称<input autoFocus disabled={busy} aria-label="文件夹名称" value={title} maxLength={240} placeholder={editing.kind==='new'?'输入文件夹名称':undefined} onChange={e=>setTitle(e.target.value)}/></label><label>{editing.kind==='new'?'上级文件夹':'所在文件夹'}<Select ariaLabel={editing.kind==='new'?'上级文件夹':'所在文件夹'} disabled={busy} value={parent} onChange={setParent} options={[{value:'',label:'根目录'},...folders.map(f=>({value:String(f.id),label:folderPath(f.id)}))]}/></label></>}{error&&<p role="alert">{error}</p>}<footer><button disabled={busy} onClick={onClose}>取消</button><button className={editing.mode==='delete'?'btn btn-danger':'btn btn-primary'} disabled={busy||!title.trim()} onClick={onSave}>{confirm}</button></footer></section></div></div>,document.body)
}

const AssetRow=React.memo(function AssetRow({a,list,selected,multiSelected,depth,disabled,actions,index,style}){return <div data-window-card={index} data-depth={depth} style={style} className={`cv-tree-asset-row ${selected?'is-selected':''} ${multiSelected?'is-multi':''}`} data-media-id={a.id} draggable={!disabled} title="拖到画布新建素材节点，拖到文件夹整理，拖到生成节点作为参考" onDragStart={e=>actions.current.dragAssets(e,[a])} onDragEnd={e=>actions.current.dragAssetsEnd(e)} onContextMenu={e=>actions.current.openMenu(e,'asset',a)}><input type="checkbox" className="cv-tree-check" aria-label={`多选素材 ${a.name}`} checked={multiSelected} disabled={disabled} onClick={e=>e.stopPropagation()} onChange={()=>actions.current.toggleAssetCheck(a)}/><button className="cv-tree-asset" aria-label={`选择素材 ${a.name}`} onClick={e=>actions.current.selectAsset(a,e)} onDoubleClick={()=>actions.current.openPreview(a,list)}><span className="cv-node-list-thumb"><LibraryThumbnail compact asset={a} thumbnail={a.thumbnail_url}/></span><span>{a.name}</span></button><button className="cv-tree-more" aria-label={`管理素材 ${a.name}`} title="素材操作" onClick={e=>actions.current.openMenu(e,'asset',a)}><MoreHorizontal size={20}/></button></div>})

function WindowedAssets({items,selected,selectedMediaSet,depth=0,disabled,actions}){
 const window=useGridWindow(items.length,80)
 const indices=Array.from({length:Math.max(0,window.end-window.start)},(_,i)=>i+window.start)
 const add=index=>{if(index>=0&&index<items.length&&!indices.includes(index))indices.push(index)}
 add(items.findIndex(a=>a.id===selected))
 if(window.pinned)for(const index of [window.pinned.index-1,window.pinned.index,window.pinned.index+1])add(index)
 indices.sort((a,b)=>a-b)
 return <div ref={window.ref} style={{display:'grid',gridTemplateColumns:'minmax(0,1fr)',position:'relative',paddingTop:window.padTop,paddingBottom:window.padBottom}}>{indices.map(index=><AssetRow key={items[index].id} a={items[index]} list={items} selected={items[index].id===selected} multiSelected={selectedMediaSet.has(items[index].id)} depth={depth} disabled={disabled} actions={actions} index={index} style={index<window.start||index>=window.end?{position:'absolute',top:index*42,left:0,width:'100%'}:undefined}/>)}</div>
}
