// V140 #2: the last opened project/canvas is a per-browser convenience (server
// workspace state keys are whitelisted server-side). Storage may be unavailable.
// WINDOW-PROJECT-20261114: each tab additionally remembers its own location in
// sessionStorage, so a reload is not pulled into another window's project.
// Order on load: this tab -> this browser -> the server's most recently updated item.
const KEY = 'ink.canvas.lastLocation'
const TAB_KEY = 'ink.canvas.tabLocation'
const sessionStore = () => { try { return globalThis.sessionStorage } catch { return undefined } }
const localStore = () => { try { return globalThis.localStorage } catch { return undefined } }
function readKey(storage, key) {
  try { const value = JSON.parse(storage?.getItem(key) || 'null'); return value && typeof value === 'object' ? value : null } catch { return null }
}
export function readLastLocation(storage = localStore()) { return readKey(storage, KEY) }
export function readTabLocation(storage = sessionStore()) { return readKey(storage, TAB_KEY) }
export function writeLastLocation(location, storage = localStore(), tabStorage = sessionStore()) {
  if (!location?.workflowId) return
  const value = JSON.stringify({ projectId: location.projectId ?? null, workflowId: location.workflowId })
  try { storage?.setItem(KEY, value) } catch { /* storage unavailable */ }
  try { tabStorage?.setItem(TAB_KEY, value) } catch { /* storage unavailable */ }
}
// The location this tab should reopen: its own first, else the browser's last one.
export function readRememberedLocation(storage = localStore(), tabStorage = sessionStore()) {
  return readTabLocation(tabStorage) || readLastLocation(storage)
}
// The remembered item when it still exists, else the first one.
export const pickLastLocation = (items, id) => (id != null && items.find(item => String(item.id) === String(id))) || items[0]

const same = (a, b) => String(a) === String(b)
// Resolve the project/canvas to open. A remembered project/canvas that is gone or not
// readable falls back to the server's most recent one (list order) and reports `missed`.
export async function resolveCanvasLocation({ projects, last, listWorkflows, getWorkflow }) {
  if (!projects?.length) return null
  const knownProject = last?.projectId != null
  let project = pickLastLocation(projects, last?.projectId)
  let missed = knownProject && !same(project.id, last.projectId)
  let workflows
  try { workflows = await listWorkflows(project.id) } catch (failure) {
    const other = projects.find(item => !same(item.id, project.id))
    if (!knownProject || !other) throw failure
    missed = true; project = other; workflows = await listWorkflows(project.id)
  }
  const wanted = last?.workflowId != null && (!knownProject || same(project.id, last.projectId)) ? last.workflowId : null
  if (!workflows.length) return { projectId: project.id, workflows, workflow: null, missed: missed || (knownProject && wanted != null) }
  const item = pickLastLocation(workflows, wanted)
  if (knownProject && wanted != null && !same(item.id, wanted)) missed = true
  let workflow
  try { workflow = await getWorkflow(item.id) } catch (failure) {
    const other = workflows.find(entry => !same(entry.id, item.id))
    if (wanted == null || !same(item.id, wanted) || !other) throw failure
    missed = true; workflow = await getWorkflow(other.id)
  }
  return { projectId: project.id, workflows, workflow, missed }
}
export const MISSED_LOCATION_MESSAGE = '上次打开的项目或画布已不存在或无法访问，已回到最近位置'

// WINDOW-PROJECT-20261114: the top-level tool (canvas/image/video/...) of this tab.
// A fresh tab has none and opens the canvas (user decision 11-14; the server appMode no longer
// decides it); once chosen it stays per tab across reloads.
const MODE_KEY = 'ink.app.tabMode'
export function readTabMode(storage = sessionStore()) {
  try { const value = storage?.getItem(MODE_KEY); return typeof value === 'string' && value ? value : null } catch { return null }
}
export function writeTabMode(mode, storage = sessionStore()) {
  try { if (typeof mode === 'string' && mode) storage?.setItem(MODE_KEY, mode) } catch { /* storage unavailable */ }
}
export function initialTabMode(storage = sessionStore()) {
  const mode = readTabMode(storage) || 'canvas'
  writeTabMode(mode, storage)
  return mode
}
