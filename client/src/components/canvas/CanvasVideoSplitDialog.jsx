import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  Loader2,
  Pause,
  Play,
  Plus,
  Scissors,
  Trash2,
  X,
} from 'lucide-react'
import {
  MAX_SEGMENTS,
  MIN_SEGMENT_SECONDS,
  computeEqualSegments,
  computeTimelineSegments,
  formatSplitTime,
  normalizeCutPoints,
  roundTime,
} from '../../lib/videoSplit'
import './canvasVideoSplit.css'

const DURATION_PRESETS = [3, 5, 10, 15]
const COUNT_PRESETS = [2, 3, 4]

function defaultEqualDuration(total) {
  if (!Number.isFinite(total) || total < MIN_SEGMENT_SECONDS * 2) return ''
  if (total >= 10) return '5'
  if (total >= 6) return '3'
  return String(roundTime(total / 2))
}

export default function CanvasVideoSplitDialog({ asset, title, onConfirm, onClose }) {
  const initialDuration = Number(asset?.duration) > 0 ? roundTime(asset.duration) : 0
  const [duration, setDuration] = useState(initialDuration)
  const [currentTime, setCurrentTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [mediaError, setMediaError] = useState('')

  const [mode, setMode] = useState('points')
  const [cutPoints, setCutPoints] = useState([])
  const [manualInput, setManualInput] = useState('')
  const [manualError, setManualError] = useState('')
  const [equalInput, setEqualInput] = useState(() => defaultEqualDuration(initialDuration))
  const equalTouched = useRef(false)

  const [draggingIndex, setDraggingIndex] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  const dialogRef = useRef(null)
  const videoRef = useRef(null)
  const trackRef = useRef(null)
  const dragState = useRef(null)

  useEffect(() => {
    dialogRef.current?.focus({ preventScroll: true })
  }, [])

  const seekTo = useCallback((nextTime) => {
    const safeMax = duration > 0 ? duration : 0
    const clamped = roundTime(Math.max(0, Math.min(safeMax, Number(nextTime) || 0)))
    setCurrentTime(clamped)
    if (videoRef.current && Number.isFinite(clamped)) {
      try {
        videoRef.current.currentTime = clamped
      } catch {
        // Ignore seek errors before metadata is ready
      }
    }
  }, [duration])

  const handleLoadedMetadata = () => {
    const video = videoRef.current
    if (!video) return
    const raw = video.duration
    if (Number.isFinite(raw) && raw > 0) {
      const nextDuration = roundTime(raw)
      setDuration(nextDuration)
      setMediaError('')
      setCutPoints(prev => normalizeCutPoints(prev, nextDuration))
      if (!equalTouched.current) {
        setEqualInput(defaultEqualDuration(nextDuration))
      }
    }
  }

  const togglePlay = () => {
    const video = videoRef.current
    if (!video || !duration) return
    if (video.paused || video.ended) {
      if (video.ended || currentTime >= duration - 0.05) {
        seekTo(0)
      }
      video.play().catch(() => {})
    } else {
      video.pause()
    }
  }

  const stepTime = delta => {
    if (!duration) return
    if (videoRef.current && !videoRef.current.paused) {
      videoRef.current.pause()
    }
    seekTo(currentTime + delta)
  }

  const addCutPoint = useCallback((rawSeconds) => {
    setManualError('')
    setSubmitError('')
    if (!duration) {
      setManualError('正在读取视频时长，请稍候')
      return false
    }
    const value = roundTime(rawSeconds)
    if (!Number.isFinite(value) || value <= 0 || value >= duration) {
      setManualError(`切点须大于 0 且小于总时长 ${duration.toFixed(2)}s`)
      return false
    }
    setCutPoints(prev => {
      if (prev.includes(value)) return prev
      return normalizeCutPoints([...prev, value], duration)
    })
    return true
  }, [duration])

  const removeCutPoint = useCallback((target) => {
    setSubmitError('')
    setManualError('')
    setCutPoints(prev => prev.filter(pt => pt !== target))
  }, [])

  const handleAddManual = () => {
    const trimmed = manualInput.trim()
    if (!trimmed) {
      setManualError('请输入切点秒数')
      return
    }
    const parsed = Number(trimmed)
    if (!Number.isFinite(parsed)) {
      setManualError('请输入有效的数字秒数')
      return
    }
    if (addCutPoint(parsed)) {
      setManualInput('')
      seekTo(parsed)
    }
  }

  const pointerToTime = useCallback((clientX) => {
    const track = trackRef.current
    if (!track || !duration) return 0
    const rect = track.getBoundingClientRect()
    if (rect.width <= 0) return 0
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    return roundTime(ratio * duration)
  }, [duration])

  const handleTrackPointerDown = (event) => {
    if (event.button !== 0 || !duration || submitting) return
    if (event.target.closest('.cv-vs-cut-marker')) return
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    dragState.current = { type: 'scrub', pointerId: event.pointerId }
    seekTo(pointerToTime(event.clientX))
  }

  const handleTrackPointerMove = (event) => {
    const active = dragState.current
    if (!active || active.pointerId !== event.pointerId || !duration) return
    if (active.type === 'scrub') {
      seekTo(pointerToTime(event.clientX))
      return
    }
    if (active.type === 'cut') {
      if (Math.abs(event.clientX - active.startX) > 3) {
        active.moved = true
      }
      if (!active.moved) return
      const minBound = 0.05
      const maxBound = Math.max(minBound, roundTime(duration - 0.05))
      const nextVal = roundTime(Math.max(minBound, Math.min(maxBound, pointerToTime(event.clientX))))
      setCutPoints(prev => {
        const copy = [...prev]
        if (active.index >= 0 && active.index < copy.length) {
          copy[active.index] = nextVal
        }
        return copy
      })
      seekTo(nextVal)
    }
  }

  const handleTrackPointerUp = (event) => {
    const active = dragState.current
    if (!active || active.pointerId !== event.pointerId) return
    dragState.current = null
    setDraggingIndex(null)
    if (active.type === 'cut') {
      if (!active.moved) {
        seekTo(active.initialValue)
      } else {
        setCutPoints(prev => normalizeCutPoints(prev, duration))
      }
    }
  }

  const handleMarkerPointerDown = (event, index, value) => {
    if (event.button !== 0 || !duration || submitting) return
    if (event.target.closest('.cv-vs-cut-marker-del')) return
    event.stopPropagation()
    event.preventDefault()
    trackRef.current?.setPointerCapture?.(event.pointerId)
    dragState.current = {
      type: 'cut',
      pointerId: event.pointerId,
      index,
      startX: event.clientX,
      initialValue: value,
      moved: false,
    }
    setDraggingIndex(index)
  }

  const preview = useMemo(() => {
    if (mode === 'points') {
      return computeTimelineSegments(duration, cutPoints)
    }
    const parsed = equalInput.trim() === '' ? NaN : Number(equalInput)
    return computeEqualSegments(duration, parsed)
  }, [mode, duration, cutPoints, equalInput])

  const visualSegments = useMemo(() => {
    if (preview.segments.length > 0) return preview.segments
    if (duration > 0) return [{ index: 1, start: 0, end: duration, duration }]
    return []
  }, [preview.segments, duration])

  const rulerTicks = useMemo(() => {
    if (!duration) return ['00:00.0', '—', '—', '—', '—']
    return [0, 0.25, 0.5, 0.75, 1].map(ratio => formatSplitTime(duration * ratio))
  }, [duration])

  const activeSegmentIndex = useMemo(() => {
    if (!visualSegments.length) return -1
    const found = visualSegments.find(seg => currentTime >= seg.start - 0.01 && currentTime < seg.end)
    if (found) return found.index
    if (currentTime >= duration - 0.02) return visualSegments[visualSegments.length - 1].index
    return visualSegments[0].index
  }, [visualSegments, currentTime, duration])

  const validationAlert = useMemo(() => {
    if (submitError) return submitError
    if (mediaError) return mediaError
    if (manualError) return manualError
    if (!duration) return ''
    if (duration < MIN_SEGMENT_SECONDS * 2) return preview.error || ''
    if (mode === 'points' && cutPoints.length === 0) return ''
    return preview.valid ? '' : (preview.error || '')
  }, [submitError, mediaError, manualError, duration, mode, cutPoints.length, preview])

  const handleConfirm = async () => {
    if (submitting || !preview.valid || !duration) return
    setSubmitError('')
    setSubmitting(true)
    const payload = mode === 'points'
      ? { mode: 'points', cut_points: preview.cutPoints }
      : { mode: 'equal', segment_duration: roundTime(Number(equalInput)) }
    try {
      await onConfirm(payload)
    } catch (failure) {
      setSubmitError(failure?.message || '视频分割失败，请重试')
      setSubmitting(false)
    }
  }

  const handleOverlayPointerDown = (event) => {
    event.stopPropagation()
    if (event.target === event.currentTarget && !submitting) {
      onClose()
    }
  }

  const handleDialogKeyDown = (event) => {
    event.stopPropagation()
    if (event.key === 'Escape') {
      event.preventDefault()
      if (!submitting) onClose()
    }
  }

  const displayName = title || asset?.name || '视频素材'
  const segmentCount = preview.valid ? preview.segments.length : 0
  const parsedEqual = equalInput.trim() === '' ? NaN : roundTime(Number(equalInput))

  return (
    <div
      className="cv-vs-overlay"
      onPointerDown={handleOverlayPointerDown}
      data-testid="video-split-overlay"
    >
      <div
        ref={dialogRef}
        className="cv-vs-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="视频分割"
        tabIndex={-1}
        onKeyDown={handleDialogKeyDown}
        onPointerDown={e => e.stopPropagation()}
      >
        <header className="cv-vs-header">
          <div className="cv-vs-title-group">
            <Scissors size={16} className="cv-vs-title-icon" aria-hidden="true" />
            <h3>视频分割</h3>
            <div className="cv-vs-meta-badges">
              <span className="cv-vs-badge" title={displayName}>{displayName}</span>
              <span className="cv-vs-badge is-duration" data-testid="video-split-duration">
                {duration > 0 ? `总时长 ${formatSplitTime(duration)}` : '读取时长中…'}
              </span>
            </div>
          </div>
          <button
            type="button"
            className="btn btn-icon btn-sm"
            aria-label="关闭"
            title="关闭"
            disabled={submitting}
            onClick={() => !submitting && onClose()}
          >
            <X size={15} aria-hidden="true" />
          </button>
        </header>

        <div className="cv-vs-body">
          <div className="cv-vs-stage">
            <div className="cv-vs-video-wrap">
              <video
                ref={videoRef}
                className="cv-vs-video"
                src={asset?.url || ''}
                preload="metadata"
                playsInline
                onLoadedMetadata={handleLoadedMetadata}
                onTimeUpdate={() => {
                  if (videoRef.current) setCurrentTime(roundTime(videoRef.current.currentTime))
                }}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onEnded={() => setPlaying(false)}
                onError={() => setMediaError('无法加载视频预览，请确认素材文件有效')}
              />
            </div>

            <div className="cv-vs-controls">
              <div className="cv-vs-transport">
                <button
                  type="button"
                  className="btn btn-sm"
                  aria-label={playing ? '暂停' : '播放'}
                  title={playing ? '暂停' : '播放'}
                  disabled={!duration || submitting}
                  onClick={togglePlay}
                >
                  {playing ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}
                  {playing ? '暂停' : '播放'}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  aria-label="后退 0.1 秒"
                  title="后退 0.1 秒"
                  disabled={!duration || submitting}
                  onClick={() => stepTime(-0.1)}
                >
                  -0.1s
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  aria-label="前进 0.1 秒"
                  title="前进 0.1 秒"
                  disabled={!duration || submitting}
                  onClick={() => stepTime(0.1)}
                >
                  +0.1s
                </button>
              </div>
              <div className="cv-vs-time-readout" data-testid="video-split-time">
                <strong>{formatSplitTime(currentTime)}</strong>
                <span> / {formatSplitTime(duration)}</span>
              </div>
            </div>

            <div className="cv-vs-timeline-section">
              <div className="cv-vs-ruler" aria-hidden="true">
                {rulerTicks.map((label, idx) => <span key={idx}>{label}</span>)}
              </div>

              <div
                ref={trackRef}
                className="cv-vs-track"
                data-testid="video-split-track"
                role="slider"
                aria-label="视频分割时间轴"
                aria-valuemin={0}
                aria-valuemax={duration || 0}
                aria-valuenow={currentTime}
                tabIndex={0}
                onPointerDown={handleTrackPointerDown}
                onPointerMove={handleTrackPointerMove}
                onPointerUp={handleTrackPointerUp}
                onPointerCancel={handleTrackPointerUp}
                onKeyDown={event => {
                  if (event.key === 'ArrowLeft') { event.preventDefault(); stepTime(-0.1) }
                  else if (event.key === 'ArrowRight') { event.preventDefault(); stepTime(0.1) }
                }}
              >
                {duration > 0 && visualSegments.map((seg, idx) => {
                  const leftPct = (seg.start / duration) * 100
                  const widthPct = ((seg.end - seg.start) / duration) * 100
                  const tooShort = seg.duration < MIN_SEGMENT_SECONDS - 1e-6
                  const isCurrent = seg.index === activeSegmentIndex
                  return (
                    <div
                      key={`${seg.index}-${seg.start}-${seg.end}`}
                      className={`cv-vs-seg-block ${idx % 2 === 0 ? 'is-odd' : 'is-even'}${isCurrent ? ' is-current' : ''}${tooShort ? ' is-too-short' : ''}`}
                      style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                    >
                      {widthPct >= 4.5 && <span className="cv-vs-seg-num">{seg.index}</span>}
                    </div>
                  )
                })}

                {duration > 0 && mode === 'equal' && preview.cutPoints.map(pt => (
                  <div
                    key={pt}
                    className="cv-vs-equal-marker"
                    style={{ left: `${(pt / duration) * 100}%` }}
                    aria-hidden="true"
                  />
                ))}

                {duration > 0 && (
                  <div
                    className="cv-vs-playhead"
                    style={{ left: `${Math.max(0, Math.min(100, (currentTime / duration) * 100))}%` }}
                    aria-hidden="true"
                  />
                )}

                {duration > 0 && mode === 'points' && cutPoints.map((pt, idx) => (
                  <div
                    key={`cut-${idx}`}
                    className={`cv-vs-cut-marker${draggingIndex === idx ? ' is-dragging' : ''}`}
                    style={{ left: `${Math.max(0, Math.min(100, (pt / duration) * 100))}%` }}
                    data-testid="video-split-cut-marker"
                    data-cut-time={pt}
                    role="button"
                    tabIndex={0}
                    aria-label={`切点 ${formatSplitTime(pt)}（拖动调整位置，按 Delete 删除）`}
                    title={`切点 ${formatSplitTime(pt)}（${pt.toFixed(2)}s），可拖动调整`}
                    onPointerDown={event => handleMarkerPointerDown(event, idx, pt)}
                    onKeyDown={event => {
                      if (event.key === 'Delete' || event.key === 'Backspace') {
                        event.preventDefault()
                        event.stopPropagation()
                        removeCutPoint(pt)
                      } else if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        event.stopPropagation()
                        seekTo(pt)
                      }
                    }}
                  >
                    <button
                      type="button"
                      className="cv-vs-cut-marker-del"
                      aria-label={`移除切点 ${formatSplitTime(pt)}`}
                      title="删除切点"
                      disabled={submitting}
                      onClick={event => {
                        event.stopPropagation()
                        removeCutPoint(pt)
                      }}
                    >
                      <X size={10} aria-hidden="true" />
                    </button>
                    <span className="cv-vs-cut-marker-cap" aria-hidden="true" />
                    <span className="cv-vs-cut-marker-stem" aria-hidden="true" />
                  </div>
                ))}
              </div>

              {mode === 'points' && (
                <div className="cv-vs-point-actions">
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={!duration || submitting}
                    onClick={() => addCutPoint(currentTime)}
                  >
                    <Plus size={14} aria-hidden="true" />
                    在当前时间添加切点
                  </button>
                  <div className="cv-vs-manual-add">
                    <input
                      type="number"
                      className="cv-vs-input cv-vs-manual-input"
                      step="0.1"
                      min={MIN_SEGMENT_SECONDS}
                      max={duration || undefined}
                      aria-label="切点秒数"
                      placeholder="秒数，如 2.5"
                      value={manualInput}
                      disabled={!duration || submitting}
                      onChange={event => {
                        setManualInput(event.target.value)
                        if (manualError) setManualError('')
                      }}
                      onKeyDown={event => {
                        if (event.key === 'Enter') {
                          event.preventDefault()
                          handleAddManual()
                        }
                      }}
                    />
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={!duration || submitting}
                      onClick={handleAddManual}
                    >
                      添加
                    </button>
                  </div>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    disabled={!cutPoints.length || submitting}
                    onClick={() => {
                      setCutPoints([])
                      setManualError('')
                      setSubmitError('')
                    }}
                  >
                    <Trash2 size={13} aria-hidden="true" />
                    清空切点
                  </button>
                </div>
              )}
            </div>
          </div>

          <aside className="cv-vs-sidebar">
            <div className="cv-vs-tabs" role="tablist" aria-label="分割模式">
              <button
                type="button"
                role="tab"
                className="cv-vs-tab"
                aria-selected={mode === 'points'}
                disabled={submitting}
                onClick={() => {
                  setMode('points')
                  setSubmitError('')
                  setManualError('')
                }}
              >
                按时间轴分割
              </button>
              <button
                type="button"
                role="tab"
                className="cv-vs-tab"
                aria-selected={mode === 'equal'}
                disabled={submitting}
                onClick={() => {
                  setMode('equal')
                  setSubmitError('')
                  setManualError('')
                  if (!equalTouched.current && duration > 0 && !equalInput) {
                    setEqualInput(defaultEqualDuration(duration))
                  }
                }}
              >
                按时长均分
              </button>
            </div>

            {mode === 'points' ? (
              <div className="cv-vs-config" role="tabpanel" aria-label="按时间轴分割配置">
                <p className="cv-vs-hint">
                  在时间轴定位并添加切点，或拖动轨道上的切点标记微调；每段不少于 {MIN_SEGMENT_SECONDS}s，最多 {MAX_SEGMENTS} 段。
                </p>
                {preview.cutPoints.length > 0 && (
                  <div className="cv-vs-chips" aria-label="已添加切点">
                    {preview.cutPoints.map(pt => (
                      <span key={pt} className="cv-vs-chip" data-testid="video-split-cut-chip">
                        <button
                          type="button"
                          className="cv-vs-chip-jump"
                          title={`跳转到 ${formatSplitTime(pt)}`}
                          onClick={() => seekTo(pt)}
                        >
                          {formatSplitTime(pt)}
                        </button>
                        <button
                          type="button"
                          className="cv-vs-chip-del"
                          aria-label={`删除切点 ${formatSplitTime(pt)}`}
                          disabled={submitting}
                          onClick={() => removeCutPoint(pt)}
                        >
                          <X size={11} aria-hidden="true" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="cv-vs-config" role="tabpanel" aria-label="按时长均分配置">
                <div className="cv-vs-field">
                  <label className="cv-vs-field-label" htmlFor="cv-vs-equal-duration">
                    单段时长
                  </label>
                  <div className="cv-vs-number-row">
                    <input
                      id="cv-vs-equal-duration"
                      type="number"
                      className="cv-vs-input cv-vs-equal-input"
                      aria-label="单段时长（秒）"
                      step="0.5"
                      min={MIN_SEGMENT_SECONDS}
                      value={equalInput}
                      disabled={!duration || submitting}
                      onChange={event => {
                        equalTouched.current = true
                        setEqualInput(event.target.value)
                        setSubmitError('')
                      }}
                    />
                    <span className="cv-vs-unit">秒（尾段 &lt;0.2s 自动合并）</span>
                  </div>
                </div>

                <div className="cv-vs-preset-group">
                  <span className="cv-vs-field-label">常用时长</span>
                  <div className="cv-vs-preset-row">
                    {DURATION_PRESETS.map(seconds => {
                      const disabled = !duration || seconds >= duration || submitting
                      const active = Number.isFinite(parsedEqual) && Math.abs(parsedEqual - seconds) < 1e-3
                      return (
                        <button
                          key={seconds}
                          type="button"
                          className={`btn btn-sm${active ? ' is-active' : ''}`}
                          disabled={disabled}
                          onClick={() => {
                            equalTouched.current = true
                            setEqualInput(String(seconds))
                            setSubmitError('')
                          }}
                        >
                          {seconds}s
                        </button>
                      )
                    })}
                  </div>
                </div>

                <div className="cv-vs-preset-group">
                  <span className="cv-vs-field-label">快捷均分段数</span>
                  <div className="cv-vs-preset-row">
                    {COUNT_PRESETS.map(count => {
                      const computed = duration > 0 ? roundTime(duration / count) : 0
                      const disabled = !duration || computed < MIN_SEGMENT_SECONDS || submitting
                      const active = preview.valid && preview.segments.length === count && Number.isFinite(parsedEqual) && Math.abs(parsedEqual - computed) < 0.002
                      return (
                        <button
                          key={count}
                          type="button"
                          className={`btn btn-sm${active ? ' is-active' : ''}`}
                          disabled={disabled}
                          onClick={() => {
                            equalTouched.current = true
                            setEqualInput(String(computed))
                            setSubmitError('')
                          }}
                        >
                          {count} 段
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
            )}

            <div className="cv-vs-segments-section">
              <div className="cv-vs-section-head">
                <span>分段预览</span>
                <span data-testid="video-split-segment-count">
                  {preview.segments.length > 0 ? `共 ${preview.segments.length} 段` : '未分段'}
                </span>
              </div>
              {preview.segments.length > 0 ? (
                <ul className="cv-vs-segments-list" data-testid="video-split-segments">
                  {preview.segments.map(seg => {
                    const tooShort = seg.duration < MIN_SEGMENT_SECONDS - 1e-6
                    const active = seg.index === activeSegmentIndex
                    return (
                      <li key={`${seg.index}-${seg.start}-${seg.end}`}>
                        <button
                          type="button"
                          className={`cv-vs-segment-item${active ? ' is-active' : ''}${tooShort ? ' is-too-short' : ''}`}
                          onClick={() => seekTo(seg.start)}
                          title={`跳转到片段 ${seg.index} 起点（${formatSplitTime(seg.start)}）`}
                        >
                          <span className="cv-vs-segment-name">片段 {seg.index}</span>
                          <span className="cv-vs-segment-range">
                            {formatSplitTime(seg.start)} → {formatSplitTime(seg.end)}
                          </span>
                          <span className="cv-vs-segment-dur">{seg.duration.toFixed(1)}s</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              ) : (
                <div className="cv-vs-empty-list">
                  {mode === 'points'
                    ? '添加至少 1 个切点后在此预览分段'
                    : '输入有效的单段时长后在此预览分段'}
                </div>
              )}
            </div>

            {validationAlert && (
              <div className="cv-vs-alert" role="alert" data-testid="video-split-error">
                <AlertCircle size={14} aria-hidden="true" />
                <span>{validationAlert}</span>
              </div>
            )}
          </aside>
        </div>

        <footer className="cv-vs-footer">
          <span className="cv-vs-footer-note">
            {segmentCount > 0
              ? `将生成 ${segmentCount} 个独立视频片段并存入素材库，原视频不会被修改`
              : '分割后的片段将存入素材库，原视频不会被修改'}
          </span>
          <div className="cv-vs-footer-actions">
            <button
              type="button"
              className="btn"
              disabled={submitting}
              onClick={() => !submitting && onClose()}
            >
              取消
            </button>
            <button
              type="button"
              className="btn btn-primary"
              data-testid="video-split-confirm"
              disabled={!preview.valid || !duration || submitting}
              onClick={handleConfirm}
            >
              {submitting ? (
                <>
                  <Loader2 size={14} className="cv-vs-spin" aria-hidden="true" />
                  正在分割视频…
                </>
              ) : (
                segmentCount > 0 ? `确认分割（生成 ${segmentCount} 段）` : '确认分割'
              )}
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
