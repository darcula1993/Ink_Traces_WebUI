import React, { useEffect, useMemo, useRef, useState } from 'react'
import { BookmarkPlus, Check, CornerDownLeft, Edit2, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { canSavePrompt, filterPrompts, nextActiveIndex } from '../../lib/promptLibrary'
import { PromptLibraryList, usePromptLibrary } from './PromptLibraryPicker'
import askConfirm from '../ui/askConfirm'
import './canvasPromptPanel.css'

// CANVAS-LAYOUT-2-20261118 + P0-UI-FIXES-20261120 (P0-4):
// Rail panel "提示词库" — search, list, preview, insert into the selected node, plus create / save / edit / delete.
export default function CanvasPromptPanel({
  onInsert,
  insertDisabledReason = '请先选中一个生成节点',
  targetLabel = '',
  selectedPromptText = '',
}) {
  const { prompts, status, loading, load, createPrompt, updatePrompt, deletePrompt } = usePromptLibrary()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [notice, setNotice] = useState('')
  const [creating, setCreating] = useState(false)
  const [draftText, setDraftText] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editingText, setEditingText] = useState('')
  const searchRef = useRef(null)
  const visible = useMemo(() => filterPrompts(prompts, query), [prompts, query])

  useEffect(() => { load() }, [])
  useEffect(() => { setActive(0) }, [query])
  useEffect(() => {
    if (visible.length === 0) setActive(0)
    else if (active >= visible.length) setActive(visible.length - 1)
  }, [visible.length, active])

  const current = visible[Math.min(active, Math.max(0, visible.length - 1))] || null
  const disabled = !!insertDisabledReason || !current || typeof onInsert !== 'function'
  const reason = insertDisabledReason || (!current ? '没有可插入的提示词' : '')
  const canSaveSelected = canSavePrompt(selectedPromptText)

  const insert = prompt => {
    if (!prompt || insertDisabledReason || typeof onInsert !== 'function') return
    onInsert(prompt.text)
    setNotice(targetLabel ? `已插入到「${targetLabel}」` : '已插入到选中节点')
  }

  const startCreate = () => {
    setEditingId(null)
    setEditingText('')
    setCreating(true)
    setDraftText('')
    setNotice('')
  }

  const cancelCreate = () => {
    setCreating(false)
    setDraftText('')
  }

  const saveCreate = async () => {
    if (!canSavePrompt(draftText)) return
    const result = await createPrompt(draftText)
    if (result.ok) {
      setCreating(false)
      setDraftText('')
      setNotice('')
    }
  }

  const saveCurrentNodePrompt = async () => {
    if (!canSaveSelected) return
    setNotice('')
    await createPrompt(selectedPromptText)
  }

  const startEdit = prompt => {
    if (!prompt) return
    setCreating(false)
    setDraftText('')
    setEditingId(prompt.id)
    setEditingText(prompt.text || '')
    setNotice('')
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditingText('')
  }

  const saveEdit = async () => {
    if (editingId == null || !canSavePrompt(editingText)) return
    const result = await updatePrompt(editingId, editingText)
    if (result.ok) {
      setEditingId(null)
      setEditingText('')
      setNotice('')
    }
  }

  const removeCurrent = async prompt => {
    if (!prompt) return
    const confirmed = await askConfirm({
      title: '删除提示词',
      message: '删除这条提示词？',
      confirmLabel: '删除',
      danger: true,
    })
    if (!confirmed) return
    if (editingId === prompt.id) cancelEdit()
    setNotice('')
    await deletePrompt(prompt.id)
  }

  const onKeyDown = event => {
    if (event.key === 'Escape' && (creating || editingId != null)) {
      event.preventDefault()
      event.stopPropagation()
      if (creating) cancelCreate()
      if (editingId != null) cancelEdit()
      return
    }
    if (creating || editingId != null) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setActive(index => nextActiveIndex(index, visible.length, event.key))
    } else if (event.key === 'Enter' && !event.nativeEvent?.isComposing && event.target === searchRef.current) {
      event.preventDefault()
      insert(current)
    }
  }

  const isEditingCurrent = current && editingId === current.id

  return (
    <div className="cv-panel-prompts" onKeyDown={onKeyDown}>
      <div className="cv-panel-prompts-toolbar">
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={loading}
          aria-expanded={creating}
          onClick={() => (creating ? cancelCreate() : startCreate())}
        >
          <Plus size={13} aria-hidden="true" />
          新建提示词
        </button>
        {canSaveSelected && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={loading}
            title={targetLabel ? `把「${targetLabel}」的提示词存入提示词库` : '把当前选中节点的提示词存入提示词库'}
            onClick={saveCurrentNodePrompt}
          >
            <BookmarkPlus size={13} aria-hidden="true" />
            存入当前节点
          </button>
        )}
      </div>

      {creating && (
        <div className="cv-panel-prompts-editor" role="form" aria-label="新建提示词表单">
          <textarea
            aria-label="新提示词内容"
            placeholder="输入要保存的提示词…"
            value={draftText}
            autoFocus
            disabled={loading}
            onChange={event => setDraftText(event.target.value)}
          />
          <div className="cv-panel-prompts-editor-actions">
            <button type="button" className="btn btn-ghost btn-sm" disabled={loading} onClick={cancelCreate}>
              <X size={13} aria-hidden="true" />
              取消
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={loading || !canSavePrompt(draftText)}
              onClick={saveCreate}
            >
              <Check size={13} aria-hidden="true" />
              保存新提示词
            </button>
          </div>
        </div>
      )}

      <div className="cv-panel-prompts-search">
        <PromptLibraryList
          listId="cv-prompt-panel-list"
          optionPrefix="cv-prompt-panel-option-"
          inputRef={searchRef}
          query={query}
          onQuery={setQuery}
          prompts={prompts}
          visible={visible}
          active={active}
          onActive={setActive}
          onPick={(prompt, index) => {
            setActive(index)
            if (editingId != null && editingId !== prompt.id) cancelEdit()
          }}
          loading={loading}
          pickOn="click"
          optionTitle="选择以预览"
        />
      </div>

      {current && (
        isEditingCurrent ? (
          <div className="cv-panel-prompts-editor" role="form" aria-label="编辑提示词表单">
            <textarea
              aria-label="编辑提示词"
              value={editingText}
              autoFocus
              disabled={loading}
              onChange={event => setEditingText(event.target.value)}
            />
            <div className="cv-panel-prompts-editor-actions">
              <button type="button" className="btn btn-ghost btn-sm" aria-label="取消编辑" disabled={loading} onClick={cancelEdit}>
                <X size={13} aria-hidden="true" />
                取消
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                aria-label="保存提示词"
                disabled={loading || !canSavePrompt(editingText)}
                onClick={saveEdit}
              >
                <Check size={13} aria-hidden="true" />
                保存
              </button>
            </div>
          </div>
        ) : (
          <section className="cv-panel-prompts-preview" aria-label="提示词预览">
            <div className="cv-panel-prompts-preview-head">
              <span>提示词预览</span>
              <div className="cv-panel-prompts-preview-tools">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm btn-icon"
                  aria-label="编辑提示词"
                  title="编辑提示词"
                  disabled={loading}
                  onClick={() => startEdit(current)}
                >
                  <Edit2 size={13} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm btn-icon btn-danger"
                  aria-label="删除提示词"
                  title="删除提示词"
                  disabled={loading}
                  onClick={() => removeCurrent(current)}
                >
                  <Trash2 size={13} aria-hidden="true" />
                </button>
              </div>
            </div>
            <p>{current.text}</p>
          </section>
        )
      )}

      <div className="cv-panel-prompts-actions">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={disabled}
          aria-describedby={reason ? 'cv-prompt-panel-reason' : undefined}
          title={reason || '插入到选中节点提示词的光标处'}
          onClick={() => insert(current)}
        >
          <CornerDownLeft size={13} aria-hidden="true" />
          插入到选中节点
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm btn-icon"
          aria-label="刷新提示词库"
          title="刷新提示词库"
          disabled={loading}
          onClick={load}
        >
          <RefreshCw size={13} aria-hidden="true" />
        </button>
      </div>

      {reason && <small id="cv-prompt-panel-reason" className="cv-panel-hint">{reason}</small>}
      <span className="cv-panel-status" role="status" aria-live="polite">{status || notice}</span>
    </div>
  )
}
