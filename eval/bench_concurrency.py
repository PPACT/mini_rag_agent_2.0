"""并发压测：把"高并发"变成数字（`2.0-57②` / `2.0-10`）。

## 它测什么

| 场景 | 打哪个接口 | 回答的问题 |
|---|---|---|
| `chat_cache_hit` | `POST /chat`（同一条问题） | **纯 API ＋ Redis** 的吞吐上限 |
| `chat_cache_miss` | `POST /chat`（不同问题） | 冷路径（真实库）的吞吐 |
| `retrieval_only` | `POST /demo/ask`（`with_answer=false`，`stress` 库） | 检索 ＋ 判定的吞吐 |
| `stages` | `POST /demo/ask` | ⭐ **时间花在哪一段**（检索 / 判定 / 生成） |
| `embed` | 进程内直接调嵌入 | 嵌入自身随并发怎么变（判"瓶颈是不是它"） |

## ⚠️ 口径与边界（读数字前先读这段）

- 打的是**本机单进程 uvicorn**（与 `start_demo.py` 现状一致）—— ⛔ 不是集群、不是多 worker。
- `/chat` **固定查真实库**；`/demo/ask` 显式选 `stress`。两者**不是同一个库**，别跨场景比。
- 每次测量前**预热**（模型加载 / 连接建立），否则首请求的冷启动会污染 QPS。
- ⛔ **别把这里的分段耗时当生产 SLA**：它含**云端 LLM** 的往返，受 provider 与账户限速影响。

## 用

    # 起服务（另开一个终端）
    python -m uvicorn src.main:app --port 8000
    # 压测
    python eval/bench_concurrency.py --base http://127.0.0.1:8000
    python eval/bench_concurrency.py --base ... --mode embed     # 只测嵌入
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
# ⚠️ `--mode embed` 要在**本进程内** import `src.*`：脚本在 `eval/` 下跑时，
#    `src` 不在 sys.path 上（其它 eval 脚本同样做这一步）。
sys.path.insert(0, str(ROOT))
DATASET = ROOT / "eval" / "local" / "dataset_layered_50q.jsonl"
TOKEN = "demo-it-token"          # 源码里的演示 token（`src/auth/deps.py`），不是密钥
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def pctl(values, q):
    s = sorted(values)
    if not s:
        return None
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


async def _fire(client, url, payload_fn, n, conc):
    sem = asyncio.Semaphore(conc)
    lat, codes, bodies = [], {}, []

    async def one(i):
        async with sem:
            t0 = time.perf_counter()
            try:
                r = await client.post(url, json=payload_fn(i))
                code = r.status_code
                bodies.append(r.json())
            except Exception:  # noqa: BLE001
                code = -1
            lat.append(time.perf_counter() - t0)
            codes[code] = codes.get(code, 0) + 1

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(n)))
    return lat, codes, time.perf_counter() - t0, bodies


def _stat(lat, codes, wall, n):
    return {
        "n": n, "wall_s": round(wall, 2), "qps": round(n / wall, 2) if wall else None,
        "p50_ms": round(pctl(lat, .50) * 1000, 1),
        "p90_ms": round(pctl(lat, .90) * 1000, 1),
        "p95_ms": round(pctl(lat, .95) * 1000, 1),
        "max_ms": round(max(lat) * 1000, 1),
        "gt_5s_ratio": round(sum(1 for x in lat if x > 5) / len(lat), 3),
        "codes": codes,
    }


def _stage_stat(bodies, key):
    vals = [b.get("timings", {}).get(key) for b in bodies]
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return None
    return {"p50": round(pctl(vals, .5), 1), "p90": round(pctl(vals, .9), 1),
            "max": round(max(vals), 1)}


async def _scenarios(base: str, questions: list[str]) -> dict:
    out: dict = {}
    async with httpx.AsyncClient(timeout=180.0, headers=HEADERS) as client:
        for _ in range(30):
            try:
                if (await client.get(f"{base}/demo")).status_code == 200:
                    break
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(1)
        else:
            raise SystemExit("服务没起来")

        # 预热：把模型加载 / 建连挤出去
        await client.post(f"{base}/chat", json={"question": "年假有几天？"})
        await client.post(f"{base}/demo/ask",
                          json={"question": questions[0], "token": TOKEN,
                                "kb": "stress", "with_answer": True})

        warm = {"question": "年假有几天？"}
        await client.post(f"{base}/chat", json=warm)   # 确保入缓存
        a = {}
        for c in (1, 2, 4, 8):
            lat, codes, wall, _ = await _fire(client, f"{base}/chat", lambda i: warm, 40, c)
            a[c] = _stat(lat, codes, wall, 40)
        out["chat_cache_hit"] = a

        b = {}
        for c in (1, 2, 4):
            lat, codes, wall, _ = await _fire(
                client, f"{base}/chat",
                lambda i, c=c: {"question": f"{questions[(i * 7 + c) % len(questions)]}（压测 {time.time_ns()}）"},
                8, c)
            b[c] = _stat(lat, codes, wall, 8)
        out["chat_cache_miss"] = b

        r = {}
        for c in (1, 2, 4):
            lat, codes, wall, _ = await _fire(
                client, f"{base}/demo/ask",
                lambda i, c=c: {"question": questions[(i * 3 + c) % len(questions)],
                                "token": TOKEN, "kb": "stress", "with_answer": False},
                8, c)
            r[c] = _stat(lat, codes, wall, 8)
        out["retrieval_only"] = r

        # 分段归因
        st = {}
        for with_answer in (False, True):
            for c in (1, 4):
                lat, codes, wall, bodies = await _fire(
                    client, f"{base}/demo/ask",
                    lambda i: {"question": questions[i % len(questions)], "token": TOKEN,
                               "kb": "stress", "with_answer": with_answer},
                    8, c)
                st[f"with_answer={with_answer}_conc={c}"] = {
                    k: _stage_stat(bodies, k)
                    for k in ("retrieve_ms", "ambiguity_ms", "generate_ms", "total_ms")
                }
        out["stages"] = st
    return out


async def _embed() -> dict:
    from src.config.settings import get_settings
    from src.embedding.base import get_embedding

    emb = get_embedding()
    settings = get_settings()
    await emb.embed(["预热"])
    out = {"backend": "ollama", "url": settings.ollama_base_url,
           "model": settings.embedding_model, "result": {}}
    for conc in (1, 2, 4, 8):
        sem = asyncio.Semaphore(conc)
        lat = []

        async def one():
            async with sem:
                t0 = time.perf_counter()
                await emb.embed(["员工差旅报销标准与审批流程说明"])
                lat.append(time.perf_counter() - t0)

        n = 20
        t0 = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(n)))
        wall = time.perf_counter() - t0
        out["result"][conc] = {"n": n, "qps": round(n / wall, 2),
                               "p50_ms": round(pctl(lat, .5) * 1000, 1),
                               "p90_ms": round(pctl(lat, .9) * 1000, 1)}
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--mode", default="all", choices=("all", "scenarios", "embed"))
    ap.add_argument("--json", default=str(ROOT / "logs" / "bench_concurrency.json"))
    args = ap.parse_args()

    result: dict = {"base": args.base, "ts": time.time()}
    if args.mode in ("all", "scenarios"):
        questions = [json.loads(line)["question"]
                     for line in open(DATASET, encoding="utf-8")]
        result["scenarios"] = await _scenarios(args.base, questions)
    if args.mode in ("all", "embed"):
        result["embed"] = await _embed()

    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("产物 →", args.json)


if __name__ == "__main__":
    asyncio.run(main())
