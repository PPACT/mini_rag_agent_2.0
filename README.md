<a id="readme-top"></a>

<div align="center">

  <!-- 大标题在上方 -->
  <h1 align="center">🧠 mini_rag_agent_2.0</h1>
  
  <p align="center">
    <b>企业知识库 RAG-Agent（2.0 重构中）—— 可溯源 · 会拒答 · 能发现文档冲突</b>
  </p>
  
  <p align="center">
    目标不止答疑：把散落的文档变成<b>有结构、有关系、值得信</b>的知识底座
    <br />
    知识库侧全本地可跑（PG + pgvector + 本地 embedding），仅生成走云端 LLM
  </p>

  <!-- 徽章在下方，使用 flat-square 扁平样式，系统会自动紧凑居中，绝不强制换行 -->
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/PostgreSQL_17-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/pgvector-336791?style=flat-square" alt="pgvector" />
  <img src="https://img.shields.io/badge/Redis-DC382D?style=flat-square&logo=redis&logoColor=white" alt="Redis" />
  <img src="https://img.shields.io/badge/Ollama-000000?style=flat-square&logo=ollama&logoColor=white" alt="Ollama" />
  <img src="https://img.shields.io/badge/LangGraph-1C3C3C?style=flat-square&logo=langchain&logoColor=white" alt="LangGraph" />
  <img src="https://img.shields.io/badge/MCP-000000?style=flat-square" alt="MCP" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License: MIT" />

  <br /><br />

  <!-- 快捷链接 -->
  <p align="center">
    <a href="docs/架构方案.md"><strong>看架构设计 »</strong></a>
    &middot; 
    <a href="#quick-start">快速开始</a>
    &middot; 
    <a href="#known-boundaries">已知边界</a>
  </p>

</div>

<br />

<details>
  <summary><b>📑 目录</b>（点击展开）</summary>
  <ol>
    <li><a href="#introduction">这是什么</a></li>
    <li><a href="#quick-start">快速开始</a></li>
    <li><a href="#architecture">架构一览</a></li>
    <li><a href="#directory">目录结构</a></li>
    <li><a href="#configuration">配置</a></li>
    <li><a href="#api">接口一览</a></li>
    <li><a href="#rerank">精排（Rerank）后端</a></li>
    <li><a href="#database">两库分离（真实库 / 压测库）</a></li>
    <li><a href="#data-ingestion">语料摄取与清洗</a></li>
    <li><a href="#known-boundaries">当前能力范围</a></li>
    <li><a href="#docs-testing">文档与测试</a></li>
    <li><a href="#license">License</a></li>
  </ol>
</details>

---

<!-- 截图占位：拿到 `/demo` 链路透视图后，把图放到**被 git 跟踪**的目录
     （如 docs/assets/demo.png），然后取消下面两行的注释。 -->
<!--
![链路透视图][demo-screenshot]
-->

<a id="introduction"></a>

## 📖 这是什么 (Introduction)

企业内部知识库的问答系统。用户上传文档（PDF / Word / **Excel** / **代码**），用自然语言提问，系统检索知识库、按需调用业务系统工具、生成**带引用溯源**的答案；当检索到的候选**互相矛盾**时，**主动追问而不是擅自选一个**。

**它要解决的第一个问题是「不敢信」**：企业文档散落各处，而 AI **答错比答不出更贵**。所以它的取舍很明确——**宁可拒答，不可编造**。

四个它特意做对的地方：

- 🛡️ **权限在服务端**：`department` / `secret_level` 一律取自鉴权 token，不信任客户端传参；
- 🎯 **引用是真的**：`sources` 只返回 LLM **实际引用**的块，不是全部召回结果；
- 🤷 **答不上来会说不知道**：判定分**三态**（有答案 / 无答案 / **无法判断**），而不是"猜一个"；
- 📑 **按结构解析**：三层路由（文件级 → 解析器级 → 切块级），**表格整体保留、不被字符数切断**，原表随引用一并返回。

> **2.0 已落地**：三层路由式解析 · **表格内容入库** · **页码元数据**（引用可答"第几页"）· **解析失败显式报错**（不再静默丢文件）。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="quick-start"></a>

## 🚀 快速开始 (Quick Start)

**前置要求**：Docker Desktop（含 Compose v2）／ **Ollama 跑在宿主**／ **一个任意 OpenAI 兼容服务的 API key**（默认 DeepSeek）。

### 方式 A · Docker 一条命令起全栈（推荐：换设备 / 演示都用这个）

> 另一台设备上只需要 **Docker ＋ Ollama ＋ 一个 API key**，不用装 Python / Node。

```bash
# 1) 嵌入模型（宿主；首次约 1.2 GB）
#    ⚠️ 必须监听所有网卡，否则容器连不进来（本项目用 11451，不是默认的 11434）
#    Windows（cmd）: set OLLAMA_HOST=0.0.0.0:11451 && ollama serve
#    macOS / Linux:  OLLAMA_HOST=0.0.0.0:11451 ollama serve
ollama pull bge-m3

# 2) 配置：复制模板，填 LLM_API_KEY（其余默认值即可跑）
cp .env.example .env

# 3) 起全栈：PG + Redis + 自动迁移 + API + worker + 前端
docker compose up -d
```

起来后打开 **<http://localhost:8080>**（用内置演示 token 登录）：

- 🩺 **健康检查**：<http://localhost:8000/health> → `{"status":"ok"}`
- ⚙️ 首次启动自动跑 `alembic upgrade head`；数据落在 Docker 卷里，`down` 后再 `up` 仍在
- 🛑 **停 / 清**：`docker compose down` ／ `docker compose down -v`
- 📘 **完整步骤、排错、边界**：见 **[DEPLOY.md](DEPLOY.md)**
- ⚠️ 容器内**默认 LLM 精排**（镜像不带 `sentence-transformers` / `torch`）；要用本地精排请走方式 B，或在 `.env` 里覆盖 `RERANK_BACKEND=local` 并自备模型。

### 方式 B · 开发模式（改代码 / 跑评测）

```bash
# 1) 依赖（锁定版本）
uv pip install -r requirements.lock

# 2) 只起基础设施（⚠️ 不带服务名会把 API / worker / 前端也一起起）
docker compose up -d postgres redis redis_queue

# 3) Ollama + 模型（本项目把 Ollama 跑在 11451，不是默认的 11434）
#    Windows（cmd）: set OLLAMA_HOST=127.0.0.1:11451 && ollama serve
#    macOS / Linux:  OLLAMA_HOST=127.0.0.1:11451 ollama serve
ollama pull bge-m3

# 4) 建表（两个库都要迁）
python scripts/migrate_all.py --kb both

# 5) 起 API（另开一个终端跑 worker）
PYTHONIOENCODING=utf-8 python -m uvicorn src.main:app
PYTHONIOENCODING=utf-8 python -m arq src.tasks.worker.WorkerSettings
```

> - 要跑**压测库**（15433，见「两库分离」）：`docker compose --profile stress up -d postgres-stress`
> - 只校验不迁移：`python scripts/migrate_all.py --check`

开发模式下打开 <http://127.0.0.1:8000/demo> 是**链路透视页**：一次问答的候选、精排前后、耗时分解都会显示出来，顶部还会标明**本次查询实际落在哪个库、用的哪个精排后端**。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="architecture"></a>

## 🏗️ 架构一览 (Architecture)

```text
入口      /chat（业务问答） · /documents（上传/状态） · /demo（链路透视）
解析      三层路由：文件级（后缀 + magic 互证）→ 解析器级（链式 fallback）→ 切块级
          产出统一中间表示；表格与代码整块不切，段落按段切
检索      混合检索（向量 + 全文）→ RRF 融合 → 两段式精排 → 歧义判定 / 澄清
抽象      VectorStore / BaseEmbedding / BaseReranker —— 各引擎各自实现，业务代码不感知
数据      PostgreSQL 17 + pgvector（向量 + 全文检索同库）；Redis（缓存 + 任务队列）
异步      Arq worker：解析 → 切块 → 本地 embedding → 原子替换切片
```

两条链路的顺序**不同**，且**只有 `/chat` 读写缓存**：

| 入口 | 顺序 |
|---|---|
| `/chat` | 缓存 → 检索 → 歧义判定 → (澄清 ｜ 生成) → 引用校验 → 写缓存 |
| `/demo/ask` | 检索 → 生成 → 歧义判定（**无缓存**） |

> 完整设计（分层 / 数据模型 / 真实链路 / 扩展点）见 [`docs/架构方案.md`](docs/架构方案.md)。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="directory"></a>

## 📁 目录结构 (Directory Structure)

```text
src/
├── api/              chat_api · upload_api · demo_api（含链路透视 WebUI）
├── rag/              retriever · reranker · ambiguity · query_rewriter
├── vector_store/     base(抽象+权限过滤) · pg_vector(实现) · milvus(占位)
├── embedding/        base(抽象) · ollama_embedding · cloud_embedding(占位)
├── document_parser/  routing(三层路由) · parsers · tables(表格) · blocks(统一 IR)
│                     · chunking(块级切块) · semantic_splitter · tokenizer(jieba)
├── agent/            graph_builder(LangGraph) · mcp_client_wrapper · mcp_mock_server
├── db/               kb(两库标识) · connection(按 kb 的连接池)
├── tasks/            queue · worker · document_task
├── config/           settings · litellm_client · prompts
└── auth/ cache/ schemas/ observability/
alembic/versions/     0001 建表 · 0002 切片元数据 · 0003 全文检索 · 0004 原始文件名
                      · 0005 page / raw_table / table_complex（2.0）
eval/                 评测脚本 + 标注数据集（语料由 `CORPUS_DIR` 指定，不入库）
prompts/rag_system.yaml   提示词（外置，便于迭代）
web/                  React 前端（生产构建由 `web/Dockerfile` 的 nginx 托管）
Dockerfile            API / worker 镜像（同一镜像，两种启动命令）
docker-compose.yml    全栈编排（infra + migrate + api + worker + web）
DEPLOY.md             部署说明（Docker 全栈）
docs/                 开发文档
```

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="configuration"></a>

## ⚙️ 配置 (Configuration)

复制 `.env.example` 为 `.env`，填好 LLM 的 key。其余默认值可本地跑通。

**LLM 不绑定特定厂商**：生成链路走 OpenAI 兼容接口（`ChatOpenAI`），判定 / 精排走 LiteLLM，两者读同一组配置。想换厂商，改 **base URL + 模型名 + provider 前缀** 即可。

| 键 | 说明 |
|---|---|
| `LLM_API_KEY` | **LLM 的 key** —— 任何 **OpenAI 兼容**服务都行，不限于 DeepSeek。空值 → `/chat` 返回 503（入库链路不受影响） |
| `LLM_BASE_URL` | LLM 的 base URL，默认 `https://api.deepseek.com` |
| `LLM_MODEL` | 模型名，默认 `deepseek-v4-flash` |
| `LLM_PROVIDER` | LiteLLM 的**协议适配器**前缀（对应 `provider/model`），默认 `deepseek` |
| `OLLAMA_BASE_URL` | 本地 embedding 服务，本项目跑在 `http://localhost:11451`（**非默认 11434**） |
| `OLLAMA_BASE_URL_DOCKER` | 仅 Docker：容器访问**宿主** Ollama 的地址，默认 `http://host.docker.internal:11451` |
| `RERANK_BACKEND` | 本地开发默认 `local`；**容器内默认 `llm`**（镜像不带 `torch`），见下节 |
| `CORPUS_DIR` / `UPLOAD_DIR` | 语料与上传件的位置；**容器内是卷**（`/app/data/corpus` 只读、`/app/data/uploads`），⛔ 不打进镜像 |

> **换模型服务商**：改 `LLM_BASE_URL` + `LLM_MODEL` + `LLM_PROVIDER` 三项即可。注意不同厂商「关闭思考链」的参数并不一致 —— 换 provider 后请复验一次判定调用（日志中 `thinking_leaked` 计数应为 0）。细节见 [`docs/架构方案.md`](docs/架构方案.md)。

**鉴权用内置示例 token（生产环境替换为 JWT / SSO）**：

| token | 身份 |
|---|---|
| `demo-it-token` | IT 部门 · 密级 3 |
| `demo-hr-token` | HR 部门 · 密级 2 |
| `demo-public-token` | 公开 · 密级 0 |

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="api"></a>

## 🔌 接口一览 (API Reference)

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/chat` | 业务问答（固定查真实库；有缓存） |
| `POST` | `/documents/upload` | 上传文档（异步解析；可指定目标库） |
| `GET` | `/documents/{id}` | 查询处理状态 |
| `POST` | `/demo/ask` | 链路透视（返回候选、精排前后、耗时分解） |
| `GET` | `/demo` | 链路透视 WebUI |
| `GET` | `/eval/index` | 评测产物只读索引（前端看板用；经 Web 容器走 `/api/eval/index`） |
| `GET` | `/eval/{name}` | 单个评测产物（只读；含路径穿越校验） |
| `GET` | `/health` | 健康检查 |

> 除 `/health`、`/demo*` 与 `/eval*` 外都需 `Authorization: Bearer <token>`。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="rerank"></a>

## 🎯 精排后端 (Rerank Backend)

检索是两段式：粗排召回 `RERANK_CANDIDATES` 条（默认 20）→ 精排取 `TOP_K` 条（默认 5）。

<details>
<summary><b>👉 两个后端的取舍与切换方式</b>（点击展开）</summary>

<br />

| 后端 | 配置 | 特点 |
|---|---|---|
| `local`（**默认**） | `RERANK_BACKEND=local` | 本地 cross-encoder（`BAAI/bge-reranker-v2-m3`，fp16 加载）：输出确定、无网络依赖、延迟可预期、零 API 成本 |
| `llm` | `RERANK_BACKEND=llm` | 走云端大模型（统一经 `src/config/litellm_client.py` 收口）：省本地模型，但受网络与限流影响 |

> **两个后端都可用，取舍取决于你的场景** —— 本地模型是否已下载 / 能否接受云端依赖 / 是否要做后端对照。本项目不宣称哪个"更好"，用配置切即可。

**切换优先级（从高到低）**：

```bash
# ① 环境变量覆盖（临时，最优先）
RERANK_BACKEND=llm PYTHONIOENCODING=utf-8 python -m uvicorn src.main:app
# ② 写进 .env（推荐）
# ③ 改 src/config/settings.py 的 rerank_backend（代码默认值）
```

用 `local` 需本地已有模型权重；设 `HF_HUB_OFFLINE=1` 可跳过 HF 联网检查（启动快很多）。模型**懒加载**：起服务后第一个请求会多花约十几秒载入权重，之后每次精排很快。

> ⚠️ **注意**：用 `llm` 后端时不要开启思考链 —— 推理模型的思考会与结论抢同一份 `max_tokens`，输出可能为空。本项目默认已关闭（`llm_thinking_enabled=False`）；`local` 后端不过 LLM，不受影响。

</details>

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="database"></a>

## 🔀 两库分离 (Database Separation)

`rag_real`(15432) / `rag_stress`(15433) **物理隔离** —— 压测语料与真实业务文档分开，互不干扰检索结果。

| 入口 | 目标库 |
|---|---|
| `/chat` | **固定真实库**（业务入口） |
| `/demo/ask`、`/upload` | 可选，默认真实库 |

`kb` 是**必填的一级参数**：库层（连接池 / 向量库 / 检索 / 任务）**一律无默认值**，忘传即报错；默认值只出现在最外层 HTTP 契约，显式可见、可被调用方覆盖。

> 压测库用 compose `profiles` 按需启，日常 `up -d` 不会启动它。迁移请用 `python scripts/migrate_all.py --kb both`（两个库都迁并逐表比对 schema）；直接 `alembic upgrade head` 只会迁一个库。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="data-ingestion"></a>

## 🧹 语料摄取与清洗 (Data Ingestion & Cleaning)

**语料放在哪由你决定** —— 目录、共享盘、临时路径都行。下面说的是**接口**：文件怎么喂进来、嵌入和清洗在哪一步发生。

<details>
<summary><b>👉 摄取入口 · 嵌入接口 · 清洗挂载点 · 支持格式</b>（点击展开）</summary>

<br />

### 一、摄取入口

| 方式 | 入口 | 说明 |
|---|---|---|
| HTTP | `POST /documents/upload` | 异步解析，返回文档 id；可指定 `kb` |
| 批量 | `python eval/ingest.py` | 逐篇 try —— **一篇失败不中断整批**，结束打印**失败清单** |

两者走**同一条管道**：

```text
文件级路由 → 解析（链式 fallback）→ 〔清洗〕 → 切块 → 嵌入 → 落库
```

### 二、嵌入接口

| 配置项 | 默认 | 说明 |
|---|---|---|
| `EMBEDDING_MODEL` | `bge-m3` | 经 Ollama 调用 |
| `EMBEDDING_DIM` | `1024` | ⚠️ **改了要同步重建向量列**，否则写入报维度不匹配 |
| `EMBEDDING_BATCH_SIZE` | `16` | 批量嵌入的批大小 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | ⚠️ **本项目跑在 `11451`**，必须显式设 |

换任何 OpenAI 兼容的嵌入服务同理：提供 `base_url` + `model` + `dim` 三元组即可。

### 三、清洗接口

清洗规则按**作用范围分布在管道各处**（不只是"解析后"的一步），共 35 条，分 5 组：
**解析前**（编码 / 换行统一）· **解析中**（去标签 / 导航 / 页眉页脚）· **解析后**（去重）· **规范化**（空格 / 全角半角 / 繁简）· **富化**（语言 / 时间 / 来源 / 权限 / 章节 / 表格 / 代码块）。

其中 `keep` 类（权限 / 章节 / 表格 / 代码块）**已随解析层生效**；`remove` / `normalize` 那几组目前**尚未接入** —— 接入时会先以 **shadow 模式**跑，只记录命中量、**不改变输出**，量出误伤率后再逐条放行。

> 规则表与取舍理由见 [`docs/架构方案.md`](docs/架构方案.md)。

### 四、支持的格式

- ✅ **支持**：PDF / Word(`.docx`) / Excel / PPT(`.pptx`) / Markdown / txt / 代码 / HTML(`.html` / `.htm`)
- ❌ **不支持**：其余格式（含 `.doc` / `.ppt` 老格式）→ **报错并给出原因**
- 📷 **扫描件**：暂时只**标记「待 OCR」**，不识别

> 支持哪些格式以 `src/document_parser/routing.py::supported_extensions()` 为准。处理失败的文件不会被跳过：`GET /documents/{id}` 能看到 `failed` 与具体原因。

</details>

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="known-boundaries"></a>

## ✨ 当前能力范围 (Current Capabilities)

- **文档解析**：PDF / Word / Excel / PPT / Markdown / txt / 代码。表格转为自然语言并**保留原表**（随引用一起返回）；PDF 带**页码**；解析失败会**给出原因**，不会静默跳过。
- **检索**：向量 + 全文双路召回 → RRF 融合 → 两段式精排。
- **问答**：引用溯源 · 三态判定（含"无法判断"）· 候选冲突时主动澄清。
- **权限**：部门 + 密级，服务端强制过滤。
- **部署**：embedding 与精排可全本地、不出网；换 LLM 服务商只改配置。

> 图片与扫描件的文字识别、网页正文提取、清洗规则组目前尚未接入。完整的实现边界与演进计划见 [`docs/架构方案.md`](docs/架构方案.md)。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="docs-testing"></a>

## 📚 文档与测试 (Docs & Testing)

| 文档 | 内容 |
|---|---|
| [`docs/架构方案.md`](docs/架构方案.md) | 系统设计：定位 / 选型 / 分层 / 数据模型 / 真实链路 / 扩展点 |
| [`docs/开发记录.md`](docs/开发记录.md) | 搭建过程、踩坑记录、关键设计决策的**理由** |
| [`docs/评测口径.md`](docs/评测口径.md) | 效果用什么尺子量：评测集 schema / 指标定义 / 命中判据 / 实验纪律 |
| [`docs/README.md`](docs/README.md) | 文档目录的边界与放置规则 |

```bash
# 单元测试：切块逻辑、权限过滤 → SQL 翻译、RRF 融合、引用解析
PYTHONPATH=. python -m pytest tests/ -v
```

> `eval/` 下有评测语料、标注数据集与评测脚本（Recall@K / MRR / 漏报误报 / 改述一致率）。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<a id="license"></a>

## 📄 License

MIT —— 见 [`LICENSE`](LICENSE)。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

---

<!-- 有截图后取消 README 顶部的注释，并把图放到被 git 跟踪的目录 -->
[demo-screenshot]: docs/assets/demo.png
