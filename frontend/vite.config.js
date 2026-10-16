import { defineConfig } from 'vite';
import legacy from '@vitejs/plugin-legacy';

export default defineConfig({
  plugins: [legacy({
    targets: ['Chrome >= 64', 'Edge >= 79', 'Firefox >= 67', 'Safari >= 12'],
    modernPolyfills: true,
  })],
});
