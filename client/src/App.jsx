import React, { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import TextToImage from './components/TextToImage'
import ImageToImage from './components/ImageToImage'
import ImageOutputControls from './components/image-parameters/ImageOutputControls'
import useImageDimensionDraft from './components/image-parameters/useImageDimensionDraft'
import {imageCapabilities,imageTabParams,imageTabPatch,imageParameterIssues,imageRequestFields,imageSizeSummary as getImageSizeSummary} from './lib/imageGenerationRules'
import PromptCollection from './components/PromptCollection'
import TaskGallery from './components/TaskGallery'
import PngInfoModal from './components/PngInfoModal'
import ReferenceMediaModal from './components/ReferenceMediaModal'
import ToolAssetLibrary from './components/library/ToolAssetLibrary'
import PromptMentionTextarea from './components/PromptMentionTextarea'
import SortableReferenceItem, { moveArrayItem } from './components/SortableReferenceItem'
import GlassBackdrop from './components/GlassBackdrop'
import IconButton from './components/ui/IconButton'
import SegmentedControl from './components/ui/SegmentedControl'
import ToggleSwitch from './components/ui/ToggleSwitch'
import { motion, AnimatePresence } from 'framer-motion'
import ReactDOM from 'react-dom'
import { Play, Settings, Cpu, HardDrive, Grid3X3, Database, X, Maximize2, Save, ImageDown, Film, LogOut, Check, Image as ImageIcon, Library, Plus, SlidersHorizontal, Braces, AudioLines, CircleAlert, FileSearch, Layers3 } from 'lucide-react'
import {videoCapabilities as getVideoCapabilities,videoDurations,videoRatio,VIDEO_RATIOS,VIDEO_AUTO_DURATION} from './lib/videoGenerationRules.js'
import { estimateBytePlusVideoCost, formatUsdEstimate, formatWanTokens } from './lib/byteplusPricing'
import { persistWorkspaceBlob, useWorkspaceObjectUrls, useWorkspaceState, workspaceImageFields } from './lib/useWorkspaceState'
import { SEEDANCE_20, SEEDANCE_25, SEEDANCE_25_MODERATED, CUPSY_VIDEO_MODELS, CUPSY_AUDIO_MODEL, AUDIO_SAMPLE_RATES, AUDIO_SPEAKERS, VIDEO_MODEL_CAPABILITIES } from './lib/generationSettings.js'
import { currentPromptMentionItems, restoredTaskReferences, isImageFile, isVideoFile, isAudioFile, readFileDataUrl, videoDropZoneHandlers } from './lib/referenceMedia.js'
import { makeImgTab, makeVideoTab, DEFAULT_AUDIO_FORM, IMAGE_WORKSPACE_OPTIONS, VIDEO_WORKSPACE_OPTIONS } from './lib/workspaceTabs.js'

axios.defaults.withCredentials = true

const LayerStudio = React.lazy(() => import('./components/LayerStudio'))
const CanvasStudio = React.lazy(() => import('./components/canvas/CanvasStudio'))
const ProviderSettings = React.lazy(() => import('./components/providers/ProviderSettings'))

function App({ onLogout }) {
  const handleLogout = async () => {
    await axios.post('/api/logout').catch(() => {})
    onLogout()
  }

  const [showPromptCollection, setShowPromptCollection] = useState(false)
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
  const appShellRef = useRef(null)

  const notify = useCallback((message, tone = 'success') => {
    window.clearTimeout(notificationTimer.current)
    setNotification({ message, tone })
    notificationTimer.current = window.setTimeout(() => setNotification(null), 2800)
  }, [])

  useEffect(() => () => window.clearTimeout(notificationTimer.current), [])

  useEffect(() => {
    const shell = appShellRef.current
    if (!shell || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined
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
  }, [])

  const [apiProvider, setApiProvider] = useState('ark')
  const [providerInfoReady, setProviderInfoReady] = useState(false)
  const [imageProviders, setImageProviders] = useState({})

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
  const [appMode, setAppMode] = useWorkspaceState('appMode', 'canvas')
  const canvasBeforeLeave = useRef(null), modeSwitchPending = useRef(false)
  async function changeAppMode(mode) {
    if (mode === appMode || modeSwitchPending.current) return
    modeSwitchPending.current = true
    try {
      if (appMode === 'canvas' && canvasBeforeLeave.current && !await canvasBeforeLeave.current()) return
      setAppMode(mode)
    } catch (error) { notify(error?.message || '暂时无法切换工具，请重试', 'error') }
    finally { modeSwitchPending.current = false }
  }


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

  const activeVideoProvider = activeTab.provider === 'cupsy' ? 'cupsy' : 'ark'
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

  const handleVideoProviderChange = useCallback((provider) => {
    updateTab(activeTab.id, tab => provider === 'cupsy' ? {
      provider: 'cupsy',
      model: CUPSY_VIDEO_MODELS.includes(tab.model) ? tab.model : SEEDANCE_25,
      duration: tab.duration,
      resolution: VIDEO_MODEL_CAPABILITIES[SEEDANCE_25].resolutions.includes(tab.resolution)
        ? tab.resolution
        : '720p',
      fast: false, outputFormat: 'mp4', returnLastFrame: false,
    } : {
      provider: 'ark',
      model: tab.model === SEEDANCE_20 ? SEEDANCE_20 : SEEDANCE_25,
    })
  }, [activeTab.id, updateTab])

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
    const files=await Promise.all(items.map(async item=>{const response=await fetch(item.asset.url);if(!response.ok)throw new Error('素材读取失败，请重新选择');return new File([await response.blob()],item.asset.name,{type:item.asset.mime_type||`${item.asset.kind}/*`})}))
    if(!owner||Object.keys(owner).some(key=>owner[key]!==libraryContext.current[key]))throw new Error('原工具或表单已切换，请重新选择素材')
    if(owner.mode==='image'){const additions=files.map(file=>({uid:`library-${Date.now()}-${Math.random()}`,file,preview:createReferencePreview(file),name:file.name,hasAlpha:null}));updateImgTab(owner.imageId,tab=>({uploadedImages:[...(tab.uploadedImages||[]),...additions]}))}
    else if(owner.mode==='audio'){if(!await addAudioReferences(files))throw new Error('参考素材上传失败，选择已保留，请重试')}
    else if(activeTab.mode==='keyframe')addPastedKeyframes(owner.videoId,files)
    else{const images=files.filter(isImageFile),videos=files.filter(isVideoFile),audios=files.filter(isAudioFile);if(images.length)addVideoReferenceImages(owner.videoId,images);if(videos.length)addVideoReferenceVideos(owner.videoId,videos);if(audios.length)addVideoReferenceAudios(owner.videoId,audios)}
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
  }, [audioForm.referenceMode, audioForm.references.length, audioForm.speaker, notify, updateAudioForm])
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

  const isArk = apiProvider === 'ark'
  const isCupsyImage = apiProvider === 'cupsy'
  const isSeedream = isArk || isCupsyImage
  const imageCapabilityModel = imageProviders[apiProvider]?.capability_model || imageProviders[apiProvider]?.model
  const imageSpec = imageCapabilities(apiProvider,imageCapabilityModel)
  const aspectRatios = imageSpec.ratios, resolutions = imageSpec.resolutions
  const imageParams = imageTabParams(apiProvider, activeImgTab)
  const imageReferences = (activeImgTab.uploadedImages || []).map((image, index) => ({
    id: String(index), name: image.name || image.file?.name || `参考素材 ${index + 1}`,
    width: image.width, height: image.height, has_alpha: image.hasAlpha,
    size_bytes: image.file?.size || image.size || 0,
  }))
  const changeImageParams = patch => updateImgTab(activeImgTab.id, imageTabPatch(patch))
  const imageDimensions = useImageDimensionDraft(imageParams, changeImageParams, activeImgTab.id)
  const imageIssues = imageParameterIssues(apiProvider, imageParams, imageReferences,imageCapabilityModel)
  const imageSizeSummary = getImageSizeSummary(apiProvider, imageParams)

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

  useEffect(() => {
    fetchProviderInfo()
    fetchVideoProviderInfo()
    fetchAudioProviderInfo()
  }, [])

  useEffect(() => {
    if (videoFastAvailable || !activeTab.fast) return
    updateTab(activeTab.id, { fast: false })
  }, [activeTab.fast, activeTab.id, updateTab, videoFastAvailable])

  useEffect(() => {
    const handleEsc = (e) => { if (e.key === 'Escape') { setShowFullEditor(false); setShowEditorVault(false) } }
    if (showFullEditor) window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [showFullEditor])

  const fetchProviderInfo = async () => {
    try {
      const response = await axios.get('/api/provider')
      if (response.data.success) {
        setApiProvider(['ark', 'cupsy'].includes(response.data.current_provider) ? response.data.current_provider : 'ark')
        setImageProviders(response.data.providers || {})
      }
    } catch (error) {
      console.error('Failed to fetch provider info:', error)
    } finally {
      setProviderInfoReady(true)
    }
  }

  const fetchVideoProviderInfo = async () => {
    try {
      const response = await axios.get('/api/video/provider')
      if (response.data.success) {
        setVideoFastAvailable(response.data.fast_available !== false)
        if (response.data.providers) setVideoProviders(response.data.providers)
      }
    } catch (error) {
      console.error('Failed to fetch video provider info:', error)
    }
  }

  const fetchAudioProviderInfo = async () => {
    try {
      const response = await axios.get('/api/audio/provider')
      if (response.data.success) {
        setAudioProvider({
          available: Boolean(response.data.providers?.cupsy?.available),
          sourceReady: response.data.providers?.cupsy?.source_ready !== false,
        })
      }
    } catch (error) {
      console.error('Failed to fetch audio provider info:', error)
    }
  }

  const handleImageProviderChange = async (newProvider) => {
    if (newProvider === apiProvider) return
    try {
      const response = await axios.post('/api/provider', { provider: newProvider })
      if (response.data.success) {
        setApiProvider(newProvider)
      }
    } catch (error) { notify(`切换失败：${error.response?.data?.error || error.message}`, 'error') }
  }
  
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
    if (!tab.prompt.trim()) {
      notify('请先填写图片描述', 'error')
      return
    }
    const issues = imageParameterIssues(apiProvider, imageTabParams(apiProvider, tab), imageReferences,imageCapabilityModel)
    if (issues.length || (isSeedream && imageDimensions.error)) {
      notify(issues[0] || imageDimensions.error, 'error')
      return
    }
    const imageOptions = imageRequestFields(apiProvider, imageTabParams(apiProvider, tab))
    const revealTimer = window.setTimeout(
      () => setTaskGalleryRevision(revision => revision + 1),
      500,
    )

    try {
      let response
      if (tab.uploadedImages.length === 0) {
        response = await axios.post('/api/generate', {
          prompt: tab.prompt, provider: apiProvider, ...imageOptions,
        })
      } else {
        const imageUrls = await Promise.all(tab.uploadedImages.map(async image => {
          if (image.preview?.startsWith('/api/workspace/assets/img_tabs/') && !image.file) {
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
          prompt: tab.prompt, provider: apiProvider, ...imageOptions,
          image_urls: imageUrls,
        })
      }

      const taskId = response.data.task_id
      notify(taskId ? `图片任务 #${taskId} 已创建` : '图片任务已创建')
    } catch (err) {
      const errorData = err.response?.data || {}
      notify(errorData.error || err.message || '图片任务创建失败', 'error')
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
    if (!videoTabHasInput(tab)) {
      notify('请填写视频提示词或添加参考素材', 'error')
      return
    }
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
      const hasFiles = Boolean(tab.firstFrame || tab.lastFrame || tab.refImages.length > 0 || tab.refAudios.length > 0)

      const cupsyAssets = tab.mode === 'keyframe'
        ? [
            tab.firstFrame?.cupsyAssetId && { id: tab.firstFrame.cupsyAssetId, role: 'first_frame' },
            tab.lastFrame?.cupsyAssetId && { id: tab.lastFrame.cupsyAssetId, role: 'last_frame' },
          ].filter(Boolean)
        : [
            ...tab.refImages.filter(item => item.cupsyAssetId).map(item => ({ id: item.cupsyAssetId, role: 'reference_image' })),
            ...readyRefVideos.filter(item => item.cupsyAssetId).map(item => ({ id: item.cupsyAssetId, role: 'reference_video' })),
            ...tab.refAudios.filter(item => item.cupsyAssetId).map(item => ({ id: item.cupsyAssetId, role: 'reference_audio' })),
          ]

      // 收集已上传的视频 URL
      const videoUrls = readyRefVideos.filter(v => !v.cupsyAssetId).map(v => v.url)

      if (hasFiles) {
        const formData = new FormData()
        formData.append('prompt', tab.prompt)
        formData.append('ratio', effectiveVideoRatio)
        formData.append('duration', effectiveVideoDuration)
        formData.append('resolution', tab.resolution)
        formData.append('model', effectiveVideoModel)
        formData.append('output_format', tab.outputFormat || 'mp4')
        formData.append('fast', tab.fast)
        formData.append('generate_audio', tab.audio)
        formData.append('return_last_frame', tab.returnLastFrame)
        formData.append('video_mode', tab.mode)
        formData.append('provider', activeVideoProvider)
        if (cupsyAssets.length) formData.append('cupsy_assets', JSON.stringify(cupsyAssets))
        const pendingFetches = []
        if (tab.mode === 'keyframe') {
          if (tab.firstFrame && !tab.firstFrame.cupsyAssetId) {
            if (tab.firstFrame.file) formData.append('image', tab.firstFrame.file)
            else if (tab.firstFrame.preview) pendingFetches.push(
              ensureFetchOk(tab.firstFrame.preview).then(blob => formData.append('image', blob, 'first_frame.png'))
            )
          }
          if (tab.lastFrame && !tab.lastFrame.cupsyAssetId) {
            if (tab.lastFrame.file) formData.append('last_image', tab.lastFrame.file)
            else if (tab.lastFrame.preview) pendingFetches.push(
              ensureFetchOk(tab.lastFrame.preview).then(blob => formData.append('last_image', blob, 'last_frame.png'))
            )
          }
        } else {
          const [resolvedRefImages, resolvedRefAudios] = await Promise.all([
            Promise.all(tab.refImages.map(async (img, index) => {
              if (img.cupsyAssetId) return null
              if (img.file) return { blob: img.file, name: img.name || img.file.name || `ref_${index}.png` }
              if (!img.preview) return null
              return { blob: await ensureFetchOk(img.preview), name: img.name || `ref_${index}.png` }
            })),
            Promise.all(tab.refAudios.map(async (aud, index) => {
              if (aud.cupsyAssetId) return null
              if (aud.file) return { blob: aud.file, name: aud.name || aud.file.name || `audio_${index}.wav` }
              if (!aud.preview) return null
              return { blob: await ensureFetchOk(aud.preview), name: aud.name || `audio_${index}.wav` }
            })),
          ])
          resolvedRefImages.filter(Boolean).forEach(({ blob, name }) => formData.append('ref_images', blob, name))
          resolvedRefAudios.filter(Boolean).forEach(({ blob, name }) => formData.append('ref_audios', blob, name))
        }
        if (videoUrls.length) formData.append('ref_video_urls', JSON.stringify(videoUrls))
        if (pendingFetches.length) await Promise.all(pendingFetches)
        resp = await axios.post('/api/video/generate', formData, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 300000 })
      } else {
        resp = await axios.post('/api/video/generate', {
          prompt: tab.prompt, ratio: effectiveVideoRatio, duration: effectiveVideoDuration,
          resolution: tab.resolution, model: effectiveVideoModel,
          output_format: tab.outputFormat || 'mp4', fast: tab.fast, generate_audio: tab.audio,
          return_last_frame: tab.returnLastFrame,
          video_mode: tab.mode,
          provider: activeVideoProvider,
          ref_video_urls: videoUrls.length ? videoUrls : undefined,
          cupsy_assets: cupsyAssets.length ? cupsyAssets : undefined,
        }, { timeout: 300000 })
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
    if (!audioForm.prompt.trim()) {
      notify('请填写音频提示词', 'error')
      return
    }
    if (!audioProvider.available) {
      notify('Cupsy 音频端点未配置', 'error')
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
    const revealTimer = window.setTimeout(() => setTaskGalleryRevision(revision => revision + 1), 500)
    try {
      const response = await axios.post('/api/audio/generate', {
        prompt: audioForm.prompt,
        model: CUPSY_AUDIO_MODEL,
        output_format: audioForm.outputFormat,
        sample_rate: Number(audioForm.sampleRate),
        enable_subtitle: Boolean(audioForm.enableSubtitle),
        watermark: Boolean(audioForm.watermark),
        reference_mode: audioForm.referenceMode,
        speaker: audioForm.referenceMode === 'audio' ? audioForm.speaker : '',
        cupsy_assets: audioForm.references.map(reference => ({ id: reference.cupsyAssetId })),
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
    }
  }, [activeImgTab.id, activeTab.id, setImgTabs, setActiveImgTabId, setVideoTabs, setActiveVideoTabId, setAppMode, updateAudioForm])

  const handleDragStart = (e) => {
    e.preventDefault()
    isDragging.current = true
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    const onMove = (ev) => {
      if (!isDragging.current) return
      setPanelWidth(Math.min(560, Math.max(300, ev.clientX)))
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
    if (appMode === 'video') updateTab(activeTab.id, { prompt })
    else if (appMode === 'audio') updateAudioForm({ prompt })
    else updateImgTab(activeImgTab.id, { prompt })
    setShowPromptCollection(false)
  }
  const imageModelValue = isSeedream
    ? (isCupsyImage ? 'seedream-5.0-pro' : imageProviders.ark?.model || 'seedream-5-0-pro')
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
      {appMode !== 'canvas' && <GlassBackdrop />}
      
      {/* 极简顶栏 */}
      <header className="app-header liquid-glass flex items-center justify-between px-3 z-50 shrink-0">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex shrink-0 items-center gap-2">
            <div className="brand-mark flex size-8 items-center justify-center text-nexus-green">
              <Braces size={15} />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold text-white">Ink Traces</div>
              <div className="brand-version font-mono text-[10px] text-nexus-muted">VISUAL WORKSPACE</div>
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
            ]}
          />
        </div>
        <div className="header-actions flex min-w-0 items-center gap-1.5">
          <div className="glass-control-group flex items-center gap-0.5">
            <IconButton label="接口管理" onClick={() => setShowProviderSettings(true)}><Settings size={16} /></IconButton>
            <IconButton label="PNG Info" onClick={() => setShowPngInfo(true)}><FileSearch size={16} /></IconButton>
            <IconButton label="提示词库" onClick={() => setShowPromptCollection(value => !value)} className={showPromptCollection ? 'text-nexus-green' : ''}><Library size={16} /></IconButton>
            <IconButton label="退出登录" onClick={handleLogout} className="hover:text-nexus-red"><LogOut size={16} /></IconButton>
          </div>
        </div>
      </header>

      {/* 主工作区 */}
      <main className="workspace-main flex-grow relative" style={appMode === 'canvas' ? { display: 'flex', backgroundImage: 'none' } : { '--prompt-user-width': `${panelWidth}px` }}>

      {appMode === 'canvas' ? (
        <React.Suspense fallback={<div className="p-6 text-nexus-text">正在载入创作画布…</div>}>
          <CanvasStudio beforeLeaveRef={canvasBeforeLeave} notify={notify} providerRevision={providerRevision} />
        </React.Suspense>
      ) : appMode === 'image' ? (<>
        
        {/* 左侧：提示词输入 */}
        <section className="prompt-pane relative z-20">

          {/* 编辑器主体 */}
          <div className="flex-grow flex flex-col min-h-0 relative z-10">
            <TextToImage 
              prompt={activeImgTab.prompt} setPrompt={v => updateImgTab(activeImgTab.id, { prompt: v })}
              mentionItems={promptMentionItems}
              isGenerating={false}
              onSavePrompt={handleSavePrompt}
            />
          </div>

          {/* 执行按钮区 */}
          <div className="prompt-actions p-3 border-t border-nexus-border z-10">
            <button
              onClick={handleGenerate}
              className="btn-base btn-primary w-full min-h-11"
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
            mode="image"
            refreshToken={taskGalleryRevision}
            onReuseTask={handleLoadTask}
          />
        </section>

        {/* 右侧：图片参数 */}
        <aside className="inspector-pane custom-scrollbar">
          <div className="inspector-header">
            <div className="flex items-center gap-2 text-sm font-semibold text-nexus-text-light"><SlidersHorizontal size={15} className="text-nexus-blue" />图片参数</div>
            <span className="font-mono text-[11px] text-nexus-muted">{imageSizeSummary}</span>
          </div>

            <div className="inspector-section">
              <div className="inspector-title">
                <Cpu size={14} className="text-nexus-green" /> 生成设置
              </div>
              <div className="inspector-fields">
                <div className="inspector-field-row">
                  <span className="field-label">端点</span>
                  <select
                    aria-label="图片端点"
                    value={apiProvider}
                    disabled={!providerInfoReady}
                    onChange={event => handleImageProviderChange(event.target.value)}
                    className="field-select min-w-0"
                  >
                    <option value="ark" disabled={imageProviders.ark?.available === false} className="bg-nexus-bg">
                      BytePlus Ark{imageProviders.ark?.available === false ? ' · 未配置' : ''}
                    </option>
                    <option value="cupsy" disabled={imageProviders.cupsy?.available === false} className="bg-nexus-bg">
                      Cupsy{imageProviders.cupsy?.available === false ? ' · 未配置' : ''}
                    </option>
                  </select>
                </div>
                <div className="inspector-field-row">
                  <span className="field-label">模型</span>
                  <select
                    aria-label="图片模型"
                    value={imageModelValue}
                    disabled
                    onChange={() => {}}
                    className="field-select min-w-0"
                  >
                    {isSeedream ? (
                      <option value={imageModelValue} className="bg-nexus-bg">{imageCapabilityModel==='dola-seedream-5-5-261028'?'Seedream 5.5':'Seedream 5.0 Pro'}</option>
                    ) : (
                      <option value="">—</option>
                    )}
                  </select>
                </div>
              </div>
            </div>
            
            <div className="inspector-section">
              <div className="inspector-title"><Settings size={14}/> 输出设置</div>
              <ImageOutputControls model={imageCapabilityModel} provider={apiProvider} params={imageParams} onChange={changeImageParams}
                references={imageReferences} dimensions={imageDimensions} issues={imageIssues}>
              </ImageOutputControls>
            </div>

            {/* SOURCE NODE */}
            <div className="inspector-section">
              <div className="inspector-title">
                <HardDrive size={14} className="text-nexus-violet" /> 参考素材
              </div>
              <div className="flex-grow min-h-0">
                 <button className="cupsy-library-button" onClick={openToolLibrary}><Library size={13}/>素材库</button>
                 <ImageToImage
                   uploadedImages={activeImgTab.uploadedImages}
                   createPreviewUrl={createReferencePreview}
                   onPreview={setReferenceMedia}
                   setUploadedImages={value => updateImgTab(activeImgTab.id, tab => ({
                     uploadedImages: typeof value === 'function'
                       ? value(Array.isArray(tab.uploadedImages) ? tab.uploadedImages : [])
                       : value,
                   }))}
                   maxImages={isSeedream ? 10 : 14}
                 />
              </div>
            </div>

        </aside>

      </>) : appMode === 'layer' ? (
        <React.Suspense fallback={<div className="flex h-full items-center justify-center text-xs text-nexus-muted">正在加载 Layer Studio...</div>}>
          <LayerStudio notify={notify} />
        </React.Suspense>
      ) : appMode === 'video' ? (
        /* ============ VIDEO MODE ============ */
        <>
          {/* 左侧：视频提示词 */}
          <section className="prompt-pane relative z-20">
            <div className="flex-grow flex flex-col min-h-0 relative z-10">
              <div className="flex-grow flex flex-col min-h-0 relative bg-transparent">
                <div className="flex h-10 shrink-0 items-center justify-between border-b border-nexus-border px-4">
                  <span className="text-xs font-medium text-nexus-text-light">视频提示词</span>
                  <span className="font-mono text-[11px] text-nexus-muted">{activeTab.prompt.length}</span>
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
              </div>
            </div>
            <div className="prompt-actions p-3 border-t border-nexus-border z-10">
              <button
                onClick={handleVideoGenerate}
                className="btn-base btn-primary w-full min-h-11"
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
              mode="video"
              refreshToken={taskGalleryRevision}
              onReuseTask={handleLoadTask}
            />
          </section>

          {/* 右侧：视频参数 */}
          <aside className="inspector-pane custom-scrollbar">
            <div className="inspector-header">
              <div className="flex items-center gap-2 text-sm font-semibold text-nexus-text-light"><SlidersHorizontal size={15} className="text-nexus-blue" />视频参数</div>
              <span className="font-mono text-[11px] text-nexus-muted">{activeTab.resolution} · {effectiveVideoDuration === -1 ? 'Auto' : `${effectiveVideoDuration}s`}</span>
            </div>

              {/* 生成模式 */}
              <div className="inspector-section">
                <div className="inspector-title">
                  <Grid3X3 size={14} className="text-nexus-blue" /> 生成设置
                </div>
                <div className="inspector-fields flex-grow">
                  <div className="inspector-field-row">
                    <span className="field-label">端点</span>
                    <select
                      aria-label="视频端点"
                      value={activeVideoProvider}
                      onChange={event => handleVideoProviderChange(event.target.value)}
                      className="field-select min-w-0"
                    >
                      <option value="ark" className="bg-nexus-bg">BytePlus Ark</option>
                      <option value="cupsy" disabled={!videoProviders.cupsy?.available} className="bg-nexus-bg">
                        Cupsy{videoProviders.cupsy?.available ? '' : ' · 未配置'}
                      </option>
                    </select>
                  </div>
                  <div className="inspector-field-row">
                    <span className="field-label">模型</span>
                    <select
                      aria-label="视频模型"
                      value={effectiveVideoModel}
                      title={effectiveVideoModel === SEEDANCE_25_MODERATED
                        ? 'Seedance 2.5 Enhanced Moderation'
                        : effectiveVideoModel === SEEDANCE_25 ? 'Seedance 2.5' : 'Seedance 2.0'}
                      onChange={e => handleVideoModelChange(e.target.value)}
                      className="field-select min-w-0"
                    >
                      {activeVideoProvider === 'ark' ? (<>
                        <option value={SEEDANCE_20} className="bg-nexus-bg">Seedance 2.0</option>
                        <option value={SEEDANCE_25} className="bg-nexus-bg">Seedance 2.5</option>
                      </>) : (<>
                        <option value={SEEDANCE_25} className="bg-nexus-bg">Seedance 2.5</option>
                        <option value={SEEDANCE_25_MODERATED} className="bg-nexus-bg">2.5 · 加强审核</option>
                      </>)}
                    </select>
                  </div>
                  <div className="inspector-field-row">
                    <span className="field-label">画幅</span>
                    <select
                      aria-label="视频画幅"
                      value={effectiveVideoRatio}
                      disabled={videoRatioLocked}
                      title={videoRatioLocked ? 'Seedance 2.5 首尾帧模式自动保持首帧比例' : '视频画幅'}
                      onChange={e => updateTab(activeTab.id, { ratio: e.target.value })}
                      className="field-select font-mono"
                    >
                      {VIDEO_RATIOS.map(r => (
                        <option key={r} value={r} className="bg-nexus-bg">{r}</option>
                      ))}
                    </select>
                  </div>
                  <div className="inspector-field-row">
                    <span className="field-label">模式</span>
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
                      className="field-select"
                    >
                      <option value="keyframe" className="bg-nexus-bg">首尾帧</option>
                      <option value="reference" className="bg-nexus-bg">全能参考</option>
                    </select>
                  </div>
                </div>
              </div>

              {/* ENGINE PARAMS */}
              <div className="inspector-section">
                <div className="inspector-title">
                  <Settings size={14} className="text-nexus-green" /> 输出参数
                </div>
                <div className="inspector-fields flex-grow">
                  <div className="inspector-field-row">
                    <span className="field-label">分辨率</span>
                    <select aria-label="视频分辨率" value={activeTab.resolution} onChange={e => updateTab(activeTab.id, { resolution: e.target.value })}
                      className="field-select font-mono">
                      {videoCapabilities.resolutions.map(resolution => (
                        <option key={resolution} value={resolution} className="bg-nexus-bg">{resolution}</option>
                      ))}
                    </select>
                  </div>
                  <div className="inspector-field-row">
                    <span className="field-label">时长</span>
                    <select
                      aria-label="视频时长"
                      value={effectiveVideoDuration}
                      title={isSeedance25 && activeTab.mode === 'reference' && hasReadyReferenceVideo
                        ? '参考生视频可指定 4–30 秒；视频编辑必须选择 Auto'
                        : '视频时长'}
                      onChange={e => updateTab(activeTab.id, { duration: Number(e.target.value) })}
                      className="field-select font-mono"
                    >
                      {videoDurationOptions.map(d => (
                        <option key={d} value={d} className="bg-nexus-bg">{d}s</option>
                      ))}
                      <option value={VIDEO_AUTO_DURATION} className="bg-nexus-bg">
                        {activeVideoProvider === 'cupsy'
                          ? 'Auto'
                          : isSeedance25 && activeTab.mode === 'reference' && hasReadyReferenceVideo
                            ? 'Auto · 编辑跟随输入'
                            : 'Auto'}
                      </option>
                    </select>
                  </div>
                  {!isSeedance25 && (
                    <div className="inspector-field-row">
                      <span className="field-label" title={videoFastAvailable ? '' : '需要配置 Ark Fast endpoint ID'}>
                        快速模式{!videoFastAvailable && <span className="ml-1 text-[9px] text-nexus-muted">未配置</span>}
                      </span>
                      <ToggleSwitch label="快速模式" checked={activeTab.fast} disabled={!videoFastAvailable} onChange={fast => updateTab(activeTab.id, { fast })} />
                    </div>
                  )}
                  {isSeedance25 && activeVideoProvider === 'ark' && (
                    <div className="inspector-field-row">
                      <span className="field-label">格式</span>
                      <select
                        aria-label="视频输出格式"
                        value={activeTab.outputFormat || 'mp4'}
                        onChange={e => updateTab(activeTab.id, { outputFormat: e.target.value })}
                        className="field-select font-mono"
                      >
                        <option value="mp4" className="bg-nexus-bg">MP4</option>
                        <option value="mov" className="bg-nexus-bg">MOV</option>
                      </select>
                    </div>
                  )}
                  <div className="inspector-field-row">
                    <span className="field-label">生成音频</span>
                    <ToggleSwitch label="生成音频" checked={activeTab.audio} onChange={audio => updateTab(activeTab.id, { audio })} />
                  </div>
                  {activeVideoProvider === 'ark' && <div className="inspector-field-row">
                    <span className="field-label">返回尾帧</span>
                    <ToggleSwitch label="返回尾帧" checked={activeTab.returnLastFrame} onChange={returnLastFrame => updateTab(activeTab.id, { returnLastFrame })} />
                  </div>}
                </div>
              </div>

              {/* KEYFRAMES / REFERENCE */}
              <div className="inspector-section">
                <div className="inspector-title justify-between">
                  <span className="flex items-center gap-2"><Film size={14} className="text-nexus-violet" /> {activeTab.mode === 'keyframe' ? '关键帧' : '参考素材'}</span>
                  {(
                    <button type="button" className="cupsy-library-button" onClick={openToolLibrary}>
                      <Library size={13} /> 素材库
                    </button>
                  )}
                </div>

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
                          <img src={activeTab.firstFrame.preview} className="w-full h-full object-cover" alt="首帧" />
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
                          <img src={activeTab.lastFrame.preview} className="w-full h-full object-cover" alt="尾帧" />
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
                            <img src={img.preview} className="w-full h-full object-cover" alt={`视频参考图片 ${i + 1}`} />
                            <Maximize2 size={10} className="absolute bottom-1 left-1 text-white opacity-0 drop-shadow transition-opacity group-hover:opacity-100" />
                          </button>
                          <button type="button" aria-label={`删除参考图片 ${i + 1}`} title="删除" onClick={() => updateTab(activeTab.id, { refImages: activeTab.refImages.filter((_, j) => j !== i) })}
                            className="absolute right-0.5 top-0.5 z-10 rounded bg-black/75 p-0.5 text-white transition-colors hover:bg-nexus-red">
                            <X size={8} />
                          </button>
                        </SortableReferenceItem>
                      ))}
                      {activeTab.refImages.length < videoCapabilities.maxRefImages && (
                        <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-[10px] font-mono">
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
                            <span className="absolute bottom-0.5 w-full truncate text-center font-mono text-[8px] text-nexus-text">{vid.name?.slice(0,6)}</span>
                          </button>
                          <button type="button" aria-label={`删除参考视频 ${i + 1}`} title="删除" onClick={() => {
                              if (vid.url && !vid.cupsyAssetId) {
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
                        <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-[10px] font-mono">
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
                            <span className="absolute bottom-0.5 w-full truncate text-center font-mono text-[8px] text-nexus-text">{(aud.file?.name || aud.name || 'audio').slice(0,6)}</span>
                          </button>
                          <button type="button" aria-label={`删除参考音频 ${i + 1}`} title="删除" onClick={() => updateTab(activeTab.id, { refAudios: activeTab.refAudios.filter((_, j) => j !== i) })}
                            className="absolute right-0.5 top-0.5 z-10 rounded bg-black/75 p-0.5 text-white transition-colors hover:bg-nexus-red">
                            <X size={8} />
                          </button>
                        </SortableReferenceItem>
                      ))}
                      {activeTab.refAudios.length < videoCapabilities.maxRefAudios && (
                        <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-[10px] font-mono">
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
              </div>

              {/* PRICE ESTIMATE */}
              <div className="inspector-section">
                <div className="inspector-title">
                  <Database size={14} className="text-nexus-amber" /> 费用估算 (USD)
                </div>
                <div className="flex flex-col justify-between flex-grow gap-2">
                  {(() => {
                    const estimate = estimateBytePlusVideoCost({
                      model: effectiveVideoModel,
                      provider: activeVideoProvider,
                      resolution: activeTab.resolution,
                      ratio: effectiveVideoRatio,
                      duration: effectiveVideoDuration,
                      fast: activeTab.fast,
                      referenceVideos: activeTab.refVideos,
                    })
                    const outputDuration = estimate.minimumOutputSeconds === estimate.maximumOutputSeconds
                      ? `${estimate.minimumOutputSeconds}s`
                      : `${estimate.minimumOutputSeconds}~${estimate.maximumOutputSeconds}s`
                    const inputVideo = estimate.hasVideo
                      ? `参考视频 ${estimate.inputVideoSeconds.toFixed(1).replace(/\.0$/, '')}s${estimate.inputDurationAssumed ? '（含 5s 默认值）' : ''}`
                      : '无参考视频'
                    return (<>
                      <div data-testid="video-cost-estimate" className="text-2xl font-mono text-nexus-green">{formatUsdEstimate(estimate)}</div>
                      <div className="text-xs font-mono text-nexus-text leading-5 opacity-80">
                        <div>{activeVideoProvider === 'cupsy'
                          ? effectiveVideoModel === SEEDANCE_25_MODERATED ? 'Seedance 2.5 · Cupsy 加强审核' : 'Seedance 2.5 · Cupsy 费率'
                          : isSeedance25 ? `Seedance 2.5 · BytePlus${estimate.promotionActive ? ' 限时按 72% 计费' : ''}`
                            : activeTab.fast ? 'Seedance 2.0 Fast' : 'Seedance 2.0'}</div>
                        <div>{estimate.width}×{estimate.height} · {outputDuration} · {estimate.fps}fps</div>
                        <div>{inputVideo}</div>
                        <div className="mt-1 opacity-50">≈{formatWanTokens(estimate.minimumTokens, estimate.maximumTokens)}{estimate.ratioAssumed ? ' · Adaptive 按 16:9' : ''}</div>
                      </div>
                    </>)
                  })()}
                </div>
              </div>

          </aside>
        </>
      ) : (
        /* ============ AUDIO MODE ============ */
        <>
          <section className="prompt-pane relative z-20">
            <div className="flex min-h-0 flex-grow flex-col">
              <div className="flex h-10 shrink-0 items-center justify-between border-b border-nexus-border px-4">
                <span className="text-xs font-medium text-nexus-text-light">音频场景提示词</span>
                <span className={`font-mono text-[11px] ${audioForm.prompt.length > 3000 ? 'text-nexus-red' : 'text-nexus-muted'}`}>{audioForm.prompt.length} / 3000</span>
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
            </div>
            <div className="prompt-actions z-10 border-t border-nexus-border p-3">
              <button type="button" onClick={handleAudioGenerate} className="btn-base btn-primary min-h-11 w-full">
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
            <TaskGallery mode="audio" refreshToken={taskGalleryRevision} onReuseTask={handleLoadTask} />
          </section>

          <aside className="inspector-pane custom-scrollbar">
            <div className="inspector-header">
              <div className="flex items-center gap-2 text-sm font-semibold text-nexus-text-light"><SlidersHorizontal size={15} className="text-nexus-cyan" />音频参数</div>
              <span className="font-mono text-[11px] text-nexus-muted">{audioForm.outputFormat.toUpperCase()} · {(audioForm.sampleRate / 1000).toFixed(audioForm.sampleRate % 1000 ? 1 : 0)} kHz</span>
            </div>

            <div className="inspector-section">
              <div className="inspector-title"><Cpu size={14} className="text-nexus-cyan" /> 生成设置</div>
              <div className="inspector-fields">
                <div className="inspector-field-row">
                  <span className="field-label">端点</span>
                  <select aria-label="音频端点" value="cupsy" disabled className="field-select"><option value="cupsy" className="bg-nexus-bg">Cupsy{audioProvider.available ? '' : ' · 未配置'}</option></select>
                </div>
                <div className="inspector-field-row">
                  <span className="field-label">模型</span>
                  <select aria-label="音频模型" value={CUPSY_AUDIO_MODEL} disabled className="field-select"><option value={CUPSY_AUDIO_MODEL} className="bg-nexus-bg">Seed Audio 1.0</option></select>
                </div>
                <div className="inspector-field-row">
                  <span className="field-label">格式</span>
                  <select aria-label="音频输出格式" value={audioForm.outputFormat} onChange={event => updateAudioForm({ outputFormat: event.target.value })} className="field-select font-mono">
                    <option value="mp3" className="bg-nexus-bg">MP3</option>
                    <option value="wav" className="bg-nexus-bg">WAV</option>
                    <option value="ogg_opus" className="bg-nexus-bg">OGG Opus</option>
                  </select>
                </div>
                <div className="inspector-field-row">
                  <span className="field-label">采样率</span>
                  <select aria-label="音频采样率" value={audioForm.sampleRate} onChange={event => updateAudioForm({ sampleRate: Number(event.target.value) })} className="field-select font-mono">
                    {AUDIO_SAMPLE_RATES.map(rate => <option key={rate} value={rate} className="bg-nexus-bg">{rate === 44100 ? '44.1' : rate / 1000} kHz</option>)}
                  </select>
                </div>
                <div className="inspector-field-row"><span className="field-label">生成字幕</span><ToggleSwitch label="生成字幕" checked={audioForm.enableSubtitle} onChange={enableSubtitle => updateAudioForm({ enableSubtitle })} /></div>
                <div className="inspector-field-row"><span className="field-label">可听水印</span><ToggleSwitch label="可听水印" checked={audioForm.watermark} onChange={watermark => updateAudioForm({ watermark })} /></div>
              </div>
            </div>

            <div className="inspector-section">
              <div className="inspector-title justify-between">
                <span className="flex items-center gap-2"><HardDrive size={14} className="text-nexus-violet" /> 参考素材</span>
                <button type="button" className="cupsy-library-button" onClick={openToolLibrary}><Library size={13} /> 素材库</button>
              </div>
              <SegmentedControl
                label="音频参考模式"
                value={audioForm.referenceMode}
                onChange={referenceMode => updateAudioForm({ referenceMode, references: [], ...(referenceMode !== 'audio' ? { speaker: '' } : {}) })}
                options={[{ value: 'none', label: '纯文本' }, { value: 'audio', label: '音频' }, { value: 'image', label: '图片' }]}
              />
              {audioForm.referenceMode === 'audio' && (
                <div className="inspector-field-row mt-3">
                  <span className="field-label">预设声线</span>
                  <select aria-label="音频预设声线" value={audioForm.speaker} onChange={event => {
                    const speaker = event.target.value
                    const maxAssets = speaker ? 2 : 3
                    updateAudioForm(form => ({ speaker, references: form.references.slice(0, maxAssets) }))
                  }} className="field-select">
                    {AUDIO_SPEAKERS.map(item => <option key={item.value || 'auto'} value={item.value} className="bg-nexus-bg">{item.label}</option>)}
                  </select>
                </div>
              )}
              {audioForm.referenceMode !== 'none' && (
                <div
                  className="audio-reference-drop-zone mt-3"
                  data-dragging="false"
                  {...videoDropZoneHandlers(addAudioReferences)}
                >
                  <div className="grid grid-cols-3 gap-2">
                    {audioForm.references.map((reference, index) => (
                      <div key={`${reference.cupsyAssetId}-${index}`} className="audio-reference-card group relative">
                        <button type="button" className="absolute inset-0 flex flex-col items-center justify-center gap-1 p-2" onClick={() => setReferenceMedia({ type: reference.kind, src: reference.preview, name: reference.name })}>
                          {reference.kind === 'image' ? <img src={reference.preview} alt={reference.name} className="size-full object-cover" /> : <AudioLines size={22} className="text-nexus-cyan" />}
                          {reference.kind === 'audio' && <span className="w-full truncate text-center text-[9px] text-nexus-muted">[Audio{index + (audioForm.speaker ? 2 : 1)}]</span>}
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
                  <div className="mt-2 font-mono text-[9px] text-nexus-muted">
                    {audioForm.referenceMode === 'audio' ? '按顺序对应 [Audio1]–[Audio3]' : '图片用于引导完整音频场景'}
                  </div>
                </div>
              )}
            </div>
          </aside>
        </>
      )}

      {/* 右侧抽屉：提示词库 */}
      <AnimatePresence>
        {showPromptCollection && (
          <motion.aside
            initial={{ x: '100%', opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: '100%', opacity: 0 }}
            transition={{ type: 'spring', damping: 28, stiffness: 260 }}
            className="drawer-panel liquid-glass-strong absolute bottom-0 right-0 top-0 z-40 flex flex-col"
          >
            <div className="glass-drawer-header flex h-12 shrink-0 items-center justify-between px-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-nexus-text-light">
                <Library size={15} className="text-nexus-violet" /> 提示词库
              </div>
              <IconButton label="关闭提示词库" onClick={() => setShowPromptCollection(false)}><X size={16} /></IconButton>
            </div>
            <div className="relative flex-grow overflow-hidden">
              <PromptCollection onSelectPrompt={handleSelectSavedPrompt} />
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      </main>

      <PngInfoModal
        open={showPngInfo}
        onClose={() => setShowPngInfo(false)}
        onApply={handleApplyPngInfo}
      />
      <ReferenceMediaModal media={referenceMedia} onClose={() => setReferenceMedia(null)} />
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
                  <span className="truncate font-mono text-[11px] text-nexus-muted">{appMode === 'video' ? 'video_prompt' : appMode === 'audio' ? 'audio_prompt' : 'image_prompt'}</span>
                </div>
                <div className="flex items-center gap-1">
                  <IconButton label="提示词库" onClick={() => setShowEditorVault(!showEditorVault)} className={showEditorVault ? 'border-nexus-violet/35 bg-nexus-violet/10 text-nexus-violet' : ''}><Library size={16} /></IconButton>
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
        <ProviderSettings onClose={() => setShowProviderSettings(false)} onSaved={() => setProviderRevision(value => value + 1)} />
      </React.Suspense>}
      <AnimatePresence>
        {notification && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            role={notification.tone === 'error' ? 'alert' : 'status'}
            aria-live="polite"
            className={`fixed ${appMode === 'layer' ? 'bottom-24 right-[308px]' : 'bottom-4 right-4'} z-[1200] flex max-w-[calc(100vw-32px)] items-center gap-2 rounded-md border px-3 py-2.5 text-sm shadow-2xl ${notification.tone === 'error' ? 'border-nexus-red/35 bg-[#211417] text-nexus-red' : 'border-nexus-green/35 bg-[#102019] text-nexus-text-light'}`}
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
