import React from 'react'
import LibraryMore from './LibraryMore'
import LibraryThumbnail from './LibraryThumbnail'
// Local catalog and remote adapters share card geometry, selection and keyboard behavior.
import {Check} from 'lucide-react'
export default function LibraryGrid({items,selectedKeys=new Set(),onToggle,onPreview,busy=false,isDisabled=()=>false,metadata,tools,primaryActions=1,children}){
 return <div className="ul-grid">{children}{items.map(item=><article className="ul-item" key={item.key}><button className="ul-card" disabled={busy||isDisabled(item)} aria-label={`选择素材 ${item.asset.name}`} aria-pressed={selectedKeys.has(item.key)} title={onPreview?'单击选择 · 双击或 Enter 预览':undefined} onClick={()=>onToggle(item)} onDoubleClick={onPreview?()=>onPreview(item):undefined} onKeyDown={onPreview?e=>{if(e.key==='Enter'){e.preventDefault();onPreview(item)}}:undefined}><LibraryThumbnail asset={item.asset} thumbnail={item.thumbnail_url}/>{selectedKeys.has(item.key)&&<i className="ul-check" aria-hidden="true"><Check size={14}/></i>}<strong title={item.asset.name}>{item.asset.name}</strong></button><div className="ul-item-meta">{metadata?.(item)}<div className="ul-item-tools">{(()=>{const content=tools?.(item),actions=React.Children.toArray(content?.type===React.Fragment?content.props.children:content);return <>{actions.slice(0,primaryActions)}{actions.length>primaryActions&&<LibraryMore name={item.asset.name} editKey={item.key}>{actions.slice(primaryActions)}</LibraryMore>}</>})()}</div></div></article>)}</div>
}
