/**
 * 后端 HTTP 客户端 —— **只读**，只调既有接口（⛔ 不改管道、⛔ 不发写请求）。
 *
 * ⚠️ 跨域：后端**没开 CORS** → 默认走同源 `/api/*`，由 `vite.config.ts` 的
 *    `server.proxy` 转发。⛔ 别为了绕开跨域去关浏览器安全策略。
 */
import type { ApiConfig } from './config'
import type { ChatResponse, DemoAskResult } from './types'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

function joinUrl(cfg: ApiConfig, path: string): string {
  return `${cfg.baseUrl.replace(/\/+$/, '')}${path}`
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (body.detail !== undefined) return JSON.stringify(body.detail)
  } catch {
    /* 错误体不是 JSON → 用状态行 */
  }
  return `${res.status} ${res.statusText}`
}

async function postJson<T>(
  cfg: ApiConfig,
  path: string,
  body: unknown,
  headers: Record<string, string> = {},
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(joinUrl(cfg, path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw new ApiError(await readError(res), res.status)
  return (await res.json()) as T
}

/** 探活（无需鉴权）。 */
export async function health(cfg: ApiConfig, signal?: AbortSignal): Promise<boolean> {
  const res = await fetch(joinUrl(cfg, '/health'), { signal })
  return res.ok
}

/** `POST /chat` —— 问答页用（`Authorization: Bearer`）。 */
export function chat(
  question: string,
  cfg: ApiConfig,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  return postJson<ChatResponse>(
    cfg,
    '/chat',
    { question },
    { Authorization: `Bearer ${cfg.token}` },
    signal,
  )
}

export interface AskOptions {
  /** `real` / `stress`。⚠️ 演示要用 **stress** —— 真实语料装在压测库里。 */
  kb: string
  useHybrid: boolean
  useRerank: boolean
}

/**
 * `POST /demo/ask` —— 链路透视页用（token 在 **body** 里，与 `/chat` 不同）。
 * ⭐ 它回的东西比 `/chat` 多得多：候选池 / 精排结果 / 分段耗时 / 判定三态。
 */
export function demoAsk(
  question: string,
  cfg: ApiConfig,
  opts: AskOptions,
  signal?: AbortSignal,
): Promise<DemoAskResult> {
  return postJson<DemoAskResult>(
    cfg,
    '/demo/ask',
    {
      question,
      token: cfg.token,
      kb: opts.kb,
      use_hybrid: opts.useHybrid,
      use_rerank: opts.useRerank,
      with_answer: true,
    },
    {},
    signal,
  )
}

/** `GET /api/eval/*` —— 评测产物（dev server 只读暴露的 `logs/*.json`）。 */
export async function fetchArtifactIndex(signal?: AbortSignal): Promise<string[]> {
  const res = await fetch('/api/eval/index', { signal })
  if (!res.ok) throw new ApiError(await readError(res), res.status)
  const body = (await res.json()) as { files?: string[] }
  return body.files ?? []
}

export async function fetchArtifact<T>(name: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/api/eval/${encodeURIComponent(name)}`, { signal })
  if (!res.ok) throw new ApiError(await readError(res), res.status)
  return (await res.json()) as T
}
