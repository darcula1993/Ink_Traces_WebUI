import React from 'react'

/**
 * Ink Traces brand logomark — "Micro-Ink Precision" geometry:
 * A precision viewfinder frame crossed by a single fluid ink trace trajectory.
 * Supports three optical weights: compact (14-18px), default (20-28px), hero (28-44px).
 */
const OPTICAL_VARIANTS = {
  compact: {
    frameStroke: 2.0,
    traceStroke: 2.45,
    glowStroke: 4.8,
    dotRadius: 2.1,
    showCornerTicks: false,
    showOriginNode: false,
  },
  default: {
    frameStroke: 1.65,
    traceStroke: 2.1,
    glowStroke: 4.4,
    dotRadius: 1.85,
    showCornerTicks: true,
    showOriginNode: true,
  },
  hero: {
    frameStroke: 1.45,
    traceStroke: 1.95,
    glowStroke: 4.4,
    dotRadius: 1.75,
    showCornerTicks: true,
    showOriginNode: true,
  },
}

export default function BrandMark({
  size = 20,
  variant = 'default',
  className = '',
  label = '',
}) {
  const opt = OPTICAL_VARIANTS[variant] || OPTICAL_VARIANTS.default
  const accessibility = label
    ? { role: 'img', 'aria-label': label }
    : { 'aria-hidden': 'true' }

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`brand-mark-svg ${className}`.trim()}
      data-brand-variant={variant}
      {...accessibility}
    >
      {/* Viewfinder precision frame: slightly broken along the ink trajectory */}
      <path
        d="M11.5 6.5H8.5C7.119 6.5 6 7.619 6 9V20.2"
        stroke="#e4e5e7"
        strokeOpacity="0.72"
        strokeWidth={opt.frameStroke}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M26 11.8V23C26 24.381 24.881 25.5 23.5 25.5H12.5"
        stroke="#e4e5e7"
        strokeOpacity="0.72"
        strokeWidth={opt.frameStroke}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Upper-right & lower-left architectural frame extensions */}
      <path
        d="M16.2 6.5H20.8"
        stroke="#e4e5e7"
        strokeOpacity="0.42"
        strokeWidth={opt.frameStroke}
        strokeLinecap="round"
      />
      {opt.showCornerTicks && (
        <>
          <path
            d="M9.2 10.2H11.4M9.2 10.2V12.4"
            stroke="#e4e5e7"
            strokeOpacity="0.34"
            strokeWidth="1.1"
            strokeLinecap="round"
          />
          <path
            d="M22.8 21.8H20.6M22.8 21.8V19.6"
            stroke="#e4e5e7"
            strokeOpacity="0.34"
            strokeWidth="1.1"
            strokeLinecap="round"
          />
        </>
      )}

      {/* Subtle ambient glow underlay along the ink trace */}
      <path
        d="M5.6 24.2C9.4 23.8 11.6 19.8 15.2 15.6C18.6 11.6 21.4 8.5 26.2 7.2"
        stroke="#45c088"
        strokeOpacity="0.2"
        strokeWidth={opt.glowStroke}
        strokeLinecap="round"
      />

      {/* Primary fluid ink trace path */}
      <path
        d="M5.6 24.2C9.4 23.8 11.6 19.8 15.2 15.6C18.6 11.6 21.4 8.5 26.2 7.2"
        stroke="#45c088"
        strokeWidth={opt.traceStroke}
        strokeLinecap="round"
      />

      {/* Precision anchor nodes */}
      {opt.showOriginNode && (
        <circle
          cx="5.6"
          cy="24.2"
          r={opt.dotRadius * 0.68}
          fill="#18191b"
          stroke="#45c088"
          strokeWidth="1.25"
        />
      )}
      <circle cx="26.2" cy="7.2" r={opt.dotRadius} fill="#45c088" />
    </svg>
  )
}
