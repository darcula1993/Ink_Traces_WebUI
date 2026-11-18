import React from 'react'
import {Music,Video,ImageIcon} from 'lucide-react'
// Browsing a library never downloads original video/audio to manufacture a thumbnail.
export default React.memo(function LibraryThumbnail({asset,thumbnail,compact=false}){
 if(thumbnail)return <img src={thumbnail} alt="" loading="lazy" decoding="async"/>

 const Icon=asset.kind==='video'?Video:asset.kind==='image'?ImageIcon:Music
 if(compact)return <Icon size={22} aria-hidden="true"/>
 return <span className="ul-audio" aria-label={asset.kind==='video'?'视频素材':asset.kind==='image'?'图片素材':'音频素材'}><Icon size={40} strokeWidth={1.4} aria-hidden="true"/><small>{asset.kind==='video'?'视频':asset.kind==='image'?'图片':'音频'}</small></span>
})
