export const NODE_WIDTH = 290
export const NODE_HEIGHT = 240
export const NODE_PORT_Y = 120
export const nodeGeometry = node => node?.type==='video'?{width:420,height:300,portY:150}:{width:NODE_WIDTH,height:NODE_HEIGHT,portY:NODE_PORT_Y}
export const editorPanelSize = size => ({width:Math.min(720,Math.max(240,size.width-32)),height:Math.min(240,Math.max(160,size.height-160))})
export function generationPanelStyle(node,view,size) {
 const geometry=nodeGeometry(node),panel=editorPanelSize(size)
 return {width:panel.width,height:panel.height,left:Math.max(16,Math.min(size.width-panel.width-16,node.x*view.zoom+view.x+geometry.width*view.zoom/2-panel.width/2)),top:(node.y+geometry.height)*view.zoom+view.y+12}
}
export function nodeEditorViewport(node,view,size,center=false) {
 const geometry=nodeGeometry(node),generation=['image','video','audio','text'].includes(node.type),panel=generation?editorPanelSize(size):{width:0,height:0},margin=16,bottom=generation?72:0
 const zoom=generation?Math.max(.2,Math.min(view.zoom,(size.width-2*margin)/geometry.width,(size.height-margin-bottom-panel.height-12)/geometry.height)):view.zoom
 const width=geometry.width*zoom,height=geometry.height*zoom+(generation?panel.height+12:0)
 let left=node.x*zoom+view.x,top=node.y*zoom+view.y
 if(center){left=(size.width-width)/2;top=(size.height-bottom-height)/2}else{left=Math.max(margin,Math.min(size.width-margin-width,left));top=Math.max(margin,Math.min(size.height-bottom-height,top))}
 return {...view,zoom,x:left-node.x*zoom,y:top-node.y*zoom}
}
export function overlapsNode(position,node,padding=20) {
 const a=nodeGeometry(position),b=nodeGeometry(node)
 return position.x<node.x+b.width+padding&&position.x+a.width+padding>node.x&&position.y<node.y+b.height+padding&&position.y+a.height+padding>node.y
}
