"""评测 / 体检脚本共用的**路径单一来源**。

⭐ **语料目录只在这里解析一次** —— 别处一律：

    from eval.paths import CORPUS_DIR

⚠️ 语料**不在仓库里**（由使用者自行维护，开发只读），因此**目录位置不做任何假设**：
它来自**环境变量 `CORPUS_DIR`**。

- **未设置 ⇒ 显式报错**（⛔ 不回落默认路径、⛔ 不静默空跑 —— 猜一个目录只会让评测
  跑在错的语料上，而且看起来一切正常）。
- 可以写进项目根的 `.env`（本模块会读），也可以直接导出环境变量（后者优先）。
- 好处：换机器 / 换目录只改一处配置，代码里也**不出现任何具体目录结构**。

📌 为什么单列一个模块（**同一事实只留一个来源**）：这条路径原先**硬编码在 12 个文件里**，
一处移动就**12 处同时断链**；两处各写一份**必然漂移**，而且是**静默**漂移。
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # `pydantic-settings` 依赖它；没装就只认真正的环境变量
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

# 项目根（本文件在 <root>/eval/ 下）
ROOT = Path(__file__).resolve().parents[1]

_ENV_KEY = "CORPUS_DIR"


def _resolve_corpus_dir() -> Path:
    """从环境变量解析语料目录；**没有就报错**（带可执行的修复指引）。"""
    # ⚠️ `pydantic-settings` 只把 `.env` 读进**它自己的模型**，**不会**写进 `os.environ`。
    #    所以这里必须显式读一次，否则"写进 `.env` 即可"并不成立。
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env", override=False)

    raw = (os.environ.get(_ENV_KEY) or "").strip()
    if not raw:
        raise RuntimeError(
            f"{_ENV_KEY} 未设置。\n"
            "  语料目录不在仓库里，请显式指向你自己的语料目录：\n"
            "    cmd : set CORPUS_DIR=<你的语料目录>\n"
            "    bash: export CORPUS_DIR=<你的语料目录>\n"
            "    或写进项目根的 .env：CORPUS_DIR=<你的语料目录>\n"
            "⛔ 不提供默认路径 —— 猜一个目录只会让评测跑在错的语料上，且不会报错。"
        )

    path = Path(raw).expanduser()
    if not path.exists():
        raise RuntimeError(
            f"{_ENV_KEY} 指向的目录不存在：{raw}\n"
            "  请检查路径（或改 .env / 环境变量），⛔ 不要用空目录继续跑评测。"
        )
    return path


CORPUS_DIR = _resolve_corpus_dir()

__all__ = ["ROOT", "CORPUS_DIR"]
