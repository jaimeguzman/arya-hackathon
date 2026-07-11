import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard talks to the backend API (local/backend/api/app.py) at :8010.
// Proxying /api avoids CORS entirely. Override the target with VITE_API_TARGET.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8010'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
