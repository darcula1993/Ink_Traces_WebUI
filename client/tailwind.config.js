/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'nexus-bg': '#0a0a0a',
        'nexus-panel': '#111111',
        'nexus-border': '#222222',
        'nexus-green': '#10b981', // emerald-500
        'nexus-green-dim': 'rgba(16, 185, 129, 0.1)',
        'nexus-text': '#888888',
        'nexus-text-light': '#cccccc',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'Menlo', 'Monaco', 'Courier New', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      backgroundImage: {
        'nexus-grid': "radial-gradient(circle, #222 1px, transparent 1px)",
      },
      backgroundSize: {
        'nexus-grid-size': '20px 20px',
      }
    }
  },
  plugins: [],
}