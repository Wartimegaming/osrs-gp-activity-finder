import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the UI runs on :5173 and forwards API calls to the FastAPI server.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
