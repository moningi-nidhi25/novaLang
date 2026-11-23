import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser talks to /api on its own origin; Vite forwards it to FastAPI.
// Start the backend with:  uvicorn backend.main:app --port 8000
const api = { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } }

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: api },
  preview: { port: 4173, proxy: api },
  test: {
    environment: 'jsdom',
    globals: true, // lets Testing Library clean the DOM between tests
    setupFiles: ['./src/test/setup.js'],
  },
})
