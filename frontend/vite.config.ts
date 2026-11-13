import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend listens on loopback only. Proxying keeps the browser on a single
// origin, so the backend needs no CORS configuration.
const BACKEND = process.env.PTM_BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND },
      '/ws': { target: BACKEND, ws: true },
    },
  },
})
