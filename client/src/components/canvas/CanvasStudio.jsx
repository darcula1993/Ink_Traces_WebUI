import {syncKeyframeGroups} from '../../lib/canvasKeyframeGroups'
import CanvasGroups from './CanvasGroups'
import {organizeCanvas} from '../../lib/canvasLayout'
import {countOverlappingUnits} from '../../lib/canvasOverlap'
import {cleanGroups,createNodeGroup,groupBounds} from '../../lib/canvasGroups'
import './nodeGroups.css'
import React, { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {preloadMediaSizes,subscribeMediaSizes,mediaSizesVersion} from './mediaSizes'
import { Plus, MousePointer2, Hand, Image, Film, Music, Upload, Minus, Maximize, X, Trash2, PanelLeftOpen, Undo2, Redo2, MoreHorizontal, RotateCw, Copy, ClipboardPaste, Keyboard, CircleHelp, LayoutGrid, Play } from 'lucide-react'
import SidebarMenu,{menuPosition} from './SidebarMenu'
import CanvasNode from './CanvasNode'
import CanvasSidebar from './CanvasSidebar'
import SidebarNameDialog from './SidebarNameDialog'
import CanvasShortcutHelp,{canvasModifier} from './CanvasShortcutHelp'
import {CanvasEditHistory,copyCanvasSelection,pasteCanvasSelection,duplicateCanvasNode} from '../../lib/canvasEditHistory'
import {freeNodePosition} from '../../lib/canvasPlacement'
import {readLastLocation,writeLastLocation,pickLastLocation} from '../../lib/canvasLastLocation'
import PendingDeletions from './PendingDeletions'
import AssetImageToolbar from './AssetImageToolbar'
import CanvasNodeMenu from './CanvasNodeMenu'
import MediaPreview from './MediaPreview'
import DeleteCanvasDialog from './DeleteCanvasDialog'
import CanvasImageAnnotator from './CanvasImageAnnotator'
import useCanvasInteractions from './useCanvasInteractions'
import {switchAssetVersion,rotateImageFile,downloadAsset} from '../../lib/canvasAssetVersions'
import AssetNodePanel from './AssetNodePanel'
import {assetPanelPlacement} from './assetPanelPlacement'
import CanvasContextMenu from './CanvasContextMenu'
import {reorderNodeReferences,reconcileReferenceMentions} from '../../lib/canvasReferenceOrder'
import { canConnect, resolveNodeInputs, mediaKind } from '../../lib/canvasReferences'
import { NODE_WIDTH, NODE_HEIGHT, nodeGeometry, overlapsNode, generationPanelPlacement, fitViewport, LOD_ZOOM } from './canvasGeometry'
import CanvasNodePanel from './CanvasNodePanel'
import CanvasLibrary from './CanvasLibrary'
import {resolveLibraryItems} from '../../lib/libraryApi'
import { listCanvasProjects, createCanvasProject, renameCanvasProject, listCanvasWorkflows, createCanvasWorkflow, getCanvasWorkflow, saveCanvasWorkflow, uploadCanvasMedia, getCanvasCapabilities, submitCanvasGeneration, getCanvasTask, getTaskStatuses, resolveCanvasReferences, getCanvasProviderPreferences, saveCanvasProviderPreferences, selectedProvider, defaultProviderSelection, nodeProvider, deleteCanvasObject } from '../../lib/canvasApi'
import './canvas.css'
import ResizableSidebar from './ResizableSidebar'
import ConfirmDialog from '../ui/ConfirmDialog'
import './sidebar.css'
import './canvasTheme.css'
import './canvasNodeMedia.css'
import {collectTaskUpdates,applyTaskUpdates,patchesNeedSave} from '../../lib/canvasTaskPolling'
import {isActiveTaskStatus,isBusyTaskStatus,isFailureTaskStatus,isServerTaskStatus,documentTask,sanitizeDocumentTasks,INVALID_STATUS_LABEL} from '../../lib/taskStatus'
import {batchRunPlan} from '../../lib/canvasBatchRun'
import {referenceDropError} from '../../lib/canvasReferenceDrop'
import {PROJECT_ASSET_DRAG} from './AssetTree'
import {markStaleDownstream,clearStale,serializableDocument} from '../../lib/canvasStaleness'

const fresh = () => ({ version: 1, nodes: [], edges: [], viewport: { x: 100, y: 90, zoom: 1 } })
const uid = () => globalThis.crypto?.randomUUID?.() || `n-${Date.now()}-${Math.random().toString(36).slice(2)}`
const labels = { text: '文本', image: '画面生成', video: '视频生成', audio: '音频生成' }
const activeTask = isActiveTaskStatus
const messageOf = error => error?.response?.data?.error || error?.message || '操作失败，请重试'

export function uniqueProjectName(projects, base = '未命名项目') {
  const names = new Set((projects || []).map(item => String(item.title ?? item.name ?? '').trim()))
  if (!names.has(base)) return base
  for (let n = 2; ; n++) if (!names.has(`${base} ${n}`)) return `${base} ${n}`
}
export default function CanvasStudio({ notify, providerRevision = 0,  beforeLeaveRef }) {
  const [sidebarRename,setSidebarRename]=useState(null)
  const [workflows, setWorkflows] = useState([])
  const [projects, setProjects] = useState([])
  const [surfaceSize, setSurfaceSize] = useState({width:1000,height:700}), [sidebarOpen,setSidebarOpen] = useState(true)
  const [projectId, setProjectId] = useState(null)
  const projectIdRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [generationCount, setGenerationCount] = useState(0)
  const [ioCount, setIoCount] = useState(0)
  const ioRef = useRef(0), navigationRef = useRef(false)
  const [renameDraft, setRenameDraft] = useState(null), [renameMode, setRenameMode] = useState('rename')
  const renameInputRef = useRef(null)
  const renameOpen = renameDraft !== null
  // The sidebar menu restores focus to its trigger when it unmounts; focus the name field after that.
  useEffect(() => { if (!renameOpen) return; const frame = requestAnimationFrame(() => { renameInputRef.current?.focus(); renameInputRef.current?.select() }); return () => cancelAnimationFrame(frame) }, [renameOpen])
  const [workflow, setWorkflow] = useState(null)
  const [doc, setDoc] = useState(fresh)
  const [title, setTitle] = useState('未命名画布')
  const [selectedEdge, setSelectedEdge] = useState(null)
  const [connection, setConnection] = useState(null)
  const [contextMenu,setContextMenu] = useState(null)
  const [pendingDeletions,setPendingDeletions]=useState(false)
  const [nodeMenu,setNodeMenu]=useState(null),[preview,setPreview]=useState(null),[historyNode,setHistoryNode]=useState(null),[annotation,setAnnotation]=useState(null),[deletion,setDeletion]=useState(null),[assetRefresh,setAssetRefresh]=useState(0)
  const annotationOwner=useRef(null),replacementOwner=useRef(null),replacementInput=useRef(null),historyRef=useRef(null)
  const uploadPoint = useRef(null)
  const [tool, setTool] = useState('select')
  const editHistory=useRef(new CanvasEditHistory()),clipboard=useRef(null),pasteCount=useRef(0),editCommands=useRef(null)
  const [historyRevision,setHistoryRevision]=useState(0),[shortcutsOpen,setShortcutsOpen]=useState(false),[moreMenu,setMoreMenu]=useState(null),moreTrigger=useRef(null)
  const refreshHistory=()=>setHistoryRevision(value=>value+1)
  const [saveState, setSaveState] = useState('尚未创建')
  const [libraryTarget, setLibraryTarget] = useState(null),libraryOwner=useRef(null)
  function openLibrary(target){libraryOwner.current={workflowId:workflowRef.current?.id,projectId:projectIdRef.current,targetId:target};setLibraryTarget(target)}
  const [error, setError] = useState('')
  const [overlapCount, setOverlapCount] = useState(0)
  const [pollWarning,setPollWarning]=useState(null),[alertDismissed,setAlertDismissed]=useState(null),[statusAnomalies,setStatusAnomalies]=useState(null)
  const [unknownTasks,setUnknownTasks]=useState(()=>new Set()),[generateConfirm,setGenerateConfirm]=useState(null),[batchPlan,setBatchPlan]=useState(null)
  const [conflict, setConflict] = useState(false)
  const [loading, setLoading] = useState(true)
  const [capabilities, setCapabilities] = useState({ image: [], video: [], audio: [] })
  // Last interface chosen per node type (server workspace state); preselects new generation nodes.
  const providerPreferences = useRef({})
  const rootRef = useRef(null), fileRef = useRef(null), uploadTarget = useRef(null)
  const docRef = useRef(doc), workflowRef = useRef(null), titleRef = useRef(title)
  const version = useRef(0), savedVersion = useRef(0), contentVersion = useRef(0), savedContentVersion = useRef(0), queue = useRef(Promise.resolve()), drag = useRef(null), space = useRef(false)
  const creatingWorkflow = useRef(null), staleBaselines = useRef(new Map())
  const conflictRef = useRef(false), mounted = useRef(true), generationLocks = useRef(new Set()), polling = useRef(false)

  const showError = useCallback(error => { const msg = typeof error === 'string' ? error : messageOf(error); setError(msg) }, [])
  const edit = useCallback((transform,options={}) => {
    // UI-ITER-R2A #14: a pure viewport change (pan/zoom/fit/locate) is not an edit; it still autosaves, silently.
    const before=docRef.current,raw=transform(before),viewOnly=raw!==before&&Object.keys({...raw,...before}).every(key=>key==='viewport'||raw[key]===before[key]),transformed=cleanGroups(raw);const staleAware=options.history!==false||options.runtime;let next = (staleAware?markStaleDownstream:(_,value)=>value)(before,reconcileReferenceMentions(before,options.history!==false?syncKeyframeGroups(before,transformed,uid):transformed),staleBaselines.current)
    const created=next.groups?.find(group=>group.keyframeNodeId&&!before.groups?.some(old=>old.id===group.id));if(created&&options.history!==false&&rootRef.current){const bounds=groupBounds(created,next.nodes),rect=rootRef.current.getBoundingClientRect(),zoom=Math.min(next.viewport.zoom,(rect.width-80)/bounds.width,(rect.height-120)/bounds.height);next={...next,viewport:{x:rect.width/2-(bounds.x+bounds.width/2)*zoom,y:(rect.height-60)/2-(bounds.y+bounds.height/2)*zoom,zoom:Math.max(.15,zoom)}}}
    if(options.runtime)editHistory.current.rebaseReferenceAssets(before,next)
    if(options.history!==false){editHistory.current.record(before,next,options.key,options.description);setHistoryRevision(value=>value+1)}
    // V140 #14: transient runtime updates (task progress only) change nothing the server stores, so they never trigger a save.
    docRef.current = next; setDoc(next); if(options.transient)return; version.current += 1; if(!viewOnly){contentVersion.current += 1; setSaveState('未保存')}
  }, [])
  const interaction = useCanvasInteractions({rootRef,docRef,edit,drag,space,tool,blocked:ioCount>0 || busy,onGestureStart:()=>editHistory.current.begin(docRef.current),onGestureEnd:()=>{editHistory.current.finish(docRef.current);refreshHistory()},onGestureCancel:()=>{const before=editHistory.current.transaction;editHistory.current.transaction=null;if(before)edit(current=>({...current,nodes:current.nodes.map(node=>{const old=before.nodes.find(n=>n.id===node.id);return old?{...node,x:old.x,y:old.y}:node})}),{history:false})},onContextMenu:openContextMenu,onNodeMenu:openNodeMenu})
  function organizeKeyframes(id){edit(current=>syncKeyframeGroups({...current,nodes:current.nodes.map(node=>node.id===id?{...node,params:{...node.params,video_mode:'reference'}}:node)},current,uid),{description:'整理首尾帧节点组'})}
  function makeGroup(){try{edit(current=>createNodeGroup(current,interaction.selectedIds,uid()),{description:'将选区创建为节点组'})}catch(error){showError(error)}}
  function locateGroup(group){setFocusedGroup(group.id);const bounds=groupBounds(group,docRef.current.nodes),rect=rootRef.current.getBoundingClientRect();if(!bounds)return;interaction.choose(group.nodeIds);edit(current=>({...current,viewport:{...current.viewport,x:rect.width/2-(bounds.x+bounds.width/2)*current.viewport.zoom,y:rect.height/2-(bounds.y+bounds.height/2)*current.viewport.zoom}}),{history:false})}
  function ungroup(group){edit(current=>({...current,groups:(current.groups||[]).filter(item=>item.id!==group.id)}),{description:`解组“${group.title}”（保留节点）`})}
  function renameGroup(group){setGroupDraft({id:group.id,title:group.title})}
  function copyGroup(group){try{const result=pasteCanvasSelection(docRef.current,copyCanvasSelection(docRef.current,group.nodeIds,workflowRef.current.id),workflowRef.current.id,uid);edit(()=>result.document);interaction.choose(result.ids)}catch(error){showError(error)}}
  const [groupDraft,setGroupDraft]=useState(null)
  const [focusedGroup,setFocusedGroup]=useState(null)
  const selected=interaction.selected,setSelected=(id,append=false)=>{setFocusedGroup(null);interaction.selectSingle(id,append)}
  const locateNode=id=>{setFocusedGroup(null);interaction.locate(id)}
  useEffect(()=>{if(historyNode)historyRef.current?.querySelector('button')?.focus()},[historyNode])
  const patchNode = (id, patch, runtime=false) => edit(current => ({ ...current, nodes: current.nodes.map(node => node.id === id ? { ...node, ...patch } : node) }),runtime?{history:false,runtime:true}:{key:`${id}:${Object.keys(patch).map(key=>key==='params'?'params:'+Object.keys(patch.params).filter(p=>JSON.stringify(patch.params[p])!==JSON.stringify(docRef.current.nodes.find(n=>n.id===id)?.params?.[p])).join(','):key).sort().join(',')}`})

  async function renameSidebarProject(name) {
    setBusy(true)
    try { const renamed=await renameCanvasProject(projectIdRef.current,name); setProjects(items=>items.map(item=>item.id===renamed.id?renamed:item)) }
    finally { setBusy(false) }
  }
  async function renameSidebarWorkflow(name) {
    const previousTitle=titleRef.current
    setBusy(true)
    try { titleRef.current=name;setTitle(name);version.current+=1;contentVersion.current+=1;await save() }
    catch (failure) { titleRef.current=previousTitle;setTitle(previousTitle);version.current+=1;contentVersion.current+=1;throw failure }
    finally { setBusy(false) }
  }

  const save = useCallback(() => {
    const operation = queue.current.catch(() => {}).then(async () => {
      const currentWorkflow = workflowRef.current
      if (!currentWorkflow || savedVersion.current === version.current) return currentWorkflow
      if (conflictRef.current) throw new Error('画布有版本冲突，请先保留本地内容并重新载入。')
      const savingVersion = version.current, savingContent = contentVersion.current, silent = savingContent === savedContentVersion.current
      const payload = { title: titleRef.current || '未命名画布', document: sanitizeDocumentTasks(serializableDocument(docRef.current)), revision: currentWorkflow.revision }
      if (mounted.current && !silent) setSaveState('保存中…')
      try {
        const result = await saveCanvasWorkflow(currentWorkflow.id, payload)
        if (workflowRef.current?.id === currentWorkflow.id) {
          workflowRef.current = { ...result, document: docRef.current }
          savedVersion.current = savingVersion; savedContentVersion.current = savingContent
          if (mounted.current) {
            setWorkflow(workflowRef.current)
            setWorkflows(items => items.map(item => item.id === result.id ? result : item))
            if (!silent) setSaveState(contentVersion.current === savingContent ? '已保存' : '未保存')
          }
        }
        return result
      } catch (failure) {
        if (failure?.status === 409 || failure?.response?.status === 409) { conflictRef.current = true; if (mounted.current) setConflict(true) }
        if (mounted.current) setSaveState('保存失败')
        throw failure
      }
    })
    queue.current = operation
    return operation
  }, [])

  useEffect(() => {
    if (!beforeLeaveRef) return undefined
    beforeLeaveRef.current = async () => {
      if (loading || navigationRef.current || ioRef.current || generationLocks.current.size) {
        showError('请等待当前画布操作完成后再切换工具'); return false
      }
      navigationRef.current = true; setBusy(true)
      try {
        await save()
        if (savedVersion.current !== version.current) {
          showError('画布仍有新的未保存修改，请稍后再切换工具'); return false
        }
        return true
      } catch (failure) { showError(failure); return false }
      finally { navigationRef.current = false; setBusy(false) }
    }
    return () => { beforeLeaveRef.current = null }
  }, [beforeLeaveRef, loading, save, showError])

  const installWorkflow = useCallback(value => {
    editHistory.current.clear();clipboard.current=null;pasteCount.current=0;setHistoryRevision(value=>value+1)
    const document = value.document || fresh()
    const hadSubmitting = document.nodes?.some(node => node.task?.status === 'submitting')
    const normalized = { ...fresh(), ...document, nodes: (document.nodes || []).map(node => node.task?.status === 'submitting' ? { ...node, task: { ...node.task, status: 'unknown', error: '上次提交被中断，请到任务记录核查。' } } : node), viewport: { ...fresh().viewport, ...document.viewport } }
    workflowRef.current = value; docRef.current = normalized; titleRef.current = value.title; staleBaselines.current = new Map()
    writeLastLocation({ projectId: value.project_id ?? projectIdRef.current, workflowId: value.id })
    version.current = hadSubmitting ? 1 : 0; savedVersion.current = 0; contentVersion.current = version.current; savedContentVersion.current = 0; conflictRef.current = false
    setOverlapCount(countOverlappingUnits(normalized)); setWorkflow(value); setDoc(normalized); setTitle(value.title); setSelected(null); setSelectedEdge(null); setConnection(null); setContextMenu(null); setNodeMenu(null);setHistoryNode(null);setPreview(null); setConflict(false); setSaveState(hadSubmitting ? '提交待核查' : '已保存')
  }, [])

  useEffect(() => {
    mounted.current = true
    let alive = true
    Promise.allSettled([listCanvasProjects(), getCanvasCapabilities()]).then(async ([listed, caps]) => {
      if (!alive) return
      if (caps.status === 'fulfilled') setCapabilities(caps.value)
      else showError(caps.reason)
      if (listed.status === 'fulfilled') {
        setProjects(listed.value)
        if (listed.value.length) {
          try {
            // V140 #2: reopen the last project/canvas of this browser; fall back to the first when it no longer exists.
            const last = readLastLocation()
            const id = pickLastLocation(listed.value, last?.projectId).id
            const items = await listCanvasWorkflows(id)
            if (!alive) return
            projectIdRef.current = id; setProjectId(id); setWorkflows(items)
            if (items.length) { const full = await getCanvasWorkflow(pickLastLocation(items, last?.workflowId).id); if (alive) installWorkflow(full) }
          } catch (failure) { if (alive) showError(failure) }
        }
      } else showError(listed.reason)
      if (alive) setLoading(false)
    })
    return () => { alive = false; mounted.current = false; save().catch(() => {}) }
  }, [installWorkflow, save, showError])

  useEffect(() => {
    let alive = true
    getCanvasProviderPreferences().then(value => { if (alive) providerPreferences.current = { ...value, ...providerPreferences.current } }).catch(() => {})
    return () => { alive = false }
  }, [])
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setSurfaceSize({width:entry.contentRect.width,height:entry.contentRect.height}))
    observer.observe(rootRef.current); return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (!providerRevision) return
    let alive = true
    getCanvasCapabilities().then(value => { if (alive) setCapabilities(value) }).catch(showError)
    return () => { alive = false }
  }, [providerRevision, showError])

  // UI-ITER-R2A #2: node sizes follow measured media; re-render when a size arrives and measure off-screen media.
  useSyncExternalStore(subscribeMediaSizes, mediaSizesVersion)
  useEffect(() => { preloadMediaSizes(doc.nodes.map(node => node.asset).filter(Boolean)) }, [doc.nodes])

  useEffect(() => {
    if (!workflow || conflict || version.current === savedVersion.current) return
    const timeout = setTimeout(() => save().catch(showError), 800)
    return () => clearTimeout(timeout)
  }, [doc, title, workflow?.id, conflict, save, showError])

  useEffect(() => {
    const beforeUnload = event => { if (contentVersion.current !== savedContentVersion.current) { event.preventDefault(); event.returnValue = '' } }
    const keydown = event => {
      const target = event.target
      // Dialogs own their keyboard interaction; canvas shortcuts must not leak through.
      if (event.defaultPrevented || target.closest?.('dialog, [role="dialog"], [role="alertdialog"], .cv-studio-overlay')) return
      const editable = ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save().catch(showError); return }
      if (editable) return
      const inCanvas=target.closest?.('.cv-surface,.cv-edit-tools')
      if(inCanvas && !target.closest?.('[role=menu],video,audio') && !rootRef.current?.closest('.canvas-studio')?.querySelector('[role=dialog],.cv-studio-overlay')) {
        const key=event.key.toLowerCase(),modifier=event.ctrlKey||event.metaKey
        if(modifier&&['z','y','c','v'].includes(key)&&!window.getSelection()?.toString()){
          if(editCommands.current?.handle(key,event.shiftKey)){event.preventDefault();return}
        }
        if(event.key==='?'){event.preventDefault();setShortcutsOpen(true);return}
      }
      if (event.code === 'Space') {
        // Preserve native Space activation/playback for focused interactive elements.
        if (target.closest?.('button, a, summary, video, audio, [role="button"], [role="checkbox"], [role="switch"]')) return
        event.preventDefault(); space.current = true
      }
      if (event.key === 'Escape') { setConnection(null); setSelectedEdge(null); setSelected(null) }
    }
    const keyup = event => { if (event.code === 'Space') space.current = false }
    const blur = () => { space.current = false; editCommands.current?.cancel() }
    window.addEventListener('beforeunload', beforeUnload); window.addEventListener('keydown', keydown); window.addEventListener('keyup', keyup); window.addEventListener('blur', blur)
    return () => { window.removeEventListener('beforeunload', beforeUnload); window.removeEventListener('keydown', keydown); window.removeEventListener('keyup', keyup); window.removeEventListener('blur', blur) }
  }, [save, showError])

  // Poll active tasks with one batch status request per cycle (100 ids each).
  // Hidden pages pause; returning to the foreground polls immediately.
  // Unchanged results neither edit nor save the canvas.
  useEffect(() => {
    let alive = true
    const tick = async () => {
      if (!alive || document.hidden || polling.current || conflictRef.current || !workflowRef.current) return
      const currentWorkflowId = workflowRef.current.id
      const isCurrent = () => alive && mounted.current && workflowRef.current?.id === currentWorkflowId
      polling.current = true
      try {
        const result = await collectTaskUpdates({ document: docRef.current, getDocument: () => docRef.current, isCurrent,
          fetchStatuses: getTaskStatuses, fetchDetail: id => getCanvasTask(currentWorkflowId, id) })
        if (result.stale || !isCurrent()) return
        setPollWarning(result.failed ? { workflowId: currentWorkflowId, count: result.failed } : null)
        // Out-of-vocabulary statuses are never written; the node keeps its previous state.
        setStatusAnomalies(result.anomalies.size ? { workflowId: currentWorkflowId, nodes: result.anomalies } : null)
        if (!result.patches.size) return
        const unknown = [...result.patches.values()].filter(patch => patch.task.resultUnknown).map(patch => patch.task.id)
        if (unknown.length) setUnknownTasks(current => new Set([...current, ...unknown]))
        const persist = patchesNeedSave(docRef.current, result.patches)
        edit(current => applyTaskUpdates(current, result.patches), { history: false, runtime: true, transient: !persist })
        if (persist) try { await save() } catch (failure) { if (isCurrent()) showError(failure) }
      } catch { /* the next cycle retries; per-node failures are counted above */ }
      finally { polling.current = false }
    }
    const timer = setInterval(tick, 3000)
    const visible = () => { if (!document.hidden) tick() }
    document.addEventListener('visibilitychange', visible)
    return () => { alive = false; clearInterval(timer); document.removeEventListener('visibilitychange', visible) }
  }, [edit, save, showError])

  // result_unknown is server state; hydrate it for failed nodes after loading a canvas.
  useEffect(() => {
    const id = workflow?.id
    setUnknownTasks(new Set())
    if (!id) return undefined
    let alive = true
    const failed = docRef.current.nodes.filter(node => node.task?.id && node.task.status === 'failed').map(node => node.task.id)
    if (failed.length) getTaskStatuses(failed).then(result => {
      if (!alive || workflowRef.current?.id !== id) return
      setUnknownTasks(new Set(result.tasks.filter(task => task.status === 'failed' && task.result?.result_unknown === true).map(task => Number(task.id))))
    }).catch(() => {})
    return () => { alive = false }
  }, [workflow?.id])

  async function newWorkflow() {
    if (creatingWorkflow.current) return creatingWorkflow.current
    if (navigationRef.current || ioRef.current || generationLocks.current.size) return null
    navigationRef.current = true
    const operation = (async () => {
      setBusy(true)
      try {
        await save()
        let owner = projectIdRef.current
        if (!owner) { const createdProject = await createCanvasProject(uniqueProjectName(projects)); owner = createdProject.id; projectIdRef.current = owner; setProjectId(owner); setProjects(items => [createdProject, ...items]) }
        const created = await createCanvasWorkflow(owner, '未命名画布')
        await save()
        installWorkflow(created); setWorkflows(items => [created, ...items]); setError('')
        return created
      } catch (failure) { showError(failure); return null } finally { setBusy(false); creatingWorkflow.current = null; navigationRef.current = false }
    })()
    creatingWorkflow.current = operation
    return operation
  }
  // V140 #3: "创建新项目" first asks for the name (prefilled with a unique default); Esc cancels without creating.
  function requestNewProject() {
    if (navigationRef.current || ioRef.current || generationLocks.current.size) return false
    setError(''); setRenameMode('create'); setRenameDraft(uniqueProjectName(projects)); return true
  }
  async function newProject(name) {
    if (navigationRef.current || ioRef.current || generationLocks.current.size) return false
    navigationRef.current = true; setBusy(true)
    try {
      await save()
      const created = await createCanvasProject(name || uniqueProjectName(projects))
      const first = await createCanvasWorkflow(created.id, '未命名画布')
      await save()
      projectIdRef.current = created.id; setProjectId(created.id); setProjects(items => [created, ...items]); setWorkflows([first]); installWorkflow(first); setError(''); return true
    } catch (failure) { showError(failure); return false } finally { setBusy(false); navigationRef.current = false }
  }
  async function chooseProject(id) {
    if (String(projectIdRef.current) === String(id)) return true
    if (navigationRef.current || ioRef.current || generationLocks.current.size) return false
    navigationRef.current = true; setBusy(true)
    try {
      await save()
      const items = await listCanvasWorkflows(id)
      const full = items.length ? await getCanvasWorkflow(items[0].id) : await createCanvasWorkflow(id, '未命名画布')
      await save()
      projectIdRef.current = id; setProjectId(id); setWorkflows(items.length ? items : [full]); installWorkflow(full); setError(''); return true
    } catch (failure) { showError(failure); return false } finally { setBusy(false); navigationRef.current = false }
  }
  async function chooseWorkflow(id) {
    if (String(id) === String(workflowRef.current?.id)) return true
    if (navigationRef.current || ioRef.current || generationLocks.current.size) return false
    navigationRef.current = true; setBusy(true)
    try { await save(); const next = await getCanvasWorkflow(id); await save(); installWorkflow(next); setError(''); return true } catch (failure) { showError(failure); return false } finally { setBusy(false); navigationRef.current = false }
  }
  const worldPoint = (clientX, clientY) => {
    const rect = rootRef.current.getBoundingClientRect(), view = docRef.current.viewport
    return { x: (clientX - rect.left - view.x) / view.zoom, y: (clientY - rect.top - view.y) / view.zoom }
  }
  async function addNode(type, point, asset = null) {
    if (!workflowRef.current && !await newWorkflow()) return
    const rect = rootRef.current.getBoundingClientRect()
    const geometry=nodeGeometry({type}),middle=worldPoint(rect.left+rect.width/2,rect.top+rect.height/2)
    // V140 #5: start at the requested point (or the viewport centre) and move to the nearest free slot.
    const position = freeNodePosition(docRef.current, {type}, point || {x:middle.x-geometry.width/2,y:middle.y-geometry.height/2})
    const providerSelection = defaultProviderSelection(capabilities, type, providerPreferences.current), provider = selectedProvider(capabilities, providerSelection, type)
    const node = { id: uid(), type, title: asset?.name || labels[type], x: position.x, y: position.y, text: '', providerSelection, params: { model: provider?.model || provider?.models?.[0]?.id || '', ratio: type === 'image' ? '1:1' : '16:9', resolution: type === 'image' ? '1K' : '720p', duration: 5 }, asset, candidates: asset ? [asset] : [], selectedCandidateId: asset?.id || null, task: null }
    edit(current => ({ ...current, nodes: [...current.nodes, node] })); setSelected(node.id); setSelectedEdge(null);requestAnimationFrame(()=>interaction.reveal(node.id))
    return node
  }
  function addAssetNodes(assets, targetId, point) {
    const current = docRef.current, target = targetId && current.nodes.find(node => node.id === targetId)
    if (targetId && !target) throw new Error('目标节点不存在，请重新选择。')
    const unique = [...new Map(assets.map(asset => [asset.id,asset])).values()]
    if (target && unique.some(asset => !canConnect({id:'new-reference',type:'asset',asset},target))) throw new Error('素材类型不兼容：图像仅接受图片，视频接受图片/视频/音频，音频接受图片/音频。')
    const rect = rootRef.current.getBoundingClientRect()
    const origin = point || (target ? {x:target.x - NODE_WIDTH - 60,y:target.y} : worldPoint(rect.left+rect.width/2-145,rect.top+rect.height/2-100))
    const nodes = [...current.nodes], edges = [...current.edges], added = []
    for (const [index,asset] of unique.entries()) {
      let source = nodes.find(node => node.type === 'asset' && node.asset?.id === asset.id)
      if (!source) {
        // UI-ITER-R2-FIX L1: stack by each blocking node's real geometry (nodeGeometry), gap 20/30, never overlapping.
        let x=origin.x,y=origin.y
        for(let guard=0;guard<600;guard++){const blocker=nodes.find(node=>overlapsNode({type:'asset',x,y,asset},node,0));if(!blocker)break;if(target)y=blocker.y+nodeGeometry(blocker).height+20;else x=blocker.x+nodeGeometry(blocker).width+30}
        source = {id:uid(),type:'asset',title:asset.name || '素材',x,y,text:'',params:{},asset,candidates:[asset],selectedCandidateId:asset.id,task:null};nodes.push(source)
      }
      added.push(source)
      if (target && !edges.some(edge => edge.source===source.id && edge.target===target.id)) edges.push({id:uid(),source:source.id,target:target.id})
    }
    if(nodes.length>500||edges.length>2000)throw new Error('添加会超过画布上限（500节点／2000连线），请减少素材数量')
    if(added.some(node=>Math.abs(node.x)>1e6||Math.abs(node.y)>1e6))throw new Error('添加位置超出画布坐标范围，请先平移视口')
    edit(() => ({...current,nodes,edges}));setSelected(target?.id || added[0]?.id || null);setSelectedEdge(null)
    return {created:nodes.length-current.nodes.length,reused:unique.length-(nodes.length-current.nodes.length)}
  }
  async function addProjectAssets(assetIds,point=null,targetId=null) {
    if(ioRef.current||navigationRef.current||generationLocks.current.size)throw new Error('请等待当前操作完成后再添加素材')
    const ids=[...new Set(assetIds)],projectOwner=projectIdRef.current
    if(!ids.length)throw new Error('文件夹中没有可添加的素材')
    if(docRef.current.nodes.length+ids.length>500)throw new Error('所选素材会超过画布500节点上限，请选择更少的素材')
    if(!workflowRef.current&&!await newWorkflow())throw new Error('无法创建画布，请重试')
    const owner=workflowRef.current.id
    ioRef.current++;setIoCount(ioRef.current)
    const copied=[];let inserted=false
    try {
      await save()
      for(let index=0;index<ids.length;index+=100){const result=await resolveCanvasReferences(owner,{asset_ids:ids.slice(index,index+100),group_ids:[]});copied.push(...result.assets)}
      if(projectIdRef.current!==projectOwner||workflowRef.current?.id!==owner)throw new Error('原画布已切换，未添加到其他画布')
      if(targetId&&!docRef.current.nodes.some(n=>n.id===targetId))throw new Error('目标节点已不存在，未添加参考');await Promise.race([preloadMediaSizes(copied),new Promise(r=>setTimeout(r,2500))]);if(projectIdRef.current!==projectOwner||workflowRef.current?.id!==owner)throw new Error('原画布已切换，未添加到其他画布');const result=addAssetNodes(copied,targetId,point);inserted=true;await save();notify?.(targetId?`已追加 ${copied.length} 个参考到节点末尾`:`已添加 ${result.created} 个素材节点${result.reused?`，复用 ${result.reused} 个已有节点`:''}`,'success')
    }catch(failure){if(!inserted)throw new Error(`${messageOf(failure)}；未添加本批节点，已复制的素材保留在原画布，可重试。`);throw failure}finally{ioRef.current--;setIoCount(ioRef.current)}
  }
  // Drag from the asset tree (or its keyboard menu) onto a generation node:
  // append as references, one undo step; type/count limits refuse with a reason.
  async function addProjectReferences(assetIds,kinds,targetId){
    const target=docRef.current.nodes.find(n=>n.id===targetId)
    const issue=referenceDropError(target,target?resolveNodeInputs(target,docRef.current.nodes,docRef.current.edges).assets:[],kinds,target&&nodeProvider(capabilities,target))
    if(issue)throw new Error(`${issue}；未添加参考`)
    await addProjectAssets(assetIds,null,targetId)
  }
  function dropProjectAssets(event){
    let payload;try{payload=JSON.parse(event.dataTransfer.getData(PROJECT_ASSET_DRAG))}catch{return}
    if(String(payload?.projectId)!==String(projectIdRef.current)||!Array.isArray(payload.ids)){showError('只能拖入当前项目的素材');return}
    const targetElement=event.target.closest?.('[data-node-id]'),target=targetElement&&docRef.current.nodes.find(n=>n.id===targetElement.dataset.nodeId)
    const run=target&&['image','video','audio'].includes(target.type)?addProjectReferences(payload.ids,payload.kinds||[],target.id):addProjectAssets(payload.ids,worldPoint(event.clientX,event.clientY))
    run.catch(showError)
  }
  function clearReferences(id) { edit(current => ({...current,nodes:current.nodes.map(node => node.id===id?{...node,referenceAssets:[],referenceGroups:[]}:node),edges:current.edges.filter(edge=>edge.target!==id)})) }
  function closeContextMenu() {setContextMenu(null);rootRef.current?.focus()}
  function openContextMenu(event) {
    if(event.target.closest('.cv-node,.cv-node-panel,.cv-tools,.cv-bottom,.cv-context-menu,.cv-alert')) return
    event.preventDefault(); const rect=rootRef.current.getBoundingClientRect()
    const x=event.clientX || rect.left+rect.width/2,y=event.clientY || rect.top+rect.height/2
    setContextMenu({x:x-rect.left,y:y-rect.top,point:worldPoint(x,y)});setSelected(null);setSelectedEdge(null)
  }
  function deleteNode(id) {
    const node = docRef.current.nodes.find(item => item.id === id)
    if (ioRef.current || generationLocks.current.has(id) || isBusyTaskStatus(node?.task?.status)) return
    edit(current => ({ ...current, nodes: current.nodes.filter(node => node.id !== id), edges: current.edges.filter(edge => edge.source !== id && edge.target !== id) })); setSelected(null); setConnection(null)
  }
  const preselectedProvider=type=>defaultProviderSelection(capabilities,type,providerPreferences.current)
  // Any explicit choice on a node becomes the next preselection for that node type.
  function rememberProvider(type,selection){
    if(!['image','video','audio'].includes(type)||!selection)return
    const next={...providerPreferences.current,[type]:{provider:selection.provider,profile_id:selection.profile_id||null}}
    providerPreferences.current=next
    saveCanvasProviderPreferences(next).catch(()=>notify?.('接口偏好未能保存到服务端，本次会话仍按最近选择预选','error'))
  }
  function copyNode(node) {
    try{const position=freeNodePosition(docRef.current,node,{x:node.x+40,y:node.y+40}),result=duplicateCanvasNode(docRef.current,node.id,uid,position,preselectedProvider)
    edit(()=>result.document,{description:`复制 1 个节点`});interaction.choose(result.ids)}catch(failure){showError(failure)}
  }
  function copySelection(){
    if(!workflowRef.current||!interaction.selectedIds.length)return false
    clipboard.current=copyCanvasSelection(docRef.current,interaction.selectedIds,workflowRef.current.id);pasteCount.current=0;refreshHistory();notify?.('已复制选区，仅可粘贴到当前画布','success');return true
  }
  function pasteSelection(){
    if(!clipboard.current)return false
    try{const result=pasteCanvasSelection(docRef.current,clipboard.current,workflowRef.current?.id,uid,40*(++pasteCount.current),preselectedProvider);edit(()=>result.document,{description:`粘贴 ${result.ids.length} 个节点`});interaction.choose(result.ids);setSelectedEdge(null)}catch(failure){showError(failure)}return true
  }
  function travelHistory(redo=false){
    if(ioRef.current||navigationRef.current||drag.current||conflictRef.current)return
    try{const previousIds=new Set(docRef.current.nodes.map(n=>n.id)),next=editHistory.current.apply(docRef.current,redo);if(next!==docRef.current)edit(()=>next,{history:false});const restored=next.nodes.filter(n=>!previousIds.has(n.id)).map(n=>n.id);interaction.choose(restored.length?restored:interaction.selectedIds.filter(id=>next.nodes.some(n=>n.id===id)));setSelectedEdge(null);setConnection(null);setHistoryNode(null);refreshHistory()}catch(failure){showError(failure)}
  }
  editCommands.current={cancel:interaction.cancel,handle:(key,shift)=>{
    if(ioRef.current||navigationRef.current||drag.current||conflictRef.current)return true
    if(key==='z'||key==='y'){travelHistory(key==='y'||shift);return true}
    return key==='c'?copySelection():pasteSelection()
  }}
  function port(id, kind) {
    if (kind === 'output') { setConnection(id); return }
    if (!connection) { showError('请先点击上游节点右侧的输出连接点。'); return }
    if (connection === id) { showError('不能将节点连接到自身。'); return }
    const source = docRef.current.nodes.find(node => node.id === connection), target = docRef.current.nodes.find(node => node.id === id)
    if (!canConnect(source,target)) { showError('素材类型不兼容：图像仅接受图片，视频接受图片/视频/音频，音频接受图片/音频。'); return }
    if (docRef.current.edges.some(edge => edge.source === connection && edge.target === id)) { setConnection(null); return }
    const reachable = new Set([id]); let changed = true
    while (changed) { changed = false; for (const edge of docRef.current.edges) if (reachable.has(edge.source) && !reachable.has(edge.target)) { reachable.add(edge.target); changed = true } }
    if (reachable.has(connection)) { showError('该连接会形成循环，请调整连接方向。'); return }
    edit(current => ({ ...current, edges: [...current.edges, { id: uid(), source: connection, target: id }] })); setConnection(null); setError('')
  }
  function startDrag(event,node,options) {setFocusedGroup(null);setContextMenu(null);setNodeMenu(null);interaction.startNode(event,node,options);setSelectedEdge(null) }
  function startSurface(event) { setContextMenu(null);setNodeMenu(null);interaction.startSurface(event) }
  function movePointer(event) { interaction.move(event) }
  function zoomAt(factor, x, y) {
    const rect = rootRef.current.getBoundingClientRect(), cx = x ?? rect.width / 2, cy = y ?? rect.height / 2
    edit(current => { const view = current.viewport, zoom = Math.min(2, Math.max(.2, view.zoom * factor)); const scale = zoom / view.zoom; return { ...current, viewport: { x: cx - (cx - view.x) * scale, y: cy - (cy - view.y) * scale, zoom } } })
  }
  const zoomRef = useRef(zoomAt); zoomRef.current = zoomAt
  useEffect(() => {
    const surface = rootRef.current
    if (!surface) return
    const wheel = event => {
      if (event.target.closest('textarea,input,select,video,audio,.cv-node-text,.cv-node-panel,.cv-tools,.cv-bottom,.cv-context-menu')) return
      event.preventDefault(); const rect = surface.getBoundingClientRect(); zoomRef.current(Math.exp(-event.deltaY * .0015), event.clientX - rect.left, event.clientY - rect.top)
    }
    surface.addEventListener('wheel', wheel, { passive: false }); return () => surface.removeEventListener('wheel', wheel)
  }, [loading])
  function organize(){if(!docRef.current.nodes.length||ioRef.current||navigationRef.current||drag.current||conflictRef.current)return;try{edit(organizeCanvas,{description:`整理画布（${docRef.current.nodes.length}个节点）`});setOverlapCount(0);fit()}catch(failure){showError(failure)}}
  function fit() {
    const nodes = docRef.current.nodes
    if (!nodes.length) return
    const bounds=[...nodes.map(n=>({x:n.x,y:n.y,...nodeGeometry(n)})),...(docRef.current.groups||[]).map(group=>groupBounds(group,nodes)).filter(Boolean)],rect = rootRef.current.getBoundingClientRect(), minX = Math.min(...bounds.map(n => n.x)), minY = Math.min(...bounds.map(n => n.y)), maxX = Math.max(...bounds.map(n => n.x + n.width)), maxY = Math.max(...bounds.map(n => n.y + n.height))
    const viewport = fitViewport({ minX, minY, maxX, maxY }, rect)
    edit(current => ({ ...current, viewport }))
  }
  async function importFiles(files, point, targetId) {
    if (!files.length) return
    if (!workflowRef.current && !await newWorkflow()) return
    const owner = workflowRef.current.id
    const batchTarget = targetId && docRef.current.nodes.find(node => node.id === targetId)
    const rect = rootRef.current.getBoundingClientRect()
    const batchOrigin = point || (batchTarget ? {x:batchTarget.x-NODE_WIDTH-60,y:batchTarget.y} : worldPoint(rect.left+rect.width/2-145,rect.top+rect.height/2-100))
    ioRef.current += 1; setIoCount(ioRef.current)
    try {
    for (const [index, file] of [...files].entries()) {
      const kind = file.type.split('/')[0]
      if (!['image', 'video', 'audio'].includes(kind)) { showError(`不支持的素材类型：${file.name}`); continue }
      const target = targetId && docRef.current.nodes.find(node => node.id === targetId)
      if (target && !canConnect({id:'uploaded-reference',type:'asset',asset:{kind}},target)) { showError('所选素材类型不能接入该生成节点。'); continue }
      try {
        const asset = await uploadCanvasMedia(owner, file)
        if (workflowRef.current?.id !== owner) { showError('素材已上传到原画布；当前画布已切换，请返回原画布导入。'); break }
        addAssetNodes([asset],targetId,{x:batchOrigin.x,y:batchOrigin.y})
        await save()
      } catch (failure) { showError(failure) }
    }
    } finally { ioRef.current -= 1; if (mounted.current) setIoCount(ioRef.current) }
  }
  function pickFile(id = null, point = null) {
    const target = id && docRef.current.nodes.find(node => node.id === id)
    uploadTarget.current = id; uploadPoint.current = point
    fileRef.current.accept = target?.type === 'image' ? 'image/*' : target?.type === 'audio' ? 'image/*,audio/*' : 'image/*,video/*,audio/*'
    fileRef.current.multiple = true
    fileRef.current.click()
  }
  async function refreshCapabilities() {
    const caps = await getCanvasCapabilities()
    if (mounted.current) setCapabilities(caps)
  }
  async function generate(id) {
    if (generationLocks.current.has(id) || conflictRef.current) return
    const owner = workflowRef.current?.id
    const node = docRef.current.nodes.find(item => item.id === id)
    if (!owner || !node || !['image','video','audio'].includes(node.type) || isBusyTaskStatus(node.task?.status)) return
    generationLocks.current.add(id); setGenerationCount(generationLocks.current.size); setError('')
    let submitted = false, receivedTask = null
    const snapshot = docRef.current
    try {
      patchNode(id, { task: { id: null, status: 'submitting', error: null } },true)
      await refreshCapabilities()
      await save()
      submitted = true
      const task = await submitCanvasGeneration(owner, snapshot.nodes.find(item => item.id === id), snapshot.nodes, snapshot.edges)
      receivedTask = task
      if (workflowRef.current?.id === owner) { patchNode(id, { task: documentTask(task) },true); if(task.invalidStatus)showError(`${INVALID_STATUS_LABEL}：提交返回了未知状态“${task.invalidStatus}”，已按等待生成记录并继续以服务端状态为准`); await save() }
    } catch (failure) {
      if (workflowRef.current?.id === owner) {
        const status = failure?.status || failure?.response?.status
        const knownRejection = failure.validation || (status >= 400 && status < 500)
        if (status === 409 || failure.validation) await refreshCapabilities().catch(() => {})
        if (!receivedTask) patchNode(id, { task: { id: null, status: submitted && !knownRejection ? 'unknown' : 'failed', error: messageOf(failure) } },true)
        await save().catch(() => {})
      }
      showError(failure)
    } finally { generationLocks.current.delete(id); if (mounted.current) setGenerationCount(generationLocks.current.size) }
  }
  const isUnknownResult=node=>node?.task?.status==='failed'&&unknownTasks.has(Number(node.task.id))
  // Regenerating after an unknown result may bill twice: require explicit confirmation.
  function requestGenerate(id){const node=docRef.current.nodes.find(item=>item.id===id);if(isUnknownResult(node)){setGenerateConfirm(id);return}generate(id)}
  function planSelection(){return batchRunPlan(docRef.current,interaction.selectedIds,{providerFor:node=>nodeProvider(capabilities,node),isUnknownResult,isLocked:id=>generationLocks.current.has(id)})}
  // Each ready node is submitted as its own task, one after another; a rejected
  // node does not stop the rest and no downstream node is started automatically.
  async function runBatch(ids){let submitted=0,failed=0;const owner=workflowRef.current?.id;for(const id of ids){if(workflowRef.current?.id!==owner||!mounted.current)break;const node=docRef.current.nodes.find(item=>item.id===id);if(!node||isUnknownResult(node)||isBusyTaskStatus(node.task?.status))continue;await generate(id);const after=docRef.current.nodes.find(item=>item.id===id)?.task;if(after?.id&&!isFailureTaskStatus(after.status))submitted++;else failed++}if(mounted.current)notify?.(`已提交 ${submitted} 个节点任务${failed?`，${failed} 个未提交或结果未知，请查看节点状态`:''}`,failed?'error':'success')}
  async function linkTask(nodeId, taskId) {
    const id = Number(taskId), owner = workflowRef.current?.id
    if (!Number.isInteger(id) || id <= 0) { showError('请输入有效的本地任务编号。'); return }
    ioRef.current += 1; setIoCount(ioRef.current)
    try {
      const result = await getCanvasTask(owner, id)
      if (workflowRef.current?.id !== owner) return
      const node = docRef.current.nodes.find(item => item.id === nodeId)
      if (!node) return
      const type = result.type || result.kind || result.assets?.[0]?.kind
      if (!type) throw new Error('暂时无法确认任务类型，请稍后重试关联。')
      if (type !== node.type || result.assets?.some(asset => asset.kind !== node.type)) throw new Error('任务类型与当前节点不一致。')
      if (!isServerTaskStatus(result.status)) throw new Error(`${INVALID_STATUS_LABEL}：任务返回未知状态“${String(result.status).slice(0,40)}”，未关联，请稍后重试。`)
      const assets = result.assets || [], candidates = [...new Map([...(node.candidates || []), ...assets].map(asset => [asset.id, asset])).values()]
      patchNode(nodeId, { task: { id: result.id, status: result.status, error: result.error || null }, candidates, ...(assets.length ? { asset: assets[0], selectedCandidateId: assets[0].id } : {}) },true)
      if(result.resultUnknown)setUnknownTasks(current=>new Set([...current,Number(result.id)]))
      await save(); setError('')
    } catch (failure) { showError(failure) } finally { ioRef.current -= 1; if (mounted.current) setIoCount(ioRef.current) }
  }
  function openNodeMenu(id,event) {
    if(ioRef.current)return
    event.preventDefault();event.stopPropagation();const rect=rootRef.current.getBoundingClientRect()
    const keyboard=event.type==='keydown',nodeRect=event.currentTarget?.getBoundingClientRect();setSelected(id);setContextMenu(null);setNodeMenu({id,x:(keyboard?nodeRect.left+30:event.clientX)-rect.left,y:(keyboard?nodeRect.top+35:event.clientY)-rect.top})
  }
  function assetOwner(id,action="替换素材") {const node=docRef.current.nodes.find(item=>item.id===id);return {workflowId:workflowRef.current?.id,nodeId:id,assetId:node?.asset?.id,kind:node?.asset?.kind,description:`${action}：节点“${node?.title}”`}}
  async function saveAssetVersion(owner,file) {
    if(!owner.workflowId || workflowRef.current?.id!==owner.workflowId)throw new Error('原画布已切换，未替换当前素材')
    const node=docRef.current.nodes.find(item=>item.id===owner.nodeId)
    if(!node || node.asset?.id!==owner.assetId)throw new Error('原素材节点已改变，请重新操作')
    if(owner.kind==='image' && node.candidates?.length>=100 && !owner.versionPending)throw new Error('图片历史版本已达100个，请创建新素材节点')
    if(file.type.split('/')[0]!==owner.kind)throw new Error('替换素材必须保持原媒体类型')
    ioRef.current++;setIoCount(ioRef.current)
    try {
      const asset=await uploadCanvasMedia(owner.workflowId,file)
      if(workflowRef.current?.id!==owner.workflowId || docRef.current.nodes.find(item=>item.id===owner.nodeId)?.asset?.id!==owner.assetId)throw new Error('原素材节点已改变，文件已保存在原画布，未替换当前素材')
      const result=switchAssetVersion(docRef.current,owner.nodeId,asset,true);edit(()=>result.document,{description:owner.description});owner.assetId=asset.id;owner.versionPending=true;await save();owner.versionPending=false;if(result.warnings.length)showError(result.warnings.join('；'))
    } catch(failure) {throw new Error(messageOf(failure))} finally {ioRef.current--;setIoCount(ioRef.current)}
  }
  async function rotateNode(id) {
    if(ioRef.current)return
    const owner=assetOwner(id,"旋转图片"),node=docRef.current.nodes.find(item=>item.id===id)
    ioRef.current++;setIoCount(ioRef.current)
    try{const file=await rotateImageFile(node.asset);await saveAssetVersion(owner,file)}catch(e){showError(e)}finally{ioRef.current--;setIoCount(ioRef.current)}
  }
  function annotateNode(id) {if(ioRef.current)return;const owner=assetOwner(id,"标注图片");annotationOwner.current=owner;setAnnotation({owner,asset:docRef.current.nodes.find(n=>n.id===id).asset});ioRef.current++;setIoCount(ioRef.current)}
  function closeAnnotation(){if(annotationOwner.current){annotationOwner.current=null;ioRef.current--;setIoCount(ioRef.current)}setAnnotation(null)}
  function replaceNodeAsset(id){replacementOwner.current=assetOwner(id);replacementInput.current.accept=`${replacementOwner.current.kind}/*`;replacementInput.current.click();setNodeMenu(null)}
  function chooseVersion(id,asset){if(ioRef.current)return;try{const result=switchAssetVersion(docRef.current,id,asset);edit(()=>result.document);setHistoryNode(null);if(result.warnings.length)showError(result.warnings.join('；'));save().catch(showError)}catch(e){showError(e)}}
  // Local material deletion rewrites affected canvases on the server (revision+1).
  // Flush pending edits first; afterwards reload a clean canvas, or enter the
  // existing conflict flow if newer local edits could not be saved.
  async function flushBeforeLibraryDelete(){if(workflowRef.current&&!conflictRef.current)await save()}
  async function afterLibraryDelete(result){
    setAssetRefresh(value=>value+1)
    const current=workflowRef.current
    if(!current||!(result.workflow_ids||[]).includes(current.id))return
    if(version.current!==savedVersion.current||conflictRef.current){conflictRef.current=true;setConflict(true);return}
    try{const fresh=await getCanvasWorkflow(current.id);if(workflowRef.current?.id===current.id&&version.current===savedVersion.current)installWorkflow(fresh);else{conflictRef.current=true;setConflict(true)}}catch(failure){showError(failure)}
  }
  function clearWorkflow(){editHistory.current.clear();clipboard.current=null;refreshHistory();workflowRef.current=null;docRef.current=fresh();version.current=0;savedVersion.current=0;contentVersion.current=0;savedContentVersion.current=0;setWorkflow(null);setDoc(docRef.current);setSelected(null);setTitle('');titleRef.current='';setSaveState('尚未创建');setConflict(false);conflictRef.current=false}
  async function refreshNavigation() {
    const remaining=await listCanvasProjects();setProjects(remaining)
    const next=remaining.find(item=>item.id===projectIdRef.current) || remaining[0]
    projectIdRef.current=next?.id || null;setProjectId(next?.id || null)
    const items=next?await listCanvasWorkflows(next.id):[];setWorkflows(items)
    const current=items.find(item=>item.id===workflowRef.current?.id) || items[0]
    if(current)installWorkflow(await getCanvasWorkflow(current.id));else clearWorkflow()
    setAssetRefresh(value=>value+1)
  }
  async function confirmDeletion(cleanup) {
    const target=deletion;if(!target)return
    ioRef.current++;setIoCount(ioRef.current)
    try {
      if(!target.pending)await save()
      const result=await deleteCanvasObject(target.kind,target.id,target.pending?target.cleanup:cleanup)
      clearWorkflow();await refreshNavigation();setDeletion(null)
      notify?.(cleanup?`已删除，清理 ${result.removed_files ?? 0} 个文件，共享引用已保留`:'已删除，素材和生成文件保持保留','success')
    } catch(failure) {
      if(failure?.response?.data?.cleanup_pending){
        // A pending scope is already hidden and read-only. Retain its immutable
        // retry target while preventing autosave from writing the archived graph.
        setDeletion({...target,pending:true,cleanup});clearWorkflow()
        try{await refreshNavigation()}catch(refreshFailure){showError(refreshFailure)}
      }
      throw failure
    } finally {ioRef.current--;setIoCount(ioRef.current)}
  }
  function downloadLocal() {
    const blob = new Blob([JSON.stringify({ title: titleRef.current, document: docRef.current }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = 'canvas-local-recovery.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const view = doc.viewport
  const selectedNode = doc.nodes.find(node => node.id === selected)
  const inputMap = new Map(doc.nodes.map(node => [node.id, resolveNodeInputs(node,doc.nodes,doc.edges)]))
  const contextNode=doc.nodes.find(node=>node.id===nodeMenu?.id)
  const contextDeleteBlocked=generationLocks.current.has(nodeMenu?.id)||isBusyTaskStatus(contextNode?.task?.status)
  const SelectedPanel = selectedNode?.type === 'asset' ? AssetNodePanel : CanvasNodePanel
  const undoDescription=editHistory.current.past.at(-1)?.description,redoDescription=editHistory.current.future.at(-1)?.description
  const panelPlacement=selectedNode&&selectedNode.type!=='asset'?generationPanelPlacement(selectedNode,view,surfaceSize,doc.nodes):{style:{},side:null}
  return <section className="canvas-studio" aria-label="创作画布">
    <div className={`cv-layout ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
    <ResizableSidebar><CanvasSidebar edges={doc.edges} groups={doc.groups||[]} onLocateGroup={locateGroup} onRenameGroup={renameGroup} onUngroup={ungroup} navigationError={error} projects={projects} projectId={projectId} workflows={workflows} workflow={workflow} nodes={doc.nodes} selected={selected} selectedIds={interaction.selectedIds} disabled={loading||busy||ioCount>0||generationCount>0} onProject={chooseProject} onWorkflow={chooseWorkflow} onNewProject={requestNewProject} onNewWorkflow={newWorkflow} onRenameProject={()=>{setError('');setRenameMode('rename');setRenameDraft(projects.find(item=>String(item.id)===String(projectId))?.title || '')}} onRenameProjectDirect={renameSidebarProject} onRenameWorkflow={renameSidebarWorkflow} onLibrary={()=>openLibrary('__browse__')} onLocate={locateNode} onSelect={locateNode} onCopy={copyNode} onDelete={deleteNode} onRating={(id,rating)=>patchNode(id,{rating})} onAddAssets={addProjectAssets} onRenameNode={node=>{setSelected(node.id);setSidebarRename({id:node.id,title:node.title})}} onCollapse={()=>setSidebarOpen(false)} onDeleteProject={()=>setDeletion({kind:'project',id:projectId,title:projects.find(p=>p.id===projectId)?.title || '当前项目'})} onDeleteWorkflow={()=>setDeletion({kind:'workflow',id:workflow.id,title})} onPendingDeletions={()=>save().then(()=>setPendingDeletions(true)).catch(showError)} assetRefresh={assetRefresh} referenceTarget={interaction.selectedIds.length===1&&['image','video','audio'].includes(selectedNode?.type)?{id:selectedNode.id,title:selectedNode.title}:null} onAddReference={(ids,kinds)=>{const target=interaction.selectedIds.length===1?interaction.selectedIds[0]:null;if(!target)throw new Error('请先选择一个生成节点');return addProjectReferences(ids,kinds,target)}}/></ResizableSidebar><div className="cv-main">
    <header className="cv-topbar">{!sidebarOpen && <button className="btn btn-icon" aria-label="展开项目导航" title="展开项目导航" onClick={() => setSidebarOpen(true)}><PanelLeftOpen size={16}/></button>}{workflow && <input className="cv-project-name" aria-label="画布名称" title={title} value={title} onChange={e => { titleRef.current = e.target.value; setTitle(e.target.value); version.current += 1; contentVersion.current += 1; setSaveState('未保存') }} />}<span className="cv-spacer" /><div className="cv-edit-tools" role="group" aria-label="画布编辑">
      <span id="cv-undo-description" className="cv-sr-only">{undoDescription ? `可撤销：${undoDescription}` : '可撤销：无'}</span><span id="cv-redo-description" className="cv-sr-only">{redoDescription ? `可重做：${redoDescription}` : '可重做：无'}</span>
      <button className="btn btn-icon" aria-label="撤销画布编辑" aria-describedby="cv-undo-description" title={`${undoDescription ? "撤销："+undoDescription : "暂无可撤销操作"} (${canvasModifier()}+Z)`} disabled={!editHistory.current.past.length||ioCount>0||busy||conflict} onClick={()=>{travelHistory();rootRef.current?.focus()}}><Undo2 size={16}/></button><button className="btn btn-icon" aria-label="重做画布编辑" aria-describedby="cv-redo-description" title={`${redoDescription ? "重做："+redoDescription : "暂无可重做操作"} (${canvasModifier()}+Shift+Z)`} disabled={!editHistory.current.future.length||ioCount>0||busy||conflict} onClick={()=>{travelHistory(true);rootRef.current?.focus()}}><Redo2 size={16}/></button>
      <button ref={moreTrigger} className="btn btn-icon" aria-label="更多画布操作" title="更多画布操作（复制／粘贴选区）" aria-haspopup="menu" aria-expanded={!!moreMenu} onClick={event=>setMoreMenu(moreMenu?null:menuPosition(event))}><MoreHorizontal size={16}/></button></div>
      {ioCount > 0 && <span className="cv-save-state" role="status">正在处理素材…</span>}<span className={`cv-save-state ${saveState === '保存失败' ? 'error' : ''}`} role="status" title={`自动保存 · ${canvasModifier()}+S 立即保存`}>{saveState}</span>{workflow && (saveState === '保存失败' || conflict) && <button className="cv-retry-save" onClick={() => {save().catch(showError);rootRef.current?.focus({preventScroll:true})}} disabled={conflict} title={conflict?'画布版本冲突，请先处理冲突提示':'重新尝试保存画布'}><RotateCw size={14} />重试保存</button>}</header>
    {moreMenu && <SidebarMenu label="更多画布操作" position={moreMenu} onClose={()=>setMoreMenu(null)} className="cv-more-menu"><button role="menuitem" aria-label="复制画布选区" title={`复制画布选区 (${canvasModifier()}+C)`} disabled={!interaction.selectedIds.length||ioCount>0||busy} onClick={()=>{copySelection();setMoreMenu(null);rootRef.current?.focus()}}><Copy size={14}/>复制选区<kbd>{canvasModifier()}+C</kbd></button><button role="menuitem" aria-label="粘贴画布选区" title={`粘贴画布选区 (${canvasModifier()}+V)`} disabled={!clipboard.current||ioCount>0||busy||conflict} onClick={()=>{pasteSelection();setMoreMenu(null);rootRef.current?.focus()}}><ClipboardPaste size={14}/>粘贴<kbd>{canvasModifier()}+V</kbd></button><button role="menuitem" onClick={()=>{setMoreMenu(null);setShortcutsOpen(true)}}><Keyboard size={14}/>快捷键帮助<kbd>?</kbd></button></SidebarMenu>}
    <div ref={rootRef} className={`cv-surface ${tool === 'pan' ? 'is-pan' : ''}`} tabIndex={0} aria-label="无限画布工作区" style={{ backgroundSize: `${24 * view.zoom}px ${24 * view.zoom}px`, backgroundPosition: `${view.x}px ${view.y}px` }} onContextMenu={e=>e.preventDefault()} onKeyDown={e=>{if(e.target===e.currentTarget && (e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')))openContextMenu(e)}} onPointerDown={startSurface} onPointerMove={movePointer} onPointerUp={interaction.end} onPointerCancel={interaction.cancel} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if ([...e.dataTransfer.types].includes(PROJECT_ASSET_DRAG)) { dropProjectAssets(e); return } const type = e.dataTransfer.getData('application/x-ink-node'); if (['image','video','audio'].includes(type)) addNode(type, worldPoint(e.clientX, e.clientY)); else importFiles(e.dataTransfer.files, worldPoint(e.clientX, e.clientY)) }}>
      <div className={`cv-world ${view.zoom < LOD_ZOOM ? 'is-lod-low' : ''}`} style={{ transform: `translate(${view.x}px,${view.y}px) scale(${view.zoom})`, '--cv-zoom': view.zoom }}>
        <CanvasGroups groups={doc.groups} nodes={doc.nodes} edges={doc.edges} onLocateSource={locateNode} onUpload={id=>pickFile(id)} onLibrary={id=>{setSelected(id);openLibrary(id)}} disabled={busy||ioCount>0} onLocate={locateGroup} onRename={renameGroup} onColor={(group,color,label)=>edit(current=>({...current,groups:current.groups.map(item=>item.id===group.id?{...item,color}:item)}),{description:`节点组底色改为${label}`})} onUngroup={ungroup} onCopy={copyGroup} onDrag={(event,group)=>{if(event.button===0){setFocusedGroup(group.id);interaction.choose(group.nodeIds);}const node=docRef.current.nodes.find(n=>group.nodeIds.includes(n.id));if(node)interaction.startNode(event,node)}}/><svg className="cv-connections">{doc.edges.map(edge => { const source = doc.nodes.find(n => n.id === edge.source), target = doc.nodes.find(n => n.id === edge.target); if (!source || !target) return null; const x1 = source.x + nodeGeometry(source).width, y1 = source.y + nodeGeometry(source).portY, x2 = target.x, y2 = target.y + nodeGeometry(target).portY, bend = Math.max(80, Math.abs(x2 - x1) / 2), path = `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`; return <g key={edge.id}><path className={`cv-edge ${selectedEdge === edge.id ? 'selected' : ''}`} d={path} /><path className="cv-edge-flow" d={path} pathLength="100" aria-hidden="true"/><path className="cv-edge-hit" d={path} onPointerDown={e => {if(e.button===2){interaction.startSurface(e);return} e.stopPropagation(); setSelectedEdge(edge.id); setSelected(null) }} /></g> })}</svg>
        {doc.nodes.map(node => <CanvasNode key={node.id} node={node} provider={nodeProvider(capabilities,node)} references={inputMap.get(node.id)?.assets || []} frames={inputMap.get(node.id)?.frames} selected={interaction.selectedIds.includes(node.id)} pendingConnection={connection} onSelect={event => { if(!ioRef.current)setSelected(node.id,event?.shiftKey); setSelectedEdge(null) }} resultUnknown={isUnknownResult(node)} statusAnomaly={statusAnomalies?.workflowId===workflow?.id?statusAnomalies.nodes.get(node.id):undefined} onSelectComplete={()=>{if(workflowRef.current?.id===workflow?.id)interaction.reveal(node.id)}} onDrag={(e,options) => startDrag(e, node,options)} onChange={patch => patchNode(node.id, patch)} onPort={kind => port(node.id, kind)} onRightDrag={event=>interaction.startSurface(event,node.id)} onMenu={event=>openNodeMenu(node.id,event)} onPreview={()=>setPreview(node.asset)} onHistory={()=>{setSelected(node.id);setHistoryNode(node.id)}} onLocate={()=>locateNode(node.id)} />)}
      </div>
      {selectedNode && !doc.groups?.some(group=>group.id===focusedGroup) && <SelectedPanel workflowId={workflow?.id} onOrganizeGroup={selectedNode.type==='video'&&selectedNode.params?.video_mode==='keyframe'&&!doc.groups?.some(group=>group.keyframeNodeId===selectedNode.id)?()=>organizeKeyframes(selectedNode.id):null} errorMessage={error} key={selectedNode.id} node={selectedNode} inputAssets={inputMap.get(selectedNode.id)?.assets || []} inputIssues={inputMap.get(selectedNode.id)?.issues||[]} inputImages={(inputMap.get(selectedNode.id)?.assets || []).filter(asset=>asset.kind==='image')} onClearReferences={()=>clearReferences(selectedNode.id)} onReorderReferences={order=>{try{const before=docRef.current.nodes.find(n=>n.id===selectedNode.id)?.text;edit(current=>reorderNodeReferences(current,selectedNode.id,order),{description:'调整参考素材顺序并同步提及'});if(docRef.current.nodes.find(n=>n.id===selectedNode.id)?.text!==before)notify?.(`已同步更新提示词中的引用（${canvasModifier()}+Z 可撤销）`,'success')}catch(error){showError(error)}}} provider={nodeProvider(capabilities, selectedNode)} providerOptions={capabilities[selectedNode.type]||[]} style={selectedNode.type==='asset'?assetPanelPlacement(selectedNode,view,surfaceSize):panelPlacement.style} placement={panelPlacement.side} onClose={() => {setSelected(null);rootRef.current?.focus()}} onChange={patch => {patchNode(selectedNode.id, patch);if(patch.providerSelection)rememberProvider(selectedNode.type,patch.providerSelection)}} onSave={()=>save().catch(showError)} resultUnknown={isUnknownResult(selectedNode)} onGenerate={() => requestGenerate(selectedNode.id)} onDismissStale={()=>edit(current=>clearStale(current,selectedNode.id),{description:'清除“上游已更新”标记'})} onUpload={() => pickFile(selectedNode.id)} onCopy={() => copyNode(selectedNode)} onLibrary={() => openLibrary(selectedNode.id)} onLinkTask={taskId => linkTask(selectedNode.id, taskId)} />}
      {interaction.marquee && <div className="cv-selection-box" style={interaction.marquee}/>}
      {interaction.selectedIds.length>1 && <div className="cv-multi-selection">已选 {interaction.selectedIds.length} 个节点 · 拖动任一标题一起移动<button disabled={busy||ioCount>0} onPointerDown={e=>e.stopPropagation()} onClick={makeGroup}>创建节点组</button><button className="cv-run-selected" disabled={busy||ioCount>0||conflict||!interaction.selectedIds.some(id=>['image','video','audio'].includes(doc.nodes.find(n=>n.id===id)?.type))} title="一次提交所选节点中输入已就绪的生成节点，每个节点独立任务，不连锁下游" onPointerDown={e=>e.stopPropagation()} onClick={()=>setBatchPlan(planSelection())}><Play size={13}/>运行所选节点</button></div>}
      {selectedNode?.type==='asset' && selectedNode.asset.kind==='image' && !annotation && <AssetImageToolbar style={{left:Math.max(8,Math.min(surfaceSize.width-290,selectedNode.x*view.zoom+view.x)),top:Math.max(8,selectedNode.y*view.zoom+view.y-44)}} busy={ioCount>0} onRotate={()=>rotateNode(selectedNode.id)} onAnnotate={()=>annotateNode(selectedNode.id)} onDownload={()=>downloadAsset(selectedNode.asset).catch(showError)} onPreview={()=>setPreview(selectedNode.asset)}/>}
      {nodeMenu && <CanvasNodeMenu isAsset={contextNode?.type==='asset'} deleteDisabled={contextDeleteBlocked} position={nodeMenu} bounds={surfaceSize} busy={ioCount>0} onClose={()=>setNodeMenu(null)} onCopy={()=>{const node=docRef.current.nodes.find(n=>n.id===nodeMenu.id);if(node)copyNode(node);setNodeMenu(null)}} onDelete={()=>{deleteNode(nodeMenu.id);setNodeMenu(null)}} onReplace={()=>replaceNodeAsset(nodeMenu.id)}/>}
      {historyNode && <div ref={historyRef} className="cv-history-popover" role="dialog" aria-label="图片历史版本" onKeyDown={e=>{e.stopPropagation();if(e.key==='Escape')setHistoryNode(null)}} onPointerDown={e=>e.stopPropagation()}><header>保留的版本<button aria-label="关闭历史版本" onClick={()=>setHistoryNode(null)}>关闭</button></header>{doc.nodes.find(n=>n.id===historyNode)?.candidates?.map((asset,index)=><button key={asset.id} disabled={ioCount>0} aria-pressed={doc.nodes.find(n=>n.id===historyNode)?.asset.id===asset.id} onClick={()=>chooseVersion(historyNode,asset)}><img src={asset.url} alt=""/>版本 {index+1}</button>)}</div>}
      {annotation && <CanvasImageAnnotator key={annotation.asset.id} asset={annotation.asset} style={{zIndex:50}} onSave={file=>saveAssetVersion(annotation.owner,file)} onClose={closeAnnotation}/>}
      {contextMenu && <CanvasContextMenu position={contextMenu} bounds={surfaceSize} onClose={closeContextMenu} onDismiss={()=>setContextMenu(null)} onUpload={()=>{const point=contextMenu.point;closeContextMenu();pickFile(null,point)}} onCreate={type=>{const point=contextMenu.point;closeContextMenu();addNode(type,point)}}/>}
      <div className="cv-tools" onPointerDown={e => e.stopPropagation()}><button title="选择节点" aria-label="选择工具" aria-pressed={tool === 'select'} onClick={() => setTool('select')}><MousePointer2 size={18} /></button><button title="平移画布（空格拖动）" aria-label="平移工具" aria-pressed={tool === 'pan'} onClick={() => setTool('pan')}><Hand size={18} /></button><hr />{[['image',Image],['video',Film],['audio',Music]].map(([type, Icon]) => <button key={type} draggable onDragStart={event => { event.dataTransfer.setData("application/x-ink-node", type); event.dataTransfer.effectAllowed = "copy" }} title={`添加${labels[type]}节点（可拖入画布）`} aria-label={`添加${labels[type]}节点`} onClick={() => addNode(type)}><Icon size={18} /></button>)}<hr /><button title="导入素材" aria-label="导入素材" onClick={() => pickFile()}><Upload size={18} /></button></div>
      {loading ? <div className="cv-empty">正在载入画布…</div> : !doc.nodes.length && <div className="cv-empty" onPointerDown={e => e.stopPropagation()}><h2>把想法放上画布</h2><p>拖入素材，连接参考，逐个制作你的镜头。</p><div className="cv-empty-actions"><button className="btn btn-primary" onClick={() => addNode('image')}><Image size={16} />图像生成</button><button onClick={() => addNode('video')}><Film size={16} />视频生成</button><button onClick={() => addNode('audio')}><Music size={16} />音频生成</button></div><small>节点自由摆放 · 连线选择参考 · 点击生成才运行任务</small></div>}
      {connection && <div className="cv-connection-note" onPointerDown={e => e.stopPropagation()}>点击目标节点左侧连接点<button onClick={() => setConnection(null)}>取消</button></div>}
      {selectedEdge && <div className="cv-connection-note" onPointerDown={e => e.stopPropagation()}><button onClick={() => { edit(current => ({ ...current, edges: current.edges.filter(edge => edge.id !== selectedEdge) })); setSelectedEdge(null) }}><Trash2 size={13} />移除连接</button></div>}
      <div className="cv-bottom" onPointerDown={e => e.stopPropagation()}><button aria-label="缩小画布" title="缩小画布" onClick={() => zoomAt(1 / 1.2)}><Minus size={14} /></button><output aria-label={`画布缩放 ${Math.round(view.zoom * 100)}%`}>{Math.round(view.zoom * 100)}%</output><button aria-label="放大画布" title="放大画布" onClick={() => zoomAt(1.2)}><Plus size={14} /></button><button aria-label="适配全部节点" title="适配全部节点" onClick={fit}><Maximize size={14} /></button><button aria-label="整理画布" title="按依赖从左到右整理，保留组内布局；可撤销" disabled={!doc.nodes.length||busy||ioCount>0||generationCount>0||!!conflict} onClick={organize}><LayoutGrid size={14}/><span className="cv-bottom-label">整理画布</span></button><button aria-label="画布快捷键帮助" title="画布快捷键帮助 (?)" onClick={()=>setShortcutsOpen(true)}><CircleHelp size={14}/></button></div><span className="cv-hint">空格 + 拖动平移 · 滚轮缩放 · 连线不会自动生成</span>
      {!error&&alertDismissed!==`${pollWarning?.count||0}|${statusAnomalies?.nodes?.size||0}`&&((pollWarning&&pollWarning.workflowId===workflow?.id)||(statusAnomalies&&statusAnomalies.workflowId===workflow?.id))&&<div className="cv-alert cv-alert-stack" role="status" onPointerDown={e=>e.stopPropagation()}>{pollWarning&&pollWarning.workflowId===workflow?.id&&<span>{pollWarning.count} 个任务暂时无法更新，正在重试；其他任务继续更新。</span>}{statusAnomalies&&statusAnomalies.workflowId===workflow?.id&&<span data-testid="task-status-anomaly">{INVALID_STATUS_LABEL}：{statusAnomalies.nodes.size} 个任务返回未知状态（{[...new Set(statusAnomalies.nodes.values())].join('、').slice(0,60)}），已保留原状态，其他任务照常更新。</span>}<button aria-label="关闭提示" title="关闭提示" onClick={()=>setAlertDismissed(`${pollWarning?.count||0}|${statusAnomalies?.nodes?.size||0}`)}><X size={13} /></button></div>}
    {!error&&overlapCount>0&&<div className="cv-alert cv-alert-stack" role="status" data-testid="overlap-notice" onPointerDown={e=>e.stopPropagation()}><span>{overlapCount} 个节点因按画面比例显示而相互重叠，可使用「整理画布」（可撤销）；不会自动移动节点。</span><span><button className="btn" onClick={organize} disabled={busy||ioCount>0||generationCount>0||!!conflict}>整理画布</button><button aria-label="关闭提示" title="关闭提示" onClick={()=>setOverlapCount(0)}><X size={13} /></button></span></div>}
    {error && <div className="cv-alert" role="alert" onPointerDown={e => e.stopPropagation()}><span>{error}</span><button aria-label="关闭提示" title="关闭提示" onClick={() => setError('')}><X size={13} /></button></div>}
    </div>
    </div></div>
    <input ref={fileRef} aria-label="导入画布素材文件" type="file" accept="image/*,video/*,audio/*" onChange={e => { importFiles([...e.target.files], uploadPoint.current, uploadTarget.current); e.target.value = '' }} />
    <input ref={replacementInput} aria-label="替换节点素材文件" type="file" onChange={e=>{const file=e.target.files[0],owner=replacementOwner.current;e.target.value='';if(file&&owner)saveAssetVersion(owner,file).catch(showError)}}/>
    {shortcutsOpen && <CanvasShortcutHelp onClose={()=>{setShortcutsOpen(false);rootRef.current?.focus()}} onClear={()=>{editHistory.current.clear();refreshHistory();setShortcutsOpen(false);rootRef.current?.focus()}}/>}
    {preview && <MediaPreview key={preview.id} asset={preview} onClose={()=>setPreview(null)}/>}
    {pendingDeletions && <PendingDeletions onClose={()=>setPendingDeletions(false)} onChanged={refreshNavigation}/>}
    {deletion && <DeleteCanvasDialog target={deletion} onClose={()=>setDeletion(null)} onConfirm={confirmDeletion}/>}
    {groupDraft && <SidebarNameDialog kind="节点组" draft={groupDraft} onChange={setGroupDraft} onClose={()=>setGroupDraft(null)} onSave={()=>{const title=groupDraft.title.trim().slice(0,100);if(title)edit(current=>({...current,groups:current.groups.map(group=>group.id===groupDraft.id?{...group,title}:group)}),{description:'重命名节点组'});setGroupDraft(null)}}/>}
    {sidebarRename && <SidebarNameDialog draft={sidebarRename} onChange={setSidebarRename} onClose={()=>setSidebarRename(null)} onSave={()=>{patchNode(sidebarRename.id,{title:sidebarRename.title.trim()});setSidebarRename(null)}}/>}
    {renameDraft !== null && (() => {
      const creating = renameMode === 'create', close = () => setRenameDraft(null)
      const commit = async () => {
        const name = renameDraft.trim()
        if (!name || busy) return
        if (creating) { if (await newProject(name)) close(); return }
        setBusy(true)
        try { const renamed = await renameCanvasProject(projectIdRef.current, name); setProjects(items => items.map(item => item.id === renamed.id ? renamed : item)); close() } catch (failure) { showError(failure) } finally { setBusy(false) }
      }
      return <div className="cv-studio-overlay"><div role="dialog" aria-modal="true" aria-label={creating ? '新建项目' : '命名项目'} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close() } }}><h3>{creating ? '新建项目' : '项目名称'}</h3><input ref={renameInputRef} autoFocus aria-label="项目名称" value={renameDraft} maxLength={100} onChange={event => setRenameDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); commit() } }} />{error && <p role="alert">{error}</p>}<p /><button onClick={close}>取消</button><button className="btn btn-primary" disabled={!renameDraft.trim() || busy} onClick={commit}>{creating ? '创建项目' : '保存名称'}</button></div></div>
    })()}
    {busy && <div className="cv-studio-overlay" role="status"><div>正在打开画布…</div></div>}
    {libraryTarget && <CanvasLibrary projectId={libraryOwner.current?.projectId} onBeforeDelete={flushBeforeLibraryDelete} onDeleted={afterLibraryDelete} onClose={() => {setLibraryTarget(null);setAssetRefresh(value=>value+1)}} browseOnly={libraryTarget === '__browse__'} canAddToCanvas={!!libraryOwner.current?.workflowId} allowedKinds={doc.nodes.find(n=>n.id===libraryTarget)?.type==='image'?['image']:doc.nodes.find(n=>n.id===libraryTarget)?.type==='audio'?['image','audio']:['image','video','audio']} validateSelection={items=>{const node=docRef.current.nodes.find(n=>n.id===libraryTarget);if(node?.type==='video'&&node.params?.video_mode==='keyframe'){return items.some(item=>item.asset.kind!=='image')?'首尾帧仅支持图片':items.length>2?'首尾帧一次最多选择两张图片':null}return null}} onApply={async items => {
      const owner=libraryOwner.current
      if(!owner)return
      const target=owner.targetId==='__browse__'?null:owner.targetId
      if(workflowRef.current?.id!==owner.workflowId||target&&!docRef.current.nodes.some(n=>n.id===target))throw new Error('原画布或节点已切换，请重新打开素材库')
      if(ioRef.current||navigationRef.current)throw new Error('请等待当前操作完成')
      ioRef.current++;setIoCount(ioRef.current)
      try{const resolved=await resolveLibraryItems(owner.workflowId,items.map(item=>item.selection));if(workflowRef.current?.id!==owner.workflowId||projectIdRef.current!==owner.projectId||target&&!docRef.current.nodes.some(n=>n.id===target))throw new Error('原画布已切换，未添加到其他画布');const currentNode=docRef.current.nodes.find(n=>n.id===target);if(currentNode?.type==='video'&&currentNode.params?.video_mode==='keyframe'){const current=resolveNodeInputs(currentNode,docRef.current.nodes,docRef.current.edges).assets,merged=[...new Map([...current,...resolved.assets].map(asset=>[asset.id,asset])).values()];if(merged.some(asset=>asset.kind!=='image')||merged.length>2)throw new Error('首尾帧最多两个图片参考，请先移除已有参考；本次未添加节点或连线')}addAssetNodes(resolved.assets||[],target);await save();setLibraryTarget(null);setAssetRefresh(value=>value+1)}finally{ioRef.current--;setIoCount(ioRef.current)}
    }} />}
    {batchPlan && <ConfirmDialog className="canvas-studio-confirm" title={batchPlan.ready.length?`运行 ${batchPlan.ready.length} 个所选节点？`:'没有可运行的节点'} confirmLabel={batchPlan.ready.length?`提交 ${batchPlan.ready.length} 个任务`:'关闭'} onClose={()=>setBatchPlan(null)} onConfirm={async()=>{const ids=batchPlan.ready.map(item=>item.node.id);setBatchPlan(null);if(ids.length)await runBatch(ids)}}><div data-testid="batch-run-summary"><p>将提交 <strong>{batchPlan.ready.length}</strong> 个节点，每个节点创建一个独立任务；不会自动运行下游节点。</p><p>合计预估：<strong>{batchPlan.ready.length?batchPlan.total.text:'—'}</strong>（按现有费率估算，非实际扣费）</p>{batchPlan.ready.length>0&&<ul>{batchPlan.ready.map(({node,cost})=><li key={node.id}>{node.title}：{cost.known?(cost.min.toFixed(2)===cost.max.toFixed(2)?`$${cost.min.toFixed(2)}`:`$${cost.min.toFixed(2)}~$${cost.max.toFixed(2)}`):`费用待估（${cost.reason}）`}</li>)}</ul>}{batchPlan.skipped.length>0&&<><p>以下 {batchPlan.skipped.length} 个节点不会提交：</p><ul>{batchPlan.skipped.map(({node,reason})=><li key={node.id}>{node.title}：{reason}</li>)}</ul></>}</div></ConfirmDialog>}
    {generateConfirm && <ConfirmDialog className="canvas-studio-confirm" title="上次结果未知，仍要重新生成？" danger confirmLabel="确认重新生成（可能重复计费）" onClose={()=>setGenerateConfirm(null)} onConfirm={async()=>{const id=generateConfirm;setGenerateConfirm(null);await generate(id)}}><p>该节点上一次任务的请求已发出但未确认结果，<strong>供应商可能已经计费</strong>。</p><p>重新生成会提交新的任务，<strong>可能重复计费</strong>。建议先到任务中心或供应商控制台核查原任务。</p></ConfirmDialog>}
    {conflict && <div className="cv-studio-overlay"><div><h3>画布已在其他窗口更新</h3><p>本地编辑已保留，自动保存已停止。先下载本地记录，再载入服务器版本；重新载入会替换当前未保存内容。</p><button onClick={downloadLocal}>下载本地记录</button><button onClick={async () => { try { installWorkflow(await getCanvasWorkflow(workflowRef.current.id)); setError('') } catch (failure) { showError(failure) } }}>重新载入</button></div></div>}
  </section>
}
