import {nodeGeometry} from '../components/canvas/canvasGeometry.js'
import {groupBounds} from './canvasGroups.js'

// Collapse groups first, then rank strongly connected components. This remains
// deterministic for cycles and imported graphs without changing their edges.
export function organizeCanvas(document){
 const nodes=document.nodes||[];if(!nodes.length)return document
 const units=[],owner=new Map()
 for(const group of document.groups||[]){const members=nodes.filter(n=>group.nodeIds.includes(n.id));if(!members.length)continue;const unit={ids:members.map(n=>n.id),bounds:groupBounds(group,nodes),order:Math.min(...members.map(n=>nodes.indexOf(n)))};units.push(unit);members.forEach(n=>owner.set(n.id,unit))}
 for(const [index,node] of nodes.entries())if(!owner.has(node.id)){const geometry=nodeGeometry(node),unit={ids:[node.id],bounds:{x:node.x,y:node.y,width:geometry.width,height:geometry.height},order:index};units.push(unit);owner.set(node.id,unit)}
 units.sort((a,b)=>a.order-b.order);const edges=units.map(()=>new Set()),unitIndex=new Map(units.map((unit,index)=>[unit,index]))
 for(const edge of document.edges||[]){const a=unitIndex.get(owner.get(edge.source)),b=unitIndex.get(owner.get(edge.target));if(a!==undefined&&b!==undefined&&a!==b)edges[a].add(b)}
 const indices=new Map(),low=new Map(),stack=[],active=new Set(),components=[];let cursor=0
 function visit(index){indices.set(index,cursor);low.set(index,cursor++);stack.push(index);active.add(index);for(const next of edges[index]){if(!indices.has(next)){visit(next);low.set(index,Math.min(low.get(index),low.get(next)))}else if(active.has(next))low.set(index,Math.min(low.get(index),indices.get(next)))}if(low.get(index)===indices.get(index)){const component=[];let current;do{current=stack.pop();active.delete(current);component.push(current)}while(current!==index);components.push(component.sort((a,b)=>a-b))}}
 units.forEach((_,index)=>{if(!indices.has(index))visit(index)})
 const componentOf=new Map();components.forEach((members,index)=>members.forEach(member=>componentOf.set(member,index)))
 const incoming=components.map(()=>new Set());edges.forEach((targets,from)=>targets.forEach(to=>{const a=componentOf.get(from),b=componentOf.get(to);if(a!==b)incoming[b].add(a)}))
 const ranks=new Map();function rank(index){if(!ranks.has(index))ranks.set(index,incoming[index].size?1+Math.max(...[...incoming[index]].map(rank)):0);return ranks.get(index)}
 const columns=[];units.forEach((unit,index)=>{const level=rank(componentOf.get(index));(columns[level]||=[]).push(unit)})
 const offsets=new Map();let x=40
 for(const column of columns){let y=40;for(const unit of column){const dx=x-unit.bounds.x,dy=y-unit.bounds.y;for(const id of unit.ids)offsets.set(id,{dx,dy});y+=unit.bounds.height+80}x+=Math.max(...column.map(unit=>unit.bounds.width))+100}
 const arranged=nodes.map(node=>{const offset=offsets.get(node.id),x=node.x+offset.dx,y=node.y+offset.dy;if(Math.abs(x)>1e6||Math.abs(y)>1e6)throw new Error('整理结果超出画布坐标范围，请减少节点');return {...node,x,y}})
 return {...document,nodes:arranged}
}
