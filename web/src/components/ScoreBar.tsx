/**
 * 得分条（指南 §二-2「用颜色和进度条代表分数」）。
 *
 * ⚠️ **一处我对指南的有意偏离，理由说清楚**：
 *    指南写「`>0.8` 绿 / `0.5~0.8` 黄 / `<0.5` 灰」—— 那套阈值假设分数是 **0~1 的相似度**。
 *    而本项目的分数**不是**那个刻度：粗排（RRF 融合）分在 **0.01~0.03** 量级，
 *    精排分**随后端而变**（本地 cross-encoder / LLM 判分，量纲不同）。
 *    照搬阈值 → **所有条都会是灰的**，等于用颜色撒了个谎。
 *    ⇒ 这里改成：**条长 = 本次结果内的相对位置**（同一次请求内比较才有意义），
 *      **颜色 = 名次**（前三名给强调色），**原始分照原样显示**。
 *    ⛔ 这不是"没照做"，是**照做了会让数字骗人**。
 */
import { cn } from 'cn'

export type Rank = number

export function ScoreBar({ score, max, rank }: { score: number; max: number; rank: Rank }) {
  const pct = max > 0 ? Math.min(100, Math.max(2, (score / max) * 100)) : 2
  const tone =
    rank <= 1
      ? 'bg-primary'
      : rank <= 3
        ? 'bg-emerald-500'
        : 'bg-slate-400 dark:bg-slate-600'

  return (
    <div className="flex w-[104px] shrink-0 items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn('h-full rounded-full transition-all duration-200', tone)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-[52px] text-right font-mono text-[11px] tabular-nums text-muted-foreground">
        {score.toFixed(4)}
      </span>
    </div>
  )
}
