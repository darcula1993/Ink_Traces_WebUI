import React from 'react'
export default function AssetNodePanel({node,style,onChange,onCopy,onClose}) {
 return <aside className="cv-node-panel cv-asset-panel" style={style} data-panel-node-id={node.id} aria-label={`${node.title}的素材面板`} onPointerDown={e=>e.stopPropagation()} onWheel={e=>e.stopPropagation()} onKeyDown={e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s')return;e.stopPropagation();if(e.key==='Escape'){e.preventDefault();onClose()}}}>
 <label>名称<input aria-label="素材名称" value={node.title} onChange={e=>onChange({title:e.target.value})}/></label><div className="cv-panel-actions"><span/><button onClick={onCopy}>复制</button></div></aside>
}
