// V140 #10: library dates follow the viewer's local calendar day (same as the task center).
// Server timestamps carry an offset; a value without one is treated as UTC.
export function localDate(value) {
  if (!value) return ''
  const text = String(value)
  if (!/T/.test(text)) return text.slice(0, 10)
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(text) ? text : `${text}Z`)
  if (Number.isNaN(date.getTime())) return text.slice(0, 10)
  const pad = n => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
