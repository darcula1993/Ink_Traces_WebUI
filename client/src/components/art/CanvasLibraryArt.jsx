import React from 'react'
import './canvasLibraryArt.css'

const INTERNAL_CANVAS_DRAG_TYPES = ['application/x-ink-library-media', 'application/x-ink-node']

/**
 * T2-6: Distinguish external OS file drags from internal canvas node / sidebar asset drags.
 */
export function isExternalFileDrag(dataTransfer, extraInternalTypes = []) {
  if (!dataTransfer) return false
  const types = [...(dataTransfer.types || [])]
  if (!types.includes('Files')) return false
  for (const internal of INTERNAL_CANVAS_DRAG_TYPES) {
    if (types.includes(internal)) return false
  }
  for (const internal of extraInternalTypes) {
    if (types.includes(internal)) return false
  }
  return true
}

// Organic, non-periodic acoustic envelopes (normalized 0.14..1.0).
// Symmetric vertically about the center baseline, shaped as natural multi-swell phrases (never % 7 sawtooth).
const COMPACT_WAVE_BARS = [
  0.16, 0.24, 0.20, 0.34, 0.52, 0.42, 0.28, 0.36, 0.62, 0.84,
  0.70, 0.48, 0.32, 0.44, 0.76, 0.96, 1.00, 0.88, 0.64, 0.46,
  0.58, 0.82, 0.72, 0.48, 0.34, 0.50, 0.66, 0.54, 0.36, 0.26,
  0.38, 0.46, 0.30, 0.22, 0.26, 0.16,
]

const CARD_WAVE_BARS = [
  0.14, 0.22, 0.34, 0.26, 0.46, 0.64, 0.50, 0.36, 0.58, 0.82,
  0.72, 0.52, 0.78, 0.98, 1.00, 0.86, 0.62, 0.44, 0.68, 0.80,
  0.60, 0.40, 0.52, 0.38, 0.28, 0.34, 0.22, 0.14,
]

const SILENT_WAVE_BARS = [0.22, 0.38, 0.28, 0.56, 0.82, 0.64, 0.42, 0.72, 0.50, 0.32, 0.44, 0.24]

/**
 * T1-4: Empty canvas "Node Ink Flow" fine-line architectural illustration (220x112).
 * Reference card -> restrained brand-green micro-flow Bezier curve -> generation frame card.
 */
export function EmptyCanvasFlowArt({ className = '' }) {
  return (
    <svg
      className={`ila-svg ila-canvas-empty ${className}`.trim()}
      width="220"
      height="112"
      viewBox="0 0 220 112"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      {/* Subtle coordinate registration marks */}
      <g className="ila-guide" strokeWidth="1" strokeLinecap="round">
        <path d="M8 14h4M10 12v4" />
        <path d="M208 98h4M210 96v4" />
        <path d="M108 16h4M110 14v4" />
      </g>

      {/* Secondary stacked reference shadow card */}
      <rect
        x="16"
        y="16"
        width="50"
        height="58"
        rx="6"
        className="ila-fill-xs ila-stroke-soft"
        strokeWidth="1"
        strokeDasharray="3 3"
      />

      {/* Left floating reference image card */}
      <g className="ila-card">
        <rect
          x="10"
          y="24"
          width="54"
          height="66"
          rx="6"
          className="ila-fill-sm ila-stroke-mid"
          strokeWidth="1.15"
        />
        {/* Card header divider */}
        <line x1="10" y1="36" x2="64" y2="36" className="ila-stroke-soft" strokeWidth="1" />
        <circle cx="17" cy="30" r="1.6" className="ila-stroke-mid" strokeWidth="1" />
        <line x1="22" y1="30" x2="40" y2="30" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />

        {/* Abstract geometric reference frame (no figurative content) */}
        <rect
          x="16"
          y="42"
          width="42"
          height="32"
          rx="3"
          className="ila-fill-xs ila-stroke-soft"
          strokeWidth="1"
        />
        <path
          d="M20 69L31 57L38 64L45 55L54 69"
          className="ila-stroke-mid"
          strokeWidth="1.1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="48" cy="49" r="2.2" className="ila-stroke-mid" strokeWidth="1" />
        {/* Bottom meta bar */}
        <line x1="16" y1="82" x2="36" y2="82" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />
      </g>

      {/* Source output port */}
      <circle cx="64" cy="57" r="3" className="ila-surface-fill ila-stroke-strong" strokeWidth="1.2" />

      {/* Bezier connection curve: structural base + subtle animated brand-green micro-flow */}
      <path
        d="M67 57C92 57 102 53 127 53"
        className="ila-stroke-mid"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <path
        d="M67 57C92 57 102 53 127 53"
        className="ila-flow-dash"
        pathLength="84"
        strokeWidth="1.35"
        strokeLinecap="round"
      />

      {/* Restrained static accent micro-dot along curve (remains crisp when reduced-motion is enabled) */}
      <circle cx="97" cy="55" r="5" className="ila-accent-halo" />
      <circle cx="97" cy="55" r="1.8" className="ila-accent-fill" />

      {/* Right floating generation shot node card */}
      <g className="ila-card">
        <rect
          x="130"
          y="14"
          width="80"
          height="84"
          rx="7"
          className="ila-fill-md ila-stroke-strong"
          strokeWidth="1.15"
        />
        {/* Node header */}
        <line x1="130" y1="27" x2="210" y2="27" className="ila-stroke-soft" strokeWidth="1" />
        <rect x="137" y="19" width="5" height="4" rx="1" className="ila-stroke-mid" strokeWidth="1" />
        <line x1="146" y1="21" x2="174" y2="21" className="ila-stroke-mid" strokeWidth="1.15" strokeLinecap="round" />
        <line x1="192" y1="21" x2="203" y2="21" className="ila-stroke-soft" strokeWidth="1" strokeLinecap="round" />

        {/* Shot generation viewfinder stage */}
        <rect
          x="138"
          y="34"
          width="64"
          height="38"
          rx="3.5"
          className="ila-fill-xs ila-stroke-soft"
          strokeWidth="1"
        />
        {/* Four delicate viewfinder corner brackets inside generation stage */}
        <path
          d="M142 42V38H146M194 38H198V42M198 64V68H194M146 68H142V64"
          className="ila-stroke-mid"
          strokeWidth="1.1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* Focal center frame reticle */}
        <path d="M167 53h6M170 50v6" className="ila-accent-stroke" strokeWidth="1.15" strokeLinecap="round" />
        <circle cx="170" cy="53" r="6.5" className="ila-stroke-soft" strokeWidth="1" />

        {/* Prompt lines & focal generate anchor */}
        <line x1="139" y1="81" x2="177" y2="81" className="ila-stroke-mid" strokeWidth="1.1" strokeLinecap="round" />
        <line x1="139" y1="88" x2="164" y2="88" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />
        <rect x="186" y="79" width="16" height="10" rx="5" className="ila-accent-soft-fill ila-accent-stroke" strokeWidth="1" />
      </g>

      {/* Target input port anchor with soft green halo */}
      <circle cx="130" cy="53" r="6" className="ila-accent-halo" />
      <circle cx="130" cy="53" r="3" className="ila-surface-fill ila-accent-stroke" strokeWidth="1.35" />
    </svg>
  )
}

/**
 * T1-6: Organic symmetric acoustic waveform envelope SVG.
 * - compact (240x42): inside canvas audio node MediaPlayer, reflects playback progress.
 * - card (240x120): inside asset library audio thumbnail cards.
 */
export function AudioWaveformArt({ variant = 'card', progress = 0, playing = false, className = '' }) {
  const isCompact = variant === 'compact'
  const bars = isCompact ? COMPACT_WAVE_BARS : CARD_WAVE_BARS
  const width = 240
  const height = isCompact ? 42 : 120
  const centerY = height / 2
  const padX = isCompact ? 10 : 22
  const spanW = width - padX * 2
  const step = spanW / bars.length
  const barW = isCompact ? 2.6 : 3.4
  const maxHalfH = isCompact ? 16.5 : 36
  const clampedProgress = Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : 0
  const hasProgress = isCompact && clampedProgress > 0.2
  const playheadX = padX + (spanW * clampedProgress) / 100

  return (
    <svg
      className={`ila-svg ila-waveform is-${variant}${playing ? ' is-playing' : ''}${hasProgress ? ' has-progress' : ''} ${className}`.trim()}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio={isCompact ? 'none' : 'xMidYMid meet'}
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      {/* Subtle dark radial acoustic halo behind center peak */}
      <ellipse
        cx={width / 2}
        cy={centerY}
        rx={isCompact ? 62 : 76}
        ry={isCompact ? 16 : 38}
        className="ila-wave-halo"
      />

      {/* Concentric subtle acoustic arcs for card variant */}
      {!isCompact && (
        <g className="ila-wave-arcs" strokeWidth="1" strokeDasharray="2 4">
          <circle cx="120" cy="60" r="36" />
          <circle cx="120" cy="60" r="52" />
        </g>
      )}

      {/* Center horizontal acoustic baseline */}
      <line
        x1={padX - 4}
        y1={centerY}
        x2={width - padX + 4}
        y2={centerY}
        className="ila-wave-baseline"
        strokeWidth="1"
        strokeLinecap="round"
      />

      {/* Symmetric organic bars */}
      {bars.map((amp, i) => {
        const cx = padX + (i + 0.5) * step
        const ratio = (i + 0.5) / bars.length
        const halfH = Math.max(2, amp * maxHalfH)
        const played = hasProgress && ratio * 100 <= clampedProgress
        const isPrimaryPeak = amp >= 0.88
        const isSecondaryPeak = !isPrimaryPeak && amp >= 0.66
        const barClass = played
          ? 'ila-wave-bar is-played'
          : isPrimaryPeak
            ? 'ila-wave-bar is-peak'
            : isSecondaryPeak
              ? 'ila-wave-bar is-violet'
              : 'ila-wave-bar'
        return (
          <rect
            key={i}
            x={Number((cx - barW / 2).toFixed(2))}
            y={Number((centerY - halfH).toFixed(2))}
            width={barW}
            height={Number((halfH * 2).toFixed(2))}
            rx={barW / 2}
            className={barClass}
            style={playing ? { '--ila-bar-delay': `${(i % 6) * 140}ms` } : undefined}
          />
        )
      })}

      {/* Subtle playhead indicator while playing/seeking */}
      {hasProgress && (
        <line
          x1={Number(playheadX.toFixed(1))}
          y1={4}
          x2={Number(playheadX.toFixed(1))}
          y2={height - 4}
          className="ila-wave-playhead"
          strokeWidth="1"
          strokeLinecap="round"
        />
      )}
    </svg>
  )
}

/**
 * T1-7 (Waiting state): Four 12x12 corner L-brackets + central type-specific fine-line viewfinder glyph.
 * Simplifies cleanly under .cv-world.is-lod-low.
 */
export function NodeWaitingArt({ kind = 'image' }) {
  return (
    <>
      <i className="ila-vf-corners" aria-hidden="true">
        <b className="ila-vf-corner is-tl" />
        <b className="ila-vf-corner is-tr" />
        <b className="ila-vf-corner is-bl" />
        <b className="ila-vf-corner is-br" />
      </i>
      {kind === 'video' ? (
        <svg
          className="ila-svg ila-waiting-glyph"
          width="54"
          height="38"
          viewBox="0 0 54 38"
          fill="none"
          aria-hidden="true"
          focusable="false"
        >
          {/* Cinema 16:9 letterbox frame */}
          <rect x="4" y="4" width="46" height="24" rx="2.5" className="ila-fill-xs ila-stroke-mid" strokeWidth="1.2" />
          {/* Inner composition play chevron */}
          <path d="M24.5 12.2L31.2 16L24.5 19.8Z" className="ila-stroke-strong" strokeWidth="1.2" strokeLinejoin="round" />
          {/* Timecode ruler ticks along bottom */}
          <g className="ila-lod-detail ila-stroke-soft" strokeWidth="1" strokeLinecap="round">
            <line x1="6" y1="33" x2="48" y2="33" />
            <line x1="8" y1="31" x2="8" y2="35" />
            <line x1="16" y1="32" x2="16" y2="34.5" />
            <line x1="24" y1="31" x2="24" y2="35" />
            <line x1="32" y1="32" x2="32" y2="34.5" />
            <line x1="40" y1="31" x2="40" y2="35" />
            <line x1="46" y1="32" x2="46" y2="34.5" />
          </g>
          {/* Subtle focal playhead tick */}
          <line x1="24" y1="30.5" x2="24" y2="35.5" className="ila-lod-detail ila-accent-stroke" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      ) : kind === 'audio' ? (
        <svg
          className="ila-svg ila-waiting-glyph"
          width="56"
          height="32"
          viewBox="0 0 56 32"
          fill="none"
          aria-hidden="true"
          focusable="false"
        >
          {/* Silent horizontal baseline */}
          <line x1="4" y1="16" x2="52" y2="16" className="ila-stroke-soft" strokeWidth="1" strokeLinecap="round" />
          {/* Subtle micro acoustic bars */}
          {SILENT_WAVE_BARS.map((amp, i) => {
            const x = 10 + i * 3.3
            const halfH = 1.5 + amp * 7.5
            const isCenter = i === 4 || i === 7
            return (
              <line
                key={i}
                x1={x}
                y1={Number((16 - halfH).toFixed(1))}
                x2={x}
                y2={Number((16 + halfH).toFixed(1))}
                className={isCenter ? 'ila-accent-stroke' : 'ila-stroke-mid'}
                strokeWidth="1.35"
                strokeLinecap="round"
              />
            )
          })}
          {/* End level ticks */}
          <path d="M5 13v6M51 13v6" className="ila-lod-detail ila-stroke-soft" strokeWidth="1" strokeLinecap="round" />
        </svg>
      ) : (
        <svg
          className="ila-svg ila-waiting-glyph"
          width="50"
          height="38"
          viewBox="0 0 50 38"
          fill="none"
          aria-hidden="true"
          focusable="false"
        >
          {/* Composition viewfinder frame */}
          <rect x="6" y="4" width="38" height="30" rx="2.5" className="ila-fill-xs ila-stroke-mid" strokeWidth="1.2" />
          {/* Rule-of-thirds faint guide ticks */}
          <g className="ila-lod-detail ila-stroke-soft" strokeWidth="1" strokeLinecap="round">
            <line x1="18.5" y1="6" x2="18.5" y2="9" />
            <line x1="31.5" y1="6" x2="31.5" y2="9" />
            <line x1="18.5" y1="29" x2="18.5" y2="32" />
            <line x1="31.5" y1="29" x2="31.5" y2="32" />
            <line x1="8" y1="14" x2="11" y2="14" />
            <line x1="8" y1="24" x2="11" y2="24" />
            <line x1="39" y1="14" x2="42" y2="14" />
            <line x1="39" y1="24" x2="42" y2="24" />
          </g>
          {/* Central viewfinder reticle */}
          <circle cx="25" cy="19" r="5.5" className="ila-stroke-strong" strokeWidth="1.15" />
          <circle cx="25" cy="19" r="1.5" className="ila-accent-fill" />
        </svg>
      )}
    </>
  )
}

/**
 * T1-7 (Unavailable state): Semantic separation between
 * - trashed: folded archive box (recoverable when task is restored)
 * - deleted: broken/fractured media frame (permanently deleted or missing)
 */
export function MediaUnavailableArt({ variant = 'deleted', size = 44, className = '' }) {
  if (variant === 'trashed') {
    return (
      <svg
        className={`ila-svg ila-unavailable is-trashed ${className}`.trim()}
        width={size}
        height={size}
        viewBox="0 0 48 48"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        {/* Archive box lid */}
        <rect x="8" y="11" width="32" height="7" rx="2" className="ila-fill-md ila-stroke-strong" strokeWidth="1.25" />
        {/* Archive box body */}
        <path
          d="M11 18v16a3 3 0 0 0 3 3h20a3 3 0 0 0 3-3V18"
          className="ila-fill-xs ila-stroke-mid"
          strokeWidth="1.25"
          strokeLinejoin="round"
        />
        {/* Recessed fold / handle slot */}
        <line x1="19" y1="23.5" x2="29" y2="23.5" className="ila-lod-detail ila-stroke-soft" strokeWidth="1.2" strokeLinecap="round" />
        {/* Subtle recoverable upward restore indicator */}
        <path
          d="M24 32.5V26.5M21 29.2L24 26.2L27 29.2"
          className="ila-warn-stroke"
          strokeWidth="1.3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  }

  return (
    <svg
      className={`ila-svg ila-unavailable is-deleted ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      {/* Broken media frame (upper-left intact, lower-right detached) */}
      <path
        d="M10 29V13a2.5 2.5 0 0 1 2.5-2.5h20"
        className="ila-stroke-mid"
        strokeWidth="1.25"
        strokeLinecap="round"
      />
      <path
        d="M38 19v16a2.5 2.5 0 0 1-2.5 2.5h-19"
        className="ila-stroke-soft"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeDasharray="3 3"
      />
      {/* Inner disconnected horizon stubs */}
      <path d="M14.5 27.5l5.5-5.5 3.5 3.5" className="ila-lod-detail ila-stroke-soft" strokeWidth="1.15" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="17.5" cy="17.5" r="2" className="ila-lod-detail ila-stroke-soft" strokeWidth="1.1" />
      {/* Clean diagonal break slash */}
      <line x1="11" y1="37" x2="37" y2="11" className="ila-danger-stroke" strokeWidth="1.35" strokeLinecap="round" />
    </svg>
  )
}

/**
 * T2-3: Global asset library empty states (120x84).
 * Variants: folder | generated | groups | search | remote
 */
export function LibraryEmptyArt({ kind = 'folder', className = '' }) {
  if (kind === 'groups') {
    return (
      <svg
        className={`ila-svg ila-lib-empty is-groups ${className}`.trim()}
        width="120"
        height="84"
        viewBox="0 0 120 84"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        {/* Dashed aggregation collection boundary */}
        <rect x="16" y="12" width="88" height="60" rx="8" className="ila-fill-xs ila-stroke-soft" strokeWidth="1.1" strokeDasharray="3.5 3.5" />
        {/* Three staggered reference cards */}
        <rect x="26" y="24" width="26" height="32" rx="4" className="ila-fill-sm ila-stroke-mid" strokeWidth="1.15" />
        <rect x="47" y="20" width="26" height="36" rx="4" className="ila-surface-fill ila-stroke-strong" strokeWidth="1.15" />
        <rect x="68" y="26" width="26" height="32" rx="4" className="ila-fill-sm ila-stroke-mid" strokeWidth="1.15" />
        {/* Reference tether link line & single green focal node */}
        <path d="M39 60c8 5 34 5 42 0" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />
        <circle cx="60" cy="38" r="5" className="ila-accent-halo" />
        <circle cx="60" cy="38" r="2" className="ila-accent-fill" />
        <line x1="53" y1="48" x2="67" y2="48" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />
      </svg>
    )
  }

  if (kind === 'generated') {
    return (
      <svg
        className={`ila-svg ila-lib-empty is-generated ${className}`.trim()}
        width="120"
        height="84"
        viewBox="0 0 120 84"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        {/* Timeline rail */}
        <line x1="14" y1="66" x2="106" y2="66" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />
        {/* Three sequential frame slots */}
        <rect x="18" y="24" width="24" height="32" rx="4" className="ila-fill-xs ila-stroke-soft" strokeWidth="1.1" />
        <rect x="48" y="18" width="24" height="38" rx="4" className="ila-fill-md ila-stroke-strong" strokeWidth="1.15" />
        <rect x="78" y="24" width="24" height="32" rx="4" className="ila-fill-xs ila-stroke-soft" strokeWidth="1.1" />
        {/* Center frame corner ticks */}
        <path d="M52 25v-3h3M65 22h3v3M68 49v3h-3M55 52h-3v-3" className="ila-stroke-mid" strokeWidth="1" strokeLinecap="round" />
        {/* Timeline markers + focal green dot */}
        <circle cx="30" cy="66" r="2" className="ila-surface-fill ila-stroke-mid" strokeWidth="1.1" />
        <circle cx="60" cy="66" r="5.5" className="ila-accent-halo" />
        <circle cx="60" cy="66" r="2.4" className="ila-accent-fill" />
        <circle cx="90" cy="66" r="2" className="ila-surface-fill ila-stroke-mid" strokeWidth="1.1" />
      </svg>
    )
  }

  if (kind === 'search') {
    return (
      <svg
        className={`ila-svg ila-lib-empty is-search ${className}`.trim()}
        width="120"
        height="84"
        viewBox="0 0 120 84"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        {/* Faint empty grid cells */}
        <rect x="20" y="16" width="24" height="22" rx="3" className="ila-fill-xs ila-stroke-soft" strokeWidth="1" strokeDasharray="3 3" />
        <rect x="48" y="16" width="24" height="22" rx="3" className="ila-fill-xs ila-stroke-soft" strokeWidth="1" strokeDasharray="3 3" />
        <rect x="76" y="16" width="24" height="22" rx="3" className="ila-fill-xs ila-stroke-soft" strokeWidth="1" strokeDasharray="3 3" />
        <rect x="20" y="44" width="24" height="22" rx="3" className="ila-fill-xs ila-stroke-soft" strokeWidth="1" strokeDasharray="3 3" />
        {/* Neutral minimalist magnifying lens (no overuse of green per spec) */}
        <circle cx="68" cy="48" r="13.5" className="ila-surface-fill ila-stroke-strong" strokeWidth="1.25" />
        <path d="M64.5 48h7" className="ila-stroke-mid" strokeWidth="1.2" strokeLinecap="round" />
        <line x1="78" y1="58" x2="88" y2="68" className="ila-stroke-strong" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }

  if (kind === 'remote') {
    return (
      <svg
        className={`ila-svg ila-lib-empty is-remote ${className}`.trim()}
        width="120"
        height="84"
        viewBox="0 0 120 84"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        {/* Remote node frame */}
        <rect x="28" y="20" width="64" height="44" rx="6" className="ila-fill-sm ila-stroke-mid" strokeWidth="1.15" />
        <line x1="28" y1="32" x2="92" y2="32" className="ila-stroke-soft" strokeWidth="1" />
        {/* Faint remote signal arcs */}
        <path d="M51 50a11 11 0 0 1 18 0" className="ila-stroke-mid" strokeWidth="1.15" strokeLinecap="round" />
        <path d="M45 45a19 19 0 0 1 30 0" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />
        <circle cx="60" cy="54" r="2.2" className="ila-accent-fill" />
        {/* Registration ticks */}
        <path d="M18 42h4M98 42h4" className="ila-stroke-soft" strokeWidth="1" strokeLinecap="round" />
      </svg>
    )
  }

  // Default: open dark folder skeleton + floating media frame
  return (
    <svg
      className={`ila-svg ila-lib-empty is-folder ${className}`.trim()}
      width="120"
      height="84"
      viewBox="0 0 120 84"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      {/* Back folder tab */}
      <path
        d="M22 28a4 4 0 0 1 4-4h18l5 6h45a4 4 0 0 1 4 4v6H22V28Z"
        className="ila-fill-xs ila-stroke-soft"
        strokeWidth="1.1"
        strokeLinejoin="round"
      />
      {/* Gently rising media frame card */}
      <rect x="42" y="14" width="36" height="28" rx="4" className="ila-surface-fill ila-stroke-strong" strokeWidth="1.15" />
      <path d="M47 36l8-8 6 6 5-5 7 7" className="ila-stroke-mid" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="71" cy="21" r="2" className="ila-accent-fill" />
      {/* Front folder pocket */}
      <path
        d="M19 36h82l-4 32a4 4 0 0 1-4 3.5H27a4 4 0 0 1-4-3.5L19 36Z"
        className="ila-fill-md ila-stroke-mid"
        strokeWidth="1.15"
        strokeLinejoin="round"
      />
      <line x1="48" y1="53" x2="72" y2="53" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  )
}

/**
 * T2-3: Character library empty states.
 * - guide (156x104): right-side structural guide showing multi-angle slots + voice waveform + @角色卡名 pill.
 * - list (96x64): compact left-column empty dossier outline.
 */
export function CharacterEmptyArt({ variant = 'guide', className = '' }) {
  if (variant === 'list') {
    return (
      <svg
        className={`ila-svg ila-char-empty is-list ${className}`.trim()}
        width="96"
        height="64"
        viewBox="0 0 96 64"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <rect x="14" y="8" width="68" height="48" rx="6" className="ila-fill-sm ila-stroke-mid" strokeWidth="1.1" />
        {/* Abstract proportion slot */}
        <rect x="21" y="15" width="20" height="20" rx="3" className="ila-fill-xs ila-stroke-soft" strokeWidth="1" />
        <circle cx="31" cy="22" r="3" className="ila-stroke-mid" strokeWidth="1" />
        <path d="M25.5 32c1-3.2 3-4.6 5.5-4.6s4.5 1.4 5.5 4.6" className="ila-stroke-mid" strokeWidth="1" strokeLinecap="round" />
        {/* Meta & voice mini bars */}
        <line x1="47" y1="19" x2="74" y2="19" className="ila-stroke-mid" strokeWidth="1.1" strokeLinecap="round" />
        <line x1="47" y1="26" x2="66" y2="26" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />
        <path d="M22 45h22" className="ila-accent-stroke" strokeWidth="1.2" strokeLinecap="round" />
        <path d="M52 45v-3M56 47v-7M60 46v-5M64 48v-9M68 46v-5M72 45v-3" className="ila-stroke-mid" strokeWidth="1.15" strokeLinecap="round" />
      </svg>
    )
  }

  return (
    <svg
      className={`ila-svg ila-char-empty is-guide ${className}`.trim()}
      width="160"
      height="108"
      viewBox="0 0 160 108"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      {/* Outer dossier frame */}
      <rect x="12" y="8" width="136" height="68" rx="8" className="ila-fill-sm ila-stroke-mid" strokeWidth="1.15" />

      {/* Top-left: 2x2 multi-angle reference slots (strictly abstract geometry, zero facial features) */}
      <g>
        <rect x="22" y="17" width="22" height="22" rx="3" className="ila-fill-md ila-stroke-strong" strokeWidth="1.1" />
        <circle cx="33" cy="24.5" r="3.2" className="ila-stroke-mid" strokeWidth="1.05" />
        <path d="M27.5 35.5c1-3.4 3.2-4.8 5.5-4.8s4.5 1.4 5.5 4.8" className="ila-stroke-mid" strokeWidth="1.05" strokeLinecap="round" />

        <rect x="48" y="17" width="22" height="22" rx="3" className="ila-fill-xs ila-stroke-soft" strokeWidth="1" />
        <path d="M53 23h4M59 28h6M53 33h10" className="ila-stroke-soft" strokeWidth="1" strokeLinecap="round" />

        <rect x="22" y="43" width="22" height="22" rx="3" className="ila-fill-xs ila-stroke-soft" strokeWidth="1" />
        <path d="M27 59l4-4 3 3 3-3 3 4" className="ila-stroke-soft" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />

        <rect x="48" y="43" width="22" height="22" rx="3" className="ila-fill-xs ila-stroke-soft" strokeWidth="1" strokeDasharray="2.5 2.5" />
        <path d="M59 51v6M56 54h6" className="ila-stroke-mid" strokeWidth="1.1" strokeLinecap="round" />
      </g>

      {/* Top-right: descriptor lines */}
      <line x1="80" y1="22" x2="134" y2="22" className="ila-stroke-strong" strokeWidth="1.2" strokeLinecap="round" />
      <line x1="80" y1="30" x2="122" y2="30" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />
      <line x1="80" y1="37" x2="110" y2="37" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />

      {/* Bottom-right: voice waveform strip */}
      <rect x="80" y="45" width="58" height="20" rx="4" className="ila-fill-xs ila-stroke-soft" strokeWidth="1" />
      <line x1="86" y1="55" x2="132" y2="55" className="ila-stroke-soft" strokeWidth="0.9" />
      {[2, 4.5, 3, 6.5, 5, 7.5, 4, 6, 3.5, 5, 2.5].map((h, i) => (
        <line
          key={i}
          x1={89 + i * 4}
          y1={55 - h}
          x2={89 + i * 4}
          y2={55 + h}
          className={i === 5 ? 'ila-accent-stroke' : 'ila-stroke-mid'}
          strokeWidth="1.35"
          strokeLinecap="round"
        />
      ))}

      {/* Connector tick from card to @mention pill */}
      <line x1="80" y1="76" x2="80" y2="83" className="ila-accent-stroke" strokeWidth="1.1" strokeDasharray="2 2" />

      {/* Bottom-center: @角色卡名 capsule pill with restrained brand-green outline */}
      <rect x="44" y="83" width="72" height="20" rx="10" className="ila-accent-soft-fill ila-accent-stroke" strokeWidth="1.15" />
      <text
        x="80"
        y="96.5"
        textAnchor="middle"
        className="ila-pill-text"
        fontSize="10"
        fontWeight="500"
      >
        @角色卡名
      </text>
    </svg>
  )
}

/**
 * T2-3: Character / prop card 48x48 cover placeholder.
 * Viewfinder ruler ticks + abstract proportion silhouette (character) or isometric cube (prop).
 * Strictly zero facial features or genre styling.
 */
export function CharacterCoverPlaceholder({ kind = 'character', className = '' }) {
  const isProp = kind === 'prop'
  return (
    <svg
      className={`ila-svg ila-char-cover is-${isProp ? 'prop' : 'character'} ${className}`.trim()}
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      {/* Subtle inner framing corner ticks */}
      <path
        d="M5 10V5h5M38 5h5v5M43 38v5h-5M10 43H5v-5"
        className="ila-stroke-soft"
        strokeWidth="1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {isProp ? (
        <>
          {/* Architectural isometric cube wireframe */}
          <path
            d="M24 12L35 18.2V30.8L24 37L13 30.8V18.2L24 12Z"
            className="ila-fill-xs ila-stroke-mid"
            strokeWidth="1.2"
            strokeLinejoin="round"
          />
          <path d="M13 18.2L24 24.4L35 18.2M24 24.4V37" className="ila-stroke-mid" strokeWidth="1.1" strokeLinejoin="round" />
          <circle cx="24" cy="24.4" r="1.5" className="ila-accent-fill" />
        </>
      ) : (
        <>
          {/* Abstract human proportion silhouette + vertical axis/eye-level ticks (zero face) */}
          <line x1="24" y1="8" x2="24" y2="11" className="ila-stroke-soft" strokeWidth="1" strokeLinecap="round" />
          <line x1="9" y1="18" x2="12" y2="18" className="ila-stroke-soft" strokeWidth="1" strokeLinecap="round" />
          <line x1="36" y1="18" x2="39" y2="18" className="ila-stroke-soft" strokeWidth="1" strokeLinecap="round" />
          <ellipse cx="24" cy="18" rx="5.2" ry="6" className="ila-fill-xs ila-stroke-mid" strokeWidth="1.2" />
          <path
            d="M13 38.5C14.2 31.6 18.4 28.2 24 28.2C29.6 28.2 33.8 31.6 35 38.5"
            className="ila-fill-xs ila-stroke-mid"
            strokeWidth="1.2"
            strokeLinecap="round"
          />
          <line x1="17" y1="34.5" x2="31" y2="34.5" className="ila-stroke-soft" strokeWidth="1" strokeLinecap="round" strokeDasharray="2 2" />
        </>
      )}
    </svg>
  )
}

/**
 * T2-4: Compact empty-state fine-line graphic for narrow CanvasTaskPanel sidebar (72x48).
 */
export function CanvasTaskEmptyArt({ className = '' }) {
  return (
    <svg
      className={`ila-svg ila-task-empty ${className}`.trim()}
      width="72"
      height="48"
      viewBox="0 0 72 48"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      {/* Top queued slot */}
      <rect x="6" y="7" width="60" height="14" rx="4" className="ila-fill-md ila-stroke-mid" strokeWidth="1.1" />
      <circle cx="14" cy="14" r="2.2" className="ila-accent-fill" />
      <line x1="21" y1="14" x2="46" y2="14" className="ila-stroke-mid" strokeWidth="1.15" strokeLinecap="round" />
      <line x1="54" y1="14" x2="60" y2="14" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />

      {/* Second idle slot */}
      <rect x="6" y="27" width="60" height="14" rx="4" className="ila-fill-xs ila-stroke-soft" strokeWidth="1.1" strokeDasharray="3 3" />
      <circle cx="14" cy="34" r="2" className="ila-stroke-soft" strokeWidth="1.1" />
      <line x1="21" y1="34" x2="39" y2="34" className="ila-stroke-soft" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  )
}

/**
 * T2-6: Canvas external file drag-in viewfinder drop overlay.
 * Pointer-events disabled so dragover/dragleave/drop events flow cleanly to .cv-surface.
 */
export function CanvasFileDropOverlay() {
  return (
    <div
      className="cv-file-drop-overlay"
      data-testid="canvas-file-drop-overlay"
      role="status"
      aria-live="polite"
    >
      <div className="cv-file-drop-frame" aria-hidden="true">
        <span className="cv-file-drop-corner is-tl" />
        <span className="cv-file-drop-corner is-tr" />
        <span className="cv-file-drop-corner is-bl" />
        <span className="cv-file-drop-corner is-br" />
      </div>
      <div className="cv-file-drop-card">
        <svg
          className="ila-svg ila-drop-glyph"
          width="52"
          height="42"
          viewBox="0 0 52 42"
          fill="none"
          aria-hidden="true"
          focusable="false"
        >
          <rect x="6" y="6" width="40" height="30" rx="5" className="ila-fill-sm ila-stroke-mid" strokeWidth="1.2" strokeDasharray="3 3" />
          <path d="M26 14v13M21 22.5L26 27.5L31 22.5" className="ila-accent-stroke" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <line x1="18" y1="31" x2="34" y2="31" className="ila-stroke-soft" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        <strong>松开以导入到画布</strong>
        <span>支持图片、视频与音频文件</span>
      </div>
    </div>
  )
}

/**
 * T2-7: Dedicated linear icons for video frame capture (exact Lucide 24x24 / strokeWidth 1.75 / round match).
 */
export function CaptureCurrentFrameIcon({ size = 15, ...props }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {/* Film frame */}
      <rect x="3" y="6" width="18" height="12" rx="2" />
      {/* Sprocket ticks */}
      <path d="M7 6v2M17 6v2M7 16v2M17 16v2" />
      {/* Playhead vertical cursor line */}
      <path d="M12 2.5v19" />
      <path d="M10 2.5h4" />
    </svg>
  )
}

export function CaptureTailFrameIcon({ size = 15, ...props }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {/* Film frame */}
      <rect x="2.5" y="6" width="14.5" height="12" rx="2" />
      {/* Left sprocket ticks */}
      <path d="M6.5 6v2M6.5 16v2" />
      {/* Cue chevron toward tail frame */}
      <path d="M10.5 9.5L13 12l-2.5 2.5" />
      {/* Terminal end-frame vertical bar */}
      <path d="M21 4.5v15" />
    </svg>
  )
}
