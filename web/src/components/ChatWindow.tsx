/**
 * 对话区（`前端ui设计.md` §2.2 / §2.3 ＋ `参考资料/…UIUX 重构指南` §二-1）。
 *
 * ⭐ **AI 的回答放在最前面**，Markdown 渲染。
 * ⭐ 请求期间显示**进行中 ＋ 已等待**（§2.3 的诚实版 —— 见 `trace-stream.ts`：
 *    非流式下**报不出**逐阶段文字，⛔ 不演）。
 */
import { Bot, Loader2, MessageSquarePlus, Send, Sparkles, User } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { MarkdownBody } from '@/components/MarkdownBody'
import { Button } from '@/components/ui/button'
import { formatElapsed } from '@/lib/trace-stream'
import type { ChatMessage, Pending } from '@/lib/use-ask-session'

function Bubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end gap-2">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-sm leading-relaxed text-primary-foreground shadow-sm">
          {msg.text}
        </div>
        <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <User className="size-3.5" />
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-2.5">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary ring-1 ring-primary/15">
        <Bot className="size-3.5" />
      </div>
      <div className="min-w-0 flex-1 pt-0.5">
        {msg.error ? (
          <div className="rounded-xl border border-destructive/30 bg-destructive/[0.06] px-3 py-2.5">
            <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-destructive">
              <span className="inline-block size-1.5 rounded-full bg-destructive" /> 请求失败
            </div>
            <p className="break-all font-mono text-[11px] text-destructive/90">{msg.error}</p>
          </div>
        ) : (
          <MarkdownBody text={msg.text} />
        )}
      </div>
    </div>
  )
}

export function ChatWindow({
  messages,
  pending,
  onAsk,
  onCancel,
  onReset,
  ready,
}: {
  messages: ChatMessage[]
  pending: Pending | null
  onAsk: (q: string) => void
  onCancel: () => void
  onReset: () => void
  /** token 没填时禁用发送（发出去也只会 401）。 */
  ready: boolean
}) {
  const [text, setText] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  // 新消息 / 新状态 → 滚到底（会话越聊越长，不滚就看不到最新那条）
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, pending])

  const submit = () => {
    if (!text.trim() || pending || !ready) return
    onAsk(text)
    setText('')
  }

  return (
    <div className="panel flex min-h-0 flex-col overflow-hidden">
      <div className="panel-head">
        <span className="panel-title">对话</span>
        <Button variant="ghost" size="sm" onClick={onReset} disabled={messages.length === 0}>
          <MessageSquarePlus /> 全新对话
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="space-y-4 px-4 py-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-14 text-center">
              <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Sparkles className="size-5" />
              </div>
              <p className="text-sm font-medium">问一句试试</p>
              <p className="max-w-xs text-[11px] leading-relaxed text-muted-foreground">
                右边会同步展开这次链路的透视 —— 候选池、精排提权/下移、耗时分解、引用校验。
              </p>
            </div>
          ) : (
            messages.map((m) => <Bubble key={m.id} msg={m} />)
          )}

          {pending ? (
            <div className="flex gap-2.5">
              <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary ring-1 ring-primary/15">
                <Bot className="size-3.5" />
              </div>
              <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs text-muted-foreground shadow-sm">
                <Loader2 className="size-3.5 animate-spin" />
                <span className="font-mono tabular-nums">进行中 · 已等待 {formatElapsed(pending.elapsedMs)}</span>
                <button
                  type="button"
                  onClick={onCancel}
                  className="ml-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground transition-all duration-200 hover:bg-muted hover:text-foreground"
                >
                  取消
                </button>
              </div>
            </div>
          ) : null}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="border-t border-border/60 bg-background/40 p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={text}
            rows={2}
            placeholder={ready ? '问点什么…（Enter 发送 · Shift+Enter 换行）' : '先在「连接设置」里填 Token'}
            disabled={!ready}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                submit()
              }
            }}
            className="min-h-[2.75rem] flex-1 resize-none rounded-xl border border-input bg-transparent px-3 py-2 text-sm leading-relaxed outline-none transition-all duration-200 placeholder:text-muted-foreground/60 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:opacity-50"
          />
          <Button size="lg" className="h-[2.75rem]" onClick={submit} disabled={!ready || !!pending || !text.trim()}>
            <Send /> 发送
          </Button>
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground/60">
          本次经由 <code className="font-mono">POST /demo/ask</code> —— 它同时给出答案与链路。
          ⚠️ 与线上 <code className="font-mono">/chat</code> 的差别：不含歧义澄清话术。
        </p>
      </div>
    </div>
  )
}
