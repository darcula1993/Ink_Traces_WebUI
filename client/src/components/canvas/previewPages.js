// PREVIEW-NAV-20261115: pure helpers for the media preview (unit-tested in client/tests/previewPages.test.js).
const MEDIA=['image','video','audio']
const withKind=(asset,node)=>asset?.url?{...asset,kind:asset.kind||(node?.type==='asset'?undefined:node?.type)}:null
const playable=asset=>Boolean(asset?.url)&&MEDIA.includes(asset.kind)
// PREVIEW-NAV-20261115: the pages of a node preview are its kept versions; a node with a single version
// pages through the media nodes of its node group (group order); otherwise just the one asset.
export function previewItems(node,doc){
 const unique=list=>[...new Map(list.filter(playable).map(item=>[item.id||item.url,item])).values()]
 const versions=unique((node?.candidates||[]).map(item=>withKind(item,node)))
 if(versions.length>1)return versions
 const group=doc?.groups?.find(item=>item.nodeIds?.includes(node?.id))
 const members=group?unique(group.nodeIds.map(id=>{const member=doc.nodes?.find(item=>item.id===id);return withKind(member?.asset,member)})):[]
 return members.length>1?members:[withKind(node?.asset,node)].filter(Boolean)
}
// Download only from this site's own storage path, never a remote or signed (query-string) address.
export function localDownloadPath(url,origin=globalThis.location?.origin){
 try{const parsed=new URL(url,origin);return origin&&parsed.origin===origin&&!parsed.search?parsed.pathname:null}catch{return null}
}
