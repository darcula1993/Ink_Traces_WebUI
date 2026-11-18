import {mediaSize} from './mediaSizes.js'
export const NODE_WIDTH = 290
export const NODE_HEIGHT = 240
export const NODE_PORT_Y = 120
// UI-ITER-R1: readable zoom levels. Node text is >=12px in canvas space; below LOD_ZOOM it would render <10px.
export const LOCATE_ZOOM = 1
export const FIT_MIN_ZOOM = .2
export const LOD_ZOOM = 10/12
// UI-ITER-R2A #2: image/video nodes take the shape of their media. The media box follows the measured
// result aspect (runtime cache), else the selected output ratio, within per-kind bounds; text keeps the
// legacy 290×240 card. Derived only from the node, so old documents need no migration.
export const NODE_HEAD=40,NODE_PAD=8,NODE_FOOTER=26,NODE_BORDER=1
// CANVAS-LAYOUT-1-20261117: generation nodes carry their prompt in the card. CARD-PROMPT-RESIZE-20261118 (user 11-18,
// scheme A as ImagineArt): a full-width text area (about 3 lines, fixed, scrolls inside) above a tool row (提示词库,
// @角色卡 | 展开编辑, cost, 生成). NODE_PROMPT is the whole prompt section at the automatic size.
// CARD-PROMPT-READABLE-20261118 (user 11-18): 14px/20px text in an inset field (3 lines = 60 + 4+4 padding + 6/2 inset
// gap = 76) and a 36px tool row with 28px buttons.
export const NODE_PROMPT_TEXT=76,NODE_PROMPT_TOOLS=36,NODE_PROMPT=NODE_PROMPT_TEXT+NODE_PROMPT_TOOLS
const MEDIA_BOUNDS={image:{maxW:272,minW:182,maxH:240,minH:120,fallback:1},video:{maxW:402,minW:242,maxH:300,minH:160,fallback:16/9}}
const AUDIO_MEDIA_HEIGHT=112
// CARD-PROMPT-RESIZE-20261118 (user 11-18): manual node size, stored as node.size = {scale} (a multiple of the
// automatic size) so the preview keeps following the media aspect and the prompt text area grows with the node.
// No field = automatic size (old documents are read as they are and never rewritten). Bounds keep the tool row
// usable (minimum card width) and the node reasonable on the canvas (maximum width / scale).
export const NODE_SCALE_MIN=.5,NODE_SCALE_MAX=3,NODE_MIN_WIDTH={generation:220,asset:160},NODE_MAX_WIDTH=1200
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
// Media-shaped nodes (generation nodes and media assets); legacy text nodes keep the 290×240 card and no resize.
export const resizableNode=node=>!!node&&['image','video','audio','asset'].includes(node.type)&&['image','video','audio'].includes(nodeMediaKind(node))
// Automatic media box (before any manual size).
function autoMedia(node,kind){
 if(kind==='audio')return {mediaWidth:NODE_WIDTH-2*NODE_BORDER-2*NODE_PAD,mediaHeight:AUDIO_MEDIA_HEIGHT}
 // Asset video thumbnails stay compact (image bounds); generated video keeps the larger stage.
 const bounds=MEDIA_BOUNDS[node.type==='video'?'video':'image'],aspect=Math.min(4,Math.max(.25,nodeAspect(node)))
 const mediaWidth=Math.round(Math.max(bounds.minW,Math.min(bounds.maxW,bounds.maxH*aspect)))
 return {mediaWidth,mediaHeight:Math.round(Math.max(bounds.minH,Math.min(bounds.maxH,mediaWidth/aspect)))}
}
// Allowed scale range of a node (the automatic width decides how far the minimum / maximum card width allow).
export function nodeScaleRange(node){
 if(!resizableNode(node))return {min:1,max:1}
 const auto=autoMedia(node,nodeMediaKind(node)).mediaWidth,frame=2*NODE_BORDER+2*NODE_PAD,minWidth=NODE_MIN_WIDTH[node.type==='asset'?'asset':'generation']
 return {min:Math.min(1,Math.max(NODE_SCALE_MIN,(minWidth-frame)/auto)),max:Math.max(1,Math.min(NODE_SCALE_MAX,(NODE_MAX_WIDTH-frame)/auto))}
}
export function clampNodeScale(node,scale){
 const {min,max}=nodeScaleRange(node),value=Number(scale)
 return Number.isFinite(value)?Math.round(Math.min(max,Math.max(min,value))*1000)/1000:1
}
export const nodeScale=node=>resizableNode(node)&&node.size&&Number.isFinite(Number(node.size.scale))?clampNodeScale(node,node.size.scale):1
export function nodeGeometry(node){
 if(!resizableNode(node))return legacyGeometry
 const scale=nodeScale(node),auto=autoMedia(node,nodeMediaKind(node)),mediaWidth=Math.round(auto.mediaWidth*scale),mediaHeight=Math.round(auto.mediaHeight*scale)
 const promptText=node.type!=='asset'?Math.round(NODE_PROMPT_TEXT*scale):0,prompt=node.type!=='asset'?promptText+NODE_PROMPT_TOOLS:0
 const footer=node.type!=='asset'&&node.task?NODE_FOOTER:0,chrome=2*NODE_BORDER+NODE_HEAD+2*NODE_PAD+footer+prompt
 return {width:mediaWidth+2*NODE_BORDER+2*NODE_PAD,height:chrome+mediaHeight,portY:NODE_BORDER+NODE_HEAD+NODE_PAD+mediaHeight/2,mediaWidth,mediaHeight,...(prompt?{promptHeight:prompt}:{})}
}
// Scale that makes the node fill the given card size (pointer resize): the larger of the width / height fit wins,
// so a corner drag in either direction resizes; the result is clamped to the node's range.
export function scaleForSize(node,width,height){
 if(!resizableNode(node))return 1
 const auto=autoMedia(node,nodeMediaKind(node)),base=nodeGeometry({...node,size:undefined}),text=node.type!=='asset'?NODE_PROMPT_TEXT:0
 const sx=(width-(base.width-auto.mediaWidth))/auto.mediaWidth,sy=(height-(base.height-auto.mediaHeight-text))/(auto.mediaHeight+text)
 return clampNodeScale(node,Math.max(sx,sy))
}
// CANVAS-LAYOUT-1-20261117 (user decision 11-17, replaces IMAGE-POPOVER-CLIP #5 "editor panel always below
// the node"): node settings live in the fixed right properties panel, outside the canvas surface. Selecting a
// node only keeps the node itself inside the visible surface (above the bottom tool bar); no room is reserved
// for a panel any more. Locating (center) frames the node at a readable 100% (or less when it does not fit).
export const SURFACE_BOTTOM_BAR=72
export function nodeEditorViewport(node,view,size,center=false) {
 // Same framing as before minus the reserved panel: locating an asset centres it at 100% in the whole surface;
 // everything else stays above the bottom bars and only zooms out when the node itself does not fit.
 const geometry=nodeGeometry(node),margin=16,fit=!(node.type==='asset'&&center),bottom=fit?SURFACE_BOTTOM_BAR:0
 const target=center?LOCATE_ZOOM:view.zoom
 const zoom=fit?Math.max(.2,Math.min(target,(size.width-2*margin)/geometry.width,(size.height-margin-bottom)/geometry.height)):target
 const width=geometry.width*zoom,height=geometry.height*zoom
 let left=node.x*zoom+view.x,top=node.y*zoom+view.y
 if(center){left=(size.width-width)/2;top=(size.height-bottom-height)/2}else{left=Math.max(margin,Math.min(size.width-margin-width,left));top=Math.max(margin,Math.min(size.height-bottom-height,top))}
 return {...view,zoom,x:left-node.x*zoom,y:top-node.y*zoom}
}
export function overlapsNode(position,node,padding=20) {
 const a=nodeGeometry(position),b=nodeGeometry(node)
 return position.x<node.x+b.width+padding&&position.x+a.width+padding>node.x&&position.y<node.y+b.height+padding&&position.y+a.height+padding>node.y
}

// FIX-B2-20261114 #1 (replaces UI-ITER-R1 "never below 0.75"): fit-all zooms out as far as the canvas
// minimum (FIT_MIN_ZOOM = 0.2) so every node is visible; the bottom pad keeps content clear of the
// floating zoom bar / tool bar. Only content that does not fit even at the minimum keeps its top-left in view.
export function fitViewport(bounds,size,pad={left:60,right:60,top:40,bottom:96}) {
 const width=Math.max(1,bounds.maxX-bounds.minX),height=Math.max(1,bounds.maxY-bounds.minY)
 const availW=Math.max(1,size.width-pad.left-pad.right),availH=Math.max(1,size.height-pad.top-pad.bottom)
 const zoom=Math.min(1.3,Math.max(FIT_MIN_ZOOM,Math.min(availW/width,availH/height)))
 const axis=(span,avail,start,min)=>span*zoom<=avail?start+(avail-span*zoom)/2-min*zoom:start-min*zoom
 return {zoom,x:axis(width,availW,pad.left,bounds.minX),y:axis(height,availH,pad.top,bounds.minY)}
}
