# API 与 worker 共用同一个镜像（两者代码相同，只是启动命令不同）。
# 依赖全部来自 requirements.lock（可复现）。
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ⛔ 不装 apt 包：healthcheck 用 Python 探活（compose 里那条命令），少一层网络依赖
COPY requirements.lock ./
# ⚠️ `requirements.lock` 是在 Windows 上生成的，含 `pywin32`（`mcp` 的 Windows 专用依赖，
#    PyPI 上没有 Linux 发行版）⇒ 构建时过滤掉它；**其余版本仍严格按 lock 安装**。
RUN grep -viE '^pywin32(==|-ctypes==)' requirements.lock > /tmp/requirements.linux.lock \
 && pip install --no-cache-dir --no-compile -r /tmp/requirements.linux.lock

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY eval ./eval
COPY prompts ./prompts
COPY scripts ./scripts

# 非 root 运行；数据目录在这里先建好（挂卷后由卷覆盖）
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /app/data/uploads /app/data/corpus /app/logs \
 && chown -R app:app /app/data /app/logs
USER app

EXPOSE 8000

# ⚠️ 本地精排（sentence-transformers / torch）**不在** requirements.lock 里
#    ⇒ 容器默认用 LLM 精排（compose 里设 RERANK_BACKEND=llm）。
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
