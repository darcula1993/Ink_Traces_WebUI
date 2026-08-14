import React, { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import TextToImage from './components/TextToImage'
import ImageToImage from './components/ImageToImage'
import PromptCollection from './components/PromptCollection'
import TaskGallery from './components/TaskGallery'
import PngInfoModal from './components/PngInfoModal'
import ReferenceMediaModal from './components/ReferenceMediaModal'
import CupsyAssetManager from './components/CupsyAssetManager'
import SortableReferenceItem, { moveArrayItem } from './components/SortableReferenceItem'
import CodeRainCanvas from './components/CodeRainCanvas'
import GlassBackdrop from './components/GlassBackdrop'
import IconButton from './components/ui/IconButton'
import SegmentedControl from './components/ui/SegmentedControl'
import ToggleSwitch from './components/ui/ToggleSwitch'
import { motion, AnimatePresence } from 'framer-motion'
import ReactDOM from 'react-dom'
import { Play, Settings, Cpu, HardDrive, Grid3X3, Grid2X2Check, Database, X, Maximize2, Save, ImageDown, Film, LogOut, Check, Image as ImageIcon, Library, Plus, SlidersHorizontal, Braces, User, LockKeyhole, Lock, LockOpen, ArrowLeftRight, AudioLines, CircleAlert, FileSearch } from 'lucide-react'
import { estimateBytePlusVideoCost, formatCnyEstimate, formatWanTokens } from './lib/byteplusPricing'
import { persistWorkspaceBlob, useWorkspaceState } from './lib/useWorkspaceState'

axios.defaults.withCredentials = true

const SEEDREAM_MIN_PIXELS = 1280 * 720
const SEEDREAM_MAX_PIXELS = 4_624_220
const SEEDANCE_20 = 'seedance-2.0'
const SEEDANCE_25 = 'seedance-2.5'
const VIDEO_REFERENCE_EXTENSIONS = new Set(['mp4', 'mov'])
const AUDIO_REFERENCE_EXTENSIONS = new Set(['wav', 'mp3'])
const VIDEO_MODEL_CAPABILITIES = {
  [SEEDANCE_20]: {
    label: 'Dreamina Seedance 2.0',
    resolutions: ['480p', '720p', '1080p'],
    minDuration: 4,
    maxDuration: 15,
    maxRefImages: 9,
    maxRefVideos: 3,
    maxRefAudios: 3,
  },
  [SEEDANCE_25]: {
    label: 'Dreamina Seedance 2.5',
    resolutions: ['480p', '720p'],
    minDuration: 4,
    maxDuration: 30,
    maxRefImages: 30,
    maxRefVideos: 10,
    maxRefAudios: 10,
  },
}
const SEEDREAM_SIZE_PRESETS = {
  '1K': {
    '1:1': [1024, 1024], '4:3': [1152, 864], '3:4': [864, 1152],
    '16:9': [1424, 800], '9:16': [800, 1424], '3:2': [1248, 832],
    '2:3': [832, 1248], '21:9': [1568, 672],
  },
  '2K': {
    '1:1': [2048, 2048], '4:3': [2368, 1776], '3:4': [1776, 2368],
    '16:9': [2816, 1584], '9:16': [1584, 2816], '3:2': [2496, 1664],
    '2:3': [1664, 2496], '21:9': [3136, 1344],
  },
}

function fileExtension(file) {
  return String(file?.name || '').split('.').pop()?.toLowerCase() || ''
}

function isImageFile(file) {
  return Boolean(file && String(file.type || '').startsWith('image/'))
}

function isVideoFile(file) {
  return Boolean(file && (
    ['video/mp4', 'video/quicktime'].includes(String(file.type || '').toLowerCase()) ||
    VIDEO_REFERENCE_EXTENSIONS.has(fileExtension(file))
  ))
}

function isAudioFile(file) {
  return Boolean(file && (
    ['audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/mp3'].includes(String(file.type || '').toLowerCase()) ||
    AUDIO_REFERENCE_EXTENSIONS.has(fileExtension(file))
  ))
}

function readFileDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = event => resolve(event.target.result)
    reader.onerror = () => reject(reader.error || new Error('文件读取失败'))
    reader.readAsDataURL(file)
  })
}

function hasExternalFiles(event) {
  return Array.from(event.dataTransfer?.types || []).includes('Files')
}

function videoDropZoneHandlers(onFiles) {
  return {
    onDragEnter: event => {
      if (!hasExternalFiles(event)) return
      event.preventDefault()
      event.stopPropagation()
      event.currentTarget.dataset.dragging = 'true'
    },
    onDragOver: event => {
      if (!hasExternalFiles(event)) return
      event.preventDefault()
      event.stopPropagation()
      event.dataTransfer.dropEffect = 'copy'
    },
    onDragLeave: event => {
      if (!hasExternalFiles(event) || event.currentTarget.contains(event.relatedTarget)) return
      event.preventDefault()
      event.stopPropagation()
      event.currentTarget.dataset.dragging = 'false'
    },
    onDrop: event => {
      if (!hasExternalFiles(event)) return
      event.preventDefault()
      event.stopPropagation()
      event.currentTarget.dataset.dragging = 'false'
      onFiles(Array.from(event.dataTransfer?.files || []))
    },
  }
}

function alignSeedreamDimension(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return value
  return Math.max(16, Math.round(numeric / 16) * 16)
}

function formatDimensionRatio(widthValue, heightValue) {
  const width = Number(widthValue)
  const height = Number(heightValue)
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return '--'
  const ratio = width / height
  return ratio >= 1 ? `${ratio.toFixed(2).replace(/\.00$/, '')}:1` : `1:${(1 / ratio).toFixed(2).replace(/\.00$/, '')}`
}

function validateSeedreamCustomSize(widthValue, heightValue) {
  const width = Number(widthValue)
  const height = Number(heightValue)
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) {
    return '宽度和高度必须是正整数'
  }
  if (width % 16 !== 0 || height % 16 !== 0) return '宽度和高度必须是 16 的倍数'
  const pixels = width * height
  if (pixels < SEEDREAM_MIN_PIXELS || pixels > SEEDREAM_MAX_PIXELS) {
    return '总像素必须在 921600 到 4624220 之间'
  }
  const ratio = width / height
  if (ratio < 1 / 16 || ratio > 16) return '宽高比必须在 1:16 到 16:1 之间'
  return ''
}

function fitSeedreamSizeToReference(widthValue, heightValue) {
  const sourceWidth = Number(widthValue)
  const sourceHeight = Number(heightValue)
  if (!Number.isFinite(sourceWidth) || !Number.isFinite(sourceHeight) || sourceWidth <= 0 || sourceHeight <= 0) {
    return { error: '无法读取参考素材尺寸' }
  }
  const sourceRatio = sourceWidth / sourceHeight
  if (sourceRatio < 1 / 16 || sourceRatio > 16) {
    return { error: '参考素材宽高比超出 1:16 到 16:1 的范围' }
  }

  const sourceArea = sourceWidth * sourceHeight
  const targetArea = Math.min(SEEDREAM_MAX_PIXELS, Math.max(SEEDREAM_MIN_PIXELS, sourceArea))
  const targetScale = Math.sqrt(targetArea / sourceArea)
  const targetWidth = sourceWidth * targetScale
  const maxDimension = Math.ceil(Math.sqrt(SEEDREAM_MAX_PIXELS * 16) / 16) * 16
  let best = null

  for (let width = 16; width <= maxDimension; width += 16) {
    const idealHeight = width / sourceRatio
    const heightCandidates = new Set([
      Math.floor(idealHeight / 16) * 16,
      Math.round(idealHeight / 16) * 16,
      Math.ceil(idealHeight / 16) * 16,
    ])
    for (const height of heightCandidates) {
      if (height < 16 || validateSeedreamCustomSize(width, height)) continue
      const area = width * height
      const ratioError = Math.abs(Math.log((width / height) / sourceRatio))
      const areaError = Math.abs(Math.log(area / targetArea))
      const scaleError = Math.abs(Math.log(width / targetWidth))
      const score = ratioError * 8 + areaError + scaleError * 0.02
      if (!best || score < best.score) best = { width, height, score }
    }
  }

  if (!best) return { error: '无法将参考素材适配到有效的输出尺寸' }
  return {
    width: best.width,
    height: best.height,
    adjusted: best.width !== sourceWidth || best.height !== sourceHeight,
  }
}

function makeImgTab(id) {
  return {
    id, prompt: '', aspectRatio: '1:1', resolution: '1K', useSearch: false, thinkLevel: 'minimal',
    customWidth: 1024, customHeight: 1024, customAspectLocked: false, customAspectRatio: 1,
    chatMode: false, sessionId: null, uploadedImages: [], outputFormat: 'png', watermark: false,
    loading: false, taskId: null, dbTaskId: null, taskStatus: null, generatedImages: [], thinkingText: '', error: null, errorType: null, errorDetails: null,
  }
}

function makeVideoTab(id) {
  return {
    id, prompt: '', model: SEEDANCE_20, ratio: 'adaptive', duration: 5, resolution: '720p', outputFormat: 'mp4',
    fast: false, audio: true, returnLastFrame: false, mode: 'keyframe',
    firstFrame: null, lastFrame: null, refImages: [], refVideos: [], refAudios: [],
    loading: false, videoUrl: null, lastFrameUrl: null, progress: 0, eta: 0, error: null,
    taskId: null, dbTaskId: null, taskProvider: null, taskStatus: null,
  }
}

function selectPersistedImageTabs(tabs) {
  return (tabs || []).map(({
    loading, taskStatus, taskId, dbTaskId, generatedImages, thinkingText,
    error, errorType, errorDetails, ...tab
  }) => tab)
}

function hydrateImageTabs(savedTabs, _currentTabs = []) {
  const sourceTabs = savedTabs?.length ? savedTabs : [makeImgTab(1)]
  return sourceTabs.map(saved => {
    return {
      ...makeImgTab(saved.id),
      ...saved,
      loading: false,
      taskId: null,
      dbTaskId: null,
      taskStatus: null,
      generatedImages: [],
      thinkingText: '',
      error: null,
      errorType: null,
      errorDetails: null,
    }
  })
}

function selectPersistedVideoTabs(tabs) {
  return (tabs || []).map(({
    loading, taskStatus, taskId, dbTaskId, taskProvider, progress, eta,
    videoUrl, lastFrameUrl, error, ...tab
  }) => ({
    ...tab,
    refVideos: (tab.refVideos || [])
      .filter(video => video.url && !video.uploading)
      .map(({ progress: _progress, uploading: _uploading, ...video }) => video),
  }))
}

function hydrateVideoTabs(savedTabs, currentTabs = []) {
  const runtime = new Map((currentTabs || []).map(tab => [Number(tab.id), tab]))
  const sourceTabs = savedTabs?.length ? savedTabs : [makeVideoTab(1)]
  return sourceTabs.map(saved => {
    const current = runtime.get(Number(saved.id))
    const persistedVideos = saved.refVideos || []
    const persistedIds = new Set(persistedVideos.map(video => video.uid))
    const uploadingVideos = (current?.refVideos || []).filter(video => video.uploading && !persistedIds.has(video.uid))
    return {
      ...makeVideoTab(saved.id),
      ...saved,
      refVideos: [...persistedVideos, ...uploadingVideos],
      loading: false,
      taskId: null,
      dbTaskId: null,
      taskProvider: null,
      taskStatus: null,
      progress: 0,
      eta: 0,
      videoUrl: null,
      lastFrameUrl: null,
      error: null,
    }
  })
}

function mergeNormalizedImageTabs(currentTabs, normalizedTabs) {
  return hydrateImageTabs(normalizedTabs, currentTabs)
}

function mergeNormalizedVideoTabs(currentTabs, normalizedTabs) {
  return hydrateVideoTabs(normalizedTabs, currentTabs)
}

const IMAGE_WORKSPACE_OPTIONS = {
  selectPersisted: selectPersistedImageTabs,
  hydrate: hydrateImageTabs,
  mergeNormalized: mergeNormalizedImageTabs,
}

const VIDEO_WORKSPACE_OPTIONS = {
  selectPersisted: selectPersistedVideoTabs,
  hydrate: hydrateVideoTabs,
  mergeNormalized: mergeNormalizedVideoTabs,
}

function LoginPage({ onLogin }) {
  const [error, setError] = useState('')
  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    try {
      const res = await axios.post('/api/login', {
        username: e.target.username.value,
        password: e.target.password.value
      })
      if (res.data.success) onLogin()
    } catch (err) {
      setError(err.response?.data?.error || '登录失败')
    }
  }
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#050706] p-5">
      <CodeRainCanvas status="submitting" />
      <div className="absolute inset-0 bg-black/55" aria-hidden="true" />
      <form onSubmit={handleSubmit} className="liquid-login relative z-10 w-full max-w-[380px] p-6">
        <div className="mb-6 flex items-center gap-3">
          <div className="brand-mark flex size-10 items-center justify-center text-nexus-green">
            <Braces size={20} />
          </div>
          <div>
            <h1 className="text-base font-semibold text-nexus-text-light">Ink Traces</h1>
            <p className="mt-0.5 text-xs text-nexus-muted">Visual generation workspace</p>
          </div>
        </div>
        <label className="mb-1.5 block text-xs font-medium text-nexus-text" htmlFor="login-username">用户名</label>
        <div className="relative mb-4">
          <User size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-nexus-muted" />
          <input id="login-username" name="username" autoComplete="username" required autoFocus
            className="glass-input h-10 w-full pl-9 pr-3 text-sm text-nexus-text-light outline-none" />
        </div>
        <label className="mb-1.5 block text-xs font-medium text-nexus-text" htmlFor="login-password">密码</label>
        <div className="relative mb-4">
          <LockKeyhole size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-nexus-muted" />
          <input id="login-password" name="password" type="password" autoComplete="current-password" required
            className="glass-input h-10 w-full pl-9 pr-3 text-sm text-nexus-text-light outline-none" />
        </div>
        {error && <div role="alert" className="mb-3 rounded border border-nexus-red/25 bg-nexus-red/10 px-3 py-2 text-xs text-nexus-red">{error}</div>}
        <button type="submit" className="btn-base btn-primary w-full min-h-10">
          登录
        </button>
      </form>
    </div>
  )
}

function AuthGate() {
  const [authed, setAuthed] = useState(null)
  useEffect(() => {
    axios.get('/api/auth/check').then(() => setAuthed(true)).catch(() => setAuthed(false))
  }, [])
  if (authed === null) return <div className="min-h-screen bg-nexus-bg flex items-center justify-center"><div className="w-5 h-5 border-2 border-nexus-green border-t-transparent rounded-full animate-spin"></div></div>
  if (!authed) return <LoginPage onLogin={() => setAuthed(true)} />
  return <App onLogout={() => setAuthed(false)} />
}

function App({ onLogout }) {
  const handleLogout = async () => {
    await axios.post('/api/logout').catch(() => {})
    onLogout()
  }

  const [showPromptCollection, setShowPromptCollection] = useState(false)
  const [showPngInfo, setShowPngInfo] = useState(false)
  const [referenceMedia, setReferenceMedia] = useState(null)
  const [referenceSizeIndex, setReferenceSizeIndex] = useState('')
  const [showFullEditor, setShowFullEditor] = useState(false)
  const [showEditorVault, setShowEditorVault] = useState(false)
  const [showCupsyAssets, setShowCupsyAssets] = useState(false)
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
  const [currentModel, setCurrentModel] = useState('gemini-3.1-flash-image-preview')
  const [availableModels, setAvailableModels] = useState([])

  // 图片生成表单。沿用旧 workspace key，在加载后收敛为单一表单。
  const [imgTabs, setImgTabs, imgWorkspace] = useWorkspaceState('img_tabs', [makeImgTab(1)], IMAGE_WORKSPACE_OPTIONS)
  const [activeImgTabId, setActiveImgTabId] = useWorkspaceState('img_activeTab', 1)

  const activeImgTab = imgTabs.find(t => t.id === activeImgTabId) || imgTabs[0] || makeImgTab(1)

  const updateImgTab = useCallback((id, updates) => {
    setImgTabs(prev => prev.map(t => {
      if (t.id !== id) return t
      const resolvedUpdates = typeof updates === 'function' ? updates(t) : updates
      return { ...t, ...resolvedUpdates }
    }))
  }, [setImgTabs])

  // 顶部模式切换：image / video
  const [appMode, setAppMode] = useWorkspaceState('appMode', 'image')

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

  const activeVideoProvider = activeTab.provider === 'cupsy' ? 'cupsy' : 'ark'
  const effectiveVideoModel = activeVideoProvider === 'cupsy' || activeTab.model === SEEDANCE_25 ? SEEDANCE_25 : SEEDANCE_20
  const isSeedance25 = effectiveVideoModel === SEEDANCE_25
  const videoCapabilities = VIDEO_MODEL_CAPABILITIES[effectiveVideoModel]
  const videoDurationOptions = Array.from(
    { length: videoCapabilities.maxDuration - videoCapabilities.minDuration + 1 },
    (_, index) => videoCapabilities.minDuration + index,
  )
  const hasReadyReferenceVideo = activeTab.refVideos.some(video => video.url && !video.uploading)
  const videoRatioLocked = isSeedance25
    && activeTab.mode === 'keyframe'
    && Boolean(activeTab.firstFrame || activeTab.lastFrame)
  const effectiveVideoRatio = videoRatioLocked ? 'adaptive' : activeTab.ratio
  const effectiveVideoDuration = activeTab.duration

  const handleVideoModelChange = useCallback((model) => {
    const nextModel = model === SEEDANCE_25 ? SEEDANCE_25 : SEEDANCE_20
    updateTab(activeTab.id, tab => {
      const capabilities = VIDEO_MODEL_CAPABILITIES[nextModel]
      const duration = nextModel === SEEDANCE_25
        ? -1
        : tab.duration !== -1 && tab.duration > capabilities.maxDuration
          ? capabilities.maxDuration
          : tab.duration
      const resolution = capabilities.resolutions.includes(tab.resolution) ? tab.resolution : '720p'
      const ratio = nextModel === SEEDANCE_25
        && tab.mode === 'keyframe'
        && (tab.firstFrame || tab.lastFrame)
        ? 'adaptive'
        : tab.ratio
      return {
        model: nextModel,
        duration,
        resolution,
        ratio,
        fast: nextModel === SEEDANCE_25 ? false : tab.fast,
        outputFormat: nextModel === SEEDANCE_25 && tab.outputFormat === 'mov' ? 'mov' : 'mp4',
      }
    })
  }, [activeTab.id, updateTab])

  const handleVideoProviderChange = useCallback((provider) => {
    updateTab(activeTab.id, tab => provider === 'cupsy' ? {
      provider: 'cupsy', model: SEEDANCE_25, duration: tab.duration === -1 ? 5 : tab.duration,
      resolution: ['480p', '720p'].includes(tab.resolution) ? tab.resolution : '720p',
      fast: false, outputFormat: 'mp4', returnLastFrame: false,
    } : { provider: 'ark' })
  }, [activeTab.id, updateTab])

  const moveVideoReference = useCallback((tabId, field, fromIndex, toIndex) => {
    setVideoTabs(prev => prev.map(tab => tab.id === tabId ? {
      ...tab,
      [field]: moveArrayItem(tab[field], fromIndex, toIndex),
    } : tab))
  }, [setVideoTabs])

  const useCupsyAsset = useCallback((asset, role) => {
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
  }, [activeTab.id, notify, updateTab])

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
        ...(tab.model === SEEDANCE_25 ? { ratio: 'adaptive' } : {}),
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
            ...(tab.model === SEEDANCE_25 ? { ratio: 'adaptive' } : {}),
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
          const model = tab.model === SEEDANCE_25 ? SEEDANCE_25 : SEEDANCE_20
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
    const model = tab.model === SEEDANCE_25 ? SEEDANCE_25 : SEEDANCE_20
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
      const model = tab.model === SEEDANCE_25 ? SEEDANCE_25 : SEEDANCE_20
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
  const standardAspectRatios = ['1:1', '1:4', '4:1', '1:8', '8:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9']
  const arkAspectRatios = ['auto', '1:1', '4:3', '3:4', '16:9', '9:16', '3:2', '2:3', '21:9', 'custom']
  const aspectRatios = isArk ? arkAspectRatios : standardAspectRatios
  const resolutions = isArk ? ['1K', '2K'] : ['0.5K', '1K', '2K', '4K']
  const isCustomSeedreamSize = isArk && activeImgTab.aspectRatio === 'custom'
  const customWidthNumber = Number(activeImgTab.customWidth)
  const customHeightNumber = Number(activeImgTab.customHeight)
  const customSizeValidation = validateSeedreamCustomSize(activeImgTab.customWidth, activeImgTab.customHeight)
  const customSizeError = isCustomSeedreamSize ? customSizeValidation : ''
  const canTransformCustomSize = isArk
    && Number.isFinite(customWidthNumber) && customWidthNumber > 0
    && Number.isFinite(customHeightNumber) && customHeightNumber > 0
  const referenceSizeOptions = (activeImgTab.uploadedImages || []).map((image, index) => ({
    index,
    name: image.name || image.file?.name || `参考素材 ${index + 1}`,
    width: Number(image.width),
    height: Number(image.height),
  })).filter(option => Number.isFinite(option.width) && option.width > 0 && Number.isFinite(option.height) && option.height > 0)
  const referenceSizeOptionsKey = referenceSizeOptions
    .map(option => `${option.index}:${option.width}x${option.height}`)
    .join('|')
  const selectedReferenceSize = referenceSizeOptions.find(option => String(option.index) === referenceSizeIndex) || null
  const presetDimensions = isArk
    ? SEEDREAM_SIZE_PRESETS[activeImgTab.resolution]?.[activeImgTab.aspectRatio]
    : null
  const presetWidth = presetDimensions?.[0]
  const presetHeight = presetDimensions?.[1]
  const imageSizeSummary = isCustomSeedreamSize
    ? `${activeImgTab.customWidth}×${activeImgTab.customHeight}`
    : `${activeImgTab.aspectRatio === 'auto' ? 'Auto' : activeImgTab.aspectRatio} · ${activeImgTab.resolution}`
  const customSizeStatus = !isArk
    ? '仅 Seedream 支持自定义尺寸'
    : customSizeError
      ? customSizeError
      : isCustomSeedreamSize
        ? `自定义 · ${(customWidthNumber * customHeightNumber).toLocaleString('zh-CN')} px · ${formatDimensionRatio(customWidthNumber, customHeightNumber)}`
        : activeImgTab.aspectRatio === 'auto'
          ? `Auto · ${activeImgTab.customWidth}×${activeImgTab.customHeight} 未启用`
          : `预设 · ${activeImgTab.customWidth}×${activeImgTab.customHeight}`

  useEffect(() => {
    if (!providerInfoReady || !isArk || !presetWidth || !presetHeight) return
    const ratio = presetWidth / presetHeight
    const dimensionsMatch = customWidthNumber === presetWidth && customHeightNumber === presetHeight
    const lockMatches = !activeImgTab.customAspectLocked
      || Math.abs(Number(activeImgTab.customAspectRatio) - ratio) < 0.000001
    if (dimensionsMatch && lockMatches) return
    updateImgTab(activeImgTab.id, {
      customWidth: presetWidth,
      customHeight: presetHeight,
      ...(activeImgTab.customAspectLocked ? { customAspectRatio: ratio } : {}),
    })
  }, [
    activeImgTab.customAspectLocked,
    activeImgTab.customAspectRatio,
    activeImgTab.id,
    customHeightNumber,
    customWidthNumber,
    isArk,
    presetHeight,
    presetWidth,
    providerInfoReady,
    updateImgTab,
  ])

  useEffect(() => {
    if (!referenceSizeIndex || referenceSizeOptions.some(option => String(option.index) === referenceSizeIndex)) return
    setReferenceSizeIndex('')
  }, [referenceSizeIndex, referenceSizeOptionsKey])

  const handleCustomDimensionChange = useCallback((dimension, rawValue) => {
    const value = rawValue === '' ? '' : Number(rawValue)
    const field = dimension === 'width' ? 'customWidth' : 'customHeight'
    const pairedField = dimension === 'width' ? 'customHeight' : 'customWidth'
    updateImgTab(activeImgTab.id, tab => {
      const updates = { aspectRatio: 'custom', [field]: value }
      if (!tab.customAspectLocked || !Number.isFinite(value) || value <= 0) return updates
      const storedRatio = Number(tab.customAspectRatio)
      const currentRatio = Number(tab.customWidth) / Number(tab.customHeight)
      const ratio = Number.isFinite(storedRatio) && storedRatio > 0 ? storedRatio : currentRatio
      if (!Number.isFinite(ratio) || ratio <= 0) return updates
      updates[pairedField] = alignSeedreamDimension(dimension === 'width' ? value / ratio : value * ratio)
      return updates
    })
  }, [activeImgTab.id, updateImgTab])

  const handleToggleCustomAspectLock = useCallback(() => {
    updateImgTab(activeImgTab.id, tab => {
      if (tab.customAspectLocked) return { customAspectLocked: false }
      const width = Number(tab.customWidth)
      const height = Number(tab.customHeight)
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return {}
      return { customAspectLocked: true, customAspectRatio: width / height }
    })
  }, [activeImgTab.id, updateImgTab])

  const handleSwapCustomDimensions = useCallback(() => {
    updateImgTab(activeImgTab.id, tab => {
      const width = Number(tab.customWidth)
      const height = Number(tab.customHeight)
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return {}
      const storedRatio = Number(tab.customAspectRatio)
      return {
        aspectRatio: 'custom',
        customWidth: height,
        customHeight: width,
        ...(tab.customAspectLocked && storedRatio > 0 ? { customAspectRatio: 1 / storedRatio } : {}),
      }
    })
  }, [activeImgTab.id, updateImgTab])

  const handleAlignCustomDimensions = useCallback(() => {
    updateImgTab(activeImgTab.id, tab => {
      const width = Number(tab.customWidth)
      const height = Number(tab.customHeight)
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return {}
      const alignedWidth = alignSeedreamDimension(width)
      const storedRatio = Number(tab.customAspectRatio)
      const alignedHeight = tab.customAspectLocked && storedRatio > 0
        ? alignSeedreamDimension(alignedWidth / storedRatio)
        : alignSeedreamDimension(height)
      return { aspectRatio: 'custom', customWidth: alignedWidth, customHeight: alignedHeight }
    })
  }, [activeImgTab.id, updateImgTab])

  const handleUseReferenceSize = useCallback((sourceIndex = referenceSizeIndex) => {
    const source = referenceSizeOptions.find(option => String(option.index) === String(sourceIndex))
    if (!isArk || !source) return
    const fitted = fitSeedreamSizeToReference(source.width, source.height)
    if (fitted.error) {
      notify(fitted.error, 'error')
      return
    }
    updateImgTab(activeImgTab.id, tab => ({
      aspectRatio: 'custom',
      customWidth: fitted.width,
      customHeight: fitted.height,
      ...(tab.customAspectLocked ? { customAspectRatio: fitted.width / fitted.height } : {}),
    }))
    if (fitted.adjusted) {
      notify(`参考素材 ${source.width}×${source.height} 已适配为 ${fitted.width}×${fitted.height}`)
    } else {
      notify('已使用参考素材尺寸')
    }
  }, [activeImgTab.id, isArk, notify, referenceSizeIndex, referenceSizeOptions, updateImgTab])

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
    if (isArk) {
      if (params.output_format !== undefined) {
        const outputFormat = String(params.output_format).toLowerCase().replace('jpg', 'jpeg')
        if (['png', 'jpeg'].includes(outputFormat)) updates.outputFormat = outputFormat
      }
      if (typeof params.watermark === 'boolean') updates.watermark = params.watermark
    } else {
      if (typeof params.use_search === 'boolean') updates.useSearch = params.use_search
      if (['minimal', 'high'].includes(params.think_level)) updates.thinkLevel = params.think_level
    }

    updateImgTab(activeImgTab.id, updates)
    setAppMode('image')
    notify(skipped.length ? `PNG Info 已载入，已忽略不兼容的${skipped.join('、')}` : 'PNG Info 已载入')
  }

  // 切换 provider 或标签页时修正不兼容的参数。
  useEffect(() => {
    if (!providerInfoReady) return
    const validResolutions = apiProvider === 'ark' ? ['1K', '2K'] : ['0.5K', '1K', '2K', '4K']
    const validRatios = apiProvider === 'ark' ? arkAspectRatios : standardAspectRatios
    const updates = {}
    if (!validResolutions.includes(activeImgTab.resolution)) updates.resolution = '1K'
    if (!validRatios.includes(activeImgTab.aspectRatio)) updates.aspectRatio = '1:1'
    if (Object.keys(updates).length > 0) updateImgTab(activeImgTab.id, updates)
  }, [apiProvider, activeImgTabId, providerInfoReady])

  useEffect(() => {
    fetchProviderInfo()
    fetchModelInfo()
    fetchVideoProviderInfo()
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
        setApiProvider(response.data.current_provider)
        setImageProviders(response.data.providers || {})
        if (response.data.current_provider !== 'ark' && response.data.current_model) setCurrentModel(response.data.current_model)
      }
    } catch (error) {
      console.error('Failed to fetch provider info:', error)
    } finally {
      setProviderInfoReady(true)
    }
  }

  const fetchModelInfo = async () => {
    try {
      const response = await axios.get('/api/model')
      if (response.data.success) {
        setCurrentModel(response.data.current_model)
        setAvailableModels(response.data.available_models)
      }
    } catch (error) { console.error('Failed to fetch model info:', error) }
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

  const handleImageModelChange = async (newModel) => {
    if (apiProvider === 'ark' || newModel === currentModel) return
    try {
      const response = await axios.post('/api/model', { model: newModel })
      if (response.data.success) {
        setCurrentModel(newModel)
      }
    } catch (error) { notify(`切换失败：${error.response?.data?.error || error.message}`, 'error') }
  }

  const handleImageProviderChange = async (newProvider) => {
    if (newProvider === apiProvider) return
    try {
      const response = await axios.post('/api/provider', { provider: newProvider })
      if (response.data.success) {
        setApiProvider(newProvider)
        if (newProvider !== 'ark' && response.data.model) setCurrentModel(response.data.model)
      }
    } catch (error) { notify(`切换失败：${error.response?.data?.error || error.message}`, 'error') }
  }
  
  const handleSavePrompt = async () => {
    const p = appMode === 'video' ? activeTab.prompt : activeImgTab.prompt
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
    if (apiProvider === 'ark' && tab.aspectRatio === 'custom') {
      const sizeError = validateSeedreamCustomSize(tab.customWidth, tab.customHeight)
      if (sizeError) {
        notify(sizeError, 'error')
        return
      }
    }
    const requestModel = apiProvider === 'ark' ? undefined : currentModel
    const arkRequestOptions = apiProvider === 'ark' ? {
      output_format: tab.outputFormat || 'png',
      watermark: Boolean(tab.watermark),
      ...(tab.aspectRatio === 'custom' ? {
        custom_width: Number(tab.customWidth),
        custom_height: Number(tab.customHeight),
      } : {}),
    } : {}
    const revealTimer = window.setTimeout(
      () => setTaskGalleryRevision(revision => revision + 1),
      500,
    )

    try {
      let response
      if (tab.uploadedImages.length === 0) {
        response = await axios.post('/api/generate', {
          prompt: tab.prompt, aspect_ratio: tab.aspectRatio,
          resolution: apiProvider === 'ark' && tab.aspectRatio === 'custom' ? undefined : tab.resolution,
          use_search: tab.useSearch, enable_chat: tab.chatMode, session_id: tab.sessionId,
          think_level: tab.thinkLevel, provider: apiProvider, model: requestModel,
          ...arkRequestOptions,
        })
      } else {
        const imageUrls = await Promise.all(tab.uploadedImages.map(async image => {
          if (image.preview?.startsWith('/api/workspace/assets/img_tabs/') && !image.file) {
            return image.preview
          }
          const blob = image.file || await ensureFetchOk(image.preview)
          const asset = await persistWorkspaceBlob('img_tabs', blob, image.name || 'image.png')
          return asset.url
        }))
        response = await axios.post('/api/generate', {
          prompt: tab.prompt, aspect_ratio: tab.aspectRatio,
          resolution: apiProvider === 'ark' && tab.aspectRatio === 'custom' ? undefined : tab.resolution,
          use_search: tab.useSearch, enable_chat: tab.chatMode, session_id: tab.sessionId,
          think_level: tab.thinkLevel, provider: apiProvider, model: requestModel,
          image_urls: imageUrls,
          ...arkRequestOptions,
        })
      }

      if (response.data.session_id) updateImgTab(tab.id, { sessionId: response.data.session_id })
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

  // 左侧面板拖拽调整宽度
  const [panelWidth, setPanelWidth] = useState(400)
  const isDragging = useRef(false)

  // 将历史任务参数覆盖到固定生成表单。
  const handleLoadTask = async (taskSummary) => {
    let task = taskSummary
    try {
      const resp = await axios.get(`/api/tasks/${taskSummary.id}`)
      if (resp.data.success) task = resp.data.task
    } catch (e) { /* use summary as fallback */ }
    const result = task.result || {}
    const params = task.params || {}

    if (task.type === 'image') {
      const id = activeImgTab.id || 1
      const restoredRefs = (result.local_refs || []).map((url, i) => ({ preview: url, name: `ref_${i}.png` }))
      const tab = {
        ...makeImgTab(id),
        prompt: task.prompt || '',
        aspectRatio: params.aspect_ratio || '1:1',
        resolution: params.resolution || '1K',
        customWidth: Number(params.custom_width) || 1024,
        customHeight: Number(params.custom_height) || 1024,
        customAspectRatio: (Number(params.custom_width) || 1024) / (Number(params.custom_height) || 1024),
        outputFormat: params.output_format || 'png',
        watermark: Boolean(params.watermark),
        useSearch: params.use_search || false,
        thinkLevel: params.think_level || 'minimal',
        uploadedImages: restoredRefs,
      }
      setImgTabs([tab])
      setActiveImgTabId(id)
      setAppMode('image')
    } else {
      const id = activeTab.id || 1
      const restoredVideos = (params.ref_video_urls || []).map((url, i) => ({
        uid: `restored_${i}_${Date.now()}`,
        name: `ref_video_${i}.mp4`, url, filepath: (params.ref_video_paths || [])[i] || null,
        thumbnail: null, progress: 100, uploading: false
      }))
      const lastFrameSrc = result.local_last_frame || result.images?.[0]?.image_url || null
      const tab = {
        ...makeVideoTab(id),
        prompt: task.prompt || '',
        model: params.model || SEEDANCE_20,
        ratio: params.ratio || 'adaptive',
        duration: params.duration || 5,
        resolution: params.resolution || '720p',
        outputFormat: params.output_format || 'mp4',
        fast: params.fast || false,
        audio: params.generate_audio !== false,
        returnLastFrame: params.return_last_frame || false,
        mode: params.video_mode || 'keyframe',
        refVideos: restoredVideos,
        lastFrame: lastFrameSrc ? { file: null, preview: lastFrameSrc } : null,
      }
      setVideoTabs([tab])
      setActiveVideoTabId(id)
      setAppMode('video')
    }
  }

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
    else updateImgTab(activeImgTab.id, { prompt })
    setShowPromptCollection(false)
  }
  const imageModelValue = isArk
    ? (imageProviders.ark?.model || 'seedream-5-0-pro')
    : currentModel

  return (
    <div ref={appShellRef} className="app-shell bg-nexus-bg text-nexus-text-light font-sans flex flex-col overflow-hidden relative">
      <GlassBackdrop />
      
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
            onChange={setAppMode}
            options={[
              { value: 'image', label: '图片', icon: ImageIcon },
              { value: 'video', label: '视频', icon: Film },
            ]}
          />
        </div>
        <div className="header-actions flex min-w-0 items-center gap-1.5">
          <div className="glass-control-group flex items-center gap-0.5">
            <IconButton label="PNG Info" onClick={() => setShowPngInfo(true)}><FileSearch size={16} /></IconButton>
            <IconButton label="提示词库" onClick={() => setShowPromptCollection(value => !value)} className={showPromptCollection ? 'text-nexus-green' : ''}><Library size={16} /></IconButton>
            <IconButton label="退出登录" onClick={handleLogout} className="hover:text-nexus-red"><LogOut size={16} /></IconButton>
          </div>
        </div>
      </header>

      {/* 主工作区 */}
      <main className="workspace-main flex-grow relative" style={{ '--prompt-user-width': `${panelWidth}px` }}>

      {appMode === 'image' ? (<>
        
        {/* 左侧：提示词输入 */}
        <section className="prompt-pane relative z-20">

          {/* 编辑器主体 */}
          <div className="flex-grow flex flex-col min-h-0 relative z-10">
            <TextToImage 
              prompt={activeImgTab.prompt} setPrompt={v => updateImgTab(activeImgTab.id, { prompt: v })}
              isGenerating={false} chatMode={activeImgTab.chatMode}
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
                    <option value="vertex" disabled={imageProviders.vertex?.available === false} className="bg-nexus-bg">
                      Vertex AI{imageProviders.vertex?.available === false ? ' · 未配置' : ''}
                    </option>
                  </select>
                </div>
                <div className="inspector-field-row">
                  <span className="field-label">模型</span>
                  <select
                    aria-label="图片模型"
                    value={imageModelValue}
                    disabled={!providerInfoReady || isArk || availableModels.length < 2}
                    onChange={event => handleImageModelChange(event.target.value)}
                    className="field-select min-w-0"
                  >
                    {isArk ? (
                      <option value={imageModelValue} className="bg-nexus-bg">Seedream 5.0 Pro</option>
                    ) : availableModels.length > 0 ? (
                      availableModels.map(model => (
                        <option key={model.id} value={model.id} className="bg-nexus-bg">{model.name || model.id}</option>
                      ))
                    ) : (
                      <option value={currentModel} className="bg-nexus-bg">{currentModel}</option>
                    )}
                  </select>
                </div>
              </div>
            </div>
            
            {/* GEOMETRY (宽高比) */}
            <div className="inspector-section">
              <div className="inspector-title">
                <Grid3X3 size={14} className="text-nexus-blue" /> 画幅
              </div>
              <div className="flex-grow">
                <div className="inspector-field-row">
                  <span className="field-label">比例</span>
                 <select 
                   value={activeImgTab.aspectRatio} onChange={e => updateImgTab(activeImgTab.id, { aspectRatio: e.target.value })}
                   aria-label="画幅"
                   className="field-select font-mono"
                 >
                   {aspectRatios.map((ratio) => (
                     <option key={ratio} value={ratio} className="bg-nexus-bg">
                       {ratio === 'auto' ? 'Auto' : ratio === 'custom' ? '自定义尺寸' : ratio}
                     </option>
                   ))}
                 </select>
                </div>
                 <div className="custom-size-editor" data-active={isCustomSeedreamSize ? 'true' : 'false'}>
                   <div className="custom-size-toolbar">
                     <div className="min-w-0">
                       <div className="text-[10px] font-semibold text-nexus-text">自定义尺寸</div>
                       <div className="mt-0.5 truncate font-mono text-[9px] text-nexus-muted">
                         {activeImgTab.customAspectLocked ? `LOCK · ${formatDimensionRatio(activeImgTab.customWidth, activeImgTab.customHeight)}` : 'FREE RATIO'}
                       </div>
                     </div>
                     <div className="custom-size-actions">
                       <IconButton label="交换宽高" tooltipClassName="icon-tooltip-above" onClick={handleSwapCustomDimensions} disabled={!canTransformCustomSize}>
                         <ArrowLeftRight size={14} />
                       </IconButton>
                       <IconButton
                         label={activeImgTab.customAspectLocked ? '解除宽高比锁定' : '锁定宽高比'}
                         onClick={handleToggleCustomAspectLock}
                         disabled={!canTransformCustomSize}
                         aria-pressed={Boolean(activeImgTab.customAspectLocked)}
                         className={activeImgTab.customAspectLocked ? 'btn-active' : ''}
                         tooltipClassName="icon-tooltip-above"
                       >
                         {activeImgTab.customAspectLocked ? <Lock size={13} /> : <LockOpen size={13} />}
                       </IconButton>
                       <IconButton label="对齐到 16 px" tooltipClassName="icon-tooltip-above" onClick={handleAlignCustomDimensions} disabled={!canTransformCustomSize}>
                         <Grid2X2Check size={14} />
                       </IconButton>
                     </div>
                   </div>
                   <div className="custom-size-reference-row">
                     <select
                       aria-label="参考素材尺寸"
                       value={referenceSizeIndex}
                       onChange={event => {
                         const sourceIndex = event.target.value
                         setReferenceSizeIndex(sourceIndex)
                         if (sourceIndex) handleUseReferenceSize(sourceIndex)
                       }}
                       disabled={!isArk || referenceSizeOptions.length === 0}
                       className="field-select min-w-0 font-mono"
                     >
                       <option value="" className="bg-nexus-bg">
                         {activeImgTab.uploadedImages?.length > 0 ? '正在读取参考素材尺寸' : '暂无参考素材'}
                       </option>
                       {referenceSizeOptions.map(option => (
                         <option key={option.index} value={String(option.index)} className="bg-nexus-bg">
                           {option.index + 1}. {option.name} · {option.width}×{option.height}
                         </option>
                       ))}
                     </select>
                     <IconButton
                       label="使用参考素材尺寸"
                       tooltipClassName="icon-tooltip-above"
                       onClick={() => handleUseReferenceSize(referenceSizeIndex)}
                       disabled={!isArk || !selectedReferenceSize}
                     >
                       <ImageDown size={14} />
                     </IconButton>
                   </div>
                   <div className="mt-2 grid grid-cols-2 gap-2">
                     <label className="min-w-0">
                       <span className="mb-1 block text-[10px] text-nexus-muted">宽度</span>
                       <input
                         type="number"
                         min="16"
                         step="16"
                         value={activeImgTab.customWidth}
                         onChange={event => handleCustomDimensionChange('width', event.target.value)}
                         aria-label="自定义图片宽度"
                         aria-describedby="custom-size-status"
                         disabled={!isArk}
                         className="glass-input h-9 w-full px-2 font-mono text-xs text-nexus-text-light outline-none"
                       />
                     </label>
                     <label className="min-w-0">
                       <span className="mb-1 block text-[10px] text-nexus-muted">高度</span>
                       <input
                         type="number"
                         min="16"
                         step="16"
                         value={activeImgTab.customHeight}
                         onChange={event => handleCustomDimensionChange('height', event.target.value)}
                         aria-label="自定义图片高度"
                         aria-describedby="custom-size-status"
                         disabled={!isArk}
                         className="glass-input h-9 w-full px-2 font-mono text-xs text-nexus-text-light outline-none"
                       />
                     </label>
                   </div>
                   <div
                     id="custom-size-status"
                     className={`custom-size-status ${customSizeError ? 'text-nexus-red' : isCustomSeedreamSize ? 'text-nexus-green' : 'text-nexus-muted'}`}
                     role={customSizeError ? 'alert' : 'status'}
                   >
                     {customSizeStatus}
                   </div>
                 </div>
              </div>
            </div>

            {/* ENGINE PARAMS (分辨率和其他) */}
            <div className="inspector-section">
              <div className="inspector-title">
                <Settings size={14} className="text-nexus-green" /> 输出设置
              </div>
              <div className="inspector-fields flex-grow">
                 {!isCustomSeedreamSize && <div className="inspector-field-row">
                   <span className="field-label">分辨率</span>
                   <select 
                     value={activeImgTab.resolution} onChange={e => updateImgTab(activeImgTab.id, { resolution: e.target.value })}
                     aria-label="图片分辨率"
                     className="field-select font-mono"
                   >
                     {resolutions.map((res) => (
                       <option key={res} value={res} className="bg-nexus-bg">{res}</option>
                     ))}
                   </select>
                 </div>}
                 {isArk ? (<>
                 <div className="inspector-field-row">
                   <span className="field-label">格式</span>
                   <select
                     value={activeImgTab.outputFormat || 'png'}
                     onChange={e => updateImgTab(activeImgTab.id, { outputFormat: e.target.value })}
                     className="field-select font-mono"
                   >
                     <option value="png" className="bg-nexus-bg">PNG</option>
                     <option value="jpeg" className="bg-nexus-bg">JPEG</option>
                   </select>
                 </div>
                 <div className="inspector-field-row">
                   <span className="field-label">添加水印</span>
                   <ToggleSwitch label="添加水印" checked={activeImgTab.watermark} onChange={watermark => updateImgTab(activeImgTab.id, { watermark })} />
                 </div>
                 <div className="inspector-field-row">
                   <span className="field-label">提示词优化</span>
                   <span className="text-xs font-medium text-nexus-green">标准</span>
                 </div>
                 </>) : (<>
                 <div className="inspector-field-row">
                   <span className="field-label">联网搜索</span>
                   <ToggleSwitch label="联网搜索" checked={activeImgTab.useSearch} onChange={useSearch => updateImgTab(activeImgTab.id, { useSearch })} />
                 </div>
                 <div className="inspector-field-row">
                   <span className="field-label">连续对话</span>
                   <ToggleSwitch label="连续对话" checked={activeImgTab.chatMode} onChange={chatMode => updateImgTab(activeImgTab.id, { chatMode })} />
                 </div>
                 <div className="inspector-field-row">
                   <span className="field-label">思考深度</span>
                   <select
                     value={activeImgTab.thinkLevel} onChange={e => updateImgTab(activeImgTab.id, { thinkLevel: e.target.value })}
                     className="field-select"
                   >
                     <option value="minimal" className="bg-nexus-bg">快速</option>
                     <option value="high" className="bg-nexus-bg">深入</option>
                   </select>
                 </div>
                 </>)}
              </div>
            </div>

            {/* SOURCE NODE */}
            <div className="inspector-section">
              <div className="inspector-title">
                <HardDrive size={14} className="text-nexus-violet" /> 参考素材
              </div>
              <div className="flex-grow min-h-0">
                 <ImageToImage
                   uploadedImages={activeImgTab.uploadedImages}
                   onPreview={setReferenceMedia}
                   setUploadedImages={value => updateImgTab(activeImgTab.id, tab => ({
                     uploadedImages: typeof value === 'function'
                       ? value(Array.isArray(tab.uploadedImages) ? tab.uploadedImages : [])
                       : value,
                   }))}
                   maxImages={isArk ? 10 : 14}
                 />
              </div>
            </div>

        </aside>

      </>) : (
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
                  <textarea
                    aria-label="视频提示词"
                    value={activeTab.prompt}
                    onChange={(e) => updateTab(activeTab.id, { prompt: e.target.value })}
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
                      disabled={activeVideoProvider === 'cupsy'}
                      onChange={e => handleVideoModelChange(e.target.value)}
                      className="field-select min-w-0"
                    >
                      {activeVideoProvider === 'ark' && <option value={SEEDANCE_20} className="bg-nexus-bg">Seedance 2.0</option>}
                      <option value={SEEDANCE_25} className="bg-nexus-bg">Seedance 2.5</option>
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
                      {['adaptive','16:9','4:3','1:1','3:4','9:16','21:9'].map(r => (
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
                      {activeVideoProvider === 'ark' && <option value={-1} className="bg-nexus-bg">
                        {isSeedance25 && activeTab.mode === 'reference' && hasReadyReferenceVideo ? 'Auto · 编辑跟随输入' : 'Auto'}
                      </option>}
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
                  {activeVideoProvider === 'cupsy' && (
                    <button type="button" className="cupsy-library-button" onClick={() => setShowCupsyAssets(true)}>
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
                  <Database size={14} className="text-nexus-amber" /> 费用估算
                </div>
                <div className="flex flex-col justify-between flex-grow gap-2">
                  {(() => {
                    const estimate = estimateBytePlusVideoCost({
                      model: effectiveVideoModel,
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
                      <div data-testid="video-cost-estimate" className="text-2xl font-mono text-nexus-green">{formatCnyEstimate(estimate)}</div>
                      <div className="text-xs font-mono text-nexus-text leading-5 opacity-80">
                        <div>{isSeedance25 ? 'Seedance 2.5 · 官方费率' : activeTab.fast ? 'Seedance 2.0 Fast' : 'Seedance 2.0'}</div>
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
      <CupsyAssetManager
        open={showCupsyAssets}
        mode={activeTab.mode}
        onClose={() => setShowCupsyAssets(false)}
        onUse={useCupsyAsset}
        onPreview={setReferenceMedia}
        notify={notify}
      />

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
                  <span className="truncate font-mono text-[11px] text-nexus-muted">{appMode === 'video' ? 'video_prompt' : 'image_prompt'}</span>
                </div>
                <div className="flex items-center gap-1">
                  <IconButton label="提示词库" onClick={() => setShowEditorVault(!showEditorVault)} className={showEditorVault ? 'border-nexus-violet/35 bg-nexus-violet/10 text-nexus-violet' : ''}><Library size={16} /></IconButton>
                  <IconButton label="保存提示词" onClick={handleSavePrompt} disabled={!(appMode === 'video' ? activeTab.prompt : activeImgTab.prompt).trim()}><Save size={16} /></IconButton>
                  <IconButton label="关闭编辑器" onClick={() => { setShowFullEditor(false); setShowEditorVault(false) }}><X size={17} /></IconButton>
                </div>
              </div>

              {/* 编辑器主体 */}
              <div className="flex-grow flex min-h-0 relative">
                {/* 行号 */}
                <div className="editor-gutter w-14 shrink-0 select-none overflow-hidden border-r border-nexus-border bg-nexus-panel py-4 pr-3 text-right font-mono text-xs text-nexus-muted/60">
                  {Array.from({ length: Math.max(50, (appMode === 'video' ? activeTab.prompt : activeImgTab.prompt).split('\n').length) }, (_, i) => (
                    <div key={i} className="h-6 leading-6">{i + 1}</div>
                  ))}
                </div>
                {/* 输入区 */}
                <textarea
                  autoFocus
                  aria-label="编辑提示词"
                  value={appMode === 'video' ? activeTab.prompt : activeImgTab.prompt}
                  onChange={(e) => appMode === 'video' ? updateTab(activeTab.id, { prompt: e.target.value }) : updateImgTab(activeImgTab.id, { prompt: e.target.value })}
                  className="min-w-0 flex-grow resize-none overflow-y-auto whitespace-pre-wrap break-words bg-transparent p-4 font-mono text-sm leading-6 text-nexus-text-light outline-none custom-scrollbar"
                  spellCheck="true"
                  placeholder="输入提示词..."
                />
                {/* Vault 侧边栏 */}
                {showEditorVault && (
                  <aside className="editor-vault liquid-glass-strong flex w-[360px] shrink-0 flex-col overflow-hidden">
                    <div className="flex h-10 shrink-0 items-center gap-2 border-b border-nexus-border px-3 text-xs font-semibold text-nexus-text-light"><Library size={14} className="text-nexus-violet" />提示词库</div>
                    <PromptCollection onSelectPrompt={(p) => appMode === 'video' ? updateTab(activeTab.id, { prompt: p }) : updateImgTab(activeImgTab.id, { prompt: p })} />
                  </aside>
                )}
              </div>

              {/* 底栏 */}
              <div className="flex h-8 shrink-0 items-center gap-4 border-t border-nexus-border bg-nexus-panel px-4 font-mono text-xs text-nexus-muted">
                <span>行 {(appMode === 'video' ? activeTab.prompt : activeImgTab.prompt).split('\n').length}</span>
                <span>字符 {(appMode === 'video' ? activeTab.prompt : activeImgTab.prompt).length}</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}

      <AnimatePresence>
        {notification && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            role={notification.tone === 'error' ? 'alert' : 'status'}
            aria-live="polite"
            className={`fixed bottom-4 right-4 z-[1200] flex max-w-[calc(100vw-32px)] items-center gap-2 rounded-md border px-3 py-2.5 text-sm shadow-2xl ${notification.tone === 'error' ? 'border-nexus-red/35 bg-[#211417] text-nexus-red' : 'border-nexus-green/35 bg-[#102019] text-nexus-text-light'}`}
          >
            {notification.tone === 'error' ? <CircleAlert size={15} /> : <Check size={15} className="text-nexus-green" />}
            {notification.message}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default AuthGate
