# 部署：Docker 全栈（本地演示）

> 目标：**干净机器 → 起来的最短路径**。单机、单副本、**不暴露公网**。

## 前置（3 样）

| 依赖 | 说明 |
|---|---|
| **Docker Desktop** | Windows / macOS 均可；Linux 需 Docker Engine ＋ Compose v2 |
| **Ollama**（留在宿主） | 提供嵌入模型 `bge-m3`（约 1.2 GB） |
| **LLM API Key** | 任何 OpenAI 兼容端点（默认 DeepSeek） |

> Ollama 不放进容器：模型与 GPU 的迁移成本高于收益。它必须监听**所有网卡**，
> 否则容器连不进来（见下面的 `OLLAMA_HOST`）。

## 三步起来

```bash
# 1) 嵌入模型（在宿主）
ollama pull bge-m3
# Windows（cmd）:  set OLLAMA_HOST=0.0.0.0:11451 && ollama serve
# macOS / Linux:  OLLAMA_HOST=0.0.0.0:11451 ollama serve

# 2) 配置（复制模板，填两样：LLM_API_KEY / 如需要 LLM_BASE_URL）
cp .env.example .env

# 3) 起全栈（一条命令）
docker compose up -d
```

起来后：

- 前端：<http://localhost:8080>
- 健康检查：<http://localhost:8000/health> → `{"status":"ok"}`

## 首次启动发生了什么

1. `postgres` / `redis`（缓存）/ `redis_queue`（队列）启动并通过健康检查；
2. **`migrate`** 一次性容器跑 `alembic upgrade head`，成功后退出；
3. `api` / `worker` 启动；`api` 健康后 `web` 启动（nginx 托管生产构建，`/api/` 反代到 API）。

## 验收（三步，别只看"容器起来了"）

1. 打开 <http://localhost:8080>，用演示 token 登录（token 定义见 `src/auth/deps.py` 的 `DEMO_USERS`）。
2. 上传一份文档 → 状态变为 **`completed`**（`worker` 完成解析 / 切块 / 嵌入 / 入库）。
3. 就上传的内容提问 → 答案里带 **[来源N]**。

## 常用命令

```bash
docker compose ps                       # 各服务状态
docker compose logs -f api worker       # 排错第一站
docker compose down                     # 停（**保留**数据卷）
docker compose down -v                  # 停并**删除**数据卷（重置）
docker compose exec api python eval/cost_ledger.py   # 评测成本台账
```

> 成本台账默认写 `logs/`，容器里该目录是**只读挂载** → 会自动改写到 `/tmp/` 并提示。

## 排错

| 现象 | 查这里 |
|---|---|
| 上传后一直 `pending` / `processing` | `docker compose logs worker`；确认 compose 的 `ulimits.stack` 生效（`jieba` 大字典编译需要大栈） |
| 嵌入失败 / 超时 | 容器访问不到宿主 Ollama。确认宿主 `OLLAMA_HOST=0.0.0.0:11451`；容器内验证：<br>`docker compose exec api python -c "import urllib.request;print(urllib.request.urlopen('http://host.docker.internal:11451/api/tags').status)"` |
| 端口被占 | 改 `.env` 的 `API_PORT` / `WEB_PORT` |
| `11451` 绑定失败（Windows） | 端口可能落在系统保留段：`netsh int ipv4 show excludedportrange protocol=tcp`；换端口并同步改 `.env` 的 `OLLAMA_BASE_URL_DOCKER` |
| 看板空白 | 看板数据来自宿主 `logs/`（只读挂载）。新部署为空表是正常的 —— 先跑一次评测脚本 |

## 数据与卷

| 卷 | 内容 |
|---|---|
| `pgdata` / `pgdata_stress` | 两个 PostgreSQL（真实库 / 压测库） |
| `uploads` | 上传的原始文件 |
| `corpus` | 语料目录（**只读**挂进容器，⛔ 不打进镜像） |
| `redisdata` / `redisqueuedata` | 缓存 / 队列 |

> 语料是可选的：不挂也能跑（上传 → 入库 → 检索这条链不依赖预置语料）。
> 需要预置时，往 `corpus` 卷里放文件即可。

## 边界（v1 有意不做）

- **单机、单副本**；不做高可用 / K8s / 反向代理集群。
- **不暴露公网**；没有多用户鉴权与计费。
- **Ollama 留在宿主**（见上）。
- 镜像里**不带**本地精排依赖（`sentence-transformers` / `torch`）⇒ 容器用 **LLM 精排**
  （compose 已设 `RERANK_BACKEND=llm`）。需要本地精排时，在 `.env` 覆盖并自行扩展镜像。
