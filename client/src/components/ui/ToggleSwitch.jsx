import React from 'react'

export default function ToggleSwitch({ checked, onChange, label, disabled = false }) {
  const isChecked = Boolean(checked)

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isChecked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => onChange(!isChecked)}
      className={`liquid-toggle relative h-5 w-9 shrink-0 rounded-full border transition-colors ${
        isChecked
          ? 'border-nexus-green/60 bg-nexus-green/25'
          : 'border-nexus-border-hover bg-nexus-surface'
      } disabled:cursor-not-allowed disabled:opacity-40`}
    >
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute left-[3px] top-[3px] size-3 rounded-full transition-transform ${
          isChecked ? 'translate-x-4 bg-nexus-green' : 'translate-x-0 bg-nexus-muted'
        }`}
      />
    </button>
  )
}
