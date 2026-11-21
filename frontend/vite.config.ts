import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwind()],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api': {
      target: 'http://127.0.0.1:' + Number(process.env.NOVARA_DEV_API_PORT || 8000),
      rewrite: (path) => path.replace(/^\/api/, ''),
    } },
  },
  test: { environment: 'jsdom' },
})
