import React, { useCallback, useEffect, useRef, useState } from 'react'
import { UploadCloud, X, Plus } from 'lucide-react'

const IMAGE_EXTENSION = /\.(avif|bmp|gif|heic|heif|jpe?g|png|webp)$/i

function isImageFile(file) {
  return file && (file.type?.startsWith('image/') || IMAGE_EXTENSION.test(file.name || ''))
}

const ImageToImage = ({ uploadedImages: rawImages, setUploadedImages, maxImages = 14 }) => {
  const uploadedImages = Array.isArray(rawImages) ? rawImages : []
  const fileInputRef = useRef(null)
  const dragDepthRef = useRef(0)
  const [isDragging, setIsDragging] = useState(false)

  const processFiles = useCallback((files) => {
    const imageFiles = Array.from(files || []).filter(isImageFile)
    if (imageFiles.length === 0) return
    const remainingSlots = maxImages - uploadedImages.length
    if (remainingSlots <= 0) return
    const filesToProcess = imageFiles.slice(0, remainingSlots)
    const newImagePromises = filesToProcess.map(file => new Promise((resolve) => {
      const reader = new FileReader()
      reader.onload = (ev) => resolve({ file, preview: ev.target.result, name: file.name })
      reader.onerror = () => resolve(null)
      reader.readAsDataURL(file)
    }))
    Promise.all(newImagePromises).then(newImages => {
      const readableImages = newImages.filter(Boolean)
      if (readableImages.length === 0) return
      setUploadedImages(current => [...current, ...readableImages].slice(0, maxImages))
    })
  }, [maxImages, setUploadedImages, uploadedImages.length])

  const handleFileChange = (event) => {
    processFiles(event.target.files)
    event.target.value = ''
  }

  const hasDraggedFiles = (event) => Array.from(event.dataTransfer?.types || []).includes('Files')

  const handleDragEnter = (event) => {
    if (!hasDraggedFiles(event)) return
    event.preventDefault()
    event.stopPropagation()
    dragDepthRef.current += 1
    if (uploadedImages.length < maxImages) setIsDragging(true)
  }

  const handleDragOver = (event) => {
    if (!hasDraggedFiles(event)) return
    event.preventDefault()
    event.stopPropagation()
    event.dataTransfer.dropEffect = uploadedImages.length < maxImages ? 'copy' : 'none'
  }

  const handleDragLeave = (event) => {
    if (!hasDraggedFiles(event)) return
    event.preventDefault()
    event.stopPropagation()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setIsDragging(false)
  }

  const handleDrop = (event) => {
    event.preventDefault()
    event.stopPropagation()
    dragDepthRef.current = 0
    setIsDragging(false)
    processFiles(event.dataTransfer?.files)
  }

  useEffect(() => {
    const handlePaste = (e) => {
      const files = []
      for (const item of e.clipboardData.items) {
        if (item.type.startsWith('image/')) files.push(item.getAsFile())
      }
      if (files.length > 0) processFiles(files)
    }
    document.addEventListener('paste', handlePaste)
    return () => document.removeEventListener('paste', handlePaste)
  }, [processFiles])

  const removeImage = (indexToRemove) => {
    setUploadedImages(current => current.filter((_, index) => index !== indexToRemove))
  }

  return (
    <div className="flex h-full min-h-[120px] flex-col">
      <div
        role="group"
        aria-label={isDragging ? '释放以添加参考图片' : '参考图片上传区'}
        data-testid="reference-drop-zone"
        data-dragging={isDragging ? 'true' : 'false'}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`relative flex flex-grow flex-col overflow-y-auto rounded-md border bg-nexus-bg p-2 custom-scrollbar transition-colors ${isDragging ? 'border-nexus-green bg-nexus-green/10 shadow-[inset_0_0_24px_rgba(53,208,138,0.12)]' : 'border-nexus-border'}`}
      >
        <input ref={fileInputRef} aria-label="选择参考图片" type="file" accept="image/*" multiple onChange={handleFileChange} className="hidden" />

        {isDragging && (
          <div className="pointer-events-none absolute inset-2 z-20 flex items-center justify-center rounded border border-dashed border-nexus-green bg-[#07120d]/95 text-nexus-green backdrop-blur-sm">
            <UploadCloud size={24} />
          </div>
        )}
        
        {uploadedImages.length > 0 ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(64px,1fr))] gap-2">
            {uploadedImages.map((img, index) => (
              <div key={index} className="group relative aspect-square min-w-0 overflow-hidden rounded border border-nexus-border bg-nexus-surface">
                <img src={img.preview} alt={`参考图片 ${index + 1}`} className="h-full w-full object-cover opacity-90 transition-opacity group-hover:opacity-100" />
                <button 
                  type="button"
                  aria-label={`删除参考图片 ${index + 1}`}
                  title="删除图片"
                  onClick={(e) => { e.stopPropagation(); removeImage(index); }} 
                  className="absolute right-1 top-1 rounded bg-black/75 p-1 text-nexus-text-light transition-colors hover:bg-nexus-red hover:text-white"
                >
                  <X size={12} />
                </button>
                <div className="absolute bottom-1 right-1 rounded bg-black/80 px-1 font-mono text-[10px] text-nexus-text">
                  {index + 1}
                </div>
              </div>
            ))}
            
            {uploadedImages.length < maxImages && (
              <button 
                type="button"
                aria-label="添加参考图片"
                title="添加参考图片"
                onClick={() => fileInputRef.current?.click()}
                className="aspect-square min-w-0 rounded border border-dashed border-nexus-border text-nexus-text transition-colors hover:border-nexus-green hover:bg-nexus-green/5 hover:text-nexus-green"
              >
                <Plus size={16} />
              </button>
            )}
          </div>
        ) : (
          <button 
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex min-h-[104px] flex-grow flex-col items-center justify-center gap-2 rounded border border-dashed border-nexus-border bg-nexus-surface/40 text-nexus-text transition-colors hover:border-nexus-green hover:bg-nexus-green/5 hover:text-nexus-green"
          >
            <UploadCloud size={20} />
            <span className="text-xs">添加参考图片</span>
            <span className="font-mono text-[10px] text-nexus-muted">0 / {maxImages}</span>
          </button>
        )}
      </div>
    </div>
  )
}

export default ImageToImage
