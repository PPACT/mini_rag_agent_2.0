/**
 * 评测看板（`前端ui设计.md` §2.5 ＋ `参考资料/…UIUX 重构指南` §二-2、§三-4）。
 *
 * ⭐ **数字全部来自产物本身**（`logs/*.json` 的 `summary`），前端**不重算** ——
 *    重算 = 第二个实现，迟早与文档侧报表打架（同一事实只留一个来源）。
 *    每个数字下面都写着**它从哪个文件的哪个字段来**。
 *
 * ⚠️ 数据源是 **dev server 只读暴露**的 `/api/eval/*`（见 `vite.config.ts`）。
 *
 * 排版：**不用柱状图** —— 指南 §三-4 要的是「分数列加一个进度条」，
 * 于是 R@K 对照做成 **臂 × 指标的矩阵**（每格一条微型条），比竖柱子更密、更好读。
 */
import { AlertTriangle, Database, FileJson, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { cn } from 'cn'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { fetchArtifact, fetchArtifactIndex } from '@/lib/api'
import { ARTIFACT_LABELS, layeredArms, type ArmView } from '@/lib/eval'
import { MiniBar, pctText, rateTone } from '@/components/MiniBar'
import type { LayeredArtifact } from '@/lib/types'

function isLayered(d: unknown): d is LayeredArtifact {
  return typeof d === 'object' && d !== null && 'results' in d
}

const RECALL_COLS = ['R@1', 'R@3', 'R@5'] as const

/**
 * `per_kind` 里的值 → 可读文本。
 * ⚠️ 产物里存的是**原始比率**（`0.9333333333333333`）—— 直接打印会糊一屏小数。
 * 0~1 之间按百分比显示（`93.3%`），其余照原样（有些产物那一格放的是**计数**）。
 */
function fmtCell(v: number | null | undefined): string {
  if (v === undefined || v === null) return '—'
  if (typeof v === 'number' && v >= 0 && v <= 1) {
    const p = v * 100
    return `${Number.isInteger(p) ? p.toFixed(0) : p.toFixed(1)}%`
  }
  return String(v)
}

function recallOf(arm: ArmView, col: (typeof RECALL_COLS)[number]): number | null {
  const n = arm.nAnswerable
  if (!n) return null
  const hit = col === 'R@1' ? arm.r1 : col === 'R@3' ? arm.r3 : arm.r5
  return hit === null ? null : hit / n
}

function Count({ label, hit, n, warn }: { label: string; hit: number | null; n: number | null; warn?: boolean }) {
  const text = hit === null || n === null ? '—' : `${hit}/${n}`
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-[10px] text-muted-foreground/60">{label}</span>
      <span
        className={
          'font-mono text-xs tabular-nums' + (warn ? ' text-rose-600 dark:text-rose-400' : ' text-foreground/85')
        }
      >
        {text}
      </span>
    </div>
  )
}

/** 每臂一行：主指标（大字）＋ 两个告警位 ＋ 判定三态分布。 */
function ArmRow({ arm, source }: { arm: ArmView; source: string }) {
  const [hit, n] = arm.allHit3
  const ratio = n ? hit / n : null
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-border/50 px-3.5 py-2.5 transition-all duration-200 last:border-0 hover:bg-accent/40">
      <div className="min-w-[9rem]">
        <div className="text-sm font-medium">{arm.name}</div>
        <div className="text-[10px] text-muted-foreground/60">
          <code className="font-mono">logs/{source}</code>
          <span className="mx-1">·</span>共 {arm.nTotal} 题（有答案 {arm.nAnswerable}）
        </div>
      </div>

      <div className="min-w-[7rem]">
        <div className="flex items-baseline gap-1.5">
          <span className="metric-xl text-primary">{hit}</span>
          <span className="text-base font-semibold text-muted-foreground/40">/{n}</span>
        </div>
        <div className="micro-label">AllHit@3</div>
        <MiniBar value={ratio} className="mt-1 w-[7rem]" tone="primary" />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <Count label="拒答" hit={arm.refuseOk} n={arm.refuseN} warn={(arm.refuseOk ?? 9) <= 3} />
        <Count label="误拒" hit={arm.falseRefuse} n={arm.falseN} warn={(arm.falseRefuse ?? 0) >= 3} />
        {/* ⚠️ 生成失败**只在有**的时候才出现 —— 恒显示"0/0"是噪音 */}
        {arm.genErrorN > 0 ? (
          <span className="flex items-center gap-1 rounded-md bg-rose-500/10 px-1.5 py-0.5 text-[10px] text-rose-600 ring-1 ring-rose-500/20 dark:text-rose-400">
            gen_error <span className="font-mono tabular-nums">{arm.genErrorN}</span>
          </span>
        ) : null}
      </div>

      {/* ⚠️ 不加 `ml-auto` —— 那会在「误拒」和「判定三态」之间留一大段空档 */}
      <div className="flex flex-wrap items-center gap-2.5 border-l border-border/50 pl-4 text-[10px] text-muted-foreground/70">
        {Object.entries(arm.judgeStatus).map(([k, v]) => (
          <span key={k} className="font-mono">
            {k} <span className="text-foreground/70">{v}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

/** 召回率对照矩阵：行 = 臂，列 = R@1/R@3/R@5，每格一条微型条。 */
function RecallMatrix({ arms }: { arms: ArmView[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[34rem] border-collapse text-left">
        <thead>
          <tr className="border-b border-border/60">
            <th className="micro-label px-3.5 py-2 font-semibold">臂</th>
            {RECALL_COLS.map((c) => (
              <th key={c} className="micro-label px-3.5 py-2 font-semibold">
                {c}
              </th>
            ))}
            <th className="micro-label px-3.5 py-2 font-semibold">分母</th>
          </tr>
        </thead>
        <tbody>
          {arms.map((a) => (
            <tr key={a.name} className="border-b border-border/40 transition-all duration-200 last:border-0 hover:bg-accent/40">
              <td className="px-3.5 py-2 text-xs font-medium whitespace-nowrap">{a.name}</td>
              {RECALL_COLS.map((c) => {
                const ratio = recallOf(a, c)
                return (
                  <td key={c} className="px-3.5 py-2">
                    <div className="flex items-center gap-2">
                      <MiniBar value={ratio} className="w-20" tone={rateTone(ratio)} />
                      <span className="font-mono text-xs tabular-nums">{pctText(ratio)}</span>
                    </div>
                  </td>
                )
              })}
              <td className="px-3.5 py-2 font-mono text-[11px] tabular-nums text-muted-foreground">
                {a.nAnswerable} 有答案
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** `per_kind` 明细 —— 结构不写死，按实际有的键出列（⛔ 不猜 schema）。 */
function PerKindTable({ arms }: { arms: ArmView[] }) {
  const kinds = useMemo(() => {
    const set = new Set<string>()
    for (const a of arms) for (const k of Object.keys(a.perKind)) set.add(k)
    return [...set]
  }, [arms])
  const cols = useMemo(() => {
    const set = new Set<string>()
    for (const a of arms) for (const v of Object.values(a.perKind)) for (const k of Object.keys(v)) set.add(k)
    return [...set]
  }, [arms])

  if (kinds.length === 0 || cols.length === 0) {
    return <p className="px-3.5 py-3 text-[11px] text-muted-foreground">该产物没有 per_kind 分层字段。</p>
  }

  return (
    <div className="overflow-x-auto">
      {/* ⚠️ 用 `w-auto`（⛔ 不是 `w-full`）—— 列按内容排、**不留中间那一大段空白**；
          臂与臂之间用一条竖线分隔即可 */}
      <table className="w-auto border-collapse text-left">
        <thead>
          <tr className="border-b border-border/60">
            <th className="micro-label py-2 pr-4 pl-3.5 font-semibold">类目</th>
            {arms.map((a, ai) =>
              cols.map((c, ci) => (
                <th
                  key={`${a.name}-${c}`}
                  className={cn(
                    'w-16 py-1.5 text-right',
                    ci === 0 && ai > 0 && 'border-l border-border/60 pl-4',
                  )}
                >
                  {ci === 0 ? (
                    <div className="text-[10px] font-semibold text-foreground/70">{a.name}</div>
                  ) : (
                    <div className="text-[10px] font-semibold text-transparent select-none">·</div>
                  )}
                  <div className="micro-label font-normal">{c}</div>
                </th>
              )),
            )}
          </tr>
        </thead>
        <tbody>
          {kinds.map((kind) => (
            <tr key={kind} className="border-b border-border/40 transition-all duration-200 last:border-0 hover:bg-accent/40">
              <td className="py-1.5 pr-4 pl-3.5 text-xs font-medium whitespace-nowrap">{kind}</td>
              {arms.map((a, ai) =>
                cols.map((c, ci) => (
                  <td
                    key={`${a.name}-${kind}-${c}`}
                    className={cn(
                      'py-1.5 pr-3 font-mono text-xs tabular-nums text-foreground/85',
                      ci === 0 && ai > 0 && 'border-l border-border/60 pl-4',
                    )}
                  >
                    {fmtCell(a.perKind[kind]?.[c])}
                  </td>
                )),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function EvalDashboard() {
  const [files, setFiles] = useState<string[]>([])
  const [selected, setSelected] = useState<string>('')
  const [data, setData] = useState<unknown>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const loadIndex = useCallback(async () => {
    try {
      const names = await fetchArtifactIndex()
      setFiles(names)
      // ⭐ 默认挑**分层评估**产物：主指标（`AllHit@3`）在那儿，演示时第一眼就该看到它。
      //    ⛔ 别用 `names[0]` —— 那是字母序，会落在 `build_reproducible.json` 这种"还没专用视图"的产物上。
      //    ⚠️ 取**最后一个**匹配：`layered_eval.json` 是旧尺子那版，`layered_eval_reverify_*` 才是现行基线。
      const layered = names.filter((n) => n.startsWith('layered_eval'))
      setSelected((cur) => cur || layered[layered.length - 1] || names[0] || '')
    } catch (e) {
      setError(String(e))
    }
  }, [])

  useEffect(() => {
    void loadIndex()
  }, [loadIndex])

  useEffect(() => {
    if (!selected) return
    let alive = true
    setLoading(true)
    setError(null)
    fetchArtifact<unknown>(selected)
      .then((d: unknown) => {
        if (alive) setData(d)
      })
      .catch((e: unknown) => {
        if (alive) setError(String(e))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [selected])

  const arms = useMemo(() => (isLayered(data) ? layeredArms(data) : []), [data])

  return (
    <div className="grid gap-2.5 pb-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={selected} onValueChange={setSelected}>
          <SelectTrigger className="h-8 w-[21rem] max-w-full text-xs">
            <SelectValue placeholder="选一份评测产物" />
          </SelectTrigger>
          <SelectContent>
            {files.map((f) => (
              <SelectItem key={f} value={f} className="text-xs">
                {ARTIFACT_LABELS[f] ?? f}
                <span className="ml-2 font-mono text-[10px] text-muted-foreground">{f}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" size="sm" onClick={() => void loadIndex()} disabled={loading}>
          <RefreshCw className={loading ? 'animate-spin' : ''} /> 刷新
        </Button>
        <span className="text-[10px] text-muted-foreground/60">
          只读 <code className="font-mono">logs/*.json</code>（dev server 暴露，无后端改动）
        </span>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>读不到产物</AlertTitle>
          <AlertDescription className="break-all font-mono text-xs">{error}</AlertDescription>
        </Alert>
      ) : null}

      {arms.length > 0 ? (
        <>
          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">主指标 ＋ 告警位</span>
              <span className="text-[10px] text-muted-foreground/60">
                源 <code className="font-mono">logs/{selected}</code> → <code className="font-mono">results.*.summary</code>
              </span>
            </div>
            {arms.map((a) => (
              <ArmRow key={a.name} arm={a} source={selected} />
            ))}
            <p className="border-t border-border/50 px-3.5 py-2 text-[10px] leading-relaxed text-muted-foreground/70">
              ⚠️ 每臂各自比各自（<code className="font-mono">regression_spec</code> 口径）—— ⛔ 不许跨臂比「谁更好」
              （开关不同，比了没意义）。告警线（变红即超线）：拒答 ≤3/5 · 误拒 ≥3/45。
            </p>
          </div>

          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">召回率对照</span>
              <span className="text-[10px] text-muted-foreground/60">分母 = 有答案题（无答案题不计入 R@K）</span>
            </div>
            <RecallMatrix arms={arms} />
          </div>

          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">分层明细</span>
              <span className="text-[10px] text-muted-foreground/60">
                <code className="font-mono">summary.per_kind</code>
              </span>
            </div>
            <PerKindTable arms={arms} />
          </div>
        </>
      ) : data ? (
        <Alert>
          <FileJson />
          <AlertTitle>该产物暂无专用视图</AlertTitle>
          <AlertDescription className="text-xs">
            顶层键：<code className="font-mono">{Object.keys(data as object).join(' / ')}</code>
            —— ⭐ 原始产物在下面，取数口径见对应评测脚本。
          </AlertDescription>
        </Alert>
      ) : null}

      {data ? (
        <details className="panel px-3.5 py-2.5">
          <summary className="flex cursor-pointer items-center gap-2 text-xs font-medium select-none">
            <Database className="size-3.5 text-muted-foreground" />
            原始产物
            <code className="font-mono text-[10px] font-normal text-muted-foreground">logs/{selected}</code>
          </summary>
          <pre className="mt-2.5 max-h-96 overflow-auto rounded-lg bg-muted/60 p-3 font-mono text-[10px] leading-relaxed">
            {JSON.stringify(data, null, 2)}
          </pre>
        </details>
      ) : null}
    </div>
  )
}
