import React from 'react'

export default function SegmentedControl({ value, options, onChange, label }) {
  return (
    <div className="liquid-segmented inline-flex p-0.5" role="group" aria-label={label}>
      {options.map(({ value: optionValue, label: optionLabel, icon: Icon }) => {
        const active = value === optionValue
        return (
          <button
            key={optionValue}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(optionValue)}
            className={`segment-button inline-flex min-h-8 items-center gap-1.5 px-2.5 text-xs font-medium transition-colors ${
              active ? 'segment-button-active text-nexus-text-light' : 'text-nexus-text hover:text-nexus-text-light'
            }`}
          >
            {Icon && <Icon size={13} />}
            {optionLabel}
          </button>
        )
      })}
    </div>
  )
}
