import React,{useState} from 'react'
import UnifiedAssetLibrary from './UnifiedAssetLibrary'
import CupsyLibrary from './CupsyLibrary'
import {normalizeLibrarySource} from './librarySources'
export default function ToolAssetLibrary({onClose,onApply,onRemoteApply,remote=true,initialSource='local',...props}){
 const [source,setSource]=useState(()=>normalizeLibrarySource(initialSource)),[showRemote,setShowRemote]=useState(false)
 return showRemote?<CupsyLibrary {...props} onApply={onRemoteApply||onApply} onClose={onClose} onLocal={value=>{setSource(normalizeLibrarySource(value));setShowRemote(false)}}/>:<UnifiedAssetLibrary {...props} initialSource={source} onApply={onApply} onClose={onClose} onRemote={remote?()=>setShowRemote(true):undefined}/>
}
