import React from 'react'
import './shellArt.css'

// Precomputed natural acoustic speech/music phrase envelopes (normalized 0.08..1.0).
// Symmetric around a central baseline; avoids mechanical modulo/sawtooth repetition.
const CARD_ENVELOPE = [
  0.10, 0.14, 0.22, 0.18, 0.31, 0.44, 0.36, 0.26, 0.48, 0.66,
  0.52, 0.39, 0.62, 0.84, 0.72, 0.56, 0.92, 1.00, 0.86, 0.68,
  0.79, 0.61, 0.45, 0.74, 0.88, 0.64, 0.46, 0.54, 0.38, 0.28,
  0.42, 0.34, 0.23, 0.19, 0.14, 0.10,
]

const COMPACT_ENVELOPE = [
  0.14, 0.22, 0.35, 0.28, 0.52, 0.68, 0.48, 0.78, 0.94, 0.72,
  0.56, 0.88, 1.00, 0.82, 0.64, 0.90, 0.70, 0.49, 0.66, 0.54,
  0.38, 0.46, 0.31, 0.24, 0.18, 0.13,
]

/**
 * Unified organic acoustic waveform SVG.
 * - card: 240x120 viewBox for Task Gallery & Audio Detail previews
 * - compact: 240x42 viewBox for narrow containers
 */
export default function AudioWaveformArt({
  variant = 'card',
  compact = false,
  accent = 'amber',
  progress = null,
  className = '',
}) {
  const isMini = variant === 'compact'
  const heights = isMini ? COMPACT_ENVELOPE : CARD_ENVELOPE
  const viewWidth = 240
  const viewHeight = isMini ? 42 : 120
  const centerY = viewHeight / 2
  const maxHalfBar = isMini ? 15 : 36
  const padX = isMini ? 12 : 20
  const usableWidth = viewWidth - padX * 2
  const step = usableWidth / (heights.length - 1)
  const barWidth = isMini ? 2.6 : 2.8
  const accentColor = accent === 'purple' ? '#A47CF3' : '#f59e0b'
  const hasProgress = typeof progress === 'number' && Number.isFinite(progress)

  return (
    <svg
      viewBox={`0 0 ${viewWidth} ${viewHeight}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`art-svg audio-task-waveform audio-waveform-svg ${compact || isMini ? 'is-compact' : ''} ${className}`.trim()}
      data-art="audio-waveform"
      data-variant={variant}
      aria-hidden="true"
    >
      {/* Subtle concentric acoustic arcs (card variant only) */}
      {!isMini && (
        <g stroke="#f5f5f7" strokeLinecap="round">
          <path
            d="M72 30A56 56 0 0 1 168 30"
            strokeOpacity="0.06"
            strokeWidth="1"
          />
          <path
            d="M72 90A56 56 0 0 0 168 90"
            strokeOpacity="0.06"
            strokeWidth="1"
          />
          <path
            d="M88 38A38 38 0 0 1 152 38"
            stroke={accentColor}
            strokeOpacity="0.12"
            strokeWidth="1"
          />
          <path
            d="M88 82A38 38 0 0 0 152 82"
            stroke={accentColor}
            strokeOpacity="0.12"
            strokeWidth="1"
          />
        </g>
      )}

      {/* Center acoustic baseline */}
      <line
        x1={padX - 6}
        y1={centerY}
        x2={viewWidth - padX + 6}
        y2={centerY}
        stroke="#f5f5f7"
        strokeOpacity="0.14"
        strokeWidth="1"
        strokeLinecap="round"
      />

      {/* Symmetric organic waveform bars */}
      {heights.map((amp, index) => {
        const x = padX + index * step - barWidth / 2
        const half = Math.max(2, amp * maxHalfBar)
        const y = centerY - half
        const ratio = index / Math.max(1, heights.length - 1)
        const isPrimaryPeak = amp >= 0.72
        const played = hasProgress && ratio <= progress
        const fill = played
          ? accentColor
          : isPrimaryPeak
            ? accentColor
            : '#f5f5f7'
        const fillOpacity = played
          ? 0.9
          : isPrimaryPeak
            ? (amp >= 0.88 ? 0.82 : 0.62)
            : (0.18 + amp * 0.24)

        return (
          <rect
            key={index}
            x={Number(x.toFixed(2))}
            y={Number(y.toFixed(2))}
            width={barWidth}
            height={Number((half * 2).toFixed(2))}
            rx={barWidth / 2}
            fill={fill}
            fillOpacity={Number(fillOpacity.toFixed(2))}
          />
        )
      })}

      {/* Baseline end ticks */}
      <circle cx={padX - 6} cy={centerY} r="1.4" fill="#f5f5f7" fillOpacity="0.24" />
      <circle cx={viewWidth - padX + 6} cy={centerY} r="1.4" fill="#f5f5f7" fillOpacity="0.24" />
    </svg>
  )
}
