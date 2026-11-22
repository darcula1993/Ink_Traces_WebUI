import { useEffect } from 'react'
import './launchSplash.css'

/**
 * LaunchSplash — "墨痕启幕" Obsidian & Amber studio launch curtain.
 *
 * Phases:
 * - 'boot': full ceremonial ink-trace choreography
 * - 'quick': repeat same-tab refresh (clean subtle breathing mark, no extra drag)
 * - 'exiting': smooth curtain dissolve with pointer-events disabled immediately
 */
export default function LaunchSplash({
  phase = 'boot',
  pending = false,
  exitDuration = 300,
  onSkip,
}) {
  const canSkip = typeof onSkip === 'function' && phase !== 'exiting'

  useEffect(() => {
    if (!canSkip) return undefined
    const handleKeyDown = (event) => {
      if (event.repeat) return
      if (
        event.key === 'Escape' ||
        event.key === 'Enter' ||
        event.key === ' ' ||
        event.code === 'Space'
      ) {
        event.preventDefault()
        event.stopPropagation()
        onSkip()
      }
    }
    window.addEventListener('keydown', handleKeyDown, true)
    return () => window.removeEventListener('keydown', handleKeyDown, true)
  }, [canSkip, onSkip])

  const handleClick = () => {
    if (canSkip) onSkip()
  }

  return (
    <div
      className="launch-splash"
      role="status"
      aria-live="polite"
      aria-label="正在启动 Ink Traces 工作台"
      data-launch-phase={phase}
      data-auth-pending={pending ? 'true' : undefined}
      style={{ '--launch-exit-ms': `${exitDuration}ms` }}
      onClick={handleClick}
    >
      <div className="launch-splash-grid" aria-hidden="true" />
      <div className="launch-splash-spotlight" aria-hidden="true" />

      <div className="launch-splash-frame" aria-hidden="true">
        <span className="launch-splash-corner launch-splash-corner-tl" />
        <span className="launch-splash-corner launch-splash-corner-tr" />
        <span className="launch-splash-corner launch-splash-corner-bl" />
        <span className="launch-splash-corner launch-splash-corner-br" />
      </div>

      <div className="launch-splash-core">
        <div className="launch-splash-medallion-shell">
          <div className="launch-splash-medallion">
            <svg
              className="launch-splash-svg"
              viewBox="0 0 32 32"
              width="44"
              height="44"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <g className="launch-splash-brackets">
                <path
                  d="M11.5 6.5H8.5C7.119 6.5 6 7.619 6 9V20.2"
                  stroke="#f5f5f7"
                  strokeOpacity="0.84"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M26 11.8V23C26 24.381 24.881 25.5 23.5 25.5H12.5"
                  stroke="#f5f5f7"
                  strokeOpacity="0.84"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M16.2 6.5H20.8"
                  stroke="#f5f5f7"
                  strokeOpacity="0.46"
                  strokeWidth="1.45"
                  strokeLinecap="round"
                />
                <path
                  d="M9.2 10.2H11.4M9.2 10.2V12.4"
                  stroke="#f5f5f7"
                  strokeOpacity="0.34"
                  strokeWidth="1.1"
                  strokeLinecap="round"
                />
                <path
                  d="M22.8 21.8H20.6M22.8 21.8V19.6"
                  stroke="#f5f5f7"
                  strokeOpacity="0.34"
                  strokeWidth="1.1"
                  strokeLinecap="round"
                />
              </g>

              <path
                className="launch-splash-trace-glow"
                d="M5.6 24.2C9.4 23.8 11.6 19.8 15.2 15.6C18.6 11.6 21.4 8.5 26.2 7.2"
                pathLength="100"
                stroke="#fbbf24"
                strokeOpacity="0.26"
                strokeWidth="4.6"
                strokeLinecap="round"
              />
              <path
                className="launch-splash-trace-main"
                d="M5.6 24.2C9.4 23.8 11.6 19.8 15.2 15.6C18.6 11.6 21.4 8.5 26.2 7.2"
                pathLength="100"
                stroke="#f59e0b"
                strokeWidth="2.05"
                strokeLinecap="round"
              />

              <circle
                className="launch-splash-ripple"
                cx="26.2"
                cy="7.2"
                r="2.1"
                stroke="#fbbf24"
                strokeWidth="1"
              />
              <circle
                className="launch-splash-dot"
                cx="5.6"
                cy="24.2"
                r="1.25"
                fill="#0a0a0e"
                stroke="#f59e0b"
                strokeWidth="1.3"
              />
              <circle
                className="launch-splash-dot"
                cx="26.2"
                cy="7.2"
                r="1.85"
                fill="#f59e0b"
              />
            </svg>
          </div>
        </div>

        <p className="launch-splash-title">INK TRACES</p>
        <p className="launch-splash-subtitle">视觉创作台</p>

        <div className="launch-splash-track" aria-hidden="true">
          <div className="launch-splash-beam" />
        </div>
      </div>
    </div>
  )
}
