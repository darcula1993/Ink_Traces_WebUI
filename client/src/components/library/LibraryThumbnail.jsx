import React,{useEffect,useState} from 'react'
import {Music,Video,ImageIcon} from 'lucide-react'
import {AudioWaveformArt} from '../art/CanvasLibraryArt'
// Browsing a library never downloads original video/audio to manufacture a thumbnail.
// Image and video items render their server-generated 320px WebP thumbnail; if unavailable (e.g. 404), fall back to the icon.
export default React.memo(function LibraryThumbnail({asset,thumbnail,compact=false}){
 const [failed,setFailed]=useState(false)
 useEffect(()=>{setFailed(false)},[thumbnail])
 if(thumbnail&&!failed)return <img src={thumbnail} alt="" loading="lazy" decoding="async" onError={()=>setFailed(true)}/>

 const Icon=asset.kind==='video'?Video:asset.kind==='image'?ImageIcon:Music
 if(compact)return <Icon size={22} aria-hidden="true"/>
 if(asset.kind==='audio')return <span className="ul-audio ul-audio-art" aria-label="音频素材"><AudioWaveformArt variant="card"/><small className="ul-audio-label">音频</small></span>
 return <span className="ul-audio" aria-label={asset.kind==='video'?'视频素材':'图片素材'}><Icon size={40} strokeWidth={1.4} aria-hidden="true"/><small>{asset.kind==='video'?'视频':'图片'}</small></span>
})
