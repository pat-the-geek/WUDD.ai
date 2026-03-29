import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

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
        // Regrouper tous les modules Mermaid dans un seul chunk pour éviter
        // les imports dynamiques résiduels qui causent des erreurs MIME en production.
        manualChunks(id) {
          if (id.includes('mermaid') || id.includes('@mermaid-js')) {
            return 'mermaid-bundle'
          }
        },
      },
    },
  },
})
