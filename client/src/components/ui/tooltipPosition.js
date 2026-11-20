const VIEWPORT_MARGIN = 8
const TOOLTIP_GAP = 8

export function computeTooltipPosition(anchorRect, tipSize, viewport, { preferredPlacement = 'bottom', align = 'center' } = {}) {
  const maxLeft = Math.max(VIEWPORT_MARGIN, viewport.width - tipSize.width - VIEWPORT_MARGIN)
  const rawLeft = align === 'start'
    ? anchorRect.left
    : align === 'end'
      ? anchorRect.right - tipSize.width
      : anchorRect.left + anchorRect.width / 2 - tipSize.width / 2
  const left = Math.max(VIEWPORT_MARGIN, Math.min(rawLeft, maxLeft))

  const belowTop = anchorRect.bottom + TOOLTIP_GAP
  const aboveTop = anchorRect.top - tipSize.height - TOOLTIP_GAP
  const fitsBelow = belowTop + tipSize.height <= viewport.height - VIEWPORT_MARGIN
  const fitsAbove = aboveTop >= VIEWPORT_MARGIN

  let placement = preferredPlacement
  if (preferredPlacement === 'bottom' && !fitsBelow && (fitsAbove || anchorRect.top > viewport.height - anchorRect.bottom)) {
    placement = 'top'
  } else if (preferredPlacement === 'top' && !fitsAbove && (fitsBelow || viewport.height - anchorRect.bottom > anchorRect.top)) {
    placement = 'bottom'
  }

  const rawTop = placement === 'top' ? aboveTop : belowTop
  const maxTop = Math.max(VIEWPORT_MARGIN, viewport.height - tipSize.height - VIEWPORT_MARGIN)
  const top = Math.max(VIEWPORT_MARGIN, Math.min(rawTop, maxTop))

  return { top, left, placement }
}
