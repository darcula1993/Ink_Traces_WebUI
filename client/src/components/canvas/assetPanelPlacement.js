import {nodeGeometry} from './canvasGeometry.js'
// Screen-space placement: keep the compact asset controls outside its preview.
export function assetPanelPlacement(node,view,size) {
 const margin=12,height=100,width=Math.min(340,size.width-24),bottom=size.height-72
 const box={left:node.x*view.zoom+view.x,top:node.y*view.zoom+view.y,width:nodeGeometry(node).width*view.zoom,height:nodeGeometry(node).height*view.zoom}
 const centered=Math.max(margin,Math.min(size.width-width-margin,box.left+box.width/2-width/2))
 const below=box.top+box.height+12,above=box.top-height-(node.asset?.kind==='image'?56:12)
 if(below+height<=bottom&&below>=margin)return {left:centered,top:below,width,height}
 if(above>=margin&&above+height<=bottom)return {left:centered,top:above,width,height}
 const top=Math.max(margin,Math.min(bottom-height,box.top+box.height/2-height/2))
 const rightSpace=size.width-margin-(box.left+box.width+12),leftSpace=box.left-24
 if(rightSpace>=280)return {left:box.left+box.width+12,top,width:Math.min(width,rightSpace),height}
 if(leftSpace>=280){const fitted=Math.min(width,leftSpace);return {left:box.left-fitted-12,top,width:fitted,height}}
 // Off-screen or unusually small surfaces: retain readable controls inside bounds.
 return {left:centered,top:Math.max(margin,Math.min(bottom-height,below)),width,height}
}
