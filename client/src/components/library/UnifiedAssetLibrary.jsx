import {localDate} from '../../lib/localDate'
import {uploadBatch,uploadSummary} from './uploadBatch'
import React,{useEffect,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import LibraryShell from './LibraryShell'
import LibraryGrid from './LibraryGrid'
import LibraryMore from './LibraryMore'
import {libraryPreviewAsset,canEditLibraryImage} from './libraryPreview'
import LibraryThumbnail from './LibraryThumbnail'
import LibraryOrganization from './LibraryOrganization'
import LibraryPopover from './LibraryPopover'
import MediaFolderTree,{folderIcon} from './MediaFolderTree'
import FolderSelect from './FolderSelect'
import MoveToFolderDialog from './MoveToFolderDialog'
import CharacterLibrary from './CharacterLibrary'
import MediaPreview from '../canvas/MediaPreview'
import {listMedia,listMediaFolders,selectMediaIds,lookupMedia,uploadMedia,moveMedia,mediaDownloadUrl,listMediaGroups,getMediaGroup,updateMediaGroup} from '../../lib/libraryApi'
import {downloadAsset} from '../../lib/canvasAssetVersions'
import {mediaItem,originLabel,placeFilters,placeTitle,folderChildren,uploadFolderOptions,uploadTargetFor,GENERATED,libraryErrorText} from './mediaLibrary'
import {Download,Trash2,Upload,LayoutGrid,ExternalLink,FolderInput,ChevronLeft,UserRound,X} from 'lucide-react'
const ImageAssetEditor=React.lazy(()=>import('../image-editor/ImageAssetEditor'))
const kinds={all:'全部',image:'图片',video:'视频',audio:'音频'}
const LIMIT=40
// LIBRARY-GLOBAL-20261116 S4a: one global library for every project. Folders only (no tags, no project
// scope, no separate “生成历史” source): the locked system folder “生成历史/图片|视频|音频” holds results.
// initialSource: 'generated' opens “生成历史”, 'characters' the character cards (browse only), else 全部素材.
// projectId is accepted for compatibility and no longer filters anything.
// initialFolderId ('root' | folder id) opens that folder; focusMediaIds highlights and scrolls to those items
// (“在素材库中显示” from the task center, S4b).
export default function UnifiedAssetLibrary({browseOnly=false,canAddToCanvas=false,allowedKinds=['image','video','audio'],selectionLimit=100,onApply,onClose,onRemote,initialSource='local',validateSelection,onBeforeDelete,onDeleted,title=null,applyLabel=null,initialFolderId=null,focusMediaIds=null}){
 const [view,setView]=useState(()=>initialSource==='characters'&&browseOnly?'characters':'media'),[place,setPlace]=useState(()=>initialFolderId||(initialSource==='generated'?'@generated':'all'))
 const [kind,setKind]=useState('all'),[query,setQuery]=useState(''),[page,setPage]=useState(1),[result,setResult]=useState({items:[],total:0}),[folders,setFolders]=useState([]),[foldersReady,setFoldersReady]=useState(false),[counts,setCounts]=useState({})
 const [groups,setGroups]=useState(null),[groupId,setGroupId]=useState(null),[groupDetail,setGroupDetail]=useState(null)
 const [selected,setSelected]=useState([]),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[queryError,setQueryError]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState(''),[revision,setRevision]=useState(0)
 const [action,setAction]=useState(null),[moving,setMoving]=useState(null),[editing,setEditing]=useState(null),[preview,setPreview]=useState(null),[uploadOptions,setUploadOptions]=useState(false),[uploadChoice,setUploadChoice]=useState(null),[picker,setPicker]=useState(null),[charactersBusy,setCharactersBusy]=useState(false),[expanded,setExpanded]=useState(()=>new Set()),[duplicates,setDuplicates]=useState(null)
 const focus=useRef(new Set(focusMediaIds||[])),allNotice=useRef(''),scrollRef=useRef(null),uploadTrigger=useRef(null),fileRef=useRef(null),alive=useRef(true),lock=useRef(false),restoreEdit=useRef(null)
 useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[])
 const message=e=>libraryErrorText(e)
 const generatedFolder=folders.find(f=>f.system_key===GENERATED)
 // Folders and the navigation totals (全部素材 / 根目录) follow every mutation.
 useEffect(()=>{let active=true;Promise.all([listMediaFolders(),listMedia({},{limit:1}),listMedia({folder_id:'root'},{limit:1})]).then(([list,all,root])=>{if(!active)return;setFolders(list);setCounts({all:all.total,root:root.total});setFoldersReady(true);const generated=list.find(f=>f.system_key===GENERATED);if(generated)setExpanded(v=>v.size?v:new Set([generated.id]));setPlace(current=>current==='@generated'?generated?.id||'all':current!=='all'&&current!=='root'&&!list.some(f=>f.id===current)?'all':current)}).catch(e=>{if(active){setError(message(e));setFoldersReady(true)}});return()=>{active=false}},[revision])
 const filters=()=>({...placeFilters(folders,place),kind,q:query})
 const listing=view==='media'&&foldersReady&&place!=='@generated'
 useEffect(()=>{if(!listing){if(view!=='media')setLoading(false);return}const controller=new AbortController();setLoading(true);setQueryError('');listMedia(filters(),{page,limit:LIMIT},controller.signal).then(data=>{if(!controller.signal.aborted)setResult(data)}).catch(e=>{if(!controller.signal.aborted)setQueryError(message(e))}).finally(()=>{if(!controller.signal.aborted)setLoading(false)});return()=>controller.abort()},[listing,place,kind,query,page,revision])
 useEffect(()=>{if(view!=='groups')return;let active=true;setLoading(true);setQueryError('');(groupId?getMediaGroup(groupId).then(d=>{if(active)setGroupDetail(d)}):listMediaGroups().then(g=>{if(active)setGroups(g)})).catch(e=>{if(active)setQueryError(message(e))}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[view,groupId,revision])
 // The upload target follows the current place unless the user picked another folder in 上传设置 for this place;
 // derived (not set by an effect) so an upload right after changing folders never uses the previous target (S7).
 const uploadTarget=uploadChoice?.place===place?uploadChoice.value:uploadTargetFor(folders,place),setUploadTarget=value=>setUploadChoice({place,value})
 const focusPending=useRef(!!focusMediaIds?.length)
 useEffect(()=>{if(loading||!focusPending.current||view!=='media'||place==='@generated')return;const take=focusPending.current==='focus';focusPending.current=false;const card=scrollRef.current?.querySelector('.ul-item.is-focus');if(card){card.scrollIntoView({block:'center'});if(take)card.querySelector('.ul-card')?.focus({preventScroll:true})}else setNotice('要显示的素材不在当前页（可能已被删除或移动），可翻页或搜索名称查找')},[loading,result])
 // LIBRARY-GLOBAL S7: after 保存为新素材 the list reloads and the item's “更多操作” trigger is re-created; once the reload
 // has finished, return focus to the edited item's trigger (Escape keeps the editor's own focus return).
 useEffect(()=>{const pending=restoreEdit.current;if(!pending||editing)return;if(loading){pending.reload=false;return}if(pending.reload)return;restoreEdit.current=null;const active=document.activeElement;if(active&&active!==document.body&&active.isConnected&&!active.classList.contains('ul-library'))return;scrollRef.current?.querySelector(`[data-library-edit="${CSS.escape(pending.key)}"]`)?.focus({preventScroll:true})},[editing,loading,result,groupDetail])
 function refresh(){setRevision(v=>v+1)}
 function close(){if(!lock.current)onClose()}
 async function run(operation){if(lock.current)return;lock.current=true;setBusy(true);setError('');try{await operation()}catch(e){if(alive.current)setError(message(e))}finally{lock.current=false;if(alive.current)setBusy(false)}}
 function goPlace(value){setNotice('');setDuplicates(null);setView('media');setGroupId(null);setPlace(value);setPage(1)}
 function goGroups(id=null){setNotice('');setView('groups');setGroupId(id);setGroupDetail(null)}
 // S10 D2: the “已全选当前筛选 N 项” notice describes one filter; it goes when the selection is cleared or the filter changes.
 function dropAllNotice(){if(allNotice.current){const text=allNotice.current;allNotice.current='';setNotice(n=>n===text?'':n)}}
 function clearSelection(){setSelected([]);dropAllNotice()}
 function filter(setter,value){setter(value);setPage(1);dropAllNotice()}
 const allowed=item=>allowedKinds.includes(item.asset.kind)
 function check(merged){if(!browseOnly&&merged.length>selectionLimit)throw new Error(`最多选择 ${selectionLimit} 个素材`);if(!browseOnly&&merged.some(i=>!allowed(i)))throw new Error('当前节点不支持所选媒体类型');const issue=browseOnly?null:validateSelection?.(merged);if(issue)throw new Error(issue)}
 function selectItems(items,replace=false){const merged=[...new Map([...(replace?[]:selected),...items].map(i=>[i.key,i])).values()];check(merged);setSelected(merged)}
 function toggle(item){setError('');if(selected.some(i=>i.key===item.key))setSelected(v=>v.filter(i=>i.key!==item.key));else try{selectItems([item])}catch(e){setError(message(e))}}
 // Server-side selection of the whole current filter, including pages not loaded yet.
 function selectAll(){run(async()=>{const {ids}=await selectMediaIds(filters()),found=(await lookupMedia(ids)).filter(i=>i.status==='ok').map(i=>mediaItem(i.media));if(!alive.current)return;const usable=browseOnly?found:found.filter(allowed);selectItems(usable,true);const text=`已全选当前筛选的 ${usable.length} 项${usable.length<found.length?`（跳过 ${found.length-usable.length} 项当前节点不支持的类型）`:''}`;allNotice.current=text;setNotice(text)})}
 function deleted(outcome){const gone=new Set([...(outcome.deleted_ids||[]),...(outcome.missing||[])]);setSelected(current=>current.filter(i=>!gone.has(i.key)));onDeleted?.(outcome);refresh()}
 async function upload(files){await run(async()=>{const folderId=uploadTarget||null,uploaded=[],found=[];let duplicates=0;const outcome=await uploadBatch(files,async file=>{const r=await uploadMedia(file,{folderId});if(r.deduplicated)duplicates++;uploaded.push(r.media);if(r.deduplicated)found.push(r.media)});if(!alive.current)return
  // User decision 2026-11-17: an upload whose content is already in the library elsewhere names that folder and
  // offers 「定位」 / 「移到当前文件夹」; it is never moved automatically.
  const elsewhere=[...new Map(found.filter(m=>(m.folder_id||null)!==folderId).map(m=>[m.id,m])).values()]
  const summary=`${uploadSummary(outcome)}${duplicates?`；${duplicates} 项内容已在库中，未重复保存`:''}`
  if(browseOnly){setUploadOptions(false);if(uploaded.length){setQuery('');setKind('all');goPlace(folderId||'root')}setNotice(summary);setDuplicates(elsewhere.length?{items:elsewhere,target:folderId}:null);refresh();if(outcome.error)throw outcome.error;return}
  // Reference picker: keep the current view and select only the uploads that fit this node.
  const accepted=[],rejected=[];for(const item of uploaded.map(mediaItem)){try{check([...new Map([...selected,...accepted,item].map(i=>[i.key,i])).values()]);accepted.push(item)}catch(e){rejected.push(`${item.asset.name}：${message(e)}`)}}
  if(accepted.length)setSelected(current=>[...new Map([...current,...accepted].map(i=>[i.key,i])).values()])
  setUploadOptions(false);setDuplicates(elsewhere.length?{items:elsewhere,target:folderId}:null);setNotice(`${summary}${accepted.length?`；已自动选中 ${accepted.length} 项`:''}`);refresh()
  if(rejected.length&&!outcome.error)throw new Error(`已上传但未选中：${rejected.join('；')}`)
  if(outcome.error)throw outcome.error})}
 async function saveEdited(file){const key=editing.id,r=await uploadMedia(file,{folderId:uploadTargetFor(folders,editing.folder_id)||null,origin:'save_as'});if(alive.current){restoreEdit.current={key,reload:true};setNotice(r.deduplicated?'编辑后的图片与库中已有素材相同，未重复保存。':'已另存编辑后的图片，原图与画布保持不变。');refresh()}}
 function locateDuplicates(){const {items}=duplicates,folder=items[0].folder_id||'root',ids=items.filter(m=>(m.folder_id||'root')===folder).map(m=>m.id);focus.current=new Set(ids);focusPending.current='focus';setQuery('');setKind('all');goPlace(folder);refresh()}
 function moveDuplicates(){const {items,target}=duplicates;run(async()=>{const moved=await moveMedia(items.map(m=>m.id),target);if(!alive.current)return;setDuplicates(null);focus.current=new Set(moved.map(m=>m.id));setSelected(current=>current.map(i=>{const m=moved.find(x=>x.id===i.key);return m?mediaItem(m):i}));setNotice(`已把 ${moved.length} 项移到「${placeTitle(folders,target||'root')}」`);refresh()})}
 async function removeFromGroup(ids){await run(async()=>{await updateMediaGroup(groupId,{remove:ids});if(alive.current){setNotice(`已从素材组移除 ${ids.length} 项`);refresh()}})}
 const folderTitle=id=>id?folders.find(f=>f.id===id)?.title||'文件夹':'根目录'
 const characterView=view==='characters'&&browseOnly
 const selectedKeys=new Set(selected.map(i=>i.key)),context=action||moving||editing||preview||picker
 const currentFolder=folders.find(f=>f.id===place),childFolders=view==='media'&&!query&&kind==='all'&&(place==='root'||currentFolder&&!currentFolder.system_key)?(folderChildren(folders).get(place==='root'?'':place)||[]).filter(f=>!f.system_key):[]
 const showFolderColumn=place==='all'||currentFolder?.system_key===GENERATED
 const groupItems=groupDetail?.items||[],okGroupItems=groupItems.filter(i=>i.status==='ok').map(i=>mediaItem(i.media)),deadGroupItems=groupItems.filter(i=>i.status!=='ok')
 const heading=view==='groups'?(groupId?groupDetail?.group?.title||'素材组':'素材组'):placeTitle(folders,place==='@generated'?'all':place)
 const openAction=value=>{setUploadOptions(false);setAction(value)}
 const itemTools=item=><><button disabled={busy} onClick={()=>setPreview(libraryPreviewAsset(item))}>预览</button>{item.asset.kind==='image'&&<button disabled={busy||!canEditLibraryImage(item.asset)} title={canEditLibraryImage(item.asset)?'编辑图片（另存为新素材）':'此格式暂不支持浏览器编辑，请下载原图后转换格式'} aria-label={`编辑图片 ${item.asset.name}`} onClick={()=>setEditing(item.asset)}>编辑</button>}<button aria-label={`重命名 ${item.asset.name}`} disabled={busy} onClick={()=>openAction({kind:'renameMedia',item:item.asset})}>重命名</button><button aria-label={`移动到文件夹 ${item.asset.name}`} disabled={busy} onClick={()=>setMoving([item.asset])}>移动到文件夹</button><button aria-label={`下载 ${item.asset.name}`} disabled={busy} onClick={()=>run(()=>downloadAsset({...item.asset,url:mediaDownloadUrl(item.media_id)}))}>下载</button>{view==='groups'&&groupId&&<button aria-label={`从素材组移除 ${item.asset.name}`} disabled={busy} onClick={()=>removeFromGroup([item.media_id])}>从素材组移除</button>}<button className="is-danger" aria-label={`删除素材 ${item.asset.name}`} disabled={busy} onClick={()=>openAction({kind:'remove',items:[item]})}>删除</button></>
 const metadata=item=>{const info=[originLabel(item.asset.origin),showFolderColumn||view==='groups'?folderTitle(item.asset.folder_id):null,localDate(item.created_at||item.asset.created_at)].filter(Boolean).join(' · ');return <small className="ul-info" title={info}>{info}</small>}
 return <><LibraryShell title={title||(browseOnly?'素材库':'选择参考素材')} busy={busy||charactersBusy} hidden={!!context} onClose={close} navigation={<>
  <MediaFolderTree folders={folders} place={place} active={view==='media'} onPlace={goPlace} expanded={expanded} onToggle={id=>setExpanded(v=>{const next=new Set(v);next.has(id)?next.delete(id):next.add(id);return next})} onAction={openAction} counts={counts} busy={busy||charactersBusy}/>
  <div className="ul-nav-extra"><button aria-current={view==='groups'?'true':undefined} className={view==='groups'?'is-current':''} disabled={busy||charactersBusy} onClick={()=>goGroups()}><LayoutGrid size={15} strokeWidth={1.7} aria-hidden="true"/>素材组</button>
  {browseOnly&&<button aria-current={view==='characters'?'true':undefined} className={view==='characters'?'is-current':''} disabled={busy||charactersBusy} onClick={()=>{setView('characters');setSelected([])}}><UserRound size={15} strokeWidth={1.7} aria-hidden="true"/>角色卡</button>}
  {onRemote&&<button className="ul-remote-link" disabled={busy} onClick={onRemote}>Cupsy 远端素材<ExternalLink size={14} aria-hidden="true"/></button>}</div></>}
 footer={characterView?<><span className="ul-muted">角色卡全局共用，不属于任何项目；在画布提示词中输入 @角色卡名 引用。</span><span style={{flex:1}}/><button disabled={charactersBusy} onClick={close}>完成</button></>:<><div className="ul-selected" aria-label="已选素材">{selected.slice(0,60).map(item=><button key={item.key} title={`取消选择 ${item.asset.name}`} aria-label={`取消选择 ${item.asset.name}`} disabled={busy} onClick={()=>toggle(item)}><LibraryThumbnail asset={item.asset} thumbnail={item.thumbnail_url}/></button>)}{selected.length>60&&<small>+{selected.length-60}</small>}</div><span>已选 {selected.length}</span>
  {selected.length>0&&<button disabled={busy} onClick={clearSelection}>清空选择</button>}
  <button className="btn btn-icon btn-outlined" aria-label="移动到文件夹" title="把已选素材移动到文件夹（不复制文件）" disabled={busy||!selected.length} onClick={()=>setMoving(selected.map(i=>i.asset))}><FolderInput size={16}/></button>
  <button className="btn btn-icon btn-outlined" aria-label="加入素材组" title="把已选素材加入新的或已有的全局素材组" disabled={busy||!selected.length} onClick={()=>openAction({kind:'group'})}><LayoutGrid size={16}/></button>
  <button className="btn btn-icon btn-outlined btn-danger" aria-label="删除" title="永久删除已选素材（删除前预览受影响画布）" disabled={busy||!selected.length} onClick={()=>openAction({kind:'remove'})}><Trash2 size={16}/></button>
  <button className="btn btn-icon btn-outlined" aria-label="下载" title="下载已选素材" disabled={busy||!selected.length} onClick={()=>run(async()=>{for(const item of selected)await downloadAsset({...item.asset,url:mediaDownloadUrl(item.media_id)})})}><Download size={16}/></button>
  <button disabled={busy} onClick={close}>{browseOnly?'完成':'取消'}</button>
  {(!browseOnly||canAddToCanvas)&&<button className="btn btn-primary" disabled={busy||!selected.length} onClick={()=>run(async()=>{check(selected);await onApply(selected)})}>{busy?'处理中…':applyLabel||(browseOnly?'添加到当前画布':'添加为节点参考')}</button>}</>}
 >
 {characterView?<><div className="ul-title"><h3>角色卡</h3></div><CharacterLibrary onBusy={setCharactersBusy} openPicker={setPicker}/></>:<>
 <div className="ul-title">{view==='groups'&&groupId&&<button aria-label="返回素材组列表" title="返回素材组列表" disabled={busy} onClick={()=>goGroups()}><ChevronLeft size={15} aria-hidden="true"/></button>}<h3>{heading}</h3>{currentFolder?.system_key&&view==='media'&&<span className="ul-system-hint">系统文件夹 · 不可重命名或删除</span>}
  {view==='media'&&<span className="ul-kinds" role="group" aria-label="媒体类型">{Object.entries(kinds).map(([key,label])=><button key={key} disabled={busy} aria-pressed={kind===key} onClick={()=>filter(setKind,key)}>{label}</button>)}</span>}</div>
 {view==='media'&&<div className="ul-tools"><input aria-label="搜索素材" placeholder="搜索素材名称" value={query} disabled={busy} maxLength={200} onChange={e=>filter(setQuery,e.target.value)}/>
  <button disabled={busy||loading||!result.total} title="按服务端筛选结果选择全部（含未加载的分页）" onClick={selectAll}>全选当前筛选</button>
  <span className="ul-popover-anchor"><button ref={uploadTrigger} disabled={busy} aria-haspopup="true" aria-expanded={uploadOptions} onClick={()=>setUploadOptions(!uploadOptions)}><Upload size={15}/>上传素材</button>{uploadOptions&&<LibraryPopover label="上传设置" trigger={uploadTrigger} onClose={()=>setUploadOptions(false)}><FolderSelect label="上传到" folders={folders} options={uploadFolderOptions(folders)} value={uploadTarget} onChange={setUploadTarget} onCreated={()=>refresh()} disabled={busy}/><button disabled={busy} onClick={()=>fileRef.current.click()}>选择本地文件</button><small>上传的素材属于全局素材库，所有项目可见。{!browseOnly&&'上传成功的素材会自动选中。'}</small></LibraryPopover>}</span></div>}
 {view==='groups'&&groupId&&groupDetail&&<div className="ul-tools"><button disabled={busy||!okGroupItems.length} onClick={()=>{try{const usable=browseOnly?okGroupItems:okGroupItems.filter(allowed);selectItems(usable);setNotice(`已选择组内 ${usable.length} 项`)}catch(e){setError(message(e))}}}>选择组内全部可用素材</button>{deadGroupItems.length>0&&<button disabled={busy} onClick={()=>removeFromGroup(deadGroupItems.map(i=>i.media_id))}>移除 {deadGroupItems.length} 个“已删除”占位</button>}<span style={{flex:1}}/><button disabled={busy} onClick={()=>openAction({kind:'groupEdit',item:groupDetail.group})}>重命名</button><button className="is-danger" disabled={busy} onClick={()=>openAction({kind:'deleteGroup',item:groupDetail.group})}>删除素材组</button></div>}
 {error&&<p className="ul-error" role="alert">{error}</p>}{notice&&<p className="ul-notice" role="status">{notice}</p>}
 {duplicates&&<div className="ul-duplicate" role="status" aria-label="内容重复的上传"><p>{duplicates.items.length===1?'上传的内容已在库中：':`${duplicates.items.length} 项上传的内容已在库中：`}{duplicates.items.slice(0,3).map((m,i)=><React.Fragment key={m.id}>{i?'；':''}「{m.name}」已在「{placeTitle(folders,m.folder_id||'root')}」中</React.Fragment>)}{duplicates.items.length>3&&` 等 ${duplicates.items.length} 项`}。未重复保存，也未自动移动。</p><button disabled={busy} title={`打开「${placeTitle(folders,duplicates.items[0].folder_id||'root')}」并高亮该素材`} onClick={locateDuplicates}>定位</button><button disabled={busy} title={`移到「${placeTitle(folders,duplicates.target||'root')}」（只改变所在文件夹，不复制文件）`} onClick={moveDuplicates}>移到当前文件夹</button><button className="btn btn-icon" aria-label="关闭重复提示" title="关闭重复提示" disabled={busy} onClick={()=>setDuplicates(null)}><X size={14}/></button></div>}
 <div className="ul-scroll" ref={scrollRef} aria-busy={loading}>{loading?<p role="status">正在载入素材…</p>:queryError?<div role="alert" className="ul-error">{queryError}<button onClick={refresh}>重试加载</button></div>
 :view==='groups'?(groupId?groupDetail&&<>
  <LibraryGrid items={okGroupItems} selectedKeys={selectedKeys} onToggle={toggle} busy={busy} isDisabled={item=>!browseOnly&&!allowed(item)} primaryActions={0} onPreview={item=>setPreview(libraryPreviewAsset(item))} metadata={metadata} tools={itemTools}>
   {deadGroupItems.map(i=><article className="ul-item ul-deleted" key={i.media_id} data-media-id={i.media_id}><div className="ul-card ul-deleted-card" aria-label={`已删除的素材 ${i.media?.name||''}`.trim()}><span className="ul-deleted-mark" aria-hidden="true"><Trash2 size={22} strokeWidth={1.5}/></span><strong title={i.media?.name}>{i.media?.name||'已删除的素材'}</strong></div><div className="ul-item-meta"><small className="ul-info">{i.status==='deleted'?'已删除':'不存在'}</small><div className="ul-item-tools"><button aria-label={`从素材组移除已删除的 ${i.media?.name||'素材'}`} disabled={busy} onClick={()=>removeFromGroup([i.media_id])}>移除</button></div></div></article>)}
  </LibraryGrid>
  {!groupItems.length&&<p className="ul-muted">此素材组没有成员。</p>}</>
  :<><div className="ul-grid">{(groups||[]).map(g=><article className="ul-item ul-folder" key={g.id}><button className="ul-card" aria-label={`打开素材组 ${g.title}`} disabled={busy} onClick={()=>goGroups(g.id)}><span className="ul-folder-icon" aria-hidden="true"><LayoutGrid size={20} strokeWidth={1.6}/></span><strong title={g.title}>{g.title}</strong></button><small>{g.member_count} 项{g.deleted_count?` · ${g.deleted_count} 已删除`:''}</small><div className="ul-item-tools"><LibraryMore name={`素材组 ${g.title}`}><button onClick={()=>openAction({kind:'groupEdit',item:g})}>重命名</button><button className="is-danger" onClick={()=>openAction({kind:'deleteGroup',item:g})}>删除素材组</button></LibraryMore></div></article>)}</div>
  {groups&&!groups.length&&<p className="ul-muted ul-empty-center" role="status">还没有素材组。在素材中选中素材后点底部“加入素材组”。素材组为全局，所有项目可用。</p>}</>)
 :<>
 <LibraryGrid items={result.items.map(mediaItem)} itemClass={item=>focus.current.has(item.media_id)?'is-focus':''} selectedKeys={selectedKeys} onToggle={toggle} busy={busy} isDisabled={item=>!browseOnly&&!allowed(item)} primaryActions={0} onPreview={item=>setPreview(libraryPreviewAsset(item))} metadata={metadata} tools={itemTools}>
  {childFolders.map(f=><article className="ul-item ul-folder" key={f.id}><button className="ul-card" onClick={()=>goPlace(f.id)} aria-label={`打开文件夹 ${f.title}`}><span className="ul-folder-icon" aria-hidden="true">{React.createElement(folderIcon(f),{size:20,strokeWidth:1.6})}</span><strong title={f.title}>{f.title}</strong></button><small>{f.media_count}</small></article>)}
 </LibraryGrid>
 {!result.items.length&&!childFolders.length&&<p className="ul-muted">{currentFolder?.system_key?'这里还没有生成结果。':'没有符合当前筛选的素材'}{(query||kind!=='all')&&<button onClick={()=>{setQuery('');setKind('all');setPage(1);dropAllNotice()}}>清除筛选</button>}</p>}
 <div className="ul-pager"><button disabled={page<=1||busy} onClick={()=>setPage(page-1)}>上一页</button><span>{result.total} 项 · 第 {page} / {Math.max(1,Math.ceil(result.total/LIMIT))} 页</span><button disabled={page*LIMIT>=result.total||busy} onClick={()=>setPage(page+1)}>下一页</button></div></>}
 </div></>}<input ref={fileRef} type="file" multiple accept="image/*,video/*,audio/*" hidden onChange={e=>{const files=[...e.target.files];e.target.value='';upload(files)}}/>
 </LibraryShell>
 {action&&<LibraryOrganization key={`${action.kind}:${action.item?.id||''}`} action={action} folders={folders} selection={action.items||selected} onClose={()=>setAction(null)} onDone={result=>{const done=action;setAction(null);if(done.kind==='renameMedia'&&result){setSelected(current=>current.map(i=>i.key===result.id?mediaItem(result):i));setNotice(`已重命名为“${result.name}”`)}if(['remove','group'].includes(done.kind)&&!done.items)setSelected([]);if(done.kind==='group')setNotice('已加入素材组')
  // LIBRARY-OPS-FIX E5: every library change confirms itself in the status line.
  if(done.kind==='remove'&&result){const count=result.deleted_ids?.length||0,missing=result.missing?.length||0;setNotice(`已永久删除 ${count} 个素材${missing?`（${missing} 项已不存在，已跳过）`:''}`)}
  if(done.kind==='groupEdit'&&result)setNotice(`已重命名素材组为“${result.title||result.group?.title||''}”`)
  if(done.kind==='deleteGroup')setNotice(`已删除素材组“${done.item.title}”，组内素材保留`)
  if(done.kind==='newFolder'&&result)setNotice(`已新建文件夹“${result.title}”`)
  if(done.kind==='folder'&&result)setNotice(`已保存文件夹“${result.title}”`)
  if(done.kind==='deleteFolder')setNotice(`已删除文件夹“${done.item.title}”`);if(done.kind==='deleteGroup'&&groupId===done.item.id)goGroups();if(done.kind==='deleteFolder'&&place===done.item.id)goPlace('all');refresh()}} onBeforeDelete={onBeforeDelete} onDeleted={deleted}/>}
 {moving&&<MoveToFolderDialog media={moving} onClose={()=>setMoving(null)} onDone={outcome=>{setMoving(null);setNotice(outcome.text);setSelected(current=>current.map(i=>{const m=outcome.moved.find(x=>x.id===i.key);return m?mediaItem(m):i}));refresh()}}/>}
 {picker&&<UnifiedAssetLibrary key="character-picker" title={picker.title} applyLabel={picker.applyLabel} allowedKinds={picker.kinds} selectionLimit={picker.limit} onApply={async items=>{await picker.onApply(items);if(alive.current)setPicker(null)}} onClose={()=>setPicker(null)}/>}
 {preview&&createPortal(<div className="ul-preview-host"><MediaPreview asset={preview} onClose={()=>setPreview(null)}/></div>,document.body)}
 {editing&&createPortal(<React.Suspense fallback={<div className="ul-subdialog" role="status">正在加载编辑器…</div>}><ImageAssetEditor asset={editing} onSave={saveEdited} onClose={()=>setEditing(null)}/></React.Suspense>,document.body)}
 </>
}
