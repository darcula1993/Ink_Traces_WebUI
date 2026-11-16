import {useCallback,useEffect,useRef,useSyncExternalStore} from 'react'
import {documentMediaIds,deletedMediaIds,onDeletedMediaChange,isDeletedMedia} from '../../lib/canvasMediaStatus'
import {deletedAmong} from '../../lib/canvasMedia'
// LIBRARY-GLOBAL-20261116 S5: ask the library (lookup) once per referenced media id whether it was
// deleted; deleted ones render as "已删除" placeholders and block generation. Runtime only, never saved.
const snapshot=()=>deletedMediaIds().sort().join(',')
export default function useCanvasMediaStatus(document){
 const deletedKey=useSyncExternalStore(onDeletedMediaChange,snapshot,snapshot),checked=useRef(new Set()),ids=documentMediaIds(document),key=ids.join(',')
 useEffect(()=>{
  const pending=ids.filter(id=>!checked.current.has(id)&&!isDeletedMedia(id))
  if(!pending.length)return
  for(const id of pending)checked.current.add(id)
  deletedAmong(pending).catch(()=>{for(const id of pending)checked.current.delete(id)})
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[key])
 // After a library deletion, a failed media load, or a refused submit: ask again.
 const recheck=useCallback(list=>{const targets=(list||documentMediaIds(document)).filter(id=>!isDeletedMedia(id));if(targets.length)return deletedAmong(targets).catch(()=>[]);return Promise.resolve([])},[document])
 return {deletedKey,recheck}
}
