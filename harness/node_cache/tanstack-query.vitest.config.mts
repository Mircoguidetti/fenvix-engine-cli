import { defineConfig } from 'vitest/config'
import fs from 'node:fs'
const pkgs = fs.readdirSync('packages').filter((p) => fs.existsSync(`packages/${p}/vite.config.ts`))
export default defineConfig({
  test: {
    projects: pkgs.map((p) => ({ extends: `./packages/${p}/vite.config.ts`, root: `./packages/${p}`, test: { name: p, root: `./packages/${p}`, dir: `./packages/${p}/src` } })),
  },
})
