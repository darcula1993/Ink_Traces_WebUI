import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'
import { Group, Image as KonvaImage, Layer, Stage, Transformer } from 'react-konva'
import {
  BoxSelect, Download, Eye, EyeOff, FolderOpen, GripVertical, ImagePlus,
  Lock, LockOpen, Maximize, MousePointer2, Plus, Redo2, RotateCcw,
  Save, Sparkles, Trash2, Undo2, ZoomIn, ZoomOut,
} from 'lucide-react'
import CodeRainCanvas from './CodeRainCanvas'
import IconButton from './ui/IconButton'

const ACTIVE_STATUSES = new Set(['submitting', 'preparing', 'pending', 'processing', 'cancel_requested'])
const EMPTY_DOCUMENT = { canvas: { width: 1600, height: 900, background: 'transparent' }, layers: [], selected_layer_id: null }

function useLoadedImage(src) {
  const [image, setImage] = useState(null)
  useEffect(() => {
    if (!src) {
      setImage(null)
      return undefined
    }
    const next = new window.Image()
    next.onload = () => setImage(next)
    next.src = src
    return () => { next.onload = null }
  }, [src])
  return image
}

function CanvasLayer({ item, selected, interactive, onSelect, onChange, nodeRef }) {
  const image = useLoadedImage(item.local_url)
  if (!image || !item.visible) return null
  return (
    <KonvaImage
      id={`studio-layer-${String(item.id).replace(/[^a-zA-Z0-9_-]/g, '-')}`}
      ref={nodeRef}
      image={image}
      x={Number(item.x) || 0}
      y={Number(item.y) || 0}
      width={Math.max(1, Number(item.display_width) || image.width)}
      height={Math.max(1, Number(item.display_height) || image.height)}
      rotation={Number(item.rotation) || 0}
      opacity={Number(item.opacity) ?? 1}
      draggable={interactive && !item.locked}
      listening={interactive && (!item.locked || selected)}
      onClick={onSelect}
      onTap={onSelect}
      onDragEnd={event => onChange({ x: event.target.x(), y: event.target.y() })}
      onTransformEnd={event => {
        const node = event.target
        const scaleX = node.scaleX()
        const scaleY = node.scaleY()
        node.scaleX(1)
        node.scaleY(1)
        onChange({
          x: node.x(), y: node.y(), rotation: node.rotation(),
          display_width: Math.max(1, node.width() * scaleX),
          display_height: Math.max(1, node.height() * scaleY),
        })
      }}
    />
  )
}

function downloadDataUrl(dataUrl, filename) {
  const anchor = document.createElement('a')
  anchor.href = dataUrl
  anchor.download = filename
  anchor.click()
}

export default function LayerStudio({ notify }) {
  const [projects, setProjects] = useState([])
  const [project, setProject] = useState(null)
  const [documentState, setDocumentState] = useState(EMPTY_DOCUMENT)
  const [prompt, setPrompt] = useState('')
  const [size, setSize] = useState('auto')
  const [sourceFile, setSourceFile] = useState(null)
  const [sourcePreview, setSourcePreview] = useState('')
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saveState, setSaveState] = useState('saved')
  const [zoom, setZoom] = useState(1)
  const [tool, setTool] = useState('select')
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [viewport, setViewport] = useState({ width: 900, height: 600 })
  const [draggedLayerId, setDraggedLayerId] = useState(null)
  const viewportRef = useRef(null)
  const stageRef = useRef(null)
  const transformerRef = useRef(null)
  const layerNodes = useRef(new Map())
  const history = useRef([])
  const future = useRef([])

  const currentTask = project?.current_task
  const processing = Boolean(currentTask && ACTIVE_STATUSES.has(currentTask.status))
  const selectedLayer = documentState.layers.find(layer => layer.id === documentState.selected_layer_id) || null

  const loadProjects = useCallback(async () => {
    const response = await axios.get('/api/layer/projects')
    setProjects(response.data.projects || [])
  }, [])

  const openProject = useCallback(async (projectId, silent = false) => {
    const response = await axios.get(`/api/layer/projects/${projectId}`)
    const next = response.data.project
    setProject(next)
    setDocumentState(next.document?.layers ? next.document : EMPTY_DOCUMENT)
    if (!silent) {
      setPrompt(next.current_task?.prompt || '')
      setSize(next.current_task?.params?.size || 'auto')
      history.current = []
      future.current = []
      setDirty(false)
      setSaveState('saved')
    }
    return next
  }, [])

  useEffect(() => {
    loadProjects().catch(() => notify?.('Layer Studio 项目加载失败', 'error'))
  }, [loadProjects, notify])

  useEffect(() => {
    const element = viewportRef.current
    if (!element) return undefined
    const observer = new ResizeObserver(entries => {
      const rect = entries[0]?.contentRect
      if (rect) setViewport({ width: Math.max(1, rect.width), height: Math.max(1, rect.height) })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!project?.id || !processing) return undefined
    const timer = window.setInterval(async () => {
      try {
        const next = await openProject(project.id, true)
        if (!ACTIVE_STATUSES.has(next.current_task?.status)) {
          await loadProjects()
          if (next.current_task?.status === 'succeeded') notify?.('图层分解完成')
          if (next.current_task?.status === 'failed') notify?.(next.current_task.error || '图层分解失败', 'error')
        }
      } catch (_) {}
    }, 1800)
    return () => window.clearInterval(timer)
  }, [loadProjects, notify, openProject, processing, project?.id])

  useEffect(() => {
    const transformer = transformerRef.current
    const node = selectedLayer ? layerNodes.current.get(selectedLayer.id) : null
    if (transformer) {
      transformer.nodes(node && !selectedLayer.locked ? [node] : [])
      transformer.getLayer()?.batchDraw()
    }
  }, [selectedLayer, documentState.layers])

  useEffect(() => {
    if (!dirty || !project?.id) return undefined
    setSaveState('saving')
    const timer = window.setTimeout(async () => {
      try {
        const response = await axios.put(`/api/layer/projects/${project.id}`, {
          document: documentState,
          revision: project.document_revision,
        })
        setProject(current => ({ ...current, document_revision: response.data.project.document_revision }))
        setDirty(false)
        setSaveState('saved')
      } catch (error) {
        setSaveState('error')
        notify?.(error.response?.data?.error || '项目自动保存失败', 'error')
      }
    }, 500)
    return () => window.clearTimeout(timer)
  }, [dirty, documentState, notify, project?.document_revision, project?.id])

  useEffect(() => () => {
    if (sourcePreview?.startsWith('blob:')) URL.revokeObjectURL(sourcePreview)
  }, [sourcePreview])

  const commit = useCallback((updater) => {
    setDocumentState(current => {
      history.current.push(current)
      if (history.current.length > 60) history.current.shift()
      future.current = []
      return typeof updater === 'function' ? updater(current) : updater
    })
    setDirty(true)
  }, [])

  const updateLayer = useCallback((id, updates) => {
    commit(current => ({
      ...current,
      layers: current.layers.map(layer => layer.id === id ? { ...layer, ...updates } : layer),
    }))
  }, [commit])

  const undo = () => {
    const previous = history.current.pop()
    if (!previous) return
    future.current.push(documentState)
    setDocumentState(previous)
    setDirty(true)
  }

  const redo = () => {
    const next = future.current.pop()
    if (!next) return
    history.current.push(documentState)
    setDocumentState(next)
    setDirty(true)
  }

  const chooseSource = file => {
    if (!file || !String(file.type).startsWith('image/')) return
    if (sourcePreview?.startsWith('blob:')) URL.revokeObjectURL(sourcePreview)
    setSourceFile(file)
    setSourcePreview(URL.createObjectURL(file))
  }

  const createProject = async () => {
    if (!sourceFile) return notify?.('请先添加需要分解的 PNG 或 JPEG 图片', 'error')
    setBusy(true)
    try {
      const data = new FormData()
      data.append('image', sourceFile)
      data.append('name', sourceFile.name.replace(/\.[^.]+$/, ''))
      data.append('prompt', prompt)
      data.append('size', size)
      const response = await axios.post('/api/layer/projects', data)
      await loadProjects()
      await openProject(response.data.project_id)
      notify?.(`图层任务 #${response.data.task_id} 已创建`)
    } catch (error) {
      notify?.(error.response?.data?.error || '图层任务创建失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const decomposeAgain = async () => {
    if (!project?.id || processing) return
    setBusy(true)
    try {
      const response = await axios.post(`/api/layer/projects/${project.id}/decompose`, { prompt, size })
      await openProject(project.id, true)
      await loadProjects()
      notify?.(`新的分解版本 #${response.data.task_id} 已创建`)
    } catch (error) {
      notify?.(error.response?.data?.error || '重新分解失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const deleteProject = async () => {
    if (!project?.id || !window.confirm(`删除项目“${project.name}”？`)) return
    await axios.delete(`/api/layer/projects/${project.id}`)
    setProject(null)
    setDocumentState(EMPTY_DOCUMENT)
    await loadProjects()
  }

  const exportCanvas = async format => {
    const stage = stageRef.current
    if (!stage || documentState.layers.length === 0) return
    const oldScale = stage.scaleX()
    const oldPosition = stage.position()
    transformerRef.current?.visible(false)
    stage.scale({ x: 1, y: 1 })
    stage.position({ x: 0, y: 0 })
    const pngUrl = stage.toDataURL({
      x: 0, y: 0,
      width: documentState.canvas.width,
      height: documentState.canvas.height,
      pixelRatio: 1,
      mimeType: 'image/png',
    })
    stage.scale({ x: oldScale, y: oldScale })
    stage.position(oldPosition)
    transformerRef.current?.visible(true)
    transformerRef.current?.getLayer()?.batchDraw()
    if (format === 'png') {
      downloadDataUrl(pngUrl, `ink-traces-layer-${project.id}-${Date.now()}.png`)
      return
    }
    const image = new window.Image()
    image.onload = () => {
      const canvas = window.document.createElement('canvas')
      canvas.width = documentState.canvas.width
      canvas.height = documentState.canvas.height
      const context = canvas.getContext('2d')
      context.fillStyle = '#ffffff'
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.drawImage(image, 0, 0)
      downloadDataUrl(canvas.toDataURL('image/jpeg', 0.94), `ink-traces-layer-${project.id}-${Date.now()}.jpg`)
    }
    image.src = pngUrl
  }

  const fitScale = useMemo(() => Math.min(
    (viewport.width - 72) / Math.max(1, documentState.canvas.width),
    (viewport.height - 72) / Math.max(1, documentState.canvas.height),
  ), [documentState.canvas.height, documentState.canvas.width, viewport.height, viewport.width])
  const stageScale = Math.max(0.02, fitScale * zoom)
  const stagePosition = {
    x: (viewport.width - documentState.canvas.width * stageScale) / 2 + pan.x,
    y: (viewport.height - documentState.canvas.height * stageScale) / 2 + pan.y,
  }

  const reorderLayer = (sourceId, targetId) => {
    if (!sourceId || sourceId === targetId) return
    commit(current => {
      const layers = [...current.layers]
      const from = layers.findIndex(layer => layer.id === sourceId)
      const to = layers.findIndex(layer => layer.id === targetId)
      if (from < 0 || to < 0) return current
      const [moved] = layers.splice(from, 1)
      layers.splice(to, 0, moved)
      return { ...current, layers }
    })
  }

  return (
    <section className="layer-studio" data-testid="layer-studio">
      <header className="layer-studio-commandbar liquid-glass">
        <div className="layer-project-identity">
          <BoxSelect size={16} className="text-nexus-cyan" />
          <strong>{project?.name || 'Layer Studio'}</strong>
          {project && <span className={`layer-save-state state-${saveState}`}><Save size={11} />{saveState === 'saving' ? '保存中' : saveState === 'error' ? '保存失败' : '已保存'}</span>}
        </div>
        <div className="layer-command-tools">
          <IconButton label="撤销" onClick={undo} disabled={history.current.length === 0}><Undo2 size={15} /></IconButton>
          <IconButton label="重做" onClick={redo} disabled={future.current.length === 0}><Redo2 size={15} /></IconButton>
          <span className="layer-command-divider" />
          <IconButton label="缩小" onClick={() => setZoom(value => Math.max(0.25, value - 0.15))}><ZoomOut size={15} /></IconButton>
          <button type="button" className="layer-zoom-value" onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button>
          <IconButton label="放大" onClick={() => setZoom(value => Math.min(4, value + 0.15))}><ZoomIn size={15} /></IconButton>
          <IconButton label="适应画布" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }) }}><Maximize size={15} /></IconButton>
        </div>
        <div className="layer-export-actions">
          <button type="button" className="btn-base btn-outline" disabled={!project?.document?.layers?.length && !documentState.layers.length} onClick={() => exportCanvas('png')}><Download size={14} /> PNG</button>
          <button type="button" className="btn-base btn-outline" disabled={!documentState.layers.length} onClick={() => exportCanvas('jpeg')}><Download size={14} /> JPEG</button>
          <a className={`btn-base btn-primary ${!documentState.layers.length ? 'pointer-events-none opacity-40' : ''}`} href={project ? `/api/layer/projects/${project.id}/layers.zip` : '#'}><Download size={14} /> 图层包</a>
        </div>
      </header>

      <aside className="layer-studio-left liquid-glass">
        <div className="layer-panel-heading"><FolderOpen size={14} />项目<button type="button" onClick={() => { setProject(null); setSourceFile(null); setSourcePreview(''); setDocumentState(EMPTY_DOCUMENT) }} title="新建项目"><Plus size={14} /></button></div>
        <div className="layer-project-list custom-scrollbar">
          {projects.map(item => (
            <button key={item.id} type="button" className={project?.id === item.id ? 'active' : ''} onClick={() => openProject(item.id)}>
              <span>{item.name}</span>
              <small>{ACTIVE_STATUSES.has(item.current_task?.status) ? '分解中' : item.current_task?.status === 'failed' ? '失败' : '项目'}</small>
            </button>
          ))}
        </div>
        {project && <>
          <div className="layer-panel-heading layer-versions-heading"><RotateCcw size={14} />版本</div>
          <div className="layer-version-list custom-scrollbar">
            {(project.revisions || []).map((revision, index) => (
              <button key={revision.id} type="button" onClick={async () => {
                await axios.post(`/api/layer/projects/${project.id}/revisions/${revision.id}/restore`)
                await openProject(project.id)
                notify?.(`已恢复到 V${project.revisions.length - index}`)
              }}>
                <span>V{project.revisions.length - index}</span><small>{revision.size}</small>
              </button>
            ))}
          </div>
          <button type="button" className="layer-delete-project" onClick={deleteProject}><Trash2 size={13} />删除项目</button>
        </>}
      </aside>

      <div className="layer-tool-rail liquid-glass">
        <IconButton label="选择图层" onClick={() => setTool('select')} className={tool === 'select' ? 'btn-active' : ''}><MousePointer2 size={16} /></IconButton>
        <IconButton label="移动画布" onClick={() => setTool('pan')} className={tool === 'pan' ? 'btn-active' : ''}><GripVertical size={16} /></IconButton>
      </div>

      <main
        ref={viewportRef}
        className="layer-studio-canvas"
        data-pan-x={pan.x}
        data-pan-y={pan.y}
        onDragOver={event => { if (!project) event.preventDefault() }}
        onDrop={event => { if (!project) { event.preventDefault(); chooseSource(event.dataTransfer.files?.[0]) } }}
      >
        {!project ? (
          <label className="layer-studio-empty" data-testid="layer-source-drop-zone">
            {sourcePreview ? <img src={sourcePreview} alt="待分解源图" /> : <ImagePlus size={34} />}
            <strong>{sourceFile ? sourceFile.name : '添加一张源图片'}</strong>
            <span>PNG / JPEG · 512×512 至 6000×6000</span>
            <input type="file" accept="image/png,image/jpeg" onChange={event => chooseSource(event.target.files?.[0])} />
          </label>
        ) : processing ? (
          <div className="layer-processing-stage">
            <img src={`/api/layer/projects/${project.id}/source`} alt="正在分解的源图" />
            <div className="layer-processing-rain"><CodeRainCanvas status="submitting" /></div>
            <div className="layer-processing-status"><Sparkles size={15} />正在构建图层 · {currentTask?.progress || 0}%</div>
          </div>
        ) : currentTask?.status === 'failed' && documentState.layers.length === 0 ? (
          <div className="layer-studio-failed"><strong>图层分解失败</strong><span>{currentTask.error}</span></div>
        ) : (
          <Stage
            ref={stageRef}
            width={viewport.width}
            height={viewport.height}
            scaleX={stageScale}
            scaleY={stageScale}
            x={stagePosition.x}
            y={stagePosition.y}
            draggable={tool === 'pan'}
            onDragEnd={event => {
              if (event.target !== event.target.getStage()) return
              const centeredX = (viewport.width - documentState.canvas.width * stageScale) / 2
              const centeredY = (viewport.height - documentState.canvas.height * stageScale) / 2
              setPan({ x: event.target.x() - centeredX, y: event.target.y() - centeredY })
            }}
            onMouseDown={event => { if (event.target === event.target.getStage()) commit(current => ({ ...current, selected_layer_id: null })) }}
          >
            <Layer>
              <Group clip={{ x: 0, y: 0, width: documentState.canvas.width, height: documentState.canvas.height }}>
                {documentState.layers.map(item => (
                  <CanvasLayer
                    key={item.id}
                    item={item}
                    selected={item.id === documentState.selected_layer_id}
                    interactive={tool === 'select'}
                    nodeRef={node => { if (node) layerNodes.current.set(item.id, node); else layerNodes.current.delete(item.id) }}
                    onSelect={() => commit(current => ({ ...current, selected_layer_id: item.id }))}
                    onChange={updates => updateLayer(item.id, updates)}
                  />
                ))}
              </Group>
              <Transformer ref={transformerRef} rotateEnabled enabledAnchors={['top-left', 'top-right', 'bottom-left', 'bottom-right']} />
            </Layer>
          </Stage>
        )}
      </main>

      <aside className="layer-studio-right liquid-glass">
        <div className="layer-panel-heading">图层<span>{documentState.layers.length}</span></div>
        <div className="studio-layer-list custom-scrollbar">
          {[...documentState.layers].reverse().map(item => (
            <div
              key={item.id}
              className={`studio-layer-row ${item.id === documentState.selected_layer_id ? 'active' : ''}`}
              draggable
              onDragStart={() => setDraggedLayerId(item.id)}
              onDragOver={event => event.preventDefault()}
              onDrop={() => { reorderLayer(draggedLayerId, item.id); setDraggedLayerId(null) }}
              onClick={() => commit(current => ({ ...current, selected_layer_id: item.id }))}
            >
              <GripVertical size={12} className="layer-row-grip" />
              <button type="button" title={item.visible ? '隐藏图层' : '显示图层'} onClick={event => { event.stopPropagation(); updateLayer(item.id, { visible: !item.visible }) }}>{item.visible ? <Eye size={14} /> : <EyeOff size={14} />}</button>
              <img src={item.thumbnail_url || item.local_url} alt="" />
              <span><strong>{item.name}</strong><small>{item.size}</small></span>
              <button type="button" title={item.locked ? '解锁图层' : '锁定图层'} onClick={event => { event.stopPropagation(); updateLayer(item.id, { locked: !item.locked }) }}>{item.locked ? <Lock size={13} /> : <LockOpen size={13} />}</button>
            </div>
          ))}
        </div>
        <div className="layer-properties">
          <div className="layer-panel-heading">属性</div>
          {selectedLayer ? <>
            <label>名称<input value={selectedLayer.name} onChange={event => updateLayer(selectedLayer.id, { name: event.target.value })} /></label>
            <div className="layer-property-grid">
              <label>X<input type="number" value={Math.round(selectedLayer.x)} onChange={event => updateLayer(selectedLayer.id, { x: Number(event.target.value) })} /></label>
              <label>Y<input type="number" value={Math.round(selectedLayer.y)} onChange={event => updateLayer(selectedLayer.id, { y: Number(event.target.value) })} /></label>
              <label>W<input type="number" min="1" value={Math.round(selectedLayer.display_width)} onChange={event => updateLayer(selectedLayer.id, { display_width: Number(event.target.value) })} /></label>
              <label>H<input type="number" min="1" value={Math.round(selectedLayer.display_height)} onChange={event => updateLayer(selectedLayer.id, { display_height: Number(event.target.value) })} /></label>
              <label>角度<input type="number" value={Math.round(selectedLayer.rotation || 0)} onChange={event => updateLayer(selectedLayer.id, { rotation: Number(event.target.value) })} /></label>
              <label>透明度<input type="number" min="0" max="100" value={Math.round((selectedLayer.opacity ?? 1) * 100)} onChange={event => updateLayer(selectedLayer.id, { opacity: Number(event.target.value) / 100 })} /></label>
            </div>
            {selectedLayer.description && <p>{selectedLayer.description}</p>}
            {!selectedLayer.locked && <button type="button" className="layer-property-delete" onClick={() => commit(current => ({ ...current, layers: current.layers.filter(layer => layer.id !== selectedLayer.id), selected_layer_id: null }))}><Trash2 size={13} />删除图层</button>}
          </> : <div className="layer-properties-empty">选择一个图层</div>}
        </div>
      </aside>

      <footer className="layer-prompt-dock liquid-glass-strong">
        <div className="layer-prompt-title"><Sparkles size={14} />DECOMPOSE PROMPT</div>
        <textarea value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="描述需要如何拆分主体、文字、前景与背景..." aria-label="图层分解提示词" />
        <select value={size} onChange={event => setSize(event.target.value)} aria-label="图层分解分辨率">
          <option value="auto">Auto</option><option value="1K">1K</option><option value="1.5K">1.5K</option><option value="2K">2K</option>
        </select>
        <button type="button" className="btn-base btn-primary" disabled={busy || processing || (!project && !sourceFile)} onClick={project ? decomposeAgain : createProject}>
          <Sparkles size={14} />{processing ? '分解中' : project ? '创建新版本' : '分解图层'}
        </button>
      </footer>
    </section>
  )
}
