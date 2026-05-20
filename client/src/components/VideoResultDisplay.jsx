import React, { useState, useRef, useCallback, useEffect } from 'react'
import ReactDOM from 'react-dom'
import { AlertTriangle, Download, Film, Maximize2, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

const VideoResultDisplay = ({ isLoading, videoUrl, lastFrameUrl, progress, error, eta }) => {
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [lastFrameExpanded, setLastFrameExpanded] = useState(false)

  // 模拟进度 + 计时
  const [elapsed, setElapsed] = useState(0)
  const timerRef = useRef(null)

  useEffect(() => {
    if (isLoading) {
      setElapsed(0)
      timerRef.current = setInterval(() => setElapsed(t => t + 1), 1000)
    } else {
      clearInterval(timerRef.current)
    }
    return () => clearInterval(timerRef.current)
  }, [isLoading])

  // 视频一般 60-180s，用对数曲线模拟到 95% 封顶
  const simProgress = isLoading ? Math.min(95, Math.round(30 * Math.log(1 + elapsed / 10))) : 0
  const formatTime = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

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
    return (
      <div className="flex-grow flex flex-col items-center justify-center p-8 relative">
        <div className="w-20 h-20 border-2 border-nexus-border rounded-lg mb-6 relative flex items-center justify-center bg-[#050505]">
          <div className="absolute inset-3 border-2 border-nexus-green rounded-sm animate-[spin_2s_linear_infinite]"></div>
          <div className="absolute inset-0 border border-nexus-green/30 rounded-lg animate-pulse"></div>
        </div>
        <h3 className="text-sm font-mono tracking-widest text-nexus-text uppercase animate-pulse">Rendering Video...</h3>
        <div className="mt-4 w-56">
          <div className="h-1 bg-nexus-border rounded-full overflow-hidden">
            <div className="h-full bg-nexus-green transition-all duration-1000 ease-out" style={{ width: `${progress > 0 ? progress : simProgress}%` }} />
          </div>
          <div className="text-xs font-mono text-nexus-text mt-2 text-center">
            {progress > 0 ? `${progress}%` : `~${simProgress}%`} · {formatTime(elapsed)}{eta > 0 ? ` · ETA ${eta}s` : ''}
          </div>
          <div className="text-[10px] font-mono text-nexus-text/40 mt-1 text-center">
            {elapsed < 30 ? 'Queuing...' : elapsed < 90 ? 'Generating frames...' : 'Encoding video...'}
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-grow flex flex-col items-center justify-center p-8 text-center">
        <AlertTriangle size={48} className="text-red-500 mb-6 drop-shadow-[0_0_10px_rgba(239,68,68,0.5)]" />
        <h3 className="text-lg font-bold font-mono text-red-500 uppercase mb-3">Render Fault</h3>
        <p className="text-sm font-mono text-red-400/80 max-w-md">{error}</p>
      </div>
    )
  }

  if (videoUrl) {
    return (
      <>
        <div className="flex-grow flex flex-col h-full min-h-0 relative group">
          <div className="h-12 border-b border-nexus-border flex items-center justify-between px-6 shrink-0 bg-[#0f0f0f]">
            <div className="text-xs font-mono text-nexus-text tracking-widest flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-nexus-green"></span>
              VIDEO OUTPUT TERMINAL
            </div>
            <div className="flex items-center gap-4">
              <button onClick={() => setIsFullscreen(true)} className="text-nexus-text hover:text-white transition-colors">
                <Maximize2 size={16} />
              </button>
              <a href={videoUrl} download={`render_${Date.now()}.mp4`} className="text-nexus-text hover:text-white transition-colors">
                <Download size={16} />
              </a>
            </div>
          </div>
          <div className="flex-grow min-h-0 relative overflow-hidden bg-[#050505] flex items-center justify-center p-4">
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
                  <span className="text-[9px] font-mono text-nexus-text tracking-widest">LAST FRAME</span>
                  <div className="flex gap-1">
                    <button onClick={() => setLastFrameExpanded(!lastFrameExpanded)} className="text-nexus-text hover:text-nexus-green transition-colors">
                      <Maximize2 size={10} />
                    </button>
                    <a href={lastFrameUrl} download={`lastframe_${Date.now()}.png`} className="text-nexus-text hover:text-nexus-green transition-colors">
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
                className="fixed inset-0 bg-black/95 z-[999] flex flex-col items-center justify-center p-8 backdrop-blur-sm"
                onClick={() => setIsFullscreen(false)}
              >
                <div className="absolute top-6 right-6 flex items-center gap-6 z-10">
                  <a href={videoUrl} download={`render_${Date.now()}.mp4`} onClick={e => e.stopPropagation()} className="text-nexus-text hover:text-white transition-colors p-2 bg-[#111] rounded-lg border border-nexus-border hover:border-nexus-green">
                    <Download size={20} />
                  </a>
                  <button onClick={() => setIsFullscreen(false)} className="text-nexus-text hover:text-white transition-colors p-2 bg-[#111] rounded-lg border border-nexus-border hover:border-red-500">
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
    <div className="flex-grow flex flex-col items-center justify-center p-8 text-center text-nexus-text relative overflow-hidden bg-[#0a0a0a]">
      <div className="absolute inset-0 bg-nexus-grid bg-nexus-grid-size opacity-10 pointer-events-none"></div>
      <Film size={64} className="opacity-10 mb-6" strokeWidth={1} />
      <h3 className="text-sm font-mono tracking-[0.2em] uppercase mb-4 opacity-50">Video Output Terminal</h3>
      <div className="px-6 py-3 border border-nexus-border border-dashed rounded-lg text-xs font-mono opacity-40 bg-[#111]">
        Waiting for render job...
      </div>
    </div>
  )
}

export default VideoResultDisplay
