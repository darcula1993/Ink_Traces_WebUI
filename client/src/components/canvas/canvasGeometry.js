import {mediaSize} from './mediaSizes.js'
export const NODE_WIDTH = 290
export const NODE_HEIGHT = 240
export const NODE_PORT_Y = 120
// UI-ITER-R1: readable zoom levels. Node text is >=12px in canvas space; below LOD_ZOOM it would render <10px.
export const LOCATE_ZOOM = 1
export const FIT_MIN_ZOOM = .75
export const LOD_ZOOM = 10/12
// UI-ITER-R2A #2: image/video nodes take the shape of their media. The media box follows the measured
// result aspect (runtime cache), else the selected output ratio, within per-kind bounds; text keeps the
// legacy 290×240 card. Derived only from the node, so old documents need no migration.
export const NODE_HEAD=40,NODE_PAD=8,NODE_FOOTER=26,NODE_BORDER=1
const MEDIA_BOUNDS={image:{maxW:272,minW:182,maxH:240,minH:120,fallback:1},video:{maxW:402,minW:242,maxH:300,minH:160,fallback:16/9}}
const AUDIO_MEDIA_HEIGHT=112
export function ratioAspect(params={}){
 if(params.ratio==='custom'){const w=Number(params.custom_width),h=Number(params.custom_height);return w>0&&h>0?w/h:null}
 const match=/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(params.ratio||'');return match&&Number(match[2])>0?Number(match[1])/Number(match[2]):null
}
export function nodeMediaKind(node){return node?.type==='asset'?node.asset?.kind:node?.type}
export function nodeAspect(node){
 const kind=nodeMediaKind(node),size=mediaSize(node?.asset?.id)
 if(size)return size.width/size.height
 if(node?.type==='asset')return kind==='video'?16/9:4/3
 return ratioAspect(node?.params)||MEDIA_BOUNDS[kind]?.fallback||1
}
const legacyGeometry={width:NODE_WIDTH,height:NODE_HEIGHT,portY:NODE_PORT_Y}
export function nodeGeometry(node){
 const kind=nodeMediaKind(node)
 if(!node||node.type==='text'||!['image','video','audio','asset'].includes(node.type)||!['image','video','audio'].includes(kind))return legacyGeometry
 const footer=node.type!=='asset'&&node.task?NODE_FOOTER:0,chrome=2*NODE_BORDER+NODE_HEAD+2*NODE_PAD+footer
 if(kind==='audio'){const mediaHeight=AUDIO_MEDIA_HEIGHT;return {width:NODE_WIDTH,height:chrome+mediaHeight,portY:NODE_BORDER+NODE_HEAD+NODE_PAD+mediaHeight/2,mediaWidth:NODE_WIDTH-2*NODE_BORDER-2*NODE_PAD,mediaHeight}}
 // Asset video thumbnails stay compact (image bounds); generated video keeps the larger stage.
 const bounds=MEDIA_BOUNDS[node.type==='video'?'video':'image'],aspect=Math.min(4,Math.max(.25,nodeAspect(node)))
 const mediaWidth=Math.round(Math.max(bounds.minW,Math.min(bounds.maxW,bounds.maxH*aspect)))
 const mediaHeight=Math.round(Math.max(bounds.minH,Math.min(bounds.maxH,mediaWidth/aspect)))
 return {width:mediaWidth+2*NODE_BORDER+2*NODE_PAD,height:chrome+mediaHeight,portY:NODE_BORDER+NODE_HEAD+NODE_PAD+mediaHeight/2,mediaWidth,mediaHeight}
}
export const editorPanelSize = size => ({width:Math.min(720,Math.max(240,size.width-32)),height:Math.min(240,Math.max(160,size.height-160))})
const screenBox=(node,view)=>{const g=nodeGeometry(node),left=node.x*view.zoom+view.x,top=node.y*view.zoom+view.y;return {left,top,right:left+g.width*view.zoom,bottom:top+g.height*view.zoom}}
const overlapArea=(a,b)=>Math.max(0,Math.min(a.right,b.right)-Math.max(a.left,b.left))*Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top))
// IMAGE-POPOVER-CLIP-20261114 #5 (user decision 11-14, replaces the v1.3.0 / UI-ITER-R2A automatic
// below/right/left/above avoidance): the editor panel is always directly below its node, centred and
// clamped inside the surface (above the bottom toolbar); covering other nodes is accepted. Selecting a
// node still moves the viewport to reveal the panel (nodeEditorViewport). Recomputed every render.
export const PANEL_SIDES=['below']
export function generationPanelPlacement(node,view,size,nodes=[]) {
 const panel=editorPanelSize(size),margin=16,gap=12,bottom=size.height-72,box=screenBox(node,view)
 const left=Math.max(margin,Math.min(size.width-panel.width-margin,(box.left+box.right)/2-panel.width/2)),top=Math.max(margin,Math.min(bottom-panel.height,box.bottom+gap))
 const rect={left,top,right:left+panel.width,bottom:top+panel.height},viewportBox={left:0,top:0,right:size.width,bottom:size.height}
 const free=overlapArea(rect,box)===0&&nodes.every(other=>other.id===node.id||overlapArea(rect,screenBox(other,view))===0||overlapArea(screenBox(other,view),viewportBox)===0)
 return {side:'below',free,style:{width:panel.width,height:panel.height,left,top}}
}
export const generationPanelStyle=(node,view,size,nodes=[])=>generationPanelPlacement(node,view,size,nodes).style
export function nodeEditorViewport(node,view,size,center=false,nodes=[]) {
 const geometry=nodeGeometry(node),generation=['image','video','audio','text'].includes(node.type),panel=generation?editorPanelSize(size):{width:0,height:0},margin=16,bottom=generation?72:0
 // UI-ITER-R2A #1: when locating, frame the node together with a free panel side (below first, then
 // right/left/above) so the editor does not land on a neighbour; fall back to the legacy below layout.
 if(center&&generation&&nodes.length>1){
  const gap=12,availW=size.width-2*margin,availH=size.height-margin-bottom-margin
  for(const side of PANEL_SIDES){
   const vertical=side==='below'||side==='above'
   const zoom=Math.max(.2,Math.min(LOCATE_ZOOM,vertical?availW/geometry.width:(availW-panel.width-gap)/geometry.width,vertical?(availH-panel.height-gap)/geometry.height:availH/geometry.height))
   const w=geometry.width*zoom,h=geometry.height*zoom,groupW=vertical?Math.max(w,panel.width):w+gap+panel.width,groupH=vertical?h+gap+panel.height:Math.max(h,panel.height)
   // Alternatives must keep the readable locate zoom (UI-ITER-R1); only the legacy below layout may zoom out.
   if(side!=='below'&&zoom<LOCATE_ZOOM||groupW>availW+1||groupH>availH+1)continue
   const groupLeft=(size.width-groupW)/2,groupTop=margin+(availH-groupH)/2
   const left=side==='left'?groupLeft+panel.width+gap:vertical?groupLeft+(groupW-w)/2:groupLeft,top=side==='above'?groupTop+panel.height+gap:vertical?groupTop:groupTop+(groupH-h)/2
   const next={...view,zoom,x:left-node.x*zoom,y:top-node.y*zoom}
   const placed=generationPanelPlacement(node,next,size,nodes);if(placed.side===side&&placed.free)return next
  }
 }
 // Locating (center) targets a readable 100%; following a selection only ever zooms out to fit the editor.
 const target=center?LOCATE_ZOOM:view.zoom
 const zoom=generation?Math.max(.2,Math.min(target,(size.width-2*margin)/geometry.width,(size.height-margin-bottom-panel.height-12)/geometry.height)):target
 const width=geometry.width*zoom,height=geometry.height*zoom+(generation?panel.height+12:0)
 let left=node.x*zoom+view.x,top=node.y*zoom+view.y
 if(center){left=(size.width-width)/2;top=(size.height-bottom-height)/2}else{left=Math.max(margin,Math.min(size.width-margin-width,left));top=Math.max(margin,Math.min(size.height-bottom-height,top))}
 return {...view,zoom,x:left-node.x*zoom,y:top-node.y*zoom}
}
export function overlapsNode(position,node,padding=20) {
 const a=nodeGeometry(position),b=nodeGeometry(node)
 return position.x<node.x+b.width+padding&&position.x+a.width+padding>node.x&&position.y<node.y+b.height+padding&&position.y+a.height+padding>node.y
}

// Fit all nodes, but never below FIT_MIN_ZOOM: if they still do not fit, keep the top-left of the content in view.
export function fitViewport(bounds,size,pad={x:90,y:50}) {
 const width=Math.max(1,bounds.maxX-bounds.minX),height=Math.max(1,bounds.maxY-bounds.minY)
 const zoom=Math.min(1.3,Math.max(FIT_MIN_ZOOM,Math.min((size.width-2*pad.x)/width,(size.height-2*pad.y)/height)))
 const axis=(span,extent,min,margin)=>span*zoom<=extent-2*margin?(extent-span*zoom)/2-min*zoom:margin-min*zoom
 return {zoom,x:axis(width,size.width,bounds.minX,pad.x),y:axis(height,size.height,bounds.minY,pad.y)}
}
