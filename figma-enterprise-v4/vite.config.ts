import { defineConfig, type Plugin } from 'vite'
import fs from 'fs'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'


function figmaAssetResolver() {
  return {
    name: 'figma-asset-resolver',
    resolveId(id) {
      if (id.startsWith('figma:asset/')) {
        const filename = id.replace('figma:asset/', '')
        return path.resolve(__dirname, 'src/assets', filename)
      }
    },
  }
}

// One immutable identity per production build (the Git SHA the release
// workflow passes as VITE_BUILD_SHA). It is compiled into the bundle, written
// to the no-store /deployment.json the running portal compares against,
// stamped into sw.js so every release installs a new service worker with its
// own cache, and exposed as <meta name="agroai-build"> for release smoke tests.
// Builds without a declared SHA are "unversioned" and fall back to comparing
// entry-module paths, so local/preview builds never claim a production identity.
function agroaiReleaseIdentity(): Plugin {
  const raw = String(process.env.VITE_BUILD_SHA || '').trim()
  const buildId = /^[A-Za-z0-9._-]{1,80}$/.test(raw) ? raw : 'unversioned'
  const environment = String(process.env.VITE_DEPLOYMENT_ENVIRONMENT || '').trim() || 'unspecified'
  let outDir = 'dist'
  return {
    name: 'agroai-release-identity',
    config() {
      return { define: { __AGROAI_BUILD_ID__: JSON.stringify(buildId) } }
    },
    configResolved(config) {
      outDir = path.resolve(config.root, config.build.outDir)
    },
    transformIndexHtml() {
      return [{ tag: 'meta', attrs: { name: 'agroai-build', content: buildId }, injectTo: 'head' }]
    },
    generateBundle(_options, bundle) {
      // The HTML entry's module chunk (index.html -> src/main.tsx).
      const entries = Object.values(bundle).filter((item) => item.type === 'chunk' && item.isEntry)
      const entry = entries.find((item) => item.type === 'chunk' && item.name === 'index') || entries[0]
      this.emitFile({
        type: 'asset',
        fileName: 'deployment.json',
        source: JSON.stringify({
          environment,
          build_sha: buildId,
          built_at: new Date().toISOString(),
          frontend_schema: 1,
          entry: entry ? `/${entry.fileName}` : null,
        }, null, 2) + '\n',
      })
    },
    closeBundle() {
      const worker = path.join(outDir, 'sw.js')
      if (!fs.existsSync(worker)) return
      const source = fs.readFileSync(worker, 'utf8')
      if (!source.includes('__AGROAI_BUILD_ID__')) throw new Error('sw.js is missing the __AGROAI_BUILD_ID__ release placeholder')
      fs.writeFileSync(worker, source.split('__AGROAI_BUILD_ID__').join(buildId))
    },
  }
}

export default defineConfig({
  plugins: [
    figmaAssetResolver(),
    agroaiReleaseIdentity(),
    // The React and Tailwind plugins are both required for Make, even if
    // Tailwind is not being actively used – do not remove them
    react({ jsxImportSource: "@agroai/i18n-jsx" }),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      // Alias @ to the src directory
      '@': path.resolve(__dirname, './src'),
      '@agroai/i18n-jsx': path.resolve(__dirname, './src/app/i18n-jsx'),
    },
  },

  // File types to support raw imports. Never add .css, .tsx, or .ts files to this.
  assetsInclude: ['**/*.svg', '**/*.csv'],

  // The portal must remain executable on Safari 15.6, which is the newest
  // Safari available on macOS Catalina. Vite 6's default target starts at
  // Safari 16, so leaving this implicit can produce a completely blank page
  // before our React/runtime recovery code has a chance to run.
  // Module workers (MapLibre GL tile worker) are emitted as ES modules.
  worker: {
    format: 'es',
  },

  build: {
    target: ['es2020', 'safari15.6'],
    cssTarget: 'safari15.6',
  },
})
