import React from 'react'
import './shellArt.css'

/**
 * T1-5: Layer Studio empty state — isometric 3-layer transparent decomposition line art (156x108).
 * Hovering or dragging a file lifts the extracted top layer via pure CSS.
 */
export function LayerExplodeArt({ className = '' }) {
  return (
    <svg
      width="156"
      height="108"
      viewBox="0 0 156 108"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`art-svg art-layer-explode ${className}`.trim()}
      data-art="layer-explode"
      aria-hidden="true"
    >
      {/* Vertical dashed registration guides */}
      <g stroke="#f5f5f7" strokeOpacity="0.14" strokeWidth="1" strokeDasharray="2 3">
        <line x1="78" y1="16" x2="78" y2="94" />
        <line x1="34" y1="36" x2="34" y2="74" />
        <line x1="122" y1="36" x2="122" y2="74" />
      </g>

      {/* Bottom plane: base canvas frame */}
      <g className="art-layer-base">
        <path
          d="M78 56L122 74L78 92L34 74L78 56Z"
          fill="#ffffff"
          fillOpacity="0.03"
          stroke="#f5f5f7"
          strokeOpacity="0.22"
          strokeWidth="1.2"
          strokeLinejoin="round"
        />
        <path
          d="M66 75L78 80L90 75"
          stroke="#f5f5f7"
          strokeOpacity="0.18"
          strokeWidth="1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>

      {/* Middle plane: alpha transparency plane with subtle micro-checker crosslines */}
      <g className="art-layer-mid">
        <path
          d="M78 38L122 56L78 74L34 56L78 38Z"
          fill="#ffffff"
          fillOpacity="0.05"
          stroke="#f5f5f7"
          strokeOpacity="0.28"
          strokeWidth="1.2"
          strokeLinejoin="round"
        />
        {/* Isometric checker ticks */}
        <path
          d="M63 50L93 62M53 54L83 66M93 50L63 62M103 54L73 66"
          stroke="#f5f5f7"
          strokeOpacity="0.11"
          strokeWidth="1"
          strokeLinecap="round"
        />
      </g>

      {/* Top plane: extracted subject layer highlighted in brand amber */}
      <g className="art-layer-top">
        <path
          d="M78 18L122 36L78 54L34 36L78 18Z"
          fill="#f59e0b"
          fillOpacity="0.065"
          stroke="#f59e0b"
          strokeOpacity="0.82"
          strokeWidth="1.25"
          strokeLinejoin="round"
        />
        {/* Inner subject contour geometry */}
        <path
          d="M78 27L98 35.5L78 44L58 35.5L78 27Z"
          fill="#f59e0b"
          fillOpacity="0.1"
          stroke="#f59e0b"
          strokeOpacity="0.48"
          strokeWidth="1"
          strokeLinejoin="round"
        />
        {/* Four precision corner handles */}
        <circle cx="78" cy="18" r="2" fill="#050507" stroke="#f59e0b" strokeWidth="1.2" />
        <circle cx="122" cy="36" r="2" fill="#050507" stroke="#f59e0b" strokeWidth="1.2" />
        <circle cx="78" cy="54" r="2" fill="#050507" stroke="#f59e0b" strokeWidth="1.2" />
        <circle cx="34" cy="36" r="2" fill="#050507" stroke="#f59e0b" strokeWidth="1.2" />
      </g>
    </svg>
  )
}

/**
 * T2-2: Five semantic empty-state architectural line illustrations (120x84)
 * for TaskGallery and GlobalTaskCenter.
 * Note: empty-trash and empty-search stay strictly neutral (no brand accent).
 */
export function TaskEmptyArt({ kind = 'empty-tasks', className = '' }) {
  return (
    <svg
      width="120"
      height="84"
      viewBox="0 0 120 84"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`art-svg art-task-empty ${className}`.trim()}
      data-art={`task-${kind}`}
      aria-hidden="true"
    >
      {kind === 'empty-favorites' ? (
        <>
          {/* Layered favorite frame folder */}
          <rect x="20" y="20" width="80" height="50" rx="6" fill="#ffffff" fillOpacity="0.025" stroke="#f5f5f7" strokeOpacity="0.2" strokeWidth="1.2" />
          <path d="M20 26C20 22.686 22.686 20 26 20H46L52 26H94C97.314 26 100 28.686 100 32" stroke="#f5f5f7" strokeOpacity="0.28" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
          <rect x="30" y="32" width="60" height="30" rx="4" fill="#ffffff" fillOpacity="0.03" stroke="#f5f5f7" strokeOpacity="0.16" strokeWidth="1" strokeDasharray="3 3" />
          {/* Geometric star bookmark accent in brand amber */}
          <path
            d="M60 37L62.8 43.2L69.5 44L64.4 48.5L65.9 55L60 51.6L54.1 55L55.6 48.5L50.5 44L57.2 43.2L60 37Z"
            fill="#f59e0b"
            fillOpacity="0.14"
            stroke="#f59e0b"
            strokeOpacity="0.85"
            strokeWidth="1.2"
            strokeLinejoin="round"
          />
        </>
      ) : kind === 'empty-active' ? (
        <>
          {/* Calm horizontal timeline frame */}
          <rect x="16" y="22" width="88" height="40" rx="6" fill="#ffffff" fillOpacity="0.025" stroke="#f5f5f7" strokeOpacity="0.22" strokeWidth="1.2" />
          <line x1="26" y1="42" x2="94" y2="42" stroke="#f5f5f7" strokeOpacity="0.18" strokeWidth="1.2" strokeLinecap="round" />
          {/* Serene standby pulse */}
          <path
            d="M42 42H51L55 34L60 50L65 38L69 42H78"
            stroke="#f59e0b"
            strokeOpacity="0.82"
            strokeWidth="1.3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="30" cy="42" r="2.2" fill="#f5f5f7" fillOpacity="0.28" />
          <circle cx="90" cy="42" r="2.2" fill="#f5f5f7" fillOpacity="0.28" />
          <circle cx="60" cy="42" r="12" stroke="#f59e0b" strokeOpacity="0.16" strokeWidth="1" strokeDasharray="2 3" />
        </>
      ) : kind === 'empty-trash' ? (
        <>
          {/* Clean neutral archive tray (strictly neutral) */}
          <path
            d="M28 28H92L86 66C85.6 68.4 83.6 70 81.2 70H38.8C36.4 70 34.4 68.4 34 66L28 28Z"
            fill="#ffffff"
            fillOpacity="0.03"
            stroke="#f5f5f7"
            strokeOpacity="0.26"
            strokeWidth="1.2"
            strokeLinejoin="round"
          />
          <path d="M22 28H98" stroke="#f5f5f7" strokeOpacity="0.34" strokeWidth="1.2" strokeLinecap="round" />
          <path d="M48 28V22C48 20.343 49.343 19 51 19H69C70.657 19 72 20.343 72 22V28" stroke="#f5f5f7" strokeOpacity="0.24" strokeWidth="1.2" strokeLinejoin="round" />
          <path d="M46 42V58M60 40V58M74 42V58" stroke="#f5f5f7" strokeOpacity="0.15" strokeWidth="1.2" strokeLinecap="round" />
        </>
      ) : kind === 'empty-search' ? (
        <>
          {/* Empty precision grid + optical loupe (strictly neutral) */}
          <rect x="20" y="18" width="56" height="44" rx="5" fill="#ffffff" fillOpacity="0.025" stroke="#f5f5f7" strokeOpacity="0.2" strokeWidth="1.2" />
          <line x1="28" y1="30" x2="54" y2="30" stroke="#f5f5f7" strokeOpacity="0.16" strokeWidth="1.2" strokeLinecap="round" />
          <line x1="28" y1="40" x2="46" y2="40" stroke="#f5f5f7" strokeOpacity="0.14" strokeWidth="1.2" strokeLinecap="round" />
          <line x1="28" y1="50" x2="42" y2="50" stroke="#f5f5f7" strokeOpacity="0.12" strokeWidth="1.2" strokeLinecap="round" />
          <circle cx="74" cy="48" r="15" fill="#050507" fillOpacity="0.85" stroke="#f5f5f7" strokeOpacity="0.34" strokeWidth="1.3" />
          <path d="M74 42V54M68 48H80" stroke="#f5f5f7" strokeOpacity="0.16" strokeWidth="1" strokeLinecap="round" />
          <path d="M85 59L96 70" stroke="#f5f5f7" strokeOpacity="0.38" strokeWidth="1.8" strokeLinecap="round" />
        </>
      ) : (
        <>
          {/* empty-tasks: stacked architectural queue cards */}
          <rect x="28" y="14" width="64" height="16" rx="4" fill="#ffffff" fillOpacity="0.02" stroke="#f5f5f7" strokeOpacity="0.16" strokeWidth="1.15" />
          <rect x="22" y="34" width="76" height="22" rx="5" fill="#ffffff" fillOpacity="0.04" stroke="#f5f5f7" strokeOpacity="0.28" strokeWidth="1.2" />
          <rect x="28" y="60" width="64" height="12" rx="4" fill="#ffffff" fillOpacity="0.02" stroke="#f5f5f7" strokeOpacity="0.14" strokeWidth="1.15" strokeDasharray="3 3" />
          {/* Focus anchor & minimal progress line */}
          <circle cx="33" cy="45" r="2.8" fill="#f59e0b" fillOpacity="0.9" />
          <line x1="42" y1="42" x2="72" y2="42" stroke="#f5f5f7" strokeOpacity="0.3" strokeWidth="1.2" strokeLinecap="round" />
          <line x1="42" y1="48" x2="58" y2="48" stroke="#f59e0b" strokeOpacity="0.55" strokeWidth="1.2" strokeLinecap="round" />
          <rect x="82" y="40" width="9" height="10" rx="2" stroke="#f5f5f7" strokeOpacity="0.2" strokeWidth="1.1" />
        </>
      )}
    </svg>
  )
}

/**
 * T1-7: Distinct semantic placeholders separating:
 * - trashed: folded archive vault (restorable)
 * - deleted: severed broken media frame (permanently deleted)
 * - unavailable: disconnected preview frame
 */
export function TaskPlaceholderArt({ kind = 'deleted', compact = true, className = '' }) {
  const width = compact ? 52 : 68
  const height = compact ? 42 : 54

  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 64 52"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`art-svg art-placeholder-${kind} ${className}`.trim()}
      data-art={`placeholder-${kind}`}
      aria-hidden="true"
    >
      {kind === 'trashed' ? (
        <>
          {/* Folded restorable archive box (neutral + subtle warm-amber cue) */}
          <rect x="12" y="18" width="40" height="24" rx="4" fill="#ffffff" fillOpacity="0.035" stroke="#fbbf24" strokeOpacity="0.46" strokeWidth="1.2" />
          <path d="M9 14.5C9 12.567 10.567 11 12.5 11H51.5C53.433 11 55 12.567 55 14.5V18H9V14.5Z" fill="#fbbf24" fillOpacity="0.07" stroke="#fbbf24" strokeOpacity="0.58" strokeWidth="1.2" strokeLinejoin="round" />
          <path d="M25 26H39" stroke="#f5f5f7" strokeOpacity="0.42" strokeWidth="1.3" strokeLinecap="round" />
          {/* Subtle return/restore arc inside */}
          <path d="M28 33.5C29.4 31.8 31.1 31 33 31C35.2 31 37 32.3 37.8 34.2" stroke="#fbbf24" strokeOpacity="0.65" strokeWidth="1.15" strokeLinecap="round" />
          <path d="M26.5 31.2V34.2H29.5" stroke="#fbbf24" strokeOpacity="0.65" strokeWidth="1.15" strokeLinecap="round" strokeLinejoin="round" />
        </>
      ) : kind === 'unavailable' ? (
        <>
          {/* Disconnected preview frame */}
          <rect x="11" y="10" width="42" height="32" rx="4" fill="#ffffff" fillOpacity="0.025" stroke="#f5f5f7" strokeOpacity="0.28" strokeWidth="1.2" />
          <path d="M18 35L27 26L33 32L39 26L46 33" stroke="#f5f5f7" strokeOpacity="0.18" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="24" cy="19" r="2.2" stroke="#f5f5f7" strokeOpacity="0.24" strokeWidth="1.1" />
          <line x1="15" y1="43" x2="49" y2="9" stroke="#f5f5f7" strokeOpacity="0.45" strokeWidth="1.3" strokeLinecap="round" />
        </>
      ) : (
        <>
          {/* Permanently deleted: broken dashed frame with severed corner */}
          <path
            d="M26 11H15C12.791 11 11 12.791 11 15V37C11 39.209 12.791 41 15 41H38"
            stroke="#f5f5f7"
            strokeOpacity="0.32"
            strokeWidth="1.2"
            strokeDasharray="3 3"
            strokeLinecap="round"
          />
          <path
            d="M36 11H49C51.209 11 53 12.791 53 15V29"
            stroke="#f5f5f7"
            strokeOpacity="0.24"
            strokeWidth="1.2"
            strokeLinecap="round"
          />
          {/* Severed media cross inside */}
          <path d="M27 21L37 31M37 21L27 31" stroke="#f87171" strokeOpacity="0.62" strokeWidth="1.35" strokeLinecap="round" />
          {/* Detached bottom-right corner fragment */}
          <path d="M46 39L52 33" stroke="#f5f5f7" strokeOpacity="0.22" strokeWidth="1.2" strokeLinecap="round" />
        </>
      )}
    </svg>
  )
}

function hashSeed(seed) {
  const str = String(seed ?? '')
  let hash = 2166136261
  for (let i = 0; i < str.length; i += 1) {
    hash ^= str.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return Math.abs(hash) % 4
}

/**
 * T2-1: Deterministic 96x72 subtle geometric topology corner motif for coverless project cards.
 * Maps project.id stably to 4 architectural patterns.
 */
export function ProjectCardCornerArt({ seed, className = '' }) {
  const variant = hashSeed(seed)

  return (
    <svg
      width="96"
      height="72"
      viewBox="0 0 96 72"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`art-svg cv-project-corner-art ${className}`.trim()}
      data-art="project-corner"
      data-pattern={variant}
      aria-hidden="true"
    >
      {variant === 0 ? (
        /* Node-graph flow topology */
        <g stroke="currentColor" strokeWidth="1.15" strokeLinecap="round" strokeLinejoin="round">
          <rect x="16" y="10" width="24" height="16" rx="3" />
          <rect x="60" y="18" width="28" height="20" rx="3" />
          <rect x="30" y="42" width="26" height="16" rx="3" />
          <path d="M40 18C50 18 50 28 60 28" />
          <path d="M43 42C48 34 52 31 60 31" />
          <circle cx="40" cy="18" r="2" fill="currentColor" />
          <circle cx="60" cy="28" r="2" fill="currentColor" />
          <circle cx="43" cy="42" r="2" fill="currentColor" />
        </g>
      ) : variant === 1 ? (
        /* Storyboard frame grid */
        <g stroke="currentColor" strokeWidth="1.15" strokeLinecap="round" strokeLinejoin="round">
          <rect x="18" y="8" width="28" height="18" rx="2.5" />
          <rect x="52" y="8" width="28" height="18" rx="2.5" />
          <rect x="34" y="34" width="28" height="18" rx="2.5" />
          <rect x="68" y="34" width="22" height="18" rx="2.5" strokeDasharray="3 3" />
          <line x1="24" y1="17" x2="36" y2="17" />
          <line x1="58" y1="17" x2="72" y2="17" />
        </g>
      ) : variant === 2 ? (
        /* Golden viewfinder reticle */
        <g stroke="currentColor" strokeWidth="1.15" strokeLinecap="round" strokeLinejoin="round">
          <rect x="20" y="10" width="64" height="44" rx="4" />
          <line x1="42" y1="10" x2="42" y2="54" strokeDasharray="2 3" />
          <line x1="20" y1="32" x2="84" y2="32" strokeDasharray="2 3" />
          <path d="M26 16H32M26 16V22" />
          <path d="M78 48H72M78 48V42" />
          <circle cx="52" cy="32" r="7" />
        </g>
      ) : (
        /* Layered film-frame cascade */
        <g stroke="currentColor" strokeWidth="1.15" strokeLinecap="round" strokeLinejoin="round">
          <rect x="44" y="8" width="40" height="26" rx="3" />
          <rect x="30" y="20" width="40" height="26" rx="3" />
          <rect x="16" y="32" width="40" height="26" rx="3" />
          <path d="M24 48C32 46 37 40 47 38" />
          <circle cx="47" cy="38" r="2" fill="currentColor" />
        </g>
      )}
    </svg>
  )
}

/**
 * T2-1: ProjectOverview centered empty state architectural SVG (140x96).
 */
export function ProjectEmptyArt({ variant = 'empty', className = '' }) {
  return (
    <svg
      width="140"
      height="96"
      viewBox="0 0 140 96"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`art-svg art-project-empty ${className}`.trim()}
      data-art={`project-${variant}`}
      aria-hidden="true"
    >
      {variant === 'search' ? (
        <>
          <rect x="22" y="18" width="66" height="52" rx="6" fill="#ffffff" fillOpacity="0.025" stroke="#f5f5f7" strokeOpacity="0.2" strokeWidth="1.2" />
          <rect x="32" y="28" width="20" height="14" rx="2.5" stroke="#f5f5f7" strokeOpacity="0.16" strokeWidth="1.1" />
          <rect x="58" y="28" width="20" height="14" rx="2.5" stroke="#f5f5f7" strokeOpacity="0.14" strokeWidth="1.1" />
          <line x1="32" y1="54" x2="58" y2="54" stroke="#f5f5f7" strokeOpacity="0.15" strokeWidth="1.2" strokeLinecap="round" />
          <circle cx="88" cy="54" r="17" fill="#050507" fillOpacity="0.9" stroke="#f5f5f7" strokeOpacity="0.34" strokeWidth="1.3" />
          <path d="M101 67L114 80" stroke="#f5f5f7" strokeOpacity="0.4" strokeWidth="1.8" strokeLinecap="round" />
        </>
      ) : (
        <>
          {/* Unfolded project board -> canvas nodes */}
          <rect x="18" y="16" width="104" height="64" rx="7" fill="#ffffff" fillOpacity="0.025" stroke="#f5f5f7" strokeOpacity="0.22" strokeWidth="1.2" />
          <line x1="18" y1="30" x2="122" y2="30" stroke="#f5f5f7" strokeOpacity="0.14" strokeWidth="1" />
          <circle cx="28" cy="23" r="2" fill="#f5f5f7" fillOpacity="0.26" />
          <circle cx="36" cy="23" r="2" fill="#f5f5f7" fillOpacity="0.18" />
          <rect x="28" y="40" width="32" height="24" rx="4" fill="#ffffff" fillOpacity="0.03" stroke="#f5f5f7" strokeOpacity="0.24" strokeWidth="1.15" />
          <rect x="80" y="40" width="32" height="24" rx="4" fill="#f59e0b" fillOpacity="0.06" stroke="#f59e0b" strokeOpacity="0.72" strokeWidth="1.2" />
          <path d="M60 52C68 52 72 52 80 52" stroke="#f59e0b" strokeOpacity="0.82" strokeWidth="1.3" strokeLinecap="round" />
          <circle cx="60" cy="52" r="2.2" fill="#050507" stroke="#f59e0b" strokeWidth="1.2" />
          <circle cx="80" cy="52" r="2.2" fill="#f59e0b" />
        </>
      )}
    </svg>
  )
}

/**
 * T2-4: PNG Info modal left drop zone — metadata x-ray frame (120x80).
 */
export function PngInfoDropArt({ className = '' }) {
  return (
    <svg
      width="120"
      height="80"
      viewBox="0 0 120 80"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`art-svg art-png-info-drop ${className}`.trim()}
      data-art="png-info-drop"
      aria-hidden="true"
    >
      {/* Left PNG image frame */}
      <rect x="14" y="14" width="48" height="52" rx="5" fill="#ffffff" fillOpacity="0.03" stroke="#f5f5f7" strokeOpacity="0.28" strokeWidth="1.2" />
      <path d="M21 53L32 41L41 50L47 44L55 53" stroke="#f5f5f7" strokeOpacity="0.22" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="28" cy="27" r="3" stroke="#f5f5f7" strokeOpacity="0.24" strokeWidth="1.1" />
      {/* Scan laser line in brand amber */}
      <line x1="12" y1="36" x2="64" y2="36" stroke="#f59e0b" strokeOpacity="0.78" strokeWidth="1.2" strokeLinecap="round" />
      {/* Extracted metadata parameter lines on right */}
      <path d="M62 36H74" stroke="#f59e0b" strokeOpacity="0.52" strokeWidth="1.15" strokeDasharray="2 2" strokeLinecap="round" />
      <rect x="74" y="20" width="32" height="40" rx="4" fill="#ffffff" fillOpacity="0.025" stroke="#f5f5f7" strokeOpacity="0.22" strokeWidth="1.15" />
      <line x1="81" y1="30" x2="99" y2="30" stroke="#f59e0b" strokeOpacity="0.72" strokeWidth="1.3" strokeLinecap="round" />
      <line x1="81" y1="38" x2="96" y2="38" stroke="#f5f5f7" strokeOpacity="0.28" strokeWidth="1.2" strokeLinecap="round" />
      <line x1="81" y1="45" x2="93" y2="45" stroke="#f5f5f7" strokeOpacity="0.22" strokeWidth="1.2" strokeLinecap="round" />
      <line x1="81" y1="52" x2="98" y2="52" stroke="#f5f5f7" strokeOpacity="0.16" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}

/**
 * T2-4: PromptCollection narrow drawer compact empty line art (72x48).
 */
export function PromptEmptyArt({ isSearch = false, className = '' }) {
  return (
    <svg
      width="72"
      height="48"
      viewBox="0 0 72 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`art-svg art-prompt-empty ${className}`.trim()}
      data-art={isSearch ? 'prompt-search-empty' : 'prompt-empty'}
      aria-hidden="true"
    >
      {isSearch ? (
        <>
          <rect x="12" y="10" width="34" height="28" rx="4" fill="#ffffff" fillOpacity="0.025" stroke="#f5f5f7" strokeOpacity="0.22" strokeWidth="1.2" />
          <line x1="18" y1="19" x2="34" y2="19" stroke="#f5f5f7" strokeOpacity="0.18" strokeWidth="1.15" strokeLinecap="round" />
          <line x1="18" y1="26" x2="29" y2="26" stroke="#f5f5f7" strokeOpacity="0.14" strokeWidth="1.15" strokeLinecap="round" />
          <circle cx="46" cy="27" r="9.5" fill="#050507" stroke="#f5f5f7" strokeOpacity="0.34" strokeWidth="1.2" />
          <path d="M53 34L60 41" stroke="#f5f5f7" strokeOpacity="0.38" strokeWidth="1.6" strokeLinecap="round" />
        </>
      ) : (
        <>
          <rect x="16" y="7" width="40" height="10" rx="3" fill="#ffffff" fillOpacity="0.02" stroke="#f5f5f7" strokeOpacity="0.16" strokeWidth="1.1" />
          <rect x="12" y="19" width="48" height="21" rx="4" fill="#ffffff" fillOpacity="0.035" stroke="#f5f5f7" strokeOpacity="0.26" strokeWidth="1.2" />
          <circle cx="20" cy="29.5" r="2" fill="#f59e0b" fillOpacity="0.85" />
          <line x1="27" y1="27" x2="52" y2="27" stroke="#f5f5f7" strokeOpacity="0.28" strokeWidth="1.2" strokeLinecap="round" />
          <line x1="27" y1="32.5" x2="43" y2="32.5" stroke="#f59e0b" strokeOpacity="0.48" strokeWidth="1.2" strokeLinecap="round" />
        </>
      )}
    </svg>
  )
}

/**
 * T2-6: Viewfinder reticle glyph for unified dark file drop-target masks.
 */
export function DropTargetReticle({ size = 28, className = '' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`art-svg ${className}`.trim()}
      data-art="drop-reticle"
      aria-hidden="true"
    >
      <path d="M4 9V5.5C4 4.672 4.672 4 5.5 4H9" stroke="#f59e0b" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M24 9V5.5C24 4.672 23.328 4 22.5 4H19" stroke="#f59e0b" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M4 19V22.5C4 23.328 4.672 24 5.5 24H9" stroke="#f59e0b" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M24 19V22.5C24 23.328 23.328 24 22.5 24H19" stroke="#f59e0b" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M14 9.5V18.5M9.5 14H18.5" stroke="#f5f5f7" strokeOpacity="0.82" strokeWidth="1.35" strokeLinecap="round" />
    </svg>
  )
}
