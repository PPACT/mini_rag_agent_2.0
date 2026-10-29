"""中文分词：为全文检索（tsvector）提供空格分隔的词序列。

为什么需要：PostgreSQL 自带的分词器不切中文（会把一整段中文当成一个 token），
所以必须在 Python 侧用 jieba 切好，再交给 `to_tsvector('simple', ...)` 建索引。
"""
from __future__ import annotations

import importlib.util
import pickle
import re
import sys
import types
from pathlib import Path


def _preload_jieba_prob() -> None:
    """先注册 jieba 的三个概率表模块，**绕过源码编译**。

    ⚠️ 为什么需要：Python 3.11 在编译 `jieba/finalseg/prob_emit.py`（1.3 MB 的字典
    字面量）时会**段错误**（实测：容器里 `import jieba` 必现 SIGSEGV，栈加大也不稳定）。
    jieba 自带同内容的 pickle 文件（`finalseg/*.p`，其 Java 分支就是这么加载的）——
    直接反序列化并注册成子模块，导入时就不会再去编译那份源码。

    📌 两份数据由 jieba 打包时从**同一份源码**生成，内容等价；只读本地已安装的包文件。
    """
    try:
        spec = importlib.util.find_spec("jieba")
    except (ImportError, ValueError):  # 没装 jieba / 路径异常 → 交给正常导入去报错
        return
    if spec is None or not spec.submodule_search_locations:
        return
    base = Path(list(spec.submodule_search_locations)[0]) / "finalseg"
    for name in ("prob_start", "prob_trans", "prob_emit"):
        key = f"jieba.finalseg.{name}"
        pkl = base / f"{name}.p"
        if key in sys.modules or not pkl.is_file():
            continue
        mod = types.ModuleType(key)
        with pkl.open("rb") as fh:
            mod.P = pickle.load(fh)  # noqa: S301 —— 只读本机已安装包内的文件
        sys.modules[key] = mod


_preload_jieba_prob()

import jieba  # noqa: E402  （必须在预加载之后）

# 词典在**首次 cut()** 时才加载（~0.5s）。放在 import 期做掉：
# 否则第一次检索/入库会在事件循环里同步加载，把整个进程卡住半秒。
jieba.initialize()

# 只保留"有意义的"token：字母、数字、汉字（丢弃纯标点/空白）
_PUNCT_ONLY = re.compile(r"^[^\w一-鿿]+$", re.UNICODE)


def tokenize(text: str) -> str:
    """切成空格分隔的词序列，供 `to_tsvector('simple', ...)` / `to_tsquery` 使用。"""
    if not text:
        return ""
    tokens = []
    for word in jieba.cut(text):
        word = word.strip()
        if word and not _PUNCT_ONLY.match(word):
            tokens.append(word.lower())
    return " ".join(tokens)
