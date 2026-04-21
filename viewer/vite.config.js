import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

function getPackageName(id) {
  const normalized = id.split('node_modules/')[1]
  if (!normalized) return null
  const parts = normalized.split('/')
  return parts[0].startsWith('@') ? `${parts[0]}/${parts[1]}` : parts[0]
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Pre-bundler Mermaid pour éviter l'erreur "text/html is not a valid JavaScript MIME type"
  // causée par les imports dynamiques internes de Mermaid v10/v11 qui échouent sans pre-bundling.
  optimizeDeps: {
    include: ['mermaid'],
  },
  server: {
    port: 5173,
    proxy: {
      // En développement, proxy /api → Flask (port 5050)
      '/api': {
        target: 'http://localhost:5050',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('/node_modules/')) return

          const pkg = getPackageName(id)
          if (!pkg) return

          if (pkg === 'react' || pkg === 'react-dom' || pkg === 'scheduler') {
            return 'react-vendor'
          }

          if (pkg === 'lucide-react') {
            return 'icons-vendor'
          }

          if (
            pkg === 'react-markdown' ||
            pkg === 'remark-gfm' ||
            pkg === 'rehype-raw' ||
            pkg.startsWith('remark-') ||
            pkg.startsWith('rehype-') ||
            pkg.startsWith('mdast-') ||
            pkg.startsWith('hast-') ||
            pkg.startsWith('micromark') ||
            pkg.startsWith('unist-') ||
            pkg === 'decode-named-character-reference'
          ) {
            return 'markdown-vendor'
          }

          if (pkg === 'leaflet' || pkg === 'react-leaflet' || pkg === '@react-leaflet/core') {
            return 'leaflet-vendor'
          }

          if (pkg === 'katex') {
            return 'katex'
          }

          if (
            pkg === 'dompurify' ||
            pkg === 'marked' ||
            pkg === 'dayjs' ||
            pkg === 'lodash-es' ||
            pkg === 'stylis' ||
            pkg === 'uuid' ||
            pkg === 'ts-dedent' ||
            pkg === 'roughjs' ||
            pkg === '@braintree/sanitize-url' ||
            pkg === '@iconify/utils'
          ) {
            return 'mermaid-shared'
          }
        },
      },
    },
  },
})
