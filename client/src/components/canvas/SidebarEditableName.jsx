import React,{useEffect,useRef,useState} from 'react'

export default function SidebarEditableName({name,onRename,onClick,children,...props}){
 const [draft,setDraft]=useState(null),[saving,setSaving]=useState(false),[error,setError]=useState('')
 const timer=useRef(null),button=useRef(null),input=useRef(null),pending=useRef(false)
 useEffect(()=>()=>clearTimeout(timer.current),[])
 const finish=(restoreFocus=true)=>{setDraft(null);setError('');if(restoreFocus)requestAnimationFrame(()=>button.current?.focus())}
 const commit=async()=>{
  if(pending.current)return
  if(!draft.trim()){setError('名称不能为空');return}
  pending.current=true;setSaving(true);setError('')
  try{await onRename(draft.trim());finish()}catch(failure){setError(failure?.response?.data?.error||failure.message||'保存失败，请重试');requestAnimationFrame(()=>input.current?.focus())}
  finally{pending.current=false;setSaving(false)}
 }
 if(draft!==null)return <span className="cv-sidebar-name-editor"><input ref={input} autoFocus aria-label={`重命名${name}`} aria-invalid={!!error} maxLength={100} value={draft} disabled={saving} onFocus={e=>e.target.select()} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{e.stopPropagation();if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();return}if(e.key==='Enter'){e.preventDefault();commit()}if(e.key==='Escape'&&!saving){e.preventDefault();finish()}}} onBlur={()=>{if(!pending.current)finish(false)}}/>{error&&<span role="alert">{error}</span>}</span>
 return <button {...props} ref={button} onClick={e=>{clearTimeout(timer.current);if(e.detail===0){onClick(e);return}const target=e.currentTarget;timer.current=setTimeout(()=>onClick({currentTarget:target}),350)}} onDoubleClick={e=>{e.preventDefault();clearTimeout(timer.current);setError('');setDraft(props.title||'')}}>{children}</button>
}
