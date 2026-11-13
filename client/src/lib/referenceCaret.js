import {referenceTokenRanges} from './referenceMedia.js'

// V140 #17: references behave as one unit for the caret and the selection.
// Every helper only computes a new selection; the text is never changed, so
// the textarea's native undo stack is untouched.
const inside = (range, position) => position > range.start && position < range.end

// Nearest boundary for a position strictly inside a reference (ties go to the end).
export function snapPosition(text, position, ranges = referenceTokenRanges(text)) {
  const range = ranges.find(item => inside(item, position))
  if (!range) return position
  return position - range.start < range.end - position ? range.start : range.end
}

// After clicks / Ctrl+arrows / Up/Down: a caret inside a reference snaps to the
// nearest boundary; a selection endpoint inside a reference grows outward to cover it.
export function snapSelection(text, start, end) {
  const ranges = referenceTokenRanges(text)
  if (start === end) { const position = snapPosition(text, start, ranges); return { start: position, end: position } }
  const first = ranges.find(item => inside(item, start)), last = ranges.find(item => inside(item, end))
  return { start: first ? first.start : start, end: last ? last.end : end }
}

// ←/→ (optionally with Shift) next to a reference moves over the whole reference.
// Returns {start,end,direction} to apply with preventDefault, or null for the default.
export function arrowSelection(text, start, end, direction, key, shift) {
  if (key !== 'ArrowLeft' && key !== 'ArrowRight') return null
  const ranges = referenceTokenRanges(text), left = key === 'ArrowLeft'
  if (!shift) {
    if (start !== end) return null // default: collapse the selection
    const range = ranges.find(item => left ? item.end === start : item.start === start)
    if (!range) return null
    const position = left ? range.start : range.end
    return { start: position, end: position, direction: 'none' }
  }
  const backward = start !== end && direction === 'backward'
  const anchor = start === end ? start : backward ? end : start, focus = start === end ? start : backward ? start : end
  const range = ranges.find(item => left ? item.end === focus : item.start === focus)
  if (!range) return null
  const next = left ? range.start : range.end
  return next < anchor ? { start: next, end: anchor, direction: 'backward' } : { start: anchor, end: next, direction: next === anchor ? 'none' : 'forward' }
}

// Double click on a reference selects the whole reference.
export function referenceAt(text, start, end) {
  return referenceTokenRanges(text).find(item => start < item.end && end > item.start && !(start === end && (start === item.start || start === item.end))) || null
}
