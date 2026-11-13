import React, { useEffect, useRef, useState } from 'react'
import Select from '../ui/Select'
import axios from 'axios'
import { Plus, Save, X, Server, RefreshCw } from 'lucide-react'
import { KINDS, ADAPTERS, adaptersFor, blankForm, profileForm, ADVANCED_NUMBERS, payloadFor } from './providerForm'
import './providers.css'

const endpoint = '/api/provider-profiles'
const messageOf = error => error?.response?.data?.error || '配置操作失败，请稍后重试。'

export default function ProviderSettings({ onClose, onSaved }) {
  const [profiles, setProfiles] = useState([])
  const [selected, setSelected] = useState(null)
  const [form, setForm] = useState(blankForm)
  const [busy, setBusy] = useState(true)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [conflict, setConflict] = useState(false)
  const [pending, setPending] = useState(null)
  const confirmRef = useRef(null)
  const dialogRef = useRef(null), lock = useRef(false), mounted = useRef(true)
  const loadList = async () => (await axios.get(endpoint)).data.profiles || []
  const install = profile => { setSelected(profile || null); setForm(profile ? profileForm(profile) : blankForm()); setDirty(false); setConflict(false); setError(''); setNotice('') }
  useEffect(() => {
    mounted.current = true
    const previousFocus = document.activeElement
    dialogRef.current?.focus()
    loadList().then(items => { if (mounted.current) { setProfiles(items); install(items[0]) } }).catch(failure => { if (mounted.current) setError(messageOf(failure)) }).finally(() => { if (mounted.current) setBusy(false) })
    return () => { mounted.current = false; previousFocus?.focus?.() }
  }, [])
  useEffect(() => { if (pending) confirmRef.current?.querySelector('button')?.focus(); else dialogRef.current?.focus() }, [pending])
  const change = patch => { setForm(current => ({ ...current, ...patch })); setDirty(true); setNotice('') }
  const setting = (key, value) => change({ settings: { ...form.settings, [key]: value } })
  function navigate(action) {
    if (busy) return
    if (dirty) { setPending(() => action); return }
    action()
  }
  const close = () => navigate(onClose)
  function changeKind(kind) { const adapter = adaptersFor(kind).includes(form.adapter) ? form.adapter : adaptersFor(kind)[0]; change({ kind, adapter, settings: blankForm(kind, adapter).settings }) }
  async function save(event) {
    event.preventDefault()
    if (lock.current || conflict) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    try {
      const payload = payloadFor(form, selected?.revision)
      const response = selected ? await axios.patch(`${endpoint}/${selected.id}`, payload) : await axios.post(endpoint, payload)
      const saved = response.data.profile
      if (!saved?.id) throw new Error('invalid response')
      install(saved)
      setProfiles(current => [...current.filter(item => item.id !== saved.id).map(item => saved.is_default && item.kind === saved.kind ? { ...item, is_default: false } : item), saved])
      setNotice('配置已保存，后续新任务可选择使用。')
      onSaved?.(saved)
      // Setting a default can revise the previous default. Refresh revisions without
      // replacing the current form or returning any credential to the client.
      try { const items = await loadList(); if (mounted.current) setProfiles(items) } catch { if (mounted.current) setNotice('配置已保存；列表刷新失败，重新打开可查看最新列表。') }
    } catch (failure) {
      if (failure?.response?.status === 409) { setConflict(true); setError('该配置已在其他窗口更新。本地输入仍保留，请重新载入后再编辑。') }
      else setError(messageOf(failure))
    } finally { lock.current = false; if (mounted.current) setBusy(false) }
  }
  async function reload() {
    if (lock.current) return
    lock.current = true; setBusy(true)
    try { const items = await loadList(); setProfiles(items); install(items.find(item => item.id === selected?.id)); setPending(null) } catch (failure) { setError(messageOf(failure)) } finally { lock.current = false; setBusy(false) }
  }
  function keyboard(event) {
    if (event.key === 'Escape') { event.stopPropagation(); event.preventDefault(); if (pending) setPending(null); else close(); return }
    if (event.key !== 'Tab') return
    const scope = pending ? confirmRef.current : dialogRef.current
    const items = [...scope.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,[tabindex="0"]')].filter(item => item.getClientRects().length)
    const first = items[0], last = items[items.length - 1]
    if (event.shiftKey && (document.activeElement === first || document.activeElement === scope)) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
  return <div className="provider-settings-backdrop">
    <section ref={dialogRef} className="provider-settings" role="dialog" aria-modal="true" aria-labelledby="provider-settings-title" tabIndex={-1} onKeyDown={keyboard}>
      <header className="ps-header"><div><h2 id="provider-settings-title"><Server size={20} />接口管理</h2><p>为同一种服务保存多套命名配置，在生成节点中选择使用。</p></div><button type="button" className="btn btn-icon btn-outlined" onClick={close} disabled={busy} aria-label="关闭接口管理" title="关闭接口管理"><X size={19} /></button></header>
      <div className="ps-layout">
        <aside className="ps-sidebar" aria-label="已保存的接口配置">
          <button type="button" className="btn btn-secondary btn-block ps-add" disabled={busy} onClick={() => navigate(() => install(null))}><Plus size={16} />新建配置</button>
          <div className="ps-profile-list">{!profiles.length && <p className="ps-muted">{busy ? '正在读取配置…' : '还没有命名配置。原有服务配置仍可使用。'}</p>}{profiles.map(profile => <button type="button" className="ps-profile" key={profile.id} aria-pressed={selected?.id === profile.id} disabled={busy} onClick={() => navigate(() => install(profile))}><strong>{profile.name}</strong><span>{KINDS[profile.kind]} · {ADAPTERS[profile.adapter] || profile.adapter}</span><small>{profile.enabled ? '已启用' : '已停用'}{profile.is_default ? ' · 默认' : ''}{profile.has_api_key ? ' · 已配置密钥' : ' · 未配置密钥'}</small></button>)}</div>
        </aside>
        <form className="ps-form" onSubmit={save}>
          <div className="ps-form-scroll">
            <h3>{selected ? '编辑接口配置' : '新建接口配置'}</h3>
            {error && <div className="ps-error" role="alert">{error}{conflict && <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setPending(() => reload)}><RefreshCw size={14} />重新载入服务器版本</button>}</div>}
            {notice && <div className="ps-notice" role="status">{notice}</div>}
            <fieldset disabled={busy}>
              <label>配置名称<input required maxLength={100} value={form.name} placeholder="例如：Ark 主账号" onChange={event => change({ name: event.target.value })} /></label>
              <div className="ps-row"><label>生成类型<Select ariaLabel="生成类型" disabled={Boolean(selected)} value={form.kind} options={Object.entries(KINDS).map(([value, label]) => ({ value, label }))} onChange={changeKind} /></label><label>服务适配器<Select ariaLabel="服务适配器" disabled={Boolean(selected)} value={form.adapter} options={(adaptersFor(form.kind).includes(form.adapter) ? adaptersFor(form.kind) : [form.adapter, ...adaptersFor(form.kind)]).map(value => ({ value, label: ADAPTERS[value] || value }))} onChange={value => change({ adapter: value, settings: blankForm(form.kind, value).settings })} /></label></div>
              {selected && <p className="ps-muted">类型和适配器创建后固定；使用另一种适配器请新建配置。</p>}
              <label>接口地址<input required type="url" value={form.settings.endpoint || ''} onChange={event => setting('endpoint', event.target.value)} spellCheck={false} /></label>
              <label>API Key<input type="password" autoComplete="new-password" value={form.api_key} disabled={form.clear_api_key} placeholder={selected?.has_api_key ? '已配置 · 留空保持现有密钥' : '输入该账号的 API Key'} onChange={event => change({ api_key: event.target.value })} /></label>
              <p className="ps-muted">{selected?.has_api_key ? `当前密钥：${selected.api_key_mask || '••••••••'}。密钥不会从服务器回显。` : '密钥仅发送到本平台后端保存，不写入节点或浏览器存储。'}</p>
              {selected?.has_api_key && <label className="ps-check"><input type="checkbox" checked={form.clear_api_key} onChange={event => change({ clear_api_key: event.target.checked, api_key: '' })} />清除已保存的密钥</label>}
              <label>{form.kind === 'video' && form.adapter === 'ark' ? 'Seedance 2.0 模型 / 推理接入点 ID' : '默认模型'}<input readOnly={form.adapter === 'cupsy' && form.kind !== 'video'} value={form.settings.model || ''} onChange={event => setting('model', event.target.value)} spellCheck={false} placeholder={form.kind === 'video' && form.adapter === 'ark' ? '例如 ep-…；按服务账号配置' : '模型标识'} /></label>
              {form.adapter === 'cupsy' && form.kind !== 'video' && <p className="ps-muted">此适配器当前使用固定模型，可配置服务地址和账号。</p>}
              <div className="ps-checks"><label className="ps-check"><input type="checkbox" checked={form.enabled} onChange={event => change({ enabled: event.target.checked, is_default: event.target.checked && form.is_default })} />启用此配置</label><label className="ps-check"><input type="checkbox" checked={form.is_default} disabled={!form.enabled} onChange={event => change({ is_default: event.target.checked })} />作为新节点的首次预选</label><span className="ps-muted">仅在该类型还没有“上次选择”时，新建节点预选它；不影响已有节点。</span></div>
              <details className="ps-advanced"><summary>高级参数</summary>
                <p className="ps-muted">留空采用服务端默认值。连接超时限制连接建立阶段，不是整个文件上传时长；查询参数仅用于异步任务。修改配置不会替换已有任务使用的配置版本。</p>
                {form.kind === 'video' && form.adapter === 'ark' && <><label>Seedance 2.0 Fast 接入点 ID<input value={form.settings.fast_model || ''} onChange={event => setting('fast_model', event.target.value)} /></label><label>Seedance 2.5 接入点 ID<input value={form.settings.seedance_2_5_model || ''} placeholder="ep-…（BytePlus 控制台真实接入点；留空沿用部署配置）" spellCheck={false} onChange={event => setting('seedance_2_5_model', event.target.value)} /></label></>}
                {form.adapter === 'cupsy' && <><label>公网素材源地址<input type="url" value={form.settings.source_base_url || ''} placeholder="https://你的平台域名" onChange={event => setting('source_base_url', event.target.value)} /></label><label>素材签名有效期（秒，至少 7200）<input type="number" min="7200" max="86400" step="1" value={form.settings.asset_token_ttl_seconds ?? ''} onChange={event => setting('asset_token_ttl_seconds', event.target.value)} /></label></>}
                <div className="ps-row">{ADVANCED_NUMBERS.map(([key, label]) => <label key={key}>{label}<input type="number" min="1" max={key === 'poll_max_attempts' ? 100000 : key === 'poll_interval_seconds' ? 300 : 3600} step="1" value={form.settings[key] ?? ''} onChange={event => setting(key, event.target.value)} /></label>)}</div>
              </details>
            </fieldset>
          </div>
          <footer className="ps-footer"><span>{dirty ? '有未保存的修改' : selected ? `配置版本 ${selected.revision}` : '保存后可在节点中选择'}</span><button className="btn btn-primary" type="submit" disabled={busy || conflict}>{busy ? '处理中…' : <><Save size={15} />保存配置</>}</button></footer>
        </form>
      </div>
      {pending && <div ref={confirmRef} className="ps-confirm" role="alertdialog" aria-modal="true" aria-label="未保存修改"><div><h3>替换当前未保存的内容？</h3><p>继续会丢弃本地编辑，已保存的服务器配置不会因此被修改。</p><button type="button" className="btn btn-secondary" onClick={() => setPending(null)}>继续编辑</button><button type="button" className="btn btn-danger" onClick={() => { const action = pending; setPending(null); action() }}>丢弃修改并继续</button></div></div>}
    </section>
  </div>
}
