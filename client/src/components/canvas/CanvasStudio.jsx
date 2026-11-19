import {syncKeyframeGroups} from '../../lib/canvasKeyframeGroups'
import CanvasGroups from './CanvasGroups'
import {useGroupRunController} from './CanvasGroupRun'
import {adoptGroupRunTasks} from '../../lib/canvasGroupRun'
import {organizeCanvas} from '../../lib/canvasLayout'
import {countOverlappingUnits} from '../../lib/canvasOverlap'
import {cleanGroups,createNodeGroup,groupBounds} from '../../lib/canvasGroups'
import './nodeGroups.css'
import React, { useCallback, useMemo, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import {createPortal} from 'react-dom'
import {preloadMediaSizes,subscribeMediaSizes,mediaSizesVersion,mediaSize} from './mediaSizes'
import { Plus, MousePointer2, Hand, Image, Film, Music, Upload, X, Trash2, MoreHorizontal, RotateCw, Copy, ClipboardPaste, Keyboard, CircleHelp, LayoutGrid, Play, Bell } from 'lucide-react'
import SidebarMenu,{menuPosition} from './SidebarMenu'
import CanvasNodeBoundary from './CanvasNodeBoundary'
import CanvasRail,{CanvasRailPanel,useCanvasRail} from './CanvasRail'
import CanvasProjectPanel from './CanvasProjectPanel'
import CanvasAssetPanel from './CanvasAssetPanel'
import CanvasPromptPanel from './CanvasPromptPanel'
import CanvasTaskPanel from './CanvasTaskPanel'
import CanvasNodeToolbar from './CanvasNodeToolbar'
import CanvasVersionPopover from './CanvasVersionPopover'
import {defaultVideoResolution} from '../../lib/videoGenerationRules'
import CanvasMinimap,{CanvasViewportTools} from './CanvasMinimap'
import {nodeToolbarVisible,nodeToolbarKind,nodeScreenRect,pinAllowed,PIN_REFUSED_MESSAGE,readMinimapPreference,writeMinimapPreference,summarizeCanvasTasks,railPanelDefaultWidth,RIGHT_PANEL_MIN,PIN_MIN_CANVAS,RAIL_WIDTH} from './canvasChrome'
import {insertPromptText} from './PromptLibraryPicker'
import SidebarNameDialog from './SidebarNameDialog'
import CanvasShortcutHelp,{canvasModifier} from './CanvasShortcutHelp'
import {CanvasEditHistory,copyCanvasSelection,pasteCanvasSelection,duplicateCanvasNode} from '../../lib/canvasEditHistory'
import {freeNodePosition,freeNodePositionInView} from '../../lib/canvasPlacement'
import {readRememberedLocation,writeLastLocation,resolveCanvasLocation,MISSED_LOCATION_MESSAGE} from '../../lib/canvasLastLocation'
import {writeDraft,readDraft,clearDraft,draftIncluded,mergeDraftDocument} from '../../lib/canvasDraftBackup'
import PendingDeletions from './PendingDeletions'
const ImageAssetEditor=React.lazy(()=>import('../image-editor/ImageAssetEditor'))
import CanvasNodeMenu from './CanvasNodeMenu'
import AddToCharacterDialog from './AddToCharacterDialog'
import CanvasMoveToFolder from './CanvasMoveToFolder'
import useCanvasMediaStatus from './useCanvasMediaStatus'
import {uploadCanvasLibraryMedia,resolveLibraryMedia,lookupMedia,readUploadFolder,writeUploadFolder} from '../../lib/canvasMedia'
import {isMediaAsset,isDeletedMedia,isTrashedMedia,markDeletedMedia} from '../../lib/canvasMediaStatus'
import MediaPreview,{previewItems} from './MediaPreview'
import DeleteCanvasDialog from './DeleteCanvasDialog'
const CanvasImageAnnotator = React.lazy(() => import('./CanvasImageAnnotator'))
import useCanvasInteractions from './useCanvasInteractions'
import {switchAssetVersion,rotateImageFile,downloadAsset} from '../../lib/canvasAssetVersions'
import CanvasContextMenu from './CanvasContextMenu'
import {reorderNodeReferences,reconcileReferenceMentions,insertNodeReferenceAt} from '../../lib/canvasReferenceOrder'
import {deriveNodePorts,portAddError,pendingReferenceEdges,removeOverLimitReferences,PORT_KINDS} from '../../lib/canvasPorts'
import {portLayout,overLimitMessages,overLimitBlock,portDropAnnouncement} from '../../lib/canvasPortLayout'
import { canConnect, resolveNodeInputs, mediaKind } from '../../lib/canvasReferences'
import { NODE_WIDTH, NODE_HEIGHT, nodeGeometry, nodeMediaKind, overlapsNode, fitViewport, LOD_ZOOM, resizableNode, clampNodeScale } from './canvasGeometry'
import CanvasPropertiesPanel,{usePropertiesPanelPrefs,canvasContent,multiContent,groupContent,textContent,assetContent,generationContent} from './CanvasPropertiesPanel'
import CanvasNodePrompt,{CanvasPromptDialog} from './CanvasNodePrompt'
import useNodeCharacters from './useNodeCharacters'
import useNodeGeneration,{quickGenerationBlock} from './useNodeGeneration'
import {useCanvasEstimate} from './CanvasVideoEstimate'
import CanvasLibrary from './CanvasLibrary'
import {resolveLibraryItems} from '../../lib/libraryApi'
import { listCanvasProjects, createCanvasProject, renameCanvasProject, listCanvasWorkflows, createCanvasWorkflow, getCanvasWorkflow, saveCanvasWorkflow, saveCanvasWorkflowKeepalive, keepaliveBodyFits, getCanvasCapabilities, submitCanvasGeneration, getCanvasTask, getTaskDetail, syncCanvasTasks, getTaskStatuses, getCanvasProviderPreferences, saveCanvasProviderPreferences, selectedProvider, defaultProviderSelection, nodeProvider, deleteCanvasObject } from '../../lib/canvasApi'
import './canvas.css'
import ConfirmDialog from '../ui/ConfirmDialog'
import './sidebar.css'
import './canvasTheme.css'
import './canvasNodeMedia.css'
import {collectTaskUpdates,applyTaskUpdates,taskSyncPatches,mergeSavedDocument,sameServerDocument} from '../../lib/canvasTaskPolling'
import {isActiveTaskStatus,isBusyTaskStatus,isFailureTaskStatus,isServerTaskStatus,documentTask,sanitizeDocumentTasks,INVALID_STATUS_LABEL} from '../../lib/taskStatus'
import {batchRunPlan,formatCostRange} from '../../lib/canvasBatchRun'
import {referenceDropError} from '../../lib/canvasReferenceDrop'
import {PROJECT_ASSET_DRAG} from './AssetTree'
import {clipboardFiles} from '../../lib/canvasClipboard'
import {captureVideoFrame,frameFileName,formatFrameTime} from '../../lib/videoFrameCapture'
import {markStaleDownstream,clearStale,serializableDocument} from '../../lib/canvasStaleness'
import TaskDoneNotices from './TaskDoneNotices'
import {requestTaskCenter} from '../../lib/taskCenterLink'
import {completionNotices,noteActiveTasks,mergeNotices,baseTitle,titleWithCount,pageInForeground,readSystemSetting,writeSystemSetting,notificationPermission,shouldAskSystem,systemEnabled} from '../../lib/taskDoneNotify'

const fresh = () => ({ version: 1, nodes: [], edges: [], viewport: { x: 100, y: 90, zoom: 1 } })
const uid = () => globalThis.crypto?.randomUUID?.() || `n-${Date.now()}-${Math.random().toString(36).slice(2)}`
const labels = { text: '文本', image: '画面生成', video: '视频生成', audio: '音频生成' }
const activeTask = isActiveTaskStatus
// CANVAS-INPUT-20261114 #7a: wheel/buttons zoom up to 800%; double-click frames a node at 300% (less when it would not fit).
export const MAX_ZOOM = 8, FOCUS_ZOOM = 3, FOCUS_FILL = .9, FOCUS_MS = 350
// FIX-B2-20261114 #3, CANVAS-LAYOUT-1-20261117: the focused node is framed above the bottom bars, centred
// horizontally, at 300% or less, and never covered. Its settings are in the right properties panel (outside
// the surface), so no room is reserved below the node any more.
export const FOCUS_BOTTOM_BAR = 72, FOCUS_MARGIN = 16
export function focusViewport(node, size) {
  const {width, height} = nodeGeometry(node)
  const top = FOCUS_MARGIN, bottom = size.height - FOCUS_BOTTOM_BAR
  const zoom = Math.max(.2, Math.min(FOCUS_ZOOM, FOCUS_FILL * size.width / width, (bottom - top) / height))
  const nodeTop = top + Math.max(0, (bottom - top - height * zoom) / 2)
  return { zoom, x: size.width / 2 - (node.x + width / 2) * zoom, y: nodeTop - node.y * zoom }
}
// TASK-DONE-NOTIFY-20261114: while the page is hidden, active tasks are still polled (same requests) at this slower cadence so completion reminders can reach a background tab.
export const HIDDEN_POLL_MS = 30000
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
  const [surfaceSize, setSurfaceSize] = useState({width:1000,height:700})
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
  const [connection, setConnection] = useState(null), [portHover, setPortHover] = useState(null)
  const [contextMenu,setContextMenu] = useState(null)
  const [pendingDeletions,setPendingDeletions]=useState(false)
  const [nodeMenu,setNodeMenu]=useState(null),[preview,setPreview]=useState(null),[historyNode,setHistoryNode]=useState(null),[annotation,setAnnotation]=useState(null),[deletion,setDeletion]=useState(null),[assetRefresh,setAssetRefresh]=useState(0),[mediaRefresh,setMediaRefresh]=useState(0)
  const annotationOwner=useRef(null),replacementOwner=useRef(null),replacementInput=useRef(null),historyReturn=useRef(null)
  const uploadPoint = useRef(null), lastPointer = useRef(null), pendingKeyPaste = useRef(false)
  // CANVAS-INPUT-20261114 #2: drag-to-connect from an output port (runtime only, never saved).
  const [portDrag,setPortDrag] = useState(null), portDragRef = useRef(null), suppressPortClick = useRef(false)
  const [tool, setTool] = useState('select')
  const editHistory=useRef(new CanvasEditHistory()),clipboard=useRef(null),pasteCount=useRef(0),editCommands=useRef(null)
  const [historyRevision,setHistoryRevision]=useState(0),[shortcutsOpen,setShortcutsOpen]=useState(false),[moreMenu,setMoreMenu]=useState(null),moreTrigger=useRef(null)
  const refreshHistory=()=>setHistoryRevision(value=>value+1)
  const [saveState, setSaveState] = useState('尚未创建')
  const [libraryTarget, setLibraryTarget] = useState(null),libraryOwner=useRef(null),[replaceOwner,setReplaceOwner]=useState(null),[characterTarget,setCharacterTarget]=useState(null),[movingAssets,setMovingAssets]=useState(null),[revealMedia,setRevealMedia]=useState(null)
  // LIBRARY-GLOBAL S5: canvas uploads/pastes/frames/save-as go to the library root or this folder (per viewer).
  const [uploadFolder,setUploadFolderState]=useState(readUploadFolder),uploadFolderRef=useRef(uploadFolder)
  const setUploadFolder=id=>{uploadFolderRef.current=id||null;setUploadFolderState(id||null);writeUploadFolder(id||null)}
  function openLibrary(target,initialSource='local'){libraryOwner.current={workflowId:workflowRef.current?.id,projectId:projectIdRef.current,targetId:target,initialSource};setLibraryTarget(target)}
  const [error, setError] = useState('')
  const [overlapCount, setOverlapCount] = useState(0)
  const [pollWarning,setPollWarning]=useState(null),[alertDismissed,setAlertDismissed]=useState(null),[statusAnomalies,setStatusAnomalies]=useState(null)
  const [unknownTasks,setUnknownTasks]=useState(()=>new Set()),[generateConfirm,setGenerateConfirm]=useState(null),[batchPlan,setBatchPlan]=useState(null)
  const [conflict, setConflict] = useState(false)
  // FIX-B2 rework: unsaved local draft found when opening a canvas ({draft, newer}); offered, never applied automatically.
  const [draftOffer, setDraftOffer] = useState(null)
  const [loading, setLoading] = useState(true)
  const [capabilities, setCapabilities] = useState({ image: [], video: [], audio: [] })
  // Last interface chosen per node type (server workspace state); preselects new generation nodes.
  const providerPreferences = useRef({})
  const rootRef = useRef(null), fileRef = useRef(null), uploadTarget = useRef(null)
  const worldId = React.useId()
  const docRef = useRef(doc), workflowRef = useRef(null), titleRef = useRef(title)
  const mediaStatus = useCanvasMediaStatus(doc)
  const version = useRef(0), savedVersion = useRef(0), contentVersion = useRef(0), savedContentVersion = useRef(0), queue = useRef(Promise.resolve()), drag = useRef(null), space = useRef(false)
  const creatingWorkflow = useRef(null), staleBaselines = useRef(new Map())
  const conflictRef = useRef(false), mounted = useRef(true), generationLocks = useRef(new Set()), polling = useRef(false)
  // CANVAS-WRITEBACK-20261114: last document this window knows the server holds, and task-sync retry throttle (taskId -> time).
  const serverDocRef = useRef(null), syncRetry = useRef(new Map())
  // TASK-DONE-NOTIFY-20261114: completion reminders (runtime only, never saved).
  const [doneNotices,setDoneNotices]=useState([]),notifiedTasks=useRef(new Set()),watchedTasks=useRef(new Set()),unreadDone=useRef(0),titleBase=useRef(null)
  const [systemSetting,setSystemSetting]=useState(()=>readSystemSetting()),[permission,setPermission]=useState(()=>notificationPermission()),[askSystem,setAskSystem]=useState(false)
  const remindRef=useRef(null)

  const showError = useCallback(error => { const msg = typeof error === 'string' ? error : messageOf(error); setError(msg) }, [])
  const edit = useCallback((transform,options={}) => {
    // UI-ITER-R2A #14: a pure viewport change (pan/zoom/fit/locate) is not an edit; it still autosaves, silently.
    const before=docRef.current,raw=transform(before),viewOnly=raw!==before&&Object.keys({...raw,...before}).every(key=>key==='viewport'||raw[key]===before[key]),transformed=cleanGroups(raw);const staleAware=options.history!==false||options.runtime;let next = (staleAware?markStaleDownstream:(_,value)=>value)(before,reconcileReferenceMentions(before,options.history!==false?syncKeyframeGroups(before,transformed,uid):transformed),staleBaselines.current)
    const created=next.groups?.find(group=>group.keyframeNodeId&&!before.groups?.some(old=>old.id===group.id));if(created&&options.history!==false&&rootRef.current){const bounds=groupBounds(created,next.nodes),rect=rootRef.current.getBoundingClientRect(),zoom=Math.min(next.viewport.zoom,(rect.width-80)/bounds.width,(rect.height-120)/bounds.height);next={...next,viewport:{x:rect.width/2-(bounds.x+bounds.width/2)*zoom,y:(rect.height-60)/2-(bounds.y+bounds.height/2)*zoom,zoom:Math.max(.15,zoom)}}}
    if(options.runtime)editHistory.current.rebaseReferenceAssets(before,next)
    // CANVAS-INPUT-20261114 #6: report mentions that followed a reference position (non-blocking panel notice).
    if(options.history!==false){const notes=[];for(const node of next.nodes){const old=before.nodes.find(item=>item.id===node.id);if(!old?.referenceMentions||!node.referenceMentions||old.referenceMentions===node.referenceMentions)continue;const inputs=resolveNodeInputs(node,next.nodes,next.edges).assets;for(const [token,id] of Object.entries(node.referenceMentions)){const was=old.referenceMentions[token];if(was&&was!==id&&!inputs.some(asset=>asset.id===was)){const asset=inputs.find(item=>item.id===id);if(asset)notes.push({nodeId:node.id,key:JSON.stringify(node.referenceMentions),text:`${token} 已改为指向 ${asset.name||'当前参考'}`})}}}if(notes.length)setMentionNotice({nodeId:notes[0].nodeId,key:notes[0].key,text:notes.filter(note=>note.nodeId===notes[0].nodeId).map(note=>note.text).join('；')})}
    if(options.history!==false){editHistory.current.record(before,next,options.key,options.description);setHistoryRevision(value=>value+1)}
    // V140 #14: transient runtime updates (task progress only) change nothing the server stores, so they never trigger a save.
    docRef.current = next; setDoc(next); if(options.transient)return; version.current += 1; if(!viewOnly){contentVersion.current += 1; setSaveState('未保存')}
  }, [])
  const interaction = useCanvasInteractions({rootRef,docRef,edit,drag,space,tool,blocked:ioCount>0 || busy,onGestureStart:()=>editHistory.current.begin(docRef.current),onGestureEnd:()=>{editHistory.current.finish(docRef.current);refreshHistory()},onGestureCancel:()=>{const before=editHistory.current.transaction;editHistory.current.transaction=null;if(before)edit(current=>({...current,nodes:current.nodes.map(node=>{const old=before.nodes.find(n=>n.id===node.id);return old?{...node,x:old.x,y:old.y}:node})}),{history:false})},onContextMenu:openContextMenu,onNodeMenu:openNodeMenu,onNodeDouble:id=>focusZoom(id)})
  // CARD-PROMPT-RESIZE-20261118 (user 11-18): manual node size (node.size = {scale}; absent = automatic). A pointer
  // gesture previews with transient edits (no save, no history) and commits once on release as one undoable edit;
  // double-click / Home restores the automatic size; keyboard steps coalesce into one history entry per node.
  const resizeRef=useRef(null)
  const withNodeSize=(document,id,scale)=>({...document,nodes:document.nodes.map(node=>{if(node.id!==id)return node;const {size,...rest}=node;const value=scale==null?null:clampNodeScale(node,scale);return value==null||value===1?rest:{...rest,size:{scale:value}}})})
  function resizeNode(id,scale,phase){
    const node=docRef.current.nodes.find(item=>item.id===id)
    if(!node||!resizableNode(node))return
    if(phase==='start'){resizeRef.current=null;if(ioRef.current)return;setFocusedGroup(null);setSelectedEdge(null);if(!(interaction.selectedIds.length===1&&interaction.selectedIds[0]===id))interaction.selectSingle(id);return}
    if(phase==='move'){if(ioRef.current||conflictRef.current)return;if(!resizeRef.current)resizeRef.current={id,size:node.size};edit(current=>withNodeSize(current,id,scale),{transient:true,history:false});return}
    const started=resizeRef.current?.id===id?resizeRef.current:null;resizeRef.current=null
    if(started)edit(current=>withNodeSize(current,id,started.size?.scale??null),{transient:true,history:false})
    if(phase==='cancel'||ioRef.current||conflictRef.current)return
    const before=started?started.size?.scale??null:node.size?.scale??null,target=phase==='reset'?null:scale
    if((before??1)===(target==null?1:clampNodeScale(node,target)))return
    edit(current=>withNodeSize(current,id,target),{description:phase==='reset'?`恢复节点“${node.title}”自动大小`:`调整节点“${node.title}”大小`,key:phase==='key'?`size:${id}`:undefined})
  }
  function organizeKeyframes(id){edit(current=>syncKeyframeGroups({...current,nodes:current.nodes.map(node=>node.id===id?{...node,params:{...node.params,video_mode:'reference'}}:node)},current,uid),{description:'整理首尾帧节点组'})}
  function makeGroup(){try{edit(current=>createNodeGroup(current,interaction.selectedIds,uid()),{description:'将选区创建为节点组'})}catch(error){showError(error)}}
  function locateGroup(group){setFocusedGroup(group.id);const bounds=groupBounds(group,docRef.current.nodes),rect=rootRef.current.getBoundingClientRect();if(!bounds)return;interaction.choose(group.nodeIds);edit(current=>({...current,viewport:{...current.viewport,x:rect.width/2-(bounds.x+bounds.width/2)*current.viewport.zoom,y:rect.height/2-(bounds.y+bounds.height/2)*current.viewport.zoom}}),{history:false})}
  function ungroup(group){edit(current=>({...current,groups:(current.groups||[]).filter(item=>item.id!==group.id)}),{description:`解组“${group.title}”（保留节点）`})}
  function renameGroup(group){setGroupDraft({id:group.id,title:group.title})}
  function copyGroup(group){try{const result=pasteCanvasSelection(docRef.current,copyCanvasSelection(docRef.current,group.nodeIds,workflowRef.current.id),workflowRef.current.id,uid);edit(()=>result.document);interaction.choose(result.ids)}catch(error){showError(error)}}
  const [groupDraft,setGroupDraft]=useState(null),[mentionNotice,setMentionNotice]=useState(null)
  const [focusedGroup,setFocusedGroup]=useState(null)
  // CANVAS-LAYOUT-1-20261117: right properties panel preferences (per browser) and the prompt editors' runtime state.
  const panelToggle=useRef(null),chromeKeys=useRef({}),toolbarRef=useRef(null),railRef=useRef(null),toolsRef=useRef(null)
  const [imageEditing,setImageEditing]=useState(null),[toolsLeft,setToolsLeft]=useState(null),[railPanelPx,setRailPanelPx]=useState(0)
  const [cardGenerate,setCardGenerate]=useState(null)
  const panelPrefs=usePropertiesPanelPrefs(),[promptDialog,setPromptDialog]=useState(null),[promptFocus,setPromptFocus]=useState({id:null,n:0})
  // CANVAS-LAYOUT-2-WIRE-20261118: left icon rail + pop-out panel (spec 2.2). Pinning keeps the canvas >= 640 wide
  // (spec 1.5): the right panel is first pressed back towards its minimum 288, otherwise pinning is refused.
  const railPanelWidth=()=>{const shell=typeof document!=='undefined'&&document.querySelector('.canvas-studio .cv-rail-panel-shell');return shell?shell.getBoundingClientRect().width:railPanelDefaultWidth(window.innerWidth)}
  const rightPanelWidth=()=>panelPrefs.collapsed?24:panelPrefs.width
  const pinRefusal=()=>!rail?.pinned&&!pinAllowed({viewport:window.innerWidth,panel:railPanelWidth(),rightPanel:panelPrefs.collapsed?24:RIGHT_PANEL_MIN})?PIN_REFUSED_MESSAGE:''
  const rail=useCanvasRail({canPin:()=>{
    const viewport=window.innerWidth,panel=railPanelWidth()
    if(pinAllowed({viewport,panel,rightPanel:rightPanelWidth()}))return null
    if(panelPrefs.collapsed||!pinAllowed({viewport,panel,rightPanel:RIGHT_PANEL_MIN}))return PIN_REFUSED_MESSAGE
    panelPrefs.setWidth(Math.max(RIGHT_PANEL_MIN,viewport-RAIL_WIDTH-panel-PIN_MIN_CANVAS));return null
  }})
  railRef.current=rail
  const togglePin=()=>{const message=rail.togglePin();if(message)notify?.(message,'info')}
  const [minimapOpen,setMinimapOpen]=useState(()=>readMinimapPreference(typeof window==='undefined'?1440:window.innerWidth-RAIL_WIDTH-panelPrefs.width))
  const [,setGestureTick]=useState(0)
  const selected=interaction.selected,setSelected=(id,append=false)=>{setFocusedGroup(null);interaction.selectSingle(id,append)}
  const locateNode=id=>{setFocusedGroup(null);interaction.locate(id)}
  // The version popover belongs to one selected node: selecting something else closes it.
  useEffect(()=>{if(historyNode&&selected!==historyNode)setHistoryNode(null)},[selected,historyNode])
  // NODE-ECHO-20261115: task number → task center of that tool (app shell listens); fallback names the id.
  const openTaskCenter=(task,type)=>{if(task?.id&&!requestTaskCenter({taskId:task.id,type}))notify?.(`请到${{image:'图片',video:'视频',audio:'音频'}[type]||''}工具的任务中心按编号 #${task.id} 查找该任务`,'info')}
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

  // FIX-B2-20261114 #2: saves run one at a time through `queue`; when idle, the request starts synchronously
  // so a page-exit flush ({keepalive:true}) is on the wire before pagehide returns. keepaliveVersion is the
  // version a keepalive request in flight already carries.
  const queuedSaves = useRef(0), keepaliveVersion = useRef(-1)
  // FIX-B2 rework (B2-FLUSH-1/2): lastSaveFailed keeps the leave prompt after a failed save; backupDraft keeps
  // unsaved edits in localStorage so a keepalive PUT that fails or gets 409 after unload can be restored later.
  const lastSaveFailed = useRef(false)
  const backupDraft = useCallback(() => {
    const current = workflowRef.current
    if (!current || contentVersion.current === savedContentVersion.current) return
    writeDraft({ workflowId: current.id, baseRevision: current.revision, title: titleRef.current || '未命名画布', document: docRef.current, known: serverDocRef.current })
  }, [])
  const save = useCallback((options = {}) => {
    const run = async () => {
      const currentWorkflow = workflowRef.current
      if (!currentWorkflow || savedVersion.current === version.current) return currentWorkflow
      if (conflictRef.current) throw new Error('画布有版本冲突，请先保留本地内容并重新载入。')
      const savingVersion = version.current, savingContent = contentVersion.current, silent = savingContent === savedContentVersion.current
      const payload = { title: titleRef.current || '未命名画布', document: sanitizeDocumentTasks(serializableDocument(docRef.current)), revision: currentWorkflow.revision }
      const body = options.keepalive ? JSON.stringify(payload) : null, keepalive = !!body && keepaliveBodyFits(body)
      if (mounted.current && !silent) setSaveState('保存中…')
      if (keepalive) keepaliveVersion.current = savingVersion
      try {
        const result = keepalive ? await saveCanvasWorkflowKeepalive(currentWorkflow.id, body) : await saveCanvasWorkflow(currentWorkflow.id, payload)
        if (workflowRef.current?.id === currentWorkflow.id) {
          // Contract C: the server merged write-backs into this save. Take the returned
          // fields, keep input typed after the PUT was sent (no undo step, not "未保存").
          if (result.merged && result.document) {
            const merged = mergeSavedDocument({ sent: payload.document, returned: result.document, local: docRef.current })
            if (merged !== docRef.current) edit(() => merged, { history: false, runtime: true, transient: true })
          }
          serverDocRef.current = result.merged && result.document ? result.document : payload.document
          const { merged: _merged, ...stored } = result
          workflowRef.current = { ...currentWorkflow, ...stored, document: docRef.current }
          savedVersion.current = savingVersion; savedContentVersion.current = savingContent; lastSaveFailed.current = false
          if (contentVersion.current === savingContent) clearDraft(currentWorkflow.id)
          if (mounted.current) {
            setWorkflow(workflowRef.current)
            setWorkflows(items => items.map(item => item.id === stored.id ? { ...item, ...stored } : item))
            if (!silent) setSaveState(contentVersion.current === savingContent ? '已保存' : '未保存')
          }
        }
        return result
      } catch (failure) {
        if (failure?.status === 409 || failure?.response?.status === 409) { conflictRef.current = true; if (mounted.current) setConflict(true) }
        if (workflowRef.current?.id === currentWorkflow.id) { lastSaveFailed.current = true; backupDraft() }
        if (mounted.current) setSaveState('保存失败')
        throw failure
      } finally { if (keepaliveVersion.current === savingVersion) keepaliveVersion.current = -1 }
    }
    const operation = queuedSaves.current ? queue.current.catch(() => {}).then(run) : run()
    queuedSaves.current += 1; const settle = () => { queuedSaves.current -= 1 }; operation.then(settle, settle)
    queue.current = operation
    return operation
  }, [backupDraft])
  // Page exit (pagehide / tab hidden / beforeunload): back up and send unsaved edits now. Returns true when the
  // current version is saved or carried by a keepalive request in flight; false when it could not be guaranteed
  // (conflict, body too large, a save in flight, or the last save failed — then the leave prompt stays).
  const flushOnExit = useCallback(() => {
    backupDraft()
    if (!workflowRef.current || conflictRef.current) return savedVersion.current === version.current
    if (savedVersion.current === version.current) return true
    const failed = lastSaveFailed.current
    if (keepaliveVersion.current !== version.current) save({ keepalive: true }).catch(() => {})
    return !failed && keepaliveVersion.current === version.current
  }, [save, backupDraft])

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
    workflowRef.current = value; docRef.current = normalized; titleRef.current = value.title; staleBaselines.current = new Map(); serverDocRef.current = document; syncRetry.current = new Map()
    writeLastLocation({ projectId: value.project_id ?? projectIdRef.current, workflowId: value.id })
    version.current = hadSubmitting ? 1 : 0; savedVersion.current = 0; contentVersion.current = version.current; savedContentVersion.current = 0; conflictRef.current = false
    setOverlapCount(countOverlappingUnits(normalized)); setWorkflow(value); setDoc(normalized); setTitle(value.title); setSelected(null); setSelectedEdge(null); setConnection(null); setContextMenu(null); setNodeMenu(null);setHistoryNode(null);setPreview(null); setConflict(false); setSaveState(hadSubmitting ? '提交待核查' : '已保存')
    lastSaveFailed.current = false; setDraftOffer(null); checkDraftRef.current?.(value, 0)
  }, [])
  // FIX-B2 rework: compare a local draft with the opened version. Contained → cleared silently. Same revision as
  // the draft's base → its keepalive PUT may still be landing, so re-read twice (800ms apart) while this window
  // has no edits. Otherwise offer restore / discard.
  const checkDraftRef = useRef(null)
  checkDraftRef.current = (value, attempt) => {
    const draft = readDraft(value.id)
    if (!draft) return
    if (draftIncluded(draft, value)) { clearDraft(value.id); return }
    const current = () => workflowRef.current?.id === value.id && workflowRef.current?.revision === value.revision
    if (value.revision === draft.baseRevision && attempt < 2) {
      setTimeout(async () => {
        if (!mounted.current || !current()) return
        let fresh = null
        try { fresh = await getCanvasWorkflow(value.id) } catch { fresh = null }
        if (!mounted.current || !current()) return
        if (fresh && fresh.revision !== value.revision && version.current === savedVersion.current && !conflictRef.current) installWorkflow(fresh)
        else checkDraftRef.current(value, attempt + 1)
      }, 800)
      return
    }
    if (mounted.current && current()) setDraftOffer({ draft, newer: value.revision !== draft.baseRevision })
  }
  function restoreDraft() {
    const offer = draftOffer
    if (!offer || workflowRef.current?.id !== offer.draft.workflowId) { setDraftOffer(null); return }
    const { draft } = offer
    titleRef.current = draft.title || titleRef.current; setTitle(titleRef.current)
    // DRAFT-MERGE-FIX-20261114: merge onto the current document (opened server version + results already
    // taken from task-sync); written-back task/versions/selection come from the server (mergeDraftDocument).
    // Results written back after this point reach the next PUT through contract C (stale base → merged).
    edit(current => ({ ...current, ...mergeDraftDocument(draft, current).document, viewport: current.viewport }), { description: '恢复本地未保存修改' })
    setDraftOffer(null)
  }
  function discardDraft() { if (draftOffer) clearDraft(draftOffer.draft.workflowId); setDraftOffer(null) }

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
            // V140 #2 + WINDOW-PROJECT-20261114: reopen this tab's (else this browser's) last project/canvas; gone or unreadable falls back to the server's most recent with a notice.
            const found = await resolveCanvasLocation({ projects: listed.value, last: readRememberedLocation(), listWorkflows: listCanvasWorkflows, getWorkflow: getCanvasWorkflow })
            if (!alive) return
            projectIdRef.current = found.projectId; setProjectId(found.projectId); setWorkflows(found.workflows)
            if (found.workflow) installWorkflow(found.workflow)
            if (found.missed) notify?.(MISSED_LOCATION_MESSAGE, 'info')
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
  // Spec 3.2: bottom tools centred on the canvas, but never left of the bottom-left cluster's right edge + 12.
  useLayoutEffect(() => {
    const tools=toolsRef.current,bar=rootRef.current?.querySelector('.cv-viewport-bar')
    if(!tools||!bar)return
    const surface=rootRef.current.getBoundingClientRect(),width=tools.getBoundingClientRect().width,clusterRight=bar.getBoundingClientRect().right-surface.left
    const centred=surface.width/2-width/2,left=Math.max(centred,clusterRight+12),zoom=Number(getComputedStyle(tools).zoom)||1
    const next=left>centred+.5?Math.round(left/zoom):null
    // Only set on a real change: an unconditional setState in this every-render layout effect counts as a nested
    // update and, together with other synchronous re-renders, tripped React's update-depth limit (#185).
    if(next!==toolsLeft)setToolsLeft(next)
  })
  useEffect(() => {
    if (!providerRevision) return
    let alive = true
    getCanvasCapabilities().then(value => { if (alive) setCapabilities(value) }).catch(showError)
    return () => { alive = false }
  }, [providerRevision, showError])

  // UI-ITER-R2A #2: node sizes follow measured media; re-render when a size arrives and measure off-screen media.
  const mediaSizeRevision = useSyncExternalStore(subscribeMediaSizes, mediaSizesVersion)
  useEffect(() => { preloadMediaSizes(doc.nodes.map(node => node.asset).filter(Boolean)) }, [doc.nodes])

  useEffect(() => {
    if (!workflow || conflict || version.current === savedVersion.current) return
    const timeout = setTimeout(() => save().catch(showError), 800)
    return () => clearTimeout(timeout)
  }, [doc, title, workflow?.id, conflict, save, showError])

  useEffect(() => {
    // FIX-B2-20261114 #2: leaving/hiding the page flushes unsaved edits (keepalive). The leave prompt only
    // remains when the flush cannot carry them (version conflict, body too large for keepalive).
    const beforeUnload = event => { if (contentVersion.current !== savedContentVersion.current && !flushOnExit()) { event.preventDefault(); event.returnValue = '' } }
    const pageHide = () => { flushOnExit() }
    const hidden = () => { if (document.visibilityState === 'hidden') flushOnExit() }
    const keydown = event => {
      const target = event.target
      // Dialogs own their keyboard interaction; canvas shortcuts must not leak through.
      if (event.defaultPrevented || target.closest?.('dialog, [role="dialog"], [role="alertdialog"], .cv-studio-overlay')) return
      // FIX-B2 #3: an open native select reports its <option> as the target; Esc there only closes the list.
      const editable = ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable || !!target.closest?.('select')
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save().catch(showError); return }
      // CANVAS-LAYOUT-1-20261117: Ctrl/⌘+. collapses / expands the right properties panel (works from any field).
      if ((event.ctrlKey || event.metaKey) && event.key === '.' && !event.altKey && !event.shiftKey) { event.preventDefault(); panelToggle.current?.(); return }
      // CANVAS-LAYOUT-2-WIRE-20261118 (spec 1.4): F6 / Shift+F6 cycle rail → open panel → canvas → properties panel.
      if (event.key === 'F6' && !event.ctrlKey && !event.metaKey && !event.altKey) { event.preventDefault(); chromeKeys.current.cycle?.(event.shiftKey); return }
      if (editable) return
      const inCanvas=target.closest?.('.cv-surface')
      if(inCanvas && !target.closest?.('[role=menu],video,audio') && !rootRef.current?.closest('.canvas-studio')?.querySelector('[role=dialog],.cv-studio-overlay')) {
        const key=event.key.toLowerCase(),modifier=event.ctrlKey||event.metaKey
        if(modifier&&key==='v'&&!event.shiftKey&&!event.altKey&&!window.getSelection()?.toString()){
          // #1: let the browser fire "paste" so clipboard files can be read; if no paste event follows, paste copied nodes.
          pendingKeyPaste.current=true;setTimeout(()=>{if(pendingKeyPaste.current){pendingKeyPaste.current=false;editCommands.current?.handle('v')}},0);return
        }
        if(modifier&&['z','y','c'].includes(key)&&!window.getSelection()?.toString()){
          if(editCommands.current?.handle(key,event.shiftKey)){event.preventDefault();return}
        }
        // #3: Delete/Backspace remove the selection; panels, players and popovers keep their own keys.
        if((event.key==='Delete'||event.key==='Backspace')&&!modifier&&!event.altKey&&!target.closest?.('.cv-properties,.cv-media-player,.cv-history-popover,.cv-context-menu')){
          if(editCommands.current?.remove()){event.preventDefault();return}
        }
        if(event.key==='?'){event.preventDefault();setShortcutsOpen(true);return}
        // Spec 3.3: Alt+T moves focus into the selected image node's toolbar (Esc there returns to the node).
        if(event.altKey&&!modifier&&!event.shiftKey&&event.code==='KeyT'&&chromeKeys.current.toolbar?.()){event.preventDefault();return}
      }
      if (event.code === 'Space') {
        // Preserve native Space activation/playback for focused interactive elements.
        if (target.closest?.('button, a, summary, video, audio, [role="button"], [role="checkbox"], [role="switch"]')) return
        event.preventDefault(); space.current = true
      }
      if (event.key === 'Escape') { if(portDragRef.current){portDragRef.current=null;setPortDrag(null);return} setConnection(null); setSelectedEdge(null); setSelected(null) }
    }
    const paste = event => {
      const target = event.target
      if (event.defaultPrevented || target.closest?.('dialog, [role="dialog"], [role="alertdialog"], .cv-studio-overlay')) { pendingKeyPaste.current = false; return }
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable) { pendingKeyPaste.current = false; return }
      if (!target.closest?.('.cv-surface') || target.closest?.('[role=menu],video,audio,.cv-properties') || rootRef.current?.closest('.canvas-studio')?.querySelector('[role=dialog],.cv-studio-overlay')) { pendingKeyPaste.current = false; return }
      pendingKeyPaste.current = false; event.preventDefault()
      const files = clipboardFiles(event.clipboardData)
      // Files win over copied nodes; a text-only clipboard falls back to copied nodes (text itself is never pasted).
      if (files.length) editCommands.current?.pasteFiles(files); else editCommands.current?.handle('v')
    }
    const keyup = event => { if (event.code === 'Space') space.current = false }
    const blur = () => { space.current = false; editCommands.current?.cancel() }
    window.addEventListener('beforeunload', beforeUnload); window.addEventListener('pagehide', pageHide); document.addEventListener('visibilitychange', hidden); window.addEventListener('keydown', keydown); window.addEventListener('paste', paste); window.addEventListener('keyup', keyup); window.addEventListener('blur', blur)
    return () => { window.removeEventListener('beforeunload', beforeUnload); window.removeEventListener('pagehide', pageHide); document.removeEventListener('visibilitychange', hidden); window.removeEventListener('keydown', keydown); window.removeEventListener('paste', paste); window.removeEventListener('keyup', keyup); window.removeEventListener('blur', blur) }
  }, [save, showError, flushOnExit])

  // D: with no unsaved local change, take the server revision after a write-back.
  // Revisions between our base and it may include another window's real save; adopt
  // only when the server document equals ours, otherwise keep the base so the next
  // PUT is merged (write-backs only) or conflicts (409) as before. Runs in the save queue.
  const adoptServerRevision = useCallback((workflowId, revision) => {
    const operation = queue.current.catch(() => {}).then(async () => {
      const clean = () => workflowRef.current?.id === workflowId && !conflictRef.current && version.current === savedVersion.current
      if (!clean() || workflowRef.current.revision >= revision) return
      const atVersion = version.current, fresh = await getCanvasWorkflow(workflowId)
      if (!clean() || version.current !== atVersion || fresh.revision <= workflowRef.current.revision) return
      if ((fresh.title || '') !== (titleRef.current || '') || !sameServerDocument(docRef.current, fresh.document)) return
      serverDocRef.current = fresh.document
      const { document: _document, ...stored } = fresh
      workflowRef.current = { ...workflowRef.current, ...stored, document: docRef.current }
      if (mounted.current) { setWorkflow(workflowRef.current); setWorkflows(items => items.map(item => item.id === stored.id ? { ...item, ...stored } : item)) }
    }).catch(() => {})
    queue.current = operation
    return operation
  }, [])

  // Poll active tasks with one batch status request per cycle (100 ids each).
  // Hidden pages pause; returning to the foreground polls immediately.
  // Unchanged results neither edit nor save the canvas.
  useEffect(() => {
    let alive = true, lastTick = 0
    const tick = async () => {
      if (!alive || polling.current || conflictRef.current || !workflowRef.current) return
      if (document.hidden && Date.now() - lastTick < HIDDEN_POLL_MS) return
      lastTick = Date.now()
      const currentWorkflowId = workflowRef.current.id
      const isCurrent = () => alive && mounted.current && workflowRef.current?.id === currentWorkflowId
      polling.current = true
      try {
        const result = await collectTaskUpdates({ document: docRef.current, getDocument: () => docRef.current, isCurrent,
          fetchStatuses: async ids => noteActiveTasks(await getTaskStatuses(ids), watchedTasks.current), fetchDetail: getTaskDetail })
        if (result.stale || !isCurrent()) return
        // Out-of-vocabulary statuses are never written; the node keeps its previous state.
        setStatusAnomalies(result.anomalies.size ? { workflowId: currentWorkflowId, nodes: result.anomalies } : null)
        // Status words and progress only update the interface (no save, no revision).
        if (result.patches.size) edit(current => applyTaskUpdates(current, result.patches), { history: false, runtime: true, transient: true })
        let failed = result.failed
        const now = Date.now(), due = new Map([...result.terminal].filter(([, task]) => (syncRetry.current.get(task.id) || 0) <= now))
        failed += result.terminal.size - due.size
        if (due.size) {
          // CANVAS-WRITEBACK-20261114 D: the server writes results back; fetch its node fields.
          let synced = null
          try { synced = await syncCanvasTasks(currentWorkflowId, [...due.values()].map(task => task.id)) } catch { synced = null }
          if (!isCurrent()) return
          if (!synced) { failed += due.size; for (const task of due.values()) syncRetry.current.set(task.id, now + 30000) }
          else {
            const { patches, missing } = taskSyncPatches({ document: docRef.current, serverNodes: synced.nodes, terminal: due, known: serverDocRef.current })
            for (const nodeId of missing) syncRetry.current.set(due.get(nodeId).id, now + 30000)
            failed += missing.length
            const unknown = [...patches.values()].filter(patch => patch.task.resultUnknown).map(patch => patch.task.id)
            if (unknown.length) setUnknownTasks(current => new Set([...current, ...unknown]))
            if (patches.size) edit(current => applyTaskUpdates(current, patches), { history: false, runtime: true, transient: true })
            // V2-FIX-20261117 F4: written-back results are new library media (生成历史) → refresh the sidebar tree and counts.
            if ([...patches.values()].some(patch => patch.additions?.length || patch.task.status === 'succeeded')) setMediaRefresh(value => value + 1)
            // TASK-DONE-NOTIFY-20261114: remind from the written-back terminal state only.
            if (patches.size) remindRef.current?.(completionNotices({ patches, document: docRef.current, workflowId: currentWorkflowId, notified: notifiedTasks.current, eligible: watchedTasks.current }))
            if (Number.isInteger(synced.revision) && synced.revision > (workflowRef.current?.revision || 0)) adoptServerRevision(currentWorkflowId, synced.revision)
          }
        }
        setPollWarning(failed ? { workflowId: currentWorkflowId, count: failed } : null)
      } catch { /* the next cycle retries; per-node failures are counted above */ }
      finally { polling.current = false }
    }
    const timer = setInterval(tick, 3000)
    const visible = () => { if (!document.hidden) tick() }
    document.addEventListener('visibilitychange', visible)
    return () => { alive = false; clearInterval(timer); document.removeEventListener('visibilitychange', visible) }
  }, [edit, adoptServerRevision])

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

  // TASK-DONE-NOTIFY-20261114: in-page reminders, unread count in the tab title, optional system notifications.
  const systemOn=systemEnabled({setting:systemSetting,permission})
  function locateNotice(notice){
    setDoneNotices(current=>current.filter(item=>item.key!==notice.key))
    const node=docRef.current.nodes.find(item=>item.id===notice.nodeId),rect=rootRef.current?.getBoundingClientRect()
    if(workflowRef.current?.id!==notice.workflowId||!node||!rect)return
    // Like the double-click locate, but the zoom level is kept: only pan the node to the centre and select it.
    stopViewAnimation();setFocusedGroup(null);interaction.selectSingle(node.id);rootRef.current.focus({preventScroll:true})
    const {width,height}=nodeGeometry(node)
    edit(current=>({...current,viewport:{...current.viewport,x:rect.width/2-(node.x+width/2)*current.viewport.zoom,y:rect.height/2-(node.y+height/2)*current.viewport.zoom}}),{history:false})
  }
  function showTitleCount(){if(titleBase.current===null)titleBase.current=baseTitle(document.title);document.title=titleWithCount(titleBase.current,unreadDone.current)}
  remindRef.current=notices=>{
    if(!notices.length||!mounted.current)return
    setDoneNotices(current=>mergeNotices(current,notices))
    if(!pageInForeground()){
      unreadDone.current+=notices.length;showTitleCount()
      if(systemOn)for(const notice of notices){try{const item=new Notification('Ink Traces',{body:notice.text,tag:`ink-task-${notice.taskId}`});item.onclick=()=>{try{window.focus()}catch{/* ignore */}locateNotice(notice);item.close()}}catch{/* notifications unavailable in this context */}}
    }
    if(shouldAskSystem({setting:systemSetting,permission:notificationPermission()}))setAskSystem(true)
  }
  useEffect(()=>{
    const clear=()=>{if(!pageInForeground()||!unreadDone.current)return;unreadDone.current=0;showTitleCount()}
    document.addEventListener('visibilitychange',clear);window.addEventListener('focus',clear)
    return()=>{document.removeEventListener('visibilitychange',clear);window.removeEventListener('focus',clear);if(titleBase.current!==null)document.title=titleBase.current}
  },[])
  useEffect(()=>{setDoneNotices([])},[workflow?.id])
  function chooseSystem(value){writeSystemSetting(value);setSystemSetting(value)}
  async function enableSystem(){
    setAskSystem(false)
    const current=notificationPermission()
    if(current==='unsupported'){notify?.('当前浏览器不支持系统通知','error');return}
    if(current==='denied'){setPermission(current);chooseSystem('off');notify?.('浏览器已阻止本站通知，请在浏览器的网站设置中允许后再开启','error');return}
    let result=current
    if(current==='default'){try{result=await Notification.requestPermission()}catch{result=notificationPermission()}}
    setPermission(result)
    if(result==='granted'){chooseSystem('on');notify?.('已开启系统完成通知','success')}
    else{chooseSystem('off');notify?.('浏览器未允许通知，已保持关闭','error')}
  }
  function declineSystem(){setAskSystem(false);chooseSystem('off')}

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
    // FIX-B2 #3: without a requested point, the free slot is searched inside the visible area first.
    const view=docRef.current.viewport,margin=24/view.zoom,visible={x:-view.x/view.zoom+margin,y:-view.y/view.zoom+margin,width:rect.width/view.zoom-2*margin,height:(rect.height-FOCUS_BOTTOM_BAR)/view.zoom-2*margin}
    const start={x:middle.x-geometry.width/2,y:middle.y-geometry.height/2}
    const position = point ? freeNodePosition(docRef.current, {type}, point) : freeNodePositionInView(docRef.current, {type}, start, visible)
    const providerSelection = defaultProviderSelection(capabilities, type, providerPreferences.current), provider = selectedProvider(capabilities, providerSelection, type)
    const node = { id: uid(), type, title: asset?.name || labels[type], x: position.x, y: position.y, text: '', providerSelection, params: { model: provider?.model || provider?.models?.[0]?.id || '', ratio: type === 'image' ? '1:1' : '16:9', resolution: type === 'image' ? '1K' : type === 'video' ? defaultVideoResolution(provider?.model || provider?.models?.[0]?.id, provider?.models) : '720p', duration: 5 }, asset, candidates: asset ? [asset] : [], selectedCandidateId: asset?.id || null, task: null }
    edit(current => ({ ...current, nodes: [...current.nodes, node] })); setSelected(node.id); setSelectedEdge(null);requestAnimationFrame(()=>interaction.reveal(node.id))
    return node
  }
  function addAssetNodes(assets, targetId, point, titles = null) {
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
        source = {id:uid(),type:'asset',title:titles?.get(asset.id) || asset.name || '素材',x,y,text:'',params:{},asset,candidates:[asset],selectedCandidateId:asset.id,task:null};nodes.push(source)
      }
      added.push(source)
      if (target && !edges.some(edge => edge.source===source.id && edge.target===target.id)) edges.push({id:uid(),source:source.id,target:target.id})
    }
    if(nodes.length>500||edges.length>2000)throw new Error('添加会超过画布上限（500节点／2000连线），请减少素材数量')
    if(added.some(node=>Math.abs(node.x)>1e6||Math.abs(node.y)>1e6))throw new Error('添加位置超出画布坐标范围，请先平移视口')
    edit(() => ({...current,nodes,edges}));setSelected(target?.id || added[0]?.id || null);setSelectedEdge(null)
    return {created:nodes.length-current.nodes.length,reused:unique.length-(nodes.length-current.nodes.length)}
  }
  // LIBRARY-GLOBAL S5: library media are referenced directly (media id); nothing is copied into the canvas.
  // S7: `source` may be an async loader (folder pages). The owner project/canvas is captured and the I/O lock
  // (which disables project/canvas switching) is taken before reading, so a slow read never writes elsewhere.
  async function addProjectAssets(source,point=null,targetId=null,check=null) {
    if(ioRef.current||navigationRef.current||generationLocks.current.size)throw new Error('请等待当前操作完成后再添加素材')
    let projectOwner=projectIdRef.current,owner=workflowRef.current?.id||null,locked=true
    const switched=()=>projectIdRef.current!==projectOwner||(workflowRef.current?.id||null)!==owner
    const unlock=()=>{if(locked){locked=false;ioRef.current--;if(mounted.current)setIoCount(ioRef.current)}}
    ioRef.current++;setIoCount(ioRef.current)
    try {
      const mediaAssets=typeof source==='function'?await source():source
      if(switched())throw new Error('原画布已切换，未添加到其他画布')
      const assets=[...new Map(mediaAssets.filter(isMediaAsset).map(asset=>[asset.id,asset])).values()]
      if(!assets.length)throw new Error('文件夹中没有可添加的素材')
      const deleted=assets.find(asset=>isDeletedMedia(asset.id));if(deleted)throw new Error(`素材“${deleted.name}”已在素材库中删除，未添加`)
      check?.(mediaAssets)
      if(docRef.current.nodes.length+assets.length>500)throw new Error('所选素材会超过画布500节点上限，请选择更少的素材')
      if(!workflowRef.current){
        // newWorkflow refuses while I/O is locked; release and re-take synchronously around it.
        unlock();if(!await newWorkflow())throw new Error('无法创建画布，请重试')
        if(ioRef.current||navigationRef.current)throw new Error('请等待当前操作完成后再添加素材')
        projectOwner=projectIdRef.current;owner=workflowRef.current.id;locked=true;ioRef.current++;setIoCount(ioRef.current)
      }
      await Promise.race([preloadMediaSizes(assets),new Promise(r=>setTimeout(r,2500))])
      if(switched())throw new Error('原画布已切换，未添加到其他画布')
      if(targetId&&!docRef.current.nodes.some(n=>n.id===targetId))throw new Error('目标节点已不存在，未添加参考')
      const result=addAssetNodes(assets,targetId,point);await save();notify?.(targetId?`已追加 ${assets.length} 个参考到节点末尾`:`已添加 ${result.created} 个素材节点${result.reused?`，复用 ${result.reused} 个已有节点`:''}`,'success')
    }finally{unlock()}
  }
  // Drag from the asset tree (or its keyboard menu) onto a generation node:
  // append as references, one undo step; type/count limits refuse with a reason.
  async function addProjectReferences(source,kinds,targetId){
    const check=items=>{
      const target=docRef.current.nodes.find(n=>n.id===targetId)
      const issue=referenceDropError(target,target?[...resolveNodeInputs(target,docRef.current.nodes,docRef.current.edges).assets,...pendingReferenceEdges(target,docRef.current.nodes,docRef.current.edges).map(item=>({kind:item.kind}))]:[],kinds||items.map(asset=>asset.kind),target&&nodeProvider(capabilities,target))
      if(issue)throw new Error(`${issue}；未添加参考`)
    }
    if(typeof source!=='function')check(source)
    await addProjectAssets(source,null,targetId,check)
  }
  function dropProjectAssets(event){
    let payload;try{payload=JSON.parse(event.dataTransfer.getData(PROJECT_ASSET_DRAG))}catch{return}
    if(!Array.isArray(payload?.media)||!payload.media.length||!payload.media.every(isMediaAsset)){showError('只能拖入素材库中的素材');return}
    const targetElement=event.target.closest?.('[data-node-id]'),target=targetElement&&docRef.current.nodes.find(n=>n.id===targetElement.dataset.nodeId)
    const run=target&&['image','video','audio'].includes(target.type)?addProjectReferences(payload.media,payload.media.map(asset=>asset.kind),target.id):addProjectAssets(payload.media,worldPoint(event.clientX,event.clientY))
    run.catch(showError)
  }
  // User 11-17 Q2: the explicit "移除超出的 K 个参考" (one undo step); nothing is removed automatically.
  function removeOverLimit(id) {
    const node = docRef.current.nodes.find(item => item.id === id)
    if (!node) return
    try { const result = removeOverLimitReferences(docRef.current, id, {provider:nodeProvider(capabilities,node)}); if (!result.removed.length) return; edit(() => result.document, {description:`移除超出上限的 ${result.removed.length} 个参考`}); notify?.(`已移除 ${result.removed.length} 个超出上限的参考（${canvasModifier()}+Z 可撤销）`,'success') } catch (failure) { showError(failure) }
  }
  function clearReferences(id) { edit(current => ({...current,nodes:current.nodes.map(node => node.id===id?{...node,referenceAssets:[],referenceGroups:[]}:node),edges:current.edges.filter(edge=>edge.target!==id)})) }
  function closeContextMenu() {setContextMenu(null);rootRef.current?.focus()}
  function openContextMenu(event) {
    if(event.target.closest('.cv-node,.cv-properties,.cv-tools,.cv-viewport-tools,.cv-node-toolbar,.cv-rail,.cv-rail-panel,.cv-context-menu,.cv-alert')) return
    event.preventDefault(); const rect=rootRef.current.getBoundingClientRect()
    const x=event.clientX || rect.left+rect.width/2,y=event.clientY || rect.top+rect.height/2
    setContextMenu({x:x-rect.left,y:y-rect.top,point:worldPoint(x,y)});setSelected(null);setSelectedEdge(null)
  }
  function deleteNode(id) {
    const node = docRef.current.nodes.find(item => item.id === id)
    if (ioRef.current || generationLocks.current.has(id) || isBusyTaskStatus(node?.task?.status)) return
    edit(current => ({ ...current, nodes: current.nodes.filter(node => node.id !== id), edges: current.edges.filter(edge => edge.source !== id && edge.target !== id) })); setSelected(null); setConnection(null)
  }
  // #3: keyboard delete of the whole selection as one undo step; busy/locked nodes stay and are reported.
  function deleteNodes(ids) {
    const current = docRef.current, existing = ids.filter(id => current.nodes.some(node => node.id === id))
    if (!existing.length) return false
    if (ioRef.current || navigationRef.current || conflictRef.current) { showError('请等待当前操作完成后再删除节点'); return true }
    const kept = existing.filter(id => generationLocks.current.has(id) || isBusyTaskStatus(current.nodes.find(node => node.id === id)?.task?.status))
    const removed = new Set(existing.filter(id => !kept.includes(id)))
    if (removed.size) edit(doc => ({ ...doc, nodes: doc.nodes.filter(node => !removed.has(node.id)), edges: doc.edges.filter(edge => !removed.has(edge.source) && !removed.has(edge.target)) }), { description: `删除 ${removed.size} 个节点` })
    setFocusedGroup(null); interaction.choose(kept); setSelectedEdge(null); setConnection(null); setNodeMenu(null)
    if (kept.length) showError(`${kept.length} 个生成中的节点未删除`); else setError('')
    rootRef.current?.focus({ preventScroll: true })
    return true
  }
  function deleteEdge(id) {
    if (!docRef.current.edges.some(edge => edge.id === id)) { setSelectedEdge(null); return false }
    edit(current => ({ ...current, edges: current.edges.filter(edge => edge.id !== id) }), { description: '移除连接' }); setSelectedEdge(null); rootRef.current?.focus({ preventScroll: true }); return true
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
  },remove:()=>selectedEdge?deleteEdge(selectedEdge):deleteNodes(interaction.selectedIds),
  pasteFiles:files=>{
    if(ioRef.current||navigationRef.current||conflictRef.current){showError('请等待当前操作完成后再粘贴素材');return}
    const pointer=lastPointer.current,point=pointer?worldPoint(pointer.x,pointer.y):null
    importFiles(files,point,null,'paste').catch?.(showError)
  }}
  // Shared by click-then-click and drag-to-connect (#2): same rules and messages.
  // Why `sourceId` cannot be connected into `id` (self, type, cycle, reference limit incl. pending — user 11-17), or ''.
  function connectionRefusal(sourceId, id, current = docRef.current) {
    if (sourceId === id) return '不能将节点连接到自身。'
    const source = current.nodes.find(node => node.id === sourceId), target = current.nodes.find(node => node.id === id)
    if (!canConnect(source,target)) return '素材类型不兼容：图像仅接受图片，视频接受图片/视频/音频，音频接受图片/音频。'
    if (current.edges.some(edge => edge.source === sourceId && edge.target === id)) return ''
    const reachable = new Set([id]); let changed = true
    while (changed) { changed = false; for (const edge of current.edges) if (reachable.has(edge.source) && !reachable.has(edge.target)) { reachable.add(edge.target); changed = true } }
    if (reachable.has(sourceId)) return '该连接会形成循环，请调整连接方向。'
    const kind = mediaKind(source)
    // Legacy text sources keep their old behaviour (user 11-17 Q3: no new text ports); media follow the port limits.
    const limit = PORT_KINDS.includes(kind) && source.asset?.id && resolveNodeInputs(target,current.nodes,current.edges).assets.some(asset => asset.id === source.asset.id) ? null : PORT_KINDS.includes(kind) ? portAddError(target,current.nodes,current.edges,kind,{provider:nodeProvider(capabilities,target)}) : null
    return limit ? `${limit}；未接入参考` : ''
  }
  // Shared by click-then-click, drag-to-connect and keyboard (#2): same rules and messages. A drop on occupied
  // port N of the source's kind inserts the reference at position N (user 11-17 Q4) in the same undo step.
  function connectNodes(sourceId, id, port = null) {
    const current = docRef.current, refusal = connectionRefusal(sourceId, id, current)
    if (refusal) { showError(refusal); return false }
    if (current.edges.some(edge => edge.source === sourceId && edge.target === id)) { setConnection(null); return true }
    const source = current.nodes.find(node => node.id === sourceId), kind = mediaKind(source), assetId = source?.asset?.id
    const insertAt = port && port.kind === kind && port.index && assetId && port.source !== 'empty' ? port.index : null
    const targetNode = current.nodes.find(node => node.id === id), before = targetNode?.text
    const beforeIds = resolveNodeInputs(targetNode, current.nodes, current.edges).assets.map(asset => asset.id)
    try {
      edit(doc => {
        let added = { ...doc, edges: [...doc.edges, { id: uid(), source: sourceId, target: id }] }
        // Connected sources resolve before library picks, so a new edge would otherwise land in front of them. Keep
        // "append to the end" (spec §4.2) by writing the full order — only when the resolved order would differ.
        if (assetId && !beforeIds.includes(assetId)) {
          const ids = resolveNodeInputs(added.nodes.find(node => node.id === id), added.nodes, added.edges).assets.map(asset => asset.id)
          if (ids.at(-1) !== assetId) added = { ...added, nodes: added.nodes.map(node => node.id === id ? { ...node, referenceOrder: [...beforeIds, assetId] } : node) }
        }
        return insertAt ? insertNodeReferenceAt(added, id, assetId, insertAt) : added
      }, insertAt ? { description: `接入参考并插入为第 ${insertAt} 位` } : undefined)
    } catch (failure) { showError(failure); return false }
    setConnection(null); setError('')
    if (insertAt && docRef.current.nodes.find(node => node.id === id)?.text !== before) notify?.(`已同步更新提示词中的引用（${canvasModifier()}+Z 可撤销）`, 'success')
    return true
  }
  function port(id, kind, target = null) {
    if (kind === 'output') { if (suppressPortClick.current) { suppressPortClick.current = false; return } setConnection(id); return }
    if (!connection) { showError('请先点击上游节点右侧的输出连接点。'); return }
    connectNodes(connection, id, target)
  }
  function startPortDrag(event, id) {
    suppressPortClick.current = false
    if (event.button !== 0 || ioRef.current || conflictRef.current || drag.current) return
    portDragRef.current = { source: id, startX: event.clientX, startY: event.clientY, active: false, pointerId: event.pointerId }
    try { event.currentTarget.setPointerCapture(event.pointerId) } catch { /* capture is optional */ }
  }
  const dropTargetAt = (x, y) => document.elementFromPoint(x, y)?.closest?.('.cv-world [data-node-id]')?.dataset.nodeId || null
  // The port under the pointer (kind/index/source), so a drop on occupied port N inserts at N.
  const dropPortAt = (x, y) => { const element = document.elementFromPoint(x, y)?.closest?.('.cv-world [data-port-kind]'); return element && !element.dataset.portGroup ? { kind: element.dataset.portKind, index: Number(element.dataset.portIndex) || null, source: element.dataset.portSource } : null }
  const portDragHandlers = useRef(null)
  portDragHandlers.current = {
    move(event) {
      const state = portDragRef.current
      if (!state || event.pointerId !== state.pointerId) return
      if (!state.active && Math.hypot(event.clientX - state.startX, event.clientY - state.startY) <= 4) return
      state.active = true
      const hover = dropTargetAt(event.clientX, event.clientY)
      setPortDrag({ source: state.source, point: worldPoint(event.clientX, event.clientY), target: hover && hover !== state.source ? hover : null })
    },
    end(event, cancelled = false) {
      const state = portDragRef.current
      if (!state || event.pointerId !== state.pointerId) return
      portDragRef.current = null
      if (!state.active) return
      suppressPortClick.current = true; setPortDrag(null)
      if (cancelled) return
      const target = dropTargetAt(event.clientX, event.clientY)
      if (target) connectNodes(state.source, target, dropPortAt(event.clientX, event.clientY))
    },
  }
  useEffect(() => {
    const move = event => portDragHandlers.current.move(event), up = event => portDragHandlers.current.end(event), cancel = event => portDragHandlers.current.end(event, true)
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up); window.addEventListener('pointercancel', cancel)
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', cancel) }
  }, [])
  // #7: preview the node's current result; closing returns focus to the node.
  const previewOwner = useRef(null)
  function openPreview(id) {
    const node = docRef.current.nodes.find(item => item.id === id)
    if (!node?.asset?.url) return
    previewOwner.current = id; setPreview({ ...node.asset, items: previewItems(node, docRef.current) })
  }
  function closePreview() {
    const id = previewOwner.current; previewOwner.current = null; setPreview(null)
    if (id) requestAnimationFrame(() => rootRef.current?.querySelector(`.cv-world [data-node-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: true }))
  }
  // #7a: animated camera move; any wheel/drag/zoom input stops it immediately.
  const viewAnimation = useRef(null)
  function stopViewAnimation() { if (viewAnimation.current) { cancelAnimationFrame(viewAnimation.current.frame); const last = viewAnimation.current.last; viewAnimation.current = null; if (last) edit(current => ({ ...current, viewport: last }), { history: false }) } }
  function focusZoom(id) {
    const node = docRef.current.nodes.find(item => item.id === id), rect = rootRef.current?.getBoundingClientRect()
    if (!node || !rect) return
    stopViewAnimation(); setFocusedGroup(null); interaction.selectSingle(id); rootRef.current.focus({ preventScroll: true }); if (panelPrefs.collapsed) panelPrefs.setCollapsed(false)
    const target = focusViewport(node, rect), from = { ...docRef.current.viewport }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { edit(current => ({ ...current, viewport: target }), { history: false }); return }
    const start = performance.now(), ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
    // Interpolate in log-zoom and keep the node's centre on a straight screen path so the node stays in view.
    const cx = node.x + nodeGeometry(node).width / 2, cy = node.y + nodeGeometry(node).height / 2
    const sx = from.x + cx * from.zoom, sy = from.y + cy * from.zoom, tx = target.x + cx * target.zoom, ty = target.y + cy * target.zoom
    const step = now => {
      const t = Math.min(1, (now - start) / FOCUS_MS), k = ease(t), zoom = Math.exp(Math.log(from.zoom) + (Math.log(target.zoom) - Math.log(from.zoom)) * k)
      const px = sx + (tx - sx) * k, py = sy + (ty - sy) * k, viewport = t >= 1 ? target : { zoom, x: px - cx * zoom, y: py - cy * zoom }
      if (t >= 1) { viewAnimation.current = null; edit(current => ({ ...current, viewport }), { history: false }); return }
      viewAnimation.current = { frame: requestAnimationFrame(step), last: viewport }
      edit(current => ({ ...current, viewport }), { history: false, transient: true })
    }
    viewAnimation.current = { frame: requestAnimationFrame(step), last: null }
  }
  function startDrag(event,node,options) {stopViewAnimation();setFocusedGroup(null);setContextMenu(null);setNodeMenu(null);interaction.startNode(event,node,options);setSelectedEdge(null) }
  function startSurface(event) { stopViewAnimation(); setContextMenu(null);setNodeMenu(null);interaction.startSurface(event) }
  function movePointer(event) { interaction.move(event) }
  function zoomAt(factor, x, y) {
    stopViewAnimation()
    const rect = rootRef.current.getBoundingClientRect(), cx = x ?? rect.width / 2, cy = y ?? rect.height / 2
    edit(current => { const view = current.viewport, zoom = Math.min(MAX_ZOOM, Math.max(.2, view.zoom * factor)); const scale = zoom / view.zoom; return { ...current, viewport: { x: cx - (cx - view.x) * scale, y: cy - (cy - view.y) * scale, zoom } } })
  }
  const zoomRef = useRef(zoomAt); zoomRef.current = zoomAt
  useEffect(() => {
    const surface = rootRef.current
    if (!surface) return
    const wheel = event => {
      if (event.target.closest('textarea,input,select,video,audio,.cv-node-text,.cv-properties,.cv-tools,.cv-viewport-tools,.cv-node-toolbar,.cv-rail,.cv-rail-panel,.cv-context-menu')) return
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
  async function importFiles(files, point, targetId, origin = 'canvas_upload') {
    if (!files.length) return
    if (!workflowRef.current && !await newWorkflow()) return
    const owner = workflowRef.current.id
    const batchTarget = targetId && docRef.current.nodes.find(node => node.id === targetId)
    const rect = rootRef.current.getBoundingClientRect()
    const batchOrigin = point || (batchTarget ? {x:batchTarget.x-NODE_WIDTH-60,y:batchTarget.y} : worldPoint(rect.left+rect.width/2-145,rect.top+rect.height/2-100))
    ioRef.current += 1; setIoCount(ioRef.current)
    // CANVAS-INPUT-20261114 #1: upload every file first, then add all nodes in one edit (one undo step per drop/paste).
    // A deduplicated upload returns the existing library media (its stored name); the new node keeps this file's name.
    const uploaded = [], problems = [], titles = new Map()
    let folderFallback = false
    try {
    for (const file of [...files]) {
      const kind = (file.type || '').split('/')[0]
      if (!['image', 'video', 'audio'].includes(kind)) { problems.push(`不支持的素材类型：${file.name || file.type || '未知文件'}（仅支持图片、视频、音频）`); continue }
      const target = targetId && docRef.current.nodes.find(node => node.id === targetId)
      if (target && !canConnect({id:'uploaded-reference',type:'asset',asset:{kind}},target)) { problems.push('所选素材类型不能接入该生成节点。'); continue }
      try {
        const saved = await uploadCanvasLibraryMedia(file, { origin, folderId: uploadFolderRef.current })
        if (saved.folderFallback) { folderFallback = true; setUploadFolder(null) }
        if (workflowRef.current?.id !== owner) { problems.push('素材已保存到素材库；当前画布已切换，未添加节点，可从素材库拖入。'); uploaded.length = 0; break }
        uploaded.push(saved.asset); if (file.name) titles.set(saved.asset.id, String(file.name).slice(0, 240))
      } catch (failure) { const status = failure?.response?.status; problems.push(`${file.name || '文件'}：${status === 413 ? '文件过大，超过服务器上传上限' : messageOf(failure)}`) }
    }
    if (uploaded.length && workflowRef.current?.id === owner) {
      try { addAssetNodes(uploaded,targetId,{x:batchOrigin.x,y:batchOrigin.y},titles); await save() } catch (failure) { problems.push(messageOf(failure)) }
    }
    if (folderFallback) problems.push('画布上传文件夹已不存在，素材已存到素材库根目录')
    if (problems.length) showError(problems.join('；'))
    } finally { ioRef.current -= 1; if (mounted.current) setIoCount(ioRef.current) }
  }
  // FRAME-CAPTURE-20261114: capture a still from a video node and add it as an image material
  // node to the right of the source, through the same upload path as paste/drop (one undo step).
  function nodePlayer(id) { return rootRef.current?.querySelector(`[data-node-id="${CSS.escape(id)}"] video`) || null }
  function currentFrameNote(id) {
    const player = nodePlayer(id)
    if (!player || !(player.played?.length || player.currentTime > 0)) return '节点内播放器未播放过，将截取首帧'
    return `${player.paused ? '暂停于' : '播放中，将暂停于'} ${formatFrameTime(player.currentTime)}`
  }
  async function captureFrame(id, tail) {
    setNodeMenu(null)
    const node = docRef.current.nodes.find(item => item.id === id), owner = workflowRef.current?.id
    if (!node?.asset?.url || mediaKind(node) !== 'video' || !owner) { showError('该节点没有可截取的视频'); return }
    if (ioRef.current) { showError('请等待当前操作完成后再截帧'); return }
    let time = 0, note = ''
    if (!tail) {
      const player = nodePlayer(id)
      if (player && (player.played?.length || player.currentTime > 0)) { if (!player.paused) player.pause(); time = player.currentTime }
      else note = '节点内播放器未播放过，已截取首帧'
    }
    let frame
    try { frame = await captureVideoFrame(node.asset.url, { tail, time }) } catch (failure) { showError(`截帧失败：${messageOf(failure)}；未新建节点`); return }
    if (!mounted.current || workflowRef.current?.id !== owner) return
    const name = frameFileName(node.title, { tail, time: frame.time }), before = docRef.current.nodes.length
    const source = docRef.current.nodes.find(item => item.id === id) || node
    await importFiles([new File([frame.blob], name, { type: 'image/png' })], { x: source.x + nodeGeometry(source).width + 60, y: source.y }, null, 'frame')
    if (mounted.current && docRef.current.nodes.length > before) notify?.(`已截取 ${name}（${frame.width}×${frame.height}）${note ? `；${note}` : ''}`)
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
  // GROUP-RUN-20261115 B5: server-side group runs (state polled from the server; never edits member node fields).
  const groupRunBlock='该节点正在节点组运行中，由组运行按顺序提交，不能手动生成；如需单独生成请先取消整组'
  const groupRun=useGroupRunController({workflowId:workflow?.id,save,getRevision:()=>workflowRef.current?.revision,titleOf:id=>docRef.current.nodes.find(n=>n.id===id)?.title||id,groupTitleOf:id=>docRef.current.groups?.find(g=>g.id===id)?.title||id,showError})
  // QA D-L1: show results of members the server submits while this page is open (task poll + task-sync; runtime only, no save).
  useEffect(()=>{if(adoptGroupRunTasks(docRef.current,groupRun.runs)!==docRef.current)edit(current=>adoptGroupRunTasks(current,groupRun.runs),{history:false,runtime:true,transient:true})},[groupRun.runs,edit])
  async function generate(id) {
    if (groupRun.owningRun(id)) { showError(groupRunBlock); return }
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
      if (task?.id) watchedTasks.current.add(Number(task.id))
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
  async function saveAssetVersion(owner,file,origin='canvas_upload') {
    if(!owner.workflowId || workflowRef.current?.id!==owner.workflowId)throw new Error('原画布已切换，未替换当前素材')
    const node=docRef.current.nodes.find(item=>item.id===owner.nodeId)
    if(!node || node.asset?.id!==owner.assetId)throw new Error('原素材节点已改变，请重新操作')
    if(owner.kind==='image' && node.candidates?.length>=100 && !owner.versionPending)throw new Error('图片历史版本已达100个，请创建新素材节点')
    if(file.type.split('/')[0]!==owner.kind)throw new Error('替换素材必须保持原媒体类型')
    ioRef.current++;setIoCount(ioRef.current)
    try {
      const saved=await uploadCanvasLibraryMedia(file,{origin,folderId:uploadFolderRef.current}),asset=saved.asset
      if(saved.folderFallback)setUploadFolder(null)
      if(workflowRef.current?.id!==owner.workflowId || docRef.current.nodes.find(item=>item.id===owner.nodeId)?.asset?.id!==owner.assetId)throw new Error('原素材节点已改变，文件已保存到素材库，未替换当前素材')
      const result=switchAssetVersion(docRef.current,owner.nodeId,asset,true);edit(()=>result.document,{description:owner.description});owner.assetId=asset.id;owner.versionPending=true;await save();owner.versionPending=false;if(result.warnings.length)showError(result.warnings.join('；'))
    } catch(failure) {throw new Error(messageOf(failure))} finally {ioRef.current--;setIoCount(ioRef.current)}
  }
  async function rotateNode(id) {
    if(ioRef.current)return
    const owner=assetOwner(id,"旋转图片"),node=docRef.current.nodes.find(item=>item.id===id)
    ioRef.current++;setIoCount(ioRef.current)
    try{const file=await rotateImageFile(node.asset);await saveImageResult(owner,file)}catch(e){showError(e)}finally{ioRef.current--;setIoCount(ioRef.current)}
  }
  function annotateNode(id) {if(ioRef.current)return;const owner=assetOwner(id,"标注图片");annotationOwner.current=owner;setAnnotation({owner,asset:docRef.current.nodes.find(n=>n.id===id).asset});ioRef.current++;setIoCount(ioRef.current)}
  // CANVAS-LAYOUT-2-WIRE-20261118 (user 11-17 Q5): image tools on an image asset node keep their behaviour (new
  // version of that node, the old file stays in the library). On an image generation node the edited / rotated /
  // annotated image is saved as a NEW library asset placed as a new asset node beside it; the result is untouched.
  async function saveImageResult(owner,file){
    const node=docRef.current.nodes.find(item=>item.id===owner.nodeId)
    if(!node||node.type==='asset')return saveAssetVersion(owner,file,'save_as')
    if(!owner.workflowId||workflowRef.current?.id!==owner.workflowId)throw new Error('原画布已切换，未保存编辑结果')
    if(node.asset?.id!==owner.assetId)throw new Error('节点结果已改变，请重新操作')
    if(file.type.split('/')[0]!=='image')throw new Error('编辑结果必须是图片')
    ioRef.current++;setIoCount(ioRef.current)
    try{
      const saved=await uploadCanvasLibraryMedia(file,{origin:'save_as',folderId:uploadFolderRef.current}),asset=saved.asset
      if(saved.folderFallback)setUploadFolder(null)
      if(workflowRef.current?.id!==owner.workflowId)throw new Error('原画布已切换，编辑结果已保存到素材库，未添加到画布')
      const source=docRef.current.nodes.find(item=>item.id===owner.nodeId)||node
      addAssetNodes([asset],null,{x:source.x+nodeGeometry(source).width+60,y:source.y})
      await save();setAssetRefresh(value=>value+1)
      notify?.(`${owner.description.split('：')[0]}结果已另存为新素材“${asset.name||'图片'}”，原生成结果不变`,'success')
    }catch(failure){throw new Error(messageOf(failure))}finally{ioRef.current--;setIoCount(ioRef.current)}
  }
  function editNodeImage(id){if(ioRef.current)return;const owner=assetOwner(id,'编辑图片'),node=docRef.current.nodes.find(n=>n.id===id);if(!node?.asset?.url)return;setImageEditing({owner,asset:node.asset});ioRef.current++;setIoCount(ioRef.current)}
  function closeImageEditor(){setImageEditing(current=>{if(current){ioRef.current--;setIoCount(ioRef.current)}return null})}
  // NODE-TOOLBAR-VERSIONS-20261118 root cause of "历史版本 does nothing": for generation nodes this used to only move
  // focus to the panel's 版本 section (programmatic focus shows no ring, the section was usually below the fold), so
  // nothing visible happened. Every node kind now opens the same version popover; focus returns to the opener.
  function openNodeHistory(id,returnTo='toolbar'){
    const node=docRef.current.nodes.find(item=>item.id===id)
    if(!node||(node.candidates?.length||0)<2)return
    historyReturn.current=returnTo;setNodeMenu(null);setSelected(id);setHistoryNode(id)
  }
  function closeHistory(){
    setHistoryNode(null)
    const target=historyReturn.current;historyReturn.current=null
    requestAnimationFrame(()=>{if(target==='toolbar'&&toolbarRef.current){toolbarRef.current.focusAction('history');return}focusSelection()})
  }
  function closeAnnotation(){if(annotationOwner.current){annotationOwner.current=null;ioRef.current--;setIoCount(ioRef.current)}setAnnotation(null)}
  function replaceNodeAsset(id){replacementOwner.current=assetOwner(id);replacementInput.current.accept=`${replacementOwner.current.kind}/*`;replacementInput.current.click();setNodeMenu(null)}
  // LIBRARY-OPS-FIX-20261117 E7: replace a node's media (e.g. an "已删除" placeholder) with one picked from the
  // library; the picked media is referenced as is (no copy, no upload). Local upload stays available.
  function replaceNodeFromLibrary(id){setNodeMenu(null);if(ioRef.current)return;const owner=assetOwner(id,'从素材库替换素材');if(owner.kind)setReplaceOwner({...owner,projectId:projectIdRef.current})}
  async function applyLibraryReplacement(owner,items){
    if(!owner.workflowId||workflowRef.current?.id!==owner.workflowId)throw new Error('原画布已切换，未替换当前素材')
    const node=docRef.current.nodes.find(item=>item.id===owner.nodeId)
    if(!node||node.asset?.id!==owner.assetId)throw new Error('原素材节点已改变，请重新操作')
    if(owner.kind==='image'&&node.candidates?.length>=100)throw new Error('图片历史版本已达100个，请创建新素材节点')
    if(ioRef.current||navigationRef.current)throw new Error('请等待当前操作完成')
    ioRef.current++;setIoCount(ioRef.current)
    try{
      const asset=(await libraryReferences(owner.workflowId,items)).assets?.[0]
      if(!asset)throw new Error('未能读取所选素材')
      if(asset.kind!==owner.kind)throw new Error('替换素材必须保持原媒体类型')
      if(workflowRef.current?.id!==owner.workflowId||docRef.current.nodes.find(item=>item.id===owner.nodeId)?.asset?.id!==owner.assetId)throw new Error('原素材节点已改变，未替换当前素材')
      const result=switchAssetVersion(docRef.current,owner.nodeId,asset,true);edit(()=>result.document,{description:owner.description});await save();setReplaceOwner(null);if(result.warnings.length)showError(result.warnings.join('；'))
    }finally{ioRef.current--;setIoCount(ioRef.current)}
  }
  // Asset nodes keep switchAssetVersion (title follows the file, downstream bindings); generation nodes use the same
  // asset + selectedCandidateId patch the panel's 版本 buttons used. Both save right away.
  function chooseVersion(id,asset){
    if(ioRef.current)return
    try{
      const node=docRef.current.nodes.find(item=>item.id===id)
      if(!node)throw new Error('节点不存在')
      if(node.type==='asset'){const result=switchAssetVersion(docRef.current,id,asset);edit(()=>result.document);if(result.warnings.length)showError(result.warnings.join('；'))}
      else{if(!node.candidates?.some(item=>item.id===asset.id))throw new Error('历史版本不存在');if(node.asset?.id!==asset.id)patchNode(id,{asset,selectedCandidateId:asset.id})}
      closeHistory();save().catch(showError)
    }catch(e){showError(e)}
  }
  // Local material deletion rewrites affected canvases on the server (revision+1).
  // Flush pending edits first; afterwards reload a clean canvas, or enter the
  // existing conflict flow if newer local edits could not be saved.
  async function flushBeforeLibraryDelete(){if(workflowRef.current&&!conflictRef.current)await save()}
  async function afterLibraryDelete(result){
    setAssetRefresh(value=>value+1)
    // LIBRARY-GLOBAL S5: deleted media become "已删除" placeholders here at once (the server rewrote affected canvases).
    if(Array.isArray(result?.deleted_ids))markDeletedMedia(result.deleted_ids)
    mediaStatus.recheck()
    const current=workflowRef.current
    if(!current||!(result.workflow_ids||[]).includes(current.id))return
    if(version.current!==savedVersion.current||conflictRef.current){conflictRef.current=true;setConflict(true);return}
    try{const fresh=await getCanvasWorkflow(current.id);if(workflowRef.current?.id===current.id&&version.current===savedVersion.current)installWorkflow(fresh);else{conflictRef.current=true;setConflict(true)}}catch(failure){showError(failure)}
  }
  // Library dialog selection → direct references. Old catalog items the library does not know yet
  // (before migration) keep the previous import route; deleted media are refused.
  async function libraryReferences(workflowId,items){
    const found=await resolveLibraryMedia(items)
    if(found.deleted.length)throw new Error(`素材“${found.deleted[0]}”已在素材库中删除，未添加`)
    const legacy=found.legacy.length?(await resolveLibraryItems(workflowId,found.legacy.map(entry=>entry.item.selection))).assets||[]:[]
    const ordered=[...found.assets,...found.legacy.map((entry,index)=>({index:entry.index,asset:legacy[index]}))].filter(entry=>entry.asset).sort((a,b)=>a.index-b.index).map(entry=>entry.asset)
    return {assets:ordered}
  }
  // "已删除" placeholder actions: an asset node can be replaced or removed; a generation node drops
  // the deleted result (and its kept version), keeping any other version.
  function removeDeletedResult(id){
    const node=docRef.current.nodes.find(item=>item.id===id)
    if(!node)return
    if(node.type==='asset'){deleteNode(id);return}
    const candidates=(node.candidates||[]).filter(candidate=>!(isMediaAsset(candidate)&&isDeletedMedia(candidate.id)&&!isTrashedMedia(candidate.id))),asset=candidates.at(-1)||null
    edit(current=>({...current,nodes:current.nodes.map(item=>item.id===id?{...item,candidates,asset,selectedCandidateId:asset?.id||null}:item)}),{description:`移除已删除的结果：节点“${node.title}”`})
  }
  async function revealInLibrary(asset){
    setNodeMenu(null)
    try{const media=isMediaAsset(asset)?{id:asset.id}:await resolveAssetMediaId(asset);if(!media)throw new Error('该结果尚未进入素材库（等待迁移）');railRef.current?.open('assets',{focus:false});setRevealMedia({id:media.id,nonce:Date.now()})}catch(e){showError(e)}
  }
  async function resolveAssetMediaId(asset){const item=(await lookupMedia([asset.url])).get(asset.url);return item?.status==='ok'?{id:item.media_id}:null}
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
  // FIX-B2-20261114 #3: when the selected node grows (the status footer appears once a task exists), re-reveal
  // it so the editor panel below never covers the node or its status line. Only on growth, never on pan.
  // CARD-PROMPT-RESIZE-20261118: a manual resize is not "growth" (the view never pans/zooms under the resize grip).
  const selectedHeight = selectedNode ? nodeGeometry(selectedNode).height : 0, selectedScale = selectedNode?.size?.scale ?? 1, grownRef = useRef(null)
  useEffect(() => {
    const previous = grownRef.current; grownRef.current = { id: selected, height: selectedHeight, scale: selectedScale }
    if (!selected || previous?.id !== selected || previous.height >= selectedHeight || previous.scale !== selectedScale || resizeRef.current || viewAnimation.current || drag.current) return
    interaction.reveal(selected)
  }, [selected, selectedHeight, selectedScale])
  // Position-only gestures do not change reference inputs. Keep their derivation stable while
  // preserving every other node field (including future fields) as an invalidation dependency.
  const inputNodesRef = useRef(doc.nodes)
  const previousInputNodes = inputNodesRef.current
  if (previousInputNodes.length !== doc.nodes.length || doc.nodes.some((node,index) => {
    const previous = previousInputNodes[index]
    const keys = new Set([...Object.keys(node), ...Object.keys(previous || {})])
    return [...keys].some(key => key !== 'x' && key !== 'y' && node[key] !== previous?.[key])
  })) inputNodesRef.current = doc.nodes
  const inputNodes = inputNodesRef.current
  // Deletion status lives outside the document; delayed lookup results must invalidate inputs too.
  const inputMap = useMemo(() => new Map(inputNodes.map(node => [node.id, resolveNodeInputs(node,inputNodes,doc.edges)])), [inputNodes, doc.edges, mediaStatus.deletedKey])
  // CANVAS-PORTS-UI-20261118: dynamic reference ports, derived only from resolveNodeInputs (never written back).
  const dragSourceId = portDrag?.source || connection, dragSource = dragSourceId && doc.nodes.find(node => node.id === dragSourceId)
  const dragKind = dragSource ? mediaKind(dragSource) : null
  const portMap = useMemo(() => new Map(inputNodes.filter(node => ['image','video','audio'].includes(node.type)).map(node => {
    const derived = deriveNodePorts(node,doc.nodes,doc.edges,{provider:nodeProvider(capabilities,node),inputs:inputMap.get(node.id)})
    const other = !!dragSource && dragSource.id !== node.id, reason = other ? connectionRefusal(dragSource.id,node.id,doc) : null
    const candidate = other && !reason && PORT_KINDS.includes(dragKind)
    const expanded = interaction.selectedIds.includes(node.id) || portHover === node.id || portDrag?.target === node.id || candidate
    return [node.id, {derived, layout: portLayout(derived,nodeGeometry(node),{expanded}), warnings: overLimitMessages(derived), block: overLimitBlock(derived), dragReason: other ? reason || null : null, dragKind: other && PORT_KINDS.includes(dragKind) ? dragKind : null}]
  })), [inputNodes, doc.edges, inputMap, capabilities, mediaSizeRevision, dragSource, dragKind, interaction.selectedIds, portHover, portDrag?.target])
  const portBlock = node => portMap.get(node?.id)?.block || ''
  const dropAnnouncement = portDrag?.target ? (portMap.get(portDrag.target)?.dragReason || portDropAnnouncement(portMap.get(portDrag.target)?.derived, dragKind)) : ''
  const contextNode=doc.nodes.find(node=>node.id===nodeMenu?.id),contextDeleted=isMediaAsset(contextNode?.asset)&&isDeletedMedia(contextNode.asset.id),contextLiveVersions=(contextNode?.candidates||[]).filter(asset=>asset?.id&&!(isMediaAsset(asset)&&isDeletedMedia(asset.id)))
  const historyNodeData=historyNode?doc.nodes.find(node=>node.id===historyNode)||null:null
  const contextDeleteBlocked=generationLocks.current.has(nodeMenu?.id)||isBusyTaskStatus(contextNode?.task?.status)
  const undoDescription=editHistory.current.past.at(-1)?.description,redoDescription=editHistory.current.future.at(-1)?.description
  // CANVAS-LAYOUT-1-20261117: editing state of the single selected node, shared by its card prompt and the panel.
  const selectedInputs=selectedNode?inputMap.get(selectedNode.id):null,selectedAssets=selectedInputs?.assets||[]
  const selectedNodeProvider=selectedNode?nodeProvider(capabilities,selectedNode):null
  const nodePatch=(id,patch)=>{patchNode(id,patch);if(patch.providerSelection){const node=docRef.current.nodes.find(n=>n.id===id);if(node)rememberProvider(node.type,patch.providerSelection)}}
  const promptEditor=useNodeCharacters({node:selectedNode,inputAssets:selectedAssets,inputIssues:selectedInputs?.issues||[],provider:selectedNodeProvider,workflowId:workflow?.id,onPatch:nodePatch})
  const selectedGen=useNodeGeneration({node:selectedNode,provider:selectedNodeProvider,inputAssets:selectedAssets,workflowId:workflow?.id,blockedReason:selectedNode&&groupRun.owningRun(selectedNode.id)?groupRunBlock:portBlock(selectedNode),resultUnknown:selectedNode?isUnknownResult(selectedNode):false,mentionIssues:promptEditor.mentionIssues,onPatch:nodePatch})
  const selectedEstimate=useCanvasEstimate({node:selectedNode,provider:selectedNodeProvider,references:selectedGen.estimateReferences,imageIssue:selectedGen.imageIssue})
  panelToggle.current=()=>panelPrefs.setCollapsed(!panelPrefs.collapsed)
  const dialogNode=doc.nodes.find(node=>node.id===promptDialog)
  // Selected card prompt: Enter edits it, Shift+Enter jumps to the panel. CARD-PROMPT-READABLE-20261118 (user 11-18):
  // a click / Enter edits in the card at every zoom; only the 展开编辑 button (or the panel button) opens the dialog.
  function activatePrompt(id){
    if(ioRef.current)return
    setFocusedGroup(null);setSelectedEdge(null);if(!(interaction.selectedIds.length===1&&interaction.selectedIds[0]===id))interaction.selectSingle(id)
    setPromptFocus(current=>({id,n:current.n+1}))
  }
  function focusPanel(){if(panelPrefs.collapsed)panelPrefs.setCollapsed(false);requestAnimationFrame(()=>document.querySelector('.cv-properties .cv-properties-body :is(input,select,textarea,button):not(:disabled), .cv-properties .cv-properties-head input')?.focus())}
  function focusSelection(){const id=interaction.selectedIds[0];const element=id&&rootRef.current?.querySelector(`.cv-node[data-node-id="${CSS.escape(id)}"]`);(element||rootRef.current)?.focus({preventScroll:true})}
  const cardPrompt=node=>{
    if(!['image','video','audio','text'].includes(node.type))return null
    const single=selected===node.id&&interaction.selectedIds.length===1,editable=single&&!ioCount
    // CANVAS-LAYOUT-1-20261117 (user 11-17, as ImagineArt): every generation card has the small 生成 button. On an
    // unselected card (or within a multi-selection) the click selects that node only, then runs the same flow as the
    // panel button once its checks are ready (same disabled reasons, result-unknown confirmation, estimate).
    const label={image:'画面',video:'视频',audio:'音频'}[node.type],nodeBlock=node.type==='text'?'':quickGenerationBlock(node,nodeProvider(capabilities,node),groupRun.owningRun(node.id)?groupRunBlock:portBlock(node))
    const generate=node.type==='text'?null:single?{nodeId:node.id,label,disabledReason:selectedGen.disabledReason,estimate:selectedEstimate,onGenerate:()=>requestGenerate(node.id)}:{nodeId:node.id,label,disabledReason:nodeBlock,provider:nodeProvider(capabilities,node),references:inputMap.get(node.id)?.assets||[],onGenerate:()=>{if(ioRef.current)return;setFocusedGroup(null);setSelectedEdge(null);interaction.selectSingle(node.id);setCardGenerate(node.id)}}
    return <CanvasNodePrompt node={node} editable={editable} inputAssets={single?selectedAssets:[]} editor={single?promptEditor:null} onText={text=>patchNode(node.id,{text})} onActivate={()=>activatePrompt(node.id)} onExpand={node.type==='text'?undefined:()=>{if(ioRef.current)return;setFocusedGroup(null);setSelectedEdge(null);if(!single)interaction.selectSingle(node.id);setPromptDialog(node.id)}} focusRequest={promptFocus.id===node.id?promptFocus.n:0} generate={generate}/>
  }
  // Card 生成 on a node that was not the single selection: decide once that node is selected and its checks are ready.
  useEffect(()=>{
    if(!cardGenerate)return
    if(selected!==cardGenerate){setCardGenerate(null);return}
    if(!selectedGen.ready)return
    setCardGenerate(null)
    if(selectedGen.disabledReason)showError(`无法生成：${selectedGen.disabledReason}`);else requestGenerate(cardGenerate)
  },[cardGenerate,selected,selectedGen.ready,selectedGen.disabledReason])
  const panelGroup=doc.groups?.find(group=>group.id===focusedGroup)
  const selectionNodes=interaction.selectedIds.map(id=>doc.nodes.find(node=>node.id===id)).filter(Boolean)
  const panelContent=panelGroup?groupContent({group:panelGroup,nodes:doc.nodes,run:groupRun.runFor(panelGroup.id),titleOf:id=>doc.nodes.find(node=>node.id===id)?.title||id,disabled:busy||ioCount>0,onRename:renameGroup,onUngroup:ungroup,onColor:(group,color,label)=>edit(current=>({...current,groups:current.groups.map(item=>item.id===group.id?{...item,color}:item)}),{description:`节点组底色改为${label}`}),onRun:group=>groupRun.start(group),onCancelRun:groupRun.requestCancel})
    :selectionNodes.length>1?multiContent({nodes:selectionNodes,plan:selectionNodes.some(node=>['image','video','audio'].includes(node.type))?planSelection():null,onLocate:locateNode,onMakeGroup:makeGroup,onRun:()=>setBatchPlan(planSelection()),groupDisabled:busy||ioCount>0,runDisabledReason:busy||ioCount>0?'请等待当前操作完成':conflict?'画布版本冲突，请先处理冲突提示':''})
    :!selectedNode?canvasContent({nodes:doc.nodes})
    :selectedNode.type==='text'?textContent({node:selectedNode,usedBy:doc.edges.filter(edge=>edge.source===selectedNode.id).length,onChange:patch=>nodePatch(selectedNode.id,patch),onEditPrompt:()=>setPromptDialog(selectedNode.id)})
    :selectedNode.type==='asset'?(()=>{const asset=selectedNode.asset,deleted=isMediaAsset(asset)&&isDeletedMedia(asset?.id),usable=asset?.id&&['image','video','audio'].includes(asset?.kind)&&!deleted;return assetContent({node:selectedNode,dimensions:mediaSize(asset?.id),deleted,onChange:patch=>nodePatch(selectedNode.id,patch),onCopy:()=>copyNode(selectedNode),onRevealInLibrary:usable?()=>revealInLibrary(asset):null,onMoveToFolder:usable?()=>setMovingAssets([asset]):null,onAddToCharacter:usable&&asset.kind==='image'&&asset.url&&workflow?.id?()=>setCharacterTarget({workflowId:workflow.id,asset}):null,onReplace:!ioCount?()=>replaceNodeAsset(selectedNode.id):null,onReplaceFromLibrary:!ioCount?()=>replaceNodeFromLibrary(selectedNode.id):null,onRemove:()=>removeDeletedResult(selectedNode.id)})})()
    :generationContent({node:selectedNode,provider:selectedNodeProvider,providerOptions:capabilities[selectedNode.type]||[],gen:selectedGen,editor:promptEditor,estimate:selectedEstimate,inputAssets:selectedAssets,errorMessage:error,resultUnknown:isUnknownResult(selectedNode),mentionNotice:mentionNotice?.nodeId===selectedNode.id&&mentionNotice.key===JSON.stringify(selectedNode.referenceMentions||{})?mentionNotice.text:'',
      onChange:patch=>nodePatch(selectedNode.id,patch),onGenerate:()=>requestGenerate(selectedNode.id),onCopy:()=>copyNode(selectedNode),onOrganizeGroup:selectedNode.type==='video'&&selectedNode.params?.video_mode==='keyframe'&&!doc.groups?.some(group=>group.keyframeNodeId===selectedNode.id)?()=>organizeKeyframes(selectedNode.id):null,
      onClearReferences:()=>clearReferences(selectedNode.id),portWarnings:portMap.get(selectedNode.id)?.warnings||[],overLimitCount:portMap.get(selectedNode.id)?.derived.overLimitCount||0,onRemoveOverLimit:()=>removeOverLimit(selectedNode.id),onReorderReferences:order=>{try{const before=docRef.current.nodes.find(n=>n.id===selectedNode.id)?.text;edit(current=>reorderNodeReferences(current,selectedNode.id,order),{description:'调整参考素材顺序并同步提及'});if(docRef.current.nodes.find(n=>n.id===selectedNode.id)?.text!==before)notify?.(`已同步更新提示词中的引用（${canvasModifier()}+Z 可撤销）`,'success')}catch(error){showError(error)}},
      onUpload:()=>pickFile(selectedNode.id),onLibrary:()=>openLibrary(selectedNode.id),onLinkTask:taskId=>linkTask(selectedNode.id,taskId),onOpenTask:task=>openTaskCenter(task,selectedNode.type),onDismissStale:()=>edit(current=>clearStale(current,selectedNode.id),{description:'清除“上游已更新”标记'}),onRevealInLibrary:revealInLibrary,onNotice:text=>{notify?.(text,'success');setAssetRefresh(value=>value+1)},onEditPrompt:()=>setPromptDialog(selectedNode.id)})
  // CANVAS-LAYOUT-2-WIRE-20261118: chrome wiring (rail panels, node toolbar, F6 regions, bottom tool position).
  const promptTarget=interaction.selectedIds.length===1&&['image','video','audio'].includes(selectedNode?.type)?selectedNode:null
  function insertLibraryPrompt(text){
    const node=promptTarget;if(!node)return
    const textarea=rootRef.current?.querySelector(`.cv-world .cv-node[data-node-id="${CSS.escape(node.id)}"] textarea.cv-card-prompt`)
    insertPromptText(textarea,text,{value:docRef.current.nodes.find(item=>item.id===node.id)?.text||'',onFallback:next=>{promptEditor?.setMentionError?.('');patchNode(node.id,{text:next})}})
  }
  const taskBadge=summarizeCanvasTasks(doc.nodes).active.length
  const toolbarShown=nodeToolbarVisible({node:selectedNode,selectedCount:interaction.selectedIds.length,dragging:drag.current?.type==='nodes'&&!!drag.current.moved,connecting:!!portDrag||!!connection,annotating:!!annotation||!!imageEditing,deleted:!!selectedNode?.asset&&isMediaAsset(selectedNode.asset)&&isDeletedMedia(selectedNode.asset.id)})
  function cycleRegion(back){
    const order=['rail',...(rail.panel?['panel']:[]),'canvas','properties'],active=document.activeElement,studio=rootRef.current?.closest('.canvas-studio')
    const current=active?.closest?.('.cv-rail')?'rail':active?.closest?.('.cv-rail-panel')?'panel':active?.closest?.('.cv-properties')?'properties':'canvas'
    const next=order[(order.indexOf(current)+(back?-1:1)+order.length)%order.length]
    const focusable=':is(button,input,select,textarea,[tabindex]):not([disabled]):not([tabindex="-1"])'
    const target=next==='rail'?studio?.querySelector('.cv-rail button[tabindex="0"]'):next==='panel'?(studio?.querySelector(`.cv-rail-panel .cv-rail-panel-body ${focusable}`)||studio?.querySelector('.cv-rail-panel-head button')):next==='properties'?studio?.querySelector(`.cv-properties ${focusable}`):null
    if(next==='canvas'||!target)focusSelection();else target.focus({preventScroll:true})
  }
  chromeKeys.current={cycle:cycleRegion,toolbar:()=>{if(!toolbarRef.current)return false;toolbarRef.current.focus();return true}}
  return <section className="canvas-studio" aria-label="创作画布">
    <div className="cv-layout">
    <CanvasRail active={rail.panel} pinned={rail.pinned} iconRefs={rail.iconRefs} onToggle={rail.toggle} onCharacters={()=>openLibrary('__browse__','characters')} onShortcuts={()=>setShortcutsOpen(true)} onTogglePin={togglePin} badges={{tasks:taskBadge}}/>
     {rail.panel && <CanvasRailPanel id={rail.panel} pinned={rail.pinned} autoFocus={rail.autoFocus} onFocused={rail.consumeFocus} onClose={rail.close} onTogglePin={togglePin} pinDisabledReason={pinRefusal()} onWidth={setRailPanelPx}>{rail.panel==='project'?<CanvasProjectPanel edges={doc.edges} groups={doc.groups||[]} onLocateGroup={locateGroup} onRenameGroup={renameGroup} onUngroup={ungroup} navigationError={error} projects={projects} projectId={projectId} workflows={workflows} workflow={workflow} nodes={doc.nodes} selected={selected} selectedIds={interaction.selectedIds} disabled={loading||busy||ioCount>0||generationCount>0} onProject={chooseProject} onWorkflow={chooseWorkflow} onNewProject={requestNewProject} onNewWorkflow={newWorkflow} onRenameProject={()=>{setError('');setRenameMode('rename');setRenameDraft(projects.find(item=>String(item.id)===String(projectId))?.title || '')}} onRenameProjectDirect={renameSidebarProject} onRenameWorkflow={renameSidebarWorkflow} onLibrary={()=>openLibrary('__browse__')} onCharacters={()=>openLibrary('__browse__','characters')} onLocate={locateNode} onSelect={locateNode} onCopy={copyNode} onDelete={deleteNode} onRating={(id,rating)=>patchNode(id,{rating})} onAddAssets={addProjectAssets} ioBusy={ioCount>0} onRenameNode={node=>{setSelected(node.id);setSidebarRename({id:node.id,title:node.title})}} onDeleteProject={()=>setDeletion({kind:'project',id:projectId,title:projects.find(p=>p.id===projectId)?.title || '当前项目'})} onDeleteWorkflow={()=>setDeletion({kind:'workflow',id:workflow.id,title})} onPendingDeletions={()=>save().then(()=>setPendingDeletions(true)).catch(showError)} assetRefresh={assetRefresh} mediaRefresh={mediaRefresh} referenceTarget={interaction.selectedIds.length===1&&['image','video','audio'].includes(selectedNode?.type)?{id:selectedNode.id,title:selectedNode.title}:null} onAddReference={(assets,kinds)=>{const target=interaction.selectedIds.length===1?interaction.selectedIds[0]:null;if(!target)throw new Error('请先选择一个生成节点');return addProjectReferences(assets,kinds,target)}} revealMedia={revealMedia} uploadFolder={uploadFolder} onUploadFolder={setUploadFolder}/>:rail.panel==='assets'?<CanvasAssetPanel edges={doc.edges} groups={doc.groups||[]} onLocateGroup={locateGroup} onRenameGroup={renameGroup} onUngroup={ungroup} navigationError={error} projects={projects} projectId={projectId} workflows={workflows} workflow={workflow} nodes={doc.nodes} selected={selected} selectedIds={interaction.selectedIds} disabled={loading||busy||ioCount>0||generationCount>0} onProject={chooseProject} onWorkflow={chooseWorkflow} onNewProject={requestNewProject} onNewWorkflow={newWorkflow} onRenameProject={()=>{setError('');setRenameMode('rename');setRenameDraft(projects.find(item=>String(item.id)===String(projectId))?.title || '')}} onRenameProjectDirect={renameSidebarProject} onRenameWorkflow={renameSidebarWorkflow} onLibrary={()=>openLibrary('__browse__')} onCharacters={()=>openLibrary('__browse__','characters')} onLocate={locateNode} onSelect={locateNode} onCopy={copyNode} onDelete={deleteNode} onRating={(id,rating)=>patchNode(id,{rating})} onAddAssets={addProjectAssets} ioBusy={ioCount>0} onRenameNode={node=>{setSelected(node.id);setSidebarRename({id:node.id,title:node.title})}} onDeleteProject={()=>setDeletion({kind:'project',id:projectId,title:projects.find(p=>p.id===projectId)?.title || '当前项目'})} onDeleteWorkflow={()=>setDeletion({kind:'workflow',id:workflow.id,title})} onPendingDeletions={()=>save().then(()=>setPendingDeletions(true)).catch(showError)} assetRefresh={assetRefresh} mediaRefresh={mediaRefresh} referenceTarget={interaction.selectedIds.length===1&&['image','video','audio'].includes(selectedNode?.type)?{id:selectedNode.id,title:selectedNode.title}:null} onAddReference={(assets,kinds)=>{const target=interaction.selectedIds.length===1?interaction.selectedIds[0]:null;if(!target)throw new Error('请先选择一个生成节点');return addProjectReferences(assets,kinds,target)}} revealMedia={revealMedia} uploadFolder={uploadFolder} onUploadFolder={setUploadFolder}/>:rail.panel==='prompts'?<CanvasPromptPanel onInsert={insertLibraryPrompt} insertDisabledReason={promptTarget?'':'请先选中一个生成节点'} targetLabel={promptTarget?.title||''}/>:<CanvasTaskPanel nodes={doc.nodes} onLocate={id=>locateNode(id)} onUnhandled={message=>notify?.(message,'info')}/>}</CanvasRailPanel>}
     <div className="cv-main" style={rail.panel&&!rail.pinned&&railPanelPx?{'--cv-float-panel':`${Math.round(railPanelPx)}px`}:undefined}>
    <header className="cv-topbar">{workflow && <input className="cv-project-name" aria-label="画布名称" title={title} value={title} onChange={e => { titleRef.current = e.target.value; setTitle(e.target.value); version.current += 1; contentVersion.current += 1; setSaveState('未保存') }} />}<span className="cv-spacer" /><div className="cv-edit-tools" role="group" aria-label="画布编辑">
      <button ref={moreTrigger} className="btn btn-icon" aria-label="更多画布操作" title="更多画布操作（复制／粘贴选区）" aria-haspopup="menu" aria-expanded={!!moreMenu} onClick={event=>setMoreMenu(moreMenu?null:menuPosition(event))}><MoreHorizontal size={16}/></button></div>
      {ioCount > 0 && <span className="cv-save-state" role="status">正在处理素材…</span>}<span className={`cv-save-state ${saveState === '保存失败' ? 'error' : ''}`} role="status" title={`自动保存 · ${canvasModifier()}+S 立即保存`}>{saveState}</span>{workflow && (saveState === '保存失败' || conflict) && <button className="cv-retry-save" onClick={() => {save().catch(showError);rootRef.current?.focus({preventScroll:true})}} disabled={conflict} title={conflict?'画布版本冲突，请先处理冲突提示':'重新尝试保存画布'}><RotateCw size={14} />重试保存</button>}</header>
    {moreMenu && <SidebarMenu label="更多画布操作" position={moreMenu} onClose={()=>setMoreMenu(null)} className="cv-more-menu"><button role="menuitem" aria-label="复制画布选区" title={`复制画布选区 (${canvasModifier()}+C)`} disabled={!interaction.selectedIds.length||ioCount>0||busy} onClick={()=>{copySelection();setMoreMenu(null);rootRef.current?.focus()}}><Copy size={14}/>复制选区<kbd>{canvasModifier()}+C</kbd></button><button role="menuitem" aria-label="粘贴画布选区" title={`粘贴画布选区 (${canvasModifier()}+V)`} disabled={!clipboard.current||ioCount>0||busy||conflict} onClick={()=>{pasteSelection();setMoreMenu(null);rootRef.current?.focus()}}><ClipboardPaste size={14}/>粘贴<kbd>{canvasModifier()}+V</kbd></button><button role="menuitemcheckbox" aria-checked={systemOn} disabled={permission==='unsupported'} title={permission==='unsupported'?'当前浏览器不支持系统通知':permission==='denied'?'浏览器已阻止本站通知，需在浏览器网站设置中允许':'页面在后台时用系统通知提醒任务完成'} onClick={()=>{setMoreMenu(null);if(systemOn)chooseSystem('off');else enableSystem()}}><Bell size={14}/>系统完成通知<kbd>{systemOn?'开':'关'}</kbd></button><button role="menuitem" onClick={()=>{setMoreMenu(null);setShortcutsOpen(true)}}><Keyboard size={14}/>快捷键帮助<kbd>?</kbd></button></SidebarMenu>}
    <div ref={rootRef} className={`cv-surface ${tool === 'pan' ? 'is-pan' : ''}`} tabIndex={0} aria-label="无限画布工作区" style={{ backgroundSize: `${24 * view.zoom}px ${24 * view.zoom}px`, backgroundPosition: `${view.x}px ${view.y}px` }} onContextMenu={e=>e.preventDefault()} onKeyDown={e=>{if(e.target===e.currentTarget && (e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')))openContextMenu(e)}} onPointerDown={startSurface} onPointerMove={event=>{lastPointer.current={x:event.clientX,y:event.clientY};movePointer(event)}} onPointerLeave={()=>{lastPointer.current=null}} onPointerUp={event=>{interaction.end(event);setGestureTick(value=>value+1)}} onPointerCancel={interaction.cancel} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if ([...e.dataTransfer.types].includes(PROJECT_ASSET_DRAG)) { dropProjectAssets(e); return } const type = e.dataTransfer.getData('application/x-ink-node'); if (['image','video','audio'].includes(type)) addNode(type, worldPoint(e.clientX, e.clientY)); else importFiles(e.dataTransfer.files, worldPoint(e.clientX, e.clientY)) }}>
      <style>{`#${CSS.escape(worldId)} :is(.cv-node-title, .cv-port, .cv-edge-hit, .cv-node-group header, .cv-node-run-mark) { --cv-zoom: ${Number(view.zoom)}; }`}</style>
      <div id={worldId} className={`cv-world ${view.zoom < LOD_ZOOM ? 'is-lod-low' : ''}`} style={{ transform: `translate(${view.x}px,${view.y}px) scale(${view.zoom})`, '--cv-zoom': view.zoom }}>
        <CanvasGroups groups={doc.groups} nodes={doc.nodes} edges={doc.edges} onLocateSource={locateNode} onUpload={id=>pickFile(id)} onLibrary={id=>{setSelected(id);openLibrary(id)}} disabled={busy||ioCount>0} onLocate={locateGroup} onRename={renameGroup} onColor={(group,color,label)=>edit(current=>({...current,groups:current.groups.map(item=>item.id===group.id?{...item,color}:item)}),{description:`节点组底色改为${label}`})} onUngroup={ungroup} onCopy={copyGroup} runFor={groupRun.runFor} onRun={group=>groupRun.start(group)} onCancelRun={groupRun.requestCancel} onDismissRun={groupRun.dismiss} onDrag={(event,group)=>{if(event.button===0){setFocusedGroup(group.id);interaction.choose(group.nodeIds);}const node=docRef.current.nodes.find(n=>group.nodeIds.includes(n.id));if(node)interaction.startNode(event,node)}}/><svg className="cv-connections">{doc.edges.map(edge => { const source = doc.nodes.find(n => n.id === edge.source), target = doc.nodes.find(n => n.id === edge.target); if (!source || !target) return null; const x1 = source.x + nodeGeometry(source).width, y1 = source.y + nodeGeometry(source).portY, x2 = target.x, y2 = target.y + (portMap.get(target.id)?.layout.edgeY.get(edge.id) ?? nodeGeometry(target).portY), bend = Math.max(80, Math.abs(x2 - x1) / 2), path = `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`; return <g key={edge.id} data-kind={nodeMediaKind(source)||undefined}><path className={`cv-edge ${selectedEdge === edge.id ? 'selected' : ''}`} d={path} /><path className="cv-edge-flow" d={path} pathLength="100" aria-hidden="true"/><path className="cv-edge-hit" d={path} onPointerDown={e => {if(e.button===2){interaction.startSurface(e);return} e.stopPropagation(); setSelectedEdge(edge.id); setSelected(null) }} /></g> })}{portDrag && (() => { const source = doc.nodes.find(n => n.id === portDrag.source); if (!source) return null; const x1 = source.x + nodeGeometry(source).width, y1 = source.y + nodeGeometry(source).portY, {x:x2,y:y2} = portDrag.point, bend = Math.max(60, Math.abs(x2 - x1) / 2); return <path className="cv-edge cv-edge-preview" data-testid="connection-preview" data-kind={nodeMediaKind(source)||undefined} d={`M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`} aria-hidden="true"/> })()}</svg>
        {doc.nodes.map(node => <CanvasNodeBoundary key={node.id} mediaStatusKey={mediaStatus.deletedKey} mediaSizeRevision={mediaSizeRevision} node={node} provider={nodeProvider(capabilities,node)} references={inputMap.get(node.id)?.assets || []} frames={inputMap.get(node.id)?.frames} selected={interaction.selectedIds.includes(node.id)} pendingConnection={connection} onSelect={event => { if(!ioRef.current)setSelected(node.id,event?.shiftKey); setSelectedEdge(null) }} resultUnknown={isUnknownResult(node)} statusAnomaly={statusAnomalies?.workflowId===workflow?.id?statusAnomalies.nodes.get(node.id):undefined} onSelectComplete={()=>{if(workflowRef.current?.id===workflow?.id)interaction.reveal(node.id)}} onDrag={(e,options) => startDrag(e, node,options)} onChange={patch => patchNode(node.id, patch)} onPort={(kind,target) => port(node.id, kind, target)} ports={portMap.get(node.id)?.derived} portLayout={portMap.get(node.id)?.layout} portWarnings={portMap.get(node.id)?.warnings} dragKind={portMap.get(node.id)?.dragKind||null} dragReason={portMap.get(node.id)?.dragReason} onPortsHover={portMap.get(node.id)?.layout.overflow?hovering=>setPortHover(current=>hovering?node.id:current===node.id?null:current):undefined} onExpandPorts={()=>{if(connection&&connection!==node.id){port(node.id,'input');return}setFocusedGroup(null);setSelectedEdge(null);interaction.selectSingle(node.id)}} onPortDrag={event => startPortDrag(event, node.id)} dropTarget={portDrag?.target === node.id} onRightDrag={event=>{stopViewAnimation();interaction.startSurface(event,node.id)}} onFocusZoom={()=>focusZoom(node.id)} onMenu={event=>openNodeMenu(node.id,event)} onPreview={()=>openPreview(node.id)} onHistory={()=>openNodeHistory(node.id,'node')} onAddReference={()=>{if(!ioRef.current)openLibrary(node.id)}} onLocate={()=>locateNode(node.id)} onOpenTask={task=>openTaskCenter(task,node.type)} runMark={groupRun.marks.get(node.id)} assetDeleted={isMediaAsset(node.asset)&&isDeletedMedia(node.asset.id)} onMediaError={()=>{if(isMediaAsset(node.asset))mediaStatus.recheck([node.asset.id])}} onReplaceDeleted={node.type==='asset'&&!ioCount?()=>replaceNodeAsset(node.id):null} onReplaceDeletedFromLibrary={node.type==='asset'&&!ioCount?()=>replaceNodeFromLibrary(node.id):null} onRemoveDeleted={()=>removeDeletedResult(node.id)} onResize={(scale,phase)=>resizeNode(node.id,scale,phase)} prompt={cardPrompt(node)} onPromptKey={shift=>{if(shift)focusPanel();else{if(panelPrefs.collapsed)panelPrefs.setCollapsed(false);activatePrompt(node.id)}}} />)}
      </div>
      {groupRun.element}
      {interaction.marquee && <div className="cv-selection-box" style={interaction.marquee}/>}
      {toolbarShown && (nodeToolbarKind(selectedNode)==='video'
        ?<CanvasNodeToolbar ref={toolbarRef} node={selectedNode} rect={nodeScreenRect(selectedNode,view)} surface={surfaceSize} busy={ioCount>0} label="视频操作" historyOpen={historyNode===selectedNode.id} captureNote={currentFrameNote(selectedNode.id)} onHistory={()=>openNodeHistory(selectedNode.id)} onCaptureCurrent={()=>captureFrame(selectedNode.id,false)} onCaptureTail={()=>captureFrame(selectedNode.id,true)} onPreview={()=>openPreview(selectedNode.id)} onDownload={()=>downloadAsset(selectedNode.asset).catch(showError)} onMore={event=>openNodeMenu(selectedNode.id,event)} onEscape={focusSelection}/>
        :<CanvasNodeToolbar ref={toolbarRef} node={selectedNode} rect={nodeScreenRect(selectedNode,view)} surface={surfaceSize} busy={ioCount>0} label="图片操作" historyOpen={historyNode===selectedNode.id} onEdit={()=>editNodeImage(selectedNode.id)} onRotate={()=>rotateNode(selectedNode.id)} onAnnotate={()=>annotateNode(selectedNode.id)} onDownload={()=>downloadAsset(selectedNode.asset).catch(showError)} onPreview={()=>openPreview(selectedNode.id)} onHistory={()=>openNodeHistory(selectedNode.id)} onMore={event=>openNodeMenu(selectedNode.id,event)} onEscape={focusSelection}/>)}
      {nodeMenu && <CanvasNodeMenu onPreview={contextNode?.asset?.url&&!contextDeleted&&['image','video','audio'].includes(mediaKind(contextNode))?()=>{const id=nodeMenu.id;setNodeMenu(null);openPreview(id)}:null} previewReason={contextNode?.type==='text'?'文本节点没有媒体内容':contextDeleted?'素材已在素材库中删除':'节点还没有生成或选择结果，暂无可预览内容'} isAsset={contextNode?.type==='asset'} deleteDisabled={contextDeleteBlocked} position={nodeMenu} bounds={surfaceSize} busy={ioCount>0} onClose={()=>setNodeMenu(null)} onCopy={()=>{const node=docRef.current.nodes.find(n=>n.id===nodeMenu.id);if(node)copyNode(node);setNodeMenu(null)}} onDelete={()=>{deleteNode(nodeMenu.id);setNodeMenu(null)}} onReplace={()=>replaceNodeAsset(nodeMenu.id)} onReplaceFromLibrary={()=>replaceNodeFromLibrary(nodeMenu.id)} {...(contextNode?.asset?.url&&!contextDeleted&&contextNode.asset.id&&mediaKind(contextNode)==='image'&&workflow?.id?{onAddToCharacter:()=>{setCharacterTarget({workflowId:workflow.id,asset:contextNode.asset});setNodeMenu(null)}}:{})} {...(contextNode?.asset?.id&&['image','video','audio'].includes(mediaKind(contextNode))&&!(isMediaAsset(contextNode.asset)&&isDeletedMedia(contextNode.asset.id))?{onRevealInLibrary:()=>revealInLibrary(contextNode.asset),onMoveToFolder:()=>{setMovingAssets([contextNode.asset]);setNodeMenu(null)}}:{})} {...((contextNode?.candidates?.length||0)>1?{onHistory:()=>openNodeHistory(nodeMenu.id,'node'),versionCount:contextNode.candidates.length}:{})} {...(contextLiveVersions.length>1?{onMoveAllVersions:()=>{setMovingAssets(contextLiveVersions);setNodeMenu(null)},liveVersionCount:contextLiveVersions.length}:{})} {...(contextNode?.asset?.url&&!contextDeleted&&mediaKind(contextNode)==='video'?{onCaptureTail:()=>captureFrame(nodeMenu.id,true),onCaptureCurrent:()=>captureFrame(nodeMenu.id,false),captureCurrentNote:currentFrameNote(nodeMenu.id)}:{})}/>}
      {historyNodeData && <CanvasVersionPopover node={historyNodeData} rect={nodeScreenRect(historyNodeData,view)} surface={surfaceSize} busy={ioCount>0} isGone={asset=>isMediaAsset(asset)&&isDeletedMedia(asset.id)} onChoose={asset=>chooseVersion(historyNodeData.id,asset)} onClose={closeHistory}/>}
      {imageEditing && createPortal(<React.Suspense fallback={<div className="cv-studio-overlay" role="status"><div>正在加载编辑器…</div></div>}><ImageAssetEditor asset={imageEditing.asset} onSave={file=>saveImageResult(imageEditing.owner,file)} onClose={closeImageEditor}/></React.Suspense>,document.body)}
      {annotation && <React.Suspense fallback={<div className="cv-studio-overlay" role="status">正在加载标注工具…</div>}><CanvasImageAnnotator key={annotation.asset.id} asset={annotation.asset} style={{zIndex:50}} onSave={file=>saveImageResult(annotation.owner,file)} onClose={closeAnnotation}/></React.Suspense>}
      {contextMenu && <CanvasContextMenu position={contextMenu} bounds={surfaceSize} onClose={closeContextMenu} onDismiss={()=>setContextMenu(null)} onUpload={()=>{const point=contextMenu.point;closeContextMenu();pickFile(null,point)}} onCreate={type=>{const point=contextMenu.point;closeContextMenu();addNode(type,point)}}/>}
      <div ref={toolsRef} className="cv-tools" style={toolsLeft==null?undefined:{left:toolsLeft,transform:'none'}} onPointerDown={e => e.stopPropagation()}><button title="选择节点" aria-label="选择工具" aria-pressed={tool === 'select'} onClick={() => setTool('select')}><MousePointer2 size={18} /></button><button title="平移画布（空格拖动）" aria-label="平移工具" aria-pressed={tool === 'pan'} onClick={() => setTool('pan')}><Hand size={18} /></button><hr />{[['image',Image],['video',Film],['audio',Music]].map(([type, Icon]) => <button key={type} draggable onDragStart={event => { event.dataTransfer.setData("application/x-ink-node", type); event.dataTransfer.effectAllowed = "copy" }} title={`添加${labels[type]}节点（可拖入画布）`} aria-label={`添加${labels[type]}节点`} onClick={() => addNode(type)}><Icon size={18} /></button>)}<hr /><button title="导入素材" aria-label="导入素材" onClick={() => pickFile()}><Upload size={18} /></button></div>
      {loading ? <div className="cv-empty">正在载入画布…</div> : !doc.nodes.length && <div className="cv-empty" onPointerDown={e => e.stopPropagation()}><h2>把想法放上画布</h2><p>拖入素材，连接参考，逐个制作你的镜头。</p><div className="cv-empty-actions"><button className="btn btn-primary" onClick={() => addNode('image')}><Image size={16} />图像生成</button><button onClick={() => addNode('video')}><Film size={16} />视频生成</button><button onClick={() => addNode('audio')}><Music size={16} />音频生成</button></div><small>节点自由摆放 · 连线选择参考 · 点击生成才运行任务</small></div>}
      {portDrag && <div className="cv-connection-note" role="status">{dropAnnouncement ? `${dropAnnouncement} · ` : ''}松开到目标节点上建立连接 · 松在空白处或按 Esc 取消</div>}{connection && !portDrag && <div className="cv-connection-note" onPointerDown={e => e.stopPropagation()}>点击目标节点建立连接<button onClick={() => setConnection(null)}>取消</button></div>}
      {selectedEdge && <div className="cv-connection-note" onPointerDown={e => e.stopPropagation()}><button onClick={() => deleteEdge(selectedEdge)}><Trash2 size={13} />移除连接</button></div>}
      <CanvasViewportTools zoom={view.zoom} onZoomIn={()=>zoomAt(1.2)} onZoomOut={()=>zoomAt(1/1.2)} onZoomTo={value=>zoomAt(value/docRef.current.viewport.zoom)} onFit={fit} onOrganize={organize} organizeDisabled={!doc.nodes.length||busy||ioCount>0||generationCount>0||!!conflict} canUndo={!!editHistory.current.past.length&&!ioCount&&!busy&&!conflict} canRedo={!!editHistory.current.future.length&&!ioCount&&!busy&&!conflict} undoDescription={undoDescription} redoDescription={redoDescription} onUndo={()=>{travelHistory();rootRef.current?.focus()}} onRedo={()=>{travelHistory(true);rootRef.current?.focus()}} onShortcuts={()=>setShortcutsOpen(true)} minimapOpen={minimapOpen} onToggleMinimap={value=>{setMinimapOpen(value);writeMinimapPreference(value)}}><CanvasMinimap nodes={doc.nodes} groups={doc.groups||[]} view={view} surface={surfaceSize} selectedIds={interaction.selectedIds} onViewChange={next=>{stopViewAnimation();edit(current=>({...current,viewport:{...current.viewport,x:next.x,y:next.y}}),{history:false})}} onFit={fit}/></CanvasViewportTools><span className="cv-hint">空格 + 拖动平移 · 滚轮缩放 · 连线不会自动生成</span>
      <TaskDoneNotices notices={doneNotices.filter(notice=>notice.workflowId===workflow?.id)} ask={askSystem&&shouldAskSystem({setting:systemSetting,permission})} onLocate={locateNotice} onDismiss={key=>setDoneNotices(current=>current.filter(item=>item.key!==key))} onEnable={enableSystem} onDecline={declineSystem}/>
      {!error&&alertDismissed!==`${pollWarning?.count||0}|${statusAnomalies?.nodes?.size||0}`&&((pollWarning&&pollWarning.workflowId===workflow?.id)||(statusAnomalies&&statusAnomalies.workflowId===workflow?.id))&&<div className="cv-alert cv-alert-stack" role="status" onPointerDown={e=>e.stopPropagation()}>{pollWarning&&pollWarning.workflowId===workflow?.id&&<span>{pollWarning.count} 个任务暂时无法更新，正在重试；其他任务继续更新。</span>}{statusAnomalies&&statusAnomalies.workflowId===workflow?.id&&<span data-testid="task-status-anomaly">{INVALID_STATUS_LABEL}：{statusAnomalies.nodes.size} 个任务返回未知状态（{[...new Set(statusAnomalies.nodes.values())].join('、').slice(0,60)}），已保留原状态，其他任务照常更新。</span>}<button aria-label="关闭提示" title="关闭提示" onClick={()=>setAlertDismissed(`${pollWarning?.count||0}|${statusAnomalies?.nodes?.size||0}`)}><X size={13} /></button></div>}
    {!error&&overlapCount>0&&<div className="cv-alert cv-alert-stack cv-alert-info" role="status" data-testid="overlap-notice" onPointerDown={e=>e.stopPropagation()}><span>{overlapCount} 个节点因按画面比例显示而相互重叠，可使用「整理画布」（可撤销）；不会自动移动节点。</span><span><button className="btn" onClick={organize} disabled={busy||ioCount>0||generationCount>0||!!conflict}>整理画布</button><button aria-label="关闭提示" title="关闭提示" onClick={()=>setOverlapCount(0)}><X size={13} /></button></span></div>}
    {error && <div className="cv-alert" role="alert" onPointerDown={e => e.stopPropagation()}><span>{error}</span><button aria-label="关闭提示" title="关闭提示" onClick={() => setError('')}><X size={13} /></button></div>}
    </div>
    </div><CanvasPropertiesPanel prefs={panelPrefs} content={panelContent} onFocusCanvas={focusSelection}/></div>
    {dialogNode && <CanvasPromptDialog key={dialogNode.id} node={dialogNode} inputAssets={dialogNode.id===selected?selectedAssets:inputMap.get(dialogNode.id)?.assets||[]} editor={dialogNode.id===selected?promptEditor:null} onText={text=>patchNode(dialogNode.id,{text})} onClose={()=>setPromptDialog(null)}/>}
    <input ref={fileRef} aria-label="导入画布素材文件" type="file" accept="image/*,video/*,audio/*" onChange={e => { importFiles([...e.target.files], uploadPoint.current, uploadTarget.current); e.target.value = '' }} />
    <input ref={replacementInput} aria-label="替换节点素材文件" type="file" onChange={e=>{const file=e.target.files[0],owner=replacementOwner.current;e.target.value='';if(file&&owner)saveAssetVersion(owner,file).catch(showError)}}/>
    {shortcutsOpen && <CanvasShortcutHelp onClose={()=>{setShortcutsOpen(false);rootRef.current?.focus()}} onClear={()=>{editHistory.current.clear();refreshHistory();setShortcutsOpen(false);rootRef.current?.focus()}}/>}
    {preview && <MediaPreview key={preview.id} asset={preview} onClose={closePreview}/>}
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
    {movingAssets && <CanvasMoveToFolder assets={movingAssets} onClose={()=>setMovingAssets(null)} onDone={text=>{setMovingAssets(null);notify?.(text,'success');setAssetRefresh(value=>value+1)}}/>}
    {characterTarget && <AddToCharacterDialog workflowId={characterTarget.workflowId} asset={characterTarget.asset} onClose={()=>setCharacterTarget(null)}/>}
    {libraryTarget && <CanvasLibrary initialSource={libraryOwner.current?.initialSource||'local'} projectId={libraryOwner.current?.projectId} onBeforeDelete={flushBeforeLibraryDelete} onDeleted={afterLibraryDelete} onClose={() => {setLibraryTarget(null);setAssetRefresh(value=>value+1)}} browseOnly={libraryTarget === '__browse__'} canAddToCanvas={!!libraryOwner.current?.workflowId} allowedKinds={doc.nodes.find(n=>n.id===libraryTarget)?.type==='image'?['image']:doc.nodes.find(n=>n.id===libraryTarget)?.type==='audio'?['image','audio']:['image','video','audio']} validateSelection={items=>{const node=docRef.current.nodes.find(n=>n.id===libraryTarget);if(node?.type==='video'&&node.params?.video_mode==='keyframe'){return items.some(item=>item.asset.kind!=='image')?'首尾帧仅支持图片':items.length>2?'首尾帧一次最多选择两张图片':null}return null}} onApply={async items => {
      const owner=libraryOwner.current
      if(!owner)return
      const target=owner.targetId==='__browse__'?null:owner.targetId
      if(workflowRef.current?.id!==owner.workflowId||target&&!docRef.current.nodes.some(n=>n.id===target))throw new Error('原画布或节点已切换，请重新打开素材库')
      if(ioRef.current||navigationRef.current)throw new Error('请等待当前操作完成')
      ioRef.current++;setIoCount(ioRef.current)
      try{const resolved=await libraryReferences(owner.workflowId,items);if(workflowRef.current?.id!==owner.workflowId||projectIdRef.current!==owner.projectId||target&&!docRef.current.nodes.some(n=>n.id===target))throw new Error('原画布已切换，未添加到其他画布');const currentNode=docRef.current.nodes.find(n=>n.id===target);if(currentNode?.type==='video'&&currentNode.params?.video_mode==='keyframe'){const current=resolveNodeInputs(currentNode,docRef.current.nodes,docRef.current.edges).assets,merged=[...new Map([...current,...resolved.assets].map(asset=>[asset.id,asset])).values()];if(merged.some(asset=>asset.kind!=='image')||merged.length>2)throw new Error('首尾帧最多两个图片参考，请先移除已有参考；本次未添加节点或连线')}addAssetNodes(resolved.assets||[],target);await save();setLibraryTarget(null);setAssetRefresh(value=>value+1)}finally{ioRef.current--;setIoCount(ioRef.current)}
    }} />}
    {replaceOwner && <CanvasLibrary key="replace-from-library" remote={false} projectId={replaceOwner.projectId} title="从素材库选择替换素材" applyLabel="替换节点素材" selectionLimit={1} allowedKinds={[replaceOwner.kind]} onBeforeDelete={flushBeforeLibraryDelete} onDeleted={afterLibraryDelete} onClose={()=>{setReplaceOwner(null);setAssetRefresh(value=>value+1)}} onApply={items=>applyLibraryReplacement(replaceOwner,items)} />}
    {batchPlan && <ConfirmDialog className="canvas-studio-confirm" title={batchPlan.ready.length?`运行 ${batchPlan.ready.length} 个所选节点？`:'没有可运行的节点'} confirmLabel={batchPlan.ready.length?`提交 ${batchPlan.ready.length} 个任务`:'关闭'} onClose={()=>setBatchPlan(null)} onConfirm={async()=>{const ids=batchPlan.ready.map(item=>item.node.id);setBatchPlan(null);if(ids.length)await runBatch(ids)}}><div data-testid="batch-run-summary"><p>将提交 <strong>{batchPlan.ready.length}</strong> 个节点，每个节点创建一个独立任务；不会自动运行下游节点。</p><p>合计预估：<strong>{batchPlan.ready.length?batchPlan.total.text:'—'}</strong>（按现有费率估算，非实际扣费）</p>{batchPlan.ready.length>0&&<ul>{batchPlan.ready.map(({node,cost})=><li key={node.id}>{node.title}：{cost.known?formatCostRange(cost.min,cost.max):`费用待估（${cost.reason}）`}</li>)}</ul>}{batchPlan.skipped.length>0&&<><p>以下 {batchPlan.skipped.length} 个节点不会提交：</p><ul>{batchPlan.skipped.map(({node,reason})=><li key={node.id}>{node.title}：{reason}</li>)}</ul></>}</div></ConfirmDialog>}
    {generateConfirm && <ConfirmDialog className="canvas-studio-confirm" title="上次结果未知，仍要重新生成？" danger confirmLabel="确认重新生成（可能重复计费）" onClose={()=>setGenerateConfirm(null)} onConfirm={async()=>{const id=generateConfirm;setGenerateConfirm(null);await generate(id)}}><p>该节点上一次任务的请求已发出但未确认结果，<strong>供应商可能已经计费</strong>。</p><p>重新生成会提交新的任务，<strong>可能重复计费</strong>。建议先到任务中心或供应商控制台核查原任务。</p></ConfirmDialog>}
    {draftOffer && !conflict && <div className="cv-studio-overlay"><div role="alertdialog" aria-modal="true" aria-labelledby="cv-draft-title" data-testid="canvas-draft-offer"><h3 id="cv-draft-title">有未保存的本地修改</h3><p>上次离开前（{new Date(draftOffer.draft.savedAt).toLocaleString()}）的修改未确认保存到服务器。{draftOffer.newer ? '服务器上已有之后保存的版本（可能来自其他窗口）；恢复会用本地修改替换当前内容（任务状态与生成结果保留服务器版本）。' : '恢复后会自动保存。'}</p><button onClick={discardDraft}>丢弃本地修改</button><button className="btn btn-primary" onClick={restoreDraft}>恢复本地修改</button></div></div>}
    {conflict && <div className="cv-studio-overlay"><div><h3>画布已在其他窗口更新</h3><p>本地编辑已保留，自动保存已停止。先下载本地记录，再载入服务器版本；重新载入会替换当前未保存内容。</p><button onClick={downloadLocal}>下载本地记录</button><button onClick={async () => { try { installWorkflow(await getCanvasWorkflow(workflowRef.current.id)); setError('') } catch (failure) { showError(failure) } }}>重新载入</button></div></div>}
  </section>
}
