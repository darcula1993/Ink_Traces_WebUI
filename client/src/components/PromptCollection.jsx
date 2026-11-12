import React, { useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import { Check, Edit2, Library, Search, Trash2, X } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'

function PromptCollection({ onSelectPrompt }) {
  const [prompts, setPrompts] = useState([])
  const [editingId, setEditingId] = useState(null)
  const [editingText, setEditingText] = useState('')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const loadPrompts = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await axios.get('/api/prompts')
      if (response.data.success) setPrompts(response.data.prompts)
      else setError('提示词同步失败')
    } catch (requestError) {
      setError('无法加载提示词库')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadPrompts() }, [])

  const visiblePrompts = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return needle ? prompts.filter(prompt => prompt.text.toLowerCase().includes(needle)) : prompts
  }, [prompts, query])

  const startEditing = (id, text) => {
    setEditingId(id)
    setEditingText(text)
  }

  const cancelEditing = () => {
    setEditingId(null)
    setEditingText('')
  }

  const saveEdit = async () => {
    if (!editingText.trim()) return
    try {
      setLoading(true)
      const response = await axios.put(`/api/prompts/${editingId}`, { text: editingText.trim() })
      if (!response.data.success) throw new Error('Update failed')
      await loadPrompts()
      cancelEditing()
    } catch (requestError) {
      window.alert('保存失败')
    } finally {
      setLoading(false)
    }
  }

  const deletePrompt = async (id) => {
    if (!window.confirm('删除这条提示词？')) return
    try {
      setLoading(true)
      const response = await axios.delete(`/api/prompts/${id}`)
      if (!response.data.success) throw new Error('Delete failed')
      await loadPrompts()
    } catch (requestError) {
      window.alert('删除失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="drawer-content flex h-full flex-col">
      <div className="shrink-0 border-b border-nexus-border p-3">
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-nexus-muted" />
          <input
            value={query}
            onChange={event => setQuery(event.target.value)}
            aria-label="搜索提示词"
            placeholder="搜索提示词"
            className="h-9 w-full rounded-md border border-nexus-border bg-nexus-bg pl-9 pr-3 text-sm text-nexus-text-light outline-none placeholder:text-nexus-muted focus:border-nexus-blue"
          />
        </div>
        {error && (
          <div className="mt-2 flex items-center justify-between rounded border border-nexus-red/25 bg-nexus-red/10 px-3 py-2 text-xs text-nexus-red">
            <span>{error}</span>
            <button type="button" onClick={loadPrompts} className="font-medium hover:text-white">重试</button>
          </div>
        )}
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-3 custom-scrollbar">
        {loading && prompts.length === 0 ? (
          <div className="flex h-32 items-center justify-center">
            <div className="size-6 animate-spin rounded-full border-2 border-nexus-green border-t-transparent" />
          </div>
        ) : visiblePrompts.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center text-center text-nexus-muted">
            <Library size={30} className="mb-3 opacity-40" />
            <p className="text-sm">{query ? '没有匹配的提示词' : '提示词库为空'}</p>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {visiblePrompts.map(prompt => (
              <motion.article
                key={prompt.id}
                layout
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.98 }}
                className="overflow-hidden rounded-md border border-nexus-border bg-nexus-surface/55 transition-colors hover:border-nexus-border-hover hover:bg-nexus-surface"
              >
                {editingId === prompt.id ? (
                  <div className="p-3">
                    <textarea
                      value={editingText}
                      onChange={event => setEditingText(event.target.value)}
                      aria-label="编辑提示词"
                      rows={5}
                      className="w-full resize-none rounded-md border border-nexus-border bg-nexus-bg p-2.5 text-sm leading-5 text-nexus-text-light outline-none focus:border-nexus-blue"
                      autoFocus
                    />
                    <div className="mt-2 flex justify-end gap-1">
                      <button type="button" aria-label="取消编辑" title="取消" onClick={cancelEditing} className="icon-button size-8"><X size={14} /></button>
                      <button type="button" aria-label="保存提示词" title="保存" onClick={saveEdit} disabled={loading || !editingText.trim()} className="icon-button size-8 text-nexus-green"><Check size={14} /></button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => onSelectPrompt?.(prompt.text)}
                      onKeyDown={event => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          onSelectPrompt?.(prompt.text)
                        }
                      }}
                      className="cursor-pointer px-3 py-3 focus-visible:outline-2 focus-visible:outline-nexus-blue"
                    >
                      <p className="line-clamp-4 text-sm leading-5 text-nexus-text-light">{prompt.text}</p>
                    </div>
                    <div className="flex items-center border-t border-nexus-border/70 px-2 py-1.5">
                      <time className="px-1 text-[11px] text-nexus-muted">
                        {new Date(prompt.createdAt).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}
                      </time>
                      <div className="ml-auto flex items-center gap-1">
                        <button type="button" aria-label="编辑提示词" title="编辑" onClick={() => startEditing(prompt.id, prompt.text)} disabled={loading} className="icon-button size-8"><Edit2 size={14} /></button>
                        <button type="button" aria-label="删除提示词" title="删除" onClick={() => deletePrompt(prompt.id)} disabled={loading} className="icon-button size-8 hover:text-nexus-red"><Trash2 size={14} /></button>
                      </div>
                    </div>
                  </>
                )}
              </motion.article>
            ))}
          </AnimatePresence>
        )}
      </div>

      <div className="shrink-0 border-t border-nexus-border px-3 py-2 text-xs text-nexus-muted">
        {query ? `${visiblePrompts.length} 条匹配` : `共 ${prompts.length} 条提示词`}
      </div>
    </div>
  )
}

export default PromptCollection
