import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Build output lands in ../static/dist, which Flask serves in production.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
  },
  server: {
    // The backend is loopback-only; the dev server proxies to it.
    proxy: {
      '/api': 'http://127.0.0.1:5000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.{test,spec}.{js,ts}'],
  },
})
