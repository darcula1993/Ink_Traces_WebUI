import {resolveNodeInputs} from './canvasReferences.js'
import {nodeGeometry} from '../components/canvas/canvasGeometry.js'
import {cleanGroups,groupBounds,nextNodeGroupTitle} from './canvasGroups.js'
// Group layout never changes reference edges. Shared/generation sources remain live external references.
export function syncKeyframeGroups(before,document,uid){
 let next=cleanGroups(document)
 for(const video of document.nodes.filter(node=>node.type==='video')){
  let group=next.groups?.find(item=>item.keyframeNodeId===video.id)
  if(video.params?.video_mode!=='keyframe'){if(group)next={...next,groups:next.groups.map(item=>item.id===group.id?(({keyframeNodeId,...plain})=>plain)(item):item)};continue}
  const old=before.nodes.find(node=>node.id===video.id),inputs=resolveNodeInputs(video,next.nodes,next.edges).assets
  const addedSource=next.edges.some(edge=>edge.target===video.id&&!before.edges.some(previous=>previous.target===video.id&&previous.source===edge.source))
  const addedDirect=(video.referenceAssets||[]).some(asset=>!(old?.referenceAssets||[]).some(previous=>previous.id===asset.id))
  const changed=old&&(old.params?.video_mode!=='keyframe'||addedSource||addedDirect)
  if(!group&&!changed)continue
  if(!group){const existing=next.groups?.find(item=>item.nodeIds.includes(video.id)&&item.nodeIds.every(id=>id===video.id||next.nodes.find(node=>node.id===id)?.type==='asset'));group=existing?{...existing,keyframeNodeId:video.id}:{id:uid(),title:nextNodeGroupTitle(next.groups),nodeIds:[video.id],keyframeNodeId:video.id}}
  const fresh=!(next.groups||[]).some(item=>item.id===group.id),members=[video.id];let nodes=[...next.nodes]
  for(const [index,asset] of inputs.filter(asset=>asset.kind==='image').entries()){
   const source=nodes.find(node=>node.type==='asset'&&node.asset?.id===asset.id&&next.edges.some(edge=>edge.source===node.id&&edge.target===video.id)&&(!(next.groups||[]).some(item=>item.id!==group.id&&item.nodeIds.includes(node.id)))&&!next.edges.some(edge=>edge.source===node.id&&edge.target!==video.id))
   if(!source)continue
   members.push(source.id)
   if(!group.nodeIds.includes(source.id))nodes=nodes.map(node=>node.id===source.id?{...node,x:Math.max(-1e6,video.x-350),y:Math.min(1e6,video.y+index*280)}:node)
  }
  const updated={...group,nodeIds:members},groups=(next.groups||[]).filter(item=>item.id!==group.id).map(item=>({...item,nodeIds:item.nodeIds.filter(id=>!members.includes(id))})).filter(item=>item.nodeIds.length)
  if(groups.length>=500)throw new Error('首尾帧节点组超出500组上限')
  if(JSON.stringify(next.groups?.find(item=>item.id===group.id))===JSON.stringify(updated)&&nodes.every((node,index)=>node===next.nodes[index]))continue
  if(fresh){const bounds=groupBounds(updated,nodes),unrelated=nodes.filter(node=>!members.includes(node.id));if(unrelated.some(node=>node.x<bounds.x+bounds.width&&node.x+nodeGeometry(node).width>bounds.x&&node.y<bounds.y+bounds.height&&node.y+nodeGeometry(node).height>bounds.y)){const dx=Math.max(...unrelated.map(node=>node.x+nodeGeometry(node).width))+80-bounds.x;if(nodes.some(node=>members.includes(node.id)&&Math.abs(node.x+dx)>1e6))throw new Error('首尾帧节点组布局超出坐标范围，请先整理画布');nodes=nodes.map(node=>members.includes(node.id)?{...node,x:node.x+dx}:node)}}
  next={...next,nodes,groups:[...groups,updated]}
 }
 return next
}
