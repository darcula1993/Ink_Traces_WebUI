import React, { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import LibraryDialog from './library/LibraryDialog'
import FolderSelect from './library/FolderSelect'
import { listMediaFolders } from '../lib/libraryApi'
import { notifyLibraryChanged } from '../lib/librarySync'
import { folderPathLabel, libraryErrorText, uploadFolderOptions } from './library/mediaLibrary'
import { renderLayerDocument } from '../lib/layerExport'
import './library/library.css'

function defaultFilename(project, selectedLayer, target) {
  const base = String(project?.name || '图层项目').trim() || '图层项目'
  if (target === 'layer' && selectedLayer) {
    const layerName = String(selectedLayer.name || 'layer').trim() || 'layer'
    return `${base}-${layerName}.png`
  }
  return `${base}-合成.png`
}

export default function LayerSaveToLibraryDialog({
  project,
  documentState,
  selectedLayer,
  initialTarget = 'composite',
  canvasContext = null,
  onReturnToCanvas = null,
  onClose,
  onLocate,
  notify,
}) {
  const canSaveLayer = Boolean(selectedLayer?.local_url)
  const [target, setTarget] = useState(initialTarget === 'layer' && canSaveLayer ? 'layer' : 'composite')
  const [name, setName] = useState(() => defaultFilename(project, selectedLayer, initialTarget === 'layer' && canSaveLayer ? 'layer' : 'composite'))
  const [nameEdited, setNameEdited] = useState(false)
  const [folders, setFolders] = useState(null)
  const [folderId, setFolderId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [outcome, setOutcome] = useState(null)
  const alive = useRef(true)

  const loadFolders = useCallback(async () => {
    const list = await listMediaFolders()
    if (alive.current) setFolders(list)
    return list
  }, [])

  useEffect(() => {
    alive.current = true
    loadFolders().catch(err => {
      if (alive.current) setError(libraryErrorText(err, '无法载入素材库文件夹'))
    })
    return () => { alive.current = false }
  }, [loadFolders])

  const switchTarget = nextTarget => {
    setTarget(nextTarget)
    if (!nameEdited) setName(defaultFilename(project, selectedLayer, nextTarget))
  }

  const handleSave = async () => {
    if (busy || !project?.id) return
    const trimmed = name.trim() || defaultFilename(project, selectedLayer, target)
    const fileName = /\.[a-z0-9]+$/i.test(trimmed) ? trimmed : `${trimmed}.png`
    setBusy(true)
    setError('')
    try {
      let response
      if (target === 'layer' && selectedLayer) {
        if (String(selectedLayer.local_url || '').startsWith('/api/tasks/')) {
          response = await axios.post(`/api/layer/projects/${project.id}/save-to-library`, {
            layer_id: selectedLayer.id,
            name: fileName,
            folder_id: folderId || null,
          })
        } else {
          const fetched = await fetch(selectedLayer.local_url)
          if (!fetched.ok) throw new Error('无法读取当前图层图像')
          const blob = await fetched.blob()
          const body = new FormData()
          body.append('file', blob, fileName)
          body.append('name', fileName)
          if (folderId) body.append('folder_id', folderId)
          response = await axios.post(`/api/layer/projects/${project.id}/save-to-library`, body)
        }
      } else {
        const blob = await renderLayerDocument(documentState, 'png')
        const body = new FormData()
        body.append('file', blob, fileName)
        body.append('name', fileName)
        if (folderId) body.append('folder_id', folderId)
        response = await axios.post(`/api/layer/projects/${project.id}/save-to-library`, body)
      }
      if (!alive.current) return
      const { media, deduplicated } = response.data
      notifyLibraryChanged({ source: 'save_as', folderId: media.folder_id || null, mediaId: media.id })
      const where = media.folder_id && folders ? `“${folderPathLabel(folders, media.folder_id) || '文件夹'}”` : '“根目录”'
      const text = deduplicated
        ? `内容已在素材库中：「${media.name}」位于${where}，未重复保存。`
        : `已保存到全局素材库${where}：「${media.name}」。`
      setOutcome({ media, deduplicated: Boolean(deduplicated), text })
      notify?.(text)
    } catch (err) {
      if (alive.current) setError(libraryErrorText(err, '保存到素材库失败'))
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  return (
    <LibraryDialog
      title={target === 'layer' ? '另存图层到全局素材库' : '另存合成图到全局素材库'}
      className="ul-subdialog-top"
      busy={busy}
      error={error}
      onClose={onClose}
      onConfirm={outcome ? null : handleSave}
      disabled={!folders || busy}
      confirmLabel="保存到素材库"
      cancelLabel={outcome ? '完成' : '取消'}
    >
      {outcome ? (
        <div className="layer-save-outcome" data-testid="layer-save-library-outcome">
          <p role="status"><strong>{outcome.text}</strong></p>
          <div className="layer-save-outcome-actions">
            {canvasContext?.workflowId && onReturnToCanvas && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                data-testid="layer-save-library-return-canvas"
                onClick={() => onReturnToCanvas(outcome.media)}
              >
                作为素材节点回到原画布
              </button>
            )}
            {onLocate && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                data-testid="layer-save-library-locate"
                onClick={() => onLocate(outcome.media)}
              >
                在素材库中定位
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="layer-save-form">
          {canSaveLayer && (
            <div className="layer-save-target" role="radiogroup" aria-label="保存内容">
              <label className="layer-save-radio-option">
                <input
                  type="radio"
                  name="layer-save-target"
                  value="composite"
                  checked={target === 'composite'}
                  disabled={busy}
                  onChange={() => switchTarget('composite')}
                />
                <span className="layer-save-radio-text">当前画布合成图</span>
              </label>
              <label className="layer-save-radio-option">
                <input
                  type="radio"
                  name="layer-save-target"
                  value="layer"
                  checked={target === 'layer'}
                  disabled={busy}
                  onChange={() => switchTarget('layer')}
                />
                <span className="layer-save-radio-text">当前选中图层（{selectedLayer.name}）</span>
              </label>
            </div>
          )}
          <label className="layer-save-name-field">
            <span>素材名称</span>
            <input
              aria-label="素材名称"
              value={name}
              maxLength={240}
              disabled={busy}
              onChange={event => {
                setName(event.target.value)
                setNameEdited(true)
              }}
            />
          </label>
          {folders ? (
            <FolderSelect
              label="目标文件夹"
              folders={folders}
              options={uploadFolderOptions(folders)}
              value={folderId}
              onChange={setFolderId}
              onCreated={loadFolders}
              disabled={busy}
            />
          ) : !error ? (
            <p role="status">正在载入文件夹…</p>
          ) : null}
          <p className="ul-muted">
            将作为独立素材存入全局素材库（默认根目录，不写入“生成历史”）；后续删除图层项目不会影响素材库中的文件。
          </p>
        </div>
      )}
    </LibraryDialog>
  )
}
