import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: process.env.PENTAGON_API_URL || env.PENTAGON_API_URL || 'http://127.0.0.1:8000',
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
      },
    },
  }
})
