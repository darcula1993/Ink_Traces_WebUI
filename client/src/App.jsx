import React, { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import TextToImage from './components/TextToImage'
import ImageToImage from './components/ImageToImage'
import PromptCollection from './components/PromptCollection'
import TaskGallery from './components/TaskGallery'
import CodeRainCanvas from './components/CodeRainCanvas'
import GlassBackdrop from './components/GlassBackdrop'
import IconButton from './components/ui/IconButton'
import SegmentedControl from './components/ui/SegmentedControl'
import ToggleSwitch from './components/ui/ToggleSwitch'
import { motion, AnimatePresence } from 'framer-motion'
import ReactDOM from 'react-dom'
import { Play, Settings, Cpu, HardDrive, Grid3X3, Database, X, Maximize2, Save, Film, LogOut, Bot, Send, Check, Image as ImageIcon, Library, Plus, SlidersHorizontal, Braces, User, LockKeyhole, AudioLines, CircleAlert } from 'lucide-react'
import { persistWorkspaceBlob, useWorkspaceState } from './lib/useWorkspaceState'

axios.defaults.withCredentials = true

function makeImgTab(id) {
  return {
    id, prompt: '', aspectRatio: '1:1', resolution: '1K', useSearch: false, thinkLevel: 'minimal',
    chatMode: false, sessionId: null, uploadedImages: [], outputFormat: 'png', watermark: false,
    loading: false, taskId: null, dbTaskId: null, taskStatus: null, generatedImages: [], thinkingText: '', error: null, errorType: null, errorDetails: null,
  }
}

function makeVideoTab(id) {
  return {
    id, prompt: '', ratio: 'adaptive', duration: 5, resolution: '720p',
    fast: false, audio: true, returnLastFrame: false, mode: 'keyframe', search: false,
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
  const [showFullEditor, setShowFullEditor] = useState(false)
  const [showEditorVault, setShowEditorVault] = useState(false)
  const [optimizingVideoPrompt, setOptimizingVideoPrompt] = useState(false)
  const [showVideoPromptAgent, setShowVideoPromptAgent] = useState(false)
  const [videoPromptAgentSessionId, setVideoPromptAgentSessionId] = useState(null)
  const [videoPromptAgentMessages, setVideoPromptAgentMessages] = useState([])
  const [videoPromptAgentInput, setVideoPromptAgentInput] = useState('')
  const [videoPromptAgentLoading, setVideoPromptAgentLoading] = useState(false)
  const [videoPromptAgentDraft, setVideoPromptAgentDraft] = useState('')
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

  const [apiProvider, setApiProvider] = useState('vertex')
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

  // 视频 Provider
  const [videoProvider, setVideoProvider] = useWorkspaceState('vid_provider', 'ark')

  // 视频生成表单。沿用旧 workspace key，在加载后收敛为单一表单。
  const [videoTabs, setVideoTabs, videoWorkspace] = useWorkspaceState('vid_tabs', [makeVideoTab(1)], VIDEO_WORKSPACE_OPTIONS)
  const [activeVideoTabId, setActiveVideoTabId] = useWorkspaceState('vid_activeTab', 1)

  const activeTab = videoTabs.find(t => t.id === activeVideoTabId) || videoTabs[0] || makeVideoTab(1)

  const updateTab = useCallback((id, updates) => {
    setVideoTabs(prev => prev.map(t => t.id === id ? { ...t, ...updates } : t))
  }, [setVideoTabs])
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
  const arkAspectRatios = ['1:1', '4:3', '3:4', '16:9', '9:16', '3:2', '2:3', '21:9']
  const aspectRatios = isArk ? arkAspectRatios : standardAspectRatios
  const resolutions = isArk ? ['1K', '2K'] : ['0.5K', '1K', '2K', '4K']

  // 切换 provider 或标签页时修正不兼容的参数。
  useEffect(() => {
    const validResolutions = apiProvider === 'ark' ? ['1K', '2K'] : ['0.5K', '1K', '2K', '4K']
    const validRatios = apiProvider === 'ark' ? arkAspectRatios : standardAspectRatios
    const updates = {}
    if (!validResolutions.includes(activeImgTab.resolution)) updates.resolution = '1K'
    if (!validRatios.includes(activeImgTab.aspectRatio)) updates.aspectRatio = '1:1'
    if (Object.keys(updates).length > 0) updateImgTab(activeImgTab.id, updates)
  }, [apiProvider, activeImgTabId])

  useEffect(() => {
    fetchProviderInfo()
    fetchModelInfo()
  }, [])

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
        if (response.data.current_provider !== 'ark' && response.data.current_model) setCurrentModel(response.data.current_model)
      }
    } catch (error) { console.error('Failed to fetch provider info:', error) }
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

  const switchModel = async () => {
    if (apiProvider === 'ark') return
    if (availableModels.length < 2) return
    const currentIndex = availableModels.findIndex(m => m.id === currentModel)
    const nextIndex = (currentIndex + 1) % availableModels.length
    const newModel = availableModels[nextIndex].id
    try {
      const response = await axios.post('/api/model', { model: newModel })
      if (response.data.success) {
        setCurrentModel(newModel)
      }
    } catch (error) { notify(`切换失败：${error.response?.data?.error || error.message}`, 'error') }
  }

  const switchApiProvider = async () => {
    const order = ['vertex', 'ai_studio', 'ark']
    const idx = order.indexOf(apiProvider)
    const newProvider = order[(idx + 1) % order.length]
    try {
      const response = await axios.post('/api/provider', { provider: newProvider })
      if (response.data.success) {
        setApiProvider(newProvider)
        if (newProvider !== 'ark' && response.data.model) setCurrentModel(response.data.model)
      }
    } catch (error) { notify(`切换失败：${error.response?.data?.error || error.message}`, 'error') }
  }
  
  const switchVideoProvider = async () => {
    const newProvider = videoProvider === 'jiekou' ? 'ark' : 'jiekou'
    try {
      const response = await axios.post('/api/video/provider', { provider: newProvider })
      if (response.data.success) setVideoProvider(newProvider)
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
    const requestModel = apiProvider === 'ark' ? undefined : currentModel
    const revealTimer = window.setTimeout(
      () => setTaskGalleryRevision(revision => revision + 1),
      500,
    )

    try {
      let response
      if (tab.uploadedImages.length === 0) {
        response = await axios.post('/api/generate', {
          prompt: tab.prompt, aspect_ratio: tab.aspectRatio, resolution: tab.resolution,
          use_search: tab.useSearch, enable_chat: tab.chatMode, session_id: tab.sessionId,
          think_level: tab.thinkLevel, provider: apiProvider, model: requestModel,
          ...(apiProvider === 'ark' ? {
            output_format: tab.outputFormat || 'png',
            watermark: Boolean(tab.watermark)
          } : {})
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
          prompt: tab.prompt, aspect_ratio: tab.aspectRatio, resolution: tab.resolution,
          use_search: tab.useSearch, enable_chat: tab.chatMode, session_id: tab.sessionId,
          think_level: tab.thinkLevel, provider: apiProvider, model: requestModel,
          image_urls: imageUrls,
          ...(apiProvider === 'ark' ? {
            output_format: tab.outputFormat || 'png',
            watermark: Boolean(tab.watermark)
          } : {})
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

  const buildVideoPromptContextPayload = (tab) => {
    const videoUrls = tab.refVideos.filter(v => v.url && !v.uploading)
    return {
      prompt: tab.prompt,
      mode: tab.mode,
      ratio: tab.ratio,
      duration: tab.duration,
      resolution: tab.resolution,
      fast: tab.fast,
      generate_audio: tab.audio,
      return_last_frame: tab.returnLastFrame,
      has_first_frame: Boolean(tab.firstFrame),
      has_last_frame: Boolean(tab.lastFrame),
      ref_image_count: tab.refImages.length,
      ref_video_count: videoUrls.length,
      ref_audio_count: tab.refAudios.length
    }
  }

  // 视频模式粘贴上传图片
  useEffect(() => {
    if (appMode !== 'video') return
    const handlePaste = (e) => {
      const files = []
      for (const item of e.clipboardData.items) {
        if (item.type.startsWith('image/')) files.push(item.getAsFile())
      }
      if (files.length === 0) return
      const tab = activeTab
      if (tab.mode === 'keyframe') {
        const f = files[0]
        const reader = new FileReader()
        reader.onload = ev => {
          if (!tab.firstFrame) updateTab(tab.id, { firstFrame: { file: f, preview: ev.target.result } })
          else if (!tab.lastFrame) updateTab(tab.id, { lastFrame: { file: f, preview: ev.target.result } })
        }
        reader.readAsDataURL(f)
      } else {
        const remaining = 9 - tab.refImages.length
        const toProcess = files.slice(0, remaining)
        Promise.all(toProcess.map(f => new Promise(r => {
          const rd = new FileReader()
          rd.onload = ev => r({ file: f, preview: ev.target.result })
          rd.readAsDataURL(f)
        }))).then(items => updateTab(tab.id, { refImages: [...tab.refImages, ...items] }))
      }
    }
    document.addEventListener('paste', handlePaste)
    return () => document.removeEventListener('paste', handlePaste)
  })

  const handleVideoGenerate = async () => {
    const tab = activeTab
    if (!videoTabHasInput(tab)) {
      notify('请填写视频提示词或添加参考素材', 'error')
      return
    }
    const revealTimer = window.setTimeout(
      () => setTaskGalleryRevision(revision => revision + 1),
      500,
    )

    try {
      let resp
      const hasFiles = Boolean(tab.firstFrame || tab.lastFrame || tab.refImages.length > 0 || tab.refAudios.length > 0)

      // 收集已上传的视频 URL
      const videoUrls = tab.refVideos.filter(v => v.url && !v.uploading).map(v => v.url)

      if (hasFiles) {
        const formData = new FormData()
        formData.append('prompt', tab.prompt)
        formData.append('ratio', tab.ratio)
        formData.append('duration', tab.duration)
        formData.append('resolution', tab.resolution)
        formData.append('fast', tab.fast)
        formData.append('generate_audio', tab.audio)
        formData.append('return_last_frame', tab.returnLastFrame)
        formData.append('web_search', tab.search)
        formData.append('video_mode', tab.mode)
        formData.append('provider', videoProvider)
        const pendingFetches = []
        if (tab.mode === 'keyframe') {
          if (tab.firstFrame) {
            if (tab.firstFrame.file) formData.append('image', tab.firstFrame.file)
            else if (tab.firstFrame.preview) pendingFetches.push(
              ensureFetchOk(tab.firstFrame.preview).then(blob => formData.append('image', blob, 'first_frame.png'))
            )
          }
          if (tab.lastFrame) {
            if (tab.lastFrame.file) formData.append('last_image', tab.lastFrame.file)
            else if (tab.lastFrame.preview) pendingFetches.push(
              ensureFetchOk(tab.lastFrame.preview).then(blob => formData.append('last_image', blob, 'last_frame.png'))
            )
          }
        } else {
          const refImgFetches = tab.refImages.map(img => {
            if (img.file) { formData.append('ref_images', img.file); return null }
            if (img.preview) return ensureFetchOk(img.preview).then(blob => formData.append('ref_images', blob, img.name || 'ref.png'))
            return null
          }).filter(Boolean)
          pendingFetches.push(...refImgFetches)
          tab.refAudios.forEach((aud, index) => {
            if (aud.file) {
              formData.append('ref_audios', aud.file)
            } else if (aud.preview) {
              pendingFetches.push(
                ensureFetchOk(aud.preview).then(blob => formData.append('ref_audios', blob, aud.name || `audio_${index}.wav`))
              )
            }
          })
        }
        if (videoUrls.length) formData.append('ref_video_urls', JSON.stringify(videoUrls))
        if (pendingFetches.length) await Promise.all(pendingFetches)
        resp = await axios.post('/api/video/generate', formData, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 300000 })
      } else {
        resp = await axios.post('/api/video/generate', {
          prompt: tab.prompt, ratio: tab.ratio, duration: tab.duration,
          resolution: tab.resolution, fast: tab.fast, generate_audio: tab.audio,
          return_last_frame: tab.returnLastFrame, web_search: tab.search,
          video_mode: tab.mode,
          provider: videoProvider,
          ref_video_urls: videoUrls.length ? videoUrls : undefined
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

  const handleOptimizeVideoPrompt = async () => {
    const tab = activeTab
    if (!tab.prompt.trim()) return
    setOptimizingVideoPrompt(true)
    updateTab(tab.id, { error: null })
    try {
      const resp = await axios.post('/api/video/optimize-prompt', buildVideoPromptContextPayload(tab), { timeout: 120000 })
      if (resp.data.success && resp.data.prompt) {
        updateTab(tab.id, { prompt: resp.data.prompt })
      } else {
        updateTab(tab.id, { error: resp.data.error || 'Prompt 优化失败' })
      }
    } catch (e) {
      updateTab(tab.id, { error: e.response?.data?.error || e.message || 'Prompt 优化失败' })
    } finally {
      setOptimizingVideoPrompt(false)
    }
  }

  const sendVideoPromptAgentMessage = async (message, startNew = false) => {
    const tab = activeTab
    if (!videoTabHasInput(tab) && !message.trim()) return

    const userMessage = message.trim() || '请根据当前视频 prompt 和参数开始优化。'
    setVideoPromptAgentLoading(true)
    setShowVideoPromptAgent(true)
    setVideoPromptAgentInput('')
    setVideoPromptAgentMessages(prev => [...prev, { role: 'user', content: userMessage }])
    updateTab(tab.id, { error: null })

    try {
      const resp = await axios.post('/api/video/prompt-agent/message', {
        ...buildVideoPromptContextPayload(tab),
        session_id: startNew ? null : videoPromptAgentSessionId,
        message: userMessage
      }, { timeout: 120000 })

      if (resp.data.success) {
        setVideoPromptAgentSessionId(resp.data.session_id)
        setVideoPromptAgentMessages(resp.data.history || [
          { role: 'user', content: userMessage },
          { role: 'assistant', content: resp.data.message || '' }
        ])
        setVideoPromptAgentDraft(resp.data.optimized_prompt || '')
      } else {
        updateTab(tab.id, { error: resp.data.error || 'Prompt Agent 失败' })
      }
    } catch (e) {
      updateTab(tab.id, { error: e.response?.data?.error || e.message || 'Prompt Agent 失败' })
      setVideoPromptAgentMessages(prev => [...prev, { role: 'assistant', content: e.response?.data?.error || e.message || 'Prompt Agent 失败' }])
    } finally {
      setVideoPromptAgentLoading(false)
    }
  }

  const openVideoPromptAgent = () => {
    if (!showVideoPromptAgent) setShowVideoPromptAgent(true)
    if (videoPromptAgentMessages.length === 0) {
      sendVideoPromptAgentMessage('', true)
    }
  }

  const resetVideoPromptAgent = async () => {
    const oldSessionId = videoPromptAgentSessionId
    setVideoPromptAgentSessionId(null)
    setVideoPromptAgentMessages([])
    setVideoPromptAgentInput('')
    setVideoPromptAgentDraft('')
    if (oldSessionId) {
      axios.delete(`/api/video/prompt-agent/session/${oldSessionId}`).catch(() => {})
    }
  }

  const applyVideoPromptAgentDraft = () => {
    if (!videoPromptAgentDraft.trim()) return
    updateTab(activeTab.id, { prompt: videoPromptAgentDraft.trim() })
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
        ratio: params.ratio || 'adaptive',
        duration: params.duration || 5,
        resolution: params.resolution || '720p',
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
  const currentModelLabel = appMode === 'video'
    ? 'Seedance 2.0'
    : apiProvider === 'ark'
      ? 'Seedream 5.0 Pro'
      : currentModel.includes('flash') ? 'Gemini Flash 3.1' : 'Gemini Pro 3.0'
  const currentProviderLabel = appMode === 'video'
    ? (videoProvider === 'ark' ? 'Ark' : 'Jiekou')
    : apiProvider === 'vertex' ? 'Vertex AI' : apiProvider === 'ark' ? 'Ark' : 'AI Studio'
  const canSwitchModel = appMode === 'image' && apiProvider !== 'ark' && availableModels.length > 1

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
          <button onClick={canSwitchModel ? switchModel : undefined} aria-disabled={!canSwitchModel} className={`header-chip btn-base btn-outline max-w-[220px] ${canSwitchModel ? '' : 'cursor-default'}`} title={canSwitchModel ? '切换模型' : '当前模型'}>
            <Cpu size={14} className="text-nexus-green" />
            <span className="header-model-label truncate">{currentModelLabel}</span>
          </button>
          <button onClick={appMode === 'video' ? switchVideoProvider : switchApiProvider} className="header-chip btn-base btn-outline max-w-[150px]" title="切换 Provider">
            <Database size={14} className="text-nexus-blue" />
            <span className="header-provider-label truncate">{currentProviderLabel}</span>
          </button>
          <div className="glass-control-group flex items-center gap-0.5">
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
            <span className="font-mono text-[11px] text-nexus-muted">{activeImgTab.aspectRatio} · {activeImgTab.resolution}</span>
          </div>
            
            {/* GEOMETRY (宽高比) */}
            <div className="inspector-section">
              <div className="inspector-title">
                <Grid3X3 size={14} className="text-nexus-blue" /> 画幅
              </div>
              <div className="flex-grow">
                 <select 
                   value={activeImgTab.aspectRatio} onChange={e => updateImgTab(activeImgTab.id, { aspectRatio: e.target.value })}
                   className="field-select w-full font-mono"
                 >
                   {aspectRatios.map((ratio) => (
                     <option key={ratio} value={ratio} className="bg-nexus-bg">{ratio}</option>
                   ))}
                 </select>
                 <div className="mt-2 text-xs text-nexus-muted">输出画面的宽高比例</div>
              </div>
            </div>

            {/* ENGINE PARAMS (分辨率和其他) */}
            <div className="inspector-section">
              <div className="inspector-title">
                <Settings size={14} className="text-nexus-green" /> 输出设置
              </div>
              <div className="flex flex-col justify-between flex-grow gap-2">
                 <div className="flex items-center justify-between">
                   <span className="field-label">分辨率</span>
                   <select 
                     value={activeImgTab.resolution} onChange={e => updateImgTab(activeImgTab.id, { resolution: e.target.value })}
                     className="field-select font-mono"
                   >
                     {resolutions.map((res) => (
                       <option key={res} value={res} className="bg-nexus-bg">{res}</option>
                     ))}
                   </select>
                 </div>
                 {isArk ? (<>
                 <div className="flex items-center justify-between">
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
                 <div className="flex items-center justify-between">
                   <span className="field-label">添加水印</span>
                   <ToggleSwitch label="添加水印" checked={activeImgTab.watermark} onChange={watermark => updateImgTab(activeImgTab.id, { watermark })} />
                 </div>
                 <div className="flex items-center justify-between">
                   <span className="field-label">提示词优化</span>
                   <span className="text-xs font-medium text-nexus-green">标准</span>
                 </div>
                 </>) : (<>
                 <div className="flex items-center justify-between">
                   <span className="field-label">联网搜索</span>
                   <ToggleSwitch label="联网搜索" checked={activeImgTab.useSearch} onChange={useSearch => updateImgTab(activeImgTab.id, { useSearch })} />
                 </div>
                 <div className="flex items-center justify-between">
                   <span className="field-label">连续对话</span>
                   <ToggleSwitch label="连续对话" checked={activeImgTab.chatMode} onChange={chatMode => updateImgTab(activeImgTab.id, { chatMode })} />
                 </div>
                 <div className="flex items-center justify-between">
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
              <div className="grid grid-cols-2 gap-2 mb-3">
                <button
                  onClick={handleOptimizeVideoPrompt}
                  disabled={optimizingVideoPrompt || !activeTab.prompt.trim()}
                  className="btn-base btn-outline min-h-9 px-2 text-xs"
                >
                  {optimizingVideoPrompt ? (
                    <><Cpu size={12} className="animate-pulse" /> <span>优化中</span></>
                  ) : (
                    <><Settings size={12} /> <span>快速优化</span></>
                  )}
                </button>
                <button
                  onClick={openVideoPromptAgent}
                  disabled={videoPromptAgentLoading || !videoTabHasInput(activeTab)}
                  className={`btn-base min-h-9 px-2 text-xs ${showVideoPromptAgent ? 'btn-active' : 'btn-outline'}`}
                >
                  <Bot size={12} /> <span>{videoPromptAgentLoading ? '处理中' : '提示词助手'}</span>
                </button>
              </div>
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
              <span className="font-mono text-[11px] text-nexus-muted">{activeTab.resolution} · {activeTab.duration === -1 ? 'Auto' : `${activeTab.duration}s`}</span>
            </div>

              {/* 生成模式 */}
              <div className="inspector-section">
                <div className="inspector-title">
                  <Grid3X3 size={14} className="text-nexus-blue" /> 生成设置
                </div>
                <div className="flex flex-col justify-between flex-grow gap-2">
                  <div className="flex items-center justify-between">
                    <span className="field-label">画幅</span>
                    <select value={activeTab.ratio} onChange={e => updateTab(activeTab.id, { ratio: e.target.value })}
                      className="field-select font-mono">
                      {['adaptive','16:9','4:3','1:1','3:4','9:16','21:9'].map(r => (
                        <option key={r} value={r} className="bg-nexus-bg">{r}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="field-label">模式</span>
                    <select value={activeTab.mode} onChange={e => updateTab(activeTab.id, { mode: e.target.value })}
                      className="field-select">
                      <option value="keyframe" className="bg-nexus-bg">首尾帧</option>
                      <option value="reference" className="bg-nexus-bg">全能参考</option>
                    </select>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="field-label">联网搜索</span>
                    <ToggleSwitch label="联网搜索" checked={activeTab.search} onChange={search => updateTab(activeTab.id, { search })} />
                  </div>
                </div>
              </div>

              {/* ENGINE PARAMS */}
              <div className="inspector-section">
                <div className="inspector-title">
                  <Settings size={14} className="text-nexus-green" /> 输出参数
                </div>
                <div className="flex flex-col justify-between flex-grow gap-2">
                  <div className="flex items-center justify-between">
                    <span className="field-label">分辨率</span>
                    <select value={activeTab.resolution} onChange={e => updateTab(activeTab.id, { resolution: e.target.value })}
                      className="field-select font-mono">
                      <option value="480p" className="bg-nexus-bg">480p</option>
                      <option value="720p" className="bg-nexus-bg">720p</option>
                      <option value="1080p" className="bg-nexus-bg">1080p</option>
                    </select>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="field-label">时长</span>
                    <select value={activeTab.duration} onChange={e => updateTab(activeTab.id, { duration: Number(e.target.value) })}
                      className="field-select font-mono">
                      {[4,5,6,7,8,9,10,11,12,13,14,15].map(d => (
                        <option key={d} value={d} className="bg-nexus-bg">{d}s</option>
                      ))}
                      <option value={-1} className="bg-nexus-bg">Auto</option>
                    </select>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="field-label">快速模式</span>
                    <ToggleSwitch label="快速模式" checked={activeTab.fast} onChange={fast => updateTab(activeTab.id, { fast })} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="field-label">生成音频</span>
                    <ToggleSwitch label="生成音频" checked={activeTab.audio} onChange={audio => updateTab(activeTab.id, { audio })} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="field-label">返回尾帧</span>
                    <ToggleSwitch label="返回尾帧" checked={activeTab.returnLastFrame} onChange={returnLastFrame => updateTab(activeTab.id, { returnLastFrame })} />
                  </div>
                </div>
              </div>

              {/* KEYFRAMES / REFERENCE */}
              <div className="inspector-section">
                <div className="inspector-title">
                  <Film size={14} className="text-nexus-violet" /> {activeTab.mode === 'keyframe' ? '关键帧' : '参考素材'}
                </div>

                {activeTab.mode === 'keyframe' ? (
                <div className="flex-grow flex gap-3">
                  <div className="w-[120px] flex flex-col">
                    <span className="mb-1.5 text-xs text-nexus-text">首帧</span>
                    {activeTab.firstFrame ? (
                      <div className="w-[120px] h-[120px] relative group rounded overflow-hidden border border-nexus-border">
                        <img src={activeTab.firstFrame.preview} className="w-full h-full object-cover" alt="首帧" />
                        <button aria-label="删除首帧" title="删除首帧" onClick={() => updateTab(activeTab.id, { firstFrame: null })}
                          className="absolute right-1 top-1 rounded bg-black/75 p-1 text-white transition-colors hover:bg-nexus-red">
                          <X size={10} />
                        </button>
                      </div>
                    ) : (
                      <label className="flex h-[120px] w-[120px] cursor-pointer flex-col items-center justify-center gap-2 rounded border border-dashed border-nexus-border text-xs text-nexus-text transition-colors hover:border-nexus-green hover:bg-nexus-green/5 hover:text-nexus-green">
                        <Plus size={16} /> 添加
                        <input aria-label="上传首帧" type="file" accept="image/*" className="hidden" onChange={e => {
                          const f = e.target.files[0]; if (!f) return
                          const reader = new FileReader()
                          reader.onload = ev => updateTab(activeTab.id, { firstFrame: { file: f, preview: ev.target.result } })
                          reader.readAsDataURL(f)
                        }} />
                      </label>
                    )}
                  </div>
                  <div className="w-[120px] flex flex-col">
                    <span className="mb-1.5 text-xs text-nexus-text">尾帧</span>
                    {activeTab.lastFrame ? (
                      <div className="w-[120px] h-[120px] relative group rounded overflow-hidden border border-nexus-border">
                        <img src={activeTab.lastFrame.preview} className="w-full h-full object-cover" alt="尾帧" />
                        <button aria-label="删除尾帧" title="删除尾帧" onClick={() => updateTab(activeTab.id, { lastFrame: null })}
                          className="absolute right-1 top-1 rounded bg-black/75 p-1 text-white transition-colors hover:bg-nexus-red">
                          <X size={10} />
                        </button>
                      </div>
                    ) : (
                      <label className="flex h-[120px] w-[120px] cursor-pointer flex-col items-center justify-center gap-2 rounded border border-dashed border-nexus-border text-xs text-nexus-text transition-colors hover:border-nexus-green hover:bg-nexus-green/5 hover:text-nexus-green">
                        <Plus size={16} /> 添加
                        <input aria-label="上传尾帧" type="file" accept="image/*" className="hidden" onChange={e => {
                          const f = e.target.files[0]; if (!f) return
                          const reader = new FileReader()
                          reader.onload = ev => updateTab(activeTab.id, { lastFrame: { file: f, preview: ev.target.result } })
                          reader.readAsDataURL(f)
                        }} />
                      </label>
                    )}
                  </div>
                </div>
                ) : (
                <div className="flex-grow flex gap-4 overflow-x-auto">
                  {/* REF IMAGES (max 9) */}
                  <div className="flex flex-col min-w-[120px]">
                    <span className="mb-1.5 text-xs text-nexus-text">图片（最多 9 个）</span>
                    <div className="flex-grow flex gap-1.5 flex-wrap items-start">
                      {activeTab.refImages.map((img, i) => (
                        <div key={i} className="w-14 h-14 relative group rounded overflow-hidden border border-nexus-border shrink-0">
                          <img src={img.preview} className="w-full h-full object-cover" alt="" />
                          <button aria-label={`删除参考图片 ${i + 1}`} title="删除" onClick={() => updateTab(activeTab.id, { refImages: activeTab.refImages.filter((_, j) => j !== i) })}
                            className="absolute right-0.5 top-0.5 rounded bg-black/75 p-0.5 text-white transition-colors hover:bg-nexus-red">
                            <X size={8} />
                          </button>
                        </div>
                      ))}
                      {activeTab.refImages.length < 9 && (
                        <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-[10px] font-mono">
                          <Plus size={14} />
                          <input aria-label="上传参考图片" type="file" accept="image/*" multiple className="hidden" onChange={e => {
                            const files = Array.from(e.target.files).slice(0, 9 - activeTab.refImages.length)
                            Promise.all(files.map(f => new Promise(r => { const rd = new FileReader(); rd.onload = ev => r({ file: f, preview: ev.target.result }); rd.readAsDataURL(f) })))
                              .then(items => updateTab(activeTab.id, { refImages: [...activeTab.refImages, ...items] }))
                          }} />
                        </label>
                      )}
                    </div>
                  </div>
                  {/* REF VIDEOS (max 3) */}
                  <div className="flex flex-col min-w-[100px]">
                    <span className="mb-1.5 text-xs text-nexus-text">视频（最多 3 个）</span>
                    <div className="flex-grow flex gap-1.5 flex-wrap items-start">
                      {activeTab.refVideos.map((vid, i) => (
                        <div key={vid.uid || i} className="w-14 h-14 relative group rounded overflow-hidden border border-nexus-border shrink-0 bg-[#111] flex items-center justify-center">
                          {vid.uploading ? (
                            <div className="absolute inset-0 flex items-center justify-center">
                              <div className="w-10 h-1 bg-[#333] rounded overflow-hidden">
                                <div className="h-full bg-nexus-green transition-all" style={{ width: `${vid.progress || 0}%` }}></div>
                              </div>
                            </div>
                          ) : vid.thumbnail ? (
                            <img src={vid.thumbnail} className="w-full h-full object-cover" alt="" />
                          ) : (
                            <Film size={14} className="text-nexus-green" />
                          )}
                          <span className="absolute bottom-0.5 text-[8px] font-mono text-nexus-text truncate w-full text-center">{vid.name?.slice(0,6)}</span>
                          <button aria-label={`删除参考视频 ${i + 1}`} title="删除" onClick={() => {
                              if (vid.url) {
                                axios.delete('/api/upload_video', { data: { url: vid.url } }).catch(() => {})
                              }
                              updateTab(activeTab.id, { refVideos: activeTab.refVideos.filter((_, j) => j !== i) })
                            }}
                            className="absolute right-0.5 top-0.5 rounded bg-black/75 p-0.5 text-white transition-colors hover:bg-nexus-red">
                            <X size={8} />
                          </button>
                        </div>
                      ))}
                      {activeTab.refVideos.length < 3 && (
                        <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-[10px] font-mono">
                          <Plus size={14} />
                          <input aria-label="上传参考视频" type="file" accept="video/mp4,video/quicktime" multiple className="hidden" onChange={e => {
                            const files = Array.from(e.target.files).slice(0, 3 - activeTab.refVideos.length)
                            const items = files.map(f => ({ uid: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`, name: f.name, url: null, thumbnail: null, progress: 0, uploading: true }))
                            const tabId = activeTab.id
                            updateTab(tabId, { refVideos: [...activeTab.refVideos, ...items] })
                            files.forEach((f, fi) => {
                              const uid = items[fi].uid
                              // 提取首帧缩略图
                              const vidEl = document.createElement('video')
                              const objectUrl = URL.createObjectURL(f)
                              const cleanupObjectUrl = () => URL.revokeObjectURL(objectUrl)
                              vidEl.preload = 'metadata'
                              vidEl.muted = true
                              vidEl.src = objectUrl
                              vidEl.onloadeddata = () => { vidEl.currentTime = 0.1 }
                              vidEl.onseeked = () => {
                                const canvas = document.createElement('canvas')
                                canvas.width = vidEl.videoWidth
                                canvas.height = vidEl.videoHeight
                                canvas.getContext('2d').drawImage(vidEl, 0, 0)
                                const thumb = canvas.toDataURL('image/jpeg', 0.6)
                                cleanupObjectUrl()
                                setVideoTabs(prev => prev.map(t => t.id === tabId ? { ...t, refVideos: t.refVideos.map(v => v.uid === uid ? { ...v, thumbnail: thumb } : v) } : t))
                              }
                              vidEl.onerror = cleanupObjectUrl
                              // 上传
                              const fd = new FormData()
                              fd.append('file', f)
                              axios.post('/api/upload_video', fd, {
                                headers: { 'Content-Type': 'multipart/form-data' },
                                onUploadProgress: (ev) => {
                                  const pct = Math.round((ev.loaded / ev.total) * 100)
                                  setVideoTabs(prev => prev.map(t => t.id === tabId ? { ...t, refVideos: t.refVideos.map(v => v.uid === uid ? { ...v, progress: pct } : v) } : t))
                                }
                              }).then(res => {
                                if (res.data.success) {
                                  setVideoTabs(prev => prev.map(t => t.id === tabId ? { ...t, refVideos: t.refVideos.map(v => v.uid === uid ? { ...v, url: res.data.url, filepath: res.data.filepath, progress: 100, uploading: false } : v) } : t))
                                }
                              }).catch(() => {
                                setVideoTabs(prev => prev.map(t => t.id === tabId ? { ...t, refVideos: t.refVideos.filter(v => v.uid !== uid) } : t))
                              })
                            })
                            e.target.value = ''
                          }} />
                        </label>
                      )}
                    </div>
                  </div>
                  {/* REF AUDIOS (max 3) */}
                  <div className="flex flex-col min-w-[100px]">
                    <span className="mb-1.5 text-xs text-nexus-text">音频（最多 3 个）</span>
                    <div className="flex-grow flex gap-1.5 flex-wrap items-start">
                      {activeTab.refAudios.map((aud, i) => (
                        <div key={i} className="w-14 h-14 relative group rounded overflow-hidden border border-nexus-border shrink-0 bg-[#111] flex items-center justify-center">
                          <AudioLines size={15} className="text-nexus-cyan" />
                          <span className="absolute bottom-0.5 text-[8px] font-mono text-nexus-text truncate w-full text-center">{(aud.file?.name || aud.name || 'audio').slice(0,6)}</span>
                          <button aria-label={`删除参考音频 ${i + 1}`} title="删除" onClick={() => updateTab(activeTab.id, { refAudios: activeTab.refAudios.filter((_, j) => j !== i) })}
                            className="absolute right-0.5 top-0.5 rounded bg-black/75 p-0.5 text-white transition-colors hover:bg-nexus-red">
                            <X size={8} />
                          </button>
                        </div>
                      ))}
                      {activeTab.refAudios.length < 3 && (
                        <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-[10px] font-mono">
                          <Plus size={14} />
                          <input aria-label="上传参考音频" type="file" accept="audio/wav,audio/mp3,audio/mpeg" multiple className="hidden" onChange={e => {
                            const files = Array.from(e.target.files).slice(0, 3 - activeTab.refAudios.length)
                            updateTab(activeTab.id, { refAudios: [...activeTab.refAudios, ...files.map(f => ({ file: f, name: f.name }))] })
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
                    const hasVid = activeTab.refVideos.filter(v => v.url).length > 0
                    const fast = activeTab.fast
                    const res = activeTab.resolution
                    const dur = activeTab.duration === -1 ? 8 : activeTab.duration
                    // 像素值 (16:9 为基准，adaptive 按 16:9 估算)
                    const pxMap = { '480p': [864, 496], '720p': [1280, 720], '1080p': [1920, 1080] }
                    const [w, h] = pxMap[res] || pxMap['720p']
                    const fps = 24
                    const inputVidDur = hasVid ? 5 : 0 // 估算输入视频 5 秒
                    const tokens = (inputVidDur + dur) * w * h * fps / 1024
                    // 单价 (元/百万token)
                    let unitPrice
                    if (fast) {
                      unitPrice = hasVid ? 22 : 37
                    } else {
                      if (res === '1080p') unitPrice = hasVid ? 31 : 51
                      else unitPrice = hasVid ? 28 : 46
                    }
                    const price = (tokens / 1000000 * unitPrice).toFixed(2)
                    return (<>
                      <div className="text-2xl font-mono text-nexus-green">¥{price}</div>
                      <div className="text-xs font-mono text-nexus-text leading-5 opacity-80">
                        <div>{fast ? 'Seedance 2.0 Fast' : 'Seedance 2.0'}</div>
                        <div>{w}×{h} · {dur}s · {fps}fps</div>
                        <div>{hasVid ? '含参考视频' : '无参考视频'}</div>
                        <div className="mt-1 opacity-50">≈{(tokens/10000).toFixed(1)}万 tokens</div>
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

      {/* 右侧抽屉：视频提示词助手 */}
      <AnimatePresence>
        {showVideoPromptAgent && appMode === 'video' && (
          <motion.aside
            initial={{ x: '100%', opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: '100%', opacity: 0 }}
            transition={{ type: 'spring', damping: 28, stiffness: 260 }}
            className="agent-drawer liquid-glass-strong absolute bottom-0 right-0 top-0 z-50 flex flex-col"
          >
            <div className="glass-drawer-header flex h-12 shrink-0 items-center justify-between px-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-nexus-text-light">
                <Bot size={15} className="text-nexus-violet" /> 提示词助手
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={resetVideoPromptAgent}
                  disabled={videoPromptAgentLoading}
                  className="btn-base min-h-8 px-2 text-xs text-nexus-text hover:bg-nexus-surface hover:text-nexus-text-light"
                >
                  重置
                </button>
                <IconButton label="关闭提示词助手" onClick={() => setShowVideoPromptAgent(false)}><X size={16} /></IconButton>
              </div>
            </div>

            <div className="flex-grow min-h-0 overflow-y-auto custom-scrollbar p-4 space-y-3 bg-nexus-bg/30">
              {videoPromptAgentMessages.length === 0 && !videoPromptAgentLoading && (
                <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-sm text-nexus-muted">
                  <Bot size={28} className="opacity-40" />
                  <span>暂无对话</span>
                </div>
              )}
              {videoPromptAgentMessages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[88%] rounded-md border px-3 py-2.5 text-sm leading-5 whitespace-pre-wrap break-words ${
                    msg.role === 'user'
                      ? 'border-nexus-blue/35 bg-nexus-blue/10 text-nexus-text-light'
                      : 'border-nexus-border bg-nexus-surface text-nexus-text-light'
                  }`}>
                    {msg.content}
                  </div>
                </div>
              ))}
              {videoPromptAgentLoading && (
                <div className="flex justify-start">
                  <div className="flex items-center gap-2 rounded-md border border-nexus-border bg-nexus-surface px-3 py-2 text-xs text-nexus-text">
                    <Cpu size={12} className="animate-pulse text-nexus-violet" /> 分析中
                  </div>
                </div>
              )}
            </div>

            {videoPromptAgentDraft && (
              <div className="shrink-0 border-t border-nexus-border bg-nexus-panel p-3">
                <div className="mb-2 text-xs font-medium text-nexus-text">建议提示词</div>
                <div className="max-h-28 overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-nexus-border bg-nexus-bg p-2.5 text-sm leading-5 text-nexus-text-light custom-scrollbar">
                  {videoPromptAgentDraft}
                </div>
                <button
                  onClick={applyVideoPromptAgentDraft}
                  className="btn-base btn-primary mt-2 w-full text-xs"
                >
                  <Check size={13} /> 应用提示词
                </button>
              </div>
            )}

            <form
              onSubmit={(e) => {
                e.preventDefault()
                if (!videoPromptAgentInput.trim() || videoPromptAgentLoading) return
                sendVideoPromptAgentMessage(videoPromptAgentInput)
              }}
              className="shrink-0 border-t border-nexus-border bg-nexus-panel p-3"
            >
              <div className="flex gap-2">
                <textarea
                  value={videoPromptAgentInput}
                  onChange={e => setVideoPromptAgentInput(e.target.value)}
                  aria-label="给提示词助手发送消息"
                  disabled={videoPromptAgentLoading}
                  rows={3}
                  className="min-w-0 flex-grow resize-none rounded-md border border-nexus-border bg-nexus-bg px-3 py-2 text-sm leading-5 text-nexus-text-light outline-none focus:border-nexus-blue custom-scrollbar disabled:opacity-50"
                  placeholder="补充要求或回复问题..."
                />
                <button
                  type="submit"
                  aria-label="发送消息"
                  title="发送"
                  disabled={videoPromptAgentLoading || !videoPromptAgentInput.trim()}
                  className="icon-button h-auto w-10 border-nexus-border bg-nexus-surface hover:text-nexus-violet"
                >
                  <Send size={14} />
                </button>
              </div>
            </form>
          </motion.aside>
        )}
      </AnimatePresence>

      </main>

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
