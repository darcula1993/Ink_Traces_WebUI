import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

// 读取配置文件
let config = {
  server: { host: '0.0.0.0', port: 5000 },
  client: { host: '0.0.0.0', port: 4545 }
}

try {
  const configPath = path.resolve(__dirname, '../config.json')
  const configFile = fs.readFileSync(configPath, 'utf-8')
  config = JSON.parse(configFile)
} catch (e) {
  console.warn('Failed to load config.json, using default configuration')
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [{ find: /^react-konva$/, replacement: path.resolve(__dirname, 'src/lib/konvaMinimal.js') }],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('commonjsHelpers')) return 'vendor-react'
          if (!id.includes('/node_modules/')) return
          if (/\/(react|react-dom|scheduler)\//.test(id)) return 'vendor-react'
          if (id.includes('/lucide-react/')) return 'vendor-icons'
          if (/\/(konva|react-konva|react-reconciler)\//.test(id)) return 'vendor-konva'
        },
      },
    },
  },
  server: {
    host: config.client.host,
    port: config.client.port,
    proxy: {
      '/api': {
        target: `http://localhost:${config.server.port}`,
        // Preserve the browser Host for same-origin credential configuration checks.
        changeOrigin: false,
        timeout: 300000,
        proxyTimeout: 300000,
      }
    }
  }
})
