import fs from 'node:fs'
import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// ---------------------------------------------------------------------------
// 端口：⭐ 从 `scripts/demo_ports.py` **读**（单一来源）。
// ⛔ 别在这里硬编码 —— 那是「同一事实两个来源」，本项目已经因此吃过亏
//    （`demo_ports.py` 的模块 docstring 就是为此写的）。
// ---------------------------------------------------------------------------
function readPorts(): { api: number; webDev: number } {
  const src = fs.readFileSync(
    path.resolve(import.meta.dirname, '../scripts/demo_ports.py'),
    'utf-8',
  )
  const pick = (name: string, fallback: number) => {
    const m = src.match(new RegExp(`^${name}\\s*=\\s*(\\d+)`, 'm'))
    return m ? Number(m[1]) : fallback
  }
  return { api: pick('API_PORT', 8000), webDev: pick('WEB_DEV_PORT', 5173) }
}

const { api: API_PORT, webDev: WEB_DEV_PORT } = readPorts()
const API_TARGET = `http://127.0.0.1:${API_PORT}`

// ---------------------------------------------------------------------------
// 跨域：🔴 后端**没开 CORS**（且用户裁定「后端不变」）→
// 前端一律调**同源**的 `/api/*`，由 dev server 转发到后端 → 浏览器看到的是同源，后端一行不用动。
// ⛔ 别为了绕开跨域去关浏览器安全策略（那是把问题藏起来，不是解）。
// ⚠️ 这层只在 dev server 生效；静态产物要跑起来需后端配合，届时单独议。
// ---------------------------------------------------------------------------
const BACKEND_PREFIXES = ['/api/chat', '/api/demo', '/api/upload', '/api/health']

const proxy = Object.fromEntries(
  BACKEND_PREFIXES.map((prefix) => [
    prefix,
    {
      target: API_TARGET,
      changeOrigin: true,
      rewrite: (p: string) => p.replace(/^\/api/, ''),
    },
  ]),
)

// ---------------------------------------------------------------------------
// 评测看板的数据源（**dev-only**）。
// 浏览器读不了本地文件，而 `logs/*.json` 是评测产物的**唯一来源**。
// ⇒ 不复制一份（复制 = 同一事实两个来源 → 必然过期）、也不动后端，
//   由 dev server 只读地把 `logs/` 暴露成 `/api/eval/*`。
// 🔒 只读 + 白名单文件名（`[A-Za-z0-9._-]+.json`）→ 杜绝路径穿越。
// ⛔ 生产产物没有这层；要它就得后端开端点（归开发侧），届时另议。
// ---------------------------------------------------------------------------
function evalLogsPlugin(logsDir: string): Plugin {
  return {
    name: 'eval-logs-dev-server',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/api/eval', (req, res) => {
        const url = (req.url ?? '/').split('?')[0]
        res.setHeader('Content-Type', 'application/json; charset=utf-8')

        // 索引：列出可用的产物文件名
        if (url === '/' || url === '/index') {
          const names = fs.existsSync(logsDir)
            ? fs.readdirSync(logsDir).filter((n) => n.endsWith('.json')).sort()
            : []
          res.end(JSON.stringify({ dir: 'logs', files: names }))
          return
        }

        const name = decodeURIComponent(url.replace(/^\//, ''))
        // 🔒 白名单：只允许 `logs/` 下的 `*.json`，且文件名不含路径分隔符
        if (!/^[A-Za-z0-9._-]+\.json$/.test(name)) {
          res.statusCode = 400
          res.end(JSON.stringify({ error: 'invalid artifact name' }))
          return
        }
        const file = path.join(logsDir, name)
        if (!fs.existsSync(file)) {
          res.statusCode = 404
          res.end(JSON.stringify({ error: 'artifact not found', name }))
          return
        }
        res.end(fs.readFileSync(file))
      })
    },
  }
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    evalLogsPlugin(path.resolve(import.meta.dirname, '../logs')),
  ],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    port: WEB_DEV_PORT,
    proxy,
  },
})
