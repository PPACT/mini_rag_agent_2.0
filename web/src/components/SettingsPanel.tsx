/**
 * 连接设置（`前端ui设计.md` §2.1）——后端地址 ＋ Token ＋ 请求参数。
 *
 * ⚠️ **Token 必须隐藏输入**；⛔ 且**不写进源码**（`R-5`）——只存本机 `localStorage`，
 *    或由 `web/.env.local` 的 `VITE_DEMO_TOKEN` 预填。
 */
import { CheckCircle2, Eye, EyeOff, RotateCcw, XCircle } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { KB_OPTIONS, setAskSettings, useAskSettings } from '@/lib/ask-config'
import { TOKEN_HINT, setConfig, useApiConfig } from '@/lib/config'

/** 一行开关（左说明 / 右控件）。 */
function ToggleRow({
  id,
  label,
  hint,
  checked,
  onChange,
}: {
  id: string
  label: string
  hint: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <Label htmlFor={id} className="text-xs font-medium">
          {label}
        </Label>
        <p className="text-[10px] text-muted-foreground/70">{hint}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  )
}

export function SettingsPanel({
  onHealthCheck,
  healthState,
}: {
  onHealthCheck: () => void
  healthState: 'idle' | 'checking' | 'ok' | 'fail'
}) {
  const cfg = useApiConfig()
  const ask = useAskSettings()
  const [showToken, setShowToken] = useState(false)

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {/* ── 连接 ─────────────────────────────────────────── */}
      <div className="panel">
        <div className="panel-head py-2">
          <span className="panel-title">连接</span>
          <div className="flex items-center gap-1.5">
            {healthState === 'ok' ? (
              <span className="flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="size-3" /> 后端可达
              </span>
            ) : healthState === 'fail' ? (
              <span className="flex items-center gap-1 text-[11px] text-destructive">
                <XCircle className="size-3" /> 后端不通
              </span>
            ) : healthState === 'checking' ? (
              <span className="text-[11px] text-muted-foreground">探活中…</span>
            ) : (
              <span className="text-[11px] text-muted-foreground/60">未探活</span>
            )}
            <Button variant="ghost" size="xs" onClick={onHealthCheck}>
              探活
            </Button>
          </div>
        </div>

        <div className="grid gap-2.5 px-3.5 py-3">
          <div className="grid gap-1">
            <Label htmlFor="baseUrl" className="text-xs font-medium">
              后端地址
            </Label>
            <Input
              id="baseUrl"
              value={cfg.baseUrl}
              placeholder="/api"
              className="h-8 text-xs"
              onChange={(e) => setConfig({ ...cfg, baseUrl: e.target.value })}
            />
            <p className="text-[10px] leading-relaxed text-muted-foreground/70">
              默认 <code className="font-mono">/api</code> = 走 dev server 代理（同源）。
              后端没开 CORS，填绝对地址会被浏览器拦下。
            </p>
          </div>

          <div className="grid gap-1">
            <Label htmlFor="token" className="text-xs font-medium">
              Token
            </Label>
            <div className="flex gap-1.5">
              <Input
                id="token"
                type={showToken ? 'text' : 'password'}
                value={cfg.token}
                placeholder="（未设置）"
                autoComplete="off"
                className="h-8 font-mono text-xs"
                onChange={(e) => setConfig({ ...cfg, token: e.target.value })}
              />
              <Button
                variant="outline"
                size="icon-sm"
                aria-label={showToken ? '隐藏 token' : '显示 token'}
                onClick={() => setShowToken((s) => !s)}
              >
                {showToken ? <EyeOff /> : <Eye />}
              </Button>
            </div>
            <p className="text-[10px] leading-relaxed text-muted-foreground/70">
              {TOKEN_HINT} ｜ 存在本机浏览器，不进仓库。
            </p>
          </div>
        </div>
      </div>

      {/* ── 这次问怎么跑 ─────────────────────────────────── */}
      <div className="panel">
        <div className="panel-head py-2">
          <span className="panel-title">请求参数</span>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setAskSettings({ kb: 'stress', useHybrid: true, useRerank: true })}
          >
            <RotateCcw /> 恢复默认
          </Button>
        </div>

        <div className="grid gap-2.5 px-3.5 py-3">
          <div className="grid gap-1">
            <Label className="text-xs font-medium">知识库</Label>
            <Select value={ask.kb} onValueChange={(v) => setAskSettings({ ...ask, kb: v })}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {KB_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value} className="text-xs">
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <ToggleRow
            id="hybrid"
            label="混合检索（向量 ＋ 全文）"
            hint="关掉 = 纯向量"
            checked={ask.useHybrid}
            onChange={(v) => setAskSettings({ ...ask, useHybrid: v })}
          />
          <ToggleRow
            id="rerank"
            label="精排（重排）"
            hint="关掉 = 只做粗排截断"
            checked={ask.useRerank}
            onChange={(v) => setAskSettings({ ...ask, useRerank: v })}
          />

          <p className="rounded-lg bg-muted/60 px-2.5 py-2 text-[10px] leading-relaxed text-muted-foreground">
            ⚠️ 默认「混合 ＋ 重排」是后端的既有默认，界面不擅改 —— 但基线实测显示
            <strong className="font-medium text-foreground">这正是当前最差的组合</strong>
            （见「评测看板」的 <code className="font-mono">AllHit@3</code> 一行）。
          </p>
        </div>
      </div>
    </div>
  )
}
