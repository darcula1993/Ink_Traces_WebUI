import {resolveNodeInputs,canvasMentionItems,referenceTokenPattern,bindReferenceMentions,referenceTokens} from './canvasReferences.js'
export function reorderNodeReferences(document,nodeId,order) {
 const node=document.nodes.find(item=>item.id===nodeId)
 if(!node)throw new Error('节点已不存在，请重新选择')
 const before=resolveNodeInputs(node,document.nodes,document.edges),ids=before.assets.map(asset=>asset.id)
 if(order.length!==ids.length||new Set(order).size!==ids.length||order.some(id=>!ids.includes(id)))throw new Error('参考素材已变化，请重新排序')
 if(before.issues.some(issue=>issue.startsWith('提及')))throw new Error('请先修复失效的素材提及，再调整参考顺序')
 const next={...node,referenceOrder:[...order]}
 const after=resolveNodeInputs(next,document.nodes,document.edges),oldMentions=canvasMentionItems(node,before.assets),newMentions=canvasMentionItems(next,after.assets)
 const byId=new Map(newMentions.map(item=>[item.assetId,item.token])),mapping=new Map(oldMentions.map(item=>[item.token,byId.get(item.assetId)||item.token]))
 const rewrite=text=>(text||'').replace(referenceTokenPattern,token=>mapping.get(token)||token)
 for(const edge of document.edges.filter(edge=>edge.target===nodeId)){
  const source=document.nodes.find(item=>item.id===edge.source)
  if(source?.type==='text'&&rewrite(source.text)!==source.text)throw new Error('排序会改变上游文本中的素材提及。请先将相关提及移到当前节点；共享文本不会自动改写。')
 }
 next.text=rewrite(node.text)
 const bound=bindReferenceMentions(node,before.assets,before.prompt);next.referenceMentions=Object.fromEntries(Object.entries(bound).map(([token,id])=>[mapping.get(token)||token,id]))
 return {...document,nodes:document.nodes.map(item=>item.id===nodeId?next:item)}
}

// Bind before structural edits, keep missing bindings invalid, and follow a unique
// surviving source when it selects another version or receives a generated result.
export function reconcileReferenceMentions(before,after) {
 const previous=new Map(before.nodes.map(node=>[node.id,node])),updated=[]
 if(before.edges===after.edges&&before.nodes.length===after.nodes.length&&after.nodes.every(node=>{const old=previous.get(node.id);return old&&old.asset?.id===node.asset?.id&&old.text===node.text&&old.referenceAssets===node.referenceAssets&&old.referenceOrder===node.referenceOrder&&old.referenceMentions===node.referenceMentions&&['video_mode','first_frame','last_frame'].every(key=>old.params?.[key]===node.params?.[key])}))return after
 for(const original of after.nodes){
  if(!['image','video','audio'].includes(original.type)){updated.push(original);continue}
  const old=previous.get(original.id),oldInputs=old?resolveNodeInputs(old,before.nodes,before.edges):null
  let node=original,nextInputs=resolveNodeInputs(node,after.nodes,after.edges)
  const explicit=old&&original.referenceMentions!==old.referenceMentions
  const oldBindings=old?bindReferenceMentions(old,oldInputs.assets,oldInputs.prompt):{}
  const bindings=explicit?{...original.referenceMentions}:bindReferenceMentions({...node,referenceMentions:oldBindings},nextInputs.assets,nextInputs.prompt)
  const ids=new Set(nextInputs.assets.map(asset=>asset.id)),replacements=new Map()
  for(const id of new Set([...(old?.referenceOrder||[]),...Object.values(bindings)])){
   if(ids.has(id))continue
   const sources=before.edges.filter(edge=>edge.target===node.id&&previous.get(edge.source)?.asset?.id===id)
   const candidates=new Set(sources.filter(edge=>after.edges.some(next=>next.source===edge.source&&next.target===node.id)).map(edge=>after.nodes.find(item=>item.id===edge.source)?.asset?.id).filter(value=>value&&ids.has(value)))
   if(candidates.size===1)replacements.set(id,[...candidates][0])
  }
  const changedOrder=node.referenceOrder&&node.referenceOrder.some(id=>replacements.has(id))
  if(changedOrder){node={...node,referenceOrder:[...new Set(node.referenceOrder.map(id=>replacements.get(id)||id))]};nextInputs=resolveNodeInputs(node,after.nodes,after.edges)}
  for(const token of Object.keys(bindings))bindings[token]=replacements.get(bindings[token])||bindings[token]
  const byId=new Map(canvasMentionItems(node,nextInputs.assets).map(item=>[item.assetId,item.token]))
  const upstream=after.edges.filter(edge=>edge.target===node.id).map(edge=>after.nodes.find(item=>item.id===edge.source)).filter(source=>source?.type==='text').map(source=>source.text||'').join('\n')
  const upstreamTokens=referenceTokens(upstream)
  const safe=Object.values(bindings).every(id=>byId.has(id))&&upstreamTokens.every(token=>!bindings[token]||byId.get(bindings[token])===token)
  let text=node.text
  if(safe){text=(text||'').replace(referenceTokenPattern,token=>byId.get(bindings[token])||token);const remapped={};for(const [token,id] of Object.entries(bindings))remapped[byId.get(id)||token]=id;Object.keys(bindings).forEach(key=>delete bindings[key]);Object.assign(bindings,remapped)}
  const hasBindings=Object.keys(bindings).length>0
  if(text!==node.text||JSON.stringify(bindings)!==JSON.stringify(node.referenceMentions||{}))node={...node,text,...(hasBindings||node.referenceMentions?{referenceMentions:bindings}:{})}
  updated.push(node)
 }
 return {...after,nodes:updated}
}
