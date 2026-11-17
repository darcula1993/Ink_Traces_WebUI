import React,{useEffect,useState} from 'react'
import MoveToFolderDialog from '../library/MoveToFolderDialog'
import LibraryDialog from '../library/LibraryDialog'
import {lookupMedia} from '../../lib/canvasMedia'
import {isMediaAsset} from '../../lib/canvasMediaStatus'
// LIBRARY-OPS-FIX2-20261117 R3: canvas "移动到文件夹" uses the library's MoveToFolderDialog (starts at the media's
// current folder; "生成历史" disabled for non-generated media). This adapter only maps canvas node assets to library
// media ids: old canvas assets resolve through their library alias; unknown ones are reported, not copied.
export async function resolveAssetMedia(assets){
 const direct=assets.filter(isMediaAsset),legacy=assets.filter(asset=>!isMediaAsset(asset)&&asset?.url)
 const found=legacy.length?await lookupMedia(legacy.map(asset=>asset.url)):new Map()
 const media=[...direct.map(asset=>({id:asset.id})),...legacy.flatMap(asset=>{const item=found.get(asset.url);return item?.status==='ok'?[{id:item.media_id}]:[]})]
 const unique=[...new Map(media.map(item=>[item.id,item])).values()]
 return {media:unique,skipped:assets.length-unique.length}
}
export default function CanvasMoveToFolder({assets,onClose,onDone}){
 const [resolved,setResolved]=useState(null),[error,setError]=useState('')
 useEffect(()=>{let alive=true;resolveAssetMedia(assets).then(r=>{if(alive)setResolved(r)}).catch(e=>{if(alive)setError(e?.response?.data?.error||e?.message||'无法读取素材库')});return()=>{alive=false}},[])
 if(resolved?.media.length)return <MoveToFolderDialog media={resolved.media} onClose={onClose} onDone={outcome=>onDone?.(`${outcome.text}${resolved.skipped?`；${resolved.skipped} 个尚未进入素材库，未移动`:''}`,outcome)}/>
 return <LibraryDialog title="移动到文件夹" error={error} onClose={onClose}>{resolved?<p role="alert">该结果尚未进入素材库（等待迁移），暂不能移动</p>:!error&&<p role="status">正在读取素材库…</p>}</LibraryDialog>
}
