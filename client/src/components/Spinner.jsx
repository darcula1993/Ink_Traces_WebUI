import React from 'react'

const Spinner = ({ theme = 'dark' }) => {
  return (
    <div className="relative flex items-center justify-center w-6 h-6">
      {/* Outer Ring */}
      <div className={`absolute w-full h-full border-2 ${theme === 'dark' ? 'border-cyan-900' : 'border-cyan-300'} rounded-full`}></div>
      {/* Spinning Segment */}
      <div className={`absolute w-full h-full border-t-2 ${theme === 'dark' ? 'border-cyan-400' : 'border-cyan-600'} rounded-full animate-spin`}></div>
      {/* Inner Pulse */}
      <div className={`absolute w-3 h-3 ${theme === 'dark' ? 'bg-cyan-500' : 'bg-cyan-600'} rounded-full animate-pulse shadow-[0_0_10px_#06b6d4]`}></div>
    </div>
  )
}

export default Spinner
