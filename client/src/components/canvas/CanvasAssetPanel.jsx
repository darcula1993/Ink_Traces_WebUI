import React,{useState} from 'react'
import AssetTree from './AssetTree'

// CANVAS-LAYOUT-2-20261118: rail panel "素材库" — the full AssetTree (folders, upload to folder, duplicate
// notice, drag onto the canvas, add as reference, manage/characters entries) plus the item count.
export default function CanvasAssetPanel({revealMedia=null,uploadFolder=null,onUploadFolder,assetRefresh,mediaRefresh=0,onLibrary,onCharacters,onAddAssets,onAddReference,referenceTarget,disabled,ioBusy,footer=true}) {
 const [count,setCount]=useState(null)
 return <div className="cv-panel-assets"><AssetTree onCount={setCount} reveal={revealMedia} uploadFolder={uploadFolder} onUploadFolder={onUploadFolder} refresh={assetRefresh} contentRefresh={mediaRefresh} onManage={onLibrary} onCharacters={onCharacters} onAddAssets={onAddAssets} onAddReference={onAddReference} referenceTarget={referenceTarget} disabled={disabled} ioBusy={ioBusy}/>
 {footer&&<footer className="cv-panel-footer"><span>{count==null?'正在读取素材…':`共 ${count} 项素材`}</span></footer>}</div>
}
