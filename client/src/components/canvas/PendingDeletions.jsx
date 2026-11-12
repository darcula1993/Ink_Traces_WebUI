import React,{useEffect,useRef,useState} from 'react'
import {listPendingCanvasDeletions,deleteCanvasObject} from '../../lib/canvasApi'
export default function PendingDeletions({onClose,onChanged}){
 const [items,setItems]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),ref=useRef(null)
 async function load(){setItems(await listPendingCanvasDeletions())}
 useEffect(()=>{ref.current.focus();load().catch(e=>setError(e.message))},[])
 async function retry(item){setBusy(true);setError('');ref.current.focus();try{await deleteCanvasObject(item.scope,item.id,item.cleanup_assets);await load();await onChanged()}catch(e){setError(e?.response?.data?.error||e.message)}finally{setBusy(false)}}
 return <div className="cv-studio-overlay"><section ref={ref} tabIndex={-1} className="cv-delete-dialog" role="dialog" aria-modal="true" aria-label="待完成删除" onKeyDown={e=>{e.stopPropagation();if(e.key==='Escape'&&!busy)onClose();if(e.key==='Tab'){const buttons=[...ref.current.querySelectorAll('button:not(:disabled)')];if(!buttons.length){e.preventDefault();ref.current.focus()}else if(e.shiftKey&&[ref.current,buttons[0]].includes(document.activeElement)){e.preventDefault();buttons.at(-1).focus()}else if(!e.shiftKey&&document.activeElement===buttons.at(-1)){e.preventDefault();buttons[0].focus()}}}}><h2>待完成删除</h2><p>这些对象已进入删除流程。继续执行原清理选项，不会变更其他项目或共享文件。</p>{!items.length&&<p>没有待完成的删除计划。</p>}{items.map(item=><div key={`${item.scope}:${item.id}`}><strong>{item.scope==='project'?'项目':'画布'}：{item.title}</strong><p>{item.cleanup_assets?'清理无其他引用的素材及产物':'保留素材及产物'}</p><button disabled={busy} onClick={()=>retry(item)}>继续清理 {item.title}</button></div>)}{error&&<p role="alert">{error}</p>}<button disabled={busy} onClick={onClose}>关闭</button></section></div>
}
