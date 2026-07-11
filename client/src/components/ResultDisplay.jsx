import React, { useState, useEffect } from 'react'
import ReactDOM from 'react-dom'
import { AlertTriangle, Download, Terminal, Image as ImageIcon, Maximize2, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import GenerationLoading from './GenerationLoading'

const ResultDisplay = ({ isLoading, generatedImages, thinkingText, error, errorType, errorDetails, taskStatus, taskId, provider }) => {
  const [currentImageIndex, setCurrentImageIndex] = useState(0)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [showThinking, setShowThinking] = useState(true)

  useEffect(() => { setCurrentImageIndex(0) }, [generatedImages])

  if (isLoading) {
    return <GenerationLoading type="image" status={taskStatus || 'submitting'} taskId={taskId} provider={provider} />
  }

  if (error) {
    return (
      <div className="flex-grow flex flex-col items-center justify-center p-8 text-center">
        <AlertTriangle size={40} className="mb-5 text-nexus-red" />
        <h3 className="mb-2 text-base font-semibold text-nexus-text-light">图片生成失败</h3>
        <p className="max-w-md text-sm text-nexus-red">{error}</p>
        {errorDetails && errorDetails.message && (
          <div className="mt-5 w-full max-w-lg rounded-md border border-nexus-red/30 bg-nexus-red/5 p-4 text-left">
            <p className="text-xs font-mono leading-relaxed text-nexus-text">{errorDetails.message}</p>
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
          <div className="flex h-11 shrink-0 items-center justify-between border-b border-nexus-border bg-nexus-panel px-4">
            <div className="flex items-center gap-2 text-xs font-medium text-nexus-text-light">
              <span className="w-2 h-2 rounded-full bg-nexus-green"></span>
              图片结果
            </div>
            <div className="flex items-center gap-1">
              <button aria-label="全屏查看" title="全屏查看" onClick={() => setIsFullscreen(true)} className="icon-button size-8">
                <Maximize2 size={16} />
              </button>
              <a aria-label="下载图片" title="下载图片" href={currentImage} download={`render_${Date.now()}.${downloadExtension}`} className="icon-button size-8">
                <Download size={16} />
              </a>
            </div>
          </div>

          {/* Main Canvas - Using a fixed layout that doesn't push bounds, relying on object-contain */}
          <div className="relative flex min-h-0 flex-grow items-center justify-center overflow-hidden bg-[#080a0d] p-4">
            
            {/* Grid background for canvas */}
            <div className="absolute inset-0 bg-nexus-grid bg-nexus-grid-size opacity-30 pointer-events-none"></div>

            <img
              src={currentImage}
              alt="生成结果"
              className="max-w-full max-h-full object-contain shadow-2xl relative z-10 cursor-zoom-in"
              onClick={() => setIsFullscreen(true)}
            />

            {/* Thumbnail Navigation overlay if multiple images */}
            {generatedImages.length > 1 && (
              <div className="absolute bottom-4 left-1/2 z-20 flex -translate-x-1/2 gap-2 rounded-md border border-nexus-border bg-black/80 p-2 backdrop-blur-md">
                {generatedImages.map((img, idx) => (
                  <button 
                    key={idx} 
                    onClick={() => setCurrentImageIndex(idx)}
                    aria-label={`查看第 ${idx + 1} 张图片`}
                    className={`h-12 w-12 rounded border ${idx === currentImageIndex ? 'border-nexus-green' : 'border-transparent opacity-60 hover:opacity-100'}`}
                  >
                    <img src={img} className="w-full h-full object-cover rounded-sm" alt="" />
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Thinking Log Overlay */}
          {thinkingText && showThinking && (
            <div className="absolute left-4 top-14 z-20 flex max-h-[400px] w-[min(384px,calc(100%-32px))] flex-col rounded-md border border-nexus-border bg-nexus-panel/95 shadow-2xl backdrop-blur-xl">
              <div className="flex shrink-0 items-center gap-2 border-b border-nexus-border px-4 py-3 text-nexus-green">
                <Terminal size={14} /> <span className="text-xs font-semibold">思考过程</span>
                <button aria-label="关闭思考过程" title="关闭" onClick={() => setShowThinking(false)} className="ml-auto text-nexus-text hover:text-white transition-colors">
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
              className="btn-base btn-outline absolute left-4 top-14 z-20 min-h-8 px-2 text-xs"
            >
              <Terminal size={12} /> 思考过程
            </button>
          )}
        </div>

        {/* Fullscreen Lightbox Modal */}
        {ReactDOM.createPortal(
        <AnimatePresence>
          {isFullscreen && (
            <motion.div 
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              role="dialog"
              aria-modal="true"
              aria-label="全屏图片预览"
              className="fixed inset-0 bg-black/95 z-[999] flex flex-col items-center justify-center p-8 backdrop-blur-sm"
              onClick={() => setIsFullscreen(false)}
            >
              <div className="absolute top-6 right-6 flex items-center gap-6 z-10">
                {generatedImages.length > 1 && (
                  <div className="text-nexus-text font-mono text-sm tracking-widest">
                    {currentImageIndex + 1} / {generatedImages.length}
                  </div>
                )}
                <a aria-label="下载图片" title="下载图片" href={currentImage} download={`render_${Date.now()}.${downloadExtension}`} onClick={e => e.stopPropagation()} className="icon-button border-nexus-border bg-nexus-surface">
                  <Download size={20} />
                </a>
                <button aria-label="关闭全屏预览" title="关闭" onClick={() => setIsFullscreen(false)} className="icon-button border-nexus-border bg-nexus-surface hover:text-nexus-red">
                  <X size={20} />
                </button>
              </div>
              <motion.img
                initial={{ scale: 0.9, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.9, y: 20 }}
                src={currentImage}
                alt="全屏生成结果"
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
    <div className="relative flex flex-grow flex-col items-center justify-center overflow-hidden bg-[#080a0d] p-8 text-center text-nexus-text">
      <div className="absolute inset-0 bg-nexus-grid bg-nexus-grid-size opacity-10 pointer-events-none"></div>
      <ImageIcon size={48} className="mb-4 opacity-15" strokeWidth={1.25} />
      <h3 className="mb-1 text-sm font-medium text-nexus-text-light">图片结果</h3>
      <p className="text-xs text-nexus-muted">生成结果将在这里显示</p>
    </div>
  )
}

export default ResultDisplay
