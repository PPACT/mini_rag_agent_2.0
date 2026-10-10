/**
 * 一次「问答 + 链路透视」的会话状态。
 *
 * ⭐ **对话与透视由同一次请求喂** —— 问答页调的是 `POST /demo/ask`（不是 `/chat`），
 *    因为它**同时**给出答案与链路。这样"透视里看到的候选/耗时"与"屏幕上那句答案"
 *    **一定是同一次请求**；分两次调就永远对不上。
 *
 * ⚠️ 代价说清楚：`/demo/ask` **不含 `/chat` 的歧义澄清话术流程** ——
 *    所以界面会标注"本次经由 /demo/ask"。要 `/chat` 的保真行为就得放弃链路透视，
 *    这属于**产品取舍**，已记在案，别在这儿偷偷改。
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import type { ApiConfig } from './config'
import type { AskSettings } from './ask-config'
import type { DemoAskResult } from './types'
import { runTrace, type TraceHandle } from './trace-stream'

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  text: string
  /** 出错时的原始信息（诚实显示，⛔ 别吞掉）。 */
  error?: string
}

export interface Pending {
  startedAt: number
  elapsedMs: number
}

let seq = 0

export function useAskSession() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pending, setPending] = useState<Pending | null>(null)
  const [result, setResult] = useState<DemoAskResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const handleRef = useRef<TraceHandle | null>(null)

  // 「进行中」的秒表：每 100ms 走一格（⛔ 不假装阶段，只诚实报已等待多久）
  useEffect(() => {
    if (!pending) return
    const timer = window.setInterval(() => {
      setPending((p) => (p ? { ...p, elapsedMs: performance.now() - p.startedAt } : p))
    }, 100)
    return () => window.clearInterval(timer)
    // ⚠️ 只依赖 `startedAt`（用函数式更新读当前值）—— 依赖整个 `pending`
    //    会每 100ms 重建一次 interval，白耗且易漂。
  }, [pending?.startedAt])

  const ask = useCallback((question: string, cfg: ApiConfig, opts: AskSettings) => {
    const q = question.trim()
    if (!q || handleRef.current) return

    setMessages((m) => [...m, { id: ++seq, role: 'user', text: q }])
    setError(null)
    setResult(null)
    setPending({ startedAt: performance.now(), elapsedMs: 0 })

    handleRef.current = runTrace(q, cfg, opts, (e) => {
      if (e.type === 'done') {
        setResult(e.result)
        setMessages((m) => [
          ...m,
          {
            id: ++seq,
            role: 'assistant',
            text: e.result.answer ?? '（本次没有生成答案）',
          },
        ])
        setPending(null)
        handleRef.current = null
      } else if (e.type === 'error') {
        setError(e.message)
        setMessages((m) => [
          ...m,
          { id: ++seq, role: 'assistant', text: '', error: e.message },
        ])
        setPending(null)
        handleRef.current = null
      }
    })
  }, [])

  const cancel = useCallback(() => {
    handleRef.current?.cancel()
    handleRef.current = null
    setPending(null)
  }, [])

  const reset = useCallback(() => {
    handleRef.current?.cancel()
    handleRef.current = null
    setMessages([])
    setResult(null)
    setError(null)
    setPending(null)
  }, [])

  return { messages, pending, result, error, ask, cancel, reset }
}
