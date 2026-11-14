import React,{useEffect,useRef,useState} from 'react'
import MediaPlayer from './MediaPlayer'
import './canvasFeedback.css'
// FIX-B2B-20261114: images open fitted to the window; "原始大小" or the slider switch to a fixed
// scale relative to the image's own pixels (100% = natural size, no longer 100% of the box width).
export default function MediaPreview({asset,onClose}) {
 const ref=useRef(null),media=useRef(null),[zoom,setZoom]=useState(100),[fit,setFit]=useState(true),[natural,setNatural]=useState(null),[error,setError]=useState('')
 useEffect(()=>{
  const previous=document.activeElement,element=ref.current.querySelector('video,audio')
  ref.current.focus()
  // StrictMode replays setup after cleanup using the same media DOM node.
  // Restore the source that cleanup released before this setup starts playback.
  if(element && element.getAttribute('src')!==asset.url){element.setAttribute('src',asset.url);element.load()}
  return()=>{if(element){element.pause();element.removeAttribute('src');element.load()}previous?.isConnected&&previous.focus()}
 },[asset.url])
 function keys(e){e.stopPropagation();if(e.key==='Escape'){e.preventDefault();onClose()}if(e.key==='Tab'){const items=[...ref.current.querySelectorAll('button,input')];if(e.shiftKey && [ref.current,items[0]].includes(document.activeElement)){e.preventDefault();items.at(-1)?.focus()}else if(!e.shiftKey&&document.activeElement===items.at(-1)){e.preventDefault();items[0]?.focus()}}}
 return <div className="cv-media-overlay"><section ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label="素材预览" className="cv-media-viewer" onKeyDown={keys}><header><strong>{asset.name}</strong><button onClick={onClose} aria-label="关闭素材预览">关闭</button></header>{asset.previewNotice&&<p role="status">{asset.previewNotice}</p>}{asset.kind==='image'&&<div className="cv-preview-zoom"><button type="button" aria-pressed={fit} title="按窗口大小完整显示图片" onClick={()=>setFit(true)}>适应窗口</button><button type="button" aria-pressed={!fit&&zoom===100} title="按原始像素显示" onClick={()=>{setFit(false);setZoom(100)}}>原始大小</button><label>缩放<input aria-label="预览缩放" type="range" min="25" max="300" value={zoom} onChange={e=>{setFit(false);setZoom(Number(e.target.value))}}/><output aria-live="off">{fit?'适应':`${zoom}%`}</output></label></div>}<div className="cv-preview-content">{asset.kind==='image'?<img src={asset.url} alt={asset.name} data-fit={fit?'true':undefined} style={fit?{maxWidth:'100%',maxHeight:'70vh',width:'auto',height:'auto',objectFit:'contain',margin:'0 auto'}:{width:natural?`${natural*zoom/100}px`:`${zoom}%`,maxWidth:'none'}} onLoad={e=>setNatural(e.currentTarget.naturalWidth||null)} onError={()=>setError('图片加载失败')}/>:asset.kind==='video'?<MediaPlayer kind="video" src={asset.url} title={asset.name} autoPlay onFail={()=>setError('视频播放失败，浏览器可能不支持此格式；可下载后查看')}/>:<MediaPlayer kind="audio" src={asset.url} title={asset.name} autoPlay onFail={()=>setError('音频播放失败，浏览器可能不支持此格式；可下载后查看')}/>}</div>{error&&<p role="alert">{error}</p>}</section></div>
}
