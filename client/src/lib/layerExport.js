// Export originals sequentially: thumbnail previews never become the saved composite.
export async function renderLayerDocument(documentState, format='png') {
 const {width,height}=documentState.canvas
 if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width*height>16000000||Math.max(width,height)>8192)throw Error('导出画布最多1600万像素、单边8192像素')
 const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height
 const ctx=canvas.getContext('2d')
 if(format==='jpeg'){ctx.fillStyle='#fff';ctx.fillRect(0,0,width,height)}
 for(const item of documentState.layers){
  if(!item.visible)continue
  const image=new Image();image.src=item.local_url
  try{await image.decode();ctx.save();ctx.translate(Number(item.x)||0,Number(item.y)||0);ctx.rotate((Number(item.rotation)||0)*Math.PI/180);ctx.globalAlpha=Math.max(0,Math.min(1,Number(item.opacity??1)));ctx.drawImage(image,0,0,item.display_width||image.width,item.display_height||image.height);ctx.restore()}finally{image.src=''}
 }
 return new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(Error('导出失败')),format==='jpeg'?'image/jpeg':'image/png',.95))
}
