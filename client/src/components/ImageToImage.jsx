import React, { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { Maximize2, UploadCloud, X, Plus, RotateCw } from 'lucide-react'
import SortableReferenceItem, { moveArrayItem } from './SortableReferenceItem'
import { persistWorkspaceBlob, workspaceImageFields } from '../lib/useWorkspaceState'
import { LIBRARY_MEDIA_URL_PATTERN } from '../lib/referenceMedia'
import { DropTargetReticle } from './art/ShellEmptyArt'

const IMAGE_EXTENSION = /\.(avif|bmp|gif|heic|heif|jpe?g|png|webp)$/i
const MAX_METADATA_CACHE_ENTRIES = 256
const libraryImageMetadataCache = new Map()
let nextReferenceId = 0

function rememberLibraryMetadata(url, meta) {
  if (libraryImageMetadataCache.size >= MAX_METADATA_CACHE_ENTRIES) {
    const oldest = libraryImageMetadataCache.keys().next().value
    if (oldest !== undefined) libraryImageMetadataCache.delete(oldest)
  }
  libraryImageMetadataCache.set(url, meta)
}

function isImageFile(file) {
  return file && (file.type?.startsWith('image/') || IMAGE_EXTENSION.test(file.name || ''))
}

const ImageToImage = ({ uploadedImages: rawImages, setUploadedImages, createPreviewUrl, onPreview, maxImages = 14 }) => {
  const uploadedImages = Array.isArray(rawImages) ? rawImages : []
  const fileInputRef = useRef(null)
  const dragDepthRef = useRef(0)
  const [isDragging, setIsDragging] = useState(false)
  const attemptedFiles = useRef(new WeakSet())
  const attemptedMetadata = useRef(new Set())
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const uploadImage = useCallback(image => {
    attemptedFiles.current.add(image.file)
    persistWorkspaceBlob('img_tabs', image.file, image.name).then(asset => {
      setUploadedImages(current => current.map(item => item.file === image.file
        ? { ...item, ...workspaceImageFields(asset), file: null, uploadError: false }
        : item))
    }).catch(() => {
      setUploadedImages(current => current.map(item => item.file === image.file
        ? { ...item, uploadError: true }
        : item))
    })
  }, [setUploadedImages])

  useEffect(() => {
    uploadedImages.forEach(image => {
      if (image.file instanceof Blob && !image.uploadError && !attemptedFiles.current.has(image.file)) uploadImage(image)
    })
  }, [uploadedImages, uploadImage])

  useEffect(() => {
    uploadedImages.forEach(image => {
      if (image.file || typeof image.hasAlpha === 'boolean') return
      const url = typeof image.preview === 'string' ? image.preview : ''
      if (!LIBRARY_MEDIA_URL_PATTERN.test(url)) return
      const cached = libraryImageMetadataCache.get(url)
      if (cached) {
        setUploadedImages(current => current.map(item => (
          item.preview === url && typeof item.hasAlpha !== 'boolean'
            ? {
                ...item,
                hasAlpha: cached.hasAlpha,
                ...(item.width > 0 ? {} : cached.width > 0 ? { width: cached.width } : {}),
                ...(item.height > 0 ? {} : cached.height > 0 ? { height: cached.height } : {}),
              }
            : item
        )))
        return
      }
      if (attemptedMetadata.current.has(url)) return
      attemptedMetadata.current.add(url)
      axios.get(`${url}/metadata`).then(response => {
        const meta = response.data?.metadata
        if (!meta || typeof meta.has_alpha !== 'boolean') return
        const resolved = {
          hasAlpha: meta.has_alpha,
          width: Number(meta.width) > 0 ? Number(meta.width) : undefined,
          height: Number(meta.height) > 0 ? Number(meta.height) : undefined,
        }
        rememberLibraryMetadata(url, resolved)
        if (!mountedRef.current) return
        setUploadedImages(current => current.map(item => (
          item.preview === url && typeof item.hasAlpha !== 'boolean'
            ? {
                ...item,
                hasAlpha: resolved.hasAlpha,
                ...(item.width > 0 ? {} : resolved.width ? { width: resolved.width } : {}),
                ...(item.height > 0 ? {} : resolved.height ? { height: resolved.height } : {}),
              }
            : item
        )))
      }).catch(() => {})
    })
  }, [uploadedImages, setUploadedImages])

  const processFiles = useCallback((files) => {
    const imageFiles = Array.from(files || []).filter(isImageFile)
    if (imageFiles.length === 0) return
    const additions = imageFiles.slice(0, maxImages).map(file => ({
      uid: `image-${Date.now()}-${++nextReferenceId}`, file, preview: createPreviewUrl(file), name: file.name, hasAlpha: null,
    }))
    setUploadedImages(current => [...current, ...additions.slice(0, Math.max(0, maxImages - current.length))])
  }, [createPreviewUrl, maxImages, setUploadedImages])

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

  const moveImage = useCallback((fromIndex, toIndex) => {
    setUploadedImages(current => moveArrayItem(current, fromIndex, toIndex))
  }, [setUploadedImages])

  const recordImageDimensions = useCallback((image, width, height) => {
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return
    if (Number(image.width) > 0 && Number(image.height) > 0) return
    setUploadedImages(current => current.map(item => (
      item === image || (image.preview && item.preview === image.preview)
        ? { ...item, width, height }
        : item
    )))
  }, [setUploadedImages])

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
          <div className="drop-reticle-overlay" data-testid="reference-drop-overlay" aria-hidden="true">
            <span className="drop-reticle-corner is-tl" />
            <span className="drop-reticle-corner is-tr" />
            <span className="drop-reticle-corner is-bl" />
            <span className="drop-reticle-corner is-br" />
            <DropTargetReticle size={24} />
            <span className="drop-reticle-label">松开以添加参考图片</span>
          </div>
        )}
        
        {uploadedImages.length > 0 ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(64px,1fr))] gap-2">
            {uploadedImages.map((img, index) => (
              <SortableReferenceItem
                key={img.uid || img.preview || index}
                listId="image-generation-references"
                index={index}
                itemCount={uploadedImages.length}
                label="参考图片"
                onMove={moveImage}
                testId={`image-reference-item-${index}`}
                className="group relative aspect-square min-w-0 overflow-hidden rounded border border-nexus-border bg-nexus-surface"
              >
                <button
                  type="button"
                  aria-label={`打开参考图片 ${index + 1}`}
                  title="查看全图"
                  onClick={() => onPreview?.({ type: 'image', src: img.preview, name: img.name || `参考图片 ${index + 1}` })}
                  className="absolute inset-0 cursor-zoom-in outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-green"
                >
                  <img
                    src={img.thumbnail || img.preview}
                    alt={`参考图片 ${index + 1}`}
                    onLoad={event => {
                      if (!img.thumbnail) recordImageDimensions(img, event.currentTarget.naturalWidth, event.currentTarget.naturalHeight)
                    }}
                    className="h-full w-full object-cover opacity-90 transition-opacity group-hover:opacity-100"
                  />
                  <span className="absolute bottom-1 left-1 flex size-5 items-center justify-center rounded bg-black/70 text-white opacity-0 transition-opacity group-hover:opacity-100">
                    <Maximize2 size={11} />
                  </span>
                </button>
                {img.uploadError && (
                  <button
                    type="button"
                    aria-label={`重试上传参考图片 ${index + 1}`}
                    title="上传失败，重试"
                    onClick={() => {
                      setUploadedImages(current => current.map(item => item.file === img.file ? { ...item, uploadError: false } : item))
                      uploadImage(img)
                    }}
                    className="absolute bottom-1 left-1 z-10 rounded bg-black/80 p-1 text-nexus-red"
                  >
                    <RotateCw size={14} />
                  </button>
                )}
                <button 
                  type="button"
                  aria-label={`删除参考图片 ${index + 1}`}
                  title="删除图片"
                  onClick={(e) => { e.stopPropagation(); removeImage(index); }} 
                  className="absolute right-1 top-1 z-10 rounded bg-black/75 p-1 text-nexus-text-light transition-colors hover:bg-nexus-red hover:text-white"
                >
                  <X size={12} />
                </button>
                <div className="pointer-events-none absolute bottom-1 right-1 rounded bg-black/80 px-1 font-mono text-xs text-nexus-text">
                  {img.hasAlpha ? 'α' : index + 1}
                </div>
              </SortableReferenceItem>
            ))}
            
            {uploadedImages.length < maxImages && (
              <button 
                type="button"
                aria-label="添加参考图片"
                title="添加参考图片"
                onClick={() => fileInputRef.current?.click()}
                className="flex aspect-square min-w-0 items-center justify-center rounded border border-dashed border-nexus-border text-nexus-text transition-colors hover:border-nexus-green hover:bg-nexus-green/5 hover:text-nexus-green"
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
            <span className="font-mono text-xs text-nexus-muted">0 / {maxImages}</span>
          </button>
        )}
      </div>
    </div>
  )
}

export default ImageToImage
