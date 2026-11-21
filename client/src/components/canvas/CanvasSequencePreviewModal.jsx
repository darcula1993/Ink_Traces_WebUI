import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Clapperboard,
  GripVertical,
  Music,
  Pause,
  Play,
  Repeat,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react'
import './canvasSequencePreview.css'

const FOCUSABLE_SELECTOR =
  'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])'

export function isUsableVideoNode(node, isGone) {
  if (!node || typeof node !== 'object' || !node.id) return false
  const asset = node.asset
  if (!asset || typeof asset !== 'object' || !asset.url || asset.deleted === true) return false
  const isVideo = asset.kind === 'video' || (node.type === 'video' && asset.kind == null)
  if (!isVideo) return false
  if (typeof isGone === 'function' && isGone(asset)) return false
  return true
}

export function isUsableAudioNode(node, isGone) {
  if (!node || typeof node !== 'object' || !node.id) return false
  const asset = node.asset
  if (!asset || typeof asset !== 'object' || !asset.url || asset.deleted === true) return false
  const isAudio = asset.kind === 'audio' || (node.type === 'audio' && asset.kind == null)
  if (!isAudio) return false
  if (typeof isGone === 'function' && isGone(asset)) return false
  return true
}

export function sortNodesByCanvasPosition(nodes = []) {
  return [...(nodes || [])].sort((a, b) => {
    const rowA = Math.floor((Number(a?.y) || 0) / 240)
    const rowB = Math.floor((Number(b?.y) || 0) / 240)
    if (rowA !== rowB) return rowA - rowB
    const xDiff = (Number(a?.x) || 0) - (Number(b?.x) || 0)
    if (xDiff !== 0) return xDiff
    const yDiff = (Number(a?.y) || 0) - (Number(b?.y) || 0)
    if (yDiff !== 0) return yDiff
    return String(a?.id || '').localeCompare(String(b?.id || ''))
  })
}

export function formatSequenceTime(seconds) {
  const numeric = Number(seconds)
  if (!Number.isFinite(numeric) || numeric < 0) return '00:00'
  const whole = Math.floor(numeric)
  const mins = Math.floor(whole / 60)
  const secs = whole % 60
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

function reorderList(ids, fromIndex, toIndex) {
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0 || fromIndex >= ids.length || toIndex >= ids.length) {
    return ids
  }
  const next = [...ids]
  const [moved] = next.splice(fromIndex, 1)
  next.splice(toIndex, 0, moved)
  return next
}

/**
 * Pure browser read-only storyboard shot-sequence preview modal.
 * Strictly read-only: never modifies canvas documents, never edits/trims/renders/exports video.
 */
export default function CanvasSequencePreviewModal({ nodes = [], isGone, onClose }) {
  const dialogRef = useRef(null)
  const videoRef = useRef(null)
  const audioRef = useRef(null)
  const playIntentRef = useRef(false)

  const videoNodes = useMemo(
    () => sortNodesByCanvasPosition((nodes || []).filter(node => isUsableVideoNode(node, isGone))),
    [nodes, isGone],
  )
  const audioNodes = useMemo(
    () => sortNodesByCanvasPosition((nodes || []).filter(node => isUsableAudioNode(node, isGone))),
    [nodes, isGone],
  )
  const videoById = useMemo(() => new Map(videoNodes.map(node => [node.id, node])), [videoNodes])

  const [orderIds, setOrderIds] = useState(() => videoNodes.map(node => node.id))
  const [enabledIds, setEnabledIds] = useState(() => new Set(videoNodes.map(node => node.id)))
  const [onlyFinalized, setOnlyFinalized] = useState(false)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [loop, setLoop] = useState(false)
  const [videoMuted, setVideoMuted] = useState(false)
  const [videoTime, setVideoTime] = useState(0)
  const [videoDuration, setVideoDuration] = useState(0)
  const [dragId, setDragId] = useState(null)
  const [dragOverId, setDragOverId] = useState(null)

  // Opt-in single audio node sync: defaults to none + muted + 50% volume so opening never blasts sound.
  const [selectedAudioId, setSelectedAudioId] = useState('')
  const [audioMuted, setAudioMuted] = useState(true)
  const [audioVolume, setAudioVolume] = useState(0.5)

  playIntentRef.current = isPlaying

  // Keep orderIds and enabledIds reconciled if nodes update while open.
  useEffect(() => {
    const liveIds = videoNodes.map(node => node.id)
    const liveSet = new Set(liveIds)
    setOrderIds(prev => {
      const kept = prev.filter(id => liveSet.has(id))
      const added = liveIds.filter(id => !kept.includes(id))
      return [...kept, ...added]
    })
    setEnabledIds(prev => new Set([...prev].filter(id => liveSet.has(id))))
  }, [videoNodes])

  useEffect(() => {
    if (selectedAudioId && !audioNodes.some(node => node.id === selectedAudioId)) {
      setSelectedAudioId('')
    }
  }, [audioNodes, selectedAudioId])

  // Focus management: focus modal on mount, return focus to opener on unmount.
  useEffect(() => {
    const previous = document.activeElement
    dialogRef.current?.focus({ preventScroll: true })
    return () => {
      if (previous && previous.isConnected && typeof previous.focus === 'function') {
        previous.focus({ preventScroll: true })
      }
    }
  }, [])

  const orderedClips = useMemo(
    () => orderIds.map(id => videoById.get(id)).filter(Boolean),
    [orderIds, videoById],
  )
  const finalizedCount = useMemo(
    () => orderedClips.filter(node => node.finalized === true).length,
    [orderedClips],
  )
  const visibleClips = useMemo(
    () => (onlyFinalized ? orderedClips.filter(node => node.finalized === true) : orderedClips),
    [orderedClips, onlyFinalized],
  )
  const activeClips = useMemo(
    () => visibleClips.filter(node => enabledIds.has(node.id)),
    [visibleClips, enabledIds],
  )

  const safeIndex = activeClips.length ? Math.min(currentIndex, activeClips.length - 1) : 0
  const currentClip = activeClips[safeIndex] || null
  const selectedAudioNode = useMemo(
    () => audioNodes.find(node => node.id === selectedAudioId) || null,
    [audioNodes, selectedAudioId],
  )

  useEffect(() => {
    if (safeIndex !== currentIndex) setCurrentIndex(safeIndex)
  }, [safeIndex, currentIndex])

  useEffect(() => {
    if (!currentClip && isPlaying) setIsPlaying(false)
  }, [currentClip, isPlaying])

  // Sync video mute flag.
  useEffect(() => {
    if (videoRef.current) videoRef.current.muted = videoMuted
  }, [videoMuted, currentClip?.id])

  // Sync audio mute & volume flags.
  useEffect(() => {
    const audioEl = audioRef.current
    if (!audioEl) return
    audioEl.muted = audioMuted
    audioEl.volume = audioVolume
  }, [audioMuted, audioVolume, selectedAudioNode?.id])

  // Keep <video> and optional <audio> playback synced with `isPlaying` and shot switches.
  useEffect(() => {
    const videoEl = videoRef.current
    const audioEl = audioRef.current
    if (!currentClip || !videoEl) {
      audioEl?.pause()
      return
    }
    if (isPlaying) {
      const p = videoEl.play()
      if (p && typeof p.catch === 'function') p.catch(() => {})
      if (audioEl && selectedAudioNode) {
        if (audioEl.paused && !audioEl.ended) {
          const ap = audioEl.play()
          if (ap && typeof ap.catch === 'function') ap.catch(() => {})
        }
      }
    } else {
      videoEl.pause()
      audioEl?.pause()
    }
  }, [isPlaying, currentClip?.id, selectedAudioNode?.id])

  // Pause audio if user clears audio selection or switches track.
  useEffect(() => {
    const audioEl = audioRef.current
    if (!audioEl) return
    audioEl.currentTime = 0
    if (selectedAudioNode && isPlaying) {
      const ap = audioEl.play()
      if (ap && typeof ap.catch === 'function') ap.catch(() => {})
    }
  }, [selectedAudioNode?.id])

  function handleTogglePlay() {
    if (!activeClips.length) return
    if (isPlaying) {
      setIsPlaying(false)
      return
    }
    const videoEl = videoRef.current
    const audioEl = audioRef.current
    const atLastEnd =
      safeIndex === activeClips.length - 1 &&
      videoEl &&
      (videoEl.ended || (Number.isFinite(videoEl.duration) && videoEl.duration > 0 && videoEl.currentTime >= videoEl.duration - 0.05))
    if (atLastEnd) {
      setCurrentIndex(0)
      if (videoEl) videoEl.currentTime = 0
      if (audioEl) audioEl.currentTime = 0
    } else if (safeIndex === 0 && videoEl && videoEl.currentTime < 0.05 && audioEl) {
      audioEl.currentTime = 0
    }
    setIsPlaying(true)
  }

  function jumpToShot(index) {
    if (!activeClips.length) return
    const clamped = Math.max(0, Math.min(activeClips.length - 1, index))
    setCurrentIndex(clamped)
    setVideoTime(0)
    if (clamped === safeIndex && videoRef.current) {
      videoRef.current.currentTime = 0
      if (isPlaying) videoRef.current.play().catch(() => {})
    }
  }

  function handlePrevShot() {
    if (!activeClips.length) return
    if (safeIndex > 0) jumpToShot(safeIndex - 1)
    else if (loop) jumpToShot(activeClips.length - 1)
    else jumpToShot(0)
  }

  function handleNextShot() {
    if (!activeClips.length) return
    if (safeIndex < activeClips.length - 1) jumpToShot(safeIndex + 1)
    else if (loop) jumpToShot(0)
  }

  function handleVideoEnded() {
    if (!activeClips.length) {
      setIsPlaying(false)
      return
    }
    if (safeIndex < activeClips.length - 1) {
      setCurrentIndex(safeIndex + 1)
      setVideoTime(0)
      return
    }
    if (loop) {
      if (audioRef.current) audioRef.current.currentTime = 0
      if (activeClips.length === 1 && videoRef.current) {
        videoRef.current.currentTime = 0
        videoRef.current.play().catch(() => {})
        if (audioRef.current && selectedAudioNode) audioRef.current.play().catch(() => {})
      } else {
        setCurrentIndex(0)
        setVideoTime(0)
      }
      return
    }
    setIsPlaying(false)
    audioRef.current?.pause()
  }

  function toggleClipEnabled(nodeId) {
    const activeId = currentClip?.id || null
    setEnabledIds(prev => {
      const next = new Set(prev)
      if (next.has(nodeId)) next.delete(nodeId)
      else next.add(nodeId)
      const nextActive = visibleClips.filter(node => next.has(node.id))
      const nextIdx = activeId ? nextActive.findIndex(node => node.id === activeId) : -1
      setCurrentIndex(nextIdx >= 0 ? nextIdx : 0)
      return next
    })
  }

  function toggleOnlyFinalized() {
    const next = !onlyFinalized
    setOnlyFinalized(next)
    setIsPlaying(false)
    setCurrentIndex(0)
    if (next) {
      setEnabledIds(prev => {
        const finalizedIds = orderedClips.filter(n => n.finalized === true).map(n => n.id)
        const kept = finalizedIds.filter(id => prev.has(id))
        return new Set(kept.length ? kept : finalizedIds)
      })
    } else {
      setEnabledIds(new Set(orderedClips.map(n => n.id)))
    }
  }

  function moveClipBy(nodeId, delta) {
    const activeId = currentClip?.id || null
    const visibleIds = visibleClips.map(node => node.id)
    const visIdx = visibleIds.indexOf(nodeId)
    const targetVisIdx = visIdx + delta
    if (visIdx < 0 || targetVisIdx < 0 || targetVisIdx >= visibleIds.length) return
    const targetId = visibleIds[targetVisIdx]
    const fromFull = orderIds.indexOf(nodeId)
    const toFull = orderIds.indexOf(targetId)
    if (fromFull < 0 || toFull < 0) return
    const nextOrder = reorderList(orderIds, fromFull, toFull)
    setOrderIds(nextOrder)
    if (activeId) {
      const nextVisible = (onlyFinalized
        ? nextOrder.map(id => videoById.get(id)).filter(n => n && n.finalized === true)
        : nextOrder.map(id => videoById.get(id)).filter(Boolean))
      const nextActive = nextVisible.filter(n => enabledIds.has(n.id))
      const idx = nextActive.findIndex(n => n.id === activeId)
      if (idx >= 0) setCurrentIndex(idx)
    }
  }

  function handleDropOnClip(targetId) {
    const sourceId = dragId
    setDragId(null)
    setDragOverId(null)
    if (!sourceId || sourceId === targetId) return
    const fromIdx = orderIds.indexOf(sourceId)
    const toIdx = orderIds.indexOf(targetId)
    if (fromIdx < 0 || toIdx < 0) return
    const activeId = currentClip?.id || null
    const nextOrder = reorderList(orderIds, fromIdx, toIdx)
    setOrderIds(nextOrder)
    if (activeId) {
      const nextVisible = (onlyFinalized
        ? nextOrder.map(id => videoById.get(id)).filter(n => n && n.finalized === true)
        : nextOrder.map(id => videoById.get(id)).filter(Boolean))
      const nextActive = nextVisible.filter(n => enabledIds.has(n.id))
      const idx = nextActive.findIndex(n => n.id === activeId)
      if (idx >= 0) setCurrentIndex(idx)
    }
  }

  function handleKeyDown(event) {
    event.stopPropagation()
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose?.()
      return
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault()
      return
    }
    if (event.key === 'Tab' && dialogRef.current) {
      const items = [...dialogRef.current.querySelectorAll(FOCUSABLE_SELECTOR)].filter(
        el => el.getClientRects().length > 0,
      )
      if (!items.length) {
        event.preventDefault()
        dialogRef.current.focus()
      } else if (event.shiftKey && (document.activeElement === dialogRef.current || document.activeElement === items[0])) {
        event.preventDefault()
        items[items.length - 1].focus()
      } else if (!event.shiftKey && document.activeElement === items[items.length - 1]) {
        event.preventDefault()
        items[0].focus()
      }
      return
    }
    const target = event.target
    if (['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(target?.tagName)) return
    if (event.code === 'Space') {
      event.preventDefault()
      handleTogglePlay()
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault()
      handlePrevShot()
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      handleNextShot()
    }
  }

  const shotStatusText = currentClip
    ? `第 ${safeIndex + 1} / ${activeClips.length} 镜 · ${currentClip.title || '未命名视频'}`
    : videoNodes.length === 0
      ? '暂无可用视频镜头'
      : '未勾选任何可播镜头'

  const content = (
    <div
      className="cv-seq-overlay"
      data-testid="sequence-preview-overlay"
      onPointerDown={event => {
        event.stopPropagation()
        if (event.target === event.currentTarget) onClose?.()
      }}
    >
      <section
        ref={dialogRef}
        className="cv-seq-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cv-seq-title"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <header className="cv-seq-header">
          <div className="cv-seq-title-group">
            <Clapperboard size={16} aria-hidden="true" />
            <h2 id="cv-seq-title">镜头序列连播预览</h2>
            <span className="cv-seq-readonly-pill">纯浏览器只读试看 · 不修改画布</span>
          </div>
          <div className="cv-seq-header-right">
            <span className="cv-seq-shot-indicator" data-testid="sequence-shot-indicator" aria-live="polite">
              {shotStatusText}
            </span>
            <button
              type="button"
              className="cv-seq-icon-btn"
              aria-label="关闭连播预览"
              title="关闭（Esc）"
              onClick={onClose}
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
        </header>

        <div className="cv-seq-body">
          <div className="cv-seq-stage-col">
            <div className="cv-seq-stage">
              {currentClip ? (
                <video
                  key={currentClip.id}
                  ref={videoRef}
                  src={currentClip.asset.url}
                  className="cv-seq-video"
                  data-testid="sequence-video-player"
                  data-node-id={currentClip.id}
                  muted={videoMuted}
                  playsInline
                  preload="auto"
                  onLoadedMetadata={event => {
                    setVideoDuration(event.currentTarget.duration || 0)
                    setVideoTime(event.currentTarget.currentTime || 0)
                    if (playIntentRef.current) {
                      event.currentTarget.play().catch(() => {})
                    }
                  }}
                  onCanPlay={event => {
                    if (playIntentRef.current && event.currentTarget.paused) {
                      event.currentTarget.play().catch(() => {})
                    }
                  }}
                  onTimeUpdate={event => setVideoTime(event.currentTarget.currentTime || 0)}
                  onEnded={handleVideoEnded}
                />
              ) : (
                <div className="cv-seq-empty-stage" role="status">
                  <Clapperboard size={28} aria-hidden="true" />
                  <strong>
                    {videoNodes.length === 0
                      ? '当前画布还没有可用的视频结果'
                      : onlyFinalized && finalizedCount === 0
                        ? '当前画布没有已标为定稿的视频镜头'
                        : '请在右侧勾选至少 1 个视频镜头'}
                  </strong>
                  <p>
                    {videoNodes.length === 0
                      ? '请先在画布中生成视频或导入视频素材后再打开连播预览。'
                      : '仅用于按顺序连续试看画布中的视频镜头，不会修改任何节点或导出成片。'}
                  </p>
                  {onlyFinalized && finalizedCount === 0 && videoNodes.length > 0 && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={toggleOnlyFinalized}
                    >
                      查看全部视频镜头
                    </button>
                  )}
                </div>
              )}
            </div>

            {activeClips.length > 0 && (
              <div className="cv-seq-pills" role="list" aria-label="镜头快速跳转">
                {activeClips.map((clip, idx) => (
                  <button
                    key={clip.id}
                    type="button"
                    role="listitem"
                    className={`cv-seq-pill ${idx === safeIndex ? 'is-active' : ''}`}
                    aria-current={idx === safeIndex ? 'true' : undefined}
                    title={`跳转到第 ${idx + 1} 镜：${clip.title || '未命名视频'}`}
                    onClick={() => jumpToShot(idx)}
                  >
                    <span className="cv-seq-pill-idx">{idx + 1}</span>
                    <span className="cv-seq-pill-name">{clip.title || '未命名视频'}</span>
                  </button>
                ))}
              </div>
            )}

            <div className="cv-seq-controls">
              <div className="cv-seq-transport">
                <button
                  type="button"
                  className="cv-seq-ctrl-btn"
                  aria-label="上一镜"
                  title="上一镜"
                  disabled={!activeClips.length || (!loop && safeIndex === 0)}
                  onClick={handlePrevShot}
                >
                  <SkipBack size={15} aria-hidden="true" />
                  <span>上一镜</span>
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm cv-seq-play-btn"
                  data-testid="sequence-play-toggle"
                  aria-label={isPlaying ? '暂停连播' : '开始连播'}
                  disabled={!activeClips.length}
                  onClick={handleTogglePlay}
                >
                  {isPlaying ? <Pause size={15} aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}
                  <span>{isPlaying ? '暂停' : '播放'}</span>
                </button>
                <button
                  type="button"
                  className="cv-seq-ctrl-btn"
                  aria-label="下一镜"
                  title="下一镜"
                  disabled={!activeClips.length || (!loop && safeIndex >= activeClips.length - 1)}
                  onClick={handleNextShot}
                >
                  <SkipForward size={15} aria-hidden="true" />
                  <span>下一镜</span>
                </button>
              </div>

              <div className="cv-seq-time" aria-label="当前镜头播放进度">
                {formatSequenceTime(videoTime)} / {formatSequenceTime(videoDuration)}
              </div>

              <div className="cv-seq-toggles">
                <button
                  type="button"
                  className={`cv-seq-ctrl-btn ${loop ? 'is-active' : ''}`}
                  data-testid="sequence-loop-toggle"
                  aria-pressed={loop}
                  title={loop ? '已开启循环连播' : '开启循环连播'}
                  onClick={() => setLoop(value => !value)}
                >
                  <Repeat size={14} aria-hidden="true" />
                  <span>循环</span>
                </button>
                <button
                  type="button"
                  className={`cv-seq-ctrl-btn ${videoMuted ? 'is-muted' : ''}`}
                  aria-pressed={videoMuted}
                  aria-label={videoMuted ? '取消视频原声静音' : '静音视频原声'}
                  title={videoMuted ? '视频原声已静音，点击恢复' : '静音视频原声'}
                  onClick={() => setVideoMuted(value => !value)}
                >
                  {videoMuted ? <VolumeX size={14} aria-hidden="true" /> : <Volume2 size={14} aria-hidden="true" />}
                  <span>{videoMuted ? '视频静音' : '视频原声'}</span>
                </button>
              </div>
            </div>

            <div className="cv-seq-audio-bar" data-testid="sequence-audio-sync">
              <div className="cv-seq-audio-select-wrap">
                <Music size={14} aria-hidden="true" />
                <label htmlFor="cv-seq-audio-select">背景/旁白音频</label>
                <select
                  id="cv-seq-audio-select"
                  aria-label="同步背景或旁白音频节点"
                  value={selectedAudioId}
                  onChange={event => setSelectedAudioId(event.target.value)}
                >
                  <option value="">不挂接音频（默认无声）</option>
                  {audioNodes.map(node => (
                    <option key={node.id} value={node.id}>
                      {node.title || '未命名音频'}
                      {node.finalized ? '（定稿）' : ''}
                    </option>
                  ))}
                </select>
              </div>

              <div className="cv-seq-audio-controls">
                <button
                  type="button"
                  className={`cv-seq-ctrl-btn ${!audioMuted && selectedAudioNode ? 'is-active' : ''}`}
                  data-testid="sequence-audio-mute-toggle"
                  disabled={!selectedAudioNode}
                  aria-pressed={audioMuted}
                  aria-label={audioMuted ? '取消伴音静音' : '静音伴音'}
                  title={selectedAudioNode ? (audioMuted ? '伴音默认静音，点击开启试听' : '点击静音伴音') : '请先选择一条音频节点'}
                  onClick={() => setAudioMuted(value => !value)}
                >
                  {audioMuted ? <VolumeX size={14} aria-hidden="true" /> : <Volume2 size={14} aria-hidden="true" />}
                  <span>{audioMuted ? '伴音已静音' : '伴音开启'}</span>
                </button>
                <label className="cv-seq-volume-label">
                  <span>音量</span>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    aria-label="伴音音量"
                    disabled={!selectedAudioNode}
                    value={audioMuted ? 0 : audioVolume}
                    onChange={event => {
                      const nextVol = Number(event.target.value)
                      setAudioVolume(nextVol)
                      if (nextVol > 0 && audioMuted) setAudioMuted(false)
                      if (nextVol === 0 && !audioMuted) setAudioMuted(true)
                    }}
                  />
                  <span className="cv-seq-volume-val">{audioMuted ? '0%' : `${Math.round(audioVolume * 100)}%`}</span>
                </label>
              </div>
              {selectedAudioNode && (
                <audio
                  ref={audioRef}
                  src={selectedAudioNode.asset.url}
                  data-testid="sequence-audio-player"
                  data-node-id={selectedAudioNode.id}
                  muted={audioMuted}
                  preload="auto"
                />
              )}
            </div>
          </div>

          <aside className="cv-seq-playlist-col" aria-label="镜头播放列表">
            <div className="cv-seq-playlist-head">
              <div>
                <strong>镜头顺序</strong>
                <span className="cv-seq-playlist-count">
                  已选 {activeClips.length} / {visibleClips.length}
                </span>
              </div>
              <button
                type="button"
                className={`cv-seq-filter-btn ${onlyFinalized ? 'is-active' : ''}`}
                data-testid="sequence-only-finalized"
                aria-pressed={onlyFinalized}
                disabled={finalizedCount === 0 && !onlyFinalized}
                title={finalizedCount > 0 ? '仅勾选并播放已标为定稿的视频镜头' : '当前画布暂无定稿视频节点'}
                onClick={toggleOnlyFinalized}
              >
                <CheckCircle2 size={13} aria-hidden="true" />
                <span>仅看定稿 ({finalizedCount})</span>
              </button>
            </div>

            {visibleClips.length === 0 ? (
              <p className="cv-seq-playlist-empty">暂无可排列的视频镜头</p>
            ) : (
              <ul className="cv-seq-playlist" data-testid="sequence-playlist">
                {visibleClips.map((clip, visIdx) => {
                  const checked = enabledIds.has(clip.id)
                  const activePos = activeClips.findIndex(item => item.id === clip.id)
                  const isCurrent = currentClip?.id === clip.id
                  return (
                    <li
                      key={clip.id}
                      data-testid={`sequence-item-${clip.id}`}
                      className={`cv-seq-item ${isCurrent ? 'is-current' : ''} ${!checked ? 'is-unchecked' : ''} ${dragOverId === clip.id ? 'is-drag-over' : ''}`}
                      draggable
                      onDragStart={event => {
                        setDragId(clip.id)
                        event.dataTransfer.effectAllowed = 'move'
                        event.dataTransfer.setData('text/plain', clip.id)
                      }}
                      onDragOver={event => {
                        event.preventDefault()
                        if (dragOverId !== clip.id) setDragOverId(clip.id)
                      }}
                      onDragLeave={() => {
                        if (dragOverId === clip.id) setDragOverId(null)
                      }}
                      onDrop={event => {
                        event.preventDefault()
                        handleDropOnClip(clip.id)
                      }}
                      onDragEnd={() => {
                        setDragId(null)
                        setDragOverId(null)
                      }}
                    >
                      <span className="cv-seq-drag-handle" aria-hidden="true" title="拖动调整顺序">
                        <GripVertical size={13} />
                      </span>
                      <input
                        type="checkbox"
                        checked={checked}
                        aria-label={`包含镜头 ${clip.title || clip.id}`}
                        onChange={() => toggleClipEnabled(clip.id)}
                      />
                      <button
                        type="button"
                        className="cv-seq-item-jump"
                        disabled={!checked}
                        onClick={() => {
                          if (activePos >= 0) jumpToShot(activePos)
                        }}
                      >
                        <span className="cv-seq-item-num">{activePos >= 0 ? `#${activePos + 1}` : '—'}</span>
                        <span className="cv-seq-item-title" title={clip.title || '未命名视频'}>
                          {clip.title || '未命名视频'}
                        </span>
                        {clip.finalized === true && <span className="cv-seq-final-tag">定稿</span>}
                      </button>
                      <div className="cv-seq-item-move">
                        <button
                          type="button"
                          className="cv-seq-move-btn"
                          aria-label={`上移镜头 ${clip.title || clip.id}`}
                          title="上移"
                          disabled={visIdx === 0}
                          onClick={() => moveClipBy(clip.id, -1)}
                        >
                          <ArrowUp size={13} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="cv-seq-move-btn"
                          aria-label={`下移镜头 ${clip.title || clip.id}`}
                          title="下移"
                          disabled={visIdx === visibleClips.length - 1}
                          onClick={() => moveClipBy(clip.id, 1)}
                        >
                          <ArrowDown size={13} aria-hidden="true" />
                        </button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </aside>
        </div>
      </section>
    </div>
  )

  return typeof document !== 'undefined' ? createPortal(content, document.body) : content
}
