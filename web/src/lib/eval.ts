/**
 * 评测产物（`logs/*.json`）的读取与**取数**。
 *
 * ⭐ **数据从哪来**：`GET /api/eval/<文件名>` —— 由 `vite.config.ts` 的
 *    `eval-logs-dev-server` 插件把 `logs/` **只读**暴露出来（dev-only）。
 *    ⛔ 不复制一份产物（复制 = 同一事实两个来源 → 必然过期）。
 *
 * ⚠️ **本模块只做取数，不做解释** —— 解释是人的事，看板不替人下结论
 *    （同 `src/ui/logs_reader.py` 的口径；那个文件是**对照组**，不是我的代码）。
 *
 * ⚠️ **数字口径**：`R@K` / 拒答 / `gen_error_n` 一律**直接读产物里的 `summary`**，
 *    前端**不自己重算**（重算 = 第二个实现 → 会跟文档侧的报表打架）。
 *    唯一例外是 `AllHit@3` —— 产物里没有，见 `allHit()` 的说明。
 */
import type { LayeredArtifact, LayeredRow } from './types'

/** 产物中文名（**纯展示**，不改任何口径；不带 label 的用文件名兜底）。 */
export const ARTIFACT_LABELS: Record<string, string> = {
  'layered_eval.json': '分层评估（50 题 · 两臂）',
  'layered_eval_reverify_20261010.json': '分层评估（四臂 · 真验收）',
  'l0_report.json': 'L0 切分体检',
  'pdf_numeric_eval.json': 'PDF 数值题（检索）',
  'pdf_numeric_e2e.json': 'PDF 数值题（端到端）',
  'excel_numeric_eval.json': 'Excel 表格块',
  'shadow_bold_heading.json': 'shadow：加粗标题',
}

/**
 * `AllHit@K` —— **每份出处都要进 top-K**。
 *
 * ⚠️ 口径**唯一来源**是 `eval/run_regression.py` 的 `_allhit()`；产物里没这个字段。
 *    这里是它的 **TS 镜像**（前后端不同语言，没法直接 import）——
 *    ⛔ 改口径时**两处必须一起改**；对不上就以 `eval/run_regression.py` 为准。
 *    · 只统计**多 anchor** 的题（单 anchor 题的 `AllHit ≡ R@K`，混进来会稀释信号）
 */
export function allHit(rows: LayeredRow[], k = 3): [number, number] {
  const multi = rows.filter((r) => r.kind !== 'no_answer' && (r.ranks_each?.length ?? 0) > 1)
  const hit = multi.filter((r) => r.ranks_each.every((x) => x !== null && x <= k)).length
  return [hit, multi.length]
}

export interface ArmView {
  name: string
  nTotal: number
  nAnswerable: number
  r1: number | null
  r3: number | null
  r5: number | null
  allHit3: [number, number]
  refuseOk: number | null
  refuseN: number | null
  falseRefuse: number | null
  falseN: number | null
  genErrorN: number
  judgeStatus: Record<string, number>
  perKind: Record<string, Record<string, number | null>>
}

function ratioOf(rate: number | null | undefined, n: number): number | null {
  return rate === null || rate === undefined ? null : Math.round(rate * n)
}

/** 分层评估产物 → 逐臂视图（**取数**，不解释）。 */
export function layeredArms(data: LayeredArtifact): ArmView[] {
  return Object.entries(data.results ?? {}).map(([name, v]) => {
    const rows = v.rows ?? []
    const s = v.summary ?? {}
    const overall = s.overall ?? {}
    const nAns = rows.filter((r) => r.kind !== 'no_answer').length
    return {
      name,
      nTotal: rows.length,
      nAnswerable: nAns,
      r1: ratioOf(overall['R@1'], nAns),
      r3: ratioOf(overall['R@3'], nAns),
      r5: ratioOf(overall['R@5'], nAns),
      allHit3: allHit(rows, 3),
      refuseOk: s.refuse_ok ?? null,
      refuseN: s.refuse_n ?? null,
      falseRefuse: s.false_refuse ?? null,
      falseN: s.false_n ?? null,
      genErrorN: s.gen_error_n ?? 0,
      judgeStatus: s.judge_status ?? {},
      perKind: s.per_kind ?? {},
    }
  })
}

/** 判定三态的中文 + 配色语义（`clear` / `ambiguous` / `unknown`）。 */
export function judgeTone(status: string): 'ok' | 'warn' | 'muted' {
  if (status === 'clear') return 'ok'
  if (status === 'ambiguous') return 'warn'
  return 'muted'
}

// ⚠️ 得分条的配色**不在这里** —— 见 `components/ScoreBar.tsx` 顶部那段说明：
//    本项目的分数刻度随后端而变，**不能**照搬"0.8 绿 / 0.5 黄"的绝对阈值。
