import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Build output lands in ../static/dist. Flask mounts that directory at
// static_url_path="/static", so production asset URLs must be rooted there.
// Dev keeps base "/" and proxies /api + /output to the backend.
const isProd = process.env.NODE_ENV === 'production'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  base: isProd ? '/static/' : '/',
  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
  },
  server: {
    // The backend is loopback-only; the dev server proxies to it.
    proxy: {
      '/api': 'http://127.0.0.1:5000',
      // Managed branding assets are served from /output/branding/...
      '/output': 'http://127.0.0.1:5000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.{test,spec}.{js,ts}'],
  },
})
