import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { Library, Trash2, Edit2 } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

function PromptCollection({ theme, currentPrompt, onSelectPrompt }) {
  const [prompts, setPrompts] = useState([])
  const [editingId, setEditingId] = useState(null)
  const [editingText, setEditingText] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { loadPrompts() }, [])

  const loadPrompts = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await axios.get('/api/prompts')
      if (response.data.success) setPrompts(response.data.prompts)
      else setError('数据同步失败')
    } catch (e) {
      setError('无法连接核心数据库')
    } finally {
      setLoading(false)
    }
  }

  const handleEditPrompt = (id, text) => {
    setEditingId(id)
    setEditingText(text)
  }

  const handleSaveEdit = async () => {
    if (!editingText.trim()) return
    try {
      setLoading(true)
      const response = await axios.put(`/api/prompts/${editingId}`, { text: editingText.trim() })
      if (response.data.success) {
        await loadPrompts()
        setEditingId(null)
        setEditingText('')
      } else alert('指令覆写失败')
    } catch (e) { alert('指令覆写失败') } 
    finally { setLoading(false) }
  }

  const handleDeletePrompt = async (id) => {
    if (!confirm('确认永久销毁该序列？')) return
    try {
      setLoading(true)
      const response = await axios.delete(`/api/prompts/${id}`)
      if (response.data.success) await loadPrompts()
      else alert('数据销毁失败')
    } catch (e) { alert('数据销毁失败') } 
    finally { setLoading(false) }
  }

  return (
    <div className="flex flex-col h-full gap-4">
      {error && (
        <div className="p-3 border-l-4 text-xs font-mono flex items-center justify-between bg-red-950/50 text-red-400 border-red-500">
          <span>[ERR] {error}</span>
          <button onClick={loadPrompts} className="underline hover:no-underline font-bold">RETRY</button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto pr-2 space-y-2 custom-scrollbar">
        {loading && prompts.length === 0 ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-8 h-8 border-2 border-t-transparent border-nexus-green rounded-full animate-spin"></div>
          </div>
        ) : prompts.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-center border border-dashed border-nexus-border text-nexus-text">
            <Library size={32} className="mb-3 opacity-30" />
            <p className="text-xs font-bold tracking-widest uppercase">库区离线</p>
            <p className="text-[10px] mt-1 font-mono uppercase opacity-50">DATA NOT FOUND</p>
          </div>
        ) : (
          <AnimatePresence>
            {prompts.map((prompt) => (
              <motion.div
                key={prompt.id}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="group relative border border-nexus-border bg-[#111] hover:border-nexus-green/40 hover:bg-nexus-green-dim transition-all duration-200"
              >
                {editingId === prompt.id ? (
                  <div className="p-3">
                    <textarea
                      value={editingText}
                      onChange={(e) => setEditingText(e.target.value)}
                      rows={3}
                      className="w-full p-2 text-sm font-mono border border-nexus-border bg-nexus-bg text-nexus-text-light outline-none resize-none focus:border-nexus-green/50"
                      autoFocus
                    />
                    <div className="flex gap-2 justify-end mt-2">
                      <button onClick={() => setEditingId(null)} className="px-3 py-1 text-xs font-mono tracking-widest border border-nexus-border text-nexus-text hover:bg-white/5 transition-colors">
                        取消
                      </button>
                      <button onClick={handleSaveEdit} className="px-3 py-1 text-xs font-mono tracking-widest border border-nexus-green/40 text-nexus-green bg-nexus-green-dim hover:bg-nexus-green/20 transition-colors">
                        覆写
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="p-3 cursor-pointer" onClick={() => onSelectPrompt && onSelectPrompt(prompt.text)}>
                    <p className="text-xs font-mono leading-relaxed line-clamp-3 mb-3 text-nexus-text-light">
                      {prompt.text}
                    </p>
                    <div className="flex items-center justify-between border-t border-nexus-border/50 pt-2">
                      <span className="text-[10px] font-mono tracking-wider text-nexus-text/60">
                        {new Date(prompt.createdAt).toLocaleDateString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
                        <button
                          onClick={() => handleEditPrompt(prompt.id, prompt.text)} disabled={loading}
                          className="p-1 border border-nexus-border text-nexus-text hover:text-nexus-green hover:border-nexus-green/40 transition-colors"
                        >
                          <Edit2 size={11} />
                        </button>
                        <button
                          onClick={() => handleDeletePrompt(prompt.id)} disabled={loading}
                          className="p-1 border border-nexus-border text-nexus-text hover:text-red-400 hover:border-red-500/40 transition-colors"
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </div>
      
      {prompts.length > 0 && (
        <div className="pt-2 mt-auto border-t border-nexus-border text-center text-[10px] font-mono tracking-[0.2em] uppercase text-nexus-text/50">
          DATA.LEN // {prompts.length}
        </div>
      )}
    </div>
  )
}

export default PromptCollection
