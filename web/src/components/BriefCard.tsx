/**
 * 候选 / 精排的**同一种卡片**（指南 §二-1：**不要用纯表格**，用卡片列表 ＋ 进度条）。
 *
 * ⭐ 字段名与后端 `demo_api._brief()` **逐字对应** —— 卡片上每个数字都能在
 *    `POST /demo/ask` 的返回里指出来（本项目最贵的一条：**数字要能溯源**）。
 */
import { ArrowDown, ArrowUp, Minus } from 'lucide-react'

import { ScoreBar } from '@/components/ScoreBar'
import type { Brief } from '@/lib/types'

/** 精排相对粗排的位次变化：正数 = 被**提权**（rank 变小）。 */
export type Move = { delta: number; from: number } | null

export function BriefCard({ b, max, move }: { b: Brief; max: number; move?: Move }) {
  return (
    <div className="group rounded-lg border border-border/70 bg-background/40 px-2.5 py-2 transition-all duration-200 hover:border-border hover:bg-accent/40">
      <div className="flex items-center gap-2">
        <span className="w-5 shrink-0 text-right font-mono text-[11px] font-semibold tabular-nums text-muted-foreground">
          {b.rank}
        </span>
        <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground" title={b.source ?? undefined}>
          {b.source ?? '（无来源文件）'}
          <span className="ml-1 text-muted-foreground/50">·{b.chunk_index}</span>
        </span>
        {move ? (
          <span
            className={
              move.delta > 0
                ? 'flex shrink-0 items-center gap-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400'
                : move.delta < 0
                  ? 'flex shrink-0 items-center gap-0.5 text-[10px] font-medium text-rose-600 dark:text-rose-400'
                  : 'flex shrink-0 items-center gap-0.5 text-[10px] text-muted-foreground/60'
            }
            title={`粗排第 ${move.from} 名 → 精排第 ${b.rank} 名`}
          >
            {move.delta > 0 ? (
              <ArrowUp className="size-3" />
            ) : move.delta < 0 ? (
              <ArrowDown className="size-3" />
            ) : (
              <Minus className="size-3" />
            )}
            {move.delta > 0 ? `+${move.delta}` : move.delta < 0 ? move.delta : '0'}
            <span className="text-muted-foreground/50">#{move.from}</span>
          </span>
        ) : null}
        <ScoreBar score={b.score} max={max} rank={b.rank} />
      </div>
      <p className="mt-1 line-clamp-2 pl-7 text-[11px] leading-relaxed text-foreground/70 transition-all duration-200 group-hover:line-clamp-none">
        {b.snippet}
      </p>
    </div>
  )
}
