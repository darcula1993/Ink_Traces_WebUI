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
  server: {
    host: config.client.host,
    port: config.client.port,
    proxy: {
      '/api': {
        target: `http://localhost:${config.server.port}`,
        changeOrigin: true,
      }
    }
  }
})
