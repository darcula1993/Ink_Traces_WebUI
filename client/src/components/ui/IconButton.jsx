import React from 'react'

export default function IconButton({ label, children, className = '', ...props }) {
  return (
    <span className="group/tooltip relative inline-flex shrink-0">
      <button
        type="button"
        aria-label={label}
        className={`icon-button ${className}`}
        {...props}
      >
        {children}
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full z-[120] mt-2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-[#050607] px-2 py-1 text-xs text-nexus-text-light shadow-xl group-hover/tooltip:block group-focus-within/tooltip:block"
      >
        {label}
      </span>
    </span>
  )
}
