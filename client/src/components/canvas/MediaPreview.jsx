import React,{useEffect,useRef,useState} from 'react'
import {ChevronLeft,ChevronRight,Download} from 'lucide-react'
import MediaPlayer from './MediaPlayer'
import './canvasFeedback.css'
import './previewNav.css'
import {localDownloadPath} from './previewPages.js'
export {previewItems} from './previewPages.js'
// FIX-B2B-20261114: images open fitted to the window; "原始大小" or the slider switch to a fixed
// scale relative to the image's own pixels (100% = natural size, no longer 100% of the box width).
export default function MediaPreview({asset,onClose}) {
 const items=asset.items?.length?asset.items:[asset],total=items.length
 const [index,setIndex]=useState(()=>Math.max(0,items.findIndex(item=>item.id===asset.id&&item.url===asset.url)))
 const current={...items[Math.min(index,total-1)]}
 if(!current.kind)current.kind=asset.kind
 const ref=useRef(null),[zoom,setZoom]=useState(100),[fit,setFit]=useState(true),[natural,setNatural]=useState(null),[error,setError]=useState('')
 useEffect(()=>{const previous=document.activeElement;ref.current.focus();return()=>{previous?.isConnected&&previous.focus()}},[])
 useEffect(()=>{
  const element=ref.current.querySelector('.cv-preview-content :is(video,audio)')
  // StrictMode replays setup after cleanup using the same media DOM node.
  // Restore the source that cleanup released before this setup starts playback.
  if(element && element.getAttribute('src')!==current.url){element.setAttribute('src',current.url);element.load()}
  // Paging (or closing) stops the previous video/audio before the next one starts.
  return()=>{if(element){element.pause();element.removeAttribute('src');element.load()}}
 },[current.url])
 // ada sign-off: each page opens fitted to the window again.
 function go(step){const next=index+step;if(next<0||next>=total)return;setIndex(next);setNatural(null);setError('');setFit(true);setZoom(100)}
 function keys(e){
  e.stopPropagation()
  if(e.key==='Escape'){e.preventDefault();onClose()}
  // Range inputs (zoom, media progress/volume) keep their own arrow keys.
  if((e.key==='ArrowLeft'||e.key==='ArrowRight')&&total>1&&!e.target.matches?.('input')){e.preventDefault();go(e.key==='ArrowLeft'?-1:1)}
  if(e.key==='Tab'){const list=[...ref.current.querySelectorAll('button:not(:disabled),input,a[href]')];if(e.shiftKey && [ref.current,list[0]].includes(document.activeElement)){e.preventDefault();list.at(-1)?.focus()}else if(!e.shiftKey&&document.activeElement===list.at(-1)){e.preventDefault();list[0]?.focus()}}
 }
 const download=localDownloadPath(current.url),name=current.name||'素材'
 return <div className="cv-media-overlay"><section ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label="素材预览" className="cv-media-viewer" onKeyDown={keys}>
  <header><strong className="cv-preview-title" title={name}>{name}</strong><div className="cv-preview-actions">
   {total>1&&<div className="cv-preview-nav" role="group" aria-label="翻页">
    <button type="button" className="cv-preview-step" aria-label="上一张" title="上一张（←）" disabled={index===0} onClick={()=>go(-1)}><ChevronLeft size={16} aria-hidden="true"/></button>
    <span className="cv-preview-count" role="status" aria-label={`第 ${index+1} 张，共 ${total} 张`}>{index+1} / {total}</span>
    <button type="button" className="cv-preview-step" aria-label="下一张" title="下一张（→）" disabled={index===total-1} onClick={()=>go(1)}><ChevronRight size={16} aria-hidden="true"/></button>
   </div>}
   {download?<a className="cv-preview-download" href={download} download={name} aria-label={`下载 ${name}`} title="下载当前文件"><Download size={14} aria-hidden="true"/>下载</a>:<button type="button" className="cv-preview-download" disabled aria-label="下载不可用" title="该文件不在本站存储，无法从预览下载"><Download size={14} aria-hidden="true"/>下载</button>}
   <button type="button" className="cv-preview-close" onClick={onClose} aria-label="关闭素材预览">关闭</button>
  </div></header>
  {(current.previewNotice||(!asset.items?.length&&asset.previewNotice))&&<p role="status">{current.previewNotice||asset.previewNotice}</p>}
  {current.kind==='image'&&<div className="cv-preview-zoom"><button type="button" aria-pressed={fit} title="按窗口大小完整显示图片" onClick={()=>setFit(true)}>适应窗口</button><button type="button" aria-pressed={!fit&&zoom===100} title="按原始像素显示" onClick={()=>{setFit(false);setZoom(100)}}>原始大小</button><label>缩放<input aria-label="预览缩放" type="range" min="25" max="300" value={zoom} onChange={e=>{setFit(false);setZoom(Number(e.target.value))}}/><output aria-live="off">{fit?'适应':`${zoom}%`}</output></label></div>}
  <div className="cv-preview-content" key={current.id||current.url}>{current.kind==='image'?<img src={current.url} alt={name} className={fit?'cv-preview-img-fit':undefined} data-fit={fit?'true':undefined} style={fit?undefined:{width:natural?`${natural*zoom/100}px`:`${zoom}%`,maxWidth:'none'}} onLoad={e=>setNatural(e.currentTarget.naturalWidth||null)} onError={()=>setError('图片加载失败')}/>:current.kind==='video'?<MediaPlayer kind="video" src={current.url} title={name} autoPlay onFail={()=>setError('视频播放失败，浏览器可能不支持此格式；可下载后查看')}/>:<MediaPlayer kind="audio" src={current.url} title={name} autoPlay onFail={()=>setError('音频播放失败，浏览器可能不支持此格式；可下载后查看')}/>}</div>
  {error&&<p role="alert">{error}</p>}
 </section></div>
}
