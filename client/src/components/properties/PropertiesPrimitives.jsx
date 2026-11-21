import React, { useEffect, useId, useRef, useState } from 'react'
import { ChevronRight, ChevronUp } from 'lucide-react'
import './propertiesPrimitives.css'

const readStored = key => {
  if (!key) return null
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

const writeStored = (key, value) => {
  if (!key) return
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    /* storage unavailable: keep the in-memory value */
  }
}

// Aspect-ratio box glyph (decorative): 16:9 draws a wide box, 9:16 a tall one, auto/custom/adaptive a dashed square.
export function RatioGlyph({ value, className = '' }) {
  const m = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(String(value || ''))
  let w = 12
  let h = 12
  if (m) {
    const a = Number(m[1])
    const b = Number(m[2])
    if (a >= b) {
      w = 14
      h = Math.max(5, Math.round((14 * b) / a))
    } else {
      h = 14
      w = Math.max(5, Math.round((14 * a) / b))
    }
  }
  return <span className={`pf-ratio cv-pf-ratio ${m ? '' : 'is-free'} ${className}`.trim()} style={{ width: w, height: h }} />
}

export const imageRatioPrefix = (name, value) =>
  name === 'ratio' ? <span className="pf-prefix cv-pf-prefix" aria-hidden="true"><RatioGlyph value={value} /></span> : null

export function PanelHeader({ icon: Icon, title, summary = null, actions = null, className = '' }) {
  return (
    <header className={`pf-header ${className}`.trim()}>
      {Icon && (
        <span className="pf-kind-box">
          <Icon size={14} aria-hidden="true" className="pf-kind-icon" />
        </span>
      )}
      <h2 className="pf-header-title">{title}</h2>
      {summary && (
        <span className="pf-header-summary" title={typeof summary === 'string' ? summary : undefined}>
          {summary}
        </span>
      )}
      {actions}
    </header>
  )
}

export function PanelSection({ id, title, summary = null, actions = null, className = '', sectionRef = null, children, ...rest }) {
  return (
    <section ref={sectionRef} className={`pf-section ${className}`.trim()} aria-labelledby={id} {...rest}>
      <div className="pf-section-head inspector-title">
        <h3 id={id} className="pf-section-title">
          <span>{title}</span>
          {summary && <small className="pf-section-summary" title={typeof summary === 'string' ? summary : undefined}>{summary}</small>}
        </h3>
        {actions && <div className="pf-section-actions">{actions}</div>}
      </div>
      {children}
    </section>
  )
}

export function PanelField({ label, hint = null, note = null, prefix = null, className = '', children }) {
  return (
    <label className={`pf-field ${prefix ? 'has-prefix' : ''} ${note ? 'has-note' : ''} ${className}`.trim()}>
      <span className="pf-label">
        {label}
        {hint && <small title={typeof hint === 'string' ? hint : undefined}>{hint}</small>}
      </span>
      {children}
      {prefix && <span className="pf-prefix" aria-hidden="true">{prefix}</span>}
      {note && <small className="pf-field-note">{note}</small>}
    </label>
  )
}

export function PanelToggle({ label, ariaLabel, hint = null, checked, disabled = false, onChange, title, className = '' }) {
  return (
    <label className={`pf-toggle ${disabled ? 'is-disabled' : ''} ${className}`.trim()} title={title || undefined}>
      <span className="pf-toggle-label">
        <span>{label}</span>
        {hint && <small>{hint}</small>}
      </span>
      <input
        type="checkbox"
        role="switch"
        className="pf-switch"
        aria-label={ariaLabel || label}
        aria-checked={Boolean(checked)}
        checked={Boolean(checked)}
        disabled={disabled}
        onChange={event => onChange?.(event.target.checked)}
      />
    </label>
  )
}

export function CollapsibleAdvanced({
  storageKey,
  summary = '',
  autoOpen = false,
  autoOpenSignal = 0,
  label = '高级',
  className = '',
  children,
}) {
  const [open, setOpen] = useState(() => Boolean(autoOpen) || readStored(storageKey) === '1')
  const seenAutoOpen = useRef(Boolean(autoOpen))
  const seenSignal = useRef(autoOpenSignal)
  const prevKey = useRef(storageKey)
  const contentId = useId()

  useEffect(() => {
    if (prevKey.current !== storageKey) {
      prevKey.current = storageKey
      setOpen(Boolean(autoOpen) || readStored(storageKey) === '1')
      seenAutoOpen.current = Boolean(autoOpen)
      seenSignal.current = autoOpenSignal
    }
  }, [storageKey, autoOpen, autoOpenSignal])

  useEffect(() => {
    if (autoOpen && !seenAutoOpen.current) setOpen(true)
    seenAutoOpen.current = Boolean(autoOpen)
  }, [autoOpen])

  useEffect(() => {
    if (autoOpenSignal && autoOpenSignal !== seenSignal.current) setOpen(true)
    seenSignal.current = autoOpenSignal
  }, [autoOpenSignal])

  const toggle = () => {
    const next = !open
    setOpen(next)
    writeStored(storageKey, next ? '1' : '0')
  }

  return (
    <div className={`pf-advanced cv-pf-advanced ${open ? 'is-open' : ''} ${className}`.trim()}>
      <button
        type="button"
        className="pf-advanced-toggle cv-pf-advanced-toggle"
        aria-expanded={open}
        aria-controls={contentId}
        title={open ? '收起高级参数' : '展开高级参数'}
        onClick={toggle}
      >
        <ChevronRight size={14} aria-hidden="true" className="pf-chevron cv-pf-chevron" />
        <span>{label}</span>
        {!open && summary && <small>{summary}</small>}
      </button>
      <div id={contentId} className="pf-advanced-body cv-pf-advanced-body" hidden={!open}>
        {children}
      </div>
    </div>
  )
}

export function CostEstimateFooter({
  amount,
  tone = 'default',
  testId,
  summaryTitle = '',
  details = null,
  label = '费用估算',
}) {
  const [expanded, setExpanded] = useState(false)
  const detailsId = useId()

  useEffect(() => {
    setExpanded(false)
  }, [testId])

  return (
    <footer className="pf-panel-footer">
      {expanded && details && (
        <div id={detailsId} className="pf-cost-details" role="region" aria-label="费用估算明细">
          {details}
        </div>
      )}
      {details ? (
        <button
          type="button"
          className="pf-cost-trigger"
          aria-expanded={expanded}
          aria-controls={detailsId}
          title={summaryTitle || (expanded ? '收起费用明细' : '查看费用明细')}
          onClick={() => setExpanded(value => !value)}
        >
          <span className="pf-cost-label">{label}</span>
          <span className="pf-cost-right">
            <span
              data-testid={testId}
              className={`pf-cost-value ${tone === 'muted' ? 'is-muted' : tone === 'warn' ? 'is-warn' : ''}`.trim()}
            >
              {amount}
            </span>
            <ChevronUp size={14} aria-hidden="true" className={`pf-cost-chevron ${expanded ? 'is-open' : ''}`} />
          </span>
        </button>
      ) : (
        <div className="pf-cost-trigger" title={summaryTitle || undefined}>
          <span className="pf-cost-label">{label}</span>
          <span className="pf-cost-right">
            <span
              data-testid={testId}
              className={`pf-cost-value ${tone === 'muted' ? 'is-muted' : tone === 'warn' ? 'is-warn' : ''}`.trim()}
            >
              {amount}
            </span>
          </span>
        </div>
      )}
    </footer>
  )
}
