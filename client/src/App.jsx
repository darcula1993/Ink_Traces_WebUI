import React, { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import TextToImage from './components/TextToImage'
const ImageToImage = lazyPanel(() => import('./components/ImageToImage'))
import ImageOutputControls from './components/image-parameters/ImageOutputControls'
import useImageDimensionDraft from './components/image-parameters/useImageDimensionDraft'
import {imageCapabilities,imageTabParams,imageTabPatch,imageParameterIssues,imageRequestFields,imageSizeSummary as getImageSizeSummary,isSeedream55,sanitizeImageTabForProvider} from './lib/imageGenerationRules'
const PromptCollection = lazyPanel(() => import('./components/PromptCollection'))
import TaskGallery from './components/TaskGallery'
import GlobalTaskCenter from './components/GlobalTaskCenter'
const PngInfoModal = lazyPanel(() => import('./components/PngInfoModal'))
import useModalFocus, { isTopModal } from './components/ui/useModalFocus'
const ReferenceMediaModal = lazyPanel(() => import('./components/ReferenceMediaModal'))
const ToolAssetLibrary = lazyPanel(() => import('./components/library/ToolAssetLibrary'))
import PromptMentionTextarea from './components/PromptMentionTextarea'
import SortableReferenceItem, { moveArrayItem } from './components/SortableReferenceItem'
import IconButton from './components/ui/IconButton'
import BrandMark from './components/ui/BrandMark'
import SegmentedControl from './components/ui/SegmentedControl'
import { RatioGlyph, imageRatioPrefix, PanelHeader, PanelSection, PanelField, PanelToggle, CollapsibleAdvanced, CostEstimateFooter } from './components/properties/PropertiesPrimitives'
import { motion, AnimatePresence } from 'framer-motion'
import ReactDOM from 'react-dom'
import { Play, Settings, Cpu, Grid3X3, X, Maximize2, Save, ImageDown, Film, LogOut, Check, Image as ImageIcon, Images, Library, ListTodo, Plus, AudioLines, CircleAlert, FileSearch, Layers3, Plug, Clock3, Mic, Music } from 'lucide-react'
import {videoCapabilities as getVideoCapabilities,videoDurations,videoRatio,videoRatioLabel,videoOutputSummary,VIDEO_RATIOS,VIDEO_AUTO_DURATION} from './lib/videoGenerationRules.js'
import { estimateBytePlusVideoCost, estimateImageParamsCost, formatUsdEstimate, formatWanTokens, IMAGE_PRICING } from './lib/byteplusPricing'
import { persistWorkspaceBlob, useWorkspaceObjectUrls, useWorkspaceState, workspaceImageFields } from './lib/useWorkspaceState'
import { initialTabMode, writeTabMode } from './lib/canvasLastLocation'
import { SEEDANCE_20, SEEDANCE_25, SEEDANCE_25_MODERATED, CUPSY_VIDEO_MODELS, CUPSY_AUDIO_MODEL, AUDIO_OUTPUT_FORMATS, AUDIO_SAMPLE_RATES, AUDIO_SPEAKERS, VIDEO_MODEL_CAPABILITIES } from './lib/generationSettings.js'
import {
  currentPromptMentionItems, restoredTaskReferences, isImageFile, isVideoFile, isAudioFile,
  readFileDataUrl, videoDropZoneHandlers, isDirectImageReferenceUrl, libraryItemToImageReference,
  libraryItemToVideoImageReference, libraryItemToVideoReference, libraryItemToVideoAudioReference,
  libraryItemToAudioToolReference, buildVideoGenerateSubmission, buildAudioReferencePayload,
} from './lib/referenceMedia.js'
import { makeImgTab, makeVideoTab, DEFAULT_AUDIO_FORM, IMAGE_WORKSPACE_OPTIONS, VIDEO_WORKSPACE_OPTIONS } from './lib/workspaceTabs.js'
import { TASK_CENTER_EVENT, TASK_CENTER_MODES } from './lib/taskCenterLink.js'
import { getToolCapabilities } from './lib/canvasApi.js'
import { resolveToolProvider, optionById, selectionFromOption, isVideoFastAvailable, toolSubmitProfileFields } from './lib/toolProviderSelection.js'
import { CANVAS_LOCATE_NODE_EVENT, CANVAS_RAIL_STATE_EVENT, LAYER_OPEN_SOURCE_EVENT, queueCanvasPngInfo, requestCanvasPngInfo, requestCanvasTogglePrompts, takePendingLayerSource } from './lib/canvasBridge.js'

// Keep loading boundaries local so navigation and existing forms stay usable.
function lazyPanel(load) {
  const Component = React.lazy(load)
  return function LazyPanel(props) {
    return <React.Suspense fallback={<div role="status" aria-label="正在加载" className="h-full w-full flex-1" />}><Component {...props} /></React.Suspense>
  }
}

axios.defaults.withCredentials = true

const LayerStudio = React.lazy(() => import('./components/LayerStudio'))
const CanvasStudio = React.lazy(() => import('./components/canvas/CanvasStudio'))
const ProviderSettings = React.lazy(() => import('./components/providers/ProviderSettings'))

const IMAGE_TOOL_ADVANCED_KEY = 'ink-traces.tool.image-advanced.v1'
const VIDEO_TOOL_ADVANCED_KEY = 'ink-traces.tool.video-advanced.v1'
const AUDIO_TOOL_ADVANCED_KEY = 'ink-traces.tool.audio-advanced.v1'
function ImageToolAdvanced(props) {
  return <CollapsibleAdvanced storageKey={IMAGE_TOOL_ADVANCED_KEY} {...props} />
}

function App({ onLogout }) {
  const handleLogout = async () => {
    await axios.post('/api/logout').catch(() => {})
    onLogout()
  }

  const [showPromptCollection, setShowPromptCollection] = useState(false)
  const [canvasRailPanel, setCanvasRailPanel] = useState(null)
  const [showGlobalLibrary, setShowGlobalLibrary] = useState(false)
  const [showPngInfo, setShowPngInfo] = useState(false)
  const [referenceMedia, setReferenceMedia] = useState(null)
  const [showFullEditor, setShowFullEditor] = useState(false)
  const [showEditorVault, setShowEditorVault] = useState(false)
  const [showCupsyAssets, setShowCupsyAssets] = useState(false)
  const libraryOwner=useRef(null),libraryContext=useRef(null)
  const [showProviderSettings, setShowProviderSettings] = useState(false)
  const [providerRevision, setProviderRevision] = useState(0)
  const [notification, setNotification] = useState(null)
  const notificationTimer = useRef(null)
  const [appMode, setTabAppMode] = useState(initialTabMode)
  const [globalTaskCenterType, setGlobalTaskCenterType] = useState('all')
  const appShellRef = useRef(null)

  const notify = useCallback((message, tone = 'success') => {
    window.clearTimeout(notificationTimer.current)
    setNotification({ message, tone })
    notificationTimer.current = window.setTimeout(() => setNotification(null), 2800)
  }, [])

  useEffect(() => () => window.clearTimeout(notificationTimer.current), [])

  useEffect(() => {
    const shell = appShellRef.current
    if (!shell || appMode === 'canvas' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined
    let frameId = null

    const updateHighlight = (event) => {
      cancelAnimationFrame(frameId)
      frameId = requestAnimationFrame(() => {
        const rect = shell.getBoundingClientRect()
        shell.style.setProperty('--glass-light-x', `${((event.clientX - rect.left) / rect.width) * 100}%`)
        shell.style.setProperty('--glass-light-y', `${((event.clientY - rect.top) / rect.height) * 100}%`)
      })
    }

    shell.addEventListener('pointermove', updateHighlight, { passive: true })
    return () => {
      shell.removeEventListener('pointermove', updateHighlight)
      cancelAnimationFrame(frameId)
    }
  }, [appMode])

  const [apiProvider, setApiProvider] = useState('ark')
  const [providerInfoReady, setProviderInfoReady] = useState(false)
  const [imageProviders, setImageProviders] = useState({})
  const [toolCapabilities, setToolCapabilities] = useState({ image: [], video: [], audio: [] })
  const [toolRawProviders, setToolRawProviders] = useState({ image: null, video: null, audio: null, saved: null })
  const [capabilitiesReady, setCapabilitiesReady] = useState(false)
  const capabilitiesFetchSeq = useRef(0)

  // 图片生成表单。沿用旧 workspace key，在加载后收敛为单一表单。
  const [imgTabs, setImgTabs, imgWorkspace] = useWorkspaceState('img_tabs', [makeImgTab(1)], IMAGE_WORKSPACE_OPTIONS)
  const [activeImgTabId, setActiveImgTabId] = useWorkspaceState('img_activeTab', 1)

  const activeImgTab = imgTabs.find(t => t.id === activeImgTabId) || imgTabs[0] || makeImgTab(1)
  const createReferencePreview = useWorkspaceObjectUrls([imgTabs, referenceMedia])

  const updateImgTab = useCallback((id, updates) => {
    setImgTabs(prev => prev.map(t => {
      if (t.id !== id) return t
      const resolvedUpdates = typeof updates === 'function' ? updates(t) : updates
      return { ...t, ...resolvedUpdates }
    }))
  }, [setImgTabs])

  // 顶部模式切换：image / video / audio
  // WINDOW-PROJECT-20261114: the server appMode is still written on every switch, but it no longer
  // decides where a fresh tab lands: a new tab always opens the canvas (user decision 11-14);
  // a reload keeps this tab's own tool.
  const [, setServerAppMode] = useWorkspaceState('appMode', 'canvas')
  const setAppMode = useCallback(mode => { setTabAppMode(mode); writeTabMode(mode); setServerAppMode(mode) }, [setServerAppMode])
  const canvasBeforeLeave = useRef(null), modeSwitchPending = useRef(false)
  async function changeAppMode(mode) {
    if (mode === appMode) return true
    if (modeSwitchPending.current) return false
    modeSwitchPending.current = true
    try {
      if (appMode === 'canvas' && canvasBeforeLeave.current && !await canvasBeforeLeave.current()) return false
      setAppMode(mode)
      return true
    } catch (error) { notify(error?.message || '暂时无法切换工具，请重试', 'error'); return false }
    finally { modeSwitchPending.current = false }
  }
  // NODE-ECHO-20261115: canvas task number → that tool's task center; TaskGallery opens the pending task.
  const changeAppModeRef = useRef(changeAppMode)
  changeAppModeRef.current = changeAppMode
  useEffect(() => {
    const open = event => {
      const type = event.detail?.type
      if (type === 'tasks' || type === 'all') {
        event.preventDefault()
        setGlobalTaskCenterType('all')
        changeAppModeRef.current('tasks')
        return
      }
      if (type === 'layer') {
        event.preventDefault()
        setGlobalTaskCenterType('layer')
        changeAppModeRef.current('tasks')
        return
      }
      if (!TASK_CENTER_MODES.includes(type)) return
      event.preventDefault()
      changeAppModeRef.current(type)
    }
    const locateCanvas = event => { if (!event.detail?.target?.workflowId) return; event.preventDefault(); changeAppModeRef.current('canvas') }
    const onRailState = event => { setCanvasRailPanel(event.detail?.panel || null) }
    const onOpenLayer = event => {
      event.preventDefault()
      Promise.resolve(changeAppModeRef.current('layer')).then(switched => {
        if (!switched) takePendingLayerSource()
      })
    }
    window.addEventListener(TASK_CENTER_EVENT, open)
    window.addEventListener(CANVAS_LOCATE_NODE_EVENT, locateCanvas)
    window.addEventListener(CANVAS_RAIL_STATE_EVENT, onRailState)
    window.addEventListener(LAYER_OPEN_SOURCE_EVENT, onOpenLayer)
    return () => {
      window.removeEventListener(TASK_CENTER_EVENT, open)
      window.removeEventListener(CANVAS_LOCATE_NODE_EVENT, locateCanvas)
      window.removeEventListener(CANVAS_RAIL_STATE_EVENT, onRailState)
      window.removeEventListener(LAYER_OPEN_SOURCE_EVENT, onOpenLayer)
    }
  }, [])
  useEffect(() => {
    if (appMode === 'canvas') setShowPromptCollection(false)
  }, [appMode])


  const [videoFastAvailable, setVideoFastAvailable] = useState(false)
  const [videoProviders, setVideoProviders] = useState({ ark: { available: true }, cupsy: { available: false, source_ready: false } })

  // 视频生成表单。沿用旧 workspace key，在加载后收敛为单一表单。
  const [videoTabs, setVideoTabs, videoWorkspace] = useWorkspaceState('vid_tabs', [makeVideoTab(1)], VIDEO_WORKSPACE_OPTIONS)
  const [activeVideoTabId, setActiveVideoTabId] = useWorkspaceState('vid_activeTab', 1)

  const activeTab = videoTabs.find(t => t.id === activeVideoTabId) || videoTabs[0] || makeVideoTab(1)

  const updateTab = useCallback((id, updates) => {
    setVideoTabs(prev => prev.map(t => {
      if (t.id !== id) return t
      const resolvedUpdates = typeof updates === 'function' ? updates(t) : updates
      return { ...t, ...resolvedUpdates }
    }))
  }, [setVideoTabs])

  const [storedAudioForm, setStoredAudioForm] = useWorkspaceState('audio_form', DEFAULT_AUDIO_FORM)
  const audioForm = { ...DEFAULT_AUDIO_FORM, ...(storedAudioForm || {}) }
  const updateAudioForm = useCallback((updates) => {
    setStoredAudioForm(previous => {
      const current = { ...DEFAULT_AUDIO_FORM, ...(previous || {}) }
      const resolved = typeof updates === 'function' ? updates(current) : updates
      return { ...current, ...resolved }
    })
  }, [setStoredAudioForm])
  const [audioProvider, setAudioProvider] = useState({ available: false, sourceReady: false })
  const [audioUploading, setAudioUploading] = useState(false)

  const videoSelectionState = resolveToolProvider(toolCapabilities, 'video', {
    selection: activeTab.providerSelection,
    legacyProvider: activeTab.providerSelection ? null : activeTab.provider,
    ready: capabilitiesReady,
  })
  const activeVideoOption = videoSelectionState.option
  const activeVideoProvider = activeVideoOption?.provider || activeTab.providerSelection?.provider || (activeTab.provider === 'cupsy' ? 'cupsy' : 'ark')
  const activeVideoFastAvailable = activeVideoOption
    ? isVideoFastAvailable(activeVideoOption, toolRawProviders.video, toolRawProviders.saved?.profiles)
    : videoFastAvailable
  const audioSelectionState = resolveToolProvider(toolCapabilities, 'audio', {
    selection: audioForm.providerSelection,
    ready: capabilitiesReady,
  })
  const activeAudioOption = audioSelectionState.option
  const effectiveVideoModel = activeVideoProvider === 'cupsy'
    ? (CUPSY_VIDEO_MODELS.includes(activeTab.model) ? activeTab.model : SEEDANCE_25)
    : activeTab.model === SEEDANCE_25 ? SEEDANCE_25 : SEEDANCE_20
  const isSeedance25 = CUPSY_VIDEO_MODELS.includes(effectiveVideoModel)
  const videoCapabilities = getVideoCapabilities(effectiveVideoModel)
  const videoDurationOptions = videoDurations(effectiveVideoModel).filter(value=>value!==VIDEO_AUTO_DURATION)
  const hasReadyReferenceVideo = activeTab.refVideos.some(video => video.url && !video.uploading)
  const ratioState=videoRatio(effectiveVideoModel,activeTab.mode,Boolean(activeTab.firstFrame||activeTab.lastFrame),activeTab.ratio)
  const videoRatioLocked=ratioState.locked,effectiveVideoRatio=ratioState.value
  const effectiveVideoDuration = activeTab.duration

  const handleVideoModelChange = useCallback((model) => {
    const nextModel = activeVideoProvider === 'cupsy'
      ? (model === SEEDANCE_25_MODERATED ? SEEDANCE_25_MODERATED : SEEDANCE_25)
      : model === SEEDANCE_25 ? SEEDANCE_25 : SEEDANCE_20
    updateTab(activeTab.id, tab => {
      const capabilities = VIDEO_MODEL_CAPABILITIES[
        nextModel === SEEDANCE_25_MODERATED ? SEEDANCE_25 : nextModel
      ]
      const nextIsSeedance25 = CUPSY_VIDEO_MODELS.includes(nextModel)
      const duration = activeVideoProvider === 'cupsy'
        ? tab.duration === -1
          ? -1
          : Math.max(capabilities.minDuration, Math.min(capabilities.maxDuration, tab.duration))
        : nextIsSeedance25 ? -1
        : tab.duration !== -1 && tab.duration > capabilities.maxDuration
          ? capabilities.maxDuration
          : tab.duration
      const resolution = capabilities.resolutions.includes(tab.resolution) ? tab.resolution : '720p'
      const ratio = nextIsSeedance25
        && tab.mode === 'keyframe'
        && (tab.firstFrame || tab.lastFrame)
        ? 'adaptive'
        : tab.ratio
      return {
        model: nextModel,
        duration,
        resolution,
        ratio,
        fast: nextIsSeedance25 ? false : tab.fast,
        outputFormat: activeVideoProvider === 'ark' && nextIsSeedance25 && tab.outputFormat === 'mov' ? 'mov' : 'mp4',
      }
    })
  }, [activeTab.id, activeVideoProvider, updateTab])

  const handleVideoProviderChange = useCallback((optionId) => {
    const option = optionById(toolCapabilities, 'video', optionId)
    if (!option) return
    const provider = option.provider
    const selection = selectionFromOption(option)
    const nextFastAvailable = isVideoFastAvailable(option, toolRawProviders.video, toolRawProviders.saved?.profiles)
    updateTab(activeTab.id, tab => provider === 'cupsy' ? {
      provider: 'cupsy',
      providerSelection: selection,
      model: CUPSY_VIDEO_MODELS.includes(tab.model) ? tab.model : SEEDANCE_25,
      duration: tab.duration,
      resolution: VIDEO_MODEL_CAPABILITIES[SEEDANCE_25].resolutions.includes(tab.resolution)
        ? tab.resolution
        : '720p',
      fast: false, outputFormat: 'mp4', returnLastFrame: false,
    } : {
      provider: 'ark',
      providerSelection: selection,
      model: tab.model === SEEDANCE_20 ? SEEDANCE_20 : SEEDANCE_25,
      ...(nextFastAvailable ? {} : { fast: false }),
    })
  }, [activeTab.id, toolCapabilities, toolRawProviders.saved, toolRawProviders.video, updateTab])

  const handleAudioProviderChange = useCallback((optionId) => {
    const option = optionById(toolCapabilities, 'audio', optionId)
    if (!option) return
    updateAudioForm({ providerSelection: selectionFromOption(option) })
  }, [toolCapabilities, updateAudioForm])

  const moveVideoReference = useCallback((tabId, field, fromIndex, toIndex) => {
    setVideoTabs(prev => prev.map(tab => tab.id === tabId ? {
      ...tab,
      [field]: moveArrayItem(tab[field], fromIndex, toIndex),
    } : tab))
  }, [setVideoTabs])

  libraryContext.current={mode:appMode,imageId:activeImgTab.id,videoId:activeTab.id}
  function openToolLibrary(){libraryOwner.current={...libraryContext.current};setShowCupsyAssets(true)}
  function validateLibraryReferences(items){
    const counts=Object.fromEntries(['image','video','audio'].map(kind=>[kind,items.filter(item=>item.asset.kind===kind).length]))
    if(appMode==='image')return counts.video||counts.audio?'图片生成只支持图片参考':counts.image+(activeImgTab.uploadedImages?.length||0)>(isSeedream?10:14)?'参考图片数量超过当前模型上限':null
    if(appMode==='audio'){if(counts.video||counts.image&&counts.audio)return '音频仅支持图片或音频参考，不能混用';const kind=counts.image?'image':'audio';if(audioForm.referenceMode!=='none'&&audioForm.referenceMode!==kind)return '请先清空另一种参考素材';return items.length+audioForm.references.length>(kind==='image'?1:3-(audioForm.speaker?1:0))?'参考数量超过当前音频模式上限':null}
    if(activeTab.mode==='keyframe')return counts.video||counts.audio?'首尾帧仅支持图片':counts.image+Number(!!activeTab.firstFrame)+Number(!!activeTab.lastFrame)>2?'首尾帧最多两张图片，请先移除已有参考':null
    const caps=getVideoCapabilities(activeTab.model);if(!caps)return '当前模型能力未知，请先选择视频模型';return counts.image+activeTab.refImages.length>caps.maxRefImages||counts.video+activeTab.refVideos.length>caps.maxRefVideos||counts.audio+activeTab.refAudios.length>caps.maxRefAudios?'参考数量超过当前模型上限':null
  }
  async function useLocalLibraryItems(items){
    const owner=libraryOwner.current,issue=validateLibraryReferences(items);if(issue)throw new Error(issue)
    if(!owner||Object.keys(owner).some(key=>owner[key]!==libraryContext.current[key]))throw new Error('原工具或表单已切换，请重新选择素材')
    const fetchAsFile=async item=>{const response=await fetch(item.asset.url);if(!response.ok)throw new Error('素材读取失败，请重新选择');return new File([await response.blob()],item.asset.name,{type:item.asset.mime_type||`${item.asset.kind}/*`})}
    if(owner.mode==='image'){
      const direct=items.map(item=>libraryItemToImageReference(item))
      const additions=direct.every(Boolean)
        ? direct
        : await Promise.all(items.map(async(item,index)=>{
            if(direct[index])return direct[index]
            const file=await fetchAsFile(item)
            return {uid:`library-${Date.now()}-${Math.random()}`,file,preview:createReferencePreview(file),name:file.name,hasAlpha:null}
          }))
      if(Object.keys(owner).some(key=>owner[key]!==libraryContext.current[key]))throw new Error('原工具或表单已切换，请重新选择素材')
      updateImgTab(owner.imageId,tab=>({uploadedImages:[...(tab.uploadedImages||[]),...additions]}))
      setShowCupsyAssets(false)
      return
    }
    if(owner.mode==='audio'){
      const direct=items.map(item=>libraryItemToAudioToolReference(item))
      if(direct.length&&direct.every(Boolean)){
        const kind=direct[0].kind
        updateAudioForm(form=>({referenceMode:kind,references:[...form.references,...direct]}))
        setShowCupsyAssets(false)
        return
      }
      const files=await Promise.all(items.map(fetchAsFile))
      if(Object.keys(owner).some(key=>owner[key]!==libraryContext.current[key]))throw new Error('原工具或表单已切换，请重新选择素材')
      if(!await addAudioReferences(files))throw new Error('参考素材上传失败，选择已保留，请重试')
      setShowCupsyAssets(false)
      return
    }
    if(activeTab.mode==='keyframe'){
      const direct=items.map(item=>libraryItemToVideoImageReference(item))
      if(direct.every(Boolean)){
        setVideoTabs(previous=>previous.map(tab=>{
          if(tab.id!==owner.videoId)return tab
          const available=[...direct]
          const firstFrame=tab.firstFrame||available.shift()||null
          const lastFrame=tab.lastFrame||available.shift()||null
          if(firstFrame===tab.firstFrame&&lastFrame===tab.lastFrame)return tab
          return {...tab,firstFrame,lastFrame,...(CUPSY_VIDEO_MODELS.includes(tab.model)?{ratio:'adaptive'}:{})}
        }))
        setShowCupsyAssets(false)
        return
      }
      const files=await Promise.all(items.map(fetchAsFile))
      if(Object.keys(owner).some(key=>owner[key]!==libraryContext.current[key]))throw new Error('原工具或表单已切换，请重新选择素材')
      addPastedKeyframes(owner.videoId,files)
      setShowCupsyAssets(false)
      return
    }
    const directMapped=items.map(item=>{
      if(item.asset?.kind==='image')return {kind:'image',ref:libraryItemToVideoImageReference(item)}
      if(item.asset?.kind==='video')return {kind:'video',ref:libraryItemToVideoReference(item)}
      if(item.asset?.kind==='audio')return {kind:'audio',ref:libraryItemToVideoAudioReference(item)}
      return {kind:item.asset?.kind,ref:null}
    })
    if(directMapped.every(entry=>entry.ref)){
      const directImages=directMapped.filter(e=>e.kind==='image').map(e=>e.ref)
      const directVideos=directMapped.filter(e=>e.kind==='video').map(e=>e.ref)
      const directAudios=directMapped.filter(e=>e.kind==='audio').map(e=>e.ref)
      setVideoTabs(previous=>previous.map(tab=>{
        if(tab.id!==owner.videoId)return tab
        const caps=getVideoCapabilities(tab.model)||VIDEO_MODEL_CAPABILITIES[SEEDANCE_20]
        const nextImages=directImages.length?[...tab.refImages,...directImages.slice(0,Math.max(0,caps.maxRefImages-tab.refImages.length))]:tab.refImages
        const nextVideos=directVideos.length?[...tab.refVideos,...directVideos.slice(0,Math.max(0,caps.maxRefVideos-tab.refVideos.length))]:tab.refVideos
        const nextAudios=directAudios.length?[...tab.refAudios,...directAudios.slice(0,Math.max(0,caps.maxRefAudios-tab.refAudios.length))]:tab.refAudios
        return {...tab,refImages:nextImages,refVideos:nextVideos,refAudios:nextAudios}
      }))
      setShowCupsyAssets(false)
      return
    }
    const files=await Promise.all(items.map(fetchAsFile))
    if(Object.keys(owner).some(key=>owner[key]!==libraryContext.current[key]))throw new Error('原工具或表单已切换，请重新选择素材')
    const images=files.filter(isImageFile),videos=files.filter(isVideoFile),audios=files.filter(isAudioFile);if(images.length)addVideoReferenceImages(owner.videoId,images);if(videos.length)addVideoReferenceVideos(owner.videoId,videos);if(audios.length)addVideoReferenceAudios(owner.videoId,audios)
    setShowCupsyAssets(false)
  }

  const useCupsyAsset = useCallback((asset, role) => {
    if (appMode === 'audio') {
      if (!['audio', 'image'].includes(asset.kind)) {
        notify('音频生成仅支持音频或图片参考', 'error')
        return
      }
      const nextMode = asset.kind
      if (audioForm.referenceMode !== 'none' && audioForm.referenceMode !== nextMode) {
        notify('音频参考与图片参考不能混用', 'error')
        return
      }
      const limit = nextMode === 'image' ? 1 : Math.max(0, 3 - (audioForm.speaker ? 1 : 0))
      if (audioForm.references.some(item => item.cupsyAssetId === asset.id)) return
      if (audioForm.references.length >= limit) {
        notify(nextMode === 'image' ? '图片参考只能添加 1 张' : '最多使用 3 个音频或声线参考', 'error')
        return
      }
      updateAudioForm(form => ({
        referenceMode: nextMode,
        references: [...form.references, {
          cupsyAssetId: asset.id,
          kind: asset.kind,
          name: asset.name || `Asset ${asset.id}`,
          preview: asset.content_url,
          status: asset.status,
        }],
      }))
      notify('素材已引用')
      return
    }
    const common = {
      cupsyAssetId: asset.id,
      name: asset.name || `Asset ${asset.id}`,
      preview: asset.content_url,
    }
    updateTab(activeTab.id, tab => {
      if (role === 'first_frame') return { firstFrame: { ...common, file: null } }
      if (role === 'last_frame') return { lastFrame: { ...common, file: null } }
      if (role === 'reference_image') {
        if (tab.refImages.some(item => item.cupsyAssetId === asset.id)) return {}
        return { refImages: [...tab.refImages, { ...common, file: null }] }
      }
      if (role === 'reference_video') {
        if (tab.refVideos.some(item => item.cupsyAssetId === asset.id)) return {}
        return { refVideos: [...tab.refVideos, { ...common, uid: `cupsy-${asset.id}`, url: asset.content_url, uploading: false }] }
      }
      if (role === 'reference_audio') {
        if (tab.refAudios.some(item => item.cupsyAssetId === asset.id)) return {}
        return { refAudios: [...tab.refAudios, { ...common, file: null }] }
      }
      return {}
    })
    notify('素材已引用')
  }, [activeTab.id, appMode, audioForm.referenceMode, audioForm.references, audioForm.speaker, notify, updateAudioForm, updateTab])

  async function useRemoteLibraryItems(items){
    const owner=libraryOwner.current,issue=validateLibraryReferences(items)
    if(issue)throw new Error(issue)
    if(!owner||Object.keys(owner).some(key=>owner[key]!==libraryContext.current[key]))throw new Error('原工具或表单已切换，请重新选择素材')
    const roles=activeTab.firstFrame?['last_frame']:['first_frame','last_frame']
    for(const [index,item] of items.entries())useCupsyAsset(item.remote,appMode==='video'&&activeTab.mode==='keyframe'?roles[index]:`reference_${item.asset.kind}`)
    setShowCupsyAssets(false)
  }

  const setVideoKeyframeFile = useCallback((tabId, field, files) => {
    const file = Array.from(files || []).find(isImageFile)
    if (!file) {
      notify('关键帧仅支持图片文件', 'error')
      return
    }
    readFileDataUrl(file).then(preview => {
      setVideoTabs(previous => previous.map(tab => tab.id === tabId ? {
        ...tab,
        [field]: { file, preview, name: file.name },
        ...(CUPSY_VIDEO_MODELS.includes(tab.model) ? { ratio: 'adaptive' } : {}),
      } : tab))
    }).catch(() => notify('关键帧图片读取失败', 'error'))
  }, [notify, setVideoTabs])

  const addPastedKeyframes = useCallback((tabId, files) => {
    const accepted = Array.from(files || []).filter(isImageFile).slice(0, 2)
    if (!accepted.length) return
    Promise.all(accepted.map(async file => ({ file, name: file.name, preview: await readFileDataUrl(file) })))
      .then(items => {
        setVideoTabs(previous => previous.map(tab => {
          if (tab.id !== tabId) return tab
          const available = [...items]
          const firstFrame = tab.firstFrame || available.shift() || null
          const lastFrame = tab.lastFrame || available.shift() || null
          if (firstFrame === tab.firstFrame && lastFrame === tab.lastFrame) return tab
          return {
            ...tab,
            firstFrame,
            lastFrame,
            ...(CUPSY_VIDEO_MODELS.includes(tab.model) ? { ratio: 'adaptive' } : {}),
          }
        }))
      })
      .catch(() => notify('关键帧图片读取失败', 'error'))
  }, [notify, setVideoTabs])

  const addVideoReferenceImages = useCallback((tabId, files) => {
    const accepted = Array.from(files || []).filter(isImageFile)
    if (!accepted.length) {
      notify('此区域仅支持图片文件', 'error')
      return
    }
    Promise.all(accepted.map(async file => ({ file, name: file.name, preview: await readFileDataUrl(file) })))
      .then(items => {
        setVideoTabs(previous => previous.map(tab => {
          if (tab.id !== tabId) return tab
          const model = CUPSY_VIDEO_MODELS.includes(tab.model) ? SEEDANCE_25 : SEEDANCE_20
          const remaining = VIDEO_MODEL_CAPABILITIES[model].maxRefImages - tab.refImages.length
          if (remaining <= 0) return tab
          return { ...tab, refImages: [...tab.refImages, ...items.slice(0, remaining)] }
        }))
      })
      .catch(() => notify('参考图片读取失败', 'error'))
  }, [notify, setVideoTabs])

  const updateReferenceVideo = useCallback((tabId, uid, updates) => {
    setVideoTabs(previous => previous.map(tab => tab.id === tabId ? {
      ...tab,
      refVideos: tab.refVideos.map(video => video.uid === uid ? { ...video, ...updates } : video),
    } : tab))
  }, [setVideoTabs])

  const uploadReferenceVideo = useCallback((tabId, uid, file) => {
    const video = document.createElement('video')
    const objectUrl = URL.createObjectURL(file)
    const releasePreview = () => URL.revokeObjectURL(objectUrl)
    video.preload = 'metadata'
    video.muted = true
    video.src = objectUrl
    video.onloadedmetadata = () => {
      const duration = Number.isFinite(video.duration) ? Math.round(video.duration * 100) / 100 : null
      updateReferenceVideo(tabId, uid, { duration })
      video.currentTime = Math.min(0.1, Math.max(0, (duration || 0) / 2))
    }
    video.onseeked = () => {
      const canvas = document.createElement('canvas')
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      canvas.getContext('2d')?.drawImage(video, 0, 0)
      updateReferenceVideo(tabId, uid, { thumbnail: canvas.toDataURL('image/jpeg', 0.6) })
      releasePreview()
    }
    video.onerror = releasePreview

    const body = new FormData()
    body.append('file', file)
    axios.post('/api/upload_video', body, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: event => {
        const progress = event.total ? Math.round((event.loaded / event.total) * 100) : 0
        updateReferenceVideo(tabId, uid, { progress })
      },
    }).then(response => {
      if (!response.data.success) throw new Error(response.data.error || '上传失败')
      updateReferenceVideo(tabId, uid, {
        url: response.data.url,
        filepath: response.data.filepath,
        progress: 100,
        uploading: false,
      })
    }).catch(error => {
      setVideoTabs(previous => previous.map(tab => tab.id === tabId ? {
        ...tab,
        refVideos: tab.refVideos.filter(videoItem => videoItem.uid !== uid),
      } : tab))
      notify(error.response?.data?.error || error.message || '参考视频上传失败', 'error')
    })
  }, [notify, setVideoTabs, updateReferenceVideo])

  const addVideoReferenceVideos = useCallback((tabId, files) => {
    const accepted = Array.from(files || []).filter(isVideoFile)
    if (!accepted.length) {
      notify('此区域仅支持 MP4 或 MOV 视频', 'error')
      return
    }
    const tab = videoTabs.find(item => item.id === tabId)
    if (!tab) return
    const model = CUPSY_VIDEO_MODELS.includes(tab.model) ? SEEDANCE_25 : SEEDANCE_20
    const remaining = VIDEO_MODEL_CAPABILITIES[model].maxRefVideos - tab.refVideos.length
    const selected = accepted.slice(0, Math.max(0, remaining))
    if (!selected.length) return
    const batchId = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    const items = selected.map((file, index) => ({
      uid: `${batchId}_${index}`,
      name: file.name,
      url: null,
      thumbnail: null,
      progress: 0,
      uploading: true,
    }))
    setVideoTabs(previous => previous.map(item => item.id === tabId ? {
      ...item,
      refVideos: [...item.refVideos, ...items],
    } : item))
    selected.forEach((file, index) => uploadReferenceVideo(tabId, items[index].uid, file))
  }, [notify, setVideoTabs, uploadReferenceVideo, videoTabs])

  const addVideoReferenceAudios = useCallback((tabId, files) => {
    const accepted = Array.from(files || []).filter(isAudioFile)
    if (!accepted.length) {
      notify('此区域仅支持 WAV 或 MP3 音频', 'error')
      return
    }
    setVideoTabs(previous => previous.map(tab => {
      if (tab.id !== tabId) return tab
      const model = CUPSY_VIDEO_MODELS.includes(tab.model) ? SEEDANCE_25 : SEEDANCE_20
      const remaining = VIDEO_MODEL_CAPABILITIES[model].maxRefAudios - tab.refAudios.length
      if (remaining <= 0) return tab
      return {
        ...tab,
        refAudios: [
          ...tab.refAudios,
          ...accepted.slice(0, remaining).map(file => ({ file, name: file.name })),
        ],
      }
    }))
  }, [notify, setVideoTabs])

  const addAudioReferences = useCallback(async (files) => {
    const selected = Array.from(files || [])
    const imageFiles = selected.filter(isImageFile)
    const audioFiles = selected.filter(isAudioFile)
    if (!imageFiles.length && !audioFiles.length) {
      notify('仅支持图片、WAV 或 MP3 参考素材', 'error')
      return
    }
    if (imageFiles.length && audioFiles.length) {
      notify('音频参考与图片参考不能混用', 'error')
      return
    }
    const kind = imageFiles.length ? 'image' : 'audio'
    if (audioForm.referenceMode !== 'none' && audioForm.referenceMode !== kind) {
      notify('请先清空另一种参考素材', 'error')
      return
    }
    const candidates = kind === 'image' ? imageFiles.slice(0, 1) : audioFiles
    const limit = kind === 'image' ? 1 : Math.max(0, 3 - (audioForm.speaker ? 1 : 0))
    const remaining = limit - audioForm.references.length
    if (remaining <= 0) {
      notify(kind === 'image' ? '图片参考只能添加 1 张' : '最多使用 3 个音频或声线参考', 'error')
      return
    }
    setAudioUploading(true)
    try {
      const uploaded = []
      for (const file of candidates.slice(0, remaining)) {
        const body = new FormData()
        body.append('file', file)
        body.append('kind', kind)
        if (activeAudioOption?.profile_id) body.append('profile_id', activeAudioOption.profile_id)
        const response = await axios.post('/api/cupsy/assets', body, { timeout: 300000 })
        const asset = response.data.asset
        uploaded.push({
          cupsyAssetId: asset.id,
          kind,
          name: asset.name || file.name,
          preview: asset.content_url,
          status: asset.status,
        })
      }
      updateAudioForm(form => ({
        referenceMode: kind,
        references: [...form.references, ...uploaded],
      }))
      notify(`${uploaded.length} 个参考素材已加入 Cupsy Assets`)
      return true
    } catch (error) {
      notify(error.response?.data?.error || '参考素材上传失败', 'error')
      return false
    } finally {
      setAudioUploading(false)
    }
  }, [activeAudioOption?.profile_id, audioForm.referenceMode, audioForm.references.length, audioForm.speaker, notify, updateAudioForm])
  const [taskGalleryRevision, setTaskGalleryRevision] = useState(0)

  useEffect(() => {
    if (!imgWorkspace.ready || imgTabs.length <= 1) return
    const selected = imgTabs.find(tab => Number(tab.id) === Number(activeImgTabId)) || imgTabs[0]
    setImgTabs([selected])
    setActiveImgTabId(selected.id)
  }, [activeImgTabId, imgTabs, imgWorkspace.ready, setActiveImgTabId, setImgTabs])

  useEffect(() => {
    if (!videoWorkspace.ready || videoTabs.length <= 1) return
    const selected = videoTabs.find(tab => Number(tab.id) === Number(activeVideoTabId)) || videoTabs[0]
    setVideoTabs([selected])
    setActiveVideoTabId(selected.id)
  }, [activeVideoTabId, setActiveVideoTabId, setVideoTabs, videoTabs, videoWorkspace.ready])

  const imageSelectionState = resolveToolProvider(toolCapabilities, 'image', {
    selection: activeImgTab.providerSelection,
    sessionProvider: apiProvider,
    ready: capabilitiesReady,
  })
  const activeImageOption = imageSelectionState.option
  const effectiveImageProvider = activeImageOption?.provider || activeImgTab.providerSelection?.provider || apiProvider || 'ark'
  const isArk = effectiveImageProvider === 'ark'
  const isCupsyImage = effectiveImageProvider === 'cupsy'
  const isSeedream = isArk || isCupsyImage
  const imageCapabilityModel = activeImageOption
    ? (activeImageOption.capability_model || activeImageOption.model)
    : (imageProviders[effectiveImageProvider]?.capability_model || imageProviders[effectiveImageProvider]?.model || '')
  const imageSpec = imageCapabilities(effectiveImageProvider, imageCapabilityModel)
  const aspectRatios = imageSpec.ratios, resolutions = imageSpec.resolutions
  const imageParams = imageTabParams(effectiveImageProvider, activeImgTab)
  const imageReferences = (activeImgTab.uploadedImages || []).map((image, index) => ({
    id: String(index), name: image.name || image.file?.name || `参考素材 ${index + 1}`,
    width: image.width, height: image.height, has_alpha: image.hasAlpha,
    size_bytes: image.file?.size || image.size || 0,
  }))
  const [imageSubmitError, setImageSubmitError] = useState('')
  const [imageAdvOpenSignal, setImageAdvOpenSignal] = useState(0)
  const imageHasSingleAlpha = effectiveImageProvider === 'ark' && imageReferences.length === 1 && imageReferences[0].has_alpha === true
  const prevSingleAlphaRef = useRef(imageHasSingleAlpha)
  useEffect(() => {
    if (imageHasSingleAlpha && !prevSingleAlphaRef.current) setImageAdvOpenSignal(n => n + 1)
    prevSingleAlphaRef.current = imageHasSingleAlpha
  }, [imageHasSingleAlpha])
  const imageActionAlertRef = useRef(null)
  const imageOutputSectionRef = useRef(null)
  const changeImageParams = patch => { setImageSubmitError(''); updateImgTab(activeImgTab.id, imageTabPatch(patch)) }
  const imageDimensions = useImageDimensionDraft(imageParams, changeImageParams, activeImgTab.id)
  const imageIssues = imageParameterIssues(effectiveImageProvider, imageParams, imageReferences, imageCapabilityModel)
  const imageSizeSummary = getImageSizeSummary(effectiveImageProvider, imageParams)
  const imageCostEstimate = estimateImageParamsCost({
    provider: activeImageOption,
    params: imageParams,
    references: imageReferences,
    issue: isSeedream ? imageDimensions.error : '',
  })
  const liveImageIssue = imageIssues[0] || (isSeedream && imageDimensions.error) || ''
  const imageActionError = (capabilitiesReady && imageSelectionState.unavailableReason) || liveImageIssue || imageSubmitError
  const scrollImageErrorIntoView = useCallback((includeInspector = false) => {
    const prefersReduced = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const behavior = prefersReduced ? 'auto' : 'smooth'
    imageActionAlertRef.current?.scrollIntoView?.({ behavior, block: 'nearest' })
    if (includeInspector) {
      const target = imageOutputSectionRef.current?.querySelector('.ip-errors, [role="alert"]') || imageOutputSectionRef.current
      target?.scrollIntoView?.({ behavior, block: 'nearest' })
    }
  }, [])

  const handleApplyPngInfo = metadata => {
    const params = metadata?.params || {}
    const updates = {}
    const skipped = []

    if (typeof metadata?.prompt === 'string' && metadata.prompt.trim()) updates.prompt = metadata.prompt

    if (params.aspect_ratio !== undefined) {
      const ratio = String(params.aspect_ratio)
      if (aspectRatios.includes(ratio)) updates.aspectRatio = ratio
      else skipped.push('画幅')
    }
    if (params.resolution !== undefined) {
      const resolution = String(params.resolution).toUpperCase()
      if (resolutions.includes(resolution)) updates.resolution = resolution
      else skipped.push('分辨率')
    }
    const sizeMatch = String(params.size || '').match(/^(\d+)x(\d+)$/i)
    const customWidth = params.custom_width ?? sizeMatch?.[1]
    const customHeight = params.custom_height ?? sizeMatch?.[2]
    if (customWidth !== undefined && customHeight !== undefined) {
      const width = Number(customWidth)
      const height = Number(customHeight)
      if (Number.isInteger(width) && Number.isInteger(height)) {
        updates.customWidth = width
        updates.customHeight = height
        updates.customAspectRatio = width / height
      }
    }
    if (isSeedream) {
      if (params.output_format !== undefined) {
        const outputFormat = String(params.output_format).toLowerCase().replace('jpg', 'jpeg')
        if (['png', 'jpeg'].includes(outputFormat)) updates.outputFormat = outputFormat
      }
      if (typeof params.watermark === 'boolean') updates.watermark = params.watermark
    }

    updateImgTab(activeImgTab.id, updates)
    setAppMode('image')
    notify(skipped.length ? `PNG Info 已载入，已忽略不兼容的${skipped.join('、')}` : 'PNG Info 已载入')
  }

  const handleApplyPngInfoToCanvas = async metadata => {
    if (appMode === 'canvas') {
      requestCanvasPngInfo(metadata)
      return
    }
    queueCanvasPngInfo(metadata)
    await changeAppMode('canvas')
  }

  const fetchAllProviderCapabilities = useCallback(async () => {
    const seq = ++capabilitiesFetchSeq.current
    try {
      const bundle = await getToolCapabilities()
      if (seq !== capabilitiesFetchSeq.current) return
      setToolCapabilities(bundle.capabilities)
      setToolRawProviders({ image: bundle.image, video: bundle.video, audio: bundle.audio, saved: bundle.saved })
      if (bundle.image?.success !== false) {
        setApiProvider(['ark', 'cupsy'].includes(bundle.image?.current_provider) ? bundle.image.current_provider : 'ark')
        setImageProviders(bundle.image?.providers || {})
      }
      if (bundle.video?.success !== false) {
        setVideoFastAvailable(bundle.video?.fast_available !== false)
        if (bundle.video?.providers) setVideoProviders(bundle.video.providers)
      }
      if (bundle.audio?.success !== false) {
        setAudioProvider({
          available: Boolean(bundle.audio?.providers?.cupsy?.available),
          sourceReady: bundle.audio?.providers?.cupsy?.source_ready !== false,
        })
      }
    } catch (error) {
      console.error('Failed to fetch provider capabilities:', error)
    } finally {
      if (seq === capabilitiesFetchSeq.current) {
        setProviderInfoReady(true)
        setCapabilitiesReady(true)
      }
    }
  }, [])

  useEffect(() => {
    fetchAllProviderCapabilities()
  }, [fetchAllProviderCapabilities])

  useEffect(() => {
    if (!capabilitiesReady || activeVideoFastAvailable || !activeTab.fast) return
    updateTab(activeTab.id, { fast: false })
  }, [activeTab.fast, activeTab.id, activeVideoFastAvailable, capabilitiesReady, updateTab])

  const fullEditorRef = useRef(null)
  useModalFocus(fullEditorRef, showFullEditor)

  useEffect(() => {
    const handleEsc = (e) => { if (e.key === 'Escape' && isTopModal(fullEditorRef)) { setShowFullEditor(false); setShowEditorVault(false) } }
    if (showFullEditor) window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [showFullEditor])

  const promptDrawerRef = useRef(null)
  const promptDrawerTriggerRef = useRef(null)
  const promptDrawerOpen = showPromptCollection && appMode !== 'canvas'

  const closePromptDrawer = useCallback((restoreFocus = true) => {
    setShowPromptCollection(false)
    if (!restoreFocus) return
    const trigger = (promptDrawerTriggerRef.current?.isConnected && promptDrawerTriggerRef.current)
      || appShellRef.current?.querySelector('[data-canvas-rail-toggle="prompts"]')
      || document.querySelector('[data-canvas-rail-toggle="prompts"]')
    promptDrawerTriggerRef.current = null
    if (trigger?.isConnected) trigger.focus({ preventScroll: true })
  }, [])

  useEffect(() => {
    if (!promptDrawerOpen) return undefined
    if (!promptDrawerTriggerRef.current?.isConnected) {
      const active = document.activeElement instanceof HTMLElement ? document.activeElement : null
      promptDrawerTriggerRef.current = (active && active !== document.body && !promptDrawerRef.current?.contains(active))
        ? active
        : (appShellRef.current?.querySelector('[data-canvas-rail-toggle="prompts"]') || null)
    }
    const frame = requestAnimationFrame(() => {
      const drawer = promptDrawerRef.current
      if (!drawer || drawer.contains(document.activeElement)) return
      const initialTarget = drawer.querySelector('input[aria-label="搜索提示词"]') || drawer
      initialTarget.focus({ preventScroll: true })
    })
    const handleEsc = (event) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      if (document.querySelector('[aria-modal="true"]')) return
      const drawer = promptDrawerRef.current
      const cancelEditBtn = drawer?.querySelector('button[aria-label="取消编辑"]')
      if (cancelEditBtn) {
        event.preventDefault()
        event.stopPropagation()
        cancelEditBtn.click()
        requestAnimationFrame(() => {
          if (drawer?.isConnected && !drawer.contains(document.activeElement)) {
            const fallback = drawer.querySelector('input[aria-label="搜索提示词"]') || drawer
            fallback.focus({ preventScroll: true })
          }
        })
        return
      }
      event.preventDefault()
      event.stopPropagation()
      closePromptDrawer(true)
    }
    window.addEventListener('keydown', handleEsc)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('keydown', handleEsc)
    }
  }, [promptDrawerOpen, closePromptDrawer])

  const handleImageProviderChange = async (optionId) => {
    const option = optionById(toolCapabilities, 'image', optionId)
    if (!option) return
    const selection = selectionFromOption(option)
    const nextCapabilityModel = option.capability_model || option.model || ''
    const sanitized = sanitizeImageTabForProvider(option.provider, activeImgTab, nextCapabilityModel, imageReferences)
    imageDimensions.sync(sanitized.params)
    setImageSubmitError('')
    updateImgTab(activeImgTab.id, { providerSelection: selection, ...sanitized.patch })
    if (option.provider === 'ark' && isSeedream55(nextCapabilityModel)) setImageAdvOpenSignal(n => n + 1)
    setApiProvider(option.provider)
    // Keep legacy session provider in sync on a best-effort basis without blocking custom profiles.
    if (!option.profile_id || option.source_key === `config:image:${option.provider}`) {
      axios.post('/api/provider', { provider: option.provider }).catch(() => {})
    }
  }

  useEffect(() => {
    if (!providerRevision || !capabilitiesReady || !activeImageOption) return
    const nextCapabilityModel = activeImageOption.capability_model || activeImageOption.model || ''
    const sanitized = sanitizeImageTabForProvider(activeImageOption.provider, activeImgTab, nextCapabilityModel, imageReferences)
    if (!sanitized.changed) return
    imageDimensions.sync(sanitized.params)
    setImageSubmitError('')
    updateImgTab(activeImgTab.id, sanitized.patch)
  }, [providerRevision, capabilitiesReady, activeImageOption?.id, activeImageOption?.capability_model])
  
  const handleSavePrompt = async () => {
    const p = appMode === 'video' ? activeTab.prompt : appMode === 'audio' ? audioForm.prompt : activeImgTab.prompt
    if (!p || !p.trim()) return notify('请先输入提示词', 'error')
    try {
      const response = await axios.post('/api/prompts', { text: p.trim() })
      if (response.data.success) notify('已保存到提示词库')
      else notify('保存失败', 'error')
    } catch (e) { notify('保存失败', 'error') }
  }

  const handleGenerate = async () => {
    const tab = activeImgTab
    if (!activeImageOption) {
      const reason = imageSelectionState.unavailableReason || '所选接口不可用，请重新选择'
      setImageSubmitError(reason)
      notify(reason, 'error')
      requestAnimationFrame(() => scrollImageErrorIntoView(false))
      return
    }
    if (!tab.prompt.trim()) {
      const reason = '请先填写图片描述'
      setImageSubmitError(reason)
      notify(reason, 'error')
      requestAnimationFrame(() => scrollImageErrorIntoView(false))
      return
    }
    const issues = imageParameterIssues(effectiveImageProvider, imageTabParams(effectiveImageProvider, tab), imageReferences, imageCapabilityModel)
    if (issues.length || (isSeedream && imageDimensions.error)) {
      const reason = issues[0] || imageDimensions.error
      setImageSubmitError(reason)
      notify(reason, 'error')
      requestAnimationFrame(() => scrollImageErrorIntoView(true))
      return
    }
    setImageSubmitError('')
    const imageOptions = imageRequestFields(effectiveImageProvider, imageTabParams(effectiveImageProvider, tab))
    const submitProfile = toolSubmitProfileFields(activeImageOption)
    const revealTimer = window.setTimeout(
      () => setTaskGalleryRevision(revision => revision + 1),
      500,
    )

    try {
      let response
      if (tab.uploadedImages.length === 0) {
        response = await axios.post('/api/generate', {
          prompt: tab.prompt, ...submitProfile, ...imageOptions,
        })
      } else {
        const imageUrls = await Promise.all(tab.uploadedImages.map(async image => {
          if (isDirectImageReferenceUrl(image.preview) && !image.file) {
            return image.preview
          }
          const blob = image.file || await ensureFetchOk(image.preview)
          const asset = await persistWorkspaceBlob('img_tabs', blob, image.name || 'image.png')
          updateImgTab(tab.id, current => ({
            uploadedImages: current.uploadedImages.map(item => (
              (image.file ? item.file === image.file : item === image)
                ? { ...item, ...workspaceImageFields(asset), file: null, uploadError: false }
                : item
            )),
          }))
          return asset.url
        }))
        response = await axios.post('/api/generate', {
          prompt: tab.prompt, ...submitProfile, ...imageOptions,
          image_urls: imageUrls,
        })
      }

      const taskId = response.data.task_id
      setImageSubmitError('')
      notify(taskId ? `图片任务 #${taskId} 已创建` : '图片任务已创建')
    } catch (err) {
      const errorData = err.response?.data || {}
      const reason = errorData.error || err.message || '图片任务创建失败'
      setImageSubmitError(reason)
      notify(reason, 'error')
      requestAnimationFrame(() => scrollImageErrorIntoView(false))
    } finally {
      window.clearTimeout(revealTimer)
      setTaskGalleryRevision(revision => revision + 1)
    }
  }

  const ensureFetchOk = async (url) => {
    const response = await fetch(url)
    if (!response.ok) throw new Error(`Failed to fetch asset: ${response.status}`)
    return response.blob()
  }

  const videoTabHasInput = (tab) => {
    const uploadedVideos = tab.refVideos.some(v => v.url && !v.uploading)
    if (tab.mode === 'keyframe') {
      return Boolean(tab.prompt.trim() || tab.firstFrame || tab.lastFrame)
    }
    return Boolean(tab.prompt.trim() || tab.refImages.length > 0 || uploadedVideos || tab.refAudios.length > 0)
  }

  // 视频模式下，将剪贴板中的媒体发送到当前素材区域。
  useEffect(() => {
    if (appMode !== 'video') return undefined
    const handlePaste = event => {
      const files = Array.from(event.clipboardData?.items || [])
        .filter(item => item.kind === 'file')
        .map(item => item.getAsFile())
        .filter(Boolean)
      if (!files.length) return

      if (activeTab.mode === 'keyframe') {
        const images = files.filter(isImageFile)
        if (!images.length) return
        event.preventDefault()
        addPastedKeyframes(activeTab.id, images)
        return
      }

      const images = files.filter(isImageFile)
      const videos = files.filter(isVideoFile)
      const audios = files.filter(isAudioFile)
      if (!images.length && !videos.length && !audios.length) return
      event.preventDefault()
      if (images.length) addVideoReferenceImages(activeTab.id, images)
      if (videos.length) addVideoReferenceVideos(activeTab.id, videos)
      if (audios.length) addVideoReferenceAudios(activeTab.id, audios)
    }
    document.addEventListener('paste', handlePaste)
    return () => document.removeEventListener('paste', handlePaste)
  }, [
    activeTab.id,
    activeTab.mode,
    addPastedKeyframes,
    addVideoReferenceAudios,
    addVideoReferenceImages,
    addVideoReferenceVideos,
    appMode,
  ])

  useEffect(() => {
    if (appMode !== 'audio') return undefined
    const handlePaste = event => {
      const files = Array.from(event.clipboardData?.items || [])
        .filter(item => item.kind === 'file')
        .map(item => item.getAsFile())
        .filter(Boolean)
      if (!files.some(file => isImageFile(file) || isAudioFile(file))) return
      event.preventDefault()
      addAudioReferences(files)
    }
    document.addEventListener('paste', handlePaste)
    return () => document.removeEventListener('paste', handlePaste)
  }, [addAudioReferences, appMode])

  const handleVideoGenerate = async () => {
    const tab = activeTab
    if (!activeVideoOption) {
      notify(videoSelectionState.unavailableReason || '所选接口不可用，请重新选择', 'error')
      return
    }
    if (!videoTabHasInput(tab)) {
      notify('请填写视频提示词或添加参考素材', 'error')
      return
    }
    const submitProfile = toolSubmitProfileFields(activeVideoOption)
    const readyRefVideos = tab.refVideos.filter(video => video.url && !video.uploading)
    if (tab.mode === 'keyframe' && tab.lastFrame && !tab.firstFrame) {
      notify('设置尾帧时必须同时提供首帧', 'error')
      return
    }
    if (tab.mode === 'reference') {
      if (tab.refImages.length > videoCapabilities.maxRefImages
        || readyRefVideos.length > videoCapabilities.maxRefVideos
        || tab.refAudios.length > videoCapabilities.maxRefAudios) {
        notify('参考素材数量超过当前模型上限', 'error')
        return
      }
      if (!isSeedance25 && tab.refAudios.length > 0 && tab.refImages.length === 0 && readyRefVideos.length === 0) {
        notify('Seedance 2.0 使用音频时还需要参考图片或视频', 'error')
        return
      }
    }
    const revealTimer = window.setTimeout(
      () => setTaskGalleryRevision(revision => revision + 1),
      500,
    )

    try {
      let resp
      const submission = buildVideoGenerateSubmission(tab, {
        prompt: tab.prompt,
        ratio: effectiveVideoRatio,
        duration: effectiveVideoDuration,
        resolution: tab.resolution,
        model: effectiveVideoModel,
        output_format: tab.outputFormat || 'mp4',
        fast: tab.fast,
        generate_audio: tab.audio,
        return_last_frame: tab.returnLastFrame,
        video_mode: tab.mode,
        ...submitProfile,
      })

      if (submission.mode === 'json') {
        resp = await axios.post('/api/video/generate', submission.body, { timeout: 300000 })
      } else {
        const formData = new FormData()
        Object.entries(submission.fields).forEach(([key, value]) => {
          if (value === undefined || value === null) return
          formData.append(key, Array.isArray(value) || typeof value === 'object' ? JSON.stringify(value) : value)
        })
        const resolvedUploads = await Promise.all(
          submission.uploadsToAppend.map(async item => ({
            field: item.field,
            name: item.name,
            blob: item.file || await ensureFetchOk(item.url),
          })),
        )
        resolvedUploads.forEach(({ field, blob, name }) => {
          formData.append(field, blob, name)
        })
        resp = await axios.post('/api/video/generate', formData, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 300000 })
      }

      if (resp.data.success && (resp.data.db_task_id || resp.data.task_id)) {
        const localTaskId = resp.data.db_task_id || resp.data.task_id
        notify(`视频任务 #${localTaskId} 已创建`)
      } else {
        notify(resp.data.error || '视频任务创建失败', 'error')
      }
    } catch (e) {
      notify(e.response?.data?.error || e.message || '视频任务创建失败', 'error')
    } finally {
      window.clearTimeout(revealTimer)
      setTaskGalleryRevision(revision => revision + 1)
    }
  }

  const handleAudioGenerate = async () => {
    if (!activeAudioOption) {
      notify(audioSelectionState.unavailableReason || '所选接口不可用，请重新选择', 'error')
      return
    }
    if (!audioForm.prompt.trim()) {
      notify('请填写音频提示词', 'error')
      return
    }
    if (audioForm.referenceMode === 'image' && audioForm.references.length !== 1) {
      notify('图片参考模式需要 1 张参考图片', 'error')
      return
    }
    if (audioForm.referenceMode === 'audio' && audioForm.references.length + (audioForm.speaker ? 1 : 0) > 3) {
      notify('最多使用 3 个音频或声线参考', 'error')
      return
    }
    const submitProfile = toolSubmitProfileFields(activeAudioOption)
    const revealTimer = window.setTimeout(() => setTaskGalleryRevision(revision => revision + 1), 500)
    try {
      const response = await axios.post('/api/audio/generate', {
        prompt: audioForm.prompt,
        ...submitProfile,
        model: activeAudioOption.model || CUPSY_AUDIO_MODEL,
        output_format: audioForm.outputFormat,
        sample_rate: Number(audioForm.sampleRate),
        enable_subtitle: Boolean(audioForm.enableSubtitle),
        watermark: Boolean(audioForm.watermark),
        reference_mode: audioForm.referenceMode,
        speaker: audioForm.referenceMode === 'audio' ? audioForm.speaker : '',
        ...buildAudioReferencePayload(audioForm.references),
      })
      notify(`音频任务 #${response.data.task_id} 已创建`)
    } catch (error) {
      notify(error.response?.data?.error || error.message || '音频任务创建失败', 'error')
    } finally {
      window.clearTimeout(revealTimer)
      setTaskGalleryRevision(revision => revision + 1)
    }
  }

  // 左侧面板拖拽调整宽度
  const [panelWidth, setPanelWidth] = useState(400)
  const isDragging = useRef(false)

  // 将历史任务参数覆盖到固定生成表单。
  const handleLoadTask = useCallback(async (taskSummary) => {
    let task = taskSummary
    try {
      const resp = await axios.get(`/api/tasks/${taskSummary.id}`)
      if (resp.data.success) task = resp.data.task
    } catch (e) { /* use summary as fallback */ }
    const params = task.params || {}
    const restoredReferences = restoredTaskReferences(task)

    if (task.type === 'image') {
      const id = activeImgTab.id || 1
      const restoredRefs = restoredReferences
        .filter(reference => reference.type === 'image')
        .map(reference => ({ preview: reference.url, name: reference.name }))
      const tab = {
        ...makeImgTab(id),
        ...(task.provider ? { providerSelection: { provider: task.provider, profile_id: params.profile_id || null } } : {}),
        prompt: task.prompt || '',
        aspectRatio: params.aspect_ratio || '1:1',
        resolution: params.resolution || '1K',
        customWidth: Number(params.custom_width) || 1024,
        customHeight: Number(params.custom_height) || 1024,
        customAspectRatio: (Number(params.custom_width) || 1024) / (Number(params.custom_height) || 1024),
        outputFormat: params.output_format || 'png',
        background: params.background || 'default',
        watermark: Boolean(params.watermark),
        uploadedImages: restoredRefs,
      }
      setImgTabs([tab])
      setActiveImgTabId(id)
      setAppMode('image')
      if (appMode === 'tasks') notify(`已复用图片任务 #${task.id} 参数并切换到图片工具`)
    } else if (task.type === 'video') {
      const id = activeTab.id || 1
      const knownVideoUrls = new Set(restoredReferences.filter(reference => reference.type === 'video').map(reference => reference.url))
      const knownVideoNames = new Set(restoredReferences.filter(reference => reference.type === 'video').map(reference => reference.name))
      const paramsVideos = (params.ref_video_urls || []).map((url, index) => ({
        url,
        type: 'video',
        role: 'reference_video',
        name: `ref_video_${index + 1}.mp4`,
        filepath: (params.ref_video_paths || [])[index] || null,
        cupsyAssetId: null,
      })).filter(reference => {
        const filename = decodeURIComponent(String(reference.url).split('/').pop() || '')
        return !knownVideoUrls.has(reference.url) && !knownVideoNames.has(filename)
      })
      const videoReferences = [...restoredReferences, ...paramsVideos]
      const restoredImages = videoReferences
        .filter(reference => reference.role === 'reference_image')
        .map(reference => ({
          file: null, preview: reference.url, name: reference.name,
          cupsyAssetId: reference.cupsyAssetId,
        }))
      const restoredVideos = videoReferences
        .filter(reference => reference.role === 'reference_video')
        .map((reference, index) => ({
          uid: `restored_${task.id}_${index}`,
          name: reference.name, url: reference.url, filepath: reference.filepath || null,
          cupsyAssetId: reference.cupsyAssetId,
          thumbnail: null, progress: 100, uploading: false,
        }))
      const restoredAudios = videoReferences
        .filter(reference => reference.role === 'reference_audio')
        .map(reference => ({
          file: null, preview: reference.url, name: reference.name,
          cupsyAssetId: reference.cupsyAssetId,
        }))
      const firstFrameReference = videoReferences.find(reference => reference.role === 'first_frame')
      const lastFrameReference = videoReferences.find(reference => reference.role === 'last_frame')
      const tab = {
        ...makeVideoTab(id),
        prompt: task.prompt || '',
        provider: task.provider === 'cupsy' ? 'cupsy' : 'ark',
        ...(task.provider ? { providerSelection: { provider: task.provider === 'cupsy' ? 'cupsy' : 'ark', profile_id: params.profile_id || null } } : {}),
        model: params.model || SEEDANCE_20,
        ratio: params.ratio || 'adaptive',
        duration: params.duration ?? 5,
        resolution: params.resolution || '720p',
        outputFormat: params.output_format || 'mp4',
        fast: params.fast || false,
        audio: params.generate_audio !== false,
        returnLastFrame: params.return_last_frame || false,
        mode: params.video_mode || 'keyframe',
        firstFrame: firstFrameReference ? {
          file: null, preview: firstFrameReference.url, name: firstFrameReference.name,
          cupsyAssetId: firstFrameReference.cupsyAssetId,
        } : null,
        lastFrame: lastFrameReference ? {
          file: null, preview: lastFrameReference.url, name: lastFrameReference.name,
          cupsyAssetId: lastFrameReference.cupsyAssetId,
        } : null,
        refImages: restoredImages,
        refVideos: restoredVideos,
        refAudios: restoredAudios,
      }
      setVideoTabs([tab])
      setActiveVideoTabId(id)
      setAppMode('video')
      if (appMode === 'tasks') notify(`已复用视频任务 #${task.id} 参数并切换到视频工具`)
    } else if (task.type === 'audio') {
      const refs = restoredReferences
        .filter(reference => ['reference_audio', 'reference_image'].includes(reference.role))
        .map(reference => ({
          cupsyAssetId: reference.cupsyAssetId,
          kind: reference.type,
          name: reference.name,
          preview: reference.url,
          status: 'active',
        }))
        .filter(reference => reference.cupsyAssetId)
      updateAudioForm({
        ...DEFAULT_AUDIO_FORM,
        ...(task.provider ? { providerSelection: { provider: task.provider, profile_id: params.profile_id || null } } : {}),
        prompt: task.prompt || '',
        outputFormat: params.output_format || 'mp3',
        sampleRate: Number(params.sample_rate) || 44100,
        enableSubtitle: params.enable_subtitle !== false,
        watermark: Boolean(params.watermark),
        referenceMode: params.reference_mode || (refs[0]?.kind || 'none'),
        speaker: params.speaker || '',
        references: refs,
      })
      setAppMode('audio')
      if (appMode === 'tasks') notify(`已复用音频任务 #${task.id} 参数并切换到音频工具`)
    } else if (task.type === 'layer') {
      notify('图层分解任务不支持回填独立生成表单，请前往「图层」工作室查看或重新分解', 'info')
    }
  }, [activeImgTab.id, activeTab.id, appMode, notify, setImgTabs, setActiveImgTabId, setVideoTabs, setActiveVideoTabId, setAppMode, updateAudioForm])

  const handleDragStart = (e) => {
    e.preventDefault()
    isDragging.current = true
    const startX = e.clientX
    const promptPane = e.currentTarget?.previousElementSibling
    const renderedWidth = promptPane?.classList?.contains('prompt-pane')
      ? promptPane.getBoundingClientRect().width
      : NaN
    const startWidth = Number.isFinite(renderedWidth) && renderedWidth > 0 ? renderedWidth : panelWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    const onMove = (ev) => {
      if (!isDragging.current) return
      setPanelWidth(Math.round(Math.min(560, Math.max(300, startWidth + (ev.clientX - startX)))))
    }
    const onUp = () => {
      isDragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  const handleResizeKeyDown = (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
    event.preventDefault()
    const delta = event.key === 'ArrowLeft' ? -20 : 20
    setPanelWidth(width => Math.min(560, Math.max(300, width + delta)))
  }

  const handleSelectSavedPrompt = (prompt) => {
    if (appMode === 'canvas') {
      setShowPromptCollection(false)
      return
    }
    if (appMode === 'layer' || appMode === 'tasks') {
      navigator.clipboard?.writeText(prompt).catch(() => {})
      notify(appMode === 'tasks' ? '任务中心无对应表单，已复制提示词到剪贴板' : '图层页无对应表单，已复制提示词到剪贴板')
      setShowPromptCollection(false)
      return
    }
    if (appMode === 'video') updateTab(activeTab.id, { prompt })
    else if (appMode === 'audio') updateAudioForm({ prompt })
    else updateImgTab(activeImgTab.id, { prompt })
    setShowPromptCollection(false)
  }
  const handleTogglePromptLibrary = () => {
    if (appMode === 'canvas') {
      setShowPromptCollection(false)
      requestCanvasTogglePrompts()
      return
    }
    if (showPromptCollection) {
      closePromptDrawer(true)
      return
    }
    promptDrawerTriggerRef.current = document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement
      : (appShellRef.current?.querySelector('[data-canvas-rail-toggle="prompts"]') || null)
    setShowPromptCollection(true)
  }
  const imageModelValue = isSeedream
    ? (isCupsyImage
      ? 'seedream-5.0-pro'
      : isSeedream55(imageCapabilityModel)
        ? 'dola-seedream-5-5-261028'
        : 'seedream-5-0-pro')
    : ''
  const currentEditorPrompt = appMode === 'video'
    ? activeTab.prompt
    : appMode === 'audio' ? audioForm.prompt : activeImgTab.prompt
  const setCurrentEditorPrompt = prompt => {
    if (appMode === 'video') updateTab(activeTab.id, { prompt })
    else if (appMode === 'audio') updateAudioForm({ prompt })
    else updateImgTab(activeImgTab.id, { prompt })
  }
  const promptMentionItems = currentPromptMentionItems(appMode, activeImgTab, activeTab, audioForm)

  return (
    <div ref={appShellRef} className={`app-shell ${appMode === 'canvas' ? 'is-canvas' : ''} bg-nexus-bg text-nexus-text-light font-sans flex flex-col overflow-hidden relative`}>
      
      {/* 极简顶栏 */}
      <header className="app-header liquid-glass flex items-center justify-between px-3 z-50 shrink-0">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex shrink-0 items-center gap-2">
            <div className="brand-mark flex size-8 items-center justify-center">
              <BrandMark size={20} variant="default" />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-[-0.01em] text-white">Ink Traces</div>
              <div className="brand-version text-[11px] text-nexus-muted">视觉创作台</div>
            </div>
          </div>
          <SegmentedControl
            label="生成模式"
            value={appMode}
            onChange={changeAppMode}
            options={[
              { value: 'canvas', label: '画布', icon: Grid3X3 },
              { value: 'image', label: '图片', icon: ImageIcon },
              { value: 'layer', label: '图层', icon: Layers3 },
              { value: 'video', label: '视频', icon: Film },
              { value: 'audio', label: '音频', icon: AudioLines },
              { value: 'tasks', label: '任务中心', icon: ListTodo },
            ]}
          />
        </div>
        <div className="header-actions flex min-w-0 items-center gap-1.5">
          <div className="glass-control-group flex items-center gap-0.5">
            <IconButton label="全局素材库" data-testid="header-library-button" onClick={() => setShowGlobalLibrary(true)} className={showGlobalLibrary ? 'is-active' : ''}><Images size={16} /></IconButton>
            <IconButton label="接口管理" onClick={() => setShowProviderSettings(true)}><Settings size={16} /></IconButton>
            <IconButton label="PNG Info" onClick={() => setShowPngInfo(true)}><FileSearch size={16} /></IconButton>
            <IconButton label="提示词库" data-canvas-rail-toggle="prompts" onClick={handleTogglePromptLibrary} className={(appMode === 'canvas' ? canvasRailPanel === 'prompts' : showPromptCollection) ? 'is-active' : ''}><Library size={16} /></IconButton>
            <IconButton label="退出登录" onClick={handleLogout}><LogOut size={16} /></IconButton>
          </div>
        </div>
      </header>

      {/* 主工作区 */}
      <main className="workspace-main flex-grow relative" style={(appMode === 'canvas' || appMode === 'tasks') ? { display: 'flex', backgroundImage: 'none' } : { '--prompt-user-width': `${panelWidth}px` }}>

      {appMode === 'canvas' ? (
        <React.Suspense fallback={<div className="flex-1" role="status" aria-label="正在载入创作画布" />}>
          <CanvasStudio beforeLeaveRef={canvasBeforeLeave} notify={notify} providerRevision={providerRevision} />
        </React.Suspense>
      ) : appMode === 'tasks' ? (
        <GlobalTaskCenter
          activeType={globalTaskCenterType}
          onTypeChange={setGlobalTaskCenterType}
          refreshToken={taskGalleryRevision}
          onReuseTask={handleLoadTask}
        />
      ) : appMode === 'image' ? (<>
        
        {/* 左侧：提示词输入 */}
        <section className="prompt-pane relative z-20">

          {/* 编辑器主体 */}
          <div className="flex-grow flex flex-col min-h-0 relative z-10">
            <TextToImage 
              prompt={activeImgTab.prompt} setPrompt={v => { setImageSubmitError(''); updateImgTab(activeImgTab.id, { prompt: v }) }}
              mentionItems={promptMentionItems}
              isGenerating={false}
              onSavePrompt={handleSavePrompt}
            />
          </div>

          {/* 执行按钮区 */}
          <div className="prompt-actions p-3 border-t border-nexus-border z-10">
            {imageActionError && (
              <div
                ref={imageActionAlertRef}
                role="alert"
                data-testid={capabilitiesReady && imageSelectionState.unavailableReason ? 'image-provider-action-alert' : 'image-generate-error'}
                className="mb-2 flex items-start gap-2 rounded-md border border-nexus-red/40 bg-[#241316] px-2.5 py-2 text-xs text-nexus-red leading-5"
              >
                <CircleAlert size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                <span className="min-w-0 break-words">{imageActionError}</span>
              </div>
            )}
            <button
              onClick={handleGenerate}
              disabled={!capabilitiesReady || !activeImageOption}
              title={imageActionError || ''}
              className="btn btn-primary btn-lg btn-block"
            >
              <Play size={14} fill="currentColor" /> <span>生成图片</span>
            </button>
          </div>

        </section>

        {/* 拖拽手柄 */}
        <div
          onMouseDown={handleDragStart}
          className="workspace-resizer z-20"
          role="separator"
          tabIndex={0}
          aria-orientation="vertical"
          aria-valuemin={300}
          aria-valuemax={560}
          aria-valuenow={panelWidth}
          aria-label="调整提示词面板宽度"
          onKeyDown={handleResizeKeyDown}
        />

        {/* 中间：生成画布 */}
        <section className="canvas-pane">
          <div className="canvas-grid" />
          <TaskGallery
            key="image"
            mode="image"
            refreshToken={taskGalleryRevision}
            onReuseTask={handleLoadTask}
          />
        </section>

        {/* 右侧：图片参数 */}
        <aside key="inspector-image" className="inspector-pane pf-panel">
          <PanelHeader
            className="inspector-header"
            icon={ImageIcon}
            title="图片参数"
            summary={imageSizeSummary}
          />
          <div className="pf-panel-body custom-scrollbar">
            <PanelSection id="tool-image-provider" title="生成设置">
              <div className="pf-fields">
                <PanelField label="接口" prefix={<Plug size={14} />}>
                  <select
                    aria-label="图片端点"
                    value={imageSelectionState.selectValue}
                    disabled={!capabilitiesReady || (!imageSelectionState.options.length && !imageSelectionState.staleOptionLabel)}
                    onChange={event => handleImageProviderChange(event.target.value)}
                  >
                    {!capabilitiesReady && <option value="">读取中…</option>}
                    {capabilitiesReady && imageSelectionState.staleOptionLabel && (
                      <option value={imageSelectionState.selectValue} disabled>
                        {imageSelectionState.staleOptionLabel}
                      </option>
                    )}
                    {capabilitiesReady && !imageSelectionState.options.length && !imageSelectionState.staleOptionLabel && (
                      <option value="">暂无可用接口</option>
                    )}
                    {imageSelectionState.options.map(option => (
                      <option key={option.id} value={option.id}>
                        {option.name}
                      </option>
                    ))}
                  </select>
                </PanelField>
                {capabilitiesReady && imageSelectionState.unavailableReason && (
                  <div role="alert" data-testid="image-provider-alert" className="pf-alert">
                    {imageSelectionState.unavailableReason}
                  </div>
                )}
                <PanelField label="模型" hint="由当前接口配置决定" prefix={<Cpu size={14} />}>
                  <select
                    aria-label="图片模型"
                    value={imageModelValue}
                    disabled
                    onChange={() => {}}
                    className="pf-readonly-select"
                  >
                    {isSeedream ? (
                      <option value={imageModelValue}>{isSeedream55(imageCapabilityModel) ? 'Seedream 5.5' : 'Seedream 5.0 Pro'}</option>
                    ) : (
                      <option value="">—</option>
                    )}
                  </select>
                </PanelField>
              </div>
            </PanelSection>

            <PanelSection
              id="tool-image-output"
              title="输出参数"
              summary={imageSizeSummary}
              sectionRef={imageOutputSectionRef}
            >
              <ImageOutputControls
                variant="panel"
                hideModel
                fieldPrefix={imageRatioPrefix}
                Advanced={ImageToolAdvanced}
                advancedAutoOpenSignal={imageAdvOpenSignal}
                model={imageCapabilityModel}
                provider={effectiveImageProvider}
                params={imageParams}
                onChange={changeImageParams}
                references={imageReferences}
                dimensions={imageDimensions}
                issues={imageIssues}
              />
            </PanelSection>

            {/* SOURCE NODE */}
            <PanelSection
              id="tool-image-refs"
              title="参考素材"
              actions={<button type="button" className="btn btn-secondary btn-sm" onClick={openToolLibrary}><Library size={13} /> 素材库</button>}
            >
              <div className="flex-grow min-h-0">
                <ImageToImage
                  uploadedImages={activeImgTab.uploadedImages}
                  createPreviewUrl={createReferencePreview}
                  onPreview={setReferenceMedia}
                  setUploadedImages={value => {
                    setImageSubmitError('')
                    updateImgTab(activeImgTab.id, tab => ({
                      uploadedImages: typeof value === 'function'
                        ? value(Array.isArray(tab.uploadedImages) ? tab.uploadedImages : [])
                        : value,
                    }))
                  }}
                  maxImages={isSeedream ? 10 : 14}
                />
              </div>
            </PanelSection>
          </div>

          {(() => {
            if (imageCostEstimate.known) {
              const est = imageCostEstimate.estimate
              const pricing = IMAGE_PRICING[est.model]
              const billedRefs = Math.max(0, est.referenceCount - pricing.freeInputImages)
              const refLine = est.referenceCount
                ? `参考图 ${est.referenceCount} 张${pricing.freeInputImages ? `（首张免费，计 ${billedRefs} 张）` : ''}`
                : '无参考图'
              const providerLine = `${pricing.label} · ${isCupsyImage ? 'Cupsy 费率' : 'BytePlus Ark'}`
              const pixelLine = `${est.width}×${est.height} · ${(est.pixels / 1_000_000).toFixed(2)}M 像素`
              const noteLine = `${est.sizeAssumed ? 'Auto 按同分辨率 1:1 估算 · ' : ''}估算，非实际扣费`
              return (
                <CostEstimateFooter
                  testId="image-cost-estimate"
                  amount={formatUsdEstimate(est)}
                  summaryTitle={[providerLine, pixelLine, refLine, noteLine].join('；')}
                  details={
                    <div className="pf-cost-detail-list">
                      <div>{providerLine}</div>
                      <div>{pixelLine}</div>
                      <div>{refLine}</div>
                      <div className="pf-cost-detail-muted">{noteLine}</div>
                    </div>
                  }
                />
              )
            }
            const reason = imageCostEstimate.reason || '当前参数暂无法估算'
            return (
              <CostEstimateFooter
                testId="image-cost-estimate"
                amount="费用待估"
                tone="warn"
                summaryTitle={`${reason}；未知费用不计作 $0`}
                details={
                  <div className="pf-cost-detail-list">
                    <div>{reason}</div>
                    <div className="pf-cost-detail-muted">未知费用不计作 $0</div>
                  </div>
                }
              />
            )
          })()}
        </aside>

      </>) : appMode === 'layer' ? (
        <React.Suspense fallback={<div className="absolute inset-0" role="status" aria-label="正在加载 Layer Studio" />}>
          <LayerStudio notify={notify} />
        </React.Suspense>
      ) : appMode === 'video' ? (
        /* ============ VIDEO MODE ============ */
        <>
          {/* 左侧：视频提示词 */}
          <section className="prompt-pane relative z-20">
            <div className="flex-grow flex flex-col min-h-0 relative z-10">
              <div className="flex-grow flex flex-col min-h-0 relative bg-transparent">
                <div className="prompt-pane-header flex h-11 shrink-0 items-center justify-between px-4">
                  <span className="text-xs font-medium text-nexus-text-light">视频提示词</span>
                  <span className="font-mono text-xs text-nexus-muted">{activeTab.prompt.length}</span>
                </div>
                <div className="flex-grow min-h-0 relative overflow-hidden">
                  <PromptMentionTextarea
                    aria-label="视频提示词"
                    value={activeTab.prompt}
                    onValueChange={prompt => updateTab(activeTab.id, { prompt })}
                    mentionItems={promptMentionItems}
                    wrapperClassName="absolute inset-0"
                    className="absolute inset-0 resize-none overflow-y-auto whitespace-pre-wrap break-words bg-transparent px-4 py-4 text-sm leading-6 text-nexus-text-light outline-none custom-scrollbar placeholder:text-nexus-muted"
                    spellCheck="true"
                    placeholder="描述镜头、主体、动作、光线与节奏..."
                  />
                </div>
                <div className="absolute bottom-4 right-4 z-10">
                  <button
                    type="button"
                    aria-label="保存到提示词库"
                    title="保存到提示词库"
                    onClick={handleSavePrompt}
                    disabled={!activeTab.prompt.trim()}
                    className="btn btn-icon btn-outlined"
                  >
                    <Save size={16} />
                  </button>
                </div>
              </div>
            </div>
            <div className="prompt-actions p-3 border-t border-nexus-border z-10">
              {capabilitiesReady && videoSelectionState.unavailableReason && (
                <div role="alert" data-testid="video-provider-action-alert" className="mb-2 text-xs text-nexus-red leading-5">
                  {videoSelectionState.unavailableReason}
                </div>
              )}
              <button
                onClick={handleVideoGenerate}
                disabled={!capabilitiesReady || !activeVideoOption}
                title={videoSelectionState.unavailableReason || ''}
                className="btn btn-primary btn-lg btn-block"
              >
                <Play size={14} fill="currentColor" /> <span>生成视频</span>
              </button>
            </div>
          </section>

          {/* 拖拽手柄 */}
          <div
            onMouseDown={handleDragStart}
            onKeyDown={handleResizeKeyDown}
            className="workspace-resizer z-20"
            role="separator"
            tabIndex={0}
            aria-orientation="vertical"
            aria-valuemin={300}
            aria-valuemax={560}
            aria-valuenow={panelWidth}
            aria-label="调整提示词面板宽度"
          />

          {/* 中间：视频画布 */}
          <section className="canvas-pane">
            <div className="canvas-grid" />
            <TaskGallery
              key="video"
              mode="video"
              refreshToken={taskGalleryRevision}
              onReuseTask={handleLoadTask}
            />
          </section>

          {/* 右侧：视频参数 */}
          {(() => {
            const videoSummary = videoOutputSummary({
              ratio: effectiveVideoRatio,
              resolution: activeTab.resolution || '720p',
              duration: effectiveVideoDuration,
            })
            const hasVideoAdvanced = !isSeedance25 || activeVideoProvider === 'ark'
            const videoAdvancedParts = [
              !isSeedance25 && activeTab.fast ? '快速' : '',
              isSeedance25 && activeVideoProvider === 'ark' ? (activeTab.outputFormat || 'mp4').toUpperCase() : '',
              activeVideoProvider === 'ark' && activeTab.returnLastFrame ? '返回尾帧' : '',
            ].filter(Boolean)
            const videoAdvancedSummary = videoAdvancedParts.length ? videoAdvancedParts.join(' · ') : '默认'
            const videoAdvancedAutoOpen = Boolean(
              (!isSeedance25 && activeTab.fast)
              || (isSeedance25 && activeVideoProvider === 'ark' && activeTab.outputFormat === 'mov')
              || (activeVideoProvider === 'ark' && activeTab.returnLastFrame),
            )
            const videoEstimate = estimateBytePlusVideoCost({
              model: effectiveVideoModel,
              provider: activeVideoProvider,
              resolution: activeTab.resolution,
              ratio: effectiveVideoRatio,
              duration: effectiveVideoDuration,
              fast: activeTab.fast,
              referenceVideos: activeTab.refVideos,
            })
            const outputDuration = videoEstimate.minimumOutputSeconds === videoEstimate.maximumOutputSeconds
              ? `${videoEstimate.minimumOutputSeconds}s`
              : `${videoEstimate.minimumOutputSeconds}~${videoEstimate.maximumOutputSeconds}s`
            const inputVideo = videoEstimate.hasVideo
              ? `参考视频 ${videoEstimate.inputVideoSeconds.toFixed(1).replace(/\.0$/, '')}s${videoEstimate.inputDurationAssumed ? '（含 5s 默认值）' : ''}`
              : '无参考视频'
            const videoModelRateLine = activeVideoProvider === 'cupsy'
              ? effectiveVideoModel === SEEDANCE_25_MODERATED ? 'Seedance 2.5 · Cupsy 加强审核' : 'Seedance 2.5 · Cupsy 费率'
              : isSeedance25 ? `Seedance 2.5 · BytePlus${videoEstimate.promotionActive ? ' 限时按 72% 计费' : ''}`
                : activeTab.fast ? 'Seedance 2.0 Fast' : 'Seedance 2.0'
            const videoSizeLine = `${videoEstimate.width}×${videoEstimate.height} · ${outputDuration} · ${videoEstimate.fps}fps`
            const videoTokenLine = `≈${formatWanTokens(videoEstimate.minimumTokens, videoEstimate.maximumTokens)}${videoEstimate.ratioAssumed ? ' · Adaptive 按 16:9' : ''} · 估算，非实际扣费`
            return (
              <aside key="inspector-video" className="inspector-pane pf-panel">
                <PanelHeader
                  className="inspector-header"
                  icon={Film}
                  title="视频参数"
                  summary={videoSummary}
                />
                <div className="pf-panel-body custom-scrollbar">
                  <PanelSection id="tool-video-provider" title="生成设置">
                    <div className="pf-fields">
                      <PanelField label="接口" prefix={<Plug size={14} />}>
                        <select
                          aria-label="视频端点"
                          value={videoSelectionState.selectValue}
                          disabled={!capabilitiesReady || (!videoSelectionState.options.length && !videoSelectionState.staleOptionLabel)}
                          onChange={event => handleVideoProviderChange(event.target.value)}
                        >
                          {!capabilitiesReady && <option value="">读取中…</option>}
                          {capabilitiesReady && videoSelectionState.staleOptionLabel && (
                            <option value={videoSelectionState.selectValue} disabled>
                              {videoSelectionState.staleOptionLabel}
                            </option>
                          )}
                          {capabilitiesReady && !videoSelectionState.options.length && !videoSelectionState.staleOptionLabel && (
                            <option value="">暂无可用接口</option>
                          )}
                          {videoSelectionState.options.map(option => (
                            <option key={option.id} value={option.id}>
                              {option.name}
                            </option>
                          ))}
                        </select>
                      </PanelField>
                      {capabilitiesReady && videoSelectionState.unavailableReason && (
                        <div role="alert" data-testid="video-provider-alert" className="pf-alert">
                          {videoSelectionState.unavailableReason}
                        </div>
                      )}
                      <PanelField label="模型" prefix={<Cpu size={14} />}>
                        <select
                          aria-label="视频模型"
                          value={effectiveVideoModel}
                          title={effectiveVideoModel === SEEDANCE_25_MODERATED
                            ? 'Seedance 2.5 Enhanced Moderation'
                            : effectiveVideoModel === SEEDANCE_25 ? 'Seedance 2.5' : 'Seedance 2.0'}
                          onChange={e => handleVideoModelChange(e.target.value)}
                        >
                          {activeVideoProvider === 'ark' ? (<>
                            <option value={SEEDANCE_20}>Seedance 2.0</option>
                            <option value={SEEDANCE_25}>Seedance 2.5</option>
                          </>) : (<>
                            <option value={SEEDANCE_25}>Seedance 2.5</option>
                            <option value={SEEDANCE_25_MODERATED}>2.5 · 加强审核</option>
                          </>)}
                        </select>
                      </PanelField>
                      <PanelField label="模式">
                        <select
                          aria-label="视频生成模式"
                          value={activeTab.mode}
                          onChange={e => {
                            const mode = e.target.value
                            updateTab(activeTab.id, tab => ({
                              mode,
                              ...(isSeedance25 && mode === 'keyframe' && (tab.firstFrame || tab.lastFrame)
                                ? { ratio: 'adaptive' }
                                : {}),
                            }))
                          }}
                        >
                          <option value="reference">全能参考</option>
                          <option value="keyframe">首尾帧</option>
                        </select>
                      </PanelField>
                    </div>
                  </PanelSection>

                  <PanelSection id="tool-video-output" title="输出参数" summary={videoSummary}>
                    <div className="pf-fields">
                      <PanelField label="画幅" prefix={<RatioGlyph value={effectiveVideoRatio} />}>
                        <select
                          aria-label="视频画幅"
                          value={effectiveVideoRatio}
                          disabled={videoRatioLocked}
                          title={videoRatioLocked ? 'Seedance 2.5 首尾帧模式自动保持首帧比例' : '视频画幅'}
                          onChange={e => updateTab(activeTab.id, { ratio: e.target.value })}
                        >
                          {VIDEO_RATIOS.map(r => (
                            <option key={r} value={r}>{videoRatioLabel(r)}</option>
                          ))}
                        </select>
                      </PanelField>
                      <PanelField label="分辨率">
                        <select
                          aria-label="视频分辨率"
                          value={activeTab.resolution}
                          onChange={e => updateTab(activeTab.id, { resolution: e.target.value })}
                        >
                          {videoCapabilities.resolutions.map(resolution => (
                            <option key={resolution} value={resolution}>{resolution}</option>
                          ))}
                        </select>
                      </PanelField>
                      <PanelField label="时长" prefix={<Clock3 size={14} />}>
                        <select
                          aria-label="视频时长"
                          value={effectiveVideoDuration}
                          title={isSeedance25 && activeTab.mode === 'reference' && hasReadyReferenceVideo
                            ? '参考生视频可指定 4–30 秒；视频编辑必须选择 Auto'
                            : '视频时长'}
                          onChange={e => updateTab(activeTab.id, { duration: Number(e.target.value) })}
                        >
                          {videoDurationOptions.map(d => (
                            <option key={d} value={d}>{d}s</option>
                          ))}
                          <option value={VIDEO_AUTO_DURATION}>
                            {activeVideoProvider === 'cupsy'
                              ? 'Auto'
                              : isSeedance25 && activeTab.mode === 'reference' && hasReadyReferenceVideo
                                ? 'Auto · 编辑跟随输入'
                                : 'Auto'}
                          </option>
                        </select>
                      </PanelField>
                      <PanelToggle
                        label="输出音频"
                        checked={activeTab.audio}
                        onChange={audio => updateTab(activeTab.id, { audio })}
                      />
                      {hasVideoAdvanced && (
                        <CollapsibleAdvanced
                          storageKey={VIDEO_TOOL_ADVANCED_KEY}
                          summary={videoAdvancedSummary}
                          autoOpen={videoAdvancedAutoOpen}
                        >
                          {!isSeedance25 && (
                            <PanelToggle
                              label="快速模式"
                              hint={!activeVideoFastAvailable ? '未配置' : null}
                              title={activeVideoFastAvailable ? '' : '需要配置 Ark Fast endpoint ID'}
                              checked={activeTab.fast}
                              disabled={!activeVideoFastAvailable}
                              onChange={fast => updateTab(activeTab.id, { fast })}
                            />
                          )}
                          {isSeedance25 && activeVideoProvider === 'ark' && (
                            <PanelField label="格式">
                              <select
                                aria-label="视频输出格式"
                                value={activeTab.outputFormat || 'mp4'}
                                onChange={e => updateTab(activeTab.id, { outputFormat: e.target.value })}
                              >
                                <option value="mp4">MP4</option>
                                <option value="mov">MOV</option>
                              </select>
                            </PanelField>
                          )}
                          {activeVideoProvider === 'ark' && (
                            <PanelToggle
                              label="返回尾帧"
                              checked={activeTab.returnLastFrame}
                              onChange={returnLastFrame => updateTab(activeTab.id, { returnLastFrame })}
                            />
                          )}
                        </CollapsibleAdvanced>
                      )}
                    </div>
                  </PanelSection>

                  {/* KEYFRAMES / REFERENCE */}
                  <PanelSection
                    id="tool-video-refs"
                    title={activeTab.mode === 'keyframe' ? '关键帧' : '参考素材'}
                    actions={
                      <button type="button" className="btn btn-secondary btn-sm" onClick={openToolLibrary}>
                        <Library size={13} /> 素材库
                      </button>
                    }
                  >
                    {activeTab.mode === 'keyframe' ? (
                      <div className="flex-grow flex gap-3">
                        <div
                          className="video-material-drop-zone flex w-[120px] flex-col"
                          data-testid="video-first-frame-drop-zone"
                          data-dragging="false"
                          {...videoDropZoneHandlers(files => setVideoKeyframeFile(activeTab.id, 'firstFrame', files))}
                        >
                          <span className="mb-1.5 text-xs text-nexus-text">首帧</span>
                          {activeTab.firstFrame ? (
                            <div className="w-[120px] h-[120px] relative group rounded overflow-hidden border border-nexus-border">
                              <button
                                type="button"
                                aria-label="打开首帧全图"
                                title="查看全图"
                                onClick={() => setReferenceMedia({ type: 'image', src: activeTab.firstFrame.preview, name: activeTab.firstFrame.file?.name || '首帧' })}
                                className="absolute inset-0 cursor-zoom-in outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-green"
                              >
                                <img src={activeTab.firstFrame.thumbnail || activeTab.firstFrame.preview} className="w-full h-full object-cover" alt="首帧" />
                                <Maximize2 size={13} className="absolute bottom-1 left-1 text-white opacity-0 drop-shadow transition-opacity group-hover:opacity-100" />
                              </button>
                              <button type="button" aria-label="删除首帧" title="删除首帧" onClick={() => updateTab(activeTab.id, { firstFrame: null })}
                                className="absolute right-1 top-1 z-10 rounded bg-black/75 p-1 text-white transition-colors hover:bg-nexus-red">
                                <X size={10} />
                              </button>
                            </div>
                          ) : (
                            <label className="flex h-[120px] w-[120px] cursor-pointer flex-col items-center justify-center gap-2 rounded border border-dashed border-nexus-border text-xs text-nexus-text transition-colors hover:border-nexus-green hover:bg-nexus-green/5 hover:text-nexus-green">
                              <Plus size={16} /> 添加
                              <input aria-label="上传首帧" type="file" accept="image/*" className="hidden" onChange={event => {
                                setVideoKeyframeFile(activeTab.id, 'firstFrame', event.target.files)
                                event.target.value = ''
                              }} />
                            </label>
                          )}
                        </div>
                        <div
                          className="video-material-drop-zone flex w-[120px] flex-col"
                          data-testid="video-last-frame-drop-zone"
                          data-dragging="false"
                          {...videoDropZoneHandlers(files => setVideoKeyframeFile(activeTab.id, 'lastFrame', files))}
                        >
                          <span className="mb-1.5 text-xs text-nexus-text">尾帧</span>
                          {activeTab.lastFrame ? (
                            <div className="w-[120px] h-[120px] relative group rounded overflow-hidden border border-nexus-border">
                              <button
                                type="button"
                                aria-label="打开尾帧全图"
                                title="查看全图"
                                onClick={() => setReferenceMedia({ type: 'image', src: activeTab.lastFrame.preview, name: activeTab.lastFrame.file?.name || '尾帧' })}
                                className="absolute inset-0 cursor-zoom-in outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-green"
                              >
                                <img src={activeTab.lastFrame.thumbnail || activeTab.lastFrame.preview} className="w-full h-full object-cover" alt="尾帧" />
                                <Maximize2 size={13} className="absolute bottom-1 left-1 text-white opacity-0 drop-shadow transition-opacity group-hover:opacity-100" />
                              </button>
                              <button type="button" aria-label="删除尾帧" title="删除尾帧" onClick={() => updateTab(activeTab.id, { lastFrame: null })}
                                className="absolute right-1 top-1 z-10 rounded bg-black/75 p-1 text-white transition-colors hover:bg-nexus-red">
                                <X size={10} />
                              </button>
                            </div>
                          ) : (
                            <label className="flex h-[120px] w-[120px] cursor-pointer flex-col items-center justify-center gap-2 rounded border border-dashed border-nexus-border text-xs text-nexus-text transition-colors hover:border-nexus-green hover:bg-nexus-green/5 hover:text-nexus-green">
                              <Plus size={16} /> 添加
                              <input aria-label="上传尾帧" type="file" accept="image/*" className="hidden" onChange={event => {
                                setVideoKeyframeFile(activeTab.id, 'lastFrame', event.target.files)
                                event.target.value = ''
                              }} />
                            </label>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className="grid flex-grow grid-cols-3 gap-2">
                        {/* Reference images */}
                        <div
                          className="video-material-drop-zone flex min-w-0 flex-col"
                          data-testid="video-reference-images-drop-zone"
                          data-dragging="false"
                          {...videoDropZoneHandlers(files => addVideoReferenceImages(activeTab.id, files))}
                        >
                          <span className="mb-1.5 truncate text-xs text-nexus-text" title={`图片（最多 ${videoCapabilities.maxRefImages} 个）`}>图片 · {videoCapabilities.maxRefImages}</span>
                          <div className="flex-grow flex gap-1.5 flex-wrap items-start">
                            {activeTab.refImages.map((img, i) => (
                              <SortableReferenceItem
                                key={i}
                                listId="video-reference-images"
                                index={i}
                                itemCount={activeTab.refImages.length}
                                label="视频参考图片"
                                onMove={(fromIndex, toIndex) => moveVideoReference(activeTab.id, 'refImages', fromIndex, toIndex)}
                                testId={`video-reference-image-item-${i}`}
                                className="group h-14 w-14 shrink-0 overflow-hidden rounded border border-nexus-border"
                              >
                                <button
                                  type="button"
                                  aria-label={`打开视频参考图片 ${i + 1}`}
                                  title="查看全图"
                                  onClick={() => setReferenceMedia({ type: 'image', src: img.preview, name: img.name || `参考图片 ${i + 1}` })}
                                  className="absolute inset-0 cursor-zoom-in outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-green"
                                >
                                  <img src={img.thumbnail || img.preview} className="w-full h-full object-cover" alt={`视频参考图片 ${i + 1}`} />
                                  <Maximize2 size={10} className="absolute bottom-1 left-1 text-white opacity-0 drop-shadow transition-opacity group-hover:opacity-100" />
                                </button>
                                <button type="button" aria-label={`删除参考图片 ${i + 1}`} title="删除" onClick={() => updateTab(activeTab.id, { refImages: activeTab.refImages.filter((_, j) => j !== i) })}
                                  className="absolute right-0.5 top-0.5 z-10 rounded bg-black/75 p-0.5 text-white transition-colors hover:bg-nexus-red">
                                  <X size={8} />
                                </button>
                              </SortableReferenceItem>
                            ))}
                            {activeTab.refImages.length < videoCapabilities.maxRefImages && (
                              <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-xs font-mono">
                                <Plus size={14} />
                                <input aria-label="上传参考图片" type="file" accept="image/*" multiple className="hidden" onChange={event => {
                                  addVideoReferenceImages(activeTab.id, event.target.files)
                                  event.target.value = ''
                                }} />
                              </label>
                            )}
                          </div>
                        </div>
                        {/* Reference videos */}
                        <div
                          className="video-material-drop-zone flex min-w-0 flex-col"
                          data-testid="video-reference-videos-drop-zone"
                          data-dragging="false"
                          {...videoDropZoneHandlers(files => addVideoReferenceVideos(activeTab.id, files))}
                        >
                          <span className="mb-1.5 truncate text-xs text-nexus-text" title={`视频（最多 ${videoCapabilities.maxRefVideos} 个）`}>视频 · {videoCapabilities.maxRefVideos}</span>
                          <div className="flex-grow flex gap-1.5 flex-wrap items-start">
                            {activeTab.refVideos.map((vid, i) => (
                              <SortableReferenceItem
                                key={vid.uid || i}
                                listId="video-reference-videos"
                                index={i}
                                itemCount={activeTab.refVideos.length}
                                label="参考视频"
                                onMove={(fromIndex, toIndex) => moveVideoReference(activeTab.id, 'refVideos', fromIndex, toIndex)}
                                testId={`video-reference-video-item-${i}`}
                                className="group flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded border border-nexus-border bg-[#111]"
                              >
                                <button
                                  type="button"
                                  disabled={vid.uploading || !vid.url}
                                  aria-label={`播放参考视频 ${i + 1}`}
                                  title={vid.uploading ? '视频上传中' : '播放视频'}
                                  onClick={() => setReferenceMedia({ type: 'video', src: vid.url, name: vid.name || `参考视频 ${i + 1}` })}
                                  className="absolute inset-0 flex items-center justify-center outline-none enabled:cursor-pointer focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-green disabled:cursor-default"
                                >
                                  {vid.uploading ? (
                                    <div className="absolute inset-0 flex items-center justify-center">
                                      <div className="w-10 h-1 bg-[#333] rounded overflow-hidden">
                                        <div className="h-full bg-nexus-green transition-all" style={{ width: `${vid.progress || 0}%` }}></div>
                                      </div>
                                    </div>
                                  ) : vid.thumbnail ? (
                                    <img src={vid.thumbnail} className="w-full h-full object-cover" alt={`参考视频 ${i + 1}`} />
                                  ) : (
                                    <Film size={14} className="text-nexus-green" />
                                  )}
                                  <span className="absolute bottom-0.5 w-full truncate text-center font-mono text-[8px] text-nexus-text">{vid.name?.slice(0, 6)}</span>
                                </button>
                                <button type="button" aria-label={`删除参考视频 ${i + 1}`} title="删除" onClick={() => {
                                  if (vid.url && !vid.cupsyAssetId && vid.url.includes('/api/upload_video/')) {
                                    axios.delete('/api/upload_video', { data: { url: vid.url } }).catch(() => {})
                                  }
                                  updateTab(activeTab.id, { refVideos: activeTab.refVideos.filter((_, j) => j !== i) })
                                }}
                                  className="absolute right-0.5 top-0.5 z-10 rounded bg-black/75 p-0.5 text-white transition-colors hover:bg-nexus-red">
                                  <X size={8} />
                                </button>
                              </SortableReferenceItem>
                            ))}
                            {activeTab.refVideos.length < videoCapabilities.maxRefVideos && (
                              <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-xs font-mono">
                                <Plus size={14} />
                                <input aria-label="上传参考视频" type="file" accept="video/mp4,video/quicktime" multiple className="hidden" onChange={event => {
                                  addVideoReferenceVideos(activeTab.id, event.target.files)
                                  event.target.value = ''
                                }} />
                              </label>
                            )}
                          </div>
                        </div>
                        {/* Reference audio */}
                        <div
                          className="video-material-drop-zone flex min-w-0 flex-col"
                          data-testid="video-reference-audios-drop-zone"
                          data-dragging="false"
                          {...videoDropZoneHandlers(files => addVideoReferenceAudios(activeTab.id, files))}
                        >
                          <span className="mb-1.5 truncate text-xs text-nexus-text" title={`音频（最多 ${videoCapabilities.maxRefAudios} 个）`}>音频 · {videoCapabilities.maxRefAudios}</span>
                          <div className="flex-grow flex gap-1.5 flex-wrap items-start">
                            {activeTab.refAudios.map((aud, i) => (
                              <SortableReferenceItem
                                key={i}
                                listId="video-reference-audios"
                                index={i}
                                itemCount={activeTab.refAudios.length}
                                label="参考音频"
                                onMove={(fromIndex, toIndex) => moveVideoReference(activeTab.id, 'refAudios', fromIndex, toIndex)}
                                testId={`video-reference-audio-item-${i}`}
                                className="group flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded border border-nexus-border bg-[#111]"
                              >
                                <button
                                  type="button"
                                  aria-label={`播放参考音频 ${i + 1}`}
                                  title="播放音频"
                                  onClick={() => setReferenceMedia({
                                    type: 'audio',
                                    src: aud.preview || aud.url,
                                    file: aud.file,
                                    name: aud.file?.name || aud.name || `参考音频 ${i + 1}`,
                                  })}
                                  className="absolute inset-0 flex cursor-pointer items-center justify-center outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-cyan"
                                >
                                  <AudioLines size={15} className="text-nexus-cyan" />
                                  <span className="absolute bottom-0.5 w-full truncate text-center font-mono text-[8px] text-nexus-text">{(aud.file?.name || aud.name || 'audio').slice(0, 6)}</span>
                                </button>
                                <button type="button" aria-label={`删除参考音频 ${i + 1}`} title="删除" onClick={() => updateTab(activeTab.id, { refAudios: activeTab.refAudios.filter((_, j) => j !== i) })}
                                  className="absolute right-0.5 top-0.5 z-10 rounded bg-black/75 p-0.5 text-white transition-colors hover:bg-nexus-red">
                                  <X size={8} />
                                </button>
                              </SortableReferenceItem>
                            ))}
                            {activeTab.refAudios.length < videoCapabilities.maxRefAudios && (
                              <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-xs font-mono">
                                <Plus size={14} />
                                <input aria-label="上传参考音频" type="file" accept="audio/wav,audio/mp3,audio/mpeg" multiple className="hidden" onChange={event => {
                                  addVideoReferenceAudios(activeTab.id, event.target.files)
                                  event.target.value = ''
                                }} />
                              </label>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </PanelSection>
                </div>

                <CostEstimateFooter
                  testId="video-cost-estimate"
                  amount={formatUsdEstimate(videoEstimate)}
                  summaryTitle={[videoModelRateLine, videoSizeLine, inputVideo, videoTokenLine].join('；')}
                  details={
                    <div className="pf-cost-detail-list">
                      <div>{videoModelRateLine}</div>
                      <div>{videoSizeLine}</div>
                      <div>{inputVideo}</div>
                      <div className="pf-cost-detail-muted">{videoTokenLine}</div>
                    </div>
                  }
                />
              </aside>
            )
          })()}
        </>
      ) : (
        /* ============ AUDIO MODE ============ */
        <>
          <section className="prompt-pane relative z-20">
            <div className="relative flex min-h-0 flex-grow flex-col">
              <div className="prompt-pane-header flex h-11 shrink-0 items-center justify-between px-4">
                <span className="text-xs font-medium text-nexus-text-light">音频场景提示词</span>
                <span className={`font-mono text-xs ${audioForm.prompt.length > 3000 ? 'text-nexus-red' : 'text-nexus-muted'}`}>{audioForm.prompt.length} / 3000</span>
              </div>
              <PromptMentionTextarea
                aria-label="音频提示词"
                value={audioForm.prompt}
                maxLength={3000}
                onValueChange={prompt => updateAudioForm({ prompt })}
                mentionItems={promptMentionItems}
                wrapperClassName="relative min-h-0 flex-grow"
                className="absolute inset-0 resize-none bg-transparent px-4 py-4 text-sm leading-6 text-nexus-text-light outline-none custom-scrollbar placeholder:text-nexus-muted"
                placeholder="描述对白、音乐、环境声、音效及时间关系..."
              />
              <div className="absolute bottom-4 right-4 z-10">
                <button
                  type="button"
                  aria-label="保存到提示词库"
                  title="保存到提示词库"
                  onClick={handleSavePrompt}
                  disabled={!audioForm.prompt.trim()}
                  className="btn btn-icon btn-outlined"
                >
                  <Save size={16} />
                </button>
              </div>
            </div>
            <div className="prompt-actions z-10 border-t border-nexus-border p-3">
              {capabilitiesReady && audioSelectionState.unavailableReason && (
                <div role="alert" data-testid="audio-provider-action-alert" className="mb-2 text-xs text-nexus-red leading-5">
                  {audioSelectionState.unavailableReason}
                </div>
              )}
              <button
                type="button"
                onClick={handleAudioGenerate}
                disabled={!capabilitiesReady || !activeAudioOption}
                title={audioSelectionState.unavailableReason || ''}
                className="btn btn-primary btn-lg btn-block"
              >
                <Play size={14} fill="currentColor" /> <span>生成音频</span>
              </button>
            </div>
          </section>

          <div
            onMouseDown={handleDragStart}
            onKeyDown={handleResizeKeyDown}
            className="workspace-resizer z-20"
            role="separator"
            tabIndex={0}
            aria-orientation="vertical"
            aria-valuemin={300}
            aria-valuemax={560}
            aria-valuenow={panelWidth}
            aria-label="调整提示词面板宽度"
          />

          <section className="canvas-pane">
            <div className="canvas-grid" />
            <TaskGallery key="audio" mode="audio" refreshToken={taskGalleryRevision} onReuseTask={handleLoadTask} />
          </section>

          {(() => {
            const audioFormatLabel = AUDIO_OUTPUT_FORMATS.find(item => item.value === audioForm.outputFormat)?.label || audioForm.outputFormat.toUpperCase()
            const audioRateLabel = `${(audioForm.sampleRate / 1000).toFixed(audioForm.sampleRate % 1000 ? 1 : 0)} kHz`
            const audioSummary = `${audioFormatLabel} · ${audioRateLabel}`
            const speakerBlocked = audioForm.referenceMode === 'image'
            return (
              <aside key="inspector-audio" className="inspector-pane pf-panel">
                <PanelHeader
                  className="inspector-header"
                  icon={Music}
                  title="音频参数"
                  summary={audioSummary}
                />
                <div className="pf-panel-body custom-scrollbar">
                  <PanelSection id="tool-audio-provider" title="生成设置">
                    <div className="pf-fields">
                      <PanelField label="接口" prefix={<Plug size={14} />}>
                        <select
                          aria-label="音频端点"
                          value={audioSelectionState.selectValue}
                          disabled={!capabilitiesReady || (!audioSelectionState.options.length && !audioSelectionState.staleOptionLabel)}
                          onChange={event => handleAudioProviderChange(event.target.value)}
                        >
                          {!capabilitiesReady && <option value="">读取中…</option>}
                          {capabilitiesReady && audioSelectionState.staleOptionLabel && (
                            <option value={audioSelectionState.selectValue} disabled>
                              {audioSelectionState.staleOptionLabel}
                            </option>
                          )}
                          {capabilitiesReady && !audioSelectionState.options.length && !audioSelectionState.staleOptionLabel && (
                            <option value="">暂无可用接口</option>
                          )}
                          {audioSelectionState.options.map(option => (
                            <option key={option.id} value={option.id}>
                              {option.name}
                            </option>
                          ))}
                        </select>
                      </PanelField>
                      {capabilitiesReady && audioSelectionState.unavailableReason && (
                        <div role="alert" data-testid="audio-provider-alert" className="pf-alert">
                          {audioSelectionState.unavailableReason}
                        </div>
                      )}
                      <PanelField label="模型" hint="由当前接口配置决定" prefix={<Cpu size={14} />}>
                        <select aria-label="音频模型" value={CUPSY_AUDIO_MODEL} disabled onChange={() => {}} className="pf-readonly-select">
                          <option value={CUPSY_AUDIO_MODEL}>Seed Audio 1.0</option>
                        </select>
                      </PanelField>
                    </div>
                  </PanelSection>

                  <PanelSection id="tool-audio-output" title="输出参数" summary={audioSummary}>
                    <div className="pf-fields">
                      <PanelField
                        label="声线"
                        prefix={<Mic size={14} />}
                        note={speakerBlocked ? '预设声线不能与图片参考同时使用' : null}
                      >
                        <select
                          aria-label="音频预设声线"
                          value={speakerBlocked ? '' : audioForm.speaker}
                          disabled={speakerBlocked}
                          title={speakerBlocked ? '预设声线不能与图片参考同时使用' : '音频预设声线'}
                          onChange={event => {
                            const speaker = event.target.value
                            const maxAssets = speaker ? 2 : 3
                            updateAudioForm(form => ({
                              speaker,
                              ...(speaker && form.referenceMode === 'none' ? { referenceMode: 'audio' } : {}),
                              references: form.references.slice(0, maxAssets),
                            }))
                          }}
                        >
                          {AUDIO_SPEAKERS.map(item => (
                            <option key={item.value || 'auto'} value={item.value}>{item.label}</option>
                          ))}
                        </select>
                      </PanelField>
                      <PanelField label="格式">
                        <select
                          aria-label="音频输出格式"
                          value={audioForm.outputFormat}
                          onChange={event => updateAudioForm({ outputFormat: event.target.value })}
                        >
                          {AUDIO_OUTPUT_FORMATS.map(item => (
                            <option key={item.value} value={item.value}>{item.label}</option>
                          ))}
                        </select>
                      </PanelField>
                      <PanelField label="采样率">
                        <select
                          aria-label="音频采样率"
                          value={audioForm.sampleRate}
                          onChange={event => updateAudioForm({ sampleRate: Number(event.target.value) })}
                        >
                          {AUDIO_SAMPLE_RATES.map(rate => (
                            <option key={rate} value={rate}>{rate === 44100 ? '44.1' : rate / 1000} kHz</option>
                          ))}
                        </select>
                      </PanelField>
                      <PanelToggle
                        label="生成字幕"
                        checked={audioForm.enableSubtitle}
                        onChange={enableSubtitle => updateAudioForm({ enableSubtitle })}
                      />
                      <CollapsibleAdvanced
                        storageKey={AUDIO_TOOL_ADVANCED_KEY}
                        summary={audioForm.watermark ? '可听水印' : '无水印'}
                        autoOpen={Boolean(audioForm.watermark)}
                      >
                        <PanelToggle
                          label="可听水印"
                          checked={audioForm.watermark}
                          onChange={watermark => updateAudioForm({ watermark })}
                        />
                      </CollapsibleAdvanced>
                      <p className="pf-note">时长由内容决定，最长 120 秒。预设声线不能与图片参考同时使用。</p>
                    </div>
                  </PanelSection>

                  <PanelSection
                    id="tool-audio-refs"
                    title="参考素材"
                    actions={<button type="button" className="btn btn-secondary btn-sm" onClick={openToolLibrary}><Library size={13} /> 素材库</button>}
                  >
                    <SegmentedControl
                      label="音频参考模式"
                      value={audioForm.referenceMode}
                      onChange={referenceMode => updateAudioForm({ referenceMode, references: [], ...(referenceMode !== 'audio' ? { speaker: '' } : {}) })}
                      options={[{ value: 'none', label: '纯文本' }, { value: 'audio', label: '音频' }, { value: 'image', label: '图片' }]}
                    />
                    {audioForm.referenceMode !== 'none' && (
                      <div
                        className="audio-reference-drop-zone"
                        data-dragging="false"
                        {...videoDropZoneHandlers(addAudioReferences)}
                      >
                        <div className="grid grid-cols-3 gap-2">
                          {audioForm.references.map((reference, index) => (
                            <div key={reference.uid || `${reference.cupsyAssetId || reference.mediaId || 'ref'}-${index}`} className="audio-reference-card group relative">
                              <button type="button" className="absolute inset-0 flex flex-col items-center justify-center gap-1 p-2" onClick={() => setReferenceMedia({ type: reference.kind, src: reference.preview, name: reference.name })}>
                                {reference.kind === 'image' ? <img src={reference.thumbnail || reference.preview} alt={reference.name} className="size-full object-cover" /> : <AudioLines size={22} className="text-nexus-cyan" />}
                                {reference.kind === 'audio' && <span className="w-full truncate text-center text-xs text-nexus-muted">[Audio{index + (audioForm.speaker ? 2 : 1)}]</span>}
                              </button>
                              <button type="button" aria-label={`删除参考素材 ${index + 1}`} onClick={() => updateAudioForm(form => ({ references: form.references.filter((_, itemIndex) => itemIndex !== index) }))} className="absolute right-1 top-1 z-10 rounded bg-black/75 p-1 text-white opacity-0 group-hover:opacity-100 hover:bg-nexus-red"><X size={10} /></button>
                            </div>
                          ))}
                          {audioForm.references.length < (audioForm.referenceMode === 'image' ? 1 : 3 - (audioForm.speaker ? 1 : 0)) && (
                            <label className="audio-reference-add">
                              <Plus size={15} />
                              <span>{audioUploading ? '上传中' : '添加'}</span>
                              <input type="file" className="hidden" disabled={audioUploading} multiple={audioForm.referenceMode === 'audio'} accept={audioForm.referenceMode === 'image' ? 'image/*' : 'audio/wav,audio/mp3,audio/mpeg'} onChange={event => { addAudioReferences(event.target.files); event.target.value = '' }} />
                            </label>
                          )}
                        </div>
                        <div className="mt-2 font-mono text-xs text-nexus-muted">
                          {audioForm.referenceMode === 'audio' ? '按顺序对应 [Audio1]–[Audio3]' : '图片用于引导完整音频场景'}
                        </div>
                      </div>
                    )}
                  </PanelSection>
                </div>

                <CostEstimateFooter
                  testId="audio-cost-estimate"
                  amount="未知"
                  tone="muted"
                  summaryTitle="音频生成暂无官方定价依据，不计作 $0"
                  details={
                    <div className="pf-cost-detail-list">
                      <div>Seed Audio 1.0 · Cupsy</div>
                      <div className="pf-cost-detail-muted">音频生成暂无官方定价依据，不计作 $0</div>
                    </div>
                  }
                />
              </aside>
            )
          })()}
        </>
      )}

      {/* 右侧抽屉：提示词库（仅独立工具页；画布模式联动左侧提示词面板） */}
      <AnimatePresence>
        {showPromptCollection && appMode !== 'canvas' && (
          <motion.aside
            ref={promptDrawerRef}
            tabIndex={-1}
            role="dialog"
            aria-label="提示词库"
            initial={{ x: '100%', opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: '100%', opacity: 0 }}
            transition={{ type: 'spring', damping: 28, stiffness: 260 }}
            className="drawer-panel liquid-glass-strong absolute bottom-0 right-0 top-0 z-40 flex flex-col outline-none"
          >
            <div className="glass-drawer-header flex h-11 shrink-0 items-center justify-between px-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-nexus-text-light">
                <Library size={15} className="text-nexus-violet" /> 提示词库
              </div>
              <IconButton label="关闭提示词库" onClick={() => closePromptDrawer(true)}><X size={16} /></IconButton>
            </div>
            <div className="relative flex-grow overflow-hidden">
              <PromptCollection onSelectPrompt={handleSelectSavedPrompt} />
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      </main>

      {showPngInfo && <PngInfoModal
        open={showPngInfo}
        onClose={() => setShowPngInfo(false)}
        onApply={handleApplyPngInfo}
        onApplyCanvas={handleApplyPngInfoToCanvas}
        preferCanvas={appMode === 'canvas'}
      />}
      {referenceMedia && <ReferenceMediaModal media={referenceMedia} onClose={() => setReferenceMedia(null)} />}
      {showGlobalLibrary && <ToolAssetLibrary
        browseOnly
        remote
        onClose={() => setShowGlobalLibrary(false)}
        onPreview={setReferenceMedia}
        notify={notify}
      />}
      {showCupsyAssets && <ToolAssetLibrary
        onApply={useLocalLibraryItems}
        onRemoteApply={useRemoteLibraryItems}
        validateSelection={validateLibraryReferences}
        remote={appMode==='audio'||appMode==='video'&&activeVideoProvider==='cupsy'}
        mode={appMode === 'audio' ? 'audio' : activeTab.mode}
        allowedKinds={appMode === 'image'||appMode==='video'&&activeTab.mode==='keyframe'?['image']:appMode === 'audio' ? ['image', 'audio'] : ['image','video','audio']}
        onClose={() => setShowCupsyAssets(false)}
        onUse={useCupsyAsset}
        onPreview={setReferenceMedia}
        notify={notify}
      />}

      {/* 全屏 Prompt 编辑器弹窗 */}
      {ReactDOM.createPortal(
        <AnimatePresence>
          {showFullEditor && (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              ref={fullEditorRef}
              tabIndex={-1}
              role="dialog"
              aria-modal="true"
              aria-label="提示词编辑器"
              className="fixed inset-0 z-[999] flex flex-col bg-nexus-bg/98 backdrop-blur-sm"
            >
              {/* 标题栏 */}
              <div className="editor-header liquid-glass-strong flex h-12 shrink-0 items-center justify-between px-3">
                <div className="flex min-w-0 items-center gap-2 text-sm text-nexus-text-light">
                  <Maximize2 size={15} className="shrink-0 text-nexus-blue" />
                  <span className="font-semibold">提示词编辑器</span>
                  <span className="truncate font-mono text-xs text-nexus-muted">{appMode === 'video' ? 'video_prompt' : appMode === 'audio' ? 'audio_prompt' : 'image_prompt'}</span>
                </div>
                <div className="flex items-center gap-1">
                  <IconButton label="提示词库" onClick={() => setShowEditorVault(!showEditorVault)} className={showEditorVault ? 'is-active' : ''}><Library size={16} /></IconButton>
                  <IconButton label="保存提示词" onClick={handleSavePrompt} disabled={!currentEditorPrompt.trim()}><Save size={16} /></IconButton>
                  <IconButton label="关闭编辑器" onClick={() => { setShowFullEditor(false); setShowEditorVault(false) }}><X size={17} /></IconButton>
                </div>
              </div>

              {/* 编辑器主体 */}
              <div className="flex-grow flex min-h-0 relative">
                {/* 行号 */}
                <div className="editor-gutter w-14 shrink-0 select-none overflow-hidden border-r border-nexus-border bg-nexus-panel py-4 pr-3 text-right font-mono text-xs text-nexus-muted/60">
                  {Array.from({ length: Math.max(50, currentEditorPrompt.split('\n').length) }, (_, i) => (
                    <div key={i} className="h-6 leading-6">{i + 1}</div>
                  ))}
                </div>
                {/* 输入区 */}
                <PromptMentionTextarea
                  autoFocus
                  aria-label="编辑提示词"
                  value={currentEditorPrompt}
                  onValueChange={setCurrentEditorPrompt}
                  mentionItems={promptMentionItems}
                  wrapperClassName="relative min-w-0 flex-grow"
                  className="absolute inset-0 resize-none overflow-y-auto whitespace-pre-wrap break-words bg-transparent p-4 font-mono text-sm leading-6 text-nexus-text-light outline-none custom-scrollbar"
                  spellCheck="true"
                  placeholder="输入提示词..."
                />
                {/* Vault 侧边栏 */}
                {showEditorVault && (
                  <aside className="editor-vault liquid-glass-strong flex w-[360px] shrink-0 flex-col overflow-hidden">
                    <div className="flex h-10 shrink-0 items-center gap-2 border-b border-nexus-border px-3 text-xs font-semibold text-nexus-text-light"><Library size={14} className="text-nexus-violet" />提示词库</div>
                    <PromptCollection onSelectPrompt={setCurrentEditorPrompt} />
                  </aside>
                )}
              </div>

              {/* 底栏 */}
              <div className="flex h-8 shrink-0 items-center gap-4 border-t border-nexus-border bg-nexus-panel px-4 font-mono text-xs text-nexus-muted">
                <span>行 {currentEditorPrompt.split('\n').length}</span>
                <span>字符 {currentEditorPrompt.length}</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}

      {showProviderSettings && <React.Suspense fallback={null}>
        <ProviderSettings onClose={() => setShowProviderSettings(false)} onSaved={() => { setProviderRevision(value => value + 1); fetchAllProviderCapabilities() }} />
      </React.Suspense>}
      <AnimatePresence>
        {notification && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            role={notification.tone === 'error' ? 'alert' : 'status'}
            aria-live="polite"
            data-testid="app-notification"
            className={`fixed bottom-[88px] left-1/2 -translate-x-1/2 z-[1200] pointer-events-none flex max-w-[min(560px,calc(100vw-32px))] items-center gap-2 rounded-md border px-3 py-2.5 text-sm shadow-2xl ${notification.tone === 'error' ? 'border-nexus-red/35 bg-[#211417] text-nexus-red' : 'border-nexus-green/35 bg-[#1c1408] text-nexus-text-light'}`}
          >
            {notification.tone === 'error' ? <CircleAlert size={15} /> : <Check size={15} className="text-nexus-green" />}
            {notification.message}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default App
