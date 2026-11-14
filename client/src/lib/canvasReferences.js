import {promptMentionItem,referenceTokenPattern} from './referenceMedia.js'
export {referenceTokenPattern}
// One ordering and compatibility contract for cards, controls and submission.
export const mediaKind = node => node?.type === 'asset' ? node.asset?.kind : node?.type
export function canConnect(source, target) {
  if (!source || !target || source.id === target.id || !['image','video','audio'].includes(target.type)) return false
  const kind = mediaKind(source)
  if (kind === 'text') return true // Legacy prompt nodes remain readable.
  return ({image:['image'],video:['image','video','audio'],audio:['image','audio']}[target.type] || []).includes(kind)
}
export function resolveNodeInputs(node, nodes, edges) {
  const byId = new Map(nodes.map(item => [item.id,item])), assets = [], texts = [], issues = []
  for (const edge of edges.filter(item => item.target === node.id)) {
    const source = byId.get(edge.source)
    if (!canConnect(source,node)) { issues.push('连接的上游节点不存在或类型不兼容'); continue }
    if (source.type === 'text') { if(source.text?.trim()) texts.push(source.text.trim()); continue }
    if (!source.asset) { issues.push(`请先为“${source.title}”生成或选择一个结果`); continue }
    assets.push(source.asset)
  }
  assets.push(...(node.referenceAssets || []))
  const unique=[...new Map(assets.map(asset => [asset.id,asset])).values()],rank=new Map((node.referenceOrder||[]).map((id,index)=>[id,index]))
  unique.sort((a,b)=>(rank.get(a.id)??Infinity)-(rank.get(b.id)??Infinity))
  const frames=resolveKeyframeRoles(node,unique)
  return {assets:unique,prompt:[...texts,node.text?.trim()].filter(Boolean).join('\n\n'),issues:[...issues,...frames.issues,...referenceMentionIssues(node,unique,texts.join('\n'))],frames}
}

export function resolveKeyframeRoles(node, assets) {
  if (node.type !== 'video' || node.params?.video_mode !== 'keyframe') return {first:null,last:null,issues:[]}
  const images=assets.filter(asset=>asset.kind==='image'),issues=[]
  if (assets.some(asset=>asset.kind!=='image')) issues.push('首尾帧模式只接受图片，请移除视频和音频参考')
  if (!images.length) issues.push('首尾帧模式请接入一张首帧图片；纯文本生成请选择全能参考')
  if (images.length>2) issues.push('首尾帧模式最多接入两张图片')
  const first=images[0] || null, last=images[1] || null
  return {first,last,issues}
}

export const referenceTokens = text => [...new Set((text||'').match(referenceTokenPattern)||[])]
export function canvasMentionItems(node,assets) {
 const frames=resolveKeyframeRoles(node,assets),ordered=node.type==='video'&&node.params?.video_mode==='keyframe'?[frames.first,frames.last].filter(Boolean):assets
 const counts={image:0,video:0,audio:0}
 return ordered.filter(asset=>Object.hasOwn(counts,asset.kind)).map(asset=>({...promptMentionItem(asset.kind,++counts[asset.kind],{...asset,preview:asset.kind==='image'?asset.url:null},'canvas'),id:asset.id,assetId:asset.id}))
}
export function bindReferenceMentions(node,assets,text=node.text) {
 const current=new Map(canvasMentionItems(node,assets).map(item=>[item.token,item.assetId])),bindings={}
 for(const token of referenceTokens(text)){const id=node.referenceMentions?.[token]||current.get(token);if(id)bindings[token]=id}
 return bindings
}
// CANVAS-INPUT-20261114 #6 (user decision 11-14): a mention whose bound material is no longer a reference is
// read by position, like the request sent to the provider: @图片N follows the current N-th image reference,
// unless that reference is already bound by another mention (then it stays invalid).
export function positionalMentionRebinds(node,assets,mentions=node.referenceMentions,text=node.text) {
 const items=canvasMentionItems(node,assets),current=new Map(items.map(item=>[item.token,item])),ids=new Set(assets.map(asset=>asset.id))
 const used=new Set(Object.values(mentions||{}).filter(id=>ids.has(id))),rebinds=[]
 for(const token of referenceTokens(text)){
  const bound=mentions?.[token],target=current.get(token)
  if(!bound||ids.has(bound)||!target||used.has(target.assetId))continue
  used.add(target.assetId);rebinds.push({token,from:bound,to:target.assetId,name:assets.find(asset=>asset.id===target.assetId)?.name||target.label||target.token})
 }
 return rebinds
}
export function referenceMentionIssues(node,assets,upstreamText='') {
 const current=new Map(canvasMentionItems(node,assets).map(item=>[item.token,item.assetId])),ids=new Set(assets.map(asset=>asset.id)),issues=[]
 const positional=new Set(positionalMentionRebinds(node,assets,node.referenceMentions,`${upstreamText}\n${node.text||''}`).map(item=>item.token))
 for(const token of referenceTokens(`${upstreamText}\n${node.text||''}`)){
  const bound=node.referenceMentions?.[token]
  if(positional.has(token))continue
  if(bound&&!ids.has(bound))issues.push(`提及 ${token} 的素材已移除，请删除该提及后重新选择素材`)
  else if(bound&&current.get(token)!==bound)issues.push(`提及 ${token} 的编号已变化，请调整或移除该提及后重新选择`)
  else if(!current.has(token))issues.push(`提及 ${token} 没有对应素材，请删除或重新选择`)
 }
 return issues
}
// V140 #18: highlight state per token — "valid" only when the token resolves to
// a current reference and any saved binding still points at that same reference.
export function referenceTokenState(node,assets) {
 const current=new Map(canvasMentionItems(node,assets).map(item=>[item.token,item.assetId])),positional=new Set(positionalMentionRebinds(node,assets).map(item=>item.token))
 return token=>{const id=current.get(token),bound=node.referenceMentions?.[token];return id&&(!bound||bound===id||positional.has(token))?'valid':'invalid'}
}
