import React, { useRef } from 'react'
import { Save } from 'lucide-react'

function TextToImage({ prompt, setPrompt, isGenerating, chatMode, onSavePrompt }) {
  const textareaRef = useRef(null)

  return (
    <div className="flex-grow flex flex-col min-h-0 relative bg-nexus-bg">
      <div className="absolute top-4 left-4 text-xs font-mono text-nexus-text opacity-50 z-10 pointer-events-none">
        // Imported from vault<br/>
      </div>
      
      <div className="flex-grow min-h-0 relative mt-8 overflow-hidden">
        <textarea
          ref={textareaRef}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={isGenerating}
          className="absolute inset-0 px-4 py-4 bg-transparent text-[#2ecc71] text-sm font-mono leading-6 outline-none resize-none whitespace-pre-wrap break-words overflow-y-auto selection:bg-[#2ecc71]/20 selection:text-white custom-scrollbar"
          spellCheck="false"
          placeholder="A futuristic cyberpunk city street, neon lights..."
        />
      </div>

      <div className="absolute bottom-4 right-4">
        <button 
          onClick={onSavePrompt}
          disabled={!prompt.trim() || isGenerating}
          className="p-2.5 rounded bg-[#111] border border-nexus-border text-nexus-text hover:text-nexus-green hover:border-nexus-green transition-colors disabled:opacity-50"
        >
          <Save size={16} />
        </button>
      </div>
    </div>
  )
}

export default TextToImage
