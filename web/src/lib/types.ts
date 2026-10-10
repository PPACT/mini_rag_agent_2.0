/**
 * 后端返回结构的 TS 类型。
 *
 * ⭐ 来源（**照实测写，不是照猜写**）：
 *   - `POST /demo/ask` → `src/api/demo_api.py` 的 `demo_ask()` 返回字典
 *   - `POST /chat`     → `src/schemas/chat.py` 的 `ChatResponse`
 * ⚠️ 权威版永远是 `GET /openapi.json`。这里只是把**已在跑的那版**写成类型，
 *    后端若改了字段，**以 `/openapi.json` 为准**并回来改本文件。
 */

/** `demo_api._brief()` —— 候选 / 精排 / 引用 三处的**同一种**卡片数据。 */
export interface Brief {
  rank: number
  /** `source_file` —— 后端可为 None（无来源文件时），别当必填。 */
  source: string | null
  chunk_index: number
  score: number
  snippet: string
}

/** `POST /demo/ask` 的完整返回 —— ⭐ 链路透视面板的全部数据都出自这里。 */
export interface DemoAskResult {
  question: string
  /** 本次**实际**查询的知识库（回显，防"看错库"）。 */
  kb: string
  user: { name: string; department: string; scope: string[] }
  /** `{"rewrite":bool,"hybrid":bool,"rerank":bool,"rerank_backend":str}` —— 实测生效值。 */
  mode: Record<string, unknown>
  /** 精排后端回显：`backend` 是**本次实际生效**的，不是配置值。 */
  rerank: { backend: string; enabled: boolean; model: string }
  timings: {
    retrieve_ms: number
    generate_ms: number
    ambiguity_ms: number
    total_ms: number
  }
  answer: string | null
  cited: Brief[]
  ambiguous: boolean
  /** 判定三态：`clear` | `ambiguous` | `unknown`。 */
  judge_status: string
  ambiguity_reason: string
  candidates: Brief[]
  final: Brief[]
}

/** `POST /chat`（`src/schemas/chat.py`）。 */
export interface ChatSource {
  source_file: string | null
  chunk_index: number
  score: number
  page: number | null
  raw_table: string | null
}

export interface ClarifyOption {
  source: string
  summary: string
}

export interface ChatResponse {
  answer: string
  sources: ChatSource[]
  need_clarification: boolean
  clarify_options: ClarifyOption[]
  judge_status: string
}

/* --------------------------------------------------------------------------
 * 评测产物（`logs/*.json`）—— 见 `src/lib/eval.ts`
 * ------------------------------------------------------------------------ */

/** 分层评估（`layered_eval*.json`）的一行 = 一题。 */
export interface LayeredRow {
  id: number
  /** `single_hop` | `multi_hop` | `conflict` | `disambig` | `table` | `no_answer` … */
  kind: string
  /** 首位命中的 rank（未命中 = null）。 */
  rank: number | null
  /** 每个 anchor 各自落在第几名（`AllHit@K` 就靠它算）。 */
  ranks_each: (number | null)[]
  hit_source: string | null
  answer: string | null
  /** 生成失败时是错误串（**必须剔出分母**，见 `regression_spec §3.4`）。 */
  gen_error: string | null
  bait_hit: boolean
  refused: boolean
}

export interface LayeredArmSummary {
  overall?: Record<string, number | null>
  per_kind?: Record<string, Record<string, number | null>>
  refuse_ok?: number
  refuse_n?: number
  false_refuse?: number
  false_n?: number
  gen_error_n?: number
  judge_status?: Record<string, number>
  need_clarification?: number
}

export interface LayeredArtifact {
  config?: Record<string, unknown>
  dataset_size?: number
  results: Record<string, { rows?: LayeredRow[]; summary?: LayeredArmSummary }>
}
