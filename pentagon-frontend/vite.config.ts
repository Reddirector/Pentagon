import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendUrl = process.env.BACKEND_URL || process.env.VITE_API_BASE_URL || env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
  return {
    base: process.env.VITE_BASE_PATH || './',
    plugins: [react(), tailwindcss()],
    server: {
      host: '127.0.0.1',
      proxy: {
        '/api': { target: backendUrl, changeOrigin: true, timeout: 0, proxyTimeout: 0 },
      },
    },
    build: {
      chunkSizeWarningLimit: 600,
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            if (id.includes('node_modules/katex') || id.includes('rehype-katex') || id.includes('remark-math')) {
              return 'katex'
            }
            if (id.includes('node_modules/react-markdown') || id.includes('remark-gfm')) {
              return 'markdown'
            }
            if (id.includes('node_modules/@supabase')) {
              return 'supabase'
            }
          },
        },
      },
    },
  }
})
