/**
 * 环形图（`参考资料/…UIUX 重构指南` §二-1：耗时分解用**小的环形图**）。
 *
 * ⭐ **手写 SVG，⛔ 不引图表库** —— 这个需求只是个三段环，`recharts` 那种
 *    几百 kB 的依赖换不来更好的效果（本项目有「依赖先量」的规矩）。
 */
export interface DonutSegment {
  label: string
  value: number
  /** 段颜色（传 CSS 颜色/变量）。 */
  color: string
}

export function Donut({
  segments,
  centerLabel,
  centerValue,
  size = 104,
  thickness = 11,
}: {
  segments: DonutSegment[]
  centerLabel: string
  centerValue: string
  size?: number
  thickness?: number
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0)
  const radius = (size - thickness) / 2
  const circumference = 2 * Math.PI * radius
  let drawn = 0

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="-rotate-90"
        role="img"
        aria-label={`${centerLabel} ${centerValue}`}
      >
        {/* 轨道 */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={thickness}
          className="text-muted"
        />
        {total > 0
          ? segments.map((s) => {
              const length = (s.value / total) * circumference
              const node = (
                <circle
                  key={s.label}
                  cx={size / 2}
                  cy={size / 2}
                  r={radius}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={thickness}
                  strokeDasharray={`${length} ${circumference - length}`}
                  strokeDashoffset={-drawn}
                  className="transition-all duration-200"
                />
              )
              drawn += length
              return node
            })
          : null}
      </svg>
      {/* 圆心文字（放在 SVG 外面 → 不跟着 -rotate-90 转） */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[10px] leading-none text-muted-foreground">{centerLabel}</span>
        <span className="mt-0.5 text-sm font-semibold tabular-nums">{centerValue}</span>
      </div>
    </div>
  )
}
