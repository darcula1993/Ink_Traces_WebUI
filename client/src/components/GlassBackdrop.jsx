import React from 'react'

const CODE_LINES = [
  'const frame = await stream.next();',
  'buffer[index] = signal ^ 0x7f;',
  'if (ready) commit(renderPass);',
  'matrix[row][col] += delta;',
  'pipeline.bind(texture, sampler);',
  '10110110 :: 0xA3 :: SYNC',
  'for (let i = 0; i < depth; i++)',
  'return compose(layer, source);',
  'cache.set(key, payload);',
  'kernel.dispatch(grid, groups);',
  'await queue.flush();',
  'trace.emit({ x, y, alpha });',
]

const TRACKS = [
  { className: 'glass-code-track-a', lines: [...CODE_LINES, ...CODE_LINES] },
  { className: 'glass-code-track-b', lines: [...CODE_LINES].reverse().concat([...CODE_LINES].reverse()) },
]

export default function GlassBackdrop() {
  return (
    <div className="glass-backdrop" aria-hidden="true">
      {TRACKS.map(track => (
        <div key={track.className} className={`glass-code-track ${track.className}`}>
          {track.lines.map((line, index) => <span key={`${index}-${line}`}>{line}</span>)}
        </div>
      ))}
    </div>
  )
}
