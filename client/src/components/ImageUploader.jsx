import React, { useState, useRef, useEffect } from 'react'
import { UploadCloud, X, Plus, Image as ImageIcon } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

const ImageUploader = ({ onImageUpload, maxImages = 1, existingImages = [], theme = 'dark', label = '// 视觉基底资产' }) => {
  const [images, setImages] = useState(existingImages)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef(null)

  const handleFileChange = (e) => processFiles(Array.from(e.target.files))

  const handleDrag = (e) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true)
    else if (e.type === "dragleave") setDragActive(false)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    processFiles(Array.from(e.dataTransfer.files).filter(file => file.type.startsWith('image/')))
  }

  useEffect(() => {
    const handlePaste = (e) => {
      const items = e.clipboardData.items
      const files = []
      for (let item of items) {
        if (item.type.indexOf('image') !== -1) files.push(item.getAsFile())
      }
      if (files.length > 0) processFiles(files)
    }
    document.addEventListener('paste', handlePaste)
    return () => document.removeEventListener('paste', handlePaste)
  }, [images, maxImages])

  const processFiles = (files) => {
    if (images.length >= maxImages) return alert(`最多允许上传 ${maxImages} 张图片`)
    const remainingSlots = maxImages - images.length
    const filesToProcess = files.slice(0, remainingSlots)

    const newImagePromises = filesToProcess.map(file => new Promise((resolve) => {
      const reader = new FileReader()
      reader.onload = (e) => resolve({ file: file, preview: e.target.result, name: file.name })
      reader.readAsDataURL(file)
    }))

    Promise.all(newImagePromises).then(newImages => {
      const updatedImages = [...images, ...newImages]
      setImages(updatedImages)
      onImageUpload(updatedImages)
    })
  }

  const removeImage = (index) => {
    const newImages = images.filter((_, i) => i !== index)
    setImages(newImages)
    onImageUpload(newImages)
  }

  const clearAll = () => {
    setImages([])
    onImageUpload([])
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className={`block text-xs font-bold tracking-widest uppercase font-mono ${theme === 'dark' ? 'text-violet-400' : 'text-violet-700'} flex items-center gap-2`}>
          <ImageIcon size={14} /> {label} {maxImages > 1 && `[ ${images.length} / ${maxImages} ]`}
        </label>
        {images.length > 0 && (
          <button onClick={clearAll} className="text-xs text-red-500 hover:text-red-400 font-bold tracking-widest uppercase transition-colors">
            清空资产
          </button>
        )}
      </div>

      <div
        className={`relative border-2 border-dashed transition-all duration-300 overflow-hidden ${
          dragActive 
            ? 'border-violet-500 bg-violet-500/10 scale-[1.02]' 
            : theme === 'dark' 
              ? 'border-violet-900/50 bg-black/40 hover:border-violet-500/50 hover:bg-violet-900/20' 
              : 'border-violet-300 bg-violet-50/50 hover:border-violet-400 hover:bg-violet-50'
        } ${images.length === 0 ? 'cursor-pointer py-10' : 'p-4'}`}
        onDragEnter={handleDrag} onDragLeave={handleDrag} onDragOver={handleDrag} onDrop={handleDrop}
        onClick={() => images.length === 0 && fileInputRef.current?.click()}
      >
        {/* 角标 */}
        <div className="absolute top-0 left-0 w-3 h-3 border-t border-l border-violet-500"></div>
        <div className="absolute top-0 right-0 w-3 h-3 border-t border-r border-violet-500"></div>
        <div className="absolute bottom-0 left-0 w-3 h-3 border-b border-l border-violet-500"></div>
        <div className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-violet-500"></div>

        <input ref={fileInputRef} type="file" accept="image/png, image/jpeg, image/webp" multiple={maxImages > 1} onChange={handleFileChange} className="hidden" />

        {images.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-center pointer-events-none">
            <div className={`w-16 h-16 mb-4 rounded-none flex items-center justify-center border transition-colors ${theme === 'dark' ? 'border-violet-900 bg-violet-950/50 text-violet-400 shadow-[0_0_20px_rgba(139,92,246,0.2)]' : 'border-violet-300 bg-white text-violet-500 shadow-sm'}`}>
              <UploadCloud size={32} />
            </div>
            <p className={`text-sm font-bold tracking-widest uppercase ${theme === 'dark' ? 'text-violet-300' : 'text-violet-700'}`}>
              点击或拖拽上传视觉基底
            </p>
            <p className={`text-xs mt-2 font-mono ${theme === 'dark' ? 'text-violet-600' : 'text-violet-400'}`}>
              支持 PNG, JPG, WEBP // 快捷键 (CTRL+V)
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className={`grid gap-3 ${maxImages === 1 ? 'grid-cols-1' : 'grid-cols-2 sm:grid-cols-3'}`}>
              <AnimatePresence>
                {images.map((img, index) => (
                  <motion.div
                    key={index + img.name}
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.9 }}
                    className={`relative group aspect-square overflow-hidden bg-black border ${theme === 'dark' ? 'border-violet-900' : 'border-violet-200'}`}
                  >
                    <img src={img.preview} alt={img.name} className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity" />
                    
                    {/* Hover 遮罩层 */}
                    <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center backdrop-blur-sm">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); removeImage(index); }}
                        className={`p-3 border transition-all ${theme === 'dark' ? 'border-red-500 text-red-500 bg-red-950/50 hover:bg-red-500 hover:text-white hover:shadow-[0_0_15px_rgba(239,68,68,0.5)]' : 'border-red-400 text-red-600 bg-white hover:bg-red-500 hover:text-white'}`}
                      >
                        <X size={20} />
                      </button>
                    </div>
                    
                    {maxImages > 1 && (
                      <div className={`absolute bottom-0 right-0 px-2 py-1 text-[10px] font-mono font-bold ${theme === 'dark' ? 'bg-violet-900/80 text-violet-300' : 'bg-violet-100 text-violet-700'}`}>
                        {index + 1}
                      </div>
                    )}
                  </motion.div>
                ))}
                
                {/* 内部添加按钮 */}
                {images.length > 0 && images.length < maxImages && (
                  <motion.button
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                    type="button"
                    onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }}
                    className={`aspect-square border-2 border-dashed flex flex-col items-center justify-center gap-2 transition-colors ${
                      theme === 'dark' ? 'border-violet-900 bg-black/40 hover:border-violet-500 hover:bg-violet-900/20' : 'border-violet-300 bg-violet-50/50 hover:border-violet-400 hover:bg-violet-100'
                    }`}
                  >
                    <Plus size={24} className={theme === 'dark' ? 'text-violet-500' : 'text-violet-400'} />
                    <span className={`text-xs font-bold tracking-widest uppercase ${theme === 'dark' ? 'text-violet-600' : 'text-violet-500'}`}>追加资产</span>
                  </motion.button>
                )}
              </AnimatePresence>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default ImageUploader
