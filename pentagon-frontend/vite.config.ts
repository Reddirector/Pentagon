import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendUrl = process.env.VITE_API_BASE_URL || env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: '127.0.0.1',
      proxy: {
        '/api': { target: backendUrl, changeOrigin: true, timeout: 0, proxyTimeout: 0 },
      },
    },
  }
})
