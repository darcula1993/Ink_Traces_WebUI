import React, { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import TextToImage from './components/TextToImage'
import ImageToImage from './components/ImageToImage'
import ResultDisplay from './components/ResultDisplay'
import VideoResultDisplay from './components/VideoResultDisplay'
import PromptCollection from './components/PromptCollection'
import TaskHistory from './components/TaskHistory'
import { motion, AnimatePresence } from 'framer-motion'
import ReactDOM from 'react-dom'
import { Play, Square, Settings, Cpu, HardDrive, Grid3X3, Database, X, Maximize2, Save, Film, Clock, LogOut } from 'lucide-react'
import { useLocalStorage } from './lib/useLocalStorage'

axios.defaults.withCredentials = true

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
    <div className="min-h-screen bg-nexus-bg flex items-center justify-center">
      <form onSubmit={handleSubmit} className="w-80 p-6 border border-nexus-border rounded-lg bg-[#0a0a0a]">
        <div className="text-center mb-6">
          <span className="text-nexus-green font-mono text-lg">&gt;</span>
          <span className="text-white font-mono text-lg ml-2">Ink_Traces_WebUI</span>
        </div>
        <input name="username" placeholder="Username" autoFocus
          className="w-full mb-3 px-3 py-2 bg-transparent border border-nexus-border rounded text-white font-mono text-sm outline-none focus:border-nexus-green" />
        <input name="password" type="password" placeholder="Password"
          className="w-full mb-4 px-3 py-2 bg-transparent border border-nexus-border rounded text-white font-mono text-sm outline-none focus:border-nexus-green" />
        {error && <div className="text-red-400 text-xs font-mono mb-3">{error}</div>}
        <button type="submit" className="w-full py-2 bg-nexus-green/10 border border-nexus-green/30 rounded text-nexus-green font-mono text-sm hover:bg-nexus-green/20 transition-colors">
          LOGIN
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
  const [showTaskQueue, setShowTaskQueue] = useState(false)
  const [showFullEditor, setShowFullEditor] = useState(false)
  const [showEditorVault, setShowEditorVault] = useState(false)

  const [apiProvider, setApiProvider] = useState('vertex')
  const [currentModel, setCurrentModel] = useState('gemini-3.1-flash-image-preview')
  const [availableModels, setAvailableModels] = useState([])

  // 图片多标签页系统
  const makeImgTab = (id) => ({
    id, prompt: '', aspectRatio: '1:1', resolution: '1K', useSearch: false, thinkLevel: 'minimal',
    chatMode: false, sessionId: null, uploadedImages: [],
    loading: false, generatedImages: [], thinkingText: '', error: null, errorType: null, errorDetails: null
  })

  const [imgTabs, setImgTabs] = useLocalStorage('img_tabs', [makeImgTab(1)])
  const [activeImgTabId, setActiveImgTabId] = useLocalStorage('img_activeTab', 1)
  const nextImgTabId = useRef(Math.max(...(imgTabs || [{ id: 1 }]).map(t => t.id)) + 1)

  const activeImgTab = imgTabs.find(t => t.id === activeImgTabId) || imgTabs[0] || makeImgTab(1)

  const updateImgTab = useCallback((id, updates) => {
    setImgTabs(prev => prev.map(t => t.id === id ? { ...t, ...updates } : t))
  }, [setImgTabs])

  const addImgTab = () => {
    const id = nextImgTabId.current++
    setImgTabs(prev => [...prev, makeImgTab(id)])
    setActiveImgTabId(id)
  }

  const closeImgTab = (id) => {
    setImgTabs(prev => {
      const remaining = prev.filter(t => t.id !== id)
      if (remaining.length === 0) {
        const newTab = makeImgTab(nextImgTabId.current++)
        setActiveImgTabId(newTab.id)
        return [newTab]
      }
      if (activeImgTabId === id) setActiveImgTabId(remaining[remaining.length - 1].id)
      return remaining
    })
  }

  // 顶部模式切换：image / video
  const [appMode, setAppMode] = useLocalStorage('appMode', 'image')

  // 视频 Provider
  const [videoProvider, setVideoProvider] = useLocalStorage('vid_provider', 'ark')

  // 视频多标签页系统
  const makeVideoTab = (id) => ({
    id, prompt: '', ratio: 'adaptive', duration: 5, resolution: '720p',
    fast: false, audio: true, returnLastFrame: false, mode: 'keyframe', search: false,
    firstFrame: null, lastFrame: null, refImages: [], refVideos: [], refAudios: [],
    loading: false, videoUrl: null, lastFrameUrl: null, progress: 0, eta: 0, error: null,
    taskId: null, taskProvider: null
  })

  const [videoTabs, setVideoTabs] = useLocalStorage('vid_tabs', [makeVideoTab(1)])
  const [activeVideoTabId, setActiveVideoTabId] = useLocalStorage('vid_activeTab', 1)
  const nextTabId = useRef(Math.max(...(videoTabs || [{ id: 1 }]).map(t => t.id)) + 1)

  const activeTab = videoTabs.find(t => t.id === activeVideoTabId) || videoTabs[0] || makeVideoTab(1)

  const updateTab = useCallback((id, updates) => {
    setVideoTabs(prev => prev.map(t => t.id === id ? { ...t, ...updates } : t))
  }, [setVideoTabs])
  const videoPollTimers = useRef(new Map())
  const unmountedRef = useRef(false)

  useEffect(() => () => {
    unmountedRef.current = true
    videoPollTimers.current.forEach(timer => clearTimeout(timer))
    videoPollTimers.current.clear()
  }, [])

  const addVideoTab = () => {
    const id = nextTabId.current++
    setVideoTabs(prev => [...prev, makeVideoTab(id)])
    setActiveVideoTabId(id)
  }

  const closeVideoTab = (id) => {
    setVideoTabs(prev => {
      const remaining = prev.filter(t => t.id !== id)
      if (remaining.length === 0) {
        const newTab = makeVideoTab(nextTabId.current++)
        setActiveVideoTabId(newTab.id)
        return [newTab]
      }
      if (activeVideoTabId === id) setActiveVideoTabId(remaining[remaining.length - 1].id)
      return remaining
    })
  }

  // 恢复原来的所有比例和分辨率选项
  const aspectRatios = ['1:1', '1:4', '4:1', '1:8', '8:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9']
  const resolutions = apiProvider === 'ark' ? ['2K', '3K'] : ['0.5K', '1K', '2K', '4K']
  const isArk = apiProvider === 'ark'

  // 切换 provider 时自动修正不兼容的分辨率
  useEffect(() => {
    const valid = apiProvider === 'ark' ? ['2K', '3K'] : ['0.5K', '1K', '2K', '4K']
    if (!valid.includes(activeImgTab.resolution)) {
      updateImgTab(activeImgTab.id, { resolution: '2K' })
    }
  }, [apiProvider])

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
    } catch (error) { alert('切换失败: ' + (error.response?.data?.error || error.message)) }
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
    } catch (error) { alert('切换失败: ' + (error.response?.data?.error || error.message)) }
  }
  
  const switchVideoProvider = async () => {
    const newProvider = videoProvider === 'jiekou' ? 'ark' : 'jiekou'
    try {
      const response = await axios.post('/api/video/provider', { provider: newProvider })
      if (response.data.success) setVideoProvider(newProvider)
    } catch (error) { alert('切换失败: ' + (error.response?.data?.error || error.message)) }
  }

  const handleSavePrompt = async () => {
    const p = appMode === 'video' ? activeTab.prompt : activeImgTab.prompt
    if (!p || !p.trim()) return alert('Empty prompt')
    try {
      const response = await axios.post('/api/prompts', { text: p.trim() })
      if (response.data.success) alert('Saved to vault')
      else alert('Failed to save')
    } catch (e) { alert('Failed to save') }
  }

  const handleGenerate = async () => {
    const tab = activeImgTab
    if (!tab.prompt.trim()) return
    const requestModel = apiProvider === 'ark' ? undefined : currentModel

    updateImgTab(tab.id, { loading: true, error: null, errorType: null, errorDetails: null })
    if (!tab.chatMode) {
      updateImgTab(tab.id, { generatedImages: [], thinkingText: '' })
    }

    try {
      if (tab.uploadedImages.length === 0) {
        const response = await axios.post('/api/generate', {
          prompt: tab.prompt, aspect_ratio: tab.aspectRatio, resolution: tab.resolution,
          use_search: tab.useSearch, enable_chat: tab.chatMode, session_id: tab.sessionId,
          think_level: tab.thinkLevel, provider: apiProvider, model: requestModel
        })
        handleResponse(tab.id, response.data)
      } else {
        const formData = new FormData()
        formData.append('prompt', tab.prompt)
        formData.append('aspect_ratio', tab.aspectRatio)
        formData.append('resolution', tab.resolution)
        formData.append('use_search', tab.useSearch)
        formData.append('enable_chat', tab.chatMode)
        formData.append('think_level', tab.thinkLevel)
        formData.append('provider', apiProvider)
        if (requestModel) formData.append('model', requestModel)
        if (tab.sessionId) formData.append('session_id', tab.sessionId)
        const pendingFetches = []
        tab.uploadedImages.forEach((img) => {
          if (img.file) {
            formData.append('images', img.file)
          } else if (img.preview && img.preview.startsWith('data:')) {
            // Restored from localStorage — reconstruct from base64
            const [header, b64] = img.preview.split(',')
            const mime = header.match(/:(.*?);/)?.[1] || 'image/png'
            const bytes = atob(b64)
            const arr = new Uint8Array(bytes.length)
            for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i)
            formData.append('images', new Blob([arr], { type: mime }), img.name || 'image.png')
          } else if (img.preview) {
            // URL reference — fetch and append
            pendingFetches.push(
              ensureFetchOk(img.preview).then(blob => formData.append('images', blob, img.name || 'image.png'))
            )
          }
        })
        if (pendingFetches.length) await Promise.all(pendingFetches)
        
        const response = await axios.post('/api/generate', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        })
        handleResponse(tab.id, response.data)
      }
    } catch (err) {
      const errorData = err.response?.data || {}
      updateImgTab(tab.id, {
        error: errorData.error || err.message || '生成失败',
        errorType: errorData.error_type, errorDetails: errorData.error_details
      })
    } finally {
      updateImgTab(tab.id, { loading: false })
    }
  }

  const handleResponse = (tabId, data) => {
    if (data.success) {
      const updates = { generatedImages: data.images || [], thinkingText: data.thinking }
      if (data.session_id) updates.sessionId = data.session_id
      updateImgTab(tabId, updates)
    } else {
      updateImgTab(tabId, {
        error: data.error || '生成失败', errorType: data.error_type, errorDetails: data.error_details
      })
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

  // 视频生成
  const pollVideoTask = useCallback(async (tabId, taskId, provider) => {
    const pollProvider = provider || videoProvider
    const timerKey = `${tabId}:${taskId}`
    if (videoPollTimers.current.has(timerKey)) {
      clearTimeout(videoPollTimers.current.get(timerKey))
      videoPollTimers.current.delete(timerKey)
    }
    try {
      const resp = await axios.get('/api/video/task', { params: { task_id: taskId, provider: pollProvider } })
      if (unmountedRef.current) return
      const d = resp.data
      if (!d.success) { updateTab(tabId, { error: d.error, loading: false }); return }

      updateTab(tabId, { progress: d.progress || 0, eta: d.eta || 0 })

      if (d.status === 'TASK_STATUS_SUCCEED') {
        const updates = { loading: false, taskId: null, taskProvider: null }
        if (d.videos && d.videos.length > 0) {
          updates.videoUrl = d.videos[0].video_url
          if (d.images && d.images.length > 0) updates.lastFrameUrl = d.images[0].image_url
        } else {
          updates.error = '任务完成但未返回视频'
        }
        updateTab(tabId, updates)
      } else if (d.status === 'TASK_STATUS_FAILED') {
        updateTab(tabId, { loading: false, taskId: null, taskProvider: null, error: d.reason || '视频生成失败' })
      } else {
        const timer = setTimeout(() => pollVideoTask(tabId, taskId, pollProvider), 3000)
        videoPollTimers.current.set(timerKey, timer)
      }
    } catch (e) {
      if (unmountedRef.current) return
      updateTab(tabId, { error: e.message, loading: false })
    }
  }, [updateTab, videoProvider])

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

  // 页面加载时恢复所有未完成的视频任务轮询
  useEffect(() => {
    videoTabs.forEach(tab => {
      if (tab.taskId && !tab.videoUrl && !tab.error) {
        updateTab(tab.id, { loading: true })
        pollVideoTask(tab.id, tab.taskId, tab.taskProvider)
      } else if (tab.loading && !tab.taskId) {
        // 清除无效的 loading 状态（上次关闭页面时残留）
        updateTab(tab.id, { loading: false })
      }
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleVideoGenerate = async () => {
    const tab = activeTab
    if (!videoTabHasInput(tab)) return

    updateTab(tab.id, { loading: true, error: null, videoUrl: null, lastFrameUrl: null, progress: 0, eta: 0 })

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
          tab.refAudios.forEach(aud => formData.append('ref_audios', aud.file))
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

      if (resp.data.success && resp.data.task_id) {
        const taskProvider = resp.data.provider || videoProvider
        updateTab(tab.id, { taskId: resp.data.task_id, taskProvider })
        pollVideoTask(tab.id, resp.data.task_id, taskProvider)
      } else {
        updateTab(tab.id, { error: resp.data.error || '提交失败', loading: false })
      }
    } catch (e) {
      updateTab(tab.id, { error: e.response?.data?.error || e.message, loading: false })
    }
  }

  // 左侧面板拖拽调整宽度
  const [panelWidth, setPanelWidth] = useState(480)
  const isDragging = useRef(false)

  // 从 Task Queue 加载任务到主 UI
  const handleLoadTask = async (taskSummary) => {
    // 从详情接口获取完整数据
    let task = taskSummary
    try {
      const resp = await axios.get(`/api/tasks/${taskSummary.id}`)
      if (resp.data.success) task = resp.data.task
    } catch (e) { /* use summary as fallback */ }
    const result = task.result || {}
    const params = task.params || {}

    if (task.type === 'image') {
      const id = nextImgTabId.current++
      const restoredRefs = (result.local_refs || []).map((url, i) => ({ preview: url, name: `ref_${i}.png` }))
      const tab = {
        ...makeImgTab(id),
        prompt: task.prompt || '',
        aspectRatio: params.aspect_ratio || '1:1',
        resolution: params.resolution || '1K',
        useSearch: params.use_search || false,
        thinkLevel: params.think_level || 'minimal',
        uploadedImages: restoredRefs,
        generatedImages: result.local_images || result.images || [],
        thinkingText: result.thinking || '',
        error: task.status === 'failed' ? task.error : null
      }
      setImgTabs(prev => [...prev, tab])
      setActiveImgTabId(id)
      setAppMode('image')
    } else {
      const id = nextTabId.current++
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
        videoUrl: result.videos?.[0]?.video_url || result.local_video || null,
        lastFrameUrl: lastFrameSrc,
        error: task.status === 'failed' ? task.error : null
      }
      setVideoTabs(prev => [...prev, tab])
      setActiveVideoTabId(id)
      setAppMode('video')
    }
    setShowTaskQueue(false)
  }

  const handleDragStart = (e) => {
    e.preventDefault()
    isDragging.current = true
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    const onMove = (ev) => {
      if (!isDragging.current) return
      setPanelWidth(Math.min(700, Math.max(300, ev.clientX)))
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

  return (
    <div className="min-h-screen bg-nexus-bg text-nexus-text-light font-sans flex flex-col overflow-hidden selection:bg-nexus-green-dim selection:text-nexus-green relative">
      
      {/* 极简顶栏 */}
      <header className="h-10 border-b border-nexus-border flex items-center justify-between px-4 bg-nexus-bg z-50 shrink-0">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 text-sm font-mono text-nexus-text">
            <span className="text-nexus-green">&gt;</span>
            <span className="tracking-wide">Ink_Traces_WebUI v1.0.0</span>
          </div>
          <div className="flex items-center gap-1 ml-2">
            <button onClick={() => setAppMode('image')} className={`px-3 py-1 text-xs font-mono tracking-widest transition-colors rounded ${appMode === 'image' ? 'bg-nexus-green/10 text-nexus-green border border-nexus-green/30' : 'text-nexus-text hover:text-white'}`}>
              <Cpu size={11} className="inline mr-1.5 -mt-0.5" />IMAGE
            </button>
            <button onClick={() => setAppMode('video')} className={`px-3 py-1 text-xs font-mono tracking-widest transition-colors rounded ${appMode === 'video' ? 'bg-nexus-green/10 text-nexus-green border border-nexus-green/30' : 'text-nexus-text hover:text-white'}`}>
              <Film size={11} className="inline mr-1.5 -mt-0.5" />VIDEO
            </button>
          </div>
        </div>
        <div className="flex items-center gap-6 text-sm font-mono">
          <button onClick={switchModel} className="flex items-center gap-2 text-nexus-text hover:text-white transition-colors cursor-pointer group">
            <span className="w-2 h-2 rounded-full bg-nexus-green shadow-[0_0_8px_#10b981]"></span>
            GPU: <span className="group-hover:text-nexus-green transition-colors">{appMode === 'video' ? 'Seedance_2.0_Cluster' : apiProvider === 'ark' ? 'SEEDREAM_5.0_LITE' : currentModel.includes('flash') ? 'FLASH_3.1_CLUSTER' : 'PRO_3.0_CLUSTER'}</span>
          </button>
          <button onClick={appMode === 'video' ? switchVideoProvider : switchApiProvider} className="flex items-center gap-2 text-nexus-text hover:text-white transition-colors cursor-pointer group">
            <Database size={12} className="group-hover:text-nexus-green transition-colors" />
            NODE: <span className="group-hover:text-nexus-green transition-colors">{appMode === 'video' ? (videoProvider === 'ark' ? 'ARK' : 'JIEKOU') : apiProvider === 'vertex' ? 'VERTEX_AI' : apiProvider === 'ark' ? 'ARK_SEEDREAM' : 'AI_STUDIO'}</span>
          </button>
          <button onClick={() => setShowPromptCollection(!showPromptCollection)} className={`flex items-center gap-2 transition-colors cursor-pointer group ${showPromptCollection ? 'text-nexus-green' : 'text-nexus-text hover:text-white'}`}>
            <HardDrive size={14} className="group-hover:text-nexus-green transition-colors" /> VAULT
          </button>
          <button onClick={() => setShowTaskQueue(!showTaskQueue)} className={`flex items-center gap-2 transition-colors cursor-pointer group ${showTaskQueue ? 'text-nexus-green' : 'text-nexus-text hover:text-white'}`}>
            <Clock size={14} className="group-hover:text-nexus-green transition-colors" /> QUEUE
          </button>
          <button onClick={handleLogout} className="flex items-center gap-2 text-nexus-text hover:text-red-400 transition-colors cursor-pointer group">
            <LogOut size={14} />
          </button>
        </div>
      </header>

      {/* 主工作区 */}
      <main className="flex-grow flex min-h-0 relative">

      {appMode === 'image' ? (<>
        
        {/* 左侧：代码编辑器风格的输入区 */}
        <div style={{ width: panelWidth }} className="shrink-0 border-r border-nexus-border flex flex-col bg-nexus-bg relative z-40 overflow-hidden">
          
          {/* 图片标签页栏 */}
          <div className="flex border-b border-nexus-border text-sm font-mono overflow-x-auto custom-scrollbar shrink-0">
            {imgTabs.map(tab => (
              <div key={tab.id}
                onClick={() => setActiveImgTabId(tab.id)}
                onDoubleClick={() => setShowFullEditor(true)}
                className={`px-3 py-2.5 flex items-center gap-1.5 cursor-pointer shrink-0 border-b-2 transition-colors ${tab.id === activeImgTabId ? 'border-nexus-green text-white' : 'border-transparent text-nexus-text hover:bg-white/5'}`}
              >
                {tab.loading ? <div className="w-3 h-3 border border-nexus-green border-t-transparent rounded-full animate-spin" /> : <Cpu size={12} className={tab.id === activeImgTabId ? 'text-nexus-green' : ''} />}
                <span className="max-w-[80px] truncate text-xs">{tab.prompt ? tab.prompt.slice(0, 12) : `img_${tab.id}`}</span>
                {imgTabs.length > 1 && (
                  <button onClick={e => { e.stopPropagation(); closeImgTab(tab.id) }} className="ml-1 text-nexus-text hover:text-red-400 transition-colors">
                    <X size={10} />
                  </button>
                )}
              </div>
            ))}
            <button onClick={addImgTab} className="px-2 py-2.5 text-nexus-text hover:text-nexus-green transition-colors shrink-0">+</button>
          </div>

          {/* 编辑器主体 */}
          <div className="flex-grow flex flex-col min-h-0 relative z-10">
            <TextToImage 
              prompt={activeImgTab.prompt} setPrompt={v => updateImgTab(activeImgTab.id, { prompt: v })}
              isGenerating={activeImgTab.loading} chatMode={activeImgTab.chatMode} 
              onSavePrompt={handleSavePrompt}
            />
          </div>

          {/* 执行按钮区 */}
          <div className="p-4 border-t border-nexus-border bg-nexus-bg z-10">
            <button
              onClick={handleGenerate}
              disabled={activeImgTab.loading || !activeImgTab.prompt.trim()}
              className="w-full py-4 px-6 rounded-lg bg-[#1a1a1a] hover:bg-[#222] border border-[#333] hover:border-nexus-green transition-all flex items-center justify-center gap-3 text-sm font-mono tracking-widest disabled:opacity-50 disabled:cursor-not-allowed group"
            >
              {activeImgTab.loading ? (
                <><Square size={14} className="text-nexus-text animate-pulse" /> <span>EXECUTING...</span></>
              ) : (
                <><Play size={14} className="text-nexus-green group-hover:drop-shadow-[0_0_8px_#10b981]" fill="currentColor" /> <span className="text-white">EXECUTE RUN()</span></>
              )}
            </button>
          </div>

        </div>

        {/* 拖拽手柄 */}
        <div
          onMouseDown={handleDragStart}
          className="w-1 shrink-0 cursor-col-resize hover:bg-nexus-green/50 active:bg-nexus-green transition-colors z-50"
        />

        {/* 右侧：画布与控制台 (中间区域) */}
        <div className={`flex-grow flex flex-col min-w-0 bg-[#0f0f0f] relative p-4 gap-6 z-0 transition-all duration-300 ${showPromptCollection ? '' : ''}`}>
          
          <div className="absolute inset-0 bg-nexus-grid bg-nexus-grid-size opacity-20 pointer-events-none"></div>

          {/* 上部：输出终端画布 */}
          <div className="flex-grow min-h-0 panel-border relative flex flex-col overflow-hidden shadow-2xl z-10" style={{ height: 0 }}>
            <ResultDisplay
              isLoading={activeImgTab.loading} generatedImages={activeImgTab.generatedImages} thinkingText={activeImgTab.thinkingText}
              error={activeImgTab.error} errorType={activeImgTab.errorType} errorDetails={activeImgTab.errorDetails}
            />
          </div>

          {/* 下部：参数控制台 */}
          <div className="h-[240px] shrink-0 panel-border p-4 flex gap-6 overflow-x-auto z-10 custom-scrollbar">
            
            {/* GEOMETRY (宽高比) */}
            <div className="w-[160px] shrink-0 flex flex-col">
              <div className="flex items-center gap-2 text-sm font-mono text-nexus-text mb-3 tracking-widest uppercase">
                <Grid3X3 size={12} /> GEOMETRY
              </div>
              <div className="flex-grow">
                 <select 
                   value={activeImgTab.aspectRatio} onChange={e => updateImgTab(activeImgTab.id, { aspectRatio: e.target.value })}
                   className="w-full bg-transparent border-b border-nexus-border text-sm font-mono text-white outline-none cursor-pointer py-2"
                 >
                   {aspectRatios.map((ratio) => (
                     <option key={ratio} value={ratio} className="bg-nexus-bg">{ratio}</option>
                   ))}
                 </select>
                 <div className="mt-4 text-sm font-mono text-nexus-text opacity-50 text-center">
                    SELECT ASPECT RATIO
                 </div>
              </div>
            </div>

            {/* ENGINE PARAMS (分辨率和其他) */}
            <div className="w-[240px] shrink-0 flex flex-col border-l border-nexus-border pl-6">
              <div className="flex items-center gap-2 text-sm font-mono text-nexus-text mb-3 tracking-widest uppercase">
                <Settings size={12} /> ENGINE PARAMS
              </div>
              <div className="flex flex-col justify-between flex-grow gap-2">
                 <div className="flex items-center justify-between">
                   <span className="text-sm font-mono text-nexus-text">RESOLUTION</span>
                   <select 
                     value={activeImgTab.resolution} onChange={e => updateImgTab(activeImgTab.id, { resolution: e.target.value })}
                     className="bg-transparent border-b border-nexus-border text-sm font-mono text-white outline-none cursor-pointer"
                   >
                     {resolutions.map((res) => (
                       <option key={res} value={res} className="bg-nexus-bg">{res}</option>
                     ))}
                   </select>
                 </div>
                 {!isArk && (<>
                 <div className="flex items-center justify-between">
                   <span className="text-sm font-mono text-nexus-text">USE_SEARCH</span>
                   <button 
                     onClick={() => updateImgTab(activeImgTab.id, { useSearch: !activeImgTab.useSearch })}
                     className={`w-8 h-4 rounded-full relative transition-colors ${activeImgTab.useSearch ? 'bg-nexus-green' : 'bg-[#333]'}`}
                   >
                     <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${activeImgTab.useSearch ? 'left-[18px]' : 'left-[2px]'}`}></div>
                   </button>
                 </div>
                 <div className="flex items-center justify-between">
                   <span className="text-sm font-mono text-nexus-text">CHAT_STATE</span>
                   <button 
                     onClick={() => updateImgTab(activeImgTab.id, { chatMode: !activeImgTab.chatMode })}
                     className={`w-8 h-4 rounded-full relative transition-colors ${activeImgTab.chatMode ? 'bg-nexus-green' : 'bg-[#333]'}`}
                   >
                     <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${activeImgTab.chatMode ? 'left-[18px]' : 'left-[2px]'}`}></div>
                   </button>
                 </div>
                 <div className="flex items-center justify-between">
                   <span className="text-sm font-mono text-nexus-text">THINK</span>
                   <select
                     value={activeImgTab.thinkLevel} onChange={e => updateImgTab(activeImgTab.id, { thinkLevel: e.target.value })}
                     className="bg-transparent border-b border-nexus-border text-sm font-mono text-white outline-none cursor-pointer"
                   >
                     <option value="minimal" className="bg-nexus-bg">Minimal</option>
                     <option value="high" className="bg-nexus-bg">High</option>
                   </select>
                 </div>
                 </>)}
              </div>
            </div>

            {/* SOURCE NODE */}
            <div className="min-w-[260px] shrink-0 flex flex-col border-l border-nexus-border pl-6">
              <div className="flex items-center gap-2 text-sm font-mono text-nexus-text mb-3 tracking-widest uppercase">
                <HardDrive size={12} /> SOURCE NODE
              </div>
              <div className="flex-grow min-h-0">
                 <ImageToImage uploadedImages={activeImgTab.uploadedImages} setUploadedImages={v => updateImgTab(activeImgTab.id, { uploadedImages: v })} />
              </div>
            </div>

          </div>

        </div>

        {/* 右侧折叠边栏：Vault Storage */}
        <AnimatePresence>
          {showPromptCollection && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 320, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className="absolute right-0 top-0 bottom-0 border-l border-nexus-border bg-nexus-bg z-30 flex flex-col"
            >
              <div className="p-4 border-b border-nexus-border flex justify-between items-center shrink-0">
                <div className="flex items-center gap-2 font-mono text-sm text-white">
                  <HardDrive size={14} className="text-nexus-green" /> VAULT_STORAGE
                </div>
                <button onClick={() => setShowPromptCollection(false)} className="text-nexus-text hover:text-white transition-colors">
                  <X size={14} />
                </button>
              </div>
              <div className="flex-grow overflow-hidden relative">
                <PromptCollection theme="dark" onSelectPrompt={(p) => { updateImgTab(activeImgTab.id, { prompt: p }); setShowPromptCollection(false); }} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

      </>) : (
        /* ============ VIDEO MODE ============ */
        <>
          {/* 左侧：视频 Prompt 输入 */}
          <div style={{ width: panelWidth }} className="shrink-0 border-r border-nexus-border flex flex-col bg-nexus-bg relative z-40 overflow-hidden">
            {/* 视频标签页栏 */}
            <div className="flex border-b border-nexus-border text-sm font-mono overflow-x-auto custom-scrollbar shrink-0">
              {videoTabs.map(tab => (
                <div key={tab.id}
                  onClick={() => setActiveVideoTabId(tab.id)}
                  onDoubleClick={() => setShowFullEditor(true)}
                  className={`px-3 py-2.5 flex items-center gap-1.5 cursor-pointer shrink-0 border-b-2 transition-colors ${tab.id === activeVideoTabId ? 'border-nexus-green text-white' : 'border-transparent text-nexus-text hover:bg-white/5'}`}
                >
                  {tab.loading ? <div className="w-3 h-3 border border-nexus-green border-t-transparent rounded-full animate-spin" /> : <Film size={12} className={tab.id === activeVideoTabId ? 'text-nexus-green' : ''} />}
                  <span className="max-w-[80px] truncate text-xs">{tab.prompt ? tab.prompt.slice(0, 12) : `vid_${tab.id}`}</span>
                  {videoTabs.length > 1 && (
                    <button onClick={e => { e.stopPropagation(); closeVideoTab(tab.id) }} className="ml-1 text-nexus-text hover:text-red-400 transition-colors">
                      <X size={10} />
                    </button>
                  )}
                </div>
              ))}
              <button onClick={addVideoTab} className="px-2 py-2.5 text-nexus-text hover:text-nexus-green transition-colors shrink-0">+</button>
            </div>
            <div className="flex-grow flex flex-col min-h-0 relative z-10">
              <div className="flex-grow flex flex-col min-h-0 relative bg-nexus-bg">
                <div className="absolute top-4 left-4 text-xs font-mono text-nexus-text opacity-50 z-10 pointer-events-none">
                  // Describe your video<br/>
                </div>
                <div className="flex-grow min-h-0 relative mt-8 overflow-hidden">
                  <textarea
                    value={activeTab.prompt}
                    onChange={(e) => updateTab(activeTab.id, { prompt: e.target.value })}
                    disabled={activeTab.loading}
                    className="absolute inset-0 px-4 py-4 bg-transparent text-[#2ecc71] text-sm font-mono leading-6 outline-none resize-none whitespace-pre-wrap break-words overflow-y-auto selection:bg-[#2ecc71]/20 selection:text-white custom-scrollbar"
                    spellCheck="false"
                    placeholder="A cinematic drone shot over a futuristic city at sunset..."
                  />
                </div>
              </div>
            </div>
            <div className="p-4 border-t border-nexus-border bg-nexus-bg z-10">
              <button
                onClick={handleVideoGenerate}
                disabled={activeTab.loading || !videoTabHasInput(activeTab)}
                className="w-full py-4 px-6 rounded-lg bg-[#1a1a1a] hover:bg-[#222] border border-[#333] hover:border-nexus-green transition-all flex items-center justify-center gap-3 text-sm font-mono tracking-widest disabled:opacity-50 disabled:cursor-not-allowed group"
              >
                {activeTab.loading ? (
                  <><Square size={14} className="text-nexus-text animate-pulse" /> <span>RENDERING...</span></>
                ) : (
                  <><Play size={14} className="text-nexus-green group-hover:drop-shadow-[0_0_8px_#10b981]" fill="currentColor" /> <span className="text-white">RENDER VIDEO()</span></>
                )}
              </button>
            </div>
          </div>

          {/* 拖拽手柄 */}
          <div onMouseDown={handleDragStart} className="w-1 shrink-0 cursor-col-resize hover:bg-nexus-green/50 active:bg-nexus-green transition-colors z-50" />

          {/* 右侧：视频画布与参数 */}
          <div className="flex-grow flex flex-col min-w-0 bg-[#0f0f0f] relative p-4 gap-6 z-0">
            <div className="absolute inset-0 bg-nexus-grid bg-nexus-grid-size opacity-20 pointer-events-none"></div>

            {/* 视频输出 */}
            <div className="flex-grow min-h-0 panel-border relative flex flex-col overflow-hidden shadow-2xl z-10" style={{ height: 0 }}>
              <VideoResultDisplay
                isLoading={activeTab.loading} videoUrl={activeTab.videoUrl} lastFrameUrl={activeTab.lastFrameUrl}
                progress={activeTab.progress} error={activeTab.error} eta={activeTab.eta}
              />
            </div>

            {/* 视频参数控制台 */}
            <div className="h-[240px] shrink-0 panel-border p-4 flex gap-6 overflow-x-auto z-10 custom-scrollbar">

              {/* 生成模式 */}
              <div className="w-[180px] shrink-0 flex flex-col">
                <div className="flex items-center gap-2 text-sm font-mono text-nexus-text mb-3 tracking-widest uppercase">
                  <Grid3X3 size={12} /> 生成模式
                </div>
                <div className="flex flex-col justify-between flex-grow gap-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono text-nexus-text">RATIO</span>
                    <select value={activeTab.ratio} onChange={e => updateTab(activeTab.id, { ratio: e.target.value })}
                      className="bg-transparent border-b border-nexus-border text-sm font-mono text-white outline-none cursor-pointer">
                      {['adaptive','16:9','4:3','1:1','3:4','9:16','21:9'].map(r => (
                        <option key={r} value={r} className="bg-nexus-bg">{r}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono text-nexus-text">MODE</span>
                    <select value={activeTab.mode} onChange={e => updateTab(activeTab.id, { mode: e.target.value })}
                      className="bg-transparent border-b border-nexus-border text-sm font-mono text-white outline-none cursor-pointer">
                      <option value="keyframe" className="bg-nexus-bg">首尾帧</option>
                      <option value="reference" className="bg-nexus-bg">全能参考</option>
                    </select>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono text-nexus-text">SEARCH</span>
                    <button onClick={() => updateTab(activeTab.id, { search: !activeTab.search })}
                      className={`w-8 h-4 rounded-full relative transition-colors ${activeTab.search ? 'bg-nexus-green' : 'bg-[#333]'}`}>
                      <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${activeTab.search ? 'left-[18px]' : 'left-[2px]'}`}></div>
                    </button>
                  </div>
                </div>
              </div>

              {/* ENGINE PARAMS */}
              <div className="w-[240px] shrink-0 flex flex-col border-l border-nexus-border pl-6">
                <div className="flex items-center gap-2 text-sm font-mono text-nexus-text mb-3 tracking-widest uppercase">
                  <Settings size={12} /> ENGINE PARAMS
                </div>
                <div className="flex flex-col justify-between flex-grow gap-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono text-nexus-text">RESOLUTION</span>
                    <select value={activeTab.resolution} onChange={e => updateTab(activeTab.id, { resolution: e.target.value })}
                      className="bg-transparent border-b border-nexus-border text-sm font-mono text-white outline-none cursor-pointer">
                      <option value="480p" className="bg-nexus-bg">480p</option>
                      <option value="720p" className="bg-nexus-bg">720p</option>
                      <option value="1080p" className="bg-nexus-bg">1080p</option>
                    </select>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono text-nexus-text">DURATION</span>
                    <select value={activeTab.duration} onChange={e => updateTab(activeTab.id, { duration: Number(e.target.value) })}
                      className="bg-transparent border-b border-nexus-border text-sm font-mono text-white outline-none cursor-pointer">
                      {[4,5,6,7,8,9,10,11,12,13,14,15].map(d => (
                        <option key={d} value={d} className="bg-nexus-bg">{d}s</option>
                      ))}
                      <option value={-1} className="bg-nexus-bg">Auto</option>
                    </select>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono text-nexus-text">FAST_MODE</span>
                    <button onClick={() => updateTab(activeTab.id, { fast: !activeTab.fast })}
                      className={`w-8 h-4 rounded-full relative transition-colors ${activeTab.fast ? 'bg-nexus-green' : 'bg-[#333]'}`}>
                      <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${activeTab.fast ? 'left-[18px]' : 'left-[2px]'}`}></div>
                    </button>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono text-nexus-text">AUDIO</span>
                    <button onClick={() => updateTab(activeTab.id, { audio: !activeTab.audio })}
                      className={`w-8 h-4 rounded-full relative transition-colors ${activeTab.audio ? 'bg-nexus-green' : 'bg-[#333]'}`}>
                      <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${activeTab.audio ? 'left-[18px]' : 'left-[2px]'}`}></div>
                    </button>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono text-nexus-text">LAST_FRM</span>
                    <button onClick={() => updateTab(activeTab.id, { returnLastFrame: !activeTab.returnLastFrame })}
                      className={`w-8 h-4 rounded-full relative transition-colors ${activeTab.returnLastFrame ? 'bg-nexus-green' : 'bg-[#333]'}`}>
                      <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${activeTab.returnLastFrame ? 'left-[18px]' : 'left-[2px]'}`}></div>
                    </button>
                  </div>
                </div>
              </div>

              {/* KEYFRAMES / REFERENCE */}
              <div className="min-w-[300px] shrink-0 flex flex-col border-l border-nexus-border pl-6">
                <div className="flex items-center gap-2 text-sm font-mono text-nexus-text mb-3 tracking-widest uppercase">
                  <Film size={12} /> {activeTab.mode === 'keyframe' ? 'KEYFRAMES' : 'REFERENCE'}
                </div>

                {activeTab.mode === 'keyframe' ? (
                <div className="flex-grow flex gap-3">
                  <div className="w-[120px] flex flex-col">
                    <span className="text-[10px] font-mono text-nexus-text mb-1">FIRST FRAME</span>
                    {activeTab.firstFrame ? (
                      <div className="w-[120px] h-[120px] relative group rounded overflow-hidden border border-nexus-border">
                        <img src={activeTab.firstFrame.preview} className="w-full h-full object-cover" alt="first" />
                        <button onClick={() => updateTab(activeTab.id, { firstFrame: null })}
                          className="absolute top-1 right-1 p-1 bg-red-900/80 text-red-400 rounded hover:bg-red-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity">
                          <X size={10} />
                        </button>
                      </div>
                    ) : (
                      <label className="w-[120px] h-[120px] border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-xs font-mono">
                        + IMG
                        <input type="file" accept="image/*" className="hidden" onChange={e => {
                          const f = e.target.files[0]; if (!f) return
                          const reader = new FileReader()
                          reader.onload = ev => updateTab(activeTab.id, { firstFrame: { file: f, preview: ev.target.result } })
                          reader.readAsDataURL(f)
                        }} />
                      </label>
                    )}
                  </div>
                  <div className="w-[120px] flex flex-col">
                    <span className="text-[10px] font-mono text-nexus-text mb-1">LAST FRAME</span>
                    {activeTab.lastFrame ? (
                      <div className="w-[120px] h-[120px] relative group rounded overflow-hidden border border-nexus-border">
                        <img src={activeTab.lastFrame.preview} className="w-full h-full object-cover" alt="last" />
                        <button onClick={() => updateTab(activeTab.id, { lastFrame: null })}
                          className="absolute top-1 right-1 p-1 bg-red-900/80 text-red-400 rounded hover:bg-red-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity">
                          <X size={10} />
                        </button>
                      </div>
                    ) : (
                      <label className="w-[120px] h-[120px] border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-xs font-mono">
                        + IMG
                        <input type="file" accept="image/*" className="hidden" onChange={e => {
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
                    <span className="text-[10px] font-mono text-nexus-text mb-1">IMAGES (max 9)</span>
                    <div className="flex-grow flex gap-1.5 flex-wrap items-start">
                      {activeTab.refImages.map((img, i) => (
                        <div key={i} className="w-14 h-14 relative group rounded overflow-hidden border border-nexus-border shrink-0">
                          <img src={img.preview} className="w-full h-full object-cover" alt="" />
                          <button onClick={() => updateTab(activeTab.id, { refImages: activeTab.refImages.filter((_, j) => j !== i) })}
                            className="absolute top-0.5 right-0.5 p-0.5 bg-red-900/80 text-red-400 rounded hover:bg-red-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity">
                            <X size={8} />
                          </button>
                        </div>
                      ))}
                      {activeTab.refImages.length < 9 && (
                        <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-[10px] font-mono">
                          +
                          <input type="file" accept="image/*" multiple className="hidden" onChange={e => {
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
                    <span className="text-[10px] font-mono text-nexus-text mb-1">VIDEOS (max 3)</span>
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
                          <button onClick={() => {
                              if (vid.url) {
                                axios.delete('/api/upload_video', { data: { url: vid.url } }).catch(() => {})
                              }
                              updateTab(activeTab.id, { refVideos: activeTab.refVideos.filter((_, j) => j !== i) })
                            }}
                            className="absolute top-0.5 right-0.5 p-0.5 bg-red-900/80 text-red-400 rounded hover:bg-red-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity">
                            <X size={8} />
                          </button>
                        </div>
                      ))}
                      {activeTab.refVideos.length < 3 && (
                        <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-[10px] font-mono">
                          +
                          <input type="file" accept="video/mp4,video/quicktime" multiple className="hidden" onChange={e => {
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
                    <span className="text-[10px] font-mono text-nexus-text mb-1">AUDIOS (max 3)</span>
                    <div className="flex-grow flex gap-1.5 flex-wrap items-start">
                      {activeTab.refAudios.map((aud, i) => (
                        <div key={i} className="w-14 h-14 relative group rounded overflow-hidden border border-nexus-border shrink-0 bg-[#111] flex items-center justify-center">
                          <span className="text-[10px] font-mono text-nexus-text">♪</span>
                          <span className="absolute bottom-0.5 text-[8px] font-mono text-nexus-text truncate w-full text-center">{aud.file.name.slice(0,6)}</span>
                          <button onClick={() => updateTab(activeTab.id, { refAudios: activeTab.refAudios.filter((_, j) => j !== i) })}
                            className="absolute top-0.5 right-0.5 p-0.5 bg-red-900/80 text-red-400 rounded hover:bg-red-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity">
                            <X size={8} />
                          </button>
                        </div>
                      ))}
                      {activeTab.refAudios.length < 3 && (
                        <label className="w-14 h-14 shrink-0 border border-dashed border-nexus-border rounded flex items-center justify-center text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors cursor-pointer text-[10px] font-mono">
                          +
                          <input type="file" accept="audio/wav,audio/mp3,audio/mpeg" multiple className="hidden" onChange={e => {
                            const files = Array.from(e.target.files).slice(0, 3 - activeTab.refAudios.length)
                            updateTab(activeTab.id, { refAudios: [...activeTab.refAudios, ...files.map(f => ({ file: f }))] })
                          }} />
                        </label>
                      )}
                    </div>
                  </div>
                </div>
                )}
              </div>

              {/* PRICE ESTIMATE */}
              <div className="w-[140px] shrink-0 flex flex-col border-l border-nexus-border pl-6">
                <div className="flex items-center gap-2 text-sm font-mono text-nexus-text mb-3 tracking-widest uppercase">
                  ¥ COST
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
                      <div className="text-[10px] font-mono text-nexus-text leading-4 opacity-70">
                        <div>{fast ? 'Seedance 2.0 Fast' : 'Seedance 2.0'}</div>
                        <div>{w}×{h} · {dur}s · {fps}fps</div>
                        <div>{hasVid ? '含参考视频' : '无参考视频'}</div>
                        <div className="mt-1 opacity-50">≈{(tokens/10000).toFixed(1)}万 tokens</div>
                      </div>
                    </>)
                  })()}
                </div>
              </div>

            </div>
          </div>
        </>
      )}

      {/* 右侧折叠边栏：Task Queue */}
      <AnimatePresence>
        {showTaskQueue && (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 360, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="absolute right-0 top-0 bottom-0 border-l border-nexus-border bg-nexus-bg z-30 flex flex-col"
          >
            <div className="p-4 border-b border-nexus-border flex justify-between items-center shrink-0">
              <div className="flex items-center gap-2 font-mono text-sm text-white">
                <Clock size={14} className="text-nexus-green" /> TASK_QUEUE
              </div>
              <button onClick={() => setShowTaskQueue(false)} className="text-nexus-text hover:text-white transition-colors">
                <X size={14} />
              </button>
            </div>
            <div className="flex-grow overflow-hidden relative">
              <TaskHistory onLoadTask={handleLoadTask} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      </main>

      {/* 全屏 Prompt 编辑器弹窗 */}
      {ReactDOM.createPortal(
        <AnimatePresence>
          {showFullEditor && (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/95 z-[999] flex flex-col backdrop-blur-sm"
            >
              {/* 标题栏 */}
              <div className="h-10 border-b border-nexus-border flex items-center justify-between px-4 bg-[#0a0a0a] shrink-0">
                <div className="flex items-center gap-2 text-sm font-mono text-nexus-text">
                  <Maximize2 size={14} className="text-nexus-green" />
                  <span className="tracking-widest">{appMode === 'video' ? 'video_prompt.nxs' : 'prompt.nxs'}</span>
                  <span className="text-nexus-text/40 ml-2">— FULLSCREEN EDITOR</span>
                </div>
                <div className="flex items-center gap-3">
                  <button onClick={() => setShowEditorVault(!showEditorVault)} className={`flex items-center gap-2 transition-colors p-1 hover:bg-white/10 rounded ${showEditorVault ? 'text-nexus-green' : 'text-nexus-text hover:text-nexus-green'}`}>
                    <HardDrive size={14} /> <span className="text-xs tracking-widest">VAULT</span>
                  </button>
                  <button onClick={handleSavePrompt} disabled={!(appMode === 'video' ? activeTab.prompt : activeImgTab.prompt).trim()} className="flex items-center gap-2 text-nexus-text hover:text-nexus-green transition-colors p-1 hover:bg-white/10 rounded disabled:opacity-30">
                    <Save size={14} /> <span className="text-xs tracking-widest">SAVE</span>
                  </button>
                  <button onClick={() => { setShowFullEditor(false); setShowEditorVault(false) }} className="text-nexus-text hover:text-white transition-colors p-1 hover:bg-white/10 rounded">
                    <X size={16} />
                  </button>
                </div>
              </div>

              {/* 编辑器主体 */}
              <div className="flex-grow flex min-h-0 relative">
                {/* 行号 */}
                <div className="w-14 shrink-0 border-r border-nexus-border/50 bg-[#0a0a0a] py-4 pr-3 font-mono text-xs text-[#555] select-none overflow-hidden text-right">
                  {Array.from({ length: Math.max(50, (appMode === 'video' ? activeTab.prompt : activeImgTab.prompt).split('\n').length) }, (_, i) => (
                    <div key={i} className="h-6 leading-6">{i + 1}</div>
                  ))}
                </div>
                {/* 输入区 */}
                <textarea
                  autoFocus
                  value={appMode === 'video' ? activeTab.prompt : activeImgTab.prompt}
                  onChange={(e) => appMode === 'video' ? updateTab(activeTab.id, { prompt: e.target.value }) : updateImgTab(activeImgTab.id, { prompt: e.target.value })}
                  className="flex-grow bg-transparent text-[#2ecc71] text-sm font-mono leading-6 p-4 outline-none resize-none whitespace-pre-wrap break-words overflow-y-auto selection:bg-[#2ecc71]/20 selection:text-white custom-scrollbar"
                  spellCheck="false"
                  placeholder="Enter your prompt here..."
                />
                {/* Vault 侧边栏 */}
                {showEditorVault && (
                  <div className="w-[350px] shrink-0 border-l border-nexus-border bg-[#0a0a0a] flex flex-col overflow-hidden">
                    <PromptCollection theme="dark" onSelectPrompt={(p) => appMode === 'video' ? updateTab(activeTab.id, { prompt: p }) : updateImgTab(activeImgTab.id, { prompt: p })} />
                  </div>
                )}
              </div>

              {/* 底栏 */}
              <div className="h-8 border-t border-nexus-border flex items-center px-4 bg-[#0a0a0a] shrink-0 text-xs font-mono text-nexus-text/50 gap-4">
                <span>Lines: {(appMode === 'video' ? activeTab.prompt : activeImgTab.prompt).split('\n').length}</span>
                <span>Chars: {(appMode === 'video' ? activeTab.prompt : activeImgTab.prompt).length}</span>
                <span className="ml-auto">ESC to close</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </div>
  )
}

export default AuthGate
