import {
  defaultProviderSelection,
  selectedProvider,
  selectionOptionId,
  toSelection,
} from './canvasProviderSelection.js'

export const STALE_TOOL_PROVIDER_LABEL = '所选接口已停用或已删除'
export const STALE_TOOL_PROVIDER_REASON = '所选接口已停用或已删除，请重新选择'
export const EMPTY_TOOL_PROVIDER_REASON = '暂无可用接口，请先在「接口管理」中启用并配置 API Key'

export function normalizeToolSelection(selection) {
  if (!selection || typeof selection !== 'object' || typeof selection.provider !== 'string' || !selection.provider) {
    return null
  }
  return {
    provider: selection.provider,
    profile_id: typeof selection.profile_id === 'string' && selection.profile_id ? selection.profile_id : null,
  }
}

export function selectionFromOption(option) {
  return toSelection(option)
}

export function optionById(capabilities, kind, optionId) {
  if (!optionId) return null
  return (capabilities?.[kind] || []).find(item => item.id === optionId) || null
}

/**
 * Resolve the active provider option for an independent tool page (image / video / audio).
 *
 * Rules:
 * - If the user has an explicit persisted `selection` (e.g. a named profile or an explicit adapter choice)
 *   and it is no longer enabled/available, NEVER silently fall back to another paid account: mark it
 *   unavailable so the UI shows a clear Chinese alert and disables generation.
 * - If no explicit `selection` is stored yet:
 *   - When `legacyProvider` is explicitly saved on a legacy form (e.g. video tab `provider: 'cupsy'`),
 *     try matching that adapter (`selectedProvider` matches legacy or `config:<kind>:<adapter>`, or
 *     a single/default profile of the SAME adapter); never silently switch across adapters.
 *   - Otherwise, preselect via `defaultProviderSelection` (prefer `sessionProvider` for image if available).
 */
export function resolveToolProvider(capabilities, kind, {
  selection = null,
  legacyProvider = null,
  sessionProvider = null,
  ready = true,
} = {}) {
  const options = capabilities?.[kind] || []
  const explicit = normalizeToolSelection(selection)

  if (!ready) {
    return {
      options,
      option: null,
      status: 'loading',
      selectValue: explicit ? selectionOptionId(explicit) : '',
      staleOptionLabel: '',
      unavailableReason: '',
    }
  }

  if (explicit) {
    const matched = selectedProvider(capabilities, explicit, kind)
    if (matched) {
      return {
        options,
        option: matched,
        status: 'ready',
        selectValue: matched.id,
        staleOptionLabel: '',
        unavailableReason: '',
      }
    }
    return {
      options,
      option: null,
      status: 'unavailable',
      selectValue: selectionOptionId(explicit),
      staleOptionLabel: STALE_TOOL_PROVIDER_LABEL,
      unavailableReason: STALE_TOOL_PROVIDER_REASON,
    }
  }

  if (legacyProvider && typeof legacyProvider === 'string') {
    const direct = selectedProvider(capabilities, { provider: legacyProvider, profile_id: null }, kind)
    if (direct) {
      return {
        options,
        option: direct,
        status: 'ready',
        selectValue: direct.id,
        staleOptionLabel: '',
        unavailableReason: '',
      }
    }
    const sameAdapter = options.filter(item => item.provider === legacyProvider)
    if (sameAdapter.length === 1) {
      return {
        options,
        option: sameAdapter[0],
        status: 'ready',
        selectValue: sameAdapter[0].id,
        staleOptionLabel: '',
        unavailableReason: '',
      }
    }
    const sameAdapterDefault = sameAdapter.find(item => item.is_default)
    if (sameAdapterDefault) {
      return {
        options,
        option: sameAdapterDefault,
        status: 'ready',
        selectValue: sameAdapterDefault.id,
        staleOptionLabel: '',
        unavailableReason: '',
      }
    }
    return {
      options,
      option: null,
      status: 'unavailable',
      selectValue: legacyProvider,
      staleOptionLabel: STALE_TOOL_PROVIDER_LABEL,
      unavailableReason: STALE_TOOL_PROVIDER_REASON,
    }
  }

  if (sessionProvider && typeof sessionProvider === 'string') {
    const sessionMatch = selectedProvider(capabilities, { provider: sessionProvider, profile_id: null }, kind)
    if (sessionMatch) {
      return {
        options,
        option: sessionMatch,
        status: 'ready',
        selectValue: sessionMatch.id,
        staleOptionLabel: '',
        unavailableReason: '',
      }
    }
  }

  const defaultChoice = defaultProviderSelection(capabilities, kind)
  const matched = defaultChoice ? selectedProvider(capabilities, defaultChoice, kind) : null
  if (matched) {
    return {
      options,
      option: matched,
      status: 'ready',
      selectValue: matched.id,
      staleOptionLabel: '',
      unavailableReason: '',
    }
  }

  return {
    options,
    option: null,
    status: 'empty',
    selectValue: '',
    staleOptionLabel: '',
    unavailableReason: EMPTY_TOOL_PROVIDER_REASON,
  }
}

export function isVideoFastAvailable(option, rawVideo, rawProfiles) {
  if (!option || option.provider !== 'ark') return false
  if (option.profile_id) {
    const profile = (rawProfiles || []).find(item => item.id === option.profile_id)
    return Boolean(profile?.settings?.fast_model)
  }
  return rawVideo?.fast_available !== false
}

export function toolSubmitProfileFields(option) {
  if (!option) return {}
  return {
    provider: option.provider,
    ...(option.profile_id ? { profile_id: option.profile_id } : {}),
  }
}
