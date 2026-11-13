// Per-node interface selection (user decision 2026-11-13): no project default.
// New generation nodes are preselected with the interface last chosen for the
// same node type; the first time BytePlus (audio: Cupsy) is used.
export const GENERATION_KINDS = ['image', 'video', 'audio']
export const FIRST_ADAPTER = { image: 'ark', video: 'ark', audio: 'cupsy' }

export const toSelection = option => option ? { provider: option.provider, profile_id: option.profile_id || null } : null
export const selectionKey = choice => choice ? `${choice.provider}:${choice.profile_id || ''}` : 'none'
export const selectionOptionId = choice => choice ? (choice.profile_id ? `profile:${choice.profile_id}` : choice.provider) : ''

export function selectedProvider(capabilities, choice, kind) {
  if (!choice) return null
  return capabilities?.[kind]?.find(p => p.provider === choice.provider && (p.profile_id || null) === (choice.profile_id || null)) || null
}

export const nodeProvider = (capabilities, node) => selectedProvider(capabilities, node?.providerSelection, node?.type)

// Remembered choice when still available, else the first available option of the
// type's first-time adapter, else the first available option, else null.
export function defaultProviderSelection(capabilities, kind, preferences) {
  if (!GENERATION_KINDS.includes(kind)) return null
  const remembered = selectedProvider(capabilities, preferences?.[kind], kind)
  if (remembered) return toSelection(remembered)
  const options = capabilities?.[kind] || []
  // UI-ITER-R2-FIX L5: the interface-management "first preselection" profile applies only while the
  // user has never chosen an interface for this type; it never touches existing nodes.
  if (!preferences?.[kind]) { const first = options.find(p => p.is_default && p.profile_id); if (first) return toSelection(first) }
  return toSelection(options.find(p => p.provider === FIRST_ADAPTER[kind]) || options[0])
}

// Keep only well-formed per-type entries; anything else is ignored rather than trusted.
export function normalizeProviderPreferences(value) {
  const result = {}
  if (!value || typeof value !== 'object' || Array.isArray(value)) return result
  for (const kind of GENERATION_KINDS) {
    const item = value[kind]
    if (item && typeof item === 'object' && typeof item.provider === 'string' && (item.profile_id == null || typeof item.profile_id === 'string')) result[kind] = { provider: item.provider, profile_id: item.profile_id || null }
  }
  return result
}

// Copies of generation nodes always carry a concrete selection: an existing one is
// kept as is; a legacy node without one receives the current preselection.
export function withProviderSelection(node, selectionFor) {
  if (!GENERATION_KINDS.includes(node?.type) || node.providerSelection) return node
  const selection = selectionFor?.(node.type)
  return selection ? { ...node, providerSelection: selection } : node
}
