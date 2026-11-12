import React, { useEffect, useRef, useState } from 'react'
import { Stage, Layer, Image as CanvasImage, Rect, Line } from 'react-konva'
import './image-editor.css'

const MAX_PIXELS = 16000000
function surface(width, height) { const c = document.createElement('canvas'); c.width = width; c.height = height; return c }
function copy(source) { const c = surface(source.width, source.height); c.getContext('2d').drawImage(source, 0, 0); return c }
function boundedHistory(items) {
  let pixels = 0
  return items.slice(-8).reverse().filter(c => { pixels += c.width * c.height; return pixels <= 32000000 }).reverse()
}
export default function ImageAssetEditor({ asset, onSave, onClose }) {
  const [bitmap, setBitmap] = useState(null), [undo, setUndo] = useState([]), [redo, setRedo] = useState([])
  const [tool, setTool] = useState('crop'), [crop, setCrop] = useState(null), [stroke, setStroke] = useState([])
  const [color, setColor] = useState('#ef4444'), [width, setWidth] = useState(12)
  const [error, setError] = useState(''), [saving, setSaving] = useState(false), [loading, setLoading] = useState(true)
  const [space, setSpace] = useState({ width: 800, height: 480 })
  const original = useRef(null), dialog = useRef(null), host = useRef(null), stage = useRef(null), gesture = useRef(null), saveLock = useRef(false)
  const scale = bitmap ? Math.min(space.width / bitmap.width, space.height / bitmap.height, 1) : 1
  useEffect(() => {
    const previous = document.activeElement
    dialog.current?.focus()
    return () => previous?.isConnected && previous.focus()
  }, [])
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setSpace({ width: Math.max(1, entry.contentRect.width - 24), height: Math.max(1, entry.contentRect.height - 24) }))
    observer.observe(host.current); return () => observer.disconnect()
  }, [])
  useEffect(() => {
    let alive = true
    setLoading(true); setError(''); setBitmap(null); setUndo([]); setRedo([]); setCrop(null)
    const image = new window.Image(); image.crossOrigin = 'anonymous'
    image.onload = () => {
      if (!alive) return
      try {
        if (!image.naturalWidth || image.naturalWidth * image.naturalHeight > MAX_PIXELS || Math.max(image.naturalWidth, image.naturalHeight) > 8192) throw new Error('图片过大：最多 1600 万像素，单边不超过 8192 像素。请先缩小原图。')
        const c = surface(image.naturalWidth, image.naturalHeight); c.getContext('2d').drawImage(image, 0, 0)
        c.getContext('2d').getImageData(0, 0, 1, 1)
        original.current = c; setBitmap(c)
      } catch (e) { setError(e.message || '无法读取图片') } finally { setLoading(false) }
    }
    image.onerror = () => { if (alive) { setError('图片加载失败，请关闭后重试。'); setLoading(false) } }
    image.src = asset.url
    return () => { alive = false }
  }, [asset.url])
  function commit(next) { setUndo(items => boundedHistory([...items, bitmap])); setRedo([]); setBitmap(next); setCrop(null); setStroke([]); setError('') }
  function transform(kind) {
    const rotate = kind === 'rotate', c = surface(rotate ? bitmap.height : bitmap.width, rotate ? bitmap.width : bitmap.height), ctx = c.getContext('2d')
    if (rotate) { ctx.translate(c.width, 0); ctx.rotate(Math.PI / 2) }
    else { ctx.translate(kind === 'horizontal' ? c.width : 0, kind === 'vertical' ? c.height : 0); ctx.scale(kind === 'horizontal' ? -1 : 1, kind === 'vertical' ? -1 : 1) }
    ctx.drawImage(bitmap, 0, 0); commit(c)
  }
  function history(back) {
    const source = back ? undo : redo, next = source.at(-1)
    if (!next) return
    if (back) { setUndo(source.slice(0, -1)); setRedo(items => boundedHistory([...items, bitmap])) }
    else { setRedo(source.slice(0, -1)); setUndo(items => boundedHistory([...items, bitmap])) }
    setBitmap(next); setCrop(null); setStroke([])
  }
  function point() { const p = stage.current.getPointerPosition(); return p && { x: Math.max(0, Math.min(bitmap.width, p.x / scale)), y: Math.max(0, Math.min(bitmap.height, p.y / scale)) } }
  function start(e) {
    if (!bitmap || saving || (e.evt.button !== undefined && e.evt.button !== 0)) return
    const p = point(); if (!p) return
    e.evt.preventDefault(); e.evt.target.setPointerCapture?.(e.evt.pointerId)
    gesture.current = { start: p, points: [p.x, p.y] }
    if (tool === 'crop') setCrop(null); else setStroke([p.x, p.y, p.x, p.y])
  }
  function move() {
    const g = gesture.current, p = point(); if (!g || !p) return
    if (tool === 'crop') {
      const x = Math.floor(Math.min(g.start.x, p.x)), y = Math.floor(Math.min(g.start.y, p.y))
      setCrop({ x, y, width: Math.ceil(Math.max(g.start.x, p.x)) - x, height: Math.ceil(Math.max(g.start.y, p.y)) - y })
    } else { g.points.push(p.x, p.y); setStroke([...g.points]) }
  }
  function finish() {
    const g = gesture.current; gesture.current = null
    if (!g || tool !== 'brush') return
    const c = copy(bitmap), ctx = c.getContext('2d'); ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = width; ctx.lineCap = 'round'; ctx.lineJoin = 'round'
    if (g.points.length === 2) { ctx.beginPath(); ctx.arc(g.points[0], g.points[1], width / 2, 0, Math.PI * 2); ctx.fill() }
    else { ctx.beginPath(); ctx.moveTo(g.points[0], g.points[1]); for (let i = 2; i < g.points.length; i += 2) ctx.lineTo(g.points[i], g.points[i + 1]); ctx.stroke() }
    commit(c)
  }
  function applyCrop() { if (!crop?.width || !crop?.height) return; const c = surface(crop.width, crop.height); c.getContext('2d').drawImage(bitmap, crop.x, crop.y, crop.width, crop.height, 0, 0, crop.width, crop.height); commit(c) }
  async function save() {
    if (!bitmap || saveLock.current) return
    saveLock.current = true; dialog.current.focus(); setSaving(true); setError('')
    try {
      const blob = await new Promise((resolve, reject) => bitmap.toBlob(value => value ? resolve(value) : reject(new Error('导出失败，请重试。')), 'image/png'))
      await onSave(new File([blob], `${(asset.name || '图片').replace(/\.[^.]+$/, '')}-编辑.png`, { type: 'image/png' }))
      onClose()
    } catch (e) { setError(e?.response?.data?.error || e.message || '保存失败，请重试。') }
    finally { saveLock.current = false; setSaving(false) }
  }
  function keys(e) {
    e.stopPropagation()
    if (e.key === 'Escape') { e.preventDefault(); if (!saveLock.current) onClose() }
    if (e.key !== 'Tab') return
    const items = [...dialog.current.querySelectorAll('button:not(:disabled), input:not(:disabled), [tabindex="0"]')], first = items[0], last = items.at(-1)
    if (!items.length) { e.preventDefault(); dialog.current.focus(); return }
    if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { e.preventDefault(); last?.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
  }
  const disabled = !bitmap || saving
  return <div className="ie-overlay" onPointerDown={e => e.stopPropagation()}><section className="ie-dialog" role="dialog" aria-modal="true" aria-label="编辑图片" tabIndex={-1} ref={dialog} onKeyDown={keys}>
    <header><div><h2>编辑图片</h2><p>另存为新素材，保留原图。</p></div><button disabled={saving} onClick={onClose} aria-label="关闭图片编辑">关闭</button></header>
    <div className="ie-tools"><button disabled={disabled} aria-pressed={tool === 'crop'} onClick={() => { setTool('crop'); setStroke([]) }}>裁剪</button><button disabled={disabled} onClick={() => transform('rotate')}>顺时针旋转 90°</button><button disabled={disabled} onClick={() => transform('horizontal')}>水平翻转</button><button disabled={disabled} onClick={() => transform('vertical')}>垂直翻转</button><button disabled={disabled} aria-pressed={tool === 'brush'} onClick={() => { setTool('brush'); setCrop(null) }}>画笔</button><label>画笔颜色<input aria-label="画笔颜色" type="color" value={color} disabled={disabled} onChange={e => setColor(e.target.value)} /></label><label>画笔粗细<input aria-label="画笔粗细" type="range" min="1" max="100" value={width} disabled={disabled} onChange={e => setWidth(Number(e.target.value))} /><output>{width} px</output></label><button disabled={disabled || !undo.length} onClick={() => history(true)}>撤销</button><button disabled={disabled || !redo.length} onClick={() => history(false)}>重做</button><button disabled={disabled || bitmap === original.current} onClick={() => commit(original.current)}>重置</button></div>
    <div className="ie-crop-tools">{tool === 'crop' && bitmap ? <><span>拖动框选；或填写像素范围：</span>{['x', 'y', 'width', 'height'].map((key, i) => <label key={key}>{['X', 'Y', '宽', '高'][i]}<input aria-label={`裁剪${['X', 'Y', '宽', '高'][i]}`} type="number" min={i < 2 ? 0 : 1} disabled={saving} value={crop?.[key] ?? (i < 2 ? 0 : bitmap[key])} onChange={e => { const c = { x: 0, y: 0, width: bitmap.width, height: bitmap.height, ...crop, [key]: Math.round(Number(e.target.value)) }; c.x = Math.max(0, Math.min(bitmap.width - 1, c.x)); c.y = Math.max(0, Math.min(bitmap.height - 1, c.y)); c.width = Math.max(1, Math.min(bitmap.width - c.x, c.width)); c.height = Math.max(1, Math.min(bitmap.height - c.y, c.height)); setCrop(c) }} /></label>)}<button disabled={saving || !crop?.width || !crop?.height} onClick={applyCrop}>应用裁剪</button></> : <span>拖动画笔绘制；粗细以原图像素为单位。</span>}</div>
    <div className="ie-preview" ref={host} aria-label="图片编辑画布">{bitmap && <Stage ref={stage} width={bitmap.width * scale} height={bitmap.height * scale} scaleX={scale} scaleY={scale} onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={() => { gesture.current = null; setStroke([]) }}><Layer><CanvasImage image={bitmap} listening={false} />{stroke.length > 0 && <Line points={stroke} stroke={color} strokeWidth={width} lineCap="round" lineJoin="round" listening={false} />}{crop && <Rect {...crop} stroke="#60a5fa" strokeWidth={2 / scale} dash={[6 / scale, 4 / scale]} fill="rgba(96,165,250,.12)" listening={false} />}</Layer></Stage>}{loading && <p>正在载入图片…</p>}</div>
    {error && <p className="ie-error" role="alert">{error}</p>}
    <footer><span>{bitmap ? `${bitmap.width} × ${bitmap.height} 像素 · PNG` : 'PNG'}{crop ? ' · 裁剪框尚未应用' : ''}</span><button disabled={saving} onClick={onClose}>取消</button><button disabled={disabled || Boolean(crop)} onClick={save}>{saving ? '保存中…' : '保存为新素材'}</button></footer>
  </section></div>
}
