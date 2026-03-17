import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import TextToImage from './components/TextToImage'
import ImageToImage from './components/ImageToImage'
import ResultDisplay from './components/ResultDisplay'
import PromptCollection from './components/PromptCollection'
import { motion, AnimatePresence } from 'framer-motion'
import ReactDOM from 'react-dom'
import { Play, Square, Settings, Cpu, HardDrive, Share2, Layers, Grid3X3, ArrowRight, Database, X, Menu, Maximize2, Save } from 'lucide-react'

function App() {
  const [isLoading, setIsLoading] = useState(false)
  const [generatedImages, setGeneratedImages] = useState([])
  const [thinkingText, setThinkingText] = useState('')
  const [error, setError] = useState(null)
  const [errorType, setErrorType] = useState(null)
  const [errorDetails, setErrorDetails] = useState(null)

  const [chatMode, setChatMode] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const [showPromptCollection, setShowPromptCollection] = useState(false)

  const [apiProvider, setApiProvider] = useState('vertex')
  const [apiProviders, setApiProviders] = useState(null)
  const [currentModel, setCurrentModel] = useState('gemini-3.1-flash-image-preview')
  const [availableModels, setAvailableModels] = useState([])

  const [prompt, setPrompt] = useState('')
  const [aspectRatio, setAspectRatio] = useState('1:1')
  const [resolution, setResolution] = useState('1K')
  const [useSearch, setUseSearch] = useState(false)
  const [thinkLevel, setThinkLevel] = useState('minimal')
  const [uploadedImages, setUploadedImages] = useState([])
  const [showFullEditor, setShowFullEditor] = useState(false)
  const [showEditorVault, setShowEditorVault] = useState(false)

  // 恢复原来的所有比例和分辨率选项
  const aspectRatios = ['1:1', '1:4', '4:1', '1:8', '8:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9']
  const resolutions = ['0.5K', '1K', '2K', '4K']

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
        setApiProviders(response.data.providers)
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
    const newProvider = apiProvider === 'vertex' ? 'ai_studio' : 'vertex'
    try {
      const response = await axios.post('/api/provider', { provider: newProvider })
      if (response.data.success) {
        setApiProvider(newProvider)
      }
    } catch (error) { alert('切换失败: ' + (error.response?.data?.error || error.message)) }
  }
  
  const handleSavePrompt = async () => {
    if (!prompt || !prompt.trim()) return alert('Empty prompt')
    try {
      const response = await axios.post('/api/prompts', { text: prompt.trim() })
      if (response.data.success) alert('Saved to vault')
      else alert('Failed to save')
    } catch (e) { alert('Failed to save') }
  }

  const handleGenerate = async () => {
    if (!prompt.trim()) return

    setIsLoading(true)
    setError(null)
    setErrorType(null)
    setErrorDetails(null)
    
    if (!chatMode) {
      setGeneratedImages([])
      setThinkingText('')
    }

    try {
      if (uploadedImages.length === 0) {
        const response = await axios.post('/api/generate', {
          prompt, aspect_ratio: aspectRatio, resolution, use_search: useSearch, enable_chat: chatMode, session_id: sessionId, think_level: thinkLevel
        })
        handleResponse(response.data)
      } else {
        const formData = new FormData()
        formData.append('prompt', prompt)
        formData.append('aspect_ratio', aspectRatio)
        formData.append('resolution', resolution)
        formData.append('use_search', useSearch)
        formData.append('enable_chat', chatMode)
        formData.append('think_level', thinkLevel)
        if (sessionId) formData.append('session_id', sessionId)
        uploadedImages.forEach((img) => formData.append('images', img.file))
        
        const response = await axios.post('/api/generate', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        })
        handleResponse(response.data)
      }
    } catch (err) {
      const errorData = err.response?.data || {}
      setError(errorData.error || err.message || '生成失败')
      setErrorType(errorData.error_type)
      setErrorDetails(errorData.error_details)
    } finally {
      setIsLoading(false)
    }
  }

  const handleResponse = (data) => {
    if (data.success) {
      setGeneratedImages(data.images || [])
      setThinkingText(data.thinking)
      if (chatMode && data.session_id) setSessionId(data.session_id)
      if (chatMode) setPrompt('')
    } else {
      setError(data.error || '生成失败')
      setErrorType(data.error_type)
      setErrorDetails(data.error_details)
    }
  }

  // 左侧面板拖拽调整宽度
  const [panelWidth, setPanelWidth] = useState(480)
  const isDragging = useRef(false)

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
        </div>
        <div className="flex items-center gap-6 text-sm font-mono">
          <button onClick={switchModel} className="flex items-center gap-2 text-nexus-text hover:text-white transition-colors cursor-pointer group">
            <span className="w-2 h-2 rounded-full bg-nexus-green shadow-[0_0_8px_#10b981]"></span>
            GPU: <span className="group-hover:text-nexus-green transition-colors">{currentModel.includes('flash') ? 'FLASH_3.1_CLUSTER' : 'PRO_3.0_CLUSTER'}</span>
          </button>
          <button onClick={switchApiProvider} className="flex items-center gap-2 text-nexus-text hover:text-white transition-colors cursor-pointer group">
            <Database size={12} className="group-hover:text-nexus-green transition-colors" />
            NODE: <span className="group-hover:text-nexus-green transition-colors">{apiProvider === 'vertex' ? 'VERTEX_AI' : 'AI_STUDIO'}</span>
          </button>
          <button onClick={() => setShowPromptCollection(!showPromptCollection)} className={`flex items-center gap-2 transition-colors cursor-pointer group ${showPromptCollection ? 'text-nexus-green' : 'text-nexus-text hover:text-white'}`}>
            <HardDrive size={14} className="group-hover:text-nexus-green transition-colors" /> VAULT
          </button>
        </div>
      </header>

      {/* 主工作区 */}
      <main className="flex-grow flex min-h-0 relative">
        
        {/* 左侧：代码编辑器风格的输入区 */}
        <div style={{ width: panelWidth }} className="shrink-0 border-r border-nexus-border flex flex-col bg-nexus-bg relative z-40 overflow-hidden">
          
          {/* 编辑器标签页 */}
          <div className="flex border-b border-nexus-border text-sm font-mono">
            <div 
              onDoubleClick={() => setShowFullEditor(true)}
              className="px-4 py-3 flex items-center gap-2 border-b-2 border-nexus-green text-white cursor-pointer"
            >
              <Cpu size={14} className="text-nexus-green" />
              prompt.nxs
            </div>
          </div>

          {/* 编辑器主体 */}
          <div className="flex-grow flex flex-col min-h-0 relative z-10">
            <TextToImage 
              prompt={prompt} setPrompt={setPrompt}
              isGenerating={isLoading} chatMode={chatMode} 
              onSavePrompt={handleSavePrompt}
            />
          </div>

          {/* 执行按钮区 */}
          <div className="p-4 border-t border-nexus-border bg-nexus-bg z-10">
            <button
              onClick={handleGenerate}
              disabled={isLoading || !prompt.trim()}
              className="w-full py-4 px-6 rounded-lg bg-[#1a1a1a] hover:bg-[#222] border border-[#333] hover:border-nexus-green transition-all flex items-center justify-center gap-3 text-sm font-mono tracking-widest disabled:opacity-50 disabled:cursor-not-allowed group"
            >
              {isLoading ? (
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
              isLoading={isLoading} generatedImages={generatedImages} thinkingText={thinkingText}
              error={error} errorType={errorType} errorDetails={errorDetails}
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
                   value={aspectRatio} onChange={e => setAspectRatio(e.target.value)}
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
                     value={resolution} onChange={e => setResolution(e.target.value)}
                     className="bg-transparent border-b border-nexus-border text-sm font-mono text-white outline-none cursor-pointer"
                   >
                     {resolutions.map((res) => (
                       <option key={res} value={res} className="bg-nexus-bg">{res}</option>
                     ))}
                   </select>
                 </div>
                 <div className="flex items-center justify-between">
                   <span className="text-sm font-mono text-nexus-text">USE_SEARCH</span>
                   <button 
                     onClick={() => setUseSearch(!useSearch)}
                     className={`w-8 h-4 rounded-full relative transition-colors ${useSearch ? 'bg-nexus-green' : 'bg-[#333]'}`}
                   >
                     <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${useSearch ? 'left-[18px]' : 'left-[2px]'}`}></div>
                   </button>
                 </div>
                 <div className="flex items-center justify-between">
                   <span className="text-sm font-mono text-nexus-text">CHAT_STATE</span>
                   <button 
                     onClick={() => setChatMode(!chatMode)}
                     className={`w-8 h-4 rounded-full relative transition-colors ${chatMode ? 'bg-nexus-green' : 'bg-[#333]'}`}
                   >
                     <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${chatMode ? 'left-[18px]' : 'left-[2px]'}`}></div>
                   </button>
                 </div>
                 <div className="flex items-center justify-between">
                   <span className="text-sm font-mono text-nexus-text">THINK</span>
                   <select
                     value={thinkLevel} onChange={e => setThinkLevel(e.target.value)}
                     className="bg-transparent border-b border-nexus-border text-sm font-mono text-white outline-none cursor-pointer"
                   >
                     <option value="minimal" className="bg-nexus-bg">Minimal</option>
                     <option value="high" className="bg-nexus-bg">High</option>
                   </select>
                 </div>
              </div>
            </div>

            {/* SOURCE NODE (Moved to the right) */}
            <div className="min-w-[260px] shrink-0 flex flex-col border-l border-nexus-border pl-6">
              <div className="flex items-center gap-2 text-sm font-mono text-nexus-text mb-3 tracking-widest uppercase">
                <HardDrive size={12} /> SOURCE NODE
              </div>
              <div className="flex-grow min-h-0">
                 <ImageToImage uploadedImages={uploadedImages} setUploadedImages={setUploadedImages} />
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
                <PromptCollection theme="dark" onSelectPrompt={(p) => { setPrompt(p); setShowPromptCollection(false); }} />
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
                  <span className="tracking-widest">prompt.nxs</span>
                  <span className="text-nexus-text/40 ml-2">— FULLSCREEN EDITOR</span>
                </div>
                <div className="flex items-center gap-3">
                  <button onClick={() => setShowEditorVault(!showEditorVault)} className={`flex items-center gap-2 transition-colors p-1 hover:bg-white/10 rounded ${showEditorVault ? 'text-nexus-green' : 'text-nexus-text hover:text-nexus-green'}`}>
                    <HardDrive size={14} /> <span className="text-xs tracking-widest">VAULT</span>
                  </button>
                  <button onClick={handleSavePrompt} disabled={!prompt.trim()} className="flex items-center gap-2 text-nexus-text hover:text-nexus-green transition-colors p-1 hover:bg-white/10 rounded disabled:opacity-30">
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
                  {Array.from({ length: Math.max(50, prompt.split('\n').length) }, (_, i) => (
                    <div key={i} className="h-6 leading-6">{i + 1}</div>
                  ))}
                </div>
                {/* 输入区 */}
                <textarea
                  autoFocus
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  className="flex-grow bg-transparent text-[#2ecc71] text-sm font-mono leading-6 p-4 outline-none resize-none whitespace-pre-wrap break-words overflow-y-auto selection:bg-[#2ecc71]/20 selection:text-white custom-scrollbar"
                  spellCheck="false"
                  placeholder="Enter your prompt here..."
                />
                {/* Vault 侧边栏 */}
                {showEditorVault && (
                  <div className="w-[350px] shrink-0 border-l border-nexus-border bg-[#0a0a0a] flex flex-col overflow-hidden">
                    <PromptCollection theme="dark" onSelectPrompt={(p) => setPrompt(p)} />
                  </div>
                )}
              </div>

              {/* 底栏 */}
              <div className="h-8 border-t border-nexus-border flex items-center px-4 bg-[#0a0a0a] shrink-0 text-xs font-mono text-nexus-text/50 gap-4">
                <span>Lines: {prompt.split('\n').length}</span>
                <span>Chars: {prompt.length}</span>
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

export default App