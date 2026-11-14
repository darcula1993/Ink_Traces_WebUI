import React,{useEffect,useRef,useState} from 'react'
import {Plus,Upload,Trash2,AudioLines,ChevronLeft,ChevronRight,Images,UserRound} from 'lucide-react'
import LibraryDialog from './LibraryDialog'
import {CharacterNameInput,CharacterDescriptionInput} from './CharacterFields'
import {listCharacters,getCharacter,createCharacter,updateCharacter,deleteCharacter,uploadCharacterImage,addLibraryImage,deleteCharacterImage,reorderCharacterImages,uploadVoiceAudio,addLibraryVoiceAudio,clearVoice,audioDuration,characterDescription} from '../../lib/characterApi'
import {CHARACTER_IMAGE_LIMIT,CHARACTER_DESCRIPTION_MAX,CHARACTER_VOICE_MAX_SECONDS,characterNameError,characterErrorMessage,descriptionLength,voiceIsAudio} from '../../lib/characterRules'
import './characterLibrary.css'

const sortImages=c=>[...(c?.images||[])].sort((a,b)=>(a.position??0)-(b.position??0))
const AUDIO_TYPES=/^audio\/(wav|x-wav|wave|vnd\.wave|mpeg|mp3)$/
const audioAllowed=file=>AUDIO_TYPES.test(file.type)||/\.(wav|mp3)$/i.test(file.name)

// Global character library: name, text description, up to 8 reference images and one reference audio.
// openPicker({title,kinds,limit,onApply}) opens the asset library as a nested picker (provided by UnifiedAssetLibrary).
export default function CharacterLibrary({openPicker,onBusy}){
 const [characters,setCharacters]=useState([]),[loading,setLoading]=useState(true),[loadError,setLoadError]=useState(''),[activeId,setActiveId]=useState(null),[detail,setDetail]=useState(null)
 const [busy,setBusyState]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[revision,setRevision]=useState(0)
 const [creating,setCreating]=useState(false),[confirmDelete,setConfirmDelete]=useState(false),[nameDraft,setNameDraft]=useState(''),[descriptionDraft,setDescriptionDraft]=useState('')
 const [dragging,setDragging]=useState(null),[dropIndex,setDropIndex]=useState(null)
 const imageInput=useRef(null),audioInput=useRef(null),lock=useRef(false),alive=useRef(true)
 useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[])
 const setBusy=v=>{setBusyState(v);onBusy?.(v)}
 useEffect(()=>{const controller=new AbortController();setLoading(true);setLoadError('');listCharacters(controller.signal).then(list=>{if(controller.signal.aborted)return;setCharacters(list);setActiveId(id=>list.some(c=>c.id===id)?id:list[0]?.id||null)}).catch(e=>{if(!controller.signal.aborted)setLoadError(characterErrorMessage(e,'角色列表加载失败'))}).finally(()=>{if(!controller.signal.aborted)setLoading(false)});return()=>controller.abort()},[revision])
 const listed=characters.find(c=>c.id===activeId)
 useEffect(()=>{let active=true;setDetail(listed||null);if(activeId)getCharacter(activeId).then(c=>{if(active&&c?.id===activeId)setDetail(c)}).catch(()=>{});return()=>{active=false}},[activeId,revision])
 useEffect(()=>{setNameDraft(detail?.name||'');setDescriptionDraft(characterDescription(detail))},[detail?.id,detail?.updated_at])
 const character=detail,images=sortImages(character),others=characters.filter(c=>c.id!==character?.id)
 const nameError=character&&nameDraft!==character.name?characterNameError(nameDraft,others):''
 const nameDirty=character&&nameDraft.trim()!==character.name,descriptionDirty=character&&descriptionDraft!==characterDescription(character)

 async function run(operation,success=''){if(lock.current){setError('请等待当前操作完成后再试');return false}lock.current=true;setBusy(true);setError('');setNotice('');try{await operation();if(alive.current&&success)setNotice(success);return true}catch(e){if(alive.current)setError(characterErrorMessage(e));return false}finally{lock.current=false;if(alive.current)setBusy(false)}}
 // Every mutation re-reads the character from the server; the server is the source of truth.
 async function reload(id=character?.id){const fresh=await getCharacter(id);if(!alive.current)return;setDetail(fresh);setCharacters(list=>list.map(c=>c.id===id?{...c,...fresh}:c))}
 function saveName(){const issue=characterNameError(nameDraft,others);if(issue){setError(issue);return}run(async()=>{await updateCharacter(character.id,{name:nameDraft.trim()});await reload()},'已保存角色名称')}
 function saveDescription(){if(descriptionLength(descriptionDraft)>CHARACTER_DESCRIPTION_MAX){setError(`文字描述最多 ${CHARACTER_DESCRIPTION_MAX} 字`);return}run(async()=>{await updateCharacter(character.id,{description:descriptionDraft});await reload()},'已保存文字描述')}
 function remaining(){return CHARACTER_IMAGE_LIMIT-images.length}
 async function uploadImages(files){const images=files.filter(f=>f.type.startsWith('image/'));if(images.length<files.length){setError('只能上传图片文件');if(!images.length)return}
  if(images.length>remaining()){setError(`每个角色最多 ${CHARACTER_IMAGE_LIMIT} 张图，还可添加 ${remaining()} 张`);return}
  let done=0;await run(async()=>{try{for(const file of images){await uploadCharacterImage(character.id,file);done++}}finally{await reload()}},`已上传 ${images.length} 张角色图`)
  if(done<images.length&&alive.current)setNotice(`已上传 ${done} 张，未处理 ${images.length-done} 张；请核对后再决定是否重新上传`)}
 function pickImages(){const left=remaining();if(left<=0){setError(`每个角色最多 ${CHARACTER_IMAGE_LIMIT} 张图`);return}
  openPicker({title:`为“${character.name}”选择角色图`,applyLabel:'加入角色图',kinds:['image'],limit:left,onApply:async items=>{const id=character.id;let done=0;try{for(const item of items){await addLibraryImage(id,item.selection);done++}}finally{if(alive.current)await reload(id).catch(()=>{})}if(alive.current)setNotice(`已从素材库加入 ${done} 张角色图（引用本地素材）`)}})}
 function removeImage(image){run(async()=>{await deleteCharacterImage(character.id,image.asset_id);await reload()},'已删除角色图')}
 function move(from,to){if(to<0||to>=images.length||from===to)return;const order=images.map(i=>i.asset_id),[item]=order.splice(from,1);order.splice(to,0,item);const optimistic=order.map((asset_id,position)=>({...images.find(i=>i.asset_id===asset_id),position}));setDetail(d=>({...d,images:optimistic}));run(async()=>{await reorderCharacterImages(character.id,order);await reload()}).then(ok=>{if(!ok&&alive.current)reload().catch(()=>{})})}
 async function checkDuration(src){let seconds;try{seconds=await audioDuration(src)}catch(e){throw e}if(!Number.isFinite(seconds))throw new Error('无法确认音频时长，请换用 wav 或 mp3 文件');if(seconds>CHARACTER_VOICE_MAX_SECONDS+0.05)throw new Error(`参考音频最长 ${CHARACTER_VOICE_MAX_SECONDS} 秒（当前约 ${seconds.toFixed(1)} 秒）`);return seconds}
 function uploadAudio(file){if(!audioAllowed(file)){setError('参考音频仅支持 wav 或 mp3');return}run(async()=>{await checkDuration(file);await uploadVoiceAudio(character.id,file);await reload()},'已设置参考音频')}
 function pickAudio(){openPicker({title:`为“${character.name}”选择参考音频`,applyLabel:'设为参考音频',kinds:['audio'],limit:1,onApply:async([item])=>{const id=character.id,known=Number(item.asset.duration);if(Number.isFinite(known)&&known>0){if(known>CHARACTER_VOICE_MAX_SECONDS+0.05)throw new Error(`参考音频最长 ${CHARACTER_VOICE_MAX_SECONDS} 秒（所选约 ${known.toFixed(1)} 秒）`)}else await checkDuration(item.asset.url);await addLibraryVoiceAudio(id,item.selection);if(alive.current){await reload(id);setNotice('已设置参考音频（引用本地素材）')}}})}
 function removeVoice(){run(async()=>{await clearVoice(character.id);await reload()},'已移除参考音频')}

 return <div className="cl-root">
  <aside className="cl-list" aria-label="角色列表">
   <div className="cl-list-head"><span>{loading?'正在载入…':`${characters.length} 个角色`}</span><button className="btn btn-primary btn-sm" disabled={busy} onClick={()=>{setError('');setCreating(true)}}><Plus size={15}/>新建角色</button></div>
   {loadError&&<div role="alert" className="ul-error">{loadError}<button onClick={()=>setRevision(v=>v+1)}>重试加载</button></div>}
   {!loading&&!loadError&&!characters.length&&<p className="ul-muted">还没有角色。新建角色后可上传角色图和参考音频，在画布提示词中用 @角色名 引用。</p>}
   <ul role="listbox" aria-label="角色">{characters.map(c=>{const cover=sortImages(c)[0],hasVoice=voiceIsAudio(c.voice);return <li key={c.id}><button role="option" aria-selected={c.id===activeId} className="cl-card" disabled={busy} aria-label={`角色 ${c.name}${hasVoice?'，已设置声音':''}`} onClick={()=>{setError('');setNotice('');setActiveId(c.id)}}>
    {cover?<img src={cover.thumbnail_url||cover.url} alt=""/>:<span className="cl-cover-empty" aria-hidden="true"><UserRound size={22} strokeWidth={1.5}/></span>}
    <span className="cl-card-text"><strong title={c.name}>{c.name}</strong><small>{(c.images||[]).length}/{CHARACTER_IMAGE_LIMIT} 张图</small></span>
    {hasVoice&&<span className="cl-voice-mark" title="已设置声音" aria-hidden="true"><AudioLines size={15}/></span>}
   </button></li>})}</ul>
  </aside>
  <section className="cl-detail" aria-label={character?`角色详情 ${character.name}`:'角色详情'}>
   {error&&<p className="ul-error" role="alert">{error}</p>}{notice&&<p className="ul-notice" role="status">{notice}</p>}
   {!character?<p className="ul-muted">{loading?'':'选择或新建一个角色'}</p>:<>
    <div className="cl-row cl-name-row"><CharacterNameInput value={nameDraft} error={nameError} onChange={v=>{setNameDraft(v);setError('')}} onEnter={()=>{if(nameDirty)saveName()}}/><button disabled={busy||!nameDirty||!!nameError} onClick={saveName}>保存名称</button><button className="btn btn-icon btn-outlined cl-delete" aria-label={`删除角色 ${character.name}`} title="删除角色" disabled={busy} onClick={()=>setConfirmDelete(true)}><Trash2 size={16}/></button></div>
    <div className="cl-row cl-description-row"><CharacterDescriptionInput value={descriptionDraft} onChange={setDescriptionDraft}/><button disabled={busy||!descriptionDirty||descriptionLength(descriptionDraft)>CHARACTER_DESCRIPTION_MAX} onClick={saveDescription}>保存描述</button></div>
    <div className="cl-section"><div className="cl-section-head"><h4>角色图 <small>{images.length}/{CHARACTER_IMAGE_LIMIT}</small></h4><button disabled={busy||remaining()<=0} onClick={()=>imageInput.current.click()}><Upload size={15}/>上传图片</button><button disabled={busy||remaining()<=0} onClick={pickImages}><Images size={15}/>从素材库选择</button></div>
     <p className="cl-hint">拖动调整顺序（也可用左右按钮）；第一张作为角色首图。角色图引用本地素材，在此上传的图片也会出现在本地素材中。</p>
     {images.length?<ol className="cl-images" aria-label="角色图（按顺序）">{images.map((image,index)=><li key={image.asset_id} className={`cl-image${dragging===image.asset_id?' is-dragging':''}${dropIndex===index&&dragging!==image.asset_id?' is-drop':''}`} draggable={!busy} onDragStart={e=>{setDragging(image.asset_id);e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',image.asset_id)}} onDragOver={e=>{if(!dragging)return;e.preventDefault();setDropIndex(index)}} onDragLeave={()=>setDropIndex(v=>v===index?null:v)} onDrop={e=>{e.preventDefault();const from=images.findIndex(i=>i.asset_id===dragging);setDragging(null);setDropIndex(null);move(from,index)}} onDragEnd={()=>{setDragging(null);setDropIndex(null)}} data-character-image={image.asset_id}>
      <img src={image.thumbnail_url||image.url} alt="" title={image.name}/><span className="cl-image-index" aria-hidden="true">{index+1}</span>
      <div className="cl-image-tools"><button aria-label={`前移 第 ${index+1} 张 ${image.name||''}`.trim()} title="前移" disabled={busy||index===0} onClick={()=>move(index,index-1)}><ChevronLeft size={14}/></button><button aria-label={`后移 第 ${index+1} 张 ${image.name||''}`.trim()} title="后移" disabled={busy||index===images.length-1} onClick={()=>move(index,index+1)}><ChevronRight size={14}/></button><button aria-label={`删除角色图 第 ${index+1} 张 ${image.name||''}`.trim()} title="删除角色图" disabled={busy} onClick={()=>removeImage(image)}><Trash2 size={14}/></button></div>
     </li>)}</ol>:<p className="ul-muted">还没有角色图。</p>}
    </div>
    <div className="cl-section"><div className="cl-section-head"><h4>声音</h4><button disabled={busy} onClick={()=>audioInput.current.click()}><Upload size={15}/>上传参考音频</button><button disabled={busy} onClick={pickAudio}><AudioLines size={15}/>从素材库选择</button>{voiceIsAudio(character.voice)&&<button disabled={busy} onClick={removeVoice}>移除声音</button>}</div>
     <p className="cl-hint">参考音频 wav / mp3，{CHARACTER_VOICE_MAX_SECONDS} 秒以内；可在下方试听。在此上传的音频也会出现在本地素材中。</p>
     {voiceIsAudio(character.voice)?<div className="cl-voice"><span title={character.voice.name}>{character.voice.name||'参考音频'}{Number.isFinite(Number(character.voice.duration))&&Number(character.voice.duration)>0?` · ${Number(character.voice.duration).toFixed(1)} 秒`:''}</span><audio key={character.voice.url} controls preload="metadata" src={character.voice.url} aria-label={`试听 ${character.name} 的参考音频`}/></div>:<p className="ul-muted">未设置声音。</p>}
    </div>
   </>}
  </section>
  <input ref={imageInput} type="file" accept="image/*" multiple hidden onChange={e=>{const files=[...e.target.files];e.target.value='';if(files.length)uploadImages(files)}}/>
  <input ref={audioInput} type="file" accept=".wav,.mp3,audio/wav,audio/mpeg" hidden onChange={e=>{const file=e.target.files[0];e.target.value='';if(file)uploadAudio(file)}}/>
  {creating&&<CreateCharacterDialog characters={characters} onClose={()=>setCreating(false)} onCreated={c=>{setCreating(false);setCharacters(list=>[...list,c]);setActiveId(c.id);setNotice(`已新建角色“${c.name}”`);setRevision(v=>v+1)}}/>}
  {confirmDelete&&character&&<DeleteCharacterDialog character={character} onClose={()=>setConfirmDelete(false)} onDeleted={()=>{setConfirmDelete(false);setActiveId(null);setNotice(`已删除角色“${character.name}”`);setRevision(v=>v+1)}}/>}
 </div>
}

export function CreateCharacterDialog({characters,onClose,onCreated}){
 const [name,setName]=useState(''),[description,setDescription]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[touched,setTouched]=useState(false)
 const nameError=touched||name?characterNameError(name,characters):''
 async function confirm(){setTouched(true);const issue=characterNameError(name,characters)||(descriptionLength(description)>CHARACTER_DESCRIPTION_MAX?`文字描述最多 ${CHARACTER_DESCRIPTION_MAX} 字`:'');if(issue){setError(issue);return}setBusy(true);setError('');try{onCreated(await createCharacter({name:name.trim(),description}))}catch(e){setError(characterErrorMessage(e,'新建角色失败'));setBusy(false)}}
 return <LibraryDialog title="新建角色" busy={busy} error={error&&error!==nameError?error:''} confirmLabel="创建角色" disabled={!!nameError} onClose={onClose} onConfirm={confirm}><CharacterNameInput autoFocus value={name} error={nameError} onChange={v=>{setName(v);setError('')}} onEnter={confirm}/><CharacterDescriptionInput value={description} onChange={setDescription}/></LibraryDialog>
}

function DeleteCharacterDialog({character,onClose,onDeleted}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('')
 return <LibraryDialog title={`删除角色“${character.name}”？`} busy={busy} error={error} confirmLabel="删除角色" onClose={onClose} onConfirm={async()=>{setBusy(true);setError('');try{await deleteCharacter(character.id);onDeleted()}catch(e){setError(characterErrorMessage(e,'删除失败'));setBusy(false)}}}><p>将删除角色“{character.name}”，无法撤销。</p><p className="ul-muted">角色引用的 {(character.images||[]).length} 张图片{character.voice?'和参考音频':''}仍保留在本地素材中；画布节点里已导入的素材保留，引用该角色的节点会提示角色已删除。</p></LibraryDialog>
}
