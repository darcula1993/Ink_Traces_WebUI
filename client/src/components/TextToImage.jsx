import React, { useRef } from 'react'
import { Save } from 'lucide-react'

function TextToImage({ prompt, setPrompt, isGenerating, chatMode, onSavePrompt }) {
  const textareaRef = useRef(null)

  return (
    <div className="flex-grow flex flex-col min-h-0 relative bg-transparent">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-nexus-border px-4">
        <span className="text-xs font-medium text-nexus-text-light">图片提示词</span>
        <div className="flex items-center gap-2">
          {chatMode && <span className="status-pill border-nexus-violet/30 bg-nexus-violet/10 text-nexus-violet">连续对话</span>}
          <span className="font-mono text-[11px] text-nexus-muted">{prompt.length}</span>
        </div>
      </div>
      
      <div className="flex-grow min-h-0 relative overflow-hidden">
        <textarea
          ref={textareaRef}
          aria-label="图片提示词"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={isGenerating}
          className="absolute inset-0 resize-none overflow-y-auto whitespace-pre-wrap break-words bg-transparent px-4 py-4 text-sm leading-6 text-nexus-text-light outline-none custom-scrollbar placeholder:text-nexus-muted"
          spellCheck="true"
          placeholder="描述主体、场景、构图、光线与风格..."
        />
      </div>

      <div className="absolute bottom-4 right-4">
        <button 
          type="button"
          aria-label="保存到提示词库"
          title="保存到提示词库"
          onClick={onSavePrompt}
          disabled={!prompt.trim() || isGenerating}
          className="icon-button border-nexus-border bg-nexus-surface shadow-lg hover:text-nexus-green disabled:opacity-40"
        >
          <Save size={16} />
        </button>
      </div>
    </div>
  )
}

export default TextToImage
