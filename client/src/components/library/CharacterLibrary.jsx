import React,{useEffect,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import {Plus,Upload,Trash2,AudioLines,ChevronLeft,ChevronRight,Images,Save,Search,X} from 'lucide-react'
import {CharacterEmptyArt,CharacterCoverPlaceholder} from '../art/CanvasLibraryArt'
import LibraryDialog from './LibraryDialog'
import {CharacterKindSelect,CharacterNameInput,CharacterInitialImagesField,DESCRIPTION_HINT,PROP_DESCRIPTION_HINT} from './CharacterFields'
import MediaPreview from '../canvas/MediaPreview'
import {withPreviewPages} from '../canvas/previewPages'
import askConfirm from '../ui/askConfirm'
import {listCharacters,getCharacter,createCharacter,updateCharacter,previewDeleteCharacter,deleteCharacter,uploadCharacterImage,addLibraryImage,deleteCharacterImage,reorderCharacterImages,uploadVoiceAudio,addLibraryVoiceAudio,clearVoice,audioDuration,characterDescription} from '../../lib/characterApi'
import {notifyLibraryChanged} from '../../lib/librarySync'
import {deletePlanLines} from './mediaLibrary'
import {CHARACTER_IMAGE_LIMIT,CHARACTER_DESCRIPTION_MAX,CHARACTER_VOICE_MAX_SECONDS,characterKindLabel,characterNameError,characterErrorMessage,descriptionLength,normalizeCharacterKind,voiceIsAudio} from '../../lib/characterRules'
import './characterLibrary.css'

// LIBRARY-GLOBAL-20261116 S6c: a picked library item is referenced by its media id (selection
// {source:'media',id}); nothing is re-uploaded. Other selections (e.g. Cupsy) go as their catalog ref.
const attachPicked=(item,reference)=>reference(item.selection?.source==='media'?{source:'media',id:item.selection.id}:item.selection)
const sortImages=c=>[...(c?.images||[])].sort((a,b)=>(a.position??0)-(b.position??0))
const AUDIO_TYPES=/^audio\/(wav|x-wav|wave|vnd\.wave|mpeg|mp3)$/
const audioAllowed=file=>AUDIO_TYPES.test(file.type)||/\.(wav|mp3)$/i.test(file.name)
const KIND_FILTERS=[{value:'all',label:'全部'},{value:'character',label:'人物'},{value:'prop',label:'物件'}]

// V24-W1-URL-POLISH-20261121: keep placeholder as a concrete example distinct from the helper hint below
// so empty description fields never display the exact same sentence twice.
function CharacterDescriptionField({value,onChange,disabled=false,kind='character'}){
 const length=descriptionLength(value),over=length>CHARACTER_DESCRIPTION_MAX,isProp=normalizeCharacterKind(kind)==='prop'
 const hint=isProp?PROP_DESCRIPTION_HINT:DESCRIPTION_HINT
 const placeholder=isProp?'例如：青铜怀表，表盖雕花，配旧黄铜链条':'例如：黑色短发，深蓝长风衣，左眼下方有小痣'
 return <div className="cl-field cl-desc-field"><div className="cl-field-head"><label htmlFor="cl-description">文字描述</label><span className={`cl-char-count${over?' is-over':''}`} aria-label={`已输入 ${length} 字，最多 ${CHARACTER_DESCRIPTION_MAX} 字`}>{length}/{CHARACTER_DESCRIPTION_MAX}{over&&'（超出上限）'}</span></div><textarea id="cl-description" disabled={disabled} aria-label="文字描述" aria-describedby="cl-description-hint" aria-invalid={over||undefined} rows={3} value={value} placeholder={placeholder} onChange={e=>onChange(e.target.value)}/><small id="cl-description-hint" className={over?'cl-field-error':'cl-hint'}>{hint}</small></div>
}

// Global character library: name, text description, up to 8 reference images and one reference audio.
// openPicker({title,kinds,limit,onApply}) opens the asset library as a nested picker (provided by UnifiedAssetLibrary).
export default function CharacterLibrary({openPicker,onBusy,onChanged,onBeforeDelete,onDeleted}){
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
 function syncLibrary(){onChanged?.();notifyLibraryChanged({source:'character'})}
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
  const renamed=nameDirty
  const msg=nameDirty&&descriptionDirty?'已保存角色卡修改':nameDirty?'已保存角色卡名称':'已保存文字描述'
  run(async()=>{await updateCharacter(character.id,patch);await reload();if(renamed)syncLibrary()},msg)
 }
 function saveKind(nextKind){const value=normalizeCharacterKind(nextKind);if(value===normalizeCharacterKind(character?.kind))return;run(async()=>{await updateCharacter(character.id,{kind:value});await reload()},`已切换为${characterKindLabel(value)}模板`)}
 function remaining(){return CHARACTER_IMAGE_LIMIT-images.length}
 async function uploadImages(files){const images=files.filter(f=>f.type.startsWith('image/'));if(images.length<files.length){setError('只能上传图片文件');if(!images.length)return}
  if(images.length>remaining()){setError(`每个角色卡最多 ${CHARACTER_IMAGE_LIMIT} 张图，还可添加 ${remaining()} 张`);return}
  let done=0;await run(async()=>{try{for(const file of images){await uploadCharacterImage(character.id,file);done++}}finally{await reload();if(done>0)syncLibrary()}},`已上传 ${images.length} 张角色卡图`)
  if(done<images.length&&alive.current)setNotice(`已上传 ${done} 张，未处理 ${images.length-done} 张；请核对后再决定是否重新上传`)}
 function pickImages(){const left=remaining();if(left<=0){setError(`每个角色卡最多 ${CHARACTER_IMAGE_LIMIT} 张图`);return}
  openPicker({title:`为“${character.name}”选择角色卡图`,applyLabel:'加入角色卡图',kinds:['image'],limit:left,onApply:async items=>{const id=character.id;let done=0;try{for(const item of items){await attachPicked(item,selection=>addLibraryImage(id,selection));done++}}finally{if(alive.current)await reload(id).catch(()=>{});if(done>0)syncLibrary()}if(alive.current)setNotice(`已从素材库加入 ${done} 张角色卡图`)}})}
 function removeImage(image){run(async()=>{await deleteCharacterImage(character.id,image.asset_id);await reload();syncLibrary()},'已从角色卡移除图片（素材已保留并移回根目录）')}
 function move(from,to){if(to<0||to>=images.length||from===to)return;const order=images.map(i=>i.asset_id),[item]=order.splice(from,1);order.splice(to,0,item);const optimistic=order.map((asset_id,position)=>({...images.find(i=>i.asset_id===asset_id),position}));setDetail(d=>({...d,images:optimistic}));run(async()=>{await reorderCharacterImages(character.id,order);await reload()}).then(ok=>{if(!ok&&alive.current)reload().catch(()=>{})})}
 function openImagePreview(image){
  const pages=images.map((item,idx)=>({id:item.asset_id,url:item.url,name:item.name||`${character?.name||'角色卡'} 图 ${idx+1}`,kind:'image'}))
  const current=pages.find(p=>p.id===image.asset_id)||pages[0]
  if(current)setPreview(withPreviewPages(current,pages))
 }
 async function checkDuration(src){let seconds;try{seconds=await audioDuration(src)}catch(e){throw e}if(!Number.isFinite(seconds))throw new Error('无法确认音频时长，请换用 wav 或 mp3 文件');if(seconds>CHARACTER_VOICE_MAX_SECONDS+0.05)throw new Error(`参考音频最长 ${CHARACTER_VOICE_MAX_SECONDS} 秒（当前约 ${seconds.toFixed(1)} 秒）`);return seconds}
 function uploadAudio(file){if(!audioAllowed(file)){setError('参考音频仅支持 wav 或 mp3');return}run(async()=>{await checkDuration(file);await uploadVoiceAudio(character.id,file);await reload();syncLibrary()},'已设置参考音频')}
 function pickAudio(){openPicker({title:`为“${character.name}”选择参考音频`,applyLabel:'设为参考音频',kinds:['audio'],limit:1,onApply:async([item])=>{const id=character.id,known=Number(item.asset.duration);if(Number.isFinite(known)&&known>0){if(known>CHARACTER_VOICE_MAX_SECONDS+0.05)throw new Error(`参考音频最长 ${CHARACTER_VOICE_MAX_SECONDS} 秒（所选约 ${known.toFixed(1)} 秒）`)}else await checkDuration(item.asset.url);await attachPicked(item,selection=>addLibraryVoiceAudio(id,selection));if(alive.current){await reload(id);syncLibrary();setNotice('已设置参考音频')}}})}
 function removeVoice(){run(async()=>{await clearVoice(character.id);await reload();syncLibrary()},'已移除参考音频（素材已保留并移回根目录）')}

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
     <CharacterDescriptionField value={descriptionDraft} kind={character.kind} disabled={busy} onChange={v=>{setDescriptionDraft(v);setError('')}}/>
    </div>
    <div className="cl-card-panel cl-section">
     <div className="cl-section-head">
      <div className="cl-section-title"><h4>角色卡图</h4><span className="cl-count-pill">{images.length}/{CHARACTER_IMAGE_LIMIT}</span></div>
      <div className="cl-section-actions">
       <button type="button" className="btn btn-secondary btn-sm" disabled={busy||remaining()<=0} onClick={()=>imageInput.current.click()}><Upload size={14}/>上传图片</button>
       <button type="button" className="btn btn-secondary btn-sm" disabled={busy||remaining()<=0} onClick={pickImages}><Images size={14}/>从素材库选择</button>
      </div>
     </div>
     <p className="cl-hint">点击缩略图查看大图，拖动或用左右按钮调整顺序；第一张作为角色卡首图。素材统一归入「角色卡 / {character.name}」子文件夹，移除单张后素材保留并移回根目录。</p>
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
     <p className="cl-hint">参考音频支持 wav / mp3，{CHARACTER_VOICE_MAX_SECONDS} 秒以内；统一归入「角色卡 / {character.name}」子文件夹，移除后保留并移回根目录。</p>
     {voiceIsAudio(character.voice)?<div className="cl-voice"><div className="cl-voice-info"><span className="cl-voice-badge" aria-hidden="true"><AudioLines size={15}/></span><span className="cl-voice-name" title={character.voice.name}>{character.voice.name||'参考音频'}{Number.isFinite(Number(character.voice.duration))&&Number(character.voice.duration)>0?` · ${Number(character.voice.duration).toFixed(1)} 秒`:''}</span></div><audio key={character.voice.url} controls preload="metadata" src={character.voice.url} aria-label={`试听 ${character.name} 的参考音频`}/></div>:<div className="cl-slot-empty cl-slot-empty-compact"><p className="ul-muted">未设置声音。</p></div>}
    </div>
   </>}
  </section>
  <input ref={imageInput} type="file" accept="image/*" multiple hidden onChange={e=>{const files=[...e.target.files];e.target.value='';if(files.length)uploadImages(files)}}/>
  <input ref={audioInput} type="file" accept=".wav,.mp3,audio/wav,audio/mpeg" hidden onChange={e=>{const file=e.target.files[0];e.target.value='';if(file)uploadAudio(file)}}/>
  {creating&&<CreateCharacterDialog characters={characters} openPicker={openPicker} libraryRootRef={rootRef} onClose={partial=>{setCreating(false);if(partial){setCharacters(list=>list.some(c=>c.id===partial.id)?list.map(c=>c.id===partial.id?{...c,...partial}:c):[...list,partial]);setActiveId(partial.id);setNotice(`角色卡“${partial.name}”已创建，可在详情页继续补充参考图`);setRevision(v=>v+1);syncLibrary()}}} onCreated={(c,{imageCount=0}={})=>{setCreating(false);setCharacters(list=>list.some(item=>item.id===c.id)?list.map(item=>item.id===c.id?{...item,...c}:item):[...list,c]);setActiveId(c.id);setNotice(imageCount?`已新建角色卡“${c.name}”（已绑定 ${imageCount} 张参考图）`:`已新建角色卡“${c.name}”`);setRevision(v=>v+1);syncLibrary()}}/>}
  {confirmDelete&&character&&<DeleteCharacterDialog character={character} onBeforeDelete={onBeforeDelete} onClose={()=>setConfirmDelete(false)} onDeleted={(result,{deleteMedia=false,preview:plan=null,mediaCount=0}={})=>{setConfirmDelete(false);setActiveId(null);const deletedIds=result?.deleted_media_ids||[];const deletedCount=deletedIds.length||mediaCount;setNotice(deleteMedia?`已删除角色卡“${character.name}”并彻底删除其文件夹下的 ${deletedCount} 个素材`:`已删除角色卡“${character.name}”，原素材已移回素材库根目录`);setRevision(v=>v+1);if(onDeleted)onDeleted(result,{deleteMedia,preview:plan});else{notifyLibraryChanged({source:'character_delete',deletedIds});onChanged?.()}}}/>}
  {preview&&createPortal(<div className="ul-preview-host"><MediaPreview key={preview.id||preview.url} asset={preview} onClose={()=>setPreview(null)}/></div>,document.body)}
 </div>
}

export function CreateCharacterDialog({characters,openPicker,libraryRootRef,onClose,onCreated}){
 const [name,setName]=useState(''),[kind,setKind]=useState('character'),[description,setDescription]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[touched,setTouched]=useState(false)
 const [picked,setPicked]=useState([]),[picking,setPicking]=useState(false),[preview,setPreview]=useState(null)
 const [created,setCreated]=useState(null),[boundKeys,setBoundKeys]=useState(()=>new Set()),[failedKey,setFailedKey]=useState(null)
 const pickButtonRef=useRef(null),wasPickingRef=useRef(false)
 const peers=created?characters.filter(c=>c.id!==created.id):characters
 const nameError=touched||name?characterNameError(name,peers):''
 const descriptionOver=descriptionLength(description)>CHARACTER_DESCRIPTION_MAX

 // When the nested library picker closes (cancel, Escape, or apply), UnifiedAssetLibrary removes `inert`
 // from the outer `.ul-library`; observe that so this dialog always reappears with its form state intact.
 useEffect(()=>{
  if(!picking){
   if(wasPickingRef.current){wasPickingRef.current=false;requestAnimationFrame(()=>pickButtonRef.current?.focus?.({preventScroll:true}))}
   return undefined
  }
  wasPickingRef.current=true
  const libraryEl=libraryRootRef?.current?.closest?.('.ul-library')
  if(!libraryEl)return undefined
  let sawHidden=libraryEl.hasAttribute('inert')
  const sync=()=>{
   const hidden=libraryEl.hasAttribute('inert')
   if(hidden)sawHidden=true
   else if(sawHidden)setPicking(false)
  }
  const observer=new MutationObserver(sync)
  observer.observe(libraryEl,{attributes:true,attributeFilter:['inert','aria-hidden']})
  const raf=requestAnimationFrame(sync)
  return()=>{cancelAnimationFrame(raf);observer.disconnect()}
 },[picking,libraryRootRef])

 function pickInitialImages(){
  if(!openPicker||busy)return
  const left=CHARACTER_IMAGE_LIMIT-picked.length
  if(left<=0){setError(`每个角色卡最多 ${CHARACTER_IMAGE_LIMIT} 张图`);return}
  setError('');setPicking(true)
  openPicker({
   title:`为新建${characterKindLabel(kind)}卡选择初始参考图`,
   applyLabel:'选为初始参考图',
   kinds:['image'],
   limit:left,
   onApply:async items=>{
    setPicked(current=>{
     const seen=new Set(current.map(i=>i.key)),next=[...current]
     for(const item of items){if(!seen.has(item.key)&&next.length<CHARACTER_IMAGE_LIMIT){seen.add(item.key);next.push(item)}}
     return next
    })
    setPicking(false)
   },
  })
 }

 function removePickedImage(key){
  if(busy||boundKeys.has(key))return
  setPicked(current=>current.filter(item=>item.key!==key))
  if(failedKey===key){setFailedKey(null);setError('')}
 }

 function openPickedPreview(item){
  const pages=picked.map((entry,idx)=>({id:entry.key,url:entry.asset?.url||entry.thumbnail_url,name:entry.asset?.name||`初始参考图 ${idx+1}`,kind:'image'}))
  const current=pages.find(p=>p.id===item.key)||pages[0]
  if(current)setPreview(withPreviewPages(current,pages))
 }

 async function confirm(){
  setTouched(true)
  const trimmedName=name.trim()
  const issue=characterNameError(trimmedName,peers)||(descriptionOver?`文字描述最多 ${CHARACTER_DESCRIPTION_MAX} 字`:'')
  if(issue){setError(issue);return}
  setBusy(true);setError('');setFailedKey(null)
  let current=created
  try{
   if(!current){
    current=await createCharacter({name:trimmedName,description,kind})
    setCreated(current)
   }else{
    const patch={}
    if(trimmedName!==current.name)patch.name=trimmedName
    if(description!==characterDescription(current))patch.description=description
    if(normalizeCharacterKind(kind)!==normalizeCharacterKind(current.kind))patch.kind=kind
    if(Object.keys(patch).length){current=await updateCharacter(current.id,patch);setCreated(current)}
   }
   const pending=picked.filter(item=>!boundKeys.has(item.key))
   let latest=current
   for(let i=0;i<pending.length;i++){
    const item=pending[i]
    try{
     const res=await attachPicked(item,selection=>addLibraryImage(current.id,selection))
     if(res?.character)latest=res.character
     setBoundKeys(prev=>{const next=new Set(prev);next.add(item.key);return next})
     setCreated(latest)
    }catch(imgErr){
     setFailedKey(item.key)
     setError(`角色卡“${current.name}”已创建，但绑定参考图“${item.asset?.name||`第 ${i+1} 张`}”失败：${characterErrorMessage(imgErr,'绑定参考图失败')}。已填信息保留，可移除失败图片后重试。`)
     setBusy(false)
     return
    }
   }
   if(picked.length&&(!latest?.images||latest.images.length<picked.length)){
    try{latest=await getCharacter(current.id)}catch{/* keep latest */}
   }
   onCreated(latest,{imageCount:picked.length})
  }catch(e){
   setError(characterErrorMessage(e,'新建角色卡失败'))
   setBusy(false)
  }
 }
 return <>
  <LibraryDialog title="新建角色卡" className={`cl-create-dialog${picking?' is-picking':''}`} busy={busy} error={error&&error!==nameError?error:''} confirmLabel={created?'重试绑定并保存':'创建角色卡'} disabled={!!nameError||descriptionOver} onClose={()=>onClose(created)} onConfirm={confirm}>
   <CharacterKindSelect value={kind} disabled={busy} onChange={setKind}/>
   <CharacterNameInput autoFocus value={name} kind={kind} disabled={busy} error={nameError} onChange={v=>{setName(v);setError('')}} onEnter={confirm}/>
   <CharacterDescriptionField value={description} kind={kind} disabled={busy} onChange={v=>{setDescription(v);setError('')}}/>
   <CharacterInitialImagesField images={picked} boundKeys={boundKeys} failedKey={failedKey} disabled={busy} canPick={!!openPicker} onPick={pickInitialImages} onRemove={removePickedImage} onPreview={openPickedPreview} pickButtonRef={pickButtonRef}/>
  </LibraryDialog>
  {preview&&createPortal(<div className="ul-preview-host"><MediaPreview key={preview.id||preview.url} asset={preview} onClose={()=>setPreview(null)}/></div>,document.body)}
 </>
}

function DeleteCharacterDialog({character,onBeforeDelete,onClose,onDeleted}){
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[deleteMedia,setDeleteMedia]=useState(false)
 const [loadingPreview,setLoadingPreview]=useState(true),[previewData,setPreviewData]=useState(null),[previewError,setPreviewError]=useState('')
 useEffect(()=>{
  let alive=true
  setLoadingPreview(true);setPreviewError('');setPreviewData(null)
  previewDeleteCharacter(character.id).then(data=>{
   if(alive)setPreviewData(data)
  }).catch(e=>{
   if(alive)setPreviewError(characterErrorMessage(e,'无法加载素材删除预览'))
  }).finally(()=>{
   if(alive)setLoadingPreview(false)
  })
  return()=>{alive=false}
 },[character.id])
 const folderTitle=previewData?.folder_title||`角色卡 / ${character.name}`
 const rawPlan=previewData?.preview||null
 const mediaCount=previewData?Number(previewData.media_count??rawPlan?.items?.length??0):((character.images||[]).length+(voiceIsAudio(character.voice)?1:0))
 const safePlan=rawPlan?{
  items:rawPlan.items||[],
  missing:rawPlan.missing||[],
  affected_workflows:rawPlan.affected_workflows||[],
  characters:rawPlan.characters||[],
  media_groups:rawPlan.media_groups||[],
  task_ids:rawPlan.task_ids||[],
 }:null
 async function handleConfirm(){
  setBusy(true);setError('')
  try{
   if(deleteMedia)await onBeforeDelete?.()
   const result=await deleteCharacter(character.id,{deleteMedia})
   onDeleted(result,{deleteMedia,preview:safePlan,mediaCount})
  }catch(e){
   setError(characterErrorMessage(e,'删除失败'))
   setBusy(false)
  }
 }
 return <LibraryDialog title={`删除角色卡“${character.name}”？`} busy={busy} error={error} confirmLabel={deleteMedia?'删除角色卡并彻底删除素材':'删除角色卡'} disabled={deleteMedia&&(loadingPreview||!safePlan)} danger onClose={onClose} onConfirm={handleConfirm}>
  <p>将删除角色卡“{character.name}”，无法撤销。</p>
  {loadingPreview?<p className="ul-muted" role="status">正在统计角色卡文件夹素材…</p>
   :previewError?<p className="ul-muted">未能获取素材删除预览（{previewError}）。默认仍可安全删除角色卡，保留原素材并移回素材库根目录。</p>
   :mediaCount===0?<p className="ul-muted">该角色卡文件夹内没有素材，删除后将自动清理空的「{folderTitle}」子文件夹。</p>
   :<>
    {!deleteMedia&&<p className="ul-muted">默认保留「{folderTitle}」下的 {mediaCount} 个素材并移回素材库根目录，自动清理空子文件夹；画布中已导入的素材不受影响。</p>}
    <div className={`cl-delete-media-toggle${deleteMedia?' is-checked':''}`}>
     <label>
      <input type="checkbox" checked={deleteMedia} disabled={busy} onChange={e=>{setDeleteMedia(e.target.checked);setError('')}}/>
      <span>同时彻底删除「{folderTitle}」文件夹下的 {mediaCount} 个素材（不可恢复）</span>
     </label>
    </div>
    {deleteMedia&&safePlan&&<div className="cl-delete-preview" role="status" data-testid="character-delete-preview">
     {deletePlanLines(safePlan).map((line,i)=><p key={i}>{line}</p>)}
     {safePlan.affected_workflows.length>0&&<ul className="ul-delete-workflows" aria-label="受影响的画布">{safePlan.affected_workflows.map(w=><li key={w.workflow_id} data-workflow-id={w.workflow_id}><b>{w.project_title||'项目已删除'}</b> / <b>{w.workflow_title||w.workflow_id}</b>：{w.placeholder_nodes||0} 个“已删除”占位，{w.stripped_nodes||0} 个节点移除引用</li>)}</ul>}
     <p className="ul-muted">“已删除”：节点保留原位置和名称并显示为“已删除”，可重新选择素材替换；归档的画布不改写。</p>
     <p><strong>此操作不可恢复。</strong>Cupsy 远端素材不受影响。</p>
    </div>}
   </>}
 </LibraryDialog>
}
