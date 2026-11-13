// Update the existing source node and only the downstream bindings that refer to it.
export function switchAssetVersion(document, nodeId, asset, append = false) {
  const source=document.nodes.find(node=>node.id===nodeId)
  if(!source || source.type!=='asset' || source.asset.kind!==asset.kind) throw new Error('素材节点不存在或媒体类型不一致')
  const candidates=asset.kind==='image' ? [...new Map([...(source.candidates || []),...(append?[asset]:[])].map(item=>[item.id,item])).values()] : [asset]
  if(candidates.length>100) throw new Error('图片历史版本最多保留100个，请创建新的素材节点继续编辑')
  if(!candidates.some(item=>item.id===asset.id)) throw new Error('历史版本不存在')
  // V140 #8: a title that still is the previous file name follows the new file; a custom title is kept.
  const followsName=!source.title||source.title===source.asset?.name
  const nodes=document.nodes.map(node=>node.id===nodeId?{...node,asset,candidates,selectedCandidateId:asset.id,...(followsName&&asset.name?{title:String(asset.name).slice(0,240)}:{})}:node)
  return {document:{...document,nodes},warnings:[]}
}
export async function rotateImageFile(asset) {
  const image=new Image();image.crossOrigin='anonymous';image.src=asset.url;await image.decode()
  if(image.naturalWidth*image.naturalHeight>16000000 || Math.max(image.naturalWidth,image.naturalHeight)>8192)throw new Error('旋转支持最多1600万像素、单边8192的图片，请先缩小原图')
  const canvas=document.createElement('canvas');canvas.width=image.naturalHeight;canvas.height=image.naturalWidth
  const ctx=canvas.getContext('2d');ctx.translate(canvas.width,0);ctx.rotate(Math.PI/2);ctx.drawImage(image,0,0)
  const blob=await new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(new Error('图片导出失败')),'image/png'))
  return new File([blob],`${(asset.name||'图片').replace(/\.[^.]+$/,'')}-旋转.png`,{type:'image/png'})
}
export async function downloadAsset(asset) {
  const response=await fetch(asset.url);if(!response.ok)throw new Error('素材下载失败，请重试')
  const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=asset.name||'素材';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
