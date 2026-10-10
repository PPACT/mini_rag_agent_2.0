/**
 * 运行时配置：后端地址 ＋ 鉴权 token。
 *
 * ⭐ **为什么不写死在源码里**：token 属敏感信息（`R-5`）——
 *    ⛔ 不进源码、不进仓库、不写进任何文档。
 *    ⇒ 三种来源，优先级从高到低：
 *      ① 界面上手输（存 `localStorage`，只在这台机器的这个浏览器里）
 *      ② `web/.env.local` 的 `VITE_DEMO_TOKEN`（该文件被根 `.gitignore` 的 `.env.*` 挡住）
 *      ③ 空（界面上会提示去哪找演示账号）
 */
import { useSyncExternalStore } from 'react'

const KEY = 'mini_pg_agent.ui.config'

export interface ApiConfig {
  /** 默认 `/api` = 走 Vite proxy（同源）。填绝对地址也可（直连后端，需后端开 CORS）。 */
  baseUrl: string
  token: string
}

/**
 * ⚠️ **token 的默认值刻意留空** —— 演示账号定义在 `src/auth/deps.py` 的 `DEMO_USERS`
 *    （由 `src/api/demo_api.py` 引用）。⛔ 别抄到这儿来。
 *    本地想免手输 → 在 `web/.env.local` 写 `VITE_DEMO_TOKEN=<token>`。
 */
const DEFAULT_CONFIG: ApiConfig = {
  baseUrl: '/api',
  token: (import.meta.env.VITE_DEMO_TOKEN as string | undefined) ?? '',
}

/** 界面上给用户的指路，⛔ 不含 token 本身。 */
export const TOKEN_HINT = '演示账号见 src/auth/deps.py 的 DEMO_USERS（⛔ 不抄进前端）'

function load(): ApiConfig {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ApiConfig>
      return { ...DEFAULT_CONFIG, ...parsed }
    }
  } catch {
    /* localStorage 被禁 / 数据坏了 → 退回默认，不抛 */
  }
  return { ...DEFAULT_CONFIG }
}

let current: ApiConfig = load()
const listeners = new Set<() => void>()

function emit() {
  for (const l of listeners) l()
}

function subscribe(l: () => void): () => void {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export function getConfig(): ApiConfig {
  return current
}

export function setConfig(next: ApiConfig): void {
  current = next
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    /* 存不下也要能用（内存态） */
  }
  emit()
}

/** 订阅式读取（配置一变，所有用到的组件一起重渲）。 */
export function useApiConfig(): ApiConfig {
  return useSyncExternalStore(subscribe, getConfig, getConfig)
}
