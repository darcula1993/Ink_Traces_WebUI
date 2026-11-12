import {isBusyTaskStatus} from './taskStatus.js'
import {cleanGroups} from './canvasGroups.js'
import {resolveNodeInputs} from './canvasReferences.js'
import {describeCanvasChange} from './canvasHistoryDescription.js'
import {withProviderSelection} from './canvasProviderSelection.js'
const clone = value => value === undefined ? undefined : structuredClone(value)
const equal = (a,b) => JSON.stringify(a) === JSON.stringify(b)
const runtimeFields = new Set(['task','candidates'])
export const protectedTask = node => isBusyTaskStatus(node?.task?.status)

function changes(before,after) {
  const old = new Map(before.nodes.map(n=>[n.id,n])), next = new Map(after.nodes.map(n=>[n.id,n]))
  const nodes=[]
  for(const id of new Set([...old.keys(),...next.keys()])) {
    const a=old.get(id),b=next.get(id)
    if(!a||!b){nodes.push({id,before:clone(a),after:clone(b),beforeIndex:before.nodes.findIndex(n=>n.id===id),afterIndex:after.nodes.findIndex(n=>n.id===id)});continue}
    const fields=[]
    for(const key of new Set([...Object.keys(a),...Object.keys(b)]))if(!runtimeFields.has(key)&&key!=='params'&&!equal(a[key],b[key]))fields.push({key,before:clone(a[key]),after:clone(b[key])})
    for(const key of new Set([...Object.keys(a.params||{}),...Object.keys(b.params||{})]))if(!equal(a.params?.[key],b.params?.[key]))fields.push({key:`params.${key}`,param:key,before:clone(a.params?.[key]),after:clone(b.params?.[key])})
    if(fields.length)nodes.push({id,fields})
  }
  const a=new Map(before.edges.map(e=>[e.id,e])),b=new Map(after.edges.map(e=>[e.id,e]))
  const edges=[...new Set([...a.keys(),...b.keys()])].filter(id=>!equal(a.get(id),b.get(id))).map(id=>({id,before:clone(a.get(id)),after:clone(b.get(id)),beforeIndex:before.edges.findIndex(e=>e.id===id),afterIndex:after.edges.findIndex(e=>e.id===id)}))
  return {nodes,edges,groups:equal(before.groups,after.groups)?null:{before:clone(before.groups),after:clone(after.groups)}}
}
export class CanvasEditHistory {
  constructor(limit=100){this.limit=limit;this.clear()}
  clear(){this.past=[];this.future=[];this.transaction=null}
  begin(document){this.transaction=clone(document)}
  finish(document){const before=this.transaction;this.transaction=null;if(before)this.record(before,{...before,nodes:before.nodes.map(node=>{const latest=document.nodes.find(n=>n.id===node.id);return latest?{...node,x:latest.x,y:latest.y}:node})})}
  rebaseReferenceAssets(before,after) {
    const oldSources=new Map(before.nodes.map(node=>[node.id,node]))
    const changed=after.nodes.filter(node=>oldSources.get(node.id)?.asset?.id&&node.asset?.id&&oldSources.get(node.id).asset.id!==node.asset.id)
    if(!changed.length)return
    for(const target of after.nodes.filter(node=>['image','video','audio'].includes(node.type))){
      const assets=new Set(resolveNodeInputs(target,after.nodes,after.edges).assets.map(asset=>asset.id)),candidates=new Map()
      for(const source of changed){const oldId=oldSources.get(source.id).asset.id;if(assets.has(oldId)||!assets.has(source.asset.id)||!before.edges.some(edge=>edge.source===source.id&&edge.target===target.id)||!after.edges.some(edge=>edge.source===source.id&&edge.target===target.id))continue;if(!candidates.has(oldId))candidates.set(oldId,new Set());candidates.get(oldId).add(source.asset.id)}
      const replacements=new Map([...candidates].filter(([,ids])=>ids.size===1).map(([id,ids])=>[id,[...ids][0]]))
      if(!replacements.size)continue
      for(const entry of [...this.past,...this.future])for(const change of entry.nodes.filter(item=>item.id===target.id))for(const field of change.fields||[])for(const side of ['before','after']){
        if(field.key==='referenceOrder'&&Array.isArray(field[side]))field[side]=[...new Set(field[side].map(id=>replacements.get(id)||id))]
        if(field.key==='referenceMentions'&&field[side])field[side]=Object.fromEntries(Object.entries(field[side]).map(([token,id])=>[token,replacements.get(id)||id]))
      }
    }
  }
  record(before,after,key=null,description=null) {
    if(this.transaction)return
    const delta=changes(before,after)
    if(!delta.nodes.length&&!delta.edges.length&&!delta.groups)return
    // Coalesce a continuous field edit, never a structural change or navigation.
    const last=this.past.at(-1),now=Date.now()
    if(!delta.groups&&!last?.groups&&key&&last?.key===key&&now-last.time<1000&&delta.nodes.every(n=>n.fields)&&!delta.edges.length){
      for(const node of delta.nodes){const previous=last.nodes.find(n=>n.id===node.id);if(!previous?.fields)continue;for(const field of node.fields){const existing=previous.fields.find(f=>f.key===field.key);if(existing)existing.after=field.after;else previous.fields.push(field)}}
      last.nodes=last.nodes.map(n=>({...n,fields:n.fields.filter(f=>!equal(f.before,f.after))})).filter(n=>n.fields.length)
      if(!last.nodes.length)this.past.pop()
      last.description=description||describeCanvasChange(last,before,after)
      last.time=now
    }else{this.past.push({...delta,key,time:now,description:description||describeCanvasChange(delta,before,after)});if(this.past.length>this.limit)this.past.shift()}
    this.future=[]
  }
  apply(document,redo=false) {
    const from=redo?this.future:this.past,to=redo?this.past:this.future,entry=from.at(-1)
    if(!entry)return document
    const side=redo?'after':'before',expected=redo?'before':'after',map=new Map(document.nodes.map(n=>[n.id,n]))
    for(const change of entry.nodes){const node=map.get(change.id);if(!change.fields&&!change[side]&&node&&(protectedTask(node)||node.task?.id&&node.task.id!==change[expected]?.task?.id))throw new Error('此操作会移除已开始生成或结果待核查的节点，不能撤销。可继续编辑，或在快捷键帮助中清空编辑记录。')}
    for(const change of entry.nodes){
      const node=map.get(change.id)
      if(change.fields){if(!node)continue;const updated={...node};for(const field of change.fields)if(equal(field.param?node.params?.[field.param]:node[field.key],field[expected])){const destination=field.param?(updated.params={...updated.params}):updated,key=field.param||field.key;if(field[side]===undefined)delete destination[key];else destination[key]=clone(field[side])}map.set(change.id,updated)}
      else if(change[side]){if(!node)map.set(change.id,clone(change.retained||change[side]))}
      else if(node){change.retained=clone(node);map.delete(change.id)}
    }
    const edges=new Map(document.edges.map(e=>[e.id,e]))
    for(const change of entry.edges){if(change[side])edges.set(change.id,clone(change[side]));else edges.delete(change.id)}
    from.pop();to.push(entry)
    const restoreOrder=(items,entries,original)=>{const result=[...items];for(const change of entries.filter(c=>!c.fields&&c[side]&&!original.some(item=>item.id===c.id)).sort((a,b)=>a[`${side}Index`]-b[`${side}Index`])){const index=result.findIndex(item=>item.id===change.id);if(index<0)continue;const [item]=result.splice(index,1);result.splice(Math.max(0,Math.min(change[`${side}Index`],result.length)),0,item)}return result}
    return cleanGroups({...document,...(entry.groups?{groups:clone(entry.groups[side])}:{}),nodes:restoreOrder(map.values(),entry.nodes,document.nodes),edges:restoreOrder(edges.values(),entry.edges,document.edges).filter(e=>map.has(e.source)&&map.has(e.target))})
  }
}
export function copyCanvasSelection(document,ids,workflowId) {
  const selected=new Set(ids)
  return {workflowId,groups:clone((document.groups||[]).filter(group=>group.nodeIds.every(id=>selected.has(id)))),nodes:clone(document.nodes.filter(n=>selected.has(n.id))).map(({upstreamStale,...n})=>({...n,task:null})),edges:clone(document.edges.filter(e=>selected.has(e.source)&&selected.has(e.target)))}
}
// selectionFor(type) fills a concrete interface into copied legacy generation nodes that have none.
export function pasteCanvasSelection(document,clipboard,workflowId,uid,offset=40,selectionFor=null) {
  if(!clipboard||clipboard.workflowId!==workflowId)throw new Error('选区只能粘贴到原画布，请重新复制。')
  if(document.nodes.length+clipboard.nodes.length>500||document.edges.length+clipboard.edges.length>2000)throw new Error('粘贴会超过画布上限（500节点／2000连线），请减少选区。')
  if(clipboard.nodes.some(n=>!Number.isFinite(n.x+offset)||!Number.isFinite(n.y+offset)||Math.abs(n.x+offset)>1e6||Math.abs(n.y+offset)>1e6))throw new Error('粘贴位置超出画布坐标范围，请先移动原选区再复制。')
  const ids=new Map(clipboard.nodes.map(n=>[n.id,uid()])),nodes=clone(clipboard.nodes).map(n=>({...n,id:ids.get(n.id),x:n.x+offset,y:n.y+offset,title:`${n.title.slice(0,237)} 副本`,task:null})).map(n=>withProviderSelection(n,selectionFor))
  const edges=clone(clipboard.edges).map(e=>({...e,id:uid(),source:ids.get(e.source),target:ids.get(e.target)}))
  const groups=(clipboard.groups||[]).map(group=>({...group,id:uid(),title:group.title.slice(0,97)+' 副本',nodeIds:group.nodeIds.map(id=>ids.get(id)),...(group.keyframeNodeId?{keyframeNodeId:ids.get(group.keyframeNodeId)}:{})}))
  return {document:{...document,...(groups.length?{groups:[...(document.groups||[]),...groups]}:{}),nodes:[...document.nodes,...nodes],edges:[...document.edges,...edges]},ids:nodes.map(n=>n.id)}
}
