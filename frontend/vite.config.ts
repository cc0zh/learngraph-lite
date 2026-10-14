import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { output: { manualChunks: { graph: ['@xyflow/react', '@dagrejs/dagre'], markdown: ['react-markdown'] } } } },
  server: { port: 5173, strictPort: true, proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } } },
});
