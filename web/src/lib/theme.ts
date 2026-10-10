/**
 * 深色 / 浅色切换（`前端ui设计.md` §三-1）。
 *
 * ⚠️ 刻意**不引 next-themes** —— 那是为 Next.js 设计的；这里就一个 class 开关，
 *    自己 20 行够了（本项目有「依赖先量」的规矩）。
 */
import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

const KEY = 'mini_pg_agent.ui.theme'
const listeners = new Set<() => void>()

function readStored(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'light' || v === 'dark') return v
  } catch {
    /* ignore */
  }
  // 没存过 → 跟随系统
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

let current: Theme = readStored()

function apply(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  document.documentElement.style.colorScheme = theme
}

apply(current)

export function setTheme(theme: Theme): void {
  current = theme
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    /* ignore */
  }
  apply(theme)
  for (const l of listeners) l()
}

function subscribe(l: () => void): () => void {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => current,
  )
}
