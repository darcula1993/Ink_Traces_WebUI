import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, CheckCircle2, Minus, Music, Pause, Play, RotateCcw, Volume2, VolumeX, X, Plus } from 'lucide-react'
import { versionTime } from './CanvasVersionPopover'
import './canvasVersionCompare.css'

const IMAGE_ZOOM_PRESETS = ['fit', 100, 150, 200]
const MIN_ZOOM = 50
const MAX_ZOOM = 300
const ZOOM_STEP = 25

function clampZoom(value) {
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(value)))
}

function formatClock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00'
  const total = Math.floor(seconds)
  const mins = Math.floor(total / 60)
  const secs = total % 60
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

export function initialCompareIds(liveEntries, currentId) {
  if (!Array.isArray(liveEntries) || !liveEntries.length) return []
  if (liveEntries.length <= 4) return liveEntries.map(entry => entry.asset.id)
  const latest = liveEntries.slice(-4).map(entry => entry.asset.id)
  if (currentId && !latest.includes(currentId) && liveEntries.some(entry => entry.asset.id === currentId)) {
    latest[0] = currentId
  }
  const picked = new Set(latest)
  return liveEntries.filter(entry => picked.has(entry.asset.id)).map(entry => entry.asset.id)
}

function CompareVideoPane({ entry, registerMedia, muted, onToggleMute, onPlayStateChange }) {
  const mediaRef = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [error, setError] = useState('')
  const isAudio = entry.kind === 'audio'

  const setRef = useCallback(el => {
    mediaRef.current = el
    registerMedia(entry.asset.id, el)
  }, [entry.asset.id, registerMedia])

  useEffect(() => {
    const el = mediaRef.current
    if (!el) return
    el.muted = muted
  }, [muted])

  useEffect(() => {
    return () => {
      const el = mediaRef.current
      if (el) {
        try { el.pause() } catch { /* ignore */ }
      }
      registerMedia(entry.asset.id, null)
    }
  }, [entry.asset.id, registerMedia])

  const togglePlay = () => {
    const el = mediaRef.current
    if (!el) return
    if (el.paused) {
      if (el.ended) el.currentTime = 0
      el.play?.().catch(() => {})
    } else {
      el.pause()
    }
  }

  const seek = event => {
    const el = mediaRef.current
    const next = Number(event.target.value)
    if (!el || !Number.isFinite(next)) return
    el.currentTime = next
    setCurrentTime(next)
  }

  const pct = duration > 0 ? Math.min(100, Math.max(0, (currentTime / duration) * 100)) : 0

  return (
    <div className={`cv-compare-media-wrap ${isAudio ? 'is-audio' : 'is-video'}`}>
      <div className="cv-compare-video-box">
        {isAudio ? (
          <div className="cv-compare-audio-visual" aria-hidden="true">
            <Music size={28} />
            <span>{entry.asset.name || `版本 ${entry.versionNumber}`}</span>
            <audio
              ref={setRef}
              src={entry.asset.url}
              muted={muted}
              preload="metadata"
              onLoadedMetadata={e => {
                setDuration(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : 0)
                setError('')
              }}
              onTimeUpdate={e => setCurrentTime(e.currentTarget.currentTime || 0)}
              onPlay={() => { setPlaying(true); onPlayStateChange() }}
              onPause={() => { setPlaying(false); onPlayStateChange() }}
              onEnded={() => { setPlaying(false); onPlayStateChange() }}
              onError={() => setError('音频加载失败')}
            />
          </div>
        ) : (
          <video
            ref={setRef}
            className="cv-compare-video"
            src={entry.asset.url}
            muted={muted}
            playsInline
            preload="metadata"
            onClick={togglePlay}
            onLoadedMetadata={e => {
              setDuration(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : 0)
              setError('')
            }}
            onTimeUpdate={e => setCurrentTime(e.currentTarget.currentTime || 0)}
            onPlay={() => { setPlaying(true); onPlayStateChange() }}
            onPause={() => { setPlaying(false); onPlayStateChange() }}
            onEnded={() => { setPlaying(false); onPlayStateChange() }}
            onError={() => setError('视频加载失败')}
          />
        )}
        {error && <div className="cv-compare-media-error" role="alert">{error}</div>}
      </div>
      <div className="cv-compare-video-bar">
        <button
          type="button"
          className="cv-compare-icon-btn"
          aria-label={playing ? `暂停 版本 ${entry.versionNumber}` : `播放 版本 ${entry.versionNumber}`}
          title={playing ? '暂停此栏' : '播放此栏'}
          onClick={togglePlay}
        >
          {playing ? <Pause size={13} aria-hidden="true" /> : <Play size={13} aria-hidden="true" />}
        </button>
        <input
          type="range"
          className="cv-compare-progress"
          aria-label={`版本 ${entry.versionNumber} 播放进度`}
          data-testid={`compare-progress-${entry.asset.id}`}
          min={0}
          max={duration > 0 ? duration : 0}
          step={0.05}
          value={duration > 0 ? Math.min(currentTime, duration) : 0}
          disabled={!(duration > 0)}
          style={{ '--cv-compare-progress': `${pct}%` }}
          onChange={seek}
        />
        <span className="cv-compare-time" aria-hidden="true">
          {formatClock(currentTime)}/{formatClock(duration)}
        </span>
        <button
          type="button"
          className={`cv-compare-icon-btn cv-compare-mute-btn ${muted ? '' : 'is-unmuted'}`}
          data-testid={`compare-mute-${entry.asset.id}`}
          aria-label={muted ? `取消静音 版本 ${entry.versionNumber}` : `静音 版本 ${entry.versionNumber}`}
          aria-pressed={!muted}
          title={muted ? '当前静音，点击开启声音' : '已开启声音，点击静音'}
          onClick={() => onToggleMute(entry.asset.id)}
        >
          {muted ? <VolumeX size={13} aria-hidden="true" /> : <Volume2 size={13} aria-hidden="true" />}
        </button>
      </div>
    </div>
  )
}

export default function CanvasVersionCompareModal({
  node,
  isGone = () => false,
  busy = false,
  onChoose,
  onToggleFinalized,
  onClose,
}) {
  const dialogRef = useRef(null)
  const fallbackKind = node.asset?.kind || (node.type === 'asset' ? 'image' : node.type)
  const currentId = node.asset?.id ?? node.selectedCandidateId
  const finalized = node.finalized === true

  const liveEntries = useMemo(() => (
    (node.candidates || [])
      .map((asset, index) => ({
        asset,
        versionNumber: index + 1,
        kind: asset?.kind || fallbackKind,
        gone: !asset?.id || isGone(asset),
      }))
      .filter(entry => !entry.gone)
  ), [node.candidates, fallbackKind, isGone])

  const [selectedIds, setSelectedIds] = useState(() => initialCompareIds(liveEntries, currentId))

  // Keep selectedIds synced with liveEntries if candidates change while open.
  useEffect(() => {
    setSelectedIds(prev => {
      const liveSet = new Set(liveEntries.map(entry => entry.asset.id))
      const kept = prev.filter(id => liveSet.has(id))
      if (kept.length >= 2) return kept.slice(0, 4)
      return initialCompareIds(liveEntries, currentId)
    })
  }, [liveEntries, currentId])

  const shownEntries = useMemo(() => {
    const picked = new Set(selectedIds)
    return liveEntries.filter(entry => picked.has(entry.asset.id)).slice(0, 4)
  }, [liveEntries, selectedIds])

  const compareKind = shownEntries[0]?.kind || fallbackKind

  // Image zoom & pan state.
  const [syncZoom, setSyncZoom] = useState(true)
  const [sharedZoom, setSharedZoom] = useState('fit')
  const [paneZooms, setPaneZooms] = useState({})
  const [naturalSizes, setNaturalSizes] = useState({})
  const scrollRefs = useRef(new Map())
  const syncingScroll = useRef(false)

  // Video / audio state: every column starts muted by default.
  const mediaRefs = useRef(new Map())
  const [mutedMap, setMutedMap] = useState({})
  const [anyPlaying, setAnyPlaying] = useState(false)

  const registerMedia = useCallback((id, el) => {
    if (el) mediaRefs.current.set(id, el)
    else mediaRefs.current.delete(id)
  }, [])

  const refreshPlayingState = useCallback(() => {
    let playing = false
    for (const el of mediaRefs.current.values()) {
      if (el && !el.paused && !el.ended) {
        playing = true
        break
      }
    }
    setAnyPlaying(playing)
  }, [])

  useEffect(() => {
    dialogRef.current?.focus({ preventScroll: true })
  }, [])

  // Pause all media cleanly if modal unmounts.
  useEffect(() => () => {
    for (const el of mediaRefs.current.values()) {
      try { el?.pause() } catch { /* ignore */ }
    }
  }, [])

  const togglePickerId = id => {
    setSelectedIds(prev => {
      if (prev.includes(id)) {
        if (prev.length <= 2) return prev
        return prev.filter(item => item !== id)
      }
      if (prev.length >= 4) return prev
      const nextSet = new Set([...prev, id])
      return liveEntries.filter(entry => nextSet.has(entry.asset.id)).map(entry => entry.asset.id)
    })
  }

  const zoomOf = id => (syncZoom ? sharedZoom : (paneZooms[id] ?? sharedZoom))

  const applyPresetZoom = preset => {
    setSharedZoom(preset)
    if (!syncZoom) {
      const next = {}
      for (const entry of shownEntries) next[entry.asset.id] = preset
      setPaneZooms(next)
    }
  }

  const stepPaneZoom = (id, delta) => {
    if (syncZoom) {
      setSharedZoom(prev => {
        const base = prev === 'fit' ? 100 : prev
        return clampZoom(base + delta)
      })
      return
    }
    setPaneZooms(prev => {
      const current = prev[id] ?? sharedZoom
      const base = current === 'fit' ? 100 : current
      return { ...prev, [id]: clampZoom(base + delta) }
    })
  }

  const resetPaneZoom = id => {
    if (syncZoom) {
      setSharedZoom('fit')
      return
    }
    setPaneZooms(prev => ({ ...prev, [id]: 'fit' }))
  }

  const handleImageWheel = (id, event) => {
    event.preventDefault()
    event.stopPropagation()
    const delta = event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP
    stepPaneZoom(id, delta)
  }

  const handlePaneScroll = (sourceId, event) => {
    if (!syncZoom || syncingScroll.current) return
    const src = event.currentTarget
    const maxX = src.scrollWidth - src.clientWidth
    const maxY = src.scrollHeight - src.clientHeight
    const rx = maxX > 0 ? src.scrollLeft / maxX : 0
    const ry = maxY > 0 ? src.scrollTop / maxY : 0
    syncingScroll.current = true
    try {
      for (const [id, el] of scrollRefs.current.entries()) {
        if (id === sourceId || !el) continue
        const targetMaxX = el.scrollWidth - el.clientWidth
        const targetMaxY = el.scrollHeight - el.clientHeight
        if (targetMaxX > 0) el.scrollLeft = rx * targetMaxX
        if (targetMaxY > 0) el.scrollTop = ry * targetMaxY
      }
    } finally {
      syncingScroll.current = false
    }
  }

  const handleSyncTogglePlay = () => {
    const elements = shownEntries.map(entry => mediaRefs.current.get(entry.asset.id)).filter(Boolean)
    if (!elements.length) return
    if (anyPlaying) {
      for (const el of elements) {
        try { el.pause() } catch { /* ignore */ }
      }
      setAnyPlaying(false)
      return
    }
    const allEnded = elements.every(el => el.ended)
    for (const el of elements) {
      if (allEnded || el.ended) {
        try { el.currentTime = 0 } catch { /* ignore */ }
      }
      el.play?.().catch(() => {})
    }
    setAnyPlaying(true)
  }

  const handleSyncRestart = () => {
    const elements = shownEntries.map(entry => mediaRefs.current.get(entry.asset.id)).filter(Boolean)
    for (const el of elements) {
      try {
        el.pause()
        el.currentTime = 0
      } catch { /* ignore */ }
    }
    setAnyPlaying(false)
  }

  const toggleMute = id => {
    setMutedMap(prev => {
      const currentMuted = prev[id] !== false
      const nextMuted = !currentMuted
      const el = mediaRefs.current.get(id)
      if (el) el.muted = nextMuted
      return { ...prev, [id]: nextMuted }
    })
  }

  const onKeyDown = event => {
    event.stopPropagation()
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key === 'Tab' && dialogRef.current) {
      const list = [...dialogRef.current.querySelectorAll('button:not(:disabled), input:not(:disabled), a[href]')]
      if (!list.length) return
      if (event.shiftKey && [dialogRef.current, list[0]].includes(document.activeElement)) {
        event.preventDefault()
        list.at(-1)?.focus()
      } else if (!event.shiftKey && document.activeElement === list.at(-1)) {
        event.preventDefault()
        list[0]?.focus()
      }
    }
  }

  const cols = Math.max(2, Math.min(4, shownEntries.length || 2))

  return (
    <div
      className="cv-compare-overlay"
      data-testid="version-compare-overlay"
      onPointerDown={e => {
        e.stopPropagation()
        if (e.target === e.currentTarget) onClose()
      }}
      onWheel={e => e.stopPropagation()}
    >
      <section
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={`并排对比 · ${node.title}`}
        data-testid="version-compare-modal"
        className="cv-compare-dialog"
        onKeyDown={onKeyDown}
        onPointerDown={e => e.stopPropagation()}
      >
        <header className="cv-compare-header">
          <div className="cv-compare-title-group">
            <h2>并排对比</h2>
            <span className="cv-compare-node-title" title={node.title}>{node.title}</span>
            <span className="cv-compare-count">
              {shownEntries.length} / {liveEntries.length} 个可用版本
            </span>
            {finalized && (
              <span className="cv-compare-badge is-finalized" data-testid="compare-header-final-badge">
                <Check size={11} aria-hidden="true" />已定稿
              </span>
            )}
          </div>
          <div className="cv-compare-header-actions">
            {onToggleFinalized && (
              <button
                type="button"
                className={`btn btn-sm ${finalized ? 'cv-compare-final-active' : 'btn-secondary'}`}
                data-testid="compare-toggle-final"
                disabled={busy}
                aria-pressed={finalized}
                title={finalized ? '取消此节点的定稿标记（可撤销）' : '将此节点当前采用版本标为定稿（可撤销）'}
                onClick={() => onToggleFinalized(!finalized)}
              >
                <CheckCircle2 size={14} aria-hidden="true" />
                {finalized ? '取消定稿' : '标为定稿'}
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              aria-label="关闭并排对比"
              onClick={onClose}
            >
              <X size={15} aria-hidden="true" />
              关闭
            </button>
          </div>
        </header>

        {liveEntries.length > 4 && (
          <div className="cv-compare-picker" role="group" aria-label="选择对比版本" data-testid="compare-version-picker">
            <span className="cv-compare-picker-label">选择 2–4 个版本（已选 {selectedIds.length}/4）：</span>
            <div className="cv-compare-picker-list">
              {liveEntries.map(entry => {
                const checked = selectedIds.includes(entry.asset.id)
                const isCurrent = entry.asset.id === currentId
                const disabledReason = checked && selectedIds.length <= 2
                  ? '至少保留 2 个版本进行对比'
                  : !checked && selectedIds.length >= 4
                    ? '最多同时对比 4 个版本，请先取消一个'
                    : undefined
                return (
                  <label
                    key={entry.asset.id}
                    className={`cv-compare-picker-chip ${checked ? 'is-checked' : ''} ${disabledReason ? 'is-locked' : ''}`}
                    title={disabledReason || (checked ? `取消勾选 版本 ${entry.versionNumber}` : `加入对比 版本 ${entry.versionNumber}`)}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={Boolean(disabledReason)}
                      aria-label={`对比 版本 ${entry.versionNumber}`}
                      onChange={() => togglePickerId(entry.asset.id)}
                    />
                    <span>版本 {entry.versionNumber}</span>
                    {isCurrent && <em className="cv-compare-picker-tag">当前</em>}
                  </label>
                )
              })}
            </div>
          </div>
        )}

        <div className="cv-compare-controls" role="toolbar" aria-label="对比控制">
          {compareKind === 'image' ? (
            <>
              <div className="cv-compare-zoom-group" role="group" aria-label="图片缩放">
                {IMAGE_ZOOM_PRESETS.map(preset => {
                  const active = syncZoom && sharedZoom === preset
                  const label = preset === 'fit' ? '适应' : `${preset}%`
                  return (
                    <button
                      key={String(preset)}
                      type="button"
                      className={`btn btn-sm ${active ? 'is-active' : 'btn-ghost'}`}
                      data-testid={`compare-zoom-${preset}`}
                      aria-pressed={active}
                      onClick={() => applyPresetZoom(preset)}
                    >
                      {label}
                    </button>
                  )
                })}
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  aria-label="重置缩放"
                  data-testid="compare-zoom-reset"
                  title="重置为适应窗口"
                  onClick={() => applyPresetZoom('fit')}
                >
                  <RotateCcw size={13} aria-hidden="true" />
                  重置
                </button>
              </div>
              <label className="cv-compare-sync-toggle">
                <input
                  type="checkbox"
                  checked={syncZoom}
                  data-testid="compare-sync-zoom"
                  onChange={e => {
                    const checked = e.target.checked
                    setSyncZoom(checked)
                    if (checked) setPaneZooms({})
                  }}
                />
                <span>同步缩放与滚动</span>
              </label>
              <span className="cv-compare-hint">支持滚轮缩放，切换采用版不会删除未采用版本</span>
            </>
          ) : (
            <>
              <div className="cv-compare-video-sync-group">
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  data-testid="compare-video-sync-play"
                  onClick={handleSyncTogglePlay}
                >
                  {anyPlaying ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}
                  {anyPlaying ? '全部暂停' : '全部同步播放'}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  data-testid="compare-video-sync-reset"
                  title="全部视频回到开头并暂停"
                  onClick={handleSyncRestart}
                >
                  <RotateCcw size={13} aria-hidden="true" />
                  回到开头
                </button>
              </div>
              <span className="cv-compare-hint">默认全部静音以防同时发声，可在各栏单独开启声音；切换采用版不删除未采用版本</span>
            </>
          )}
        </div>

        {shownEntries.length < 2 ? (
          <div className="cv-compare-empty">至少需要 2 个可用版本才能进行并排对比。</div>
        ) : (
          <div className="cv-compare-grid" data-cols={cols} style={{ '--cv-compare-cols': cols }}>
            {shownEntries.map(entry => {
              const isCurrent = entry.asset.id === currentId
              const isCurrentFinal = isCurrent && finalized
              const time = versionTime(entry.asset)
              const zoom = zoomOf(entry.asset.id)
              const nat = naturalSizes[entry.asset.id]
              const isMuted = mutedMap[entry.asset.id] !== false

              return (
                <article
                  key={entry.asset.id}
                  className={`cv-compare-col ${isCurrent ? 'is-current' : ''} ${isCurrentFinal ? 'is-finalized' : ''}`}
                  data-testid={`compare-col-${entry.asset.id}`}
                  data-version-number={entry.versionNumber}
                >
                  <header className="cv-compare-col-head">
                    <div className="cv-compare-col-meta">
                      <strong>版本 {entry.versionNumber}</strong>
                      {isCurrent && <span className="cv-compare-badge is-current">当前采用</span>}
                      {isCurrentFinal && <span className="cv-compare-badge is-finalized">定稿</span>}
                      {time && <time className="cv-compare-col-time">{time}</time>}
                    </div>
                    {entry.kind === 'image' && (
                      <div className="cv-compare-col-zoom">
                        {!syncZoom && (
                          <button
                            type="button"
                            className="cv-compare-icon-btn"
                            aria-label={`缩小 版本 ${entry.versionNumber}`}
                            onClick={() => stepPaneZoom(entry.asset.id, -ZOOM_STEP)}
                          >
                            <Minus size={12} aria-hidden="true" />
                          </button>
                        )}
                        <span className="cv-compare-zoom-readout" data-testid={`compare-zoom-value-${entry.asset.id}`}>
                          {zoom === 'fit' ? '适应' : `${zoom}%`}
                        </span>
                        {!syncZoom && (
                          <>
                            <button
                              type="button"
                              className="cv-compare-icon-btn"
                              aria-label={`放大 版本 ${entry.versionNumber}`}
                              onClick={() => stepPaneZoom(entry.asset.id, ZOOM_STEP)}
                            >
                              <Plus size={12} aria-hidden="true" />
                            </button>
                            <button
                              type="button"
                              className="cv-compare-icon-btn"
                              aria-label={`重置 版本 ${entry.versionNumber} 缩放`}
                              onClick={() => resetPaneZoom(entry.asset.id)}
                            >
                              <RotateCcw size={12} aria-hidden="true" />
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </header>

                  <div className="cv-compare-stage">
                    {entry.kind === 'image' ? (
                      <div
                        ref={el => {
                          if (el) scrollRefs.current.set(entry.asset.id, el)
                          else scrollRefs.current.delete(entry.asset.id)
                        }}
                        className={`cv-compare-img-viewport ${zoom === 'fit' ? 'is-fit' : 'is-zoomed'}`}
                        onWheel={e => handleImageWheel(entry.asset.id, e)}
                        onScroll={e => handlePaneScroll(entry.asset.id, e)}
                      >
                        <img
                          src={entry.asset.url}
                          alt={`${node.title} 版本 ${entry.versionNumber}`}
                          draggable={false}
                          data-zoom={String(zoom)}
                          style={zoom === 'fit' ? undefined : {
                            width: nat ? `${Math.round(nat.width * zoom / 100)}px` : `${zoom}%`,
                            maxWidth: 'none',
                            maxHeight: 'none',
                          }}
                          onLoad={e => {
                            const w = e.currentTarget.naturalWidth
                            const h = e.currentTarget.naturalHeight
                            if (w && h) {
                              setNaturalSizes(prev => (
                                prev[entry.asset.id]?.width === w && prev[entry.asset.id]?.height === h
                                  ? prev
                                  : { ...prev, [entry.asset.id]: { width: w, height: h } }
                              ))
                            }
                          }}
                        />
                      </div>
                    ) : (
                      <CompareVideoPane
                        entry={entry}
                        registerMedia={registerMedia}
                        muted={isMuted}
                        onToggleMute={toggleMute}
                        onPlayStateChange={refreshPlayingState}
                      />
                    )}
                  </div>

                  <footer className="cv-compare-col-actions">
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      data-testid={`compare-adopt-${entry.asset.id}`}
                      disabled={busy || isCurrent}
                      title={isCurrent ? '已是当前采用版' : `将版本 ${entry.versionNumber} 设为当前采用版（可撤销）`}
                      onClick={() => onChoose(entry.asset, { finalize: false })}
                    >
                      设为当前采用版
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      data-testid={`compare-adopt-final-${entry.asset.id}`}
                      disabled={busy || isCurrentFinal}
                      title={isCurrentFinal ? '已采用并标为定稿' : `采用版本 ${entry.versionNumber} 并将节点标为定稿（可撤销）`}
                      onClick={() => onChoose(entry.asset, { finalize: true })}
                    >
                      <Check size={13} aria-hidden="true" />
                      采用并标为定稿
                    </button>
                  </footer>
                </article>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}
