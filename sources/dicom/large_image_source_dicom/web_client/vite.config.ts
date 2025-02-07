import {compileClient} from 'pug';
import {defineConfig} from 'vite';
import {resolve} from 'path';

function pugPlugin() {
    return {
        name: 'pug',
        transform(src: string, id: string) {
            if (id.endsWith('pug')) {
                return {
                    code: `${compileClient(src, {filename: id})}\nexport default template`,
                    map: null,
                };
            }
        },
    };
}

export default defineConfig({
    plugins: [pugPlugin()],
    build: {
        sourcemap: true,
        lib: {
            entry: resolve(__dirname, 'main.js'),
            name: 'GirderPluginDicomWeb',
            fileName: 'girder-plugin-dicomweb',
        },
    },
    define: {
        __BUILD_TIMESTAMP__: `${new Date()}`,
    },
});
