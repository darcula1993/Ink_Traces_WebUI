import React, {useRef} from 'react'

export const GROUP_COLORS = {green:'绿色',cyan:'青色',blue:'蓝色',purple:'紫色',amber:'琥珀色',rose:'玫瑰色'}

export default function CanvasGroupColors({group,disabled,onChange,onSummaryPointerDown,variant='canvas'}) {
  const root = useRef(null), colorKey = group.color || 'green'
  function close() { root.current.open=false; root.current.querySelector('summary').focus() }
  return <details ref={root} className={`cv-group-colors ${variant==='panel'?'is-panel':''}`} onPointerDown={event=>event.stopPropagation()} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))event.currentTarget.open=false}} onKeyDown={event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s')return
    event.stopPropagation()
    if(event.key==='Escape'){event.preventDefault();close()}
  }}>
    <summary className={variant==='panel'?'btn btn-secondary btn-sm':undefined} aria-label={`节点组 ${group.title} 的底色`} aria-disabled={disabled||undefined} onPointerDown={onSummaryPointerDown} onClick={event=>{if(disabled)event.preventDefault()}}>{variant==='panel'&&<i className="cv-group-color-dot" data-color={colorKey} aria-hidden="true"/>}底色</summary>
    <div role="group" aria-label="节点组底色" className="cv-group-palette">
      {Object.entries(GROUP_COLORS).map(([color,label])=><button key={color} type="button" disabled={disabled} aria-label={label} aria-pressed={colorKey===color} title={label} data-color={color} onClick={()=>{onChange(group,color,label);close()}}><i aria-hidden="true"/>{label}</button>)}
    </div>
  </details>
}
