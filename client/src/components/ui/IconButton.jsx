import React from 'react'

export default function IconButton({ label, children, className = '', tooltipClassName = '', ...props }) {
  return (
    <span className="group/tooltip relative inline-flex shrink-0">
      <button
        type="button"
        aria-label={label}
        className={`btn btn-icon ${className}`}
        {...props}
      >
        {children}
      </button>
      <span
        role="tooltip"
        className={`pointer-events-none absolute left-1/2 top-full z-[120] mt-2 hidden -translate-x-1/2 whitespace-nowrap rounded border border-[var(--border)] bg-[var(--surface-raised)] px-2 py-1 text-xs text-nexus-text-light shadow-xl group-hover/tooltip:block group-focus-within/tooltip:block ${tooltipClassName}`}
      >
        {label}
      </span>
    </span>
  )
}
