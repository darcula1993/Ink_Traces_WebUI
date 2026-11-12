const browserImages=new Set(['image/png','image/jpeg','image/webp','image/gif','image/avif','image/bmp','image/x-icon','image/vnd.microsoft.icon','image/svg+xml','image/apng'])
export const canEditLibraryImage=asset=>asset.kind==='image'&&browserImages.has(asset.mime_type)
export function libraryPreviewAsset(item){
 const asset=item.asset
 return asset.kind==='image'&&!browserImages.has(asset.mime_type)&&item.thumbnail_url
  ?{...asset,url:item.thumbnail_url,previewNotice:'此格式使用缩略图预览；下载保留原始文件与分辨率。'}:asset
}
