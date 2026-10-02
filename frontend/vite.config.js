import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Pin the port so the ngrok tunnel always targets the right place.
    port: 5173,
    // Allow the dev server to be reached through an ngrok tunnel
    // (Vite blocks unknown Host headers by default).
    allowedHosts: true,
    proxy: {
      // Forward API calls to the FastAPI backend so the whole app
      // can be shared through a single ngrok tunnel.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
