import React,{useEffect,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import Select from '../ui/Select'
import {listMediaFolders,createMediaFolder,moveMedia,lookupMedia,moveTargets,folderPath,isSystemFolder} from '../../lib/canvasMedia'
import {isMediaAsset} from '../../lib/canvasMediaStatus'
// LIBRARY-GLOBAL-20261116 S5 (replaces "加入本地素材"): results and versions already are library
// media, so the node menu only changes their folder (folder_id), with an inline "新建文件夹".
// Old canvas assets resolve through their library alias; unknown ones are reported, not copied.
export async function resolveAssetMedia(assets){
 const direct=assets.filter(isMediaAsset),legacy=assets.filter(asset=>!isMediaAsset(asset)&&asset?.url)
 const found=legacy.length?await lookupMedia(legacy.map(asset=>asset.url)):new Map()
 const media=[...direct.map(asset=>({id:asset.id,kind:asset.kind,name:asset.name})),...legacy.flatMap(asset=>{const item=found.get(asset.url);return item?.status==='ok'?[{id:item.media_id,kind:item.media.kind,name:item.media.name}]:[]})]
 const unique=[...new Map(media.map(item=>[item.id,item])).values()]
 return {media:unique,skipped:assets.length-direct.length-legacy.filter(asset=>found.get(asset.url)?.status==='ok').length}
}
export default function MoveToFolderDialog({assets,title='移动到文件夹',onClose,onDone}){
 const ref=useRef(null),[folders,setFolders]=useState(null),[media,setMedia]=useState(null),[skipped,setSkipped]=useState(0),[target,setTarget]=useState(''),[creating,setCreating]=useState(false),[name,setName]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('')
 useEffect(()=>{let alive=true;Promise.all([listMediaFolders(),resolveAssetMedia(assets)]).then(([list,resolved])=>{if(!alive)return;setFolders(list);setMedia(resolved.media);setSkipped(resolved.skipped)}).catch(e=>{if(alive)setError(e?.response?.data?.error||e.message||'无法读取素材库')});return()=>{alive=false}},[])
 useEffect(()=>{ref.current?.focus()},[])
 const kinds=[...new Set((media||[]).map(item=>item.kind))],targets=folders?moveTargets(folders,kinds):[]
 const parentOk=!target||!isSystemFolder(folders?.find(f=>f.id===target))
 async function run(operation){setBusy(true);setError('');try{await operation()}catch(e){setError(e?.response?.data?.error||e.message||'操作失败')}finally{setBusy(false)}}
 const create=()=>run(async()=>{const folder=await createMediaFolder(name.trim(),parentOk?target||null:null);setFolders(list=>[...list,{...folder,media_count:0}]);setTarget(folder.id);setCreating(false);setName('')})
 const confirm=()=>run(async()=>{await moveMedia(media.map(item=>item.id),target||null);const label=target?folderPath(folders,target):'根目录';onDone?.(`已将 ${media.length} 个素材移动到“${label}”${skipped?`；${skipped} 个尚未进入素材库，未移动`:''}`)})
 const ready=folders&&media
 return createPortal(<div className="canvas-studio cv-tree-editor-portal"><div className="cv-studio-overlay"><section className="cv-tree-editor cv-move-dialog" ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} onPointerDown={e=>e.stopPropagation()} onKeyDown={e=>{e.stopPropagation();if(e.key==='Escape'&&!busy)onClose()}}>
  <h3>{title}</h3>
  {!ready&&!error&&<p role="status">正在读取素材库…</p>}
  {ready&&!media.length&&<p role="alert">该结果尚未进入素材库（等待迁移），暂不能移动</p>}
  {ready&&media.length>0&&<>
   <p className="cv-move-summary">{media.length===1?`“${media[0].name}”`:`${media.length} 个素材`}已在素材库中；移动只改变所在文件夹，画布引用不变。{skipped?`另有 ${skipped} 个尚未进入素材库。`:''}</p>
   <label>目标文件夹<Select ariaLabel="目标文件夹" disabled={busy} value={target} onChange={setTarget} options={[{value:'',label:'根目录'},...targets.map(f=>({value:f.id,label:folderPath(folders,f.id)}))]}/></label>
   {creating?<label>新文件夹名称<span className="cv-move-create"><input autoFocus aria-label="新文件夹名称" maxLength={240} value={name} disabled={busy} placeholder={parentOk&&target?`建在“${folderPath(folders,target)}”下`:'建在根目录'} onChange={e=>setName(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&name.trim()&&!busy){e.preventDefault();create()}}}/><button disabled={busy||!name.trim()} onClick={create}>创建</button><button disabled={busy} onClick={()=>{setCreating(false);setName('')}}>取消</button></span></label>:<button className="cv-move-new" disabled={busy} onClick={()=>setCreating(true)}>新建文件夹</button>}
  </>}
  {error&&<p role="alert">{error}</p>}
  <footer><button disabled={busy} onClick={onClose}>取消</button><button className="btn btn-primary" disabled={busy||!ready||!media?.length||creating} onClick={confirm}>移动</button></footer>
 </section></div></div>,document.body)
}
