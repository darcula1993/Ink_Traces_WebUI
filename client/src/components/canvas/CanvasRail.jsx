import React,{useCallback,useEffect,useRef,useState} from 'react'
import {FolderKanban,Images,Users,Library,ListChecks,CircleHelp,Pin,PinOff,X} from 'lucide-react'
import ResizableSidebar from './ResizableSidebar'
import {RAIL_ITEMS,RAIL_PANEL_IDS,RAIL_PANEL_MAX,RAIL_PANEL_MIN,railFocusIndex,railPanelDefaultWidth,readRailPreference,writeRailPreference} from './canvasChrome'
import './canvasChrome.css'

const ICONS={project:FolderKanban,assets:Images,characters:Users,prompts:Library,tasks:ListChecks}
const SHORT_LABELS={project:'画布',assets:'素材',characters:'角色',prompts:'提示词',tasks:'任务'}
export const RAIL_PANEL_TITLES=Object.fromEntries(RAIL_ITEMS.map(item=>[item.id,item.label]))
const panelDomId=id=>`cv-rail-panel-${id}`

// CANVAS-LAYOUT-2-20261118: rail state. One panel at a time; pinned + panel persist in localStorage
// (never an unpinned one). `open(id,{focus})` from the rail moves focus into the panel; restoring a pinned
// panel after reload does not. `canPin()` may return a refusal message (spec 1.5: canvas would be < 640).
export function useCanvasRail({canPin}={}) {
 const [state,setState]=useState(()=>{const saved=readRailPreference();return {panel:saved.panel,pinned:saved.pinned,focus:false}})
 const iconRefs=useRef({})
 useEffect(()=>{writeRailPreference(state)},[state.panel,state.pinned])
 const focusIcon=useCallback(id=>{requestAnimationFrame(()=>iconRefs.current[id]?.focus({preventScroll:true}))},[])
 const open=useCallback((id,{focus=true}={})=>{if(RAIL_PANEL_IDS.includes(id))setState(current=>({...current,panel:id,focus}))},[])
 const toggle=useCallback(id=>setState(current=>current.panel===id?{...current,panel:null,focus:false}:{...current,panel:id,focus:true}),[])
 const stateRef=useRef(state);stateRef.current=state
 const close=useCallback(({returnFocus=false}={})=>{const panel=stateRef.current.panel;if(returnFocus&&panel)focusIcon(panel);setState(current=>({...current,panel:null,focus:false}))},[focusIcon])
 const togglePin=useCallback(()=>{
  if(!state.pinned){const refusal=canPin?.();if(refusal)return refusal}
  setState(current=>({...current,pinned:!current.pinned,focus:false}));return null
 },[state.pinned,canPin])
 const consumeFocus=useCallback(()=>setState(current=>current.focus?{...current,focus:false}:current),[])
 return {panel:state.panel,pinned:state.pinned,autoFocus:state.focus,open,toggle,close,togglePin,consumeFocus,iconRefs,focusIcon}
}

// Vertical icon rail (48px). Props: active (panel id|null), onToggle(id), onCharacters(),
// onShortcuts(), iconRefs (from useCanvasRail), badges {tasks: n} (optional).
// P1-CANVAS-WORKFLOW-20261120 (P2): pin/unpin button lives only in CanvasRailPanel's header (no duplicate rail entry).
export default function CanvasRail({active=null,onToggle,onCharacters,onShortcuts,iconRefs,badges={},disabled={}}) {
 const [focusIndex,setFocusIndex]=useState(0),bar=useRef(null)
 const entries=[...RAIL_ITEMS.map(item=>({...item,Icon:ICONS[item.id]})),{id:'shortcuts',label:'快捷键帮助',kind:'action',Icon:CircleHelp,bottom:true}]
 const onKeyDown=event=>{
  const all=[...bar.current.querySelectorAll('button[data-rail-item]')],buttons=all.filter(button=>!button.disabled),index=buttons.indexOf(document.activeElement),next=railFocusIndex(index<0?Math.max(0,buttons.indexOf(all[focusIndex])):index,buttons.length,event.key)
  if(next==null)return
  event.preventDefault();event.stopPropagation();setFocusIndex(all.indexOf(buttons[next]));buttons[next]?.focus()
 }
 const run=entry=>{
  if(entry.kind==='panel')onToggle?.(entry.id)
  else if(entry.id==='characters')onCharacters?.()
  else if(entry.id==='shortcuts')onShortcuts?.()
 }
 const button=(entry,index)=>{
  const isPanel=entry.kind==='panel',isActive=isPanel&&active===entry.id,shortLabel=SHORT_LABELS[entry.id]
  return <button key={entry.id} type="button" data-rail-item={entry.id} ref={el=>{if(iconRefs&&isPanel)iconRefs.current[entry.id]=el}}
   className={`cv-rail-button${shortLabel?' has-label':''}${isActive?' is-active':''}`} aria-label={entry.label} title={entry.label}
   tabIndex={index===focusIndex?0:-1} onFocus={()=>setFocusIndex(index)}
   {...(isPanel?{'aria-expanded':isActive,'aria-controls':isActive?panelDomId(entry.id):undefined}:{})}
   disabled={disabled[entry.id]} onClick={()=>run(entry)}>
   <span className="cv-rail-icon" aria-hidden="true"><entry.Icon size={shortLabel?17:16} aria-hidden="true"/></span>
   {shortLabel&&<span className="cv-rail-label" aria-hidden="true">{shortLabel}</span>}
   {badges[entry.id]>0&&<span className="cv-rail-badge" aria-hidden="true">{badges[entry.id]>99?'99+':badges[entry.id]}</span>}
  </button>
 }
 return <nav ref={bar} className="cv-rail" role="toolbar" aria-orientation="vertical" aria-label="画布导航" onKeyDown={onKeyDown}>
  <div className="cv-rail-group">{entries.filter(e=>!e.bottom).map((entry)=>button(entry,entries.indexOf(entry)))}</div>
  <div className="cv-rail-group is-bottom">{entries.filter(e=>e.bottom).map(entry=>button(entry,entries.indexOf(entry)))}</div>
 </nav>
}

const PORTAL_SELECTOR='.cv-sidebar-menu-portal,[role=dialog],[role=alertdialog],[role=menu],.cv-studio-overlay,.cv-media-overlay'
// Pop-out panel next to the rail. Floating (not pinned): glass overlay over the canvas, closes on Esc, on a
// pointerdown outside (rail, panel, menus and dialogs excluded) — never while a drag that started in the
// panel is in progress. Pinned: docked, squeezes the canvas, does not steal focus. Width via ResizableSidebar
// (240–360, key ink-traces.canvas.sidebar-width.v1). Canvas shortcuts do not fire from inside (stopPropagation,
// Ctrl/⌘+S still saves).
export function CanvasRailPanel({id,title=RAIL_PANEL_TITLES[id],pinned=false,autoFocus=false,onFocused,onClose,onTogglePin,pinDisabledReason='',onWidth,children}) {
 const root=useRef(null),dragging=useRef(false)
 const viewport=typeof window!=='undefined'?window.innerWidth:1440
 // Spec 1.5 widths are on-screen px across all desktop viewports (no per-region zoom).
 useEffect(()=>{
  if(!autoFocus)return
  const target=root.current?.querySelector('.cv-rail-panel-body :is(button,input,select,textarea,[tabindex]):not([disabled]):not([tabindex="-1"])')||root.current?.querySelector('.cv-rail-panel-head button')
  target?.focus({preventScroll:true});onFocused?.()
 },[id,autoFocus])
 useEffect(()=>{
  if(pinned)return undefined
  const outside=event=>{
   if(dragging.current)return
   const target=event.target
   if(!(target instanceof Element)||root.current?.contains(target)||target.closest('.cv-rail-panel-shell,.cv-sidebar-resizer,.cv-rail,[data-canvas-rail-toggle]')||target.closest(PORTAL_SELECTOR))return
   onClose?.({returnFocus:false,reason:'outside'})
  }
  const start=event=>{if(root.current?.contains(event.target))dragging.current=true}
  const stop=()=>{dragging.current=false}
  document.addEventListener('pointerdown',outside,true);document.addEventListener('dragstart',start,true);document.addEventListener('dragend',stop,true);document.addEventListener('drop',stop,true)
  return ()=>{document.removeEventListener('pointerdown',outside,true);document.removeEventListener('dragstart',start,true);document.removeEventListener('dragend',stop,true);document.removeEventListener('drop',stop,true)}
 },[pinned,onClose])
 const onKeyDown=event=>{
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s')return
  if(event.key==='F6')return // region cycling (spec 1.4) is handled by the canvas
  if(event.key==='Escape'&&!event.defaultPrevented){event.preventDefault();onClose?.({returnFocus:true,reason:'escape'})}
  event.stopPropagation()
 }
 return <ResizableSidebar className={`cv-rail-panel-shell ${pinned?'is-pinned':'is-floating'}`} minWidth={RAIL_PANEL_MIN} maxWidth={RAIL_PANEL_MAX} defaultWidth={railPanelDefaultWidth(viewport)} reserve={pinned?640:240} label={`调整${title}面板宽度`} onWidth={onWidth}>
  <section ref={root} id={panelDomId(id)} className="cv-rail-panel" data-panel={id} data-panel-bounds="" aria-label={title} onKeyDown={onKeyDown}>
   <header className="cv-rail-panel-head"><h2>{title}</h2>
    <button type="button" className="btn btn-ghost btn-sm btn-icon" aria-label={pinned?'取消钉住面板':'钉住面板'} aria-pressed={pinned} title={pinDisabledReason||(pinned?'取消钉住（改为浮层）':'钉住（停靠在左侧，挤压画布）')} disabled={!!pinDisabledReason&&!pinned} onClick={onTogglePin}>{pinned?<PinOff size={14} aria-hidden="true"/>:<Pin size={14} aria-hidden="true"/>}</button>
    <button type="button" className="btn btn-ghost btn-sm btn-icon" aria-label={`关闭${title}`} title="关闭 (Esc)" onClick={()=>onClose?.({returnFocus:true,reason:'button'})}><X size={14} aria-hidden="true"/></button>
   </header>
   <div className="cv-rail-panel-body cv-sidebar">{children}</div>
  </section>
 </ResizableSidebar>
}
