"""测试环境的前置设置（`2.0-74`）。

`eval/paths.py` 现在要求**显式**给出 `CORPUS_DIR`（⛔ 不猜默认路径）。
测试**不读真实语料**，所以这里给一个**临时空目录** —— 既不把测试绑在某个人的数据集上，
也不会因为"没设变量"而让整批测试在 import 阶段就红。

⚠️ 必须在任何 `eval.*` 被导入**之前**设置：`conftest.py` 由 pytest 最先加载。
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("CORPUS_DIR", tempfile.mkdtemp(prefix="mini_pg_agent_test_corpus_"))
