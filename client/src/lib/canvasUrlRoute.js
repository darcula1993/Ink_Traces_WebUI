// V24-W1-URL-POLISH-20261121: URL query-parameter persistence for the active canvas project/workflow
// (?project=<projectId>&canvas=<workflowId>). Pure and Node-testable; uses replaceState to keep browser
// history clean and supports popstate synchronization across multi-tab sessions.
import { resolveCanvasLocation } from './canvasLastLocation.js'

export const CANVAS_PROJECT_PARAM = 'project'
export const CANVAS_WORKFLOW_PARAM = 'canvas'
export const URL_MISSED_LOCATION_MESSAGE = '链接中的项目或画布已不存在或无法访问，已回到最近位置'

const cleanParam = value => {
  if (value == null) return null
  const trimmed = String(value).trim()
  return trimmed || null
}

const sameId = (a, b) => String(a) === String(b)

export function readCanvasUrlRoute(search = globalThis.window?.location?.search || '') {
  const raw = typeof search === 'string' ? search : ''
  if (!raw) return null
  const params = new URLSearchParams(raw.startsWith('?') ? raw.slice(1) : raw)
  const projectId = cleanParam(params.get(CANVAS_PROJECT_PARAM))
  const workflowId = cleanParam(params.get(CANVAS_WORKFLOW_PARAM))
  if (!projectId && !workflowId) return null
  return { projectId, workflowId }
}

export function buildCanvasUrl({ projectId = null, workflowId = null } = {}, currentHref = globalThis.window?.location?.href || '/') {
  const base = 'http://localhost'
  const url = new URL(currentHref || '/', base)
  const nextProject = cleanParam(projectId)
  const nextWorkflow = cleanParam(workflowId)
  if (nextProject) url.searchParams.set(CANVAS_PROJECT_PARAM, nextProject)
  else url.searchParams.delete(CANVAS_PROJECT_PARAM)
  if (nextWorkflow) url.searchParams.set(CANVAS_WORKFLOW_PARAM, nextWorkflow)
  else url.searchParams.delete(CANVAS_WORKFLOW_PARAM)
  return `${url.pathname}${url.search}${url.hash}`
}

export function syncCanvasUrlRoute(route, win = globalThis.window) {
  if (!win?.location || typeof win?.history?.replaceState !== 'function') return false
  try {
    const current = `${win.location.pathname || '/'}${win.location.search || ''}${win.location.hash || ''}`
    const next = buildCanvasUrl(route, win.location.href || current)
    if (next === current) return false
    win.history.replaceState(win.history.state, '', next)
    return true
  } catch {
    return false
  }
}

export function subscribeCanvasUrlRoute(onRoute, win = globalThis.window) {
  if (typeof onRoute !== 'function' || typeof win?.addEventListener !== 'function') return () => {}
  const handle = () => onRoute(readCanvasUrlRoute(win.location?.search || ''))
  win.addEventListener('popstate', handle)
  return () => win.removeEventListener('popstate', handle)
}

// Priority: URL query parameters > remembered tab/browser location > server default (first/most recent).
// If the URL points to a deleted or inaccessible project/canvas, falls back to the nearest available
// project/canvas and sets `missed: true, source: 'url'` so the caller can show a gentle notice and fix the URL.
export async function resolveCanvasRouteLocation({ projects, urlRoute, remembered, listWorkflows, getWorkflow }) {
  const hasUrl = Boolean(urlRoute && (cleanParam(urlRoute.projectId) || cleanParam(urlRoute.workflowId)))
  if (!projects?.length) {
    return hasUrl ? { projectId: null, workflows: [], workflow: null, missed: true, source: 'url' } : null
  }
  if (!hasUrl) {
    const found = await resolveCanvasLocation({ projects, last: remembered, listWorkflows, getWorkflow })
    return found ? { ...found, source: remembered ? 'storage' : 'default' } : null
  }

  const wantedProject = cleanParam(urlRoute.projectId)
  const wantedWorkflow = cleanParam(urlRoute.workflowId)

  if (wantedProject) {
    const found = await resolveCanvasLocation({
      projects,
      last: { projectId: wantedProject, workflowId: wantedWorkflow },
      listWorkflows,
      getWorkflow,
    })
    return found ? { ...found, source: 'url' } : null
  }

  // Only ?canvas=<workflowId> was provided without ?project=. Resolve the workflow first to discover its project.
  try {
    const workflow = await getWorkflow(wantedWorkflow)
    const ownerProject = workflow && projects.find(item => sameId(item.id, workflow.project_id))
    if (ownerProject) {
      const workflows = await listWorkflows(ownerProject.id)
      if (workflows.some(item => sameId(item.id, workflow.id))) {
        return { projectId: ownerProject.id, workflows, workflow, missed: false, source: 'url' }
      }
    }
  } catch {
    // Missing or inaccessible workflow: fall through to fallback below.
  }

  const fallback = await resolveCanvasLocation({ projects, last: remembered, listWorkflows, getWorkflow })
  return fallback ? { ...fallback, missed: true, source: 'url' } : null
}
