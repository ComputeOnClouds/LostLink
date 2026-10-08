import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // amazon-cognito-identity-js still references Node's `global` in its browser bundle.
  define: { global: 'globalThis' },
  build: {
    outDir: 'dist',
  },
});
