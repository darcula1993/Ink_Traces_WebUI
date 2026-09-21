import React, { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { AudioLines, CheckCheck, CheckSquare2, Film, Image as ImageIcon, Library, ListChecks, Plus, RefreshCw, Square, Trash2, X } from 'lucide-react'
import IconButton from './ui/IconButton'

const KIND_ICON = {
  image: ImageIcon,
  video: Film,
  audio: AudioLines,
}

function CupsyAssetManager({ open, mode, allowedKinds, onClose, onUse, onPreview, notify }) {
  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [sourceReady, setSourceReady] = useState(true)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedAssetIds, setSelectedAssetIds] = useState(new Set())
  const inputRef = useRef(null)

  const loadAssets = useCallback(async () => {
    setLoading(true)
    try {
      const response = await axios.get('/api/cupsy/assets')
      const nextAssets = response.data.assets || []
      const availableIds = new Set(nextAssets.map(asset => asset.id))
      setAssets(nextAssets)
      setSelectedAssetIds(current => new Set([...current].filter(assetId => availableIds.has(assetId))))
      setSourceReady(response.data.source_ready !== false)
    } catch (error) {
      notify(error.response?.data?.error || 'Cupsy 素材加载失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [notify])

  useEffect(() => {
    if (!open) return
    loadAssets()
    const timer = window.setInterval(loadAssets, 3000)
    return () => window.clearInterval(timer)
  }, [loadAssets, open])

  useEffect(() => {
    if (open) return
    setSelectionMode(false)
    setSelectedAssetIds(new Set())
  }, [open])

  if (!open) return null

  const uploadFiles = async files => {
    const selected = Array.from(files || [])
    if (!selected.length) return
    setUploading(true)
    try {
      for (const file of selected) {
        const form = new FormData()
        form.append('file', file)
        await axios.post('/api/cupsy/assets', form, { timeout: 300000 })
      }
      notify(`${selected.length} 个素材已加入导入队列`)
      await loadAssets()
    } catch (error) {
      notify(error.response?.data?.error || 'Cupsy 素材上传失败', 'error')
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const deleteAsset = async asset => {
    if (!window.confirm(`删除素材“${asset.name || asset.id}”？`)) return
    try {
      await axios.delete(`/api/cupsy/assets/${asset.id}`)
      setAssets(current => current.filter(item => item.id !== asset.id))
      setSelectedAssetIds(current => {
        const next = new Set(current)
        next.delete(asset.id)
        return next
      })
    } catch (error) {
      notify(error.response?.data?.error || 'Cupsy 素材删除失败', 'error')
    }
  }

  const toggleSelectionMode = () => {
    setSelectionMode(current => !current)
    setSelectedAssetIds(new Set())
  }

  const toggleAssetSelection = assetId => {
    setSelectedAssetIds(current => {
      const next = new Set(current)
      if (next.has(assetId)) next.delete(assetId)
      else next.add(assetId)
      return next
    })
  }

  const allSelected = assets.length > 0 && selectedAssetIds.size === assets.length
  const toggleSelectAll = () => {
    setSelectedAssetIds(allSelected ? new Set() : new Set(assets.map(asset => asset.id)))
  }

  const deleteSelectedAssets = async () => {
    const assetIds = [...selectedAssetIds]
    if (!assetIds.length) return
    if (!window.confirm(`永久删除选中的 ${assetIds.length} 个素材？此操作无法撤销。`)) return
    setDeleting(true)
    const removedIds = new Set()
    let deletedCount = 0
    const failed = []
    try {
      for (let offset = 0; offset < assetIds.length; offset += 100) {
        const response = await axios.post('/api/cupsy/assets/bulk-delete', {
          ids: assetIds.slice(offset, offset + 100),
        }, { timeout: 600000 })
        deletedCount += Number(response.data.deleted) || 0
        ;[...(response.data.deleted_ids || []), ...(response.data.missing_ids || [])]
          .forEach(assetId => removedIds.add(Number(assetId)))
        failed.push(...(response.data.failed || []))
      }
      setAssets(current => current.filter(asset => !removedIds.has(asset.id)))
      setSelectedAssetIds(new Set(failed.map(item => Number(item.id))))
      if (failed.length) {
        notify(`已删除 ${deletedCount} 个素材，${failed.length} 个删除失败`, 'error')
      } else {
        notify(`已删除 ${deletedCount} 个素材`)
        setSelectionMode(false)
      }
    } catch (error) {
      notify(error.response?.data?.error || '批量删除素材失败', 'error')
      await loadAssets()
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="cupsy-assets-backdrop" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
      <section className="cupsy-assets-modal" role="dialog" aria-modal="true" aria-label="Cupsy 素材库">
        <header className="cupsy-assets-header">
          <div className="flex items-center gap-2 text-sm font-semibold text-nexus-text-light">
            <Library size={16} className="text-nexus-cyan" /> Cupsy Assets
          </div>
          <div className="flex items-center gap-1">
            <IconButton label="刷新素材" onClick={loadAssets} disabled={loading}><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></IconButton>
            <IconButton label="关闭素材库" onClick={onClose}><X size={16} /></IconButton>
          </div>
        </header>
        <div className="cupsy-assets-toolbar">
          <div className="cupsy-assets-toolbar-actions">
            <button type="button" className="btn-base btn-primary min-h-9 px-3 text-xs" disabled={uploading || deleting || !sourceReady} title={sourceReady ? '添加素材' : '需要配置公网 HTTP(S) 素材源'} onClick={() => inputRef.current?.click()}>
              <Plus size={14} /> {uploading ? '上传中' : sourceReady ? '添加素材' : '公网源未配置'}
            </button>
            <button type="button" className={`cupsy-assets-command ${selectionMode ? 'active' : ''}`} aria-pressed={selectionMode} onClick={toggleSelectionMode} disabled={deleting || assets.length === 0}>
              {selectionMode ? <X size={14} /> : <ListChecks size={14} />}
              {selectionMode ? '退出选择' : '批量选择'}
            </button>
            {selectionMode && <>
              <button type="button" className={`cupsy-assets-command ${allSelected ? 'active' : ''}`} onClick={toggleSelectAll} disabled={deleting}>
                <CheckCheck size={14} /> {allSelected ? '取消全选' : '全选'}
              </button>
              <button type="button" className="cupsy-assets-command danger" onClick={deleteSelectedAssets} disabled={deleting || selectedAssetIds.size === 0}>
                <Trash2 size={14} /> {deleting ? '删除中' : `删除 (${selectedAssetIds.size})`}
              </button>
            </>}
          </div>
          <input ref={inputRef} className="hidden" type="file" accept="image/*,video/mp4,video/quicktime,audio/wav,audio/mp3,audio/mpeg" multiple onChange={event => uploadFiles(event.target.files)} />
          <span className="text-xs text-nexus-muted">{selectionMode ? `已选 ${selectedAssetIds.size} / ` : ''}{assets.length} 个素材</span>
        </div>
        <div className="cupsy-assets-grid custom-scrollbar">
          {!loading && assets.length === 0 && <div className="cupsy-assets-empty">暂无素材</div>}
          {assets.map(asset => {
            const KindIcon = KIND_ICON[asset.kind] || Library
            const ready = asset.status === 'active'
            const allowed = !allowedKinds || allowedKinds.includes(asset.kind)
            const selected = selectedAssetIds.has(asset.id)
            const selectionLabel = `${selected ? '取消选择' : '选择'}素材 ${asset.name || asset.id}`
            return (
              <article className={`cupsy-asset-card ${selected ? 'selected' : ''}`} key={asset.id}>
                {selectionMode && (
                  <button type="button" className="cupsy-asset-selector" aria-label={selectionLabel} aria-pressed={selected} onClick={() => toggleAssetSelection(asset.id)}>
                    {selected ? <CheckSquare2 size={17} /> : <Square size={17} />}
                  </button>
                )}
                <button type="button" className="cupsy-asset-preview" onClick={() => selectionMode ? toggleAssetSelection(asset.id) : onPreview({ type: asset.kind, src: asset.content_url, name: asset.name })}>
                  {asset.kind === 'image' && <img src={asset.content_url} alt={asset.name || 'Cupsy 素材'} />}
                  {asset.kind === 'video' && <video src={asset.content_url} muted preload="metadata" />}
                  {asset.kind === 'audio' && <AudioLines size={26} className="text-nexus-cyan" />}
                  <KindIcon size={13} className="cupsy-asset-kind" />
                </button>
                <div className="cupsy-asset-meta">
                  <div className="truncate text-xs text-nexus-text-light" title={asset.name}>{asset.name || `Asset ${asset.id}`}</div>
                  <div className={`cupsy-asset-status status-${asset.status}`}>{asset.status}</div>
                </div>
                {asset.error && <div className="cupsy-asset-error" title={asset.error}>{asset.error}</div>}
                <div className="cupsy-asset-actions">
                  {selectionMode ? (
                    <button type="button" className={selected ? 'selected' : ''} onClick={() => toggleAssetSelection(asset.id)}>{selected ? '已选择' : '选择素材'}</button>
                  ) : mode === 'keyframe' && asset.kind === 'image' ? <>
                    <button type="button" disabled={!ready} onClick={() => onUse(asset, 'first_frame')}>首帧</button>
                    <button type="button" disabled={!ready} onClick={() => onUse(asset, 'last_frame')}>尾帧</button>
                  </> : (
                    <button type="button" disabled={!ready || mode === 'keyframe' || !allowed} title={allowed ? '引用素材' : '当前模式不支持此素材'} onClick={() => onUse(asset, `reference_${asset.kind}`)}>引用</button>
                  )}
                  {!selectionMode && <button type="button" className="danger" title="删除素材" aria-label={`删除素材 ${asset.name || asset.id}`} onClick={() => deleteAsset(asset)}><Trash2 size={13} /></button>}
                </div>
              </article>
            )
          })}
        </div>
      </section>
    </div>
  )
}

export default CupsyAssetManager
