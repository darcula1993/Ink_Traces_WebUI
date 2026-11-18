// FE-LIST-PERF-20261118: pure helpers for windowed (virtualized) list/grid rendering (node-testable, no React).

// Rows of a uniform grid to render for a viewport. offset = viewport top relative to the grid top (px),
// stride = row height + row gap. pin (item index, optional) is kept rendered, e.g. the focused card, as long
// as it is within maxPinRows of the viewport, so keyboard focus is not dropped by scrolling.
export function gridWindow({count, columns, stride, offset, height, overscanRows = 3, pin = -1, maxPinRows = 40}) {
  const cols = Math.max(1, Math.floor(columns) || 1)
  const rows = Math.ceil(count / cols)
  if (!count) return {start: 0, end: 0, padTop: 0, padBottom: 0, rows: 0}
  if (!(stride > 0)) return {start: 0, end: count, padTop: 0, padBottom: 0, rows}
  let first = Math.floor(Math.max(0, offset) / stride) - overscanRows
  let last = Math.ceil(Math.max(0, offset + height) / stride) + overscanRows
  first = Math.max(0, Math.min(first, rows - 1))
  last = Math.max(first + 1, Math.min(last, rows))
  if (pin >= 0 && pin < count) {
    const pinRow = Math.floor(pin / cols)
    if (pinRow < first && first - pinRow <= maxPinRows) first = pinRow
    else if (pinRow >= last && pinRow - last < maxPinRows) last = pinRow + 1
  }
  return {start: first * cols, end: Math.min(count, last * cols), padTop: first * stride, padBottom: (rows - last) * stride, rows}
}

// Number of grid columns from a resolved `grid-template-columns` value ("246px 246px 246px").
export function columnCount(template) {
  const value = String(template || '').trim()
  if (!value || value === 'none') return 1
  return Math.max(1, value.split(/\s+(?![^(]*\))/).length)
}

// Progressive list growth: how many rows to render so that `index` (e.g. the selected/revealed row) is included.
export function progressiveLimit(limit, index, step) {
  if (index < 0 || index < limit) return limit
  return Math.ceil((index + 1) / step) * step
}
