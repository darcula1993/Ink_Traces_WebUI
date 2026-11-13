export const NODE_WIDTH = 290
export const NODE_HEIGHT = 240
export const NODE_PORT_Y = 120
// UI-ITER-R1: readable zoom levels. Node text is >=12px in canvas space; below LOD_ZOOM it would render <10px.
export const LOCATE_ZOOM = 1
export const FIT_MIN_ZOOM = .75
export const LOD_ZOOM = 10/12
export const nodeGeometry = node => node?.type==='video'?{width:420,height:300,portY:150}:{width:NODE_WIDTH,height:NODE_HEIGHT,portY:NODE_PORT_Y}
export const editorPanelSize = size => ({width:Math.min(720,Math.max(240,size.width-32)),height:Math.min(240,Math.max(160,size.height-160))})
export function generationPanelStyle(node,view,size) {
 const geometry=nodeGeometry(node),panel=editorPanelSize(size)
 return {width:panel.width,height:panel.height,left:Math.max(16,Math.min(size.width-panel.width-16,node.x*view.zoom+view.x+geometry.width*view.zoom/2-panel.width/2)),top:(node.y+geometry.height)*view.zoom+view.y+12}
}
export function nodeEditorViewport(node,view,size,center=false) {
 const geometry=nodeGeometry(node),generation=['image','video','audio','text'].includes(node.type),panel=generation?editorPanelSize(size):{width:0,height:0},margin=16,bottom=generation?72:0
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
