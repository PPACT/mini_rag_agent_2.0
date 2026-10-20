"""`2.0-74`：语料目录**只从环境变量来**。

判据（文档侧 `提醒 #34`）：
1. **未设置 ⇒ 显式报错**（⛔ 不回落默认路径、⛔ 不静默空跑）；
2. **代码里看不出任何具体目录结构** —— 这条**由提交前的全树扫描**保障，
   ⛔ 不写成 committed test：想在测试里断言"某串不出现"，就得先把那串写进测试源码，
   等于自己泄一次（测试文件也是公开的）。

⚠️ 为什么这条要有测试：把默认路径删掉之后，最容易的"修复"就是**加回一个猜的路径**——
那样测试会全绿、评测却可能安静地跑在**空目录或错的目录**上。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from eval import paths


def _no_dotenv(monkeypatch):
    """隔离 `.env`：本机 `.env` 里可能**确实**设了 CORPUS_DIR，否则测不出"未设置"。"""
    monkeypatch.setattr(paths, "load_dotenv", None)


def test_unset_raises_with_actionable_message(monkeypatch):
    monkeypatch.delenv("CORPUS_DIR", raising=False)
    _no_dotenv(monkeypatch)

    with pytest.raises(RuntimeError) as ei:
        paths._resolve_corpus_dir()

    msg = str(ei.value)
    assert "CORPUS_DIR" in msg
    assert "set CORPUS_DIR=" in msg and "export CORPUS_DIR=" in msg, (
        "报错要能直接照着修（cmd / bash 两种写法）"
    )
    assert "不提供默认路径" in msg, "要说明**为什么**不猜路径，否则下一个人会顺手加回去"


def test_empty_value_counts_as_unset(monkeypatch):
    """`CORPUS_DIR=`（空值）必须按"未设置"处理 —— 否则等于给了个隐式默认。"""
    monkeypatch.setenv("CORPUS_DIR", "   ")
    _no_dotenv(monkeypatch)
    with pytest.raises(RuntimeError):
        paths._resolve_corpus_dir()


def test_set_returns_that_path(monkeypatch, tmp_path):
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path))
    _no_dotenv(monkeypatch)
    assert paths._resolve_corpus_dir() == tmp_path


def test_missing_directory_is_an_error(monkeypatch, tmp_path):
    """指向一个**不存在**的目录也要炸：空跑出来的评测数字比没有更坏。"""
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path / "nope"))
    _no_dotenv(monkeypatch)
    with pytest.raises(RuntimeError) as ei:
        paths._resolve_corpus_dir()
    assert "不存在" in str(ei.value)


def test_corpus_dir_is_a_real_path_in_tests():
    """测试环境里必须**能**解析出路径（`conftest.py` 给了临时目录）——否则 15 个调用方会 import 失败。"""
    assert isinstance(paths.CORPUS_DIR, Path)
