/**
 * ⭐ **「阶段事件」的可订阅事件源** —— 非流式实现的替身。
 *
 * ── 为什么长这样 ────────────────────────────────────────────────────────
 * 后端**没有 SSE**（`2.0-56` 未开工，实测代码里 `StreamingResponse` /
 * `text/event-stream` 一个都没有）→ 我们**拿不到真实的逐阶段事件**。
 *
 * 所以本实现**只发两种事件**：
 *   · `started` —— 请求已发出（界面显示"进行中 ＋ 已等待 Ns"）
 *   · `done`    —— 拿到完整响应（**真实的**分段耗时随结果一起到）
 *
 * ⛔ 它**不发**"🔍 正在检索… → 📊 精排中…"这类逐阶段文字 ——
 *    那些文字在非流式下**没有真实来源**，编出来就是"没有数据的动效"
 *    （`前端ui设计.md` §一-3 明确禁止）。
 *    ★ 同理，界面上的**耗时分解是真的**（`timings` 字段），但**实时滚动是假的**，不许演。
 *
 * ⭐ **日后后端上了 SSE**：换掉本文件的实现即可，**订阅方（组件）一行不改** ——
 *    只要继续吐同样形状的 `TraceEvent`（`stage` 事件就是给那天预留的位置）。
 */
import type { ApiConfig } from './config'
import { demoAsk, type AskOptions } from './api'
import type { DemoAskResult } from './types'

export type TraceEvent =
  | { type: 'started'; at: number }
  /** 预留：SSE 到位后才有真货。非流式实现**永不发**它。 */
  | { type: 'stage'; at: number; label: string }
  | { type: 'done'; at: number; result: DemoAskResult }
  | { type: 'error'; at: number; message: string }

export interface TraceHandle {
  cancel(): void
}

export function runTrace(
  question: string,
  cfg: ApiConfig,
  opts: AskOptions,
  onEvent: (e: TraceEvent) => void,
): TraceHandle {
  const ctrl = new AbortController()
  onEvent({ type: 'started', at: performance.now() })

  demoAsk(question, cfg, opts, ctrl.signal)
    .then((result) => {
      onEvent({ type: 'done', at: performance.now(), result })
    })
    .catch((err: unknown) => {
      if (ctrl.signal.aborted) return // 用户主动取消 → 不当错误报
      onEvent({ type: 'error', at: performance.now(), message: String(err) })
    })

  return {
    cancel: () => {
      ctrl.abort()
    },
  }
}

/** 秒表格式化：`1234` → `"1.2s"`。 */
export function formatElapsed(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
