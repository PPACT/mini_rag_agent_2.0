/**
 * 「这次问怎么跑」——知识库 ＋ 两个开关。
 *
 * ⚠️ **默认开混合 ＋ 重排**：这是 `/demo/ask` 与 `/chat` 的**既有默认**，
 *    界面**不擅自改默认**（改了就等于悄悄换了被测对象）。
 *    📌 已知现状（`STATUS.md` 第 1 批结论）：这个默认组合正是**最差组合** ——
 *    界面保留它，但**把实测数字摆在旁边**，让"默认踩坑"这件事**看得见**。
 *
 * ⚠️ `kb` 的取值来自 `src/db/kb.py` 的 `VALID_KBS` —— 后端若加库，这里要同步
 *    （后端没有"列可选库"的只读端点，这是本前端**唯一**抄来的契约值，已记在案）。
 */
import { useSyncExternalStore } from 'react'

const KEY = 'mini_pg_agent.ui.ask'

export interface AskSettings {
  kb: string
  useHybrid: boolean
  useRerank: boolean
}

/** ⚠️ 默认 `stress` —— 真实语料装在压测库里，`real` 库当前是空的。 */
const DEFAULTS: AskSettings = { kb: 'stress', useHybrid: true, useRerank: true }

export const KB_OPTIONS = [
  { value: 'stress', label: 'stress（压测库 · 真实语料在这儿）' },
  { value: 'real', label: 'real（真实库 · 当前为空）' },
]

function load(): AskSettings {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<AskSettings>) }
  } catch {
    /* ignore */
  }
  return { ...DEFAULTS }
}

let current: AskSettings = load()
const listeners = new Set<() => void>()

export function getAskSettings(): AskSettings {
  return current
}

export function setAskSettings(next: AskSettings): void {
  current = next
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    /* ignore */
  }
  for (const l of listeners) l()
}

export function useAskSettings(): AskSettings {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => {
        listeners.delete(l)
      }
    },
    getAskSettings,
    getAskSettings,
  )
}
