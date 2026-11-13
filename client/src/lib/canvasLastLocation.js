// V140 #2: the last opened project/canvas is a per-browser convenience (server
// workspace state keys are whitelisted server-side). Storage may be unavailable.
const KEY = 'ink.canvas.lastLocation'
export function readLastLocation(storage = globalThis.localStorage) {
  try { const value = JSON.parse(storage?.getItem(KEY) || 'null'); return value && typeof value === 'object' ? value : null } catch { return null }
}
export function writeLastLocation(location, storage = globalThis.localStorage) {
  try { if (location?.workflowId) storage?.setItem(KEY, JSON.stringify({ projectId: location.projectId ?? null, workflowId: location.workflowId })) } catch { /* storage unavailable */ }
}
// The remembered item when it still exists, else the first one.
export const pickLastLocation = (items, id) => (id != null && items.find(item => String(item.id) === String(id))) || items[0]
