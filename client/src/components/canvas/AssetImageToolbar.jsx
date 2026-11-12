import React from 'react'
export default function AssetImageToolbar({style,busy,onRotate,onAnnotate,onDownload,onPreview}) {
 return <div className="cv-image-toolbar" style={style} role="toolbar" aria-label="图片素材工具" onPointerDown={e=>e.stopPropagation()}><button disabled={busy} onClick={onRotate}>旋转</button><button disabled={busy} onClick={onAnnotate}>标注</button><button disabled={busy} onClick={onDownload}>下载</button><button disabled={busy} onClick={onPreview}>预览</button></div>
}
