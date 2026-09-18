import { defineConfig } from 'vite';

export default defineConfig({
  build: { outDir: "static" },
  server: {
    proxy: Object.fromEntries(
      ['/api', '/static'].map(path => [path, 'http://127.0.0.1:8000']),
    ),
  },
});
