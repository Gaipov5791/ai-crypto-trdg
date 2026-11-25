import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    hmr: {
      host: "127.0.0.1",
    },
    proxy: {
      "/health": "http://127.0.0.1:8000",
      "/market": "http://127.0.0.1:8000",
      "/paper": "http://127.0.0.1:8000",
      "/signals": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
})
