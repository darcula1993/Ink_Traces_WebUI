import {nodeGeometry} from './canvasGeometry.js'
// Screen-space placement, always directly below the node (IMAGE-POPOVER-CLIP-20261114 #5, user decision
// 11-14 replacing the above/right/left avoidance); centred and clamped inside the surface.
export function assetPanelPlacement(node,view,size) {
 const margin=12,height=100,width=Math.min(340,size.width-24),bottom=size.height-72
 const box={left:node.x*view.zoom+view.x,top:node.y*view.zoom+view.y,width:nodeGeometry(node).width*view.zoom,height:nodeGeometry(node).height*view.zoom}
 const left=Math.max(margin,Math.min(size.width-width-margin,box.left+box.width/2-width/2))
 return {left,top:Math.max(margin,Math.min(bottom-height,box.top+box.height+12)),width,height}
}
