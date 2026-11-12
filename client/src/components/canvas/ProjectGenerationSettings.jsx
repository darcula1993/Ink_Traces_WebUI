import React, { useEffect, useRef, useState } from 'react'
import { getProjectGenerationSettings, saveProjectGenerationSettings } from '../../lib/canvasApi'
const kinds = [['image', '图像'], ['video', '视频'], ['audio', '音频']]
export default function ProjectGenerationSettings({ projectId, capabilities, onClose, onSaved }) {
  const [draft, setDraft] = useState(null), [busy, setBusy] = useState(true), [error, setError] = useState(''), [conflict, setConflict] = useState(false)
  const ref = useRef(null), lock = useRef(false)
  async function load() {
    setBusy(true); setError('')
    try { setDraft(await getProjectGenerationSettings(projectId)); setConflict(false) } catch(e) { setError(e?.response?.data?.error || e.message) } finally { setBusy(false) }
  }
  useEffect(() => { load(); const prior = document.activeElement; ref.current?.focus(); return () => prior?.isConnected && prior.focus() }, [projectId])
  async function save() {
    if (lock.current) return
    lock.current = true; ref.current.focus(); setBusy(true); setError('')
    try { const result = await saveProjectGenerationSettings(projectId, draft); onSaved(result); onClose() }
    catch(e) { const collision = e?.response?.status === 409; setConflict(collision); setError(collision ? '项目设置已被其他窗口修改。本地选择已保留，请重新载入后再修改。' : e?.response?.data?.error || e.message) }
    finally { lock.current = false; setBusy(false) }
  }
  function keys(e) {
    e.stopPropagation()
    if(e.key === 'Escape' && !busy) onClose()
    if(e.key !== 'Tab') return
    const items = [...ref.current.querySelectorAll('button:not(:disabled),select:not(:disabled)')]
    if (!items.length) { e.preventDefault(); ref.current.focus() }
    else if (e.shiftKey && [items[0],ref.current].includes(document.activeElement)) {e.preventDefault();items.at(-1).focus()}
    else if (!e.shiftKey && document.activeElement === items.at(-1)) {e.preventDefault();items[0].focus()}
  }
  return <div className="cv-studio-overlay"><section className="cv-project-settings" ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label="项目生成设置" onKeyDown={keys}><h2>项目默认接口</h2><p>本项目未单独选择接口的生成节点继承以下默认值。节点可独立选择接口；保存只影响之后提交的任务。</p>{draft && kinds.map(([kind,label]) => { const selected = draft.providers[kind], id = selected ? selected.profile_id ? `profile:${selected.profile_id}` : selected.provider : '', options = capabilities[kind] || []; return <label key={kind}>{label}生成接口<select aria-label={`${label}生成接口`} disabled={busy} value={id} onChange={e => {const provider = options.find(p => p.id === e.target.value);setDraft({...draft,providers:{...draft.providers,[kind]:provider ? {provider:provider.provider,profile_id:provider.profile_id || null} : null}})}}><option value="">未配置（请选择后保存）</option>{id && !options.some(p => p.id === id) && <option value={id}>已选接口已停用或不可用</option>}{options.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label> })}{busy && <p role="status">正在处理…</p>}{error && <p role="alert">{error}</p>}{conflict && <button disabled={busy} onClick={load}>重新载入项目设置</button>}<footer><button disabled={busy} onClick={onClose}>取消</button><button className="cv-primary" disabled={busy || !draft || conflict} onClick={save}>保存项目设置</button></footer></section></div>
}
