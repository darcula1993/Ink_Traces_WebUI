import React, { useRef, useEffect } from 'react'
import { UploadCloud, X, Plus } from 'lucide-react'

const ImageToImage = ({ uploadedImages: rawImages, setUploadedImages, maxImages = 14 }) => {
  const uploadedImages = Array.isArray(rawImages) ? rawImages : []
  const fileInputRef = useRef(null)

  const processFiles = (files) => {
    if (files.length === 0) return
    const remainingSlots = maxImages - uploadedImages.length
    const filesToProcess = files.slice(0, remainingSlots)
    const newImagePromises = filesToProcess.map(file => new Promise((resolve) => {
      const reader = new FileReader()
      reader.onload = (ev) => resolve({ file, preview: ev.target.result, name: file.name })
      reader.readAsDataURL(file)
    }))
    Promise.all(newImagePromises).then(newImages => {
      setUploadedImages([...uploadedImages, ...newImages])
    })
  }

  const handleFileChange = (e) => processFiles(Array.from(e.target.files))

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
  })

  const removeImage = (indexToRemove) => {
    setUploadedImages(uploadedImages.filter((_, index) => index !== indexToRemove))
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex-grow border border-nexus-border rounded-lg bg-[#0a0a0a] p-3 overflow-y-auto custom-scrollbar flex flex-col">
        <input ref={fileInputRef} type="file" accept="image/*" multiple onChange={handleFileChange} className="hidden" />
        
        {uploadedImages.length > 0 ? (
          <div className="flex gap-2 flex-wrap" style={{ minWidth: Math.ceil((uploadedImages.length + 1) / 2) * 90 }}>
            {uploadedImages.map((img, index) => (
              <div key={index} className="w-20 h-20 relative group rounded overflow-hidden border border-nexus-border shrink-0">
                <img src={img.preview} alt={`Upload ${index}`} className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity" />
                <button 
                  onClick={(e) => { e.stopPropagation(); removeImage(index); }} 
                  className="absolute top-1 right-1 p-1 bg-red-900/80 text-red-400 rounded hover:bg-red-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X size={12} />
                </button>
                <div className="absolute bottom-1 right-1 text-[10px] font-mono bg-black/80 text-nexus-text px-1 rounded">
                  {index + 1}
                </div>
              </div>
            ))}
            
            {uploadedImages.length < maxImages && (
              <button 
                onClick={() => fileInputRef.current?.click()}
                className="w-20 h-20 shrink-0 border border-dashed border-nexus-border rounded flex flex-col items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors"
              >
                <Plus size={16} />
              </button>
            )}
          </div>
        ) : (
          <button 
            onClick={() => fileInputRef.current?.click()}
            className="flex-grow flex flex-col items-center justify-center gap-3 border border-dashed border-nexus-border rounded-lg text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors bg-[#111]"
          >
            <UploadCloud size={20} />
            <span className="text-xs font-mono">Mount Image [0/{maxImages}]</span>
          </button>
        )}
      </div>
    </div>
  )
}

export default ImageToImage