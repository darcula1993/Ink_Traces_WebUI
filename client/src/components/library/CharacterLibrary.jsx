import React,{useEffect,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import {Plus,Upload,Trash2,AudioLines,ChevronLeft,ChevronRight,Images,Save,Search,X} from 'lucide-react'
import {CharacterEmptyArt,CharacterCoverPlaceholder} from '../art/CanvasLibraryArt'
import LibraryDialog from './LibraryDialog'
import {CharacterKindSelect,CharacterNameInput,CharacterDescriptionInput} from './CharacterFields'
import MediaPreview from '../canvas/MediaPreview'
import {withPreviewPages} from '../canvas/previewPages'
import askConfirm from '../ui/askConfirm'
import {listCharacters,getCharacter,createCharacter,updateCharacter,deleteCharacter,uploadCharacterImage,addLibraryImage,deleteCharacterImage,reorderCharacterImages,uploadVoiceAudio,addLibraryVoiceAudio,clearVoice,audioDuration,characterDescription} from '../../lib/characterApi'
import {CHARACTER_IMAGE_LIMIT,CHARACTER_DESCRIPTION_MAX,CHARACTER_VOICE_MAX_SECONDS,characterKindLabel,characterNameError,characterErrorMessage,descriptionLength,normalizeCharacterKind,voiceIsAudio} from '../../lib/characterRules'
import './characterLibrary.css'

// LIBRARY-GLOBAL-20261116 S6c: a picked library item is referenced by its media id (selection
// {source:'media',id}); nothing is re-uploaded. Other selections (e.g. Cupsy) go as their catalog ref.
const attachPicked=(item,reference)=>reference(item.selection?.source==='media'?{source:'media',id:item.selection.id}:item.selection)
const sortImages=c=>[...(c?.images||[])].sort((a,b)=>(a.position??0)-(b.position??0))
const AUDIO_TYPES=/^audio\/(wav|x-wav|wave|vnd\.wave|mpeg|mp3)$/
const audioAllowed=file=>AUDIO_TYPES.test(file.type)||/\.(wav|mp3)$/i.test(file.name)
const KIND_FILTERS=[{value:'all',label:'全部'},{value:'character',label:'人物'},{value:'prop',label:'物件'}]

// Global character library: name, text description, up to 8 reference images and one reference audio.
// openPicker({title,kinds,limit,onApply}) opens the asset library as a nested picker (provided by UnifiedAssetLibrary).
export default function CharacterLibrary({openPicker,onBusy}){
 const [characters,setCharacters]=useState([]),[loading,setLoading]=useState(true),[loadError,setLoadError]=useState(''),[activeId,setActiveId]=useState(null),[detail,setDetail]=useState(null)
 const [busy,setBusyState]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[revision,setRevision]=useState(0)
 const [creating,setCreating]=useState(false),[confirmDelete,setConfirmDelete]=useState(false),[nameDraft,setNameDraft]=useState(''),[descriptionDraft,setDescriptionDraft]=useState('')
 const [query,setQuery]=useState(''),[kindFilter,setKindFilter]=useState('all'),[preview,setPreview]=useState(null)
 const [dragging,setDragging]=useState(null),[dropIndex,setDropIndex]=useState(null)
 const rootRef=useRef(null),imageInput=useRef(null),audioInput=useRef(null),lock=useRef(false),alive=useRef(true)
 const bypassGuardRef=useRef(false),confirmingRef=useRef(false)
 useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[])
 const setBusy=v=>{setBusyState(v);onBusy?.(v)}
 useEffect(()=>{const controller=new AbortController();setLoading(true);setLoadError('');listCharacters(controller.signal).then(list=>{if(controller.signal.aborted)return;setCharacters(list);setActiveId(id=>list.some(c=>c.id===id)?id:list[0]?.id||null)}).catch(e=>{if(!controller.signal.aborted)setLoadError(characterErrorMessage(e,'角色卡列表加载失败'))}).finally(()=>{if(!controller.signal.aborted)setLoading(false)});return()=>controller.abort()},[revision])
 const listed=characters.find(c=>c.id===activeId)
 useEffect(()=>{let active=true;setDetail(listed||null);if(activeId)getCharacter(activeId).then(c=>{if(active&&c?.id===activeId)setDetail(c)}).catch(()=>{});return()=>{active=false}},[activeId,revision])
 useEffect(()=>{setNameDraft(detail?.name||'');setDescriptionDraft(characterDescription(detail))},[detail?.id,detail?.updated_at])
 const character=detail,images=sortImages(character),others=characters.filter(c=>c.id!==character?.id)
 const nameError=character&&nameDraft!==character.name?characterNameError(nameDraft,others):''
 const nameDirty=Boolean(character&&nameDraft.trim()!==character.name)
 const descriptionDirty=Boolean(character&&descriptionDraft!==characterDescription(character))
 const descriptionOver=descriptionLength(descriptionDraft)>CHARACTER_DESCRIPTION_MAX
 const hasUnsavedChanges=nameDirty||descriptionDirty
 const canSave=hasUnsavedChanges&&!nameError&&!descriptionOver&&!busy

 const trimmedQuery=query.trim().toLocaleLowerCase()
 const visibleCharacters=characters.filter(c=>{
  if(kindFilter!=='all'&&normalizeCharacterKind(c.kind)!==kindFilter)return false
  if(!trimmedQuery)return true
  const hay=`${c.name||''} ${characterDescription(c)}`.toLocaleLowerCase()
  return hay.includes(trimmedQuery)
 })

 async function confirmDiscard(message){
  if(confirmingRef.current)return false
  confirmingRef.current=true
  try{
   return await askConfirm({
    title:'放弃未保存的修改？',
    message,
    confirmLabel:'放弃并继续',
    cancelLabel:'继续编辑',
    danger:true,
   })
  }finally{
   confirmingRef.current=false
  }
 }

 // Guard closing or leaving the enclosing UnifiedAssetLibrary dialog while edits are unsaved.
 useEffect(()=>{
  if(!hasUnsavedChanges||busy||creating||confirmDelete||preview)return
  const libraryEl=rootRef.current?.closest('.ul-library')
  if(!libraryEl)return
  const resetDrafts=()=>{
   if(!character)return
   setNameDraft(character.name||'')
   setDescriptionDraft(characterDescription(character))
  }
  const onClickCapture=event=>{
   if(bypassGuardRef.current||confirmingRef.current||libraryEl.hasAttribute('inert'))return
   if(document.querySelector('.ink-confirm-dialog'))return
   const button=event.target instanceof Element?event.target.closest('button'):null
   if(!button||!libraryEl.contains(button))return
   const isCloseBtn=button.classList.contains('ul-close')||Boolean(button.closest('.ul-footer'))
   const isNavLeave=Boolean(button.closest('.ul-nav'))&&button.getAttribute('aria-current')!=='true'
   if(!isCloseBtn&&!isNavLeave)return
   event.preventDefault()
   event.stopPropagation()
   event.stopImmediatePropagation()
   confirmDiscard(isNavLeave?'当前角色卡的名称或文字描述尚未保存，切换页面将丢失这些修改。':'当前角色卡的名称或文字描述尚未保存，关闭弹窗将丢失这些修改。').then(ok=>{
    if(!ok||!alive.current)return
    resetDrafts()
    bypassGuardRef.current=true
    try{button.click()}finally{setTimeout(()=>{bypassGuardRef.current=false},0)}
   })
  }
  const onKeyDownCapture=event=>{
   if(event.key!=='Escape'||bypassGuardRef.current||confirmingRef.current||libraryEl.hasAttribute('inert'))return
   if(document.querySelector('.ink-confirm-dialog'))return
   if(!libraryEl.contains(event.target)&&event.target!==document.body)return
   event.preventDefault()
   event.stopPropagation()
   event.stopImmediatePropagation()
   confirmDiscard('当前角色卡的名称或文字描述尚未保存，关闭弹窗将丢失这些修改。').then(ok=>{
    if(!ok||!alive.current)return
    resetDrafts()
    const closeBtn=libraryEl.querySelector('.ul-close')
    bypassGuardRef.current=true
    try{closeBtn?.click()}finally{setTimeout(()=>{bypassGuardRef.current=false},0)}
   })
  }
  document.addEventListener('click',onClickCapture,true)
  document.addEventListener('keydown',onKeyDownCapture,true)
  return()=>{
   document.removeEventListener('click',onClickCapture,true)
   document.removeEventListener('keydown',onKeyDownCapture,true)
  }
 },[hasUnsavedChanges,busy,creating,confirmDelete,preview,character])

 async function selectCharacter(id){
  if(id===activeId||busy)return
  if(hasUnsavedChanges){
   const ok=await confirmDiscard('当前角色卡的名称或文字描述尚未保存，切换角色卡将丢失这些修改。')
   if(!ok||!alive.current)return
  }
  setError('');setNotice('');setActiveId(id)
 }

 async function openCreate(){
  if(busy)return
  if(hasUnsavedChanges){
   const ok=await confirmDiscard('当前角色卡的名称或文字描述尚未保存，新建角色卡将丢失这些修改。')
   if(!ok||!alive.current)return
  }
  setError('');setCreating(true)
 }

 async function run(operation,success=''){if(lock.current){setError('请等待当前操作完成后再试');return false}lock.current=true;setBusy(true);setError('');setNotice('');try{await operation();if(alive.current&&success)setNotice(success);return true}catch(e){if(alive.current)setError(characterErrorMessage(e));return false}finally{lock.current=false;if(alive.current)setBusy(false)}}
 // Every mutation re-reads the character from the server; the server is the source of truth.
 async function reload(id=character?.id){const fresh=await getCharacter(id);if(!alive.current)return;setDetail(fresh);setCharacters(list=>list.map(c=>c.id===id?{...c,...fresh}:c))}
 function saveChanges(){
  if(!character||!hasUnsavedChanges)return
  const patch={}
  if(nameDirty){
   const issue=characterNameError(nameDraft,others)
   if(issue){setError(issue);return}
   patch.name=nameDraft.trim()
  }
  if(descriptionDirty){
   if(descriptionLength(descriptionDraft)>CHARACTER_DESCRIPTION_MAX){setError(`文字描述最多 ${CHARACTER_DESCRIPTION_MAX} 字`);return}
   patch.description=descriptionDraft
  }
  const msg=nameDirty&&descriptionDirty?'已保存角色卡修改':nameDirty?'已保存角色卡名称':'已保存文字描述'
  run(async()=>{await updateCharacter(character.id,patch);await reload()},msg)
 }
 function saveKind(nextKind){const value=normalizeCharacterKind(nextKind);if(value===normalizeCharacterKind(character?.kind))return;run(async()=>{await updateCharacter(character.id,{kind:value});await reload()},`已切换为${characterKindLabel(value)}模板`)}
 function remaining(){return CHARACTER_IMAGE_LIMIT-images.length}
 async function uploadImages(files){const images=files.filter(f=>f.type.startsWith('image/'));if(images.length<files.length){setError('只能上传图片文件');if(!images.length)return}
  if(images.length>remaining()){setError(`每个角色卡最多 ${CHARACTER_IMAGE_LIMIT} 张图，还可添加 ${remaining()} 张`);return}
  let done=0;await run(async()=>{try{for(const file of images){await uploadCharacterImage(character.id,file);done++}}finally{await reload()}},`已上传 ${images.length} 张角色卡图`)
  if(done<images.length&&alive.current)setNotice(`已上传 ${done} 张，未处理 ${images.length-done} 张；请核对后再决定是否重新上传`)}
 function pickImages(){const left=remaining();if(left<=0){setError(`每个角色卡最多 ${CHARACTER_IMAGE_LIMIT} 张图`);return}
  openPicker({title:`为“${character.name}”选择角色卡图`,applyLabel:'加入角色卡图',kinds:['image'],limit:left,onApply:async items=>{const id=character.id;let done=0;try{for(const item of items){await attachPicked(item,selection=>addLibraryImage(id,selection));done++}}finally{if(alive.current)await reload(id).catch(()=>{})}if(alive.current)setNotice(`已从素材库加入 ${done} 张角色卡图`)}})}
 function removeImage(image){run(async()=>{await deleteCharacterImage(character.id,image.asset_id);await reload()},'已删除角色卡图')}
 function move(from,to){if(to<0||to>=images.length||from===to)return;const order=images.map(i=>i.asset_id),[item]=order.splice(from,1);order.splice(to,0,item);const optimistic=order.map((asset_id,position)=>({...images.find(i=>i.asset_id===asset_id),position}));setDetail(d=>({...d,images:optimistic}));run(async()=>{await reorderCharacterImages(character.id,order);await reload()}).then(ok=>{if(!ok&&alive.current)reload().catch(()=>{})})}
 function openImagePreview(image){
  const pages=images.map((item,idx)=>({id:item.asset_id,url:item.url,name:item.name||`${character?.name||'角色卡'} 图 ${idx+1}`,kind:'image'}))
  const current=pages.find(p=>p.id===image.asset_id)||pages[0]
  if(current)setPreview(withPreviewPages(current,pages))
 }
 async function checkDuration(src){let seconds;try{seconds=await audioDuration(src)}catch(e){throw e}if(!Number.isFinite(seconds))throw new Error('无法确认音频时长，请换用 wav 或 mp3 文件');if(seconds>CHARACTER_VOICE_MAX_SECONDS+0.05)throw new Error(`参考音频最长 ${CHARACTER_VOICE_MAX_SECONDS} 秒（当前约 ${seconds.toFixed(1)} 秒）`);return seconds}
 function uploadAudio(file){if(!audioAllowed(file)){setError('参考音频仅支持 wav 或 mp3');return}run(async()=>{await checkDuration(file);await uploadVoiceAudio(character.id,file);await reload()},'已设置参考音频')}
 function pickAudio(){openPicker({title:`为“${character.name}”选择参考音频`,applyLabel:'设为参考音频',kinds:['audio'],limit:1,onApply:async([item])=>{const id=character.id,known=Number(item.asset.duration);if(Number.isFinite(known)&&known>0){if(known>CHARACTER_VOICE_MAX_SECONDS+0.05)throw new Error(`参考音频最长 ${CHARACTER_VOICE_MAX_SECONDS} 秒（所选约 ${known.toFixed(1)} 秒）`)}else await checkDuration(item.asset.url);await attachPicked(item,selection=>addLibraryVoiceAudio(id,selection));if(alive.current){await reload(id);setNotice('已设置参考音频')}}})}
 function removeVoice(){run(async()=>{await clearVoice(character.id);await reload()},'已移除参考音频')}

 const isFiltered=Boolean(trimmedQuery||kindFilter!=='all')

 return <div ref={rootRef} className="cl-root">
  <aside className="cl-list" aria-label="角色卡列表">
   <div className="cl-list-head"><span>{loading?'正在载入…':isFiltered?`${visibleCharacters.length}/${characters.length} 个角色卡`:`${characters.length} 个角色卡`}</span><button className="btn btn-primary btn-sm" disabled={busy} onClick={openCreate}><Plus size={15}/>新建角色卡</button></div>
   <div className="cl-list-filters">
    <div className="cl-search-box">
     <Search size={14} className="cl-search-icon" aria-hidden="true"/>
     <input type="search" aria-label="搜索角色卡" placeholder="搜索名称或描述…" value={query} onChange={e=>setQuery(e.target.value)}/>
     {query&&<button type="button" className="cl-search-clear" aria-label="清空角色卡搜索" title="清空搜索" onClick={()=>setQuery('')}><X size={13}/></button>}
    </div>
    <div className="cl-filter-group" role="group" aria-label="按类型筛选角色卡">
     {KIND_FILTERS.map(opt=><button key={opt.value} type="button" aria-pressed={kindFilter===opt.value} onClick={()=>setKindFilter(opt.value)}>{opt.label}</button>)}
    </div>
   </div>
   {loadError&&<div role="alert" className="ul-error">{loadError}<button onClick={()=>setRevision(v=>v+1)}>重试加载</button></div>}
   {!loading&&!loadError&&!characters.length&&<div className="ul-empty-center cl-list-empty ila-empty-block"><CharacterEmptyArt variant="list"/><p className="ul-muted">还没有角色卡。新建角色卡后可上传角色卡图和参考音频，在画布提示词中用 @角色卡名 引用。</p></div>}
   {!loading&&!loadError&&characters.length>0&&!visibleCharacters.length&&<div className="cl-filter-empty"><p className="ul-muted">没有符合条件的角色卡</p><button type="button" className="btn btn-secondary btn-sm" onClick={()=>{setQuery('');setKindFilter('all')}}>清除筛选</button></div>}
   <ul role="listbox" aria-label="角色卡">{visibleCharacters.map(c=>{const cover=sortImages(c)[0],hasVoice=voiceIsAudio(c.voice),isProp=normalizeCharacterKind(c.kind)==='prop';return <li key={c.id}><button role="option" aria-selected={c.id===activeId} className="cl-card" disabled={busy} aria-label={`角色卡 ${c.name}${isProp?'（物件）':''}${hasVoice?'，已设置声音':''}`} onClick={()=>selectCharacter(c.id)}>
    {cover?<img src={cover.thumbnail_url||cover.url} alt=""/>:<span className="cl-cover-empty" aria-hidden="true"><CharacterCoverPlaceholder kind={isProp?'prop':'character'}/></span>}
    <span className="cl-card-text"><strong title={c.name}>{c.name}</strong><small>{isProp?'物件 · ':''}{(c.images||[]).length}/{CHARACTER_IMAGE_LIMIT} 张图</small></span>
    {hasVoice&&<span className="cl-voice-mark" title="已设置声音" aria-hidden="true"><AudioLines size={15}/></span>}
   </button></li>})}</ul>
  </aside>
  <section className="cl-detail" aria-label={character?`角色卡详情 ${character.name}`:'角色卡详情'}>
   {error&&<p className="ul-error" role="alert">{error}</p>}{notice&&<p className="ul-notice" role="status">{notice}</p>}
   {!character?(loading?null:<div className="ul-empty-center cl-detail-empty ila-empty-block"><CharacterEmptyArt variant="guide"/><p className="ul-muted">选择或新建一个角色卡</p><span className="ila-empty-sub">支持最多 {CHARACTER_IMAGE_LIMIT} 张多视角参考图与 1 段参考音频，在画布提示词中用 @角色卡名 引用</span>{!characters.length&&<button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={openCreate}>创建第一个角色卡</button>}</div>):<>
    <header className="cl-detail-header">
     <div className="cl-detail-hero">
      {images[0]?<img className="cl-detail-avatar" src={images[0].thumbnail_url||images[0].url} alt=""/>:<span className="cl-detail-avatar cl-cover-empty" aria-hidden="true"><CharacterCoverPlaceholder kind={normalizeCharacterKind(character.kind)==='prop'?'prop':'character'}/></span>}
      <div className="cl-detail-meta">
       <div className="cl-detail-title-row">
        <h3 title={character.name}>{character.name}</h3>
        <span className={`cl-kind-pill${normalizeCharacterKind(character.kind)==='prop'?' is-prop':''}`}>{characterKindLabel(character.kind)}</span>
        {hasUnsavedChanges&&<span className="cl-dirty-pill">未保存</span>}
       </div>
       <span className="cl-detail-stats">{images.length}/{CHARACTER_IMAGE_LIMIT} 张参考图 · {voiceIsAudio(character.voice)?'已设置参考音频':'未设声音'}</span>
      </div>
     </div>
     <div className="cl-detail-actions">
      <button type="button" className={`btn btn-sm ${canSave?'btn-primary':'btn-secondary'} cl-save-btn`} disabled={!canSave} onClick={saveChanges}><Save size={14}/>保存</button>
      <button type="button" className="btn btn-icon btn-outlined btn-danger cl-delete" aria-label={`删除角色卡 ${character.name}`} title="删除角色卡" disabled={busy} onClick={()=>setConfirmDelete(true)}><Trash2 size={16}/></button>
     </div>
    </header>
    <div className="cl-card-panel cl-identity-panel">
     <div className="cl-identity-top">
      <CharacterNameInput value={nameDraft} kind={character.kind} disabled={busy} error={nameError} onChange={v=>{setNameDraft(v);setError('')}} onEnter={()=>{if(canSave)saveChanges()}}/>
      <CharacterKindSelect value={character.kind} disabled={busy} onChange={saveKind}/>
     </div>
     <CharacterDescriptionInput value={descriptionDraft} kind={character.kind} disabled={busy} onChange={v=>{setDescriptionDraft(v);setError('')}}/>
    </div>
    <div className="cl-card-panel cl-section">
     <div className="cl-section-head">
      <div className="cl-section-title"><h4>角色卡图</h4><span className="cl-count-pill">{images.length}/{CHARACTER_IMAGE_LIMIT}</span></div>
      <div className="cl-section-actions">
       <button type="button" className="btn btn-secondary btn-sm" disabled={busy||remaining()<=0} onClick={()=>imageInput.current.click()}><Upload size={14}/>上传图片</button>
       <button type="button" className="btn btn-secondary btn-sm" disabled={busy||remaining()<=0} onClick={pickImages}><Images size={14}/>从素材库选择</button>
      </div>
     </div>
     <p className="cl-hint">点击缩略图查看大图，拖动或用左右按钮调整顺序；第一张作为角色卡首图。</p>
     {images.length?<ol className="cl-images" aria-label="角色卡图（按顺序）">{images.map((image,index)=><li key={image.asset_id} className={`cl-image${index===0?' is-cover':''}${dragging===image.asset_id?' is-dragging':''}${dropIndex===index&&dragging!==image.asset_id?' is-drop':''}`} draggable={!busy} onDragStart={e=>{setDragging(image.asset_id);e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',image.asset_id)}} onDragOver={e=>{if(!dragging)return;e.preventDefault();setDropIndex(index)}} onDragLeave={()=>setDropIndex(v=>v===index?null:v)} onDrop={e=>{e.preventDefault();const from=images.findIndex(i=>i.asset_id===dragging);setDragging(null);setDropIndex(null);move(from,index)}} onDragEnd={()=>{setDragging(null);setDropIndex(null)}} data-character-image={image.asset_id}>
      <button type="button" className="cl-image-preview-btn" aria-label={`预览角色卡图 第 ${index+1} 张 ${image.name||''}`.trim()} title={image.name?`${image.name}（点击查看大图）`:'点击查看大图'} onClick={()=>openImagePreview(image)}>
       <img src={image.thumbnail_url||image.url} alt="" draggable={false}/>
      </button>
      <span className={`cl-image-index${index===0?' is-cover':''}`} aria-hidden="true">{index===0?'1 · 首图':index+1}</span>
      <div className="cl-image-tools"><button type="button" aria-label={`前移 第 ${index+1} 张 ${image.name||''}`.trim()} title="前移" disabled={busy||index===0} onClick={()=>move(index,index-1)}><ChevronLeft size={13}/></button><button type="button" aria-label={`后移 第 ${index+1} 张 ${image.name||''}`.trim()} title="后移" disabled={busy||index===images.length-1} onClick={()=>move(index,index+1)}><ChevronRight size={13}/></button><button type="button" className="cl-image-del" aria-label={`删除角色卡图 第 ${index+1} 张 ${image.name||''}`.trim()} title="删除角色卡图" disabled={busy} onClick={()=>removeImage(image)}><Trash2 size={13}/></button></div>
     </li>)}</ol>:<div className="cl-slot-empty"><p className="ul-muted">还没有角色卡图。</p></div>}
    </div>
    <div className="cl-card-panel cl-section">
     <div className="cl-section-head">
      <div className="cl-section-title"><h4>声音</h4><span className="cl-count-pill">{CHARACTER_VOICE_MAX_SECONDS}s 以内</span></div>
      <div className="cl-section-actions">
       <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={()=>audioInput.current.click()}><Upload size={14}/>上传参考音频</button>
       <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={pickAudio}><AudioLines size={14}/>从素材库选择</button>
       {voiceIsAudio(character.voice)&&<button type="button" className="btn btn-ghost btn-sm btn-danger" disabled={busy} onClick={removeVoice}>移除声音</button>}
      </div>
     </div>
     <p className="cl-hint">参考音频支持 wav / mp3，{CHARACTER_VOICE_MAX_SECONDS} 秒以内；上传后同步入本地素材库。</p>
     {voiceIsAudio(character.voice)?<div className="cl-voice"><div className="cl-voice-info"><span className="cl-voice-badge" aria-hidden="true"><AudioLines size={15}/></span><span className="cl-voice-name" title={character.voice.name}>{character.voice.name||'参考音频'}{Number.isFinite(Number(character.voice.duration))&&Number(character.voice.duration)>0?` · ${Number(character.voice.duration).toFixed(1)} 秒`:''}</span></div><audio key={character.voice.url} controls preload="metadata" src={character.voice.url} aria-label={`试听 ${character.name} 的参考音频`}/></div>:<div className="cl-slot-empty cl-slot-empty-compact"><p className="ul-muted">未设置声音。</p></div>}
    </div>
   </>}
  </section>
  <input ref={imageInput} type="file" accept="image/*" multiple hidden onChange={e=>{const files=[...e.target.files];e.target.value='';if(files.length)uploadImages(files)}}/>
  <input ref={audioInput} type="file" accept=".wav,.mp3,audio/wav,audio/mpeg" hidden onChange={e=>{const file=e.target.files[0];e.target.value='';if(file)uploadAudio(file)}}/>
  {creating&&<CreateCharacterDialog characters={characters} onClose={()=>setCreating(false)} onCreated={c=>{setCreating(false);setCharacters(list=>[...list,c]);setActiveId(c.id);setNotice(`已新建角色卡“${c.name}”`);setRevision(v=>v+1)}}/>}
  {confirmDelete&&character&&<DeleteCharacterDialog character={character} onClose={()=>setConfirmDelete(false)} onDeleted={()=>{setConfirmDelete(false);setActiveId(null);setNotice(`已删除角色卡“${character.name}”`);setRevision(v=>v+1)}}/>}
  {preview&&createPortal(<div className="ul-preview-host"><MediaPreview key={preview.id||preview.url} asset={preview} onClose={()=>setPreview(null)}/></div>,document.body)}
 </div>
}

export function CreateCharacterDialog({characters,onClose,onCreated}){
 const [name,setName]=useState(''),[kind,setKind]=useState('character'),[description,setDescription]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[touched,setTouched]=useState(false)
 const nameError=touched||name?characterNameError(name,characters):''
 async function confirm(){setTouched(true);const issue=characterNameError(name,characters)||(descriptionLength(description)>CHARACTER_DESCRIPTION_MAX?`文字描述最多 ${CHARACTER_DESCRIPTION_MAX} 字`:'');if(issue){setError(issue);return}setBusy(true);setError('');try{onCreated(await createCharacter({name:name.trim(),description,kind}))}catch(e){setError(characterErrorMessage(e,'新建角色卡失败'));setBusy(false)}}
 return <LibraryDialog title="新建角色卡" busy={busy} error={error&&error!==nameError?error:''} confirmLabel="创建角色卡" disabled={!!nameError} onClose={onClose} onConfirm={confirm}><CharacterKindSelect value={kind} disabled={busy} onChange={setKind}/><CharacterNameInput autoFocus value={name} kind={kind} error={nameError} onChange={v=>{setName(v);setError('')}} onEnter={confirm}/><CharacterDescriptionInput value={description} kind={kind} onChange={setDescription}/></LibraryDialog>
}

function DeleteCharacterDialog({character,onClose,onDeleted}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('')
 return <LibraryDialog title={`删除角色卡“${character.name}”？`} busy={busy} error={error} confirmLabel="删除角色卡" danger onClose={onClose} onConfirm={async()=>{setBusy(true);setError('');try{await deleteCharacter(character.id);onDeleted()}catch(e){setError(characterErrorMessage(e,'删除失败'));setBusy(false)}}}><p>将删除角色卡“{character.name}”，无法撤销。</p><p className="ul-muted">角色卡引用的 {(character.images||[]).length} 张图片{character.voice?'和参考音频':''}仍保留在本地素材中；画布节点里已导入的素材保留，引用该角色卡的节点会提示角色卡已删除。</p></LibraryDialog>
}
