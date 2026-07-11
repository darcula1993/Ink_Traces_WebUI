import React, { useState, useRef, useCallback } from 'react'
import ReactDOM from 'react-dom'
import { AlertTriangle, Download, Film, Maximize2, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import GenerationLoading from './GenerationLoading'

const VideoResultDisplay = ({ isLoading, videoUrl, lastFrameUrl, progress, error, taskStatus, taskId, provider }) => {
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [lastFrameExpanded, setLastFrameExpanded] = useState(false)

  // Draggable last frame
  const [framePos, setFramePos] = useState({ x: 16, y: 60 })
  const dragRef = useRef(null)
  const dragging = useRef(false)
  const dragOffset = useRef({ x: 0, y: 0 })

  const onDragStart = useCallback((e) => {
    if (e.target.tagName === 'BUTTON') return
    e.preventDefault()
    dragging.current = true
    const rect = dragRef.current.getBoundingClientRect()
    dragOffset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top }
    const parent = dragRef.current.parentElement.getBoundingClientRect()

    const onMove = (ev) => {
      if (!dragging.current) return
      setFramePos({
        x: Math.max(0, Math.min(ev.clientX - parent.left - dragOffset.current.x, parent.width - rect.width)),
        y: Math.max(0, Math.min(ev.clientY - parent.top - dragOffset.current.y, parent.height - rect.height))
      })
    }
    const onUp = () => {
      dragging.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [])

  if (isLoading) {
    return <GenerationLoading type="video" status={taskStatus || 'submitting'} progress={progress} taskId={taskId} provider={provider} />
  }

  if (error) {
    return (
      <div className="flex-grow flex flex-col items-center justify-center p-8 text-center">
        <AlertTriangle size={40} className="mb-5 text-nexus-red" />
        <h3 className="mb-2 text-base font-semibold text-nexus-text-light">视频生成失败</h3>
        <p className="max-w-md text-sm text-nexus-red">{error}</p>
      </div>
    )
  }

  if (videoUrl) {
    return (
      <>
        <div className="flex-grow flex flex-col h-full min-h-0 relative group">
          <div className="flex h-11 shrink-0 items-center justify-between border-b border-nexus-border bg-nexus-panel px-4">
            <div className="flex items-center gap-2 text-xs font-medium text-nexus-text-light">
              <span className="w-2 h-2 rounded-full bg-nexus-green"></span>
              视频结果
            </div>
            <div className="flex items-center gap-1">
              <button aria-label="全屏播放" title="全屏播放" onClick={() => setIsFullscreen(true)} className="icon-button size-8">
                <Maximize2 size={16} />
              </button>
              <a aria-label="下载视频" title="下载视频" href={videoUrl} download={`render_${Date.now()}.mp4`} className="icon-button size-8">
                <Download size={16} />
              </a>
            </div>
          </div>
          <div className="relative flex min-h-0 flex-grow items-center justify-center overflow-hidden bg-[#080a0d] p-4">
            <div className="absolute inset-0 bg-nexus-grid bg-nexus-grid-size opacity-30 pointer-events-none"></div>
            <video
              src={videoUrl}
              controls autoPlay loop
              className="max-w-full max-h-full object-contain shadow-2xl relative z-10 cursor-pointer"
              onClick={() => setIsFullscreen(true)}
            />

            {/* Last Frame Overlay */}
            {lastFrameUrl && (
              <div
                ref={dragRef}
                onMouseDown={onDragStart}
                className="absolute z-20 bg-[#0a0a0a]/90 border border-nexus-border backdrop-blur-sm shadow-2xl cursor-move select-none"
                style={{ left: framePos.x, top: framePos.y, width: lastFrameExpanded ? 320 : 140, height: lastFrameExpanded ? 'auto' : 100 }}
              >
                <div className="flex items-center justify-between px-2 py-1 border-b border-nexus-border/50">
                  <span className="text-[10px] font-medium text-nexus-text">尾帧</span>
                  <div className="flex gap-1">
                    <button aria-label="切换尾帧尺寸" title="切换尺寸" onClick={() => setLastFrameExpanded(!lastFrameExpanded)} className="text-nexus-text hover:text-nexus-green transition-colors">
                      <Maximize2 size={10} />
                    </button>
                    <a aria-label="下载尾帧" title="下载尾帧" href={lastFrameUrl} download={`lastframe_${Date.now()}.png`} className="text-nexus-text hover:text-nexus-green transition-colors">
                      <Download size={10} />
                    </a>
                  </div>
                </div>
                <img
                  src={lastFrameUrl}
                  alt="Last Frame"
                  className="w-full object-contain"
                  onClick={() => setLastFrameExpanded(!lastFrameExpanded)}
                  style={{ cursor: 'pointer' }}
                />
              </div>
            )}
          </div>
        </div>

        {ReactDOM.createPortal(
          <AnimatePresence>
            {isFullscreen && (
              <motion.div
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                role="dialog"
                aria-modal="true"
                aria-label="全屏视频预览"
                className="fixed inset-0 bg-black/95 z-[999] flex flex-col items-center justify-center p-8 backdrop-blur-sm"
                onClick={() => setIsFullscreen(false)}
              >
                <div className="absolute top-6 right-6 flex items-center gap-6 z-10">
                  <a aria-label="下载视频" title="下载视频" href={videoUrl} download={`render_${Date.now()}.mp4`} onClick={e => e.stopPropagation()} className="icon-button border-nexus-border bg-nexus-surface">
                    <Download size={20} />
                  </a>
                  <button aria-label="关闭全屏预览" title="关闭" onClick={() => setIsFullscreen(false)} className="icon-button border-nexus-border bg-nexus-surface hover:text-nexus-red">
                    <X size={20} />
                  </button>
                </div>
                <motion.video
                  initial={{ scale: 0.9, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.9, y: 20 }}
                  src={videoUrl}
                  controls autoPlay loop
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

  return (
    <div className="relative flex flex-grow flex-col items-center justify-center overflow-hidden bg-[#080a0d] p-8 text-center text-nexus-text">
      <div className="absolute inset-0 bg-nexus-grid bg-nexus-grid-size opacity-10 pointer-events-none"></div>
      <Film size={48} className="mb-4 opacity-15" strokeWidth={1.25} />
      <h3 className="mb-1 text-sm font-medium text-nexus-text-light">视频结果</h3>
      <p className="text-xs text-nexus-muted">生成结果将在这里显示</p>
    </div>
  )
}

export default VideoResultDisplay
