import React, { useEffect, useRef, useState } from 'react'
import Select from '../ui/Select'
import axios from 'axios'
import { Plus, Save, X, Server, RefreshCw, Trash2, ShieldCheck, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react'
import { KINDS, ADAPTERS, adaptersFor, blankForm, profileForm, ADVANCED_NUMBERS, payloadFor } from './providerForm'
import './providers.css'

const endpoint = '/api/provider-profiles'
const GROUP_ORDER = [
  ['image', '图像'],
  ['video', '视频'],
  ['audio', '音频'],
]
const messageOf = error => error?.response?.data?.error || '配置操作失败，请稍后重试。'

function preflightPayloadFor(form) {
  const settings = { ...form.settings }
  for (const [key] of [...ADVANCED_NUMBERS, ['asset_token_ttl_seconds']]) {
    if (key in settings) {
      if (settings[key] === '' || settings[key] == null) settings[key] = null
      else settings[key] = Number(settings[key])
    }
  }
  const payload = {
    kind: form.kind,
    adapter: form.adapter,
    enabled: form.enabled,
    settings,
  }
  if (form.clear_api_key) payload.clear_api_key = true
  else if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  return payload
}

function StatusIcon({ status }) {
  if (status === 'ok') return <CheckCircle2 size={15} className="ps-check-ico is-ok" aria-hidden="true" />
  if (status === 'warn') return <AlertTriangle size={15} className="ps-check-ico is-warn" aria-hidden="true" />
  return <XCircle size={15} className="ps-check-ico is-error" aria-hidden="true" />
}

export default function ProviderSettings({ onClose, onSaved }) {
  const [profiles, setProfiles] = useState([])
  const [selected, setSelected] = useState(null)
  const [form, setForm] = useState(blankForm)
  const [busy, setBusy] = useState(true)
  const [checking, setChecking] = useState(false)
  const [preflight, setPreflight] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [conflict, setConflict] = useState(false)
  const [pending, setPending] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const confirmRef = useRef(null)
  const dialogRef = useRef(null), lock = useRef(false), mounted = useRef(true)
  const loadList = async () => (await axios.get(endpoint)).data.profiles || []
  const install = profile => {
    setSelected(profile || null)
    setForm(profile ? profileForm(profile) : blankForm())
    setDirty(false)
    setConflict(false)
    setError('')
    setNotice('')
    setPreflight(null)
    setConfirmDelete(false)
  }
  useEffect(() => {
    mounted.current = true
    const previousFocus = document.activeElement
    dialogRef.current?.focus()
    loadList().then(items => { if (mounted.current) { setProfiles(items); install(items[0]) } }).catch(failure => { if (mounted.current) setError(messageOf(failure)) }).finally(() => { if (mounted.current) setBusy(false) })
    return () => { mounted.current = false; previousFocus?.focus?.() }
  }, [])
  useEffect(() => { if (pending || confirmDelete) confirmRef.current?.querySelector('button')?.focus(); else dialogRef.current?.focus() }, [pending, confirmDelete])
  const change = patch => { setForm(current => ({ ...current, ...patch })); setDirty(true); setNotice(''); setPreflight(null) }
  const setting = (key, value) => change({ settings: { ...form.settings, [key]: value } })
  function navigate(action) {
    if (busy || checking) return
    if (dirty) { setPending(() => action); return }
    action()
  }
  const close = () => navigate(onClose)
  function changeKind(kind) { const adapter = adaptersFor(kind).includes(form.adapter) ? form.adapter : adaptersFor(kind)[0]; change({ kind, adapter, settings: blankForm(kind, adapter).settings }) }
  const sameAdapterPeers = profiles.filter(item => item.adapter === form.adapter && item.id !== selected?.id)
  const changingKey = Boolean(form.clear_api_key || form.api_key.trim())
  const canSyncAdapterKey = sameAdapterPeers.length > 0 && changingKey

  const groupedProfiles = GROUP_ORDER
    .map(([kind, label]) => ({ kind, label, items: profiles.filter(item => item.kind === kind) }))
    .filter(group => group.items.length > 0)

  async function runPreflight() {
    if (busy || checking || lock.current) return
    setChecking(true)
    setError('')
    try {
      const url = selected ? `${endpoint}/${selected.id}/check` : `${endpoint}/check`
      const payload = selected && !dirty ? {} : preflightPayloadFor(form)
      const response = await axios.post(url, payload)
      if (mounted.current) setPreflight(response.data)
    } catch (failure) {
      if (mounted.current) setError(messageOf(failure))
    } finally {
      if (mounted.current) setChecking(false)
    }
  }

  async function save(event) {
    event.preventDefault()
    if (lock.current || conflict) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    try {
      const payload = payloadFor(form, selected?.revision, canSyncAdapterKey)
      const response = selected ? await axios.patch(`${endpoint}/${selected.id}`, payload) : await axios.post(endpoint, payload)
      const saved = response.data.profile
      const syncedIds = Array.isArray(response.data.synced_profile_ids) ? response.data.synced_profile_ids : []
      if (!saved?.id) throw new Error('invalid response')
      install(saved)
      setProfiles(current => [...current.filter(item => item.id !== saved.id).map(item => saved.is_default && item.kind === saved.kind ? { ...item, is_default: false } : item), saved])
      setNotice(
        syncedIds.length
          ? `配置已保存，并同步更新了另外 ${syncedIds.length} 个 ${ADAPTERS[saved.adapter] || saved.adapter} 配置的 API Key，修改已即时生效。`
          : '配置已保存并即时生效，后续新任务可选择使用。'
      )
      onSaved?.(saved)
      // Setting a default or syncing same-adapter keys can revise other profiles. Refresh
      // revisions and key badges without replacing the current form or returning any credential.
      try { const items = await loadList(); if (mounted.current) setProfiles(items) } catch { if (mounted.current) setNotice('配置已保存；列表刷新失败，重新打开可查看最新列表。') }
    } catch (failure) {
      if (failure?.response?.status === 409) { setConflict(true); setError('该配置已在其他窗口更新。本地输入仍保留，请重新载入后再编辑。') }
      else setError(messageOf(failure))
    } finally { lock.current = false; if (mounted.current) setBusy(false) }
  }
  async function remove() {
    if (!selected || lock.current || conflict) return
    const target = selected
    lock.current = true; setBusy(true); setError(''); setNotice(''); setConfirmDelete(false)
    try {
      await axios.delete(`${endpoint}/${target.id}`, { data: { revision: target.revision } })
      let items
      try { items = await loadList() } catch { items = profiles.filter(item => item.id !== target.id) }
      if (mounted.current) {
        setProfiles(items)
        install(items[0] || null)
        setNotice(`已删除接口配置“${target.name}”。`)
      }
      onSaved?.()
    } catch (failure) {
      if (mounted.current) {
        if (failure?.response?.status === 409) { setConflict(true); setError('该配置已在其他窗口更新。请重新载入后再操作。') }
        else setError(messageOf(failure))
      }
    } finally { lock.current = false; if (mounted.current) setBusy(false) }
  }
  async function reload() {
    if (lock.current) return
    lock.current = true; setBusy(true)
    try { const items = await loadList(); setProfiles(items); install(items.find(item => item.id === selected?.id) || items[0] || null); setPending(null) } catch (failure) { setError(messageOf(failure)) } finally { lock.current = false; setBusy(false) }
  }
  function keyboard(event) {
    if (event.key === 'Escape') { event.stopPropagation(); event.preventDefault(); if (confirmDelete) setConfirmDelete(false); else if (pending) setPending(null); else close(); return }
    if (event.key !== 'Tab') return
    const scope = (pending || confirmDelete) ? confirmRef.current : dialogRef.current
    const items = [...scope.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,[tabindex="0"]')].filter(item => item.getClientRects().length)
    const first = items[0], last = items[items.length - 1]
    if (event.shiftKey && (document.activeElement === first || document.activeElement === scope)) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
  return <div className="provider-settings-backdrop">
    <section ref={dialogRef} className="provider-settings" role="dialog" aria-modal="true" aria-labelledby="provider-settings-title" tabIndex={-1} onKeyDown={keyboard}>
      <header className="ps-header"><div><h2 id="provider-settings-title"><Server size={20} />接口管理</h2><p>统一管理所有接口配置与密钥；修改后即时生效，无需重启或修改 config.json。</p></div><button type="button" className="btn btn-icon btn-outlined" onClick={close} disabled={busy || checking} aria-label="关闭接口管理" title="关闭接口管理"><X size={19} /></button></header>
      <div className="ps-layout">
        <aside className="ps-sidebar" aria-label="已保存的接口配置">
          <button type="button" className="btn btn-secondary btn-block ps-add" disabled={busy || checking} onClick={() => navigate(() => install(null))}><Plus size={16} />新建配置</button>
          <div className="ps-profile-list">
            {!profiles.length && <p className="ps-muted">{busy ? '正在读取配置…' : '还没有接口配置，点击上方「新建配置」开始'}</p>}
            {groupedProfiles.map(group => (
              <div key={group.kind} className="ps-group" role="group" aria-label={`${group.label}配置`} data-provider-group={group.kind}>
                <div className="ps-group-head">
                  <span>{group.label}</span>
                  <small>{group.items.length}</small>
                </div>
                {group.items.map(profile => (
                  <button type="button" className="ps-profile" key={profile.id} aria-pressed={selected?.id === profile.id} disabled={busy || checking} onClick={() => navigate(() => install(profile))}>
                    <div className="ps-profile-head">
                      <strong>{profile.name}</strong>
                    </div>
                    <span>{KINDS[profile.kind]} · {ADAPTERS[profile.adapter] || profile.adapter}</span>
                    <small>{profile.enabled ? '已启用' : '已停用'}{profile.is_default ? ' · 默认' : ''}{profile.has_api_key ? ' · 已配置密钥' : ' · 未配置密钥'}</small>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </aside>
        <form className="ps-form" onSubmit={save}>
          <div className="ps-form-scroll">
            <div className="ps-form-head"><h3>{selected ? '编辑接口配置' : '新建接口配置'}</h3></div>
            {error && <div className="ps-error" role="alert">{error}{conflict && <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => (dirty ? setPending(() => reload) : reload())}><RefreshCw size={14} />重新载入服务器版本</button>}</div>}
            {notice && <div className="ps-notice" role="status">{notice}</div>}
            {preflight && (
              <section className={`ps-preflight is-${preflight.status || 'ok'}`} role="region" aria-label="配置预检结果" data-testid="provider-preflight-result">
                <div className="ps-preflight-head">
                  <StatusIcon status={preflight.status} />
                  <strong>{preflight.summary || '预检完成'}</strong>
                  <span className="ps-preflight-tag">零计费本地校验</span>
                </div>
                <ul className="ps-preflight-list">
                  {(preflight.checks || []).map(item => (
                    <li key={item.key} className={`ps-preflight-item is-${item.status}`} data-check-key={item.key} data-check-status={item.status}>
                      <StatusIcon status={item.status} />
                      <span className="ps-preflight-label">{item.label}</span>
                      <span className="ps-preflight-msg">{item.message}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <fieldset disabled={busy || checking}>
              <label>配置名称<input required maxLength={100} value={form.name} placeholder="例如：Ark 主账号" onChange={event => change({ name: event.target.value })} /></label>
              <div className="ps-row"><label>生成类型<Select ariaLabel="生成类型" disabled={Boolean(selected)} value={form.kind} options={Object.entries(KINDS).map(([value, label]) => ({ value, label }))} onChange={changeKind} /></label><label>服务适配器<Select ariaLabel="服务适配器" disabled={Boolean(selected)} value={form.adapter} options={(adaptersFor(form.kind).includes(form.adapter) ? adaptersFor(form.kind) : [form.adapter, ...adaptersFor(form.kind)]).map(value => ({ value, label: ADAPTERS[value] || value }))} onChange={value => change({ adapter: value, settings: blankForm(form.kind, value).settings })} /></label></div>
              {selected && <p className="ps-muted">类型和适配器创建后固定；使用另一种适配器请新建配置。</p>}
              <label>接口地址<input required type="url" value={form.settings.endpoint || ''} onChange={event => setting('endpoint', event.target.value)} spellCheck={false} /></label>
              <label>API Key<input type="password" autoComplete="new-password" value={form.api_key} disabled={form.clear_api_key} placeholder={selected?.has_api_key ? '已配置 · 留空保持现有密钥' : '输入该账号的 API Key'} onChange={event => change({ api_key: event.target.value })} /></label>
              <p className="ps-muted">{selected?.has_api_key ? `当前密钥：${selected.api_key_mask || '••••••••'}。密钥不会从服务器回显。` : '密钥仅发送到本平台后端保存，不写入节点或浏览器存储。'}</p>
              {selected?.has_api_key && <label className="ps-check"><input type="checkbox" checked={form.clear_api_key} onChange={event => change({ clear_api_key: event.target.checked, api_key: '' })} />清除已保存的密钥</label>}
              {canSyncAdapterKey && <><label className="ps-check ps-sync-key"><input type="checkbox" checked={form.sync_adapter_api_key} onChange={event => change({ sync_adapter_api_key: event.target.checked })} />同时同步更新所有 {ADAPTERS[form.adapter] || form.adapter} 配置的 API Key</label><p className="ps-muted">将同步更新另外 {sameAdapterPeers.length} 个 {ADAPTERS[form.adapter] || form.adapter} 配置的密钥，并立即生效。</p></>}
              <label>{form.kind === 'video' && form.adapter === 'ark' ? 'Seedance 2.0 模型 / 推理接入点 ID' : '默认模型'}<input readOnly={form.adapter === 'cupsy' && form.kind !== 'video'} value={form.settings.model || ''} onChange={event => setting('model', event.target.value)} spellCheck={false} placeholder={form.kind === 'video' && form.adapter === 'ark' ? '例如 ep-…；按服务账号配置' : '模型标识'} /></label>
              {form.adapter === 'cupsy' && form.kind !== 'video' && <p className="ps-muted">此适配器当前使用固定模型，可配置服务地址和账号。</p>}
              <div className="ps-checks"><label className="ps-check"><input type="checkbox" checked={form.enabled} onChange={event => change({ enabled: event.target.checked, is_default: event.target.checked && form.is_default })} />启用此配置</label><label className="ps-check"><input type="checkbox" checked={form.is_default} disabled={!form.enabled} onChange={event => change({ is_default: event.target.checked })} />默认配置</label><span className="ps-muted">该类型尚无“上次选择”时优先选用此配置；不影响已有节点。</span></div>
              <details className="ps-advanced"><summary>高级参数</summary>
                <p className="ps-muted">留空采用服务端默认值。连接超时限制连接建立阶段，不是整个文件上传时长；查询参数仅用于异步任务。修改配置不会替换已有任务使用的配置版本。</p>
                {form.kind === 'video' && form.adapter === 'ark' && <><label>Seedance 2.0 Fast 接入点 ID<input value={form.settings.fast_model || ''} onChange={event => setting('fast_model', event.target.value)} /></label><label>Seedance 2.5 接入点 ID<input value={form.settings.seedance_2_5_model || ''} placeholder="ep-…（BytePlus 控制台真实接入点；留空沿用部署配置）" spellCheck={false} onChange={event => setting('seedance_2_5_model', event.target.value)} /></label></>}
                {form.adapter === 'cupsy' && <><label>公网素材源地址<input type="url" value={form.settings.source_base_url || ''} placeholder="https://你的平台域名" onChange={event => setting('source_base_url', event.target.value)} /></label><label>素材签名有效期（秒，至少 7200）<input type="number" min="7200" max="86400" step="1" value={form.settings.asset_token_ttl_seconds ?? ''} onChange={event => setting('asset_token_ttl_seconds', event.target.value)} /></label></>}
                <div className="ps-row">{ADVANCED_NUMBERS.map(([key, label]) => <label key={key}>{label}<input type="number" min="1" max={key === 'poll_max_attempts' ? 100000 : key === 'poll_interval_seconds' ? 300 : 3600} step="1" value={form.settings[key] ?? ''} onChange={event => setting(key, event.target.value)} /></label>)}</div>
              </details>
            </fieldset>
          </div>
          <footer className="ps-footer">
            <span>{dirty ? '有未保存的修改' : selected ? `配置版本 ${selected.revision}` : '保存后可在节点中选择'}</span>
            <div className="ps-footer-actions">
              <button type="button" className="btn btn-secondary" disabled={busy || checking} onClick={runPreflight}><ShieldCheck size={15} />{checking ? '预检中…' : '配置预检'}</button>
              {selected && <button type="button" className="btn btn-danger" disabled={busy || checking || conflict} onClick={() => setConfirmDelete(true)}><Trash2 size={15} />删除配置</button>}
              <button className="btn btn-primary" type="submit" disabled={busy || checking || conflict}>{busy ? '处理中…' : <><Save size={15} />保存配置</>}</button>
            </div>
          </footer>
        </form>
      </div>
      {pending && <div ref={confirmRef} className="ps-confirm" role="alertdialog" aria-modal="true" aria-label="未保存修改"><div><h3>替换当前未保存的内容？</h3><p>继续会丢弃本地编辑，已保存的服务器配置不会因此被修改。</p><button type="button" className="btn btn-secondary" onClick={() => setPending(null)}>继续编辑</button><button type="button" className="btn btn-danger" onClick={() => { const action = pending; setPending(null); action() }}>丢弃修改并继续</button></div></div>}
      {!pending && confirmDelete && selected && <div ref={confirmRef} className="ps-confirm" role="alertdialog" aria-modal="true" aria-labelledby="ps-delete-title"><div><h3 id="ps-delete-title">删除接口配置“{selected.name}”？</h3><p>删除后将从接口列表和画布下拉中移除，引用它的已有画布节点需重新选择接口；已提交的任务仍按原版本完成。</p><button type="button" className="btn btn-secondary" onClick={() => setConfirmDelete(false)}>取消</button><button type="button" className="btn btn-danger" onClick={remove}>确认删除</button></div></div>}
    </section>
  </div>
}
