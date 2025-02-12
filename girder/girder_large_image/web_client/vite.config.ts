import { resolve } from 'path';

import { defineConfig } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy'
import { compileClient } from 'pug';
import vue from '@vitejs/plugin-vue2';

function pugPlugin() {
  return {
    name: 'pug',
    transform(src: string, id: string) {
      if (id.endsWith('.pug')) {
        return {
          code: `${compileClient(src, {filename: id})}\nexport default template`,
          map: null,
        };
      }
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    pugPlugin(),
    vue(),
    viteStaticCopy({
      targets: [
        {
          src: 'node_modules/geojs/geo.lean.min.js',
          dest: 'extra',
          rename: () => 'geojs.js',
        }
      ]
    })
  ],
  build: {
    sourcemap: true,
    lib: {
      entry: resolve(__dirname, 'main.js'),
      name: 'GirderPluginLargeImage',
      fileName: 'girder-plugin-large-image',
    },
  },
  define: {
    __BUILD_TIMESTAMP__: `${+new Date()}`,
    'process.env': {},  // for legacy Vue 2
  },
});
