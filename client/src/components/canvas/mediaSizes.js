// UI-ITER-R2A #2: runtime cache of measured media sizes (asset id → natural width/height).
// Node geometry reads it so every consumer (render, edges, marquee, groups, organize, panel
// placement) agrees on one size. It is never written into the canvas document.
const sizes=new Map(),listeners=new Set(),pending=new Set()
let version=0
export const mediaSize=id=>id?sizes.get(id):undefined
export const mediaSizesVersion=()=>version
export function subscribeMediaSizes(listener){listeners.add(listener);return()=>listeners.delete(listener)}
export function recordMediaSize(id,width,height){
 if(!id||!(width>0)||!(height>0))return
 const old=sizes.get(id);if(old&&old.width===width&&old.height===height)return
 sizes.set(id,{width,height});version+=1;listeners.forEach(listener=>listener())
}
// Measure off-screen assets too (node images are lazy), so layout never waits on scrolling into view.
export function preloadMediaSizes(assets){
 if(typeof document==='undefined')return Promise.resolve()
 const waits=[]
 for(const asset of assets){
  if(!asset?.id||!asset.url||sizes.has(asset.id)||!['image','video'].includes(asset.kind))continue
  if(pending.has(asset.id))continue
  pending.add(asset.id)
  waits.push(new Promise(resolve=>{
   const done=()=>{pending.delete(asset.id);resolve()}
   if(asset.kind==='image'){const image=new Image();image.decoding='async';image.onload=()=>{recordMediaSize(asset.id,image.naturalWidth,image.naturalHeight);done()};image.onerror=done;image.src=asset.url}
   else{const video=document.createElement('video');video.preload='metadata';video.muted=true;const release=()=>{video.onloadedmetadata=video.onerror=null;video.removeAttribute('src');video.load();done()};video.onloadedmetadata=()=>{recordMediaSize(asset.id,video.videoWidth,video.videoHeight);release()};video.onerror=release;video.src=asset.url}
  }))
 }
 return Promise.all(waits).then(()=>{})
}
