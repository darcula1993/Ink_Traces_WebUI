// V24-W3-BUDGET-HISTORY-20261121 (#14): pure project budget soft-warning calculator.
// Estimates only (never actual charges). Unknown costs are ALWAYS listed separately
// and NEVER treated as zero; soft warnings NEVER hard-block task submission.

export const PROJECT_BUDGET_MIN = 0
export const PROJECT_BUDGET_MAX = 100000
export const PROJECT_BUDGET_EVENT = 'ink:project-budget-changed'

const EPSILON = 1e-9

export function formatBudgetUsd(value) {
  const n = Number(value)
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return '—'
  return `$${n.toFixed(3)}`
}

export function formatBudgetRange(min, max) {
  const a = formatBudgetUsd(min)
  const b = formatBudgetUsd(max)
  return a === b ? a : `${a}~${b}`
}

export function parseBudgetInput(raw) {
  if (raw === null || raw === undefined) return { valid: true, value: null, error: '' }
  const cleaned = String(raw).trim().replace(/^\$/, '').trim()
  if (!cleaned) return { valid: true, value: null, error: '' }
  if (!/^(?:\d+(?:\.\d+)?|\.\d+)$/.test(cleaned)) {
    return { valid: false, value: null, error: `请输入大于 0 且不超过 ${PROJECT_BUDGET_MAX} 的美元金额` }
  }
  const amount = Number(cleaned)
  if (!Number.isFinite(amount) || amount <= PROJECT_BUDGET_MIN || amount > PROJECT_BUDGET_MAX) {
    return { valid: false, value: null, error: `预算提醒线须大于 0 且不超过 $${PROJECT_BUDGET_MAX}` }
  }
  return { valid: true, value: amount, error: '' }
}

// Parse incoming estimate from single-node useCanvasEstimate, multi-select plan.total,
// or group-run preview.total. Unknown items are strictly counted and never converted to 0.
export function parseIncomingEstimate(incoming) {
  if (!incoming || typeof incoming !== 'object') {
    return { knownMin: 0, knownMax: 0, knownCount: 0, unknownCount: 0 }
  }
  // Multi-select plan.total: { knownCount, unknownCount, min, max }
  if ('knownCount' in incoming || 'unknownCount' in incoming) {
    const knownCount = Math.max(0, Number(incoming.knownCount) || 0)
    const unknownCount = Math.max(0, Number(incoming.unknownCount) || 0)
    const min = knownCount > 0 && Number.isFinite(Number(incoming.min)) ? Math.max(0, Number(incoming.min)) : 0
    const max = knownCount > 0 && Number.isFinite(Number(incoming.max)) ? Math.max(min, Number(incoming.max)) : min
    return { knownMin: min, knownMax: max, knownCount, unknownCount }
  }
  // Group-run preview.total: { known_count, unknown_count, usd }
  if ('known_count' in incoming || 'unknown_count' in incoming) {
    const knownCount = Math.max(0, Number(incoming.known_count) || 0)
    const unknownCount = Math.max(0, Number(incoming.unknown_count) || 0)
    const usd = knownCount > 0 && Number.isFinite(Number(incoming.usd)) ? Math.max(0, Number(incoming.usd)) : 0
    const min = knownCount > 0 && Number.isFinite(Number(incoming.usd_min)) ? Math.max(0, Number(incoming.usd_min)) : usd
    const max = knownCount > 0 && Number.isFinite(Number(incoming.usd_max)) ? Math.max(min, Number(incoming.usd_max)) : Math.max(min, usd)
    return { knownMin: min, knownMax: max, knownCount, unknownCount }
  }
  // Single-node estimate: { known: boolean, min?, max?, usd?, text? }
  if (incoming.known === false) {
    return { knownMin: 0, knownMax: 0, knownCount: 0, unknownCount: 1 }
  }
  if (incoming.known === true) {
    if (Number.isFinite(Number(incoming.min)) || Number.isFinite(Number(incoming.max))) {
      const min = Math.max(0, Number(incoming.min ?? incoming.max) || 0)
      const max = Math.max(min, Number(incoming.max ?? incoming.min) || min)
      return { knownMin: min, knownMax: max, knownCount: 1, unknownCount: 0 }
    }
    if (Number.isFinite(Number(incoming.usd))) {
      const usd = Math.max(0, Number(incoming.usd))
      return { knownMin: usd, knownMax: usd, knownCount: 1, unknownCount: 0 }
    }
    if (typeof incoming.text === 'string') {
      const matches = [...incoming.text.matchAll(/\$(\d+(?:\.\d+)?)/g)].map(m => Number(m[1])).filter(Number.isFinite)
      if (matches.length >= 2) {
        const min = Math.min(matches[0], matches[1])
        const max = Math.max(matches[0], matches[1])
        return { knownMin: min, knownMax: max, knownCount: 1, unknownCount: 0 }
      }
      if (matches.length === 1) {
        return { knownMin: matches[0], knownMax: matches[0], knownCount: 1, unknownCount: 0 }
      }
    }
    return { knownMin: 0, knownMax: 0, knownCount: 0, unknownCount: 1 }
  }
  return { knownMin: 0, knownMax: 0, knownCount: 0, unknownCount: 0 }
}

export function evaluateBudgetProgress({ billable, budgetUsd } = {}) {
  const knownCount = Math.max(0, Number(billable?.known_count) || 0)
  const unknownCount = Math.max(0, Number(billable?.unknown_count) || 0)
  const knownMin = knownCount > 0 && Number.isFinite(Number(billable?.known_usd_min)) ? Math.max(0, Number(billable.known_usd_min)) : 0
  const knownMax = knownCount > 0 && Number.isFinite(Number(billable?.known_usd_max)) ? Math.max(knownMin, Number(billable.known_usd_max)) : knownMin
  const threshold = budgetUsd != null && Number.isFinite(Number(budgetUsd)) && Number(budgetUsd) > 0 ? Number(budgetUsd) : null
  const unknownNote = unknownCount > 0 ? `另有 ${unknownCount} 条未知费用任务未计入（不当作零）` : ''
  const spentText = knownCount > 0 ? formatBudgetRange(knownMin, knownMax) : (unknownCount > 0 ? '暂无已知估算' : '$0.000')

  if (threshold === null) {
    return {
      configured: false,
      budgetUsd: null,
      knownMin,
      knownMax,
      knownCount,
      unknownCount,
      percent: 0,
      exceeded: false,
      nearLimit: false,
      status: 'unset',
      spentText,
      summaryText: '未设置项目预算提醒线（设置后超额仅作软提醒，不阻断提交）',
      unknownNote,
    }
  }

  const ratio = knownCount > 0 ? knownMax / threshold : 0
  const rawPercent = Math.round(ratio * 1000) / 10
  const percent = Math.min(100, Math.max(0, rawPercent))
  const exceeded = knownCount > 0 && knownMax > threshold + EPSILON
  const nearLimit = !exceeded && knownCount > 0 && ratio >= 0.8 - EPSILON
  const status = exceeded ? 'exceeded' : nearLimit ? 'near' : 'ok'
  const pctLabel = knownCount > 0 ? `${Math.round(ratio * 100)}%` : '0%'
  const summaryText = exceeded
    ? `当前已完成估算 ${spentText} / 预算提醒线 ${formatBudgetUsd(threshold)}（已达 ${pctLabel}，仅供参考）`
    : `当前已完成估算 ${spentText} / 预算提醒线 ${formatBudgetUsd(threshold)}（${pctLabel}）`

  return {
    configured: true,
    budgetUsd: threshold,
    knownMin,
    knownMax,
    knownCount,
    unknownCount,
    percent,
    exceeded,
    nearLimit,
    status,
    spentText,
    summaryText,
    unknownNote,
  }
}

export function evaluateBudgetWarning({ spent, incoming, budgetUsd } = {}) {
  const threshold = budgetUsd != null && Number.isFinite(Number(budgetUsd)) && Number(budgetUsd) > 0 ? Number(budgetUsd) : null
  const spentKnownCount = Math.max(0, Number(spent?.known_count) || 0)
  const spentUnknown = Math.max(0, Number(spent?.unknown_count) || 0)
  const spentMin = spentKnownCount > 0 && Number.isFinite(Number(spent?.known_usd_min)) ? Math.max(0, Number(spent.known_usd_min)) : 0
  const spentMax = spentKnownCount > 0 && Number.isFinite(Number(spent?.known_usd_max)) ? Math.max(spentMin, Number(spent.known_usd_max)) : spentMin

  const inc = parseIncomingEstimate(incoming)
  const projectedMin = spentMin + inc.knownMin
  const projectedMax = spentMax + inc.knownMax
  const totalKnownCount = spentKnownCount + inc.knownCount
  const totalUnknown = spentUnknown + inc.unknownCount
  const projectedText = totalKnownCount > 0 ? formatBudgetRange(projectedMin, projectedMax) : '—'
  const exceeds = threshold !== null && totalKnownCount > 0 && projectedMax > threshold + EPSILON

  const unknownNote = totalUnknown > 0 ? `另含 ${totalUnknown} 项未知费用未计入（不当作零）` : ''
  const message = exceeds
    ? `预计累计 ${projectedText} 将超出本项目预算提醒线 ${formatBudgetUsd(threshold)}（仅供参考，不阻断提交）${unknownNote ? `；${unknownNote}` : ''}`
    : ''

  return {
    exceeds,
    blocked: false, // Soft reminder only — NEVER blocks submission.
    budgetUsd: threshold,
    spentMin,
    spentMax,
    spentUnknown,
    incomingMin: inc.knownMin,
    incomingMax: inc.knownMax,
    incomingKnownCount: inc.knownCount,
    incomingUnknown: inc.unknownCount,
    projectedMin,
    projectedMax,
    projectedText,
    totalUnknown,
    unknownNote,
    message,
  }
}
