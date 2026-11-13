import {nodeGeometry} from '../components/canvas/canvasGeometry.js'
import {groupBounds} from './canvasGroups.js'

// Count units (single nodes, or a whole group) whose outer boxes overlap another unit. Read-only.
export function countOverlappingUnits(document){
  const nodes=document?.nodes||[],owner=new Map(),units=[]
  for(const group of document?.groups||[]){
    const members=nodes.filter(node=>group.nodeIds?.includes(node.id));if(!members.length)continue
    const bounds=groupBounds(group,nodes),unit={bounds};units.push(unit);members.forEach(node=>owner.set(node.id,unit))
  }
  for(const node of nodes)if(!owner.has(node.id)){const g=nodeGeometry(node);units.push({bounds:{x:node.x,y:node.y,width:g.width,height:g.height}})}
  const hit=new Set()
  for(let i=0;i<units.length;i++)for(let j=i+1;j<units.length;j++){
    const a=units[i].bounds,b=units[j].bounds
    if(a.x<b.x+b.width-1&&a.x+a.width>b.x+1&&a.y<b.y+b.height-1&&a.y+a.height>b.y+1){hit.add(i);hit.add(j)}
  }
  return hit.size
}
