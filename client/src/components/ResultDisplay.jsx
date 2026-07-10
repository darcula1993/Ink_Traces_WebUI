import React, { useState, useEffect } from 'react'
import ReactDOM from 'react-dom'
import { AlertTriangle, Download, Terminal, Image as ImageIcon, Maximize2, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

const ResultDisplay = ({ isLoading, generatedImages, thinkingText, error, errorType, errorDetails }) => {
  const [currentImageIndex, setCurrentImageIndex] = useState(0)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [showThinking, setShowThinking] = useState(true)

  useEffect(() => { setCurrentImageIndex(0) }, [generatedImages])

  if (isLoading) {
    return (
      <div className="flex-grow flex flex-col items-center justify-center p-8 relative">
        <div className="w-20 h-20 border-2 border-nexus-border rounded-lg mb-6 relative flex items-center justify-center bg-[#050505]">
           <div className="absolute inset-3 border-2 border-nexus-green rounded-sm animate-[spin_2s_linear_infinite]"></div>
           <div className="absolute inset-0 border border-nexus-green/30 rounded-lg animate-pulse"></div>
        </div>
        <h3 className="text-sm font-mono tracking-widest text-nexus-text uppercase animate-pulse">Processing Matrix...</h3>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-grow flex flex-col items-center justify-center p-8 text-center">
        <AlertTriangle size={48} className="text-red-500 mb-6 drop-shadow-[0_0_10px_rgba(239,68,68,0.5)]" />
        <h3 className="text-lg font-bold font-mono text-red-500 uppercase mb-3">Execution Fault</h3>
        <p className="text-sm font-mono text-red-400/80 max-w-md">{error}</p>
        {errorDetails && errorDetails.message && (
          <div className="mt-6 p-4 border border-red-900/50 bg-red-950/20 text-left w-full max-w-lg shadow-xl">
            <p className="text-xs font-mono text-red-300/70 leading-relaxed">{errorDetails.message}</p>
          </div>
        )}
      </div>
    )
  }

  if (generatedImages && generatedImages.length > 0) {
    const currentImage = generatedImages[currentImageIndex]
    const normalizedImageUrl = String(currentImage || '').toLowerCase().split('?', 1)[0]
    const downloadExtension = normalizedImageUrl.startsWith('data:image/jpeg') || normalizedImageUrl.endsWith('.jpg') || normalizedImageUrl.endsWith('.jpeg') ? 'jpg' : 'png'

    return (
      <>
        <div className="flex-grow flex flex-col h-full min-h-0 relative group">
          
          {/* Top bar of canvas */}
          <div className="h-12 border-b border-nexus-border flex items-center justify-between px-6 shrink-0 bg-[#0f0f0f]">
            <div className="text-xs font-mono text-nexus-text tracking-widest flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-nexus-green"></span>
              CANVAS OUTPUT TERMINAL
            </div>
            <div className="flex items-center gap-4">
              <button onClick={() => setIsFullscreen(true)} className="text-nexus-text hover:text-white transition-colors">
                <Maximize2 size={16} />
              </button>
              <a href={currentImage} download={`render_${Date.now()}.${downloadExtension}`} className="text-nexus-text hover:text-white transition-colors">
                <Download size={16} />
              </a>
            </div>
          </div>

          {/* Main Canvas - Using a fixed layout that doesn't push bounds, relying on object-contain */}
          <div className="flex-grow min-h-0 relative overflow-hidden bg-[#050505] flex items-center justify-center p-4">
            
            {/* Grid background for canvas */}
            <div className="absolute inset-0 bg-nexus-grid bg-nexus-grid-size opacity-30 pointer-events-none"></div>

            <img
              src={currentImage}
              alt="Generated Output"
              className="max-w-full max-h-full object-contain shadow-2xl relative z-10 cursor-zoom-in"
              onClick={() => setIsFullscreen(true)}
            />

            {/* Thumbnail Navigation overlay if multiple images */}
            {generatedImages.length > 1 && (
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex gap-2 z-20 bg-black/80 p-2 rounded-lg border border-nexus-border backdrop-blur-md opacity-0 group-hover:opacity-100 transition-opacity">
                {generatedImages.map((img, idx) => (
                  <button 
                    key={idx} 
                    onClick={() => setCurrentImageIndex(idx)}
                    className={`w-12 h-12 rounded border ${idx === currentImageIndex ? 'border-nexus-green' : 'border-transparent opacity-50 hover:opacity-100'}`}
                  >
                    <img src={img} className="w-full h-full object-cover rounded-sm" alt="thumb" />
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Thinking Log Overlay */}
          {thinkingText && showThinking && (
            <div className="absolute top-16 left-6 w-96 bg-[#0a0a0a]/90 border border-nexus-border backdrop-blur-xl max-h-[400px] shadow-2xl z-20 flex flex-col">
              <div className="flex items-center gap-2 text-nexus-green px-5 pt-4 pb-3 border-b border-[#222] tracking-widest shrink-0">
                <Terminal size={14} /> <span className="uppercase font-bold text-xs">Runtime Log</span>
                <button onClick={() => setShowThinking(false)} className="ml-auto text-nexus-text hover:text-white transition-colors">
                  <X size={14} />
                </button>
              </div>
              <div className="text-nexus-text-light leading-relaxed whitespace-pre-wrap opacity-90 text-xs font-mono p-5 overflow-y-auto custom-scrollbar">
                {thinkingText}
              </div>
            </div>
          )}
          {thinkingText && !showThinking && (
            <button
              onClick={() => setShowThinking(true)}
              className="absolute top-16 left-6 z-20 flex items-center gap-2 px-3 py-2 bg-[#0a0a0a]/90 border border-nexus-border backdrop-blur-xl text-xs font-mono text-nexus-text hover:text-nexus-green transition-colors"
            >
              <Terminal size={12} /> LOG
            </button>
          )}
        </div>

        {/* Fullscreen Lightbox Modal */}
        {ReactDOM.createPortal(
        <AnimatePresence>
          {isFullscreen && (
            <motion.div 
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/95 z-[999] flex flex-col items-center justify-center p-8 backdrop-blur-sm"
              onClick={() => setIsFullscreen(false)}
            >
              <div className="absolute top-6 right-6 flex items-center gap-6 z-10">
                {generatedImages.length > 1 && (
                  <div className="text-nexus-text font-mono text-sm tracking-widest">
                    {currentImageIndex + 1} / {generatedImages.length}
                  </div>
                )}
                <a href={currentImage} download={`render_${Date.now()}.${downloadExtension}`} onClick={e => e.stopPropagation()} className="text-nexus-text hover:text-white transition-colors p-2 bg-[#111] rounded-lg border border-nexus-border hover:border-nexus-green">
                  <Download size={20} />
                </a>
                <button onClick={() => setIsFullscreen(false)} className="text-nexus-text hover:text-white transition-colors p-2 bg-[#111] rounded-lg border border-nexus-border hover:border-red-500">
                  <X size={20} />
                </button>
              </div>
              <motion.img
                initial={{ scale: 0.9, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.9, y: 20 }}
                src={currentImage}
                alt="Fullscreen Render"
                className="max-w-[95vw] max-h-[90vh] object-contain shadow-[0_0_50px_rgba(0,0,0,1)] border border-nexus-border/50"
                onClick={e => e.stopPropagation()}
              />
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
        )}
      </>
    )
  }

  // Empty State
  return (
    <div className="flex-grow flex flex-col items-center justify-center p-8 text-center text-nexus-text relative overflow-hidden bg-[#0a0a0a]">
      <div className="absolute inset-0 bg-nexus-grid bg-nexus-grid-size opacity-10 pointer-events-none"></div>
      <ImageIcon size={64} className="opacity-10 mb-6" strokeWidth={1} />
      <h3 className="text-sm font-mono tracking-[0.2em] uppercase mb-4 opacity-50">Canvas Output Terminal</h3>
      <div className="px-6 py-3 border border-nexus-border border-dashed rounded-lg text-xs font-mono opacity-40 bg-[#111]">
        Waiting for execution run...
      </div>
    </div>
  )
}

export default ResultDisplay
