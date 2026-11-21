import React, {useEffect,useLayoutEffect,useRef,useState} from 'react'
export default function CanvasContextMenu({position,bounds,onUpload,onCreate,onOpenTemplates,templatesDisabled=false,canPaste=false,onPaste,organizeDisabled=false,onOrganize,fitDisabled=false,onFit,onClose,onDismiss}) {
 const [expanded,setExpanded]=useState(false),ref=useRef(null),[size,setSize]=useState({width:220,height:180})
 useLayoutEffect(()=>{ref.current?.querySelector('button:not(:disabled)')?.focus();const observer=new ResizeObserver(([entry])=>setSize({width:entry.borderBoxSize?.[0]?.inlineSize || 220,height:entry.borderBoxSize?.[0]?.blockSize || 180}));observer.observe(ref.current);return()=>observer.disconnect()},[])
 useLayoutEffect(()=>{const rect=ref.current.getBoundingClientRect();setSize({width:rect.width,height:rect.height})},[expanded])
 useEffect(()=>{const dismiss=e=>{if(!ref.current?.contains(e.target))onDismiss()};document.addEventListener('pointerdown',dismiss);return()=>document.removeEventListener('pointerdown',dismiss)},[onDismiss])
 function keydown(e){e.stopPropagation();if(e.key==='Escape'){e.preventDefault();onClose();return}const items=[...ref.current.querySelectorAll('button:not(:disabled)')],i=items.indexOf(document.activeElement);if(!items.length)return;if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();items[e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus()}if(e.key==='Tab'){e.preventDefault();items[(i+(e.shiftKey?-1:1)+items.length)%items.length]?.focus()}}
 return <div ref={ref} role="menu" aria-label="画布操作" className="cv-context-menu" style={{maxHeight:bounds.height-16,overflowY:'auto',left:Math.max(8,Math.min(position.x,bounds.width-size.width-8)),top:Math.max(8,Math.min(position.y,bounds.height-size.height-8))}} onPointerDown={e=>e.stopPropagation()} onContextMenu={e=>e.preventDefault()} onKeyDown={keydown}>
  <button role="menuitem" onClick={onUpload}>上传</button>
  <button role="menuitem" aria-expanded={expanded} onClick={()=>setExpanded(value=>!value)}>新建节点 <span>›</span></button>
  {expanded && <div role="group" aria-label="生成节点类型">{[['image','图像'],['video','视频'],['audio','音频']].map(([type,label])=><button role="menuitem" key={type} onClick={()=>onCreate(type)}>{label}生成节点</button>)}</div>}
  {onOpenTemplates&&<button role="menuitem" disabled={templatesDisabled} aria-haspopup="dialog" title="从已保存的节点组结构模板添加到当前位置" onClick={onOpenTemplates}>从模板添加</button>}
  {onPaste&&<button role="menuitem" disabled={!canPaste} title={canPaste?'粘贴已复制的节点到此位置':'剪贴板中没有可粘贴的节点'} onClick={onPaste}>粘贴</button>}
  {(onOrganize||onFit)&&<hr className="cv-context-sep"/>}
  {onOrganize&&<button role="menuitem" disabled={organizeDisabled} title={organizeDisabled?'当前画布没有可整理的节点或正在操作中':'自动整理画布节点布局'} onClick={onOrganize}>整理布局</button>}
  {onFit&&<button role="menuitem" disabled={fitDisabled} title={fitDisabled?'当前画布没有节点':'缩放并居中显示全部节点'} onClick={onFit}>适应视口</button>}
 </div>
}
