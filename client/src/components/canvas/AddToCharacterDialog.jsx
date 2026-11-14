import React,{useEffect,useState} from 'react'
import {UserRound} from 'lucide-react'
import LibraryDialog from '../library/LibraryDialog'
import {CharacterNameInput,CharacterDescriptionInput} from '../library/CharacterFields'
import {listCharacters,createCharacter,addCanvasImage} from '../../lib/characterApi'
import {CHARACTER_IMAGE_LIMIT,CHARACTER_DESCRIPTION_MAX,characterNameError,characterErrorMessage,descriptionLength} from '../../lib/characterRules'
import '../library/library.css'
import '../library/characterLibrary.css'
// Canvas node context menu → “加入角色”: copy the node's image into an existing or new character.
// The server registers it as a local asset and the character references it; the canvas node is unchanged.
export default function AddToCharacterDialog({workflowId,asset,onClose}){
 const [characters,setCharacters]=useState(null),[mode,setMode]=useState('existing'),[chosen,setChosen]=useState(''),[name,setName]=useState(''),[description,setDescription]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[done,setDone]=useState('')
 useEffect(()=>{let active=true;listCharacters().then(list=>{if(!active)return;setCharacters(list);if(!list.length)setMode('new');else setChosen(list.find(c=>(c.images||[]).length<CHARACTER_IMAGE_LIMIT)?.id||'')}).catch(e=>{if(active){setCharacters([]);setError(characterErrorMessage(e,'角色列表加载失败'))}});return()=>{active=false}},[])
 const list=characters||[],nameError=mode==='new'&&name?characterNameError(name,list):''
 const target=list.find(c=>c.id===chosen),full=c=>(c.images||[]).length>=CHARACTER_IMAGE_LIMIT
 async function confirm(){
  setError('')
  if(mode==='new'){const issue=characterNameError(name,list)||(descriptionLength(description)>CHARACTER_DESCRIPTION_MAX?`文字描述最多 ${CHARACTER_DESCRIPTION_MAX} 字`:'');if(issue){setError(issue);return}}
  else if(!target){setError('请选择一个角色');return}
  else if(full(target)){setError(`角色“${target.name}”已有 ${CHARACTER_IMAGE_LIMIT} 张图，请先在角色库删除部分图片`);return}
  setBusy(true)
  let character=target
  try{
   if(mode==='new'){character=await createCharacter({name:name.trim(),description});setCharacters(v=>[...(v||[]),character]);setChosen(character.id);setMode('existing')}
   await addCanvasImage(character.id,workflowId,asset.id)
   setDone(`已把图片加入角色“${character.name}”（已登记为本地素材并由角色引用，画布节点不变）`)
  }catch(e){setError(mode==='new'&&character&&character!==target?`已新建角色“${character.name}”，但加入图片失败：${characterErrorMessage(e)}`:characterErrorMessage(e,'加入角色失败'))}
  finally{setBusy(false)}
 }
 if(done)return <LibraryDialog title="加入角色" cancelLabel="关闭" onClose={onClose}><p role="status">{done}</p></LibraryDialog>
 return <LibraryDialog title="加入角色" busy={busy} error={error&&error!==nameError?error:''} confirmLabel={mode==='new'?'新建并加入':'加入角色'} disabled={!characters||mode==='existing'&&(!target||full(target))||mode==='new'&&!!nameError} onClose={onClose} onConfirm={confirm}>
  <div className="cl-pick-preview">{asset.url&&<img src={asset.thumbnail_url||asset.url} alt=""/>}<span>把这张图片登记为本地素材，并作为角色参考图引用。</span></div>
  <div className="cl-pick-mode" role="group" aria-label="加入方式"><button aria-pressed={mode==='existing'} disabled={busy||!list.length} onClick={()=>{setMode('existing');setError('')}}>选择已有角色</button><button aria-pressed={mode==='new'} disabled={busy} onClick={()=>{setMode('new');setError('')}}>新建角色</button></div>
  {!characters?<p role="status">正在载入角色…</p>:mode==='existing'?<ul className="cl-pick" role="radiogroup" aria-label="选择角色">{list.map(c=>{const cover=[...(c.images||[])].sort((a,b)=>(a.position??0)-(b.position??0))[0];return <li key={c.id}><button role="radio" aria-checked={c.id===chosen} disabled={busy||full(c)} aria-label={`${c.name}${full(c)?`（已满 ${CHARACTER_IMAGE_LIMIT} 张）`:''}`} onClick={()=>setChosen(c.id)}>{cover?<img src={cover.thumbnail_url||cover.url} alt="" width={36} height={36} style={{objectFit:'cover',borderRadius:6}}/>:<UserRound size={20} aria-hidden="true"/>}<span>{c.name}</span><small className="ul-muted">{(c.images||[]).length}/{CHARACTER_IMAGE_LIMIT}{full(c)?' · 已满':''}</small></button></li>})}</ul>
  :<><CharacterNameInput autoFocus value={name} error={nameError} onChange={v=>{setName(v);setError('')}} onEnter={confirm}/><CharacterDescriptionInput value={description} onChange={setDescription}/></>}
 </LibraryDialog>
}
