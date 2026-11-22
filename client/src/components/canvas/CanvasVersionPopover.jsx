import React,{useEffect,useLayoutEffect,useRef,useState} from 'react'
import {Check,CheckCircle2,Columns2,Music} from 'lucide-react'
import {GENERATION_TYPES,formatVersionParamChips,formatVersionPromptPreview} from '../../lib/canvasVersionSnapshots'

// NODE-TOOLBAR-VERSIONS-20261118 (user 11-18): the one place to switch a node's kept versions (asset, image, video and
// audio generation nodes; the properties panel no longer lists them). Opened from the node toolbar's 历史版本 button
// or the node menu. Each entry: thumbnail + 版本 N (+ time when the asset carries one); the current one is pressed.
// Esc / 关闭 closes; the caller returns focus to where the popover was opened from.
const KIND_LABEL={image:'图片',video:'视频',audio:'音频'}
export function versionTime(asset){
 const raw=asset?.created_at??asset?.createdAt
 if(raw==null||raw==='')return ''
 const date=new Date(typeof raw==='number'&&raw<1e12?raw*1000:raw)
 if(Number.isNaN(date.getTime()))return ''
 const pad=n=>String(n).padStart(2,'0')
 return `${pad(date.getMonth()+1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
// Right of the node's top edge; left of it when there is no room; clamped inside the surface.
export function versionPopoverPlacement(rect,surface,size,{gap=12,margin=8}={}){
 if(!rect||!surface)return {left:margin,top:margin}
 const width=size?.width||0,height=size?.height||0
 let left=rect.left+rect.width+gap
 if(left+width>surface.width-margin)left=rect.left-gap-width
 left=Math.max(margin,Math.min(surface.width-width-margin,left))
 const top=Math.max(margin,Math.min(surface.height-height-margin,rect.top))
 return {left:Math.round(left),top:Math.round(top)}
}

export default function CanvasVersionPopover({node,snapshots={},rect,surface,busy=false,isGone=()=>false,onChoose,onCompare,onToggleFinalized,onClose}){
 const ref=useRef(null),[size,setSize]=useState(null)
 const kind=node.asset?.kind||(node.type==='asset'?'image':node.type),label=`${KIND_LABEL[kind]||''}历史版本`
 const isGeneration=GENERATION_TYPES.has(node.type)
 const candidates=node.candidates||[],currentId=node.asset?.id??node.selectedCandidateId
 const liveCount=candidates.filter(asset=>asset?.id&&!isGone(asset)).length
 const canCompare=Boolean(onCompare)&&liveCount>=2
 const finalized=node.finalized===true
 useLayoutEffect(()=>{const el=ref.current;if(el){const next={width:el.offsetWidth,height:el.offsetHeight};if(!size||size.width!==next.width||size.height!==next.height)setSize(next)}})
 // Focus once the popover is measured and visible (a visibility:hidden element cannot take focus).
 const measured=!!size
 useEffect(()=>{if(!measured)return;const el=ref.current;(el?.querySelector('.cv-version-item[aria-pressed=true]:not(:disabled)')||el?.querySelector('.cv-version-item:not(:disabled)')||el?.querySelector('button'))?.focus({preventScroll:true})},[node.id,measured])
 const place=versionPopoverPlacement(rect,surface,size||{width:0,height:0})
 const onKeyDown=event=>{
  event.stopPropagation()
  if(event.key==='Escape'){event.preventDefault();onClose();return}
  if(['ArrowDown','ArrowUp','ArrowRight','ArrowLeft','Home','End'].includes(event.key)){
   const items=[...ref.current.querySelectorAll('.cv-version-item:not(:disabled)')],index=items.indexOf(document.activeElement)
   if(!items.length)return
   event.preventDefault()
   const next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(['ArrowDown','ArrowRight'].includes(event.key)?1:-1)+items.length)%items.length
   items[next]?.focus()
  }
 }
 return <div ref={ref} className="cv-history-popover cv-version-popover" role="dialog" aria-label={label} data-testid="version-popover" style={{left:place.left,top:place.top,right:'auto',visibility:size?undefined:'hidden'}} onKeyDown={onKeyDown} onPointerDown={e=>e.stopPropagation()} onWheel={e=>e.stopPropagation()}>
  <header>
   <span>历史版本（{candidates.length}）</span>
   <span className="cv-version-header-actions">
    {canCompare&&<button type="button" className="btn btn-secondary btn-sm cv-version-compare-btn" disabled={busy} data-testid="version-popover-compare" title="并排对比 2–4 个候选版本" onClick={()=>onCompare(node.id)}><Columns2 size={13} aria-hidden="true"/>并排对比</button>}
    <button type="button" className="btn btn-ghost btn-sm" aria-label="关闭历史版本" onClick={onClose}>关闭</button>
   </span>
  </header>
  {onToggleFinalized&&<div className="cv-version-final-bar">
   <button type="button" className={`btn btn-sm cv-version-final-toggle ${finalized?'is-finalized':'btn-ghost'}`} disabled={busy} aria-pressed={finalized} data-testid="version-popover-finalize" title={finalized?'取消此节点的定稿标记（可撤销）':'将当前采用版本标为定稿（可撤销）'} onClick={()=>onToggleFinalized(node.id,!finalized)}><CheckCircle2 size={13} aria-hidden="true"/>{finalized?'已定稿 · 取消定稿':'标为定稿'}</button>
  </div>}
  <div className="cv-version-list" role="group" aria-label="保留的版本">
   {candidates.map((asset,index)=>{const gone=isGone(asset),time=versionTime(asset),current=asset.id===currentId,itemKind=asset.kind||kind
    const snapshot=isGeneration?(snapshots?.[asset.id]||node.versionSnapshots?.[asset.id]||null):null
    const paramChips=snapshot?formatVersionParamChips(snapshot,node.type):[]
    const promptPreview=snapshot?formatVersionPromptPreview(snapshot,56):''
    const fullPrompt=typeof snapshot?.text==='string'?snapshot.text.trim():''
    const hasSnapshot=Boolean(snapshot&&(fullPrompt||paramChips.length||snapshot.providerSelection))
    const reason=gone?'该版本已在素材库中删除':busy?'请等待当前操作完成':undefined
    const actionHint=current?'当前版本':(hasSnapshot?`切换到版本 ${index+1}（同步提示词与生成参数）`:`切换到版本 ${index+1}`)
    const itemTitle=reason||(fullPrompt?`${actionHint}\n提示词：${fullPrompt}`:actionHint)
    return <button type="button" key={asset.id} className="cv-version-item" data-version-id={asset.id} disabled={busy||gone} title={itemTitle} aria-label={`版本 ${index+1}`} aria-description={[current?'当前版本':'',current&&finalized?'已定稿':'',time,gone?'已删除':''].filter(Boolean).join('，')||undefined} aria-pressed={current} onClick={()=>onChoose(asset)}>
     <span className="cv-version-thumb">{gone?<span className="cv-history-deleted">已删除</span>:itemKind==='video'?<video src={asset.url} muted preload="metadata" playsInline aria-hidden="true"/>:itemKind==='audio'?<Music size={18} aria-hidden="true"/>:<img src={asset.url} alt="" loading="lazy" draggable={false}/>}</span>
     <span className="cv-version-meta"><b>版本 {index+1}</b>{current&&<small className="cv-version-current">当前</small>}{current&&finalized&&<small className="cv-version-final"><Check size={10} aria-hidden="true"/>定稿</small>}{time&&<small>{time}</small>}{gone&&<small>（已删除）</small>}</span>
     {hasSnapshot&&(paramChips.length>0||promptPreview)&&<span className="cv-version-snapshot" data-testid={`version-snapshot-${asset.id}`}>
      {paramChips.length>0&&<span className="cv-version-params" title={paramChips.join(' · ')}>{paramChips.slice(0,3).map(chip=><span key={chip} className="cv-version-param-chip">{chip}</span>)}</span>}
      {promptPreview&&<span className="cv-version-prompt" title={fullPrompt||promptPreview}>{promptPreview}</span>}
     </span>}
    </button>})}
  </div>
 </div>
}
