import React,{useEffect,useRef} from 'react'
export default function SidebarNameDialog({kind='节点',draft,onChange,onSave,onClose}) {
 const ref=useRef(null)
 useEffect(()=>{ref.current.querySelector('input').focus()},[])
 return <div className="cv-studio-overlay"><div ref={ref} role="dialog" aria-modal="true" aria-label={`重命名${kind}`} onKeyDown={e=>{e.stopPropagation();if(e.key==='Escape')onClose();if(e.key==='Tab'){const items=[...ref.current.querySelectorAll('input,button:not(:disabled)')];if(e.shiftKey&&document.activeElement===items[0]){e.preventDefault();items.at(-1).focus()}else if(!e.shiftKey&&document.activeElement===items.at(-1)){e.preventDefault();items[0].focus()}}}}><h3>重命名{kind}</h3><input aria-label={`${kind}名称`} maxLength={kind==='节点组'?100:240} value={draft.title} onChange={e=>onChange({...draft,title:e.target.value})}/><p/><button onClick={onClose}>取消</button><button disabled={!draft.title.trim()} onClick={onSave}>保存{kind}名称</button></div></div>
}
