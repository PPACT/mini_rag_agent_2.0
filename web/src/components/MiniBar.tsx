/**
 * 表格/列表里的**微型条** —— 让"比率"这类数字一眼可比（指南 §三-4）。
 */
import { cn } from 'cn'

export function MiniBar({
  value,
  className,
  tone = 'primary',
}: {
  /** 0~1 的比率。`null` → 显示空条 + `—`。 */
  value: number | null
  className?: string
  tone?: 'primary' | 'emerald' | 'amber' | 'rose' | 'muted'
}) {
  const pct = value === null ? 0 : Math.min(100, Math.max(0, value * 100))
  const toneClass = {
    primary: 'bg-primary',
    emerald: 'bg-emerald-500',
    amber: 'bg-amber-500',
    rose: 'bg-rose-500',
    muted: 'bg-slate-400 dark:bg-slate-600',
  }[tone]

  return (
    <div className={cn('h-1.5 w-full overflow-hidden rounded-full bg-muted', className)}>
      <div
        className={cn('h-full rounded-full transition-all duration-200', toneClass)}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

/** 比率 → 文字（`0.7111` → `71.1%`；`null` → `—`）。 */
export function pctText(value: number | null, digits = 1): string {
  if (value === null) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

/** 比率 → 配色档（用于告警线：拒答/误拒）。 */
export function rateTone(value: number | null): 'emerald' | 'amber' | 'rose' | 'muted' {
  if (value === null) return 'muted'
  if (value >= 0.8) return 'emerald'
  if (value >= 0.5) return 'amber'
  return 'rose'
}
