import {useEffect,useRef,useState} from 'react'
import useCharacterLibrary from './useCharacterLibrary'
import {importCharacterAssets} from '../../lib/canvasApi'
import {characterMentionItems,planCharacterInsert,applyCharacterInsert,applyCharacterSync,characterNotices,characterUsage,hasCharacterInBlock,blockCharacterNames,referenceLimitError} from '../../lib/canvasCharacters'
import {canvasMentionItems,referenceMentionIssues} from '../../lib/canvasReferences'

const failureText=error=>error?.response?.data?.error||error?.message||'请求失败'
// CANVAS-LAYOUT-1-20261117: prompt-editing state of the selected node, shared by the card prompt (where @ inserts
// characters) and the right properties panel (where notices, busy state and errors are shown). Split out of the
// retired CanvasNodePanel. CHARACTER-LIBRARY-20261114 race protection is kept as it was: an import compares the
// node text and reference ids before/after (nodeRef/assetsRef). The old panel was re-mounted per node (key), so a
// late import result was dropped after switching nodes; the session counter reproduces that: results that come
// back after the selected node changed (or the editor unmounted) are discarded, and patches go to the node that
// started the import.
export default function useNodeCharacters({node,inputAssets=[],inputIssues=[],provider,workflowId,onPatch}) {
 const enabled=!!node&&['image','video','audio'].includes(node.type)
 const library=useCharacterLibrary(enabled)
 const nodeRef=useRef(node),assetsRef=useRef(inputAssets),session=useRef(0),mounted=useRef(true)
 const [mentionError,setMentionError]=useState(''),[characterBusy,setCharacterBusy]=useState('')
 nodeRef.current=node;assetsRef.current=inputAssets
 const nodeId=node?.id
 useEffect(()=>{session.current+=1;setMentionError('');setCharacterBusy('')},[nodeId])
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
 const live=mine=>mounted.current&&session.current===mine
 const notices=enabled?characterNotices(node,library.characters):[]
 const libraryUnknown=enabled&&!library.characters&&library.error&&Object.values(node.characterRefs||{}).some(ref=>blockCharacterNames(node.text).includes(ref.name))
 async function insertCharacter(item,mention){
  const mine=session.current
  const character=(library.characters||[]).find(entry=>entry.id===item.characterId)
  const fail=message=>{setMentionError(message);return null}
  if(!character)return fail('角色卡已不在角色卡库中，请重新选择')
  const before=nodeRef.current,beforeIds=assetsRef.current.map(asset=>asset.id).join(',')
  if(hasCharacterInBlock(before.text,character.name)){const result=applyCharacterInsert({node:before,assets:assetsRef.current,character,caret:mention});setMentionError('');onPatch(before.id,result.patch);return result.cursor}
  if(!workflowId)return fail('画布尚未载入，未插入角色卡')
  const plan=planCharacterInsert({node:before,assets:assetsRef.current,provider,character})
  if(plan.error)return fail(`未插入：${plan.error}`)
  setCharacterBusy(character.name)
  try{
   const imported=plan.imageIds.length||plan.voice?await importCharacterAssets(workflowId,character.id,plan):{assets:[],voice:null}
   if(!live(mine))return null
   if(nodeRef.current.text!==before.text||assetsRef.current.map(asset=>asset.id).join(',')!==beforeIds)return fail(`导入期间提示词或参考已变化，未插入角色卡“${character.name}”；请重新选择（已导入的素材保留在画布中）`)
   const result=applyCharacterInsert({node:nodeRef.current,assets:assetsRef.current,character,imported,caret:mention})
   setMentionError('');onPatch(before.id,result.patch);return result.cursor
  }catch(error){return live(mine)?fail(`未插入角色卡“${character.name}”：${failureText(error)}`):null}finally{if(live(mine))setCharacterBusy('')}
 }
 async function syncCharacter(id){
  const mine=session.current
  const character=(library.characters||[]).find(entry=>entry.id===id)
  if(!character||!workflowId||!node)return
  const usage=characterUsage(node.type,character),before=nodeRef.current
  setCharacterBusy(character.name);setMentionError('')
  try{
   const imported=usage.images.length||usage.voice?await importCharacterAssets(workflowId,id,{imageIds:usage.images.map(image=>image.asset_id),voice:usage.voice}):{assets:[],voice:null}
   if(!live(mine))return
   if(nodeRef.current.text!==before.text)throw new Error('同步期间提示词已变化，请重试')
   const result=applyCharacterSync({node:nodeRef.current,assets:assetsRef.current,character,imported}),limit=referenceLimitError(before,result.assets,provider)
   if(limit)throw new Error(`同步后超出参考上限：${limit}`)
   onPatch(before.id,result.patch)
  }catch(error){if(live(mine))setMentionError(`未同步角色卡“${character.name}”：${failureText(error)}`)}finally{if(live(mine))setCharacterBusy('')}
 }
 const dismissCharacter=id=>{if(!node)return;const {[id]:_,...rest}=node.characterRefs||{};onPatch(node.id,{characterRefs:Object.keys(rest).length?rest:undefined})}
 const mentionItems=node?[...canvasMentionItems(node,inputAssets),...(enabled?characterMentionItems(library.characters||[]):[])]:[]
 const mentionIssues=node?[...new Set([...referenceMentionIssues(node,inputAssets),...inputIssues.filter(issue=>issue.startsWith('提及')||issue.includes('已在素材库中删除'))])]:[]
 // Same rules as the old panel textarea: characters go through the guarded import; re-pointing a stale
 // positional mention must first delete the old token.
 function onMentionSelect(item,mention){
  if(item.type==='character')return characterBusy?Promise.resolve(null):insertCharacter(item,mention)
  if(node.referenceMentions?.[item.token]&&node.referenceMentions[item.token]!==item.assetId&&node.text?.includes(item.token)){setMentionError(`请先删除原来的失效提及 ${item.token}，再选择新素材`);return false}
 }
 return {nodeId,mentionItems,mentionIssues,mentionError,setMentionError,characterBusy,notices,libraryUnknown,syncCharacter,dismissCharacter,onMentionSelect}
}
