import React, {useRef} from 'react'

export const GROUP_COLORS = {green:'绿色',cyan:'青色',blue:'蓝色',purple:'紫色',amber:'琥珀色',rose:'玫瑰色'}

export default function CanvasGroupColors({group,disabled,onChange}) {
  const root = useRef(null)
  function close() { root.current.open=false; root.current.querySelector('summary').focus() }
  return <details ref={root} className="cv-group-colors" onPointerDown={event=>event.stopPropagation()} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))event.currentTarget.open=false}} onKeyDown={event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s')return
    event.stopPropagation()
    if(event.key==='Escape'){event.preventDefault();close()}
  }}>
    <summary aria-label={`节点组 ${group.title} 的底色`} aria-disabled={disabled||undefined} onClick={event=>{if(disabled)event.preventDefault()}}>底色</summary>
    <div role="group" aria-label="节点组底色" className="cv-group-palette">
      {Object.entries(GROUP_COLORS).map(([color,label])=><button key={color} type="button" disabled={disabled} aria-label={label} aria-pressed={(group.color||'green')===color} title={label} data-color={color} onClick={()=>{onChange(group,color,label);close()}}><i aria-hidden="true"/>{label}</button>)}
    </div>
  </details>
}
