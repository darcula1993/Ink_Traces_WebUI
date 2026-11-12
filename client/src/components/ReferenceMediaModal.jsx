import React, { useEffect, useMemo, useState } from 'react'
import ReactDOM from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { AudioLines, Film, Image as ImageIcon, X } from 'lucide-react'
import IconButton from './ui/IconButton'

const MEDIA_LABELS = {
  image: '参考图片预览',
  video: '参考视频播放',
  audio: '参考音频播放',
}

const MEDIA_ICONS = {
  image: ImageIcon,
  video: Film,
  audio: AudioLines,
}

export default function ReferenceMediaModal({ media, onClose }) {
  const [objectUrl, setObjectUrl] = useState('')

  useEffect(() => {
    if (media?.src || media?.preview || !(media?.file instanceof Blob)) {
      setObjectUrl('')
      return undefined
    }
    const url = URL.createObjectURL(media.file)
    setObjectUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [media])

  useEffect(() => {
    if (!media) return undefined
    const handleKeyDown = event => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [media, onClose])

  const type = media?.type || 'image'
  const source = media?.src || media?.preview || objectUrl
  const label = MEDIA_LABELS[type] || '参考素材预览'
  const MediaIcon = useMemo(() => MEDIA_ICONS[type] || ImageIcon, [type])

  return ReactDOM.createPortal(
    <AnimatePresence>
      {media && (
        <motion.div
          className="reference-media-backdrop fixed inset-0 z-[1100] flex items-center justify-center p-10"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}
        >
          <motion.section
            role="dialog"
            aria-modal="true"
            aria-label={label}
            data-media-type={type}
            className="reference-media-modal liquid-glass-strong flex min-h-0 flex-col overflow-hidden"
            initial={{ opacity: 0, scale: 0.97, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 8 }}
          >
            <header className="flex h-12 shrink-0 items-center border-b border-white/10 px-3">
              <MediaIcon size={16} className="text-nexus-green" />
              <span className="ml-2 text-sm font-semibold text-nexus-text-light">{label}</span>
              {media.name && <span className="ml-3 min-w-0 truncate font-mono text-[11px] text-nexus-muted">{media.name}</span>}
              <div className="ml-auto">
                <IconButton label={`关闭${label}`} onClick={onClose}><X size={17} /></IconButton>
              </div>
            </header>

            <div className={`reference-media-stage flex min-h-0 flex-1 items-center justify-center overflow-hidden ${type === 'video' ? 'p-0' : 'p-5'}`}>
              {type === 'image' && source && (
                <img src={source} className="max-h-full max-w-full object-contain" alt={media.name || '参考图片全图'} />
              )}
              {type === 'video' && source && (
                <video
                  data-testid="reference-video-player"
                  src={source}
                  controls
                  preload="metadata"
                  className="size-full bg-black object-contain"
                />
              )}
              {type === 'audio' && source && (
                <div className="reference-audio-player flex w-full max-w-xl items-center gap-4 p-5">
                  <div className="flex size-12 shrink-0 items-center justify-center rounded-md border border-nexus-cyan/25 bg-nexus-cyan/10 text-nexus-cyan">
                    <AudioLines size={22} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="mb-3 truncate text-sm text-nexus-text-light">{media.name || '参考音频'}</div>
                    <audio data-testid="reference-audio-player" src={source} controls preload="metadata" className="w-full" />
                  </div>
                </div>
              )}
              {!source && <div className="text-sm text-nexus-muted">素材尚未准备完成</div>}
            </div>
          </motion.section>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
