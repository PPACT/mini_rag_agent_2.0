/**
 * 链路透视面板（`前端ui设计.md` §2.4 ＋ `参考资料/…UIUX 重构指南` §二-1）——
 * ⚠️ **硬约束，不是锦上添花**。⛔ 做成一堆好看的气泡却把这块丢掉 = 把最有价值的演示能力扔掉。
 *
 * ⭐ **每个数字都指得出源**：全部来自 `POST /demo/ask` 的**那一个**返回对象。
 *
 * 排版：卡片头用统一的 `.panel-head`，内容**堆叠不并排**（面板只占 40% 宽，
 * 并排会把 104px 的得分条挤扁）；"候选 vs 精排"的对比靠**每张卡上的位次变化角标**
 * ＋ 顶部一行汇总 ＋ 可展开的"被挤出"清单来表达。
 */
import { AlertTriangle, Clock, Link2, Search } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { BriefCard, type Move } from '@/components/BriefCard'
import { Donut } from '@/components/Donut'
import { judgeTone } from '@/lib/eval'
import { formatElapsed } from '@/lib/trace-stream'
import type { DemoAskResult } from '@/lib/types'
import type { Pending } from '@/lib/use-ask-session'

/** 耗时三段 —— 键名与 `demo_api` 的 `timings` 逐字对应；颜色取主题图色。 */
const TIMING_SEGMENTS = [
  { key: 'retrieve_ms', label: '检索（含精排）', color: 'var(--chart-1)' },
  { key: 'generate_ms', label: '生成答案', color: 'var(--chart-2)' },
  { key: 'ambiguity_ms', label: '歧义判定', color: 'var(--chart-4)' },
] as const

const JUDGE_TONE = {
  ok: 'bg-emerald-500/12 text-emerald-700 ring-1 ring-emerald-500/25 dark:text-emerald-400',
  warn: 'bg-amber-500/12 text-amber-700 ring-1 ring-amber-500/25 dark:text-amber-400',
  muted: 'bg-muted text-muted-foreground ring-1 ring-border',
} as const

const JUDGE_LABEL: Record<string, string> = {
  clear: 'clear · 有答案',
  ambiguous: 'ambiguous · 无唯一答案',
  unknown: 'unknown · 判不出',
}

function chunkKey(source: string | null, chunkIndex: number): string {
  return `${source ?? ''}#${chunkIndex}`
}

/** 一行小 chip（meta 条用）。 */
function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
      {children}
    </span>
  )
}

export function InspectorPanel({
  result,
  pending,
  error,
}: {
  result: DemoAskResult | null
  pending: Pending | null
  error: string | null
}) {
  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTriangle />
        <AlertTitle>本次请求失败</AlertTitle>
        <AlertDescription className="break-all font-mono text-xs">{error}</AlertDescription>
      </Alert>
    )
  }

  if (pending) {
    return (
      <div className="panel">
        <div className="panel-head">
          <span className="panel-title flex items-center gap-2">
            <Clock className="size-3.5 text-muted-foreground" /> 进行中
          </span>
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            已等待 {formatElapsed(pending.elapsedMs)}
          </span>
        </div>
        <p className="px-3.5 py-3 text-[11px] leading-relaxed text-muted-foreground">
          后端没有 SSE（<code className="font-mono">2.0-56</code> 未开工），所以
          <strong className="font-medium text-foreground">报不出</strong>
          「正在检索 → 正在精排」这种逐阶段文字 —— 那些话目前没有真实来源，编出来就是没有数据的动效。
          分段耗时是真的，但它要等整次请求结束才拿得到。
        </p>
      </div>
    )
  }

  if (!result) {
    return (
      <div className="panel">
        <div className="panel-head">
          <span className="panel-title flex items-center gap-2">
            <Search className="size-3.5 text-muted-foreground" /> 链路透视
          </span>
        </div>
        <p className="px-3.5 py-3 text-[11px] leading-relaxed text-muted-foreground">
          问一句 —— 这里会展开这一次请求的：耗时分解 · 判定三态 · 候选池 vs 精排（含提权/下移）· 引用校验。
        </p>
      </div>
    )
  }

  const total = result.timings.total_ms || 1
  const maxScore = Math.max(
    ...result.final.map((b) => b.score),
    ...result.candidates.map((b) => b.score),
    0,
  )
  const candRank = new Map(result.candidates.map((c) => [chunkKey(c.source, c.chunk_index), c.rank]))
  const moveOf = (b: (typeof result.final)[number]): Move => {
    const from = candRank.get(chunkKey(b.source, b.chunk_index))
    if (from === undefined) return null
    return { from, delta: from - b.rank }
  }
  const promoted = result.final.filter((b) => (moveOf(b)?.delta ?? 0) > 0).length
  const demoted = result.final.filter((b) => (moveOf(b)?.delta ?? 0) < 0).length
  const killed = result.candidates.filter(
    (c) =>
      !result.final.some(
        (f) => chunkKey(f.source, f.chunk_index) === chunkKey(c.source, c.chunk_index),
      ),
  )

  return (
    <div className="grid gap-2.5 pb-1">
      {/* ── 本次请求（细条 meta，不再是一大块） ───────────────────── */}
      <div className="panel">
        <div className="panel-head py-2">
          <span className="panel-title">本次请求</span>
          <span className={'rounded-md px-2 py-0.5 text-[11px] font-medium ' + JUDGE_TONE[judgeTone(result.judge_status)]}>
            {JUDGE_LABEL[result.judge_status] ?? result.judge_status}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 px-3.5 py-2.5">
          <Chip>
            <span className="text-muted-foreground/60">库</span> {result.kb}
          </Chip>
          <Chip>
            <span className="text-muted-foreground/60">用户</span> {result.user.name}（{result.user.department}）
          </Chip>
          <Chip>
            <span className="text-muted-foreground/60">可见</span> {result.user.scope.join(' / ')}
          </Chip>
          <Chip>
            混合 <span className={result.mode.hybrid ? 'text-foreground' : ''}>{result.mode.hybrid ? '开' : '关'}</span>
          </Chip>
          <Chip>
            精排{' '}
            <span className={result.mode.rerank ? 'text-foreground' : ''}>
              {result.mode.rerank ? String(result.rerank.backend) : '关'}
            </span>
          </Chip>
          {result.ambiguity_reason ? (
            <span className="text-[11px] text-muted-foreground/70">{result.ambiguity_reason}</span>
          ) : null}
        </div>
      </div>

      {/* ── 耗时分解：环形图 ＋ 图例 ────────────────────────────── */}
      <div className="panel">
        <div className="panel-head py-2">
          <span className="panel-title">耗时分解</span>
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            合计 {result.timings.total_ms} ms
          </span>
        </div>
        <div className="flex items-center gap-4 px-3.5 py-3">
          <Donut
            segments={TIMING_SEGMENTS.map((s) => ({
              label: s.label,
              value: result.timings[s.key],
              color: s.color,
            }))}
            centerLabel="合计"
            centerValue={`${(result.timings.total_ms / 1000).toFixed(1)}s`}
          />
          <ul className="min-w-0 flex-1 space-y-1.5">
            {TIMING_SEGMENTS.map((s) => {
              const ms = result.timings[s.key]
              const share = (ms / total) * 100
              return (
                <li key={s.key} className="flex items-center gap-2">
                  <span className="size-2 shrink-0 rounded-full" style={{ background: s.color }} />
                  <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">{s.label}</span>
                  <span className="font-mono text-[11px] tabular-nums">{ms}ms</span>
                  <span className="w-9 text-right font-mono text-[10px] tabular-nums text-muted-foreground/60">
                    {share.toFixed(0)}%
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      </div>

      {/* ── 候选池 vs 精排 ──────────────────────────────────────── */}
      <div className="panel">
        <div className="panel-head py-2">
          <span className="panel-title">候选池 vs 精排</span>
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {result.candidates.length} → {result.final.length}
            {promoted || demoted ? (
              <span className="ml-1.5">
                <span className="text-emerald-600 dark:text-emerald-400">↑{promoted}</span>
                <span className="mx-0.5 text-muted-foreground/40">/</span>
                <span className="text-rose-600 dark:text-rose-400">↓{demoted}</span>
              </span>
            ) : null}
          </span>
        </div>

        <div className="space-y-2.5 px-3.5 py-3">
          <div>
            <div className="micro-label mb-1.5 flex items-center justify-between">
              <span>候选池 · RRF 融合后</span>
              <span className="normal-case tracking-normal text-muted-foreground/50">条长按本次最高分归一</span>
            </div>
            {result.candidates.length === 0 ? (
              <p className="py-2 text-[11px] text-muted-foreground">（空 —— 检索没召回到任何块）</p>
            ) : (
              <div className="space-y-1">
                {result.candidates.map((c) => (
                  <BriefCard key={chunkKey(c.source, c.chunk_index)} b={c} max={maxScore} />
                ))}
              </div>
            )}
          </div>

          <div>
            <div className="micro-label mb-1.5">
              精排结果 · {String(result.mode.rerank_backend ?? '')}
              {result.mode.rerank ? '' : '（未开）'}
            </div>
            {result.final.length === 0 ? (
              <p className="py-2 text-[11px] text-muted-foreground">（空）</p>
            ) : (
              <div className="space-y-1">
                {result.final.map((f) => (
                  <BriefCard
                    key={chunkKey(f.source, f.chunk_index)}
                    b={f}
                    max={maxScore}
                    move={moveOf(f)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {killed.length > 0 ? (
          <details className="border-t border-border/60 px-3.5 py-2">
            <summary className="cursor-pointer select-none text-[11px] text-muted-foreground">
              被精排挤出去的 {killed.length} 块
            </summary>
            <ul className="mt-1.5 space-y-0.5">
              {killed.map((k) => (
                <li key={chunkKey(k.source, k.chunk_index)} className="font-mono text-[10px] text-muted-foreground">
                  粗排 #{k.rank} · {k.source ?? '（无来源）'} · 块 {k.chunk_index} · 分 {k.score}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>

      {/* ── 引用校验 ───────────────────────────────────────────── */}
      <div className="panel">
        <div className="panel-head py-2">
          <span className="panel-title flex items-center gap-2">
            <Link2 className="size-3.5 text-muted-foreground" /> 引用校验
          </span>
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {result.cited.length} 条
          </span>
        </div>
        <div className="space-y-1.5 px-3.5 py-3">
          {result.cited.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">
              （本次答案没有引用任何块 —— 可能是拒答、或生成时未标注引用）
            </p>
          ) : (
            result.cited.map((c) => (
              <div
                key={chunkKey(c.source, c.chunk_index)}
                className="border-l-2 border-emerald-500/70 bg-emerald-500/[0.06] py-1.5 pl-2.5 pr-2"
              >
                <div className="text-[11px] font-medium text-emerald-700 dark:text-emerald-400">
                  {c.source ?? '（无来源文件）'}
                  <span className="ml-1 text-emerald-700/50 dark:text-emerald-400/50">· 块 {c.chunk_index}</span>
                </div>
                <p className="mt-0.5 line-clamp-3 text-[11px] leading-relaxed text-foreground/70">{c.snippet}</p>
              </div>
            ))
          )}
        </div>
      </div>

      <p className="px-1 text-[10px] text-muted-foreground/50">
        以上每个数字都来自 <code className="font-mono">POST /demo/ask</code> 的返回 —— 本页不做二次计算。
      </p>
    </div>
  )
}
