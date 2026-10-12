"""全局配置：pydantic-settings 读取 .env。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（src/config/settings.py -> 上三级），避免依赖 cwd 漂移
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_models_dir() -> Path:
    """conda 环境下的 `models/` 目录 —— ⭐ **环境资源的唯一落点**（用户 2026-10-11 规则）。

    ⛔ **这里不出现任何本机绝对路径** —— 用 `sys.prefix`（当前解释器所属环境的根）
    相对定位，于是它在**任何机器上**都指向"那个环境自己的 `models/` 目录"，
    **路径可移植、也不把机器信息写进 tracked 文件**（`R-5`）。
    """
    import sys

    return Path(sys.prefix) / "models"


def _default_rerank_model() -> str:
    """精排模型的解析：**优先 conda 环境里的本地副本**，否则用 HF 模型名。"""
    local = _env_models_dir() / "bge-reranker-v2-m3"
    return str(local) if local.is_dir() else "BAAI/bge-reranker-v2-m3"


def _default_hf_cache() -> str:
    """**HF 缓存的唯一落点** —— 环境目录下的 `models/hf/hub`（`2.0-62`）。

    ⚠️ **为什么必须显式传**：HF 的默认缓存是 `~/.cache/huggingface`（**C 盘**）——
    不传参数它就一直落那儿（实测 C 盘那份 ≈1.2 GB）。用户裁「**不设 `HF_HOME`**」⇒
    只能在**调用处传 `cache_folder`**（`sentence-transformers` 的参数名）。

    ⚠️ **末级必须是 `hub`** —— 这个参数直接当 `cache_dir` 用，**它下面就得是
    `models--X--Y/` 那层**。实测：指到 `hf/` 会 `OSError: couldn't find them in the
    cached files`；指到 `hf/hub` 才加载成功（2026-10-12 踩过一次）。
    """
    return str(_env_models_dir() / "hf" / "hub")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM —— **任何 OpenAI 兼容服务**（变量名刻意不带厂商前缀，便于换厂商）
    # 生成链路走 ChatOpenAI + base_url，本来就是厂商中立的；
    # 判定 / 精排走 LiteLLM，需要下面这个 provider 前缀。
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    # 默认值需与 .env.example 一致：此处曾遗留 "deepseek-chat"（旧模型名，项目实际不用），
    # 照默认跑会静默用错模型。
    llm_model: str = "deepseek-v4-flash"
    # LiteLLM 用 `<provider>/<model>` 选**协议适配器**。
    # ⚠️ **默认保持 "deepseek" 是刻意的，不是漏改**：
    #    实测（`logs/verify_provider_unbind.py`，四组对照）——把前缀换成通用的 `openai/` 后，
    #    `reasoning_effort="none"`（关思考）**被静默忽略** → 思考链复活：
    #    实测 0 字思考 / 983ms  →  7298 字思考 / 11591ms，且 `finish_reason=length`
    #    （思考吃满 max_tokens）→ **正是 7d16cc3 修掉的那个 bug 原样复现**。
    #    换厂商时改这里，并**复验一次判定调用**——`litellm_client` 会打 `thinking_leaked` 告警兜底。
    llm_provider: str = "deepseek"

    # Embedding（本地 Ollama）
    # ⚠️ 默认 11434 是 Ollama 标准端口；本项目实际把 Ollama 跑在 11451
    # （见 scripts/start_demo.py 的 OLLAMA_HOST，规避 Windows 保留端口段），
    # 所以 .env 必须显式设 OLLAMA_BASE_URL=http://localhost:11451，否则连不上。
    ollama_base_url: str = "http://localhost:11434"
    # 空闲多久后允许 Ollama 卸载 embedding 模型。Ollama 默认 5m，代价是
    # **每次隔一会儿再问，第一个请求要重载模型（实测多等 ~2.5 秒）**。
    # 折中取 30m：短暂离开回来不用等，长时间闲置仍会释放显存（bge-m3 约 660MB）。
    # 取值：Go duration 字符串（"30m"/"1h"）或秒数；-1 = 常驻不卸载（显存换延迟）。
    ollama_keep_alive: str = "30m"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    embedding_batch_size: int = 16

    # PostgreSQL + pgvector —— **两库分离**：真实业务库 / 压测库
    # 背景：合成评测语料含 624 篇"近重复干扰"，与真实文档同库会**淹没真实答案**（详见交流区 §1.6）。
    # kb 取值见 `src/db/kb.py`，**必填、无默认**（有默认就会"忘传 → 静默落真实库"）。
    # 端口与 docker-compose 保持一致（15432 真实 / 15433 压测）。
    database_url: str = "postgresql://rag:rag_demo_pwd@localhost:15432/rag_real"
    database_url_stress: str = "postgresql://rag:rag_demo_pwd@localhost:15433/rag_stress"

    def db_url(self, kb: str) -> str:
        """按 kb 取连接串。**无默认分支**——未知 kb 必须抛错，不能回退。"""
        from src.db.kb import KB_REAL, KB_STRESS, validate

        validate(kb)
        return self.database_url if kb == KB_REAL else self.database_url_stress


    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # 向量库开关（pgvector | milvus）
    vector_store: str = "pgvector"

    # 范围模型：公司级文档的部门标记（全员可见）。
    # 用户可见范围 = 公司级 + 本部门 —— 少了它，全员该看的制度反而看不到。
    company_scope: str = "公司"

    # 范围过滤：硬 vs 软
    # 硬过滤（默认，安全）：范围外完全排除。元数据一旦标错/缺失 → 永久静默搜不到。
    # 软过滤：范围内权重 1.0、范围外 ×penalty 降权但不排除 → 标错时文档仍能找到（排后）。
    # 高密级场景仍需硬隔离（secret_level 永远硬过滤），此开关只影响「范围偏好」。
    scope_soft_enabled: bool = False
    scope_soft_penalty: float = 0.85   # 实测：0.6 降权过重致标错文档掉出候选，0.85 可使其回到第 2

    # 应用
    upload_dir: str = "./data/uploads"
    max_upload_size: int = 50 * 1024 * 1024  # 上传大小上限（默认 50MB）
    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k: int = 5
    cache_ttl: int = 3600

    # 多查询扩展（Query Rewriting）
    # 实测（清晰题 80 条）：单独使用零增益；与精排组合后关掉它 Recall@1 反而 0.800→0.850、MRR 0.872→0.896。
    # 且它是链路里的一级 LLM（4→3 级），关掉可减少方差。故默认关闭，保留开关备用。
    query_rewrite_enabled: bool = False
    query_rewrite_count: int = 3       # 生成的改写变体数（不含原问题）
    rrf_k: int = 60                    # RRF 融合常数

    # 两段式检索：粗排召回 → 精排（Rerank）
    rerank_enabled: bool = True
    rerank_candidates: int = 20        # 粗排召回的候选数（精排后取 top_k）
    rerank_snippet_chars: int = 300    # 送进精排时每条的截断长度（控成本）

    # 精排后端：local = 本地 cross-encoder（**默认**）｜ llm = 云端 LLM
    #
    # ⚠️ **默认保持 local 是 2026-09-27 的用户裁决**（不是在"llm 更差"的基础上定的）。
    #    §8 矩阵实测 **llm 质量更好**（R@1 0.938 vs 本地 0.875），但仍然**暂不改默认**：
    #
    #    ① **迁移性未知（最要命）**：那个优势来自压测语料里 **624 篇人造近重复** ——
    #       恰是 LLM 精排的强项（它能读懂 `21:1-23:1` vs `20:00-22:00`）；
    #       **真实文档没有这类干扰**，而**真实库现在是空的** → 改了也**无法在真实业务上验证**
    #       （P-4：在当前语料上能验证 ≠ 能迁移）。
    #    ② **成本未算**：llm 精排 = 每次问答**多一次云调用**（20 候选 × 300 字 ≈ 4000+ tokens 输入）。
    #    ③ ⚠️ **本注释原来的理由已作废**：原写"默认 local 因为不受思考链影响" ——
    #       该说法已被 §8 实测**推翻**（llm 质量更好）。**结论照旧，但理由必须换掉**，
    #       否则下一个人会拿一个错理由去支持一个对结论。
    #
    # 想改用 llm：设 `RERANK_BACKEND=llm`（全局），或在 `/demo` 用**后端选择器逐请求切换**
    # （D11，不改变默认值）。本地模型未下载 / 显存不足时也可显式切 llm。
    rerank_backend: str = "local"
    # ⭐ 模型解析：**优先用 conda 环境里的本地副本**（用户 2026-10-11 裁：环境资源放环境里）。
    # ⛔ **绝不把本机绝对路径写在这里** —— 本文件是 tracked 的，绝对路径 = 机器信息（`R-5`）。
    # ⇒ 用 `sys.prefix`（**当前环境根**）相对定位：在任何机器上都指向"那个环境自己的
    #    `models/` 目录"，**路径可移植**；找不到才回落到 HF 模型名。
    rerank_local_model: str = Field(default_factory=_default_rerank_model)
    # ⭐ `2.0-62`：HF 缓存的落点 —— 默认**环境目录下的 `models/hf`**（⛔ 不是 C 盘）。
    #    ⚠️ 只对"**需要下载/按模型名查找**"的路径有意义；本地目录模型（如 v2-m3）不受它影响。
    hf_cache_dir: str = Field(default_factory=_default_hf_cache)
    rerank_local_device: str = ""      # 空 = 自动（有 CUDA 用 cuda，否则 cpu）
    # 加载精度："" = 默认（fp32）｜ "fp16" = 半精度。
    # ⚠️ 这不是可选优化而是**必需**：`bge-reranker-v2-m3` fp32 要 2.27 GB 显存，
    #    在 8 GB 卡上（Ollama 还占着一份）会打满 → 实测掉进抖动、跑不动；
    #    **同一份权重按 fp16 加载只占 1.09 GB** ⇒ 装得下（2026-10-11 实测）。
    rerank_local_dtype: str = "fp16"

    # ⭐ 路由（2026-10-11）：**按块内容的数字密度**决定「送进精排的文本形态」。
    #
    #   背景：实测**抽核心句**（按 query 挑句子）在**短文本语料**上有效
    #   （`AllHit@3` 5→7 / 9→10），但在**年报类长文档**上**无效**（CFQA 负向比 11→12）——
    #   因为年报的答案大量在**表格/数字**里，抽句规则（按句号切 ＋ 2-gram 重合）**对表格无效**。
    #
    #   → 所以按**块自己的数字密度**分流，而不是按"哪个库"：
    #     · 数字密度 **≥ 阈值** ⇒ 判为「数值/表格类」→ ⛔ **不抽句，保留上下文**
    #     · 否则 ⇒ 判为「纯文本」→ **抽核心句**
    #
    #   📌 阈值依据（2026-10-11 实测 p50）：纯文本语料 **9.2%** ｜ 年报（金融）**26.3%**
    #   ⚠️ **不用 `raw_table` 判**：PDF 块**永远没有** `raw_table`（`parse_pdf` 不抽表），
    #      实测 CFQA **0/4848** ⇒ 拿它当信号会**在年报上全判成"非表格"**。
    rerank_route_enabled: bool = True      # ✅ 2026-10-11 用户裁「按建议走」→ 开
    rerank_numeric_density: float = 20.0   # 数字密度阈值（%）

    # 混合检索（向量 + 全文检索 RRF 融合，兜底"精确词"查询）
    hybrid_search_enabled: bool = True

    # HNSW 检索深度。pgvector 默认 40，实测在 1231 切片时**损失 12% 召回**，
    # 提到 100 仅多 ~3ms 即可恢复满召回 —— 默认值会静默降低检索质量。
    hnsw_ef_search: int = 100

    # LLM 思考链（DeepSeek 推理模型专用开关）
    # 实测（2026-09-19）：**判定/精排这类分类任务，开思考是有害的** ——
    #   ① 思考（reasoning_content）与结论（content）**共用 max_tokens 预算**，
    #      思考一旦吃满预算 → finish_reason=length、content 为空 →
    #      parse_result("") 会**静默返回"不歧义"** → 漏报（实测有歧义题被整题漏掉）。
    #   ② 慢：开思考 4~10 秒 ｜ 关掉 0.7~1.4 秒。
    # ⚠️ litellm 语义坑：DeepSeek 的 `reasoning_effort` **除 "none" 外都是开启思考**——
    #    传 "low" 不是"少思考"，而是"开启思考"。要关只有 "none"。
    llm_thinking_enabled: bool = False

    # 歧义判定（避免"候选互相矛盾却擅自选一个"）
    ambiguity_check_enabled: bool = True
    # ⚠️ `ambiguity_source_threshold` 已于 2026-09-28 **移除**（P1-3 移除门控）。
    #    它原本驱动「来源分散度 ≥N 才判定」那道门控，而数据判该门控**无效且有害**
    #    （通过率 98% 省不下调用，还制造 2~7 例漏报，见 `优化方案.md` §3 P1-3）。
    #    ⚠️ **不要加回来**：留下一个"生产不读的配置项"正是本项目最怕的
    #    「配置值不生效」陷阱 —— 改了它但毫无效果，且不报错。
    #    门控的**复现对照**（eval 侧）用各自脚本里的局部常量，不再走全局配置。
    ambiguity_snippet_chars: int = 300

    # ===== LLM 预算（**D9-⑨⑩ 由硬编码提为配置项**）=====
    #
    # ⑩ `max_tokens`：这个值**就是「思考链 bug」的触发条件之一** ——
    #   思考（reasoning_content）与结论（content）**共用同一份预算**，思考一旦吃满 →
    #   finish_reason=length、content 为空 → 调用方静默拿到空串（判定器会静默判"不歧义"）。
    #   故开启思考时必须同步调大它，否则 bug 原样复现（启动时会告警，见 warn_if_thinking_enabled）。
    llm_max_tokens: int = 2048

    # ⑨ 超时 / 重试：**按路径分档，不做"对齐"**。
    #   本项目要求：**延迟不可接受** → 超时应相对**正常耗时**留合理倍数。
    #   ① 判定 / 精排（延迟敏感）：正常 0.5~1.5s → 8s，**无重试** → 最坏 ~8s
    #      （原来 60s 超时 = 等于没有超时，长尾故障代价全额转给用户）
    #   ② 生成（Agent）：正常 ~2.5s → 20s，重试 1 次 → 最坏 ~40s
    #      （原来 `max_retries=3` × 60s = **最坏 180s+**）
    #   ⚠️ 曾经的设想是"两条路径对齐成同样的重试次数"——**那是错的**：
    #      生成侧 3 次重试正是延迟灾难的源头，"对齐"只会把延迟敏感的那条也拖成一样差。
    llm_timeout_judge: float = 8.0        # 判定 / 精排（延迟敏感路径）
    llm_max_retries_judge: int = 0        # 显式 0：这条路上的长尾不该由重试买单
    llm_timeout_generate: float = 20.0    # 生成（Agent）
    llm_max_retries_generate: int = 1

    # `drop_params`：**默认 False = 不静默丢弃**（`2.0-41`）
    #   True 时 litellm 会把**不支持的参数静默丢掉** —— 换 provider 后
    #   `reasoning_effort="none"` 被丢掉 = **思考链复活，且不报错**（D8 踩过的那个坑）。
    #   False 时它**直接报错**：从"静默失效"变成"**响**"。
    #   ⚠️ 它的作用是"让翻译错了就必须响"，所以排在四层处置的**第一位**（见 `docs/开发记录.md` §3.5）。
    #   实测（2026-10-01，deepseek provider）：`False` + `reasoning_effort` **正常通过**（0.53s）
    #   → **当前 provider 下没有别的参数在裸奔**，可安全落地。
    #   ⚠️ 只波及 **LiteLLM 这条路**（判定/精排）—— 生成链路走 `ChatOpenAI`，不经 litellm。
    #   换 provider 后若这里开始报错，**那是设计如此**：说明新 provider 不支持该参数，
    #   该去 `2.0-42`（`ThinkingControl` 适配器）补翻译，而不是把这里改回 True。
    llm_drop_params: bool = False

    @model_validator(mode="after")
    def _reject_unimplemented_backends(self) -> "Settings":
        """fail-closed：把「选了未实现的引擎」挡在**启动期**。

        D9-⑥ 的附加项：`MilvusStore` 是占位桩（所有方法 `raise NotImplementedError`），
        而 `get_vector_store` 只看 `VECTOR_STORE` 就返回它 —— 于是选了 milvus 之后
        **启动、建连、写文档全部正常，直到第一次检索才炸**，属于典型的静默故障。
        配置加载即报错，比运行时深处报错便宜得多。
        """
        if self.vector_store.lower() == "milvus":
            raise ValueError(
                "VECTOR_STORE=milvus 尚未接入（src/vector_store/milvus.py 是占位桩，"
                "所有方法都 raise NotImplementedError）。请用 VECTOR_STORE=pgvector。"
                "—— 选它原本会一路正常、**直到第一次检索才抛错**（静默故障）。"
            )
        return self

    @property
    def upload_dir_abs(self) -> str:
        """上传目录绝对路径（upload_dir 相对路径以项目根为基准）。"""
        p = Path(self.upload_dir)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        return str(p)


@lru_cache
def get_settings() -> Settings:
    """返回单例配置。"""
    return Settings()
