import React,{useEffect,useRef,useState} from 'react'
import {Music} from 'lucide-react'
export default function LibraryThumbnail({asset,thumbnail}){
 const ref=useRef(null),[visible,setVisible]=useState(false)
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)){setVisible(true);observer.disconnect()}},{rootMargin:'60px'});if(ref.current)observer.observe(ref.current);return()=>observer.disconnect()},[asset.url])
 return asset.kind==='image'?<img src={thumbnail||asset.url} alt="" loading="lazy"/>:asset.kind==='video'?<div className="ul-video-thumb" ref={ref}>{visible&&<video src={asset.url} poster={thumbnail||undefined} muted preload="metadata" onLoadedMetadata={e=>{const v=e.currentTarget;if(!thumbnail&&Number.isFinite(v.duration)&&v.duration>0)v.currentTime=Math.min(.05,v.duration/2)}}/>}</div>:<span className="ul-audio" aria-label="音频素材"><Music size={40} strokeWidth={1.4} aria-hidden="true"/><small>音频</small></span>
}
