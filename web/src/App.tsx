/**
 * 应用外壳 —— 照 `参考资料/RAG 项目前端 UIUX 重构指南_20261010.md` §二-1 的**左右分栏**：
 * 左侧**对话区**（60%）· 右侧**洞察面板**（40%，**可折叠**）。
 *
 * ⭐ 定位（`roles/ui-agent.md`）：**我不是"又一个前端"，我是「证据的显示器」**。
 *    ⛔ 不做多租户 / 计费 / 权限管理 / 上传管理 / 拒答策略面板。
 */
import { PanelRightClose, PanelRightOpen, Settings2 } from 'lucide-react'
import { Suspense, lazy, useCallback, useState } from 'react'
import { cn } from 'cn'

import { ChatWindow } from '@/components/ChatWindow'
import { InspectorPanel } from '@/components/InspectorPanel'
import { SettingsPanel } from '@/components/SettingsPanel'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { health } from '@/lib/api'
import { useAskSettings } from '@/lib/ask-config'
import { useApiConfig } from '@/lib/config'
import { useAskSession } from '@/lib/use-ask-session'

/**
 * 看板**懒加载** —— 只在点开那个页签时才拉（问答页完全用不到）。
 */
const EvalDashboard = lazy(() =>
  import('@/components/EvalDashboard').then((m) => ({ default: m.EvalDashboard })),
)

type HealthState = 'idle' | 'checking' | 'ok' | 'fail'

/** 页签可从地址栏深链：`#eval` 直接打开评测看板（演示时把链接甩过去即可）。 */
function readTab(): string {
  return window.location.hash === '#eval' ? 'eval' : 'chat'
}

export default function App() {
  const cfg = useApiConfig()
  const askSettings = useAskSettings()
  const session = useAskSession()
  const [settingsOpen, setSettingsOpen] = useState(cfg.token.trim().length === 0)
  const [healthState, setHealthState] = useState<HealthState>('idle')
  const [tab, setTab] = useState(readTab)
  const [showInspector, setShowInspector] = useState(true)

  const changeTab = useCallback((next: string) => {
    setTab(next)
    // 用 replaceState（不塞历史记录，免得退格键要按很多次）
    history.replaceState(null, '', next === 'eval' ? '#eval' : window.location.pathname)
  }, [])

  const ready = cfg.token.trim().length > 0

  const checkHealth = useCallback(() => {
    setHealthState('checking')
    health(cfg)
      .then((ok) => setHealthState(ok ? 'ok' : 'fail'))
      .catch(() => setHealthState('fail'))
  }, [cfg])

  // 演示鉴权：请求过一次就知道当前是谁（`/demo/ask` 回 `user`）
  const who = session.result?.user.name ?? '演示'

  return (
    <Tabs
      value={tab}
      onValueChange={changeTab}
      className="flex h-svh flex-col gap-0 overflow-hidden bg-background"
    >
      {/* ── 极简顶栏 ───────────────────────────────────────────── */}
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-card/40 px-4">
        <div className="flex items-center gap-2.5">
          {/* Logo（内联 SVG，不引图片资源） */}
          <svg viewBox="0 0 32 32" className="size-6 shrink-0" aria-hidden>
            <rect width="32" height="32" rx="8" className="fill-primary" />
            <path
              d="M9 11h14M9 16h9M9 21h11"
              stroke="white"
              strokeWidth="2.4"
              strokeLinecap="round"
              fill="none"
            />
          </svg>
          <div className="flex items-baseline gap-2">
            <h1 className="text-sm font-semibold tracking-tight">RAG 证据看板</h1>
            <span className="hidden text-[11px] text-muted-foreground md:inline">
              界面是入口，数字是内容
            </span>
          </div>
        </div>

        <TabsList className="ml-2 h-8">
          <TabsTrigger value="chat" className="text-xs">
            问答 ＋ 链路透视
          </TabsTrigger>
          <TabsTrigger value="eval" className="text-xs">
            评测看板
          </TabsTrigger>
        </TabsList>

        <div className="ml-auto flex items-center gap-1.5">
          {tab === 'chat' ? (
            <Button
              variant="ghost"
              size="icon"
              aria-label={showInspector ? '收起洞察面板' : '展开洞察面板'}
              title={showInspector ? '收起洞察面板' : '展开洞察面板'}
              onClick={() => setShowInspector((v) => !v)}
              className="hidden lg:inline-flex"
            >
              {showInspector ? <PanelRightClose /> : <PanelRightOpen />}
            </Button>
          ) : null}
          <Badge variant="outline" className="hidden font-mono text-[10px] sm:inline-flex">
            {cfg.baseUrl}
          </Badge>
          {!ready ? (
            <Badge variant="destructive" className="text-[10px]">
              未设 Token
            </Badge>
          ) : null}
          <ThemeToggle />
          {/* 用户头像（演示鉴权）—— 点它 = 切账号 = 打开连接设置 */}
          <button
            type="button"
            onClick={() => setSettingsOpen((v) => !v)}
            title={`当前：${who}（点击切换账号 / 改后端地址）`}
            className="flex size-8 items-center justify-center rounded-full bg-primary/12 text-xs font-semibold text-primary ring-1 ring-primary/20 transition-all duration-200 hover:bg-primary/20"
          >
            {who.slice(0, 1)}
          </button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="连接设置"
            title="连接设置"
            onClick={() => setSettingsOpen((v) => !v)}
          >
            <Settings2 />
          </Button>
        </div>
      </header>

      <Collapsible open={settingsOpen} onOpenChange={setSettingsOpen}>
        <CollapsibleContent className="shrink-0 border-b border-border bg-card/20 p-3">
          <SettingsPanel onHealthCheck={checkHealth} healthState={healthState} />
        </CollapsibleContent>
      </Collapsible>

      {/* ── 左 60% 对话 / 右 40% 洞察 ─────────────────────────── */}
      <TabsContent
        value="chat"
        className={cn(
          'm-0 grid min-h-0 flex-1 gap-3 p-3',
          showInspector ? 'lg:grid-cols-[3fr_2fr]' : 'grid-cols-1',
        )}
      >
        <ChatWindow
          messages={session.messages}
          pending={session.pending}
          ready={ready}
          onAsk={(q) => session.ask(q, cfg, askSettings)}
          onCancel={session.cancel}
          onReset={session.reset}
        />
        {showInspector ? (
          <div className="min-h-0 overflow-y-auto pr-0.5">
            <InspectorPanel result={session.result} pending={session.pending} error={session.error} />
          </div>
        ) : null}
      </TabsContent>

      <TabsContent value="eval" className="m-0 min-h-0 flex-1 overflow-y-auto p-3">
        <Suspense
          fallback={<p className="p-4 text-xs text-muted-foreground">正在载入看板…</p>}
        >
          <EvalDashboard />
        </Suspense>
      </TabsContent>
    </Tabs>
  )
}
