"""`2.0-64` —— 「格式清单」与「采集范围」是**两件事**，且只有一份事实源。

⚠️ **不测"两清单必须一致"** —— 采集范围**本来就允许更窄**（本批语料没有 `.js` 就不收），
那种断言会**永远红**（教训：「永远红」和「永远绿」一样没用）。
这里只钉两件真的会坏的事：① 格式清单别再被抄成第二份 ② 漏采**不许静默**。
"""
from __future__ import annotations

from eval.ingest import _COLLECT_SUFFIXES, _KNOWN_SUFFIXES, collect_files, scope_skipped


def _touch(d, name: str):
    p = d / name
    p.write_text("x", encoding="utf-8")
    return p


def test_known_suffixes_are_derived_from_routing():
    """格式清单**引用** `routing` 的唯一事实源 —— ⛔ 不是 ingest 自己再抄一份。"""
    from src.document_parser.routing import supported_extensions

    assert _KNOWN_SUFFIXES == frozenset(f".{e}" for e in supported_extensions()), \
        "格式清单被抄成第二份了 —— 应直接引用 routing.supported_extensions()"
    # 旧清单漏掉的正是这类：路由认得、但当时既没报错也没进库
    assert ".js" in _KNOWN_SUFFIXES and ".log" in _KNOWN_SUFFIXES
    # 旧版二进制路由**不认**（没有解析器）—— 它不该被当成"漏采"
    assert ".doc" not in _KNOWN_SUFFIXES


def test_collect_respects_scope_and_reports_skips(tmp_path):
    """采集按**显式范围**；范围外但认得的格式 → **报出来**，⛔ 不静默。"""
    _touch(tmp_path, "a.md")
    _touch(tmp_path, "b.py")
    _touch(tmp_path, "c.js")     # 路由认得、不在采集范围
    _touch(tmp_path, "d.log")    # 同上
    _touch(tmp_path, "e.doc")    # 路由不认得（旧版二进制）

    got = {p.name for p in collect_files(False, [tmp_path])}
    assert got == {"a.md", "b.py"}, f"采集范围变了：{got}"

    skipped = scope_skipped([tmp_path])
    assert skipped == {".js": 1, ".log": 1}, f"漏采没报出来 / 报错了：{skipped}"
    assert ".doc" not in skipped, "路由本来就认不得的格式，不算「漏采」"
