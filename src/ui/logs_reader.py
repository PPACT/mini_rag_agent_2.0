"""只读 `logs/*.json` 的**展示层** —— 供 `2.0-54` 评测看板用。

⛔ **本模块只读**：不改任何产物、**不动 `eval/**`**（`2.0-54` 约束 2 / 4）。
⭐ **不 import streamlit** —— 纯函数，便于单测（`2.0-54` 约束 7）。

📌 为什么 `AllHit@3` 在这里**不重写**：
口径在 `eval/run_regression.py:_allhit` 已有唯一定义 —— "同一事实只留一个来源"。
本项目 `2.0-51` 已经踩过"两份实现必然静默漂移"，`§1.99` 又踩过一次"手算算错分母"。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 项目根（本文件在 <root>/src/ui/ 下）
ROOT = Path(__file__).resolve().parents[2]
LOGS_DIR = ROOT / "logs"

# 已知产物 → 中文名（看板按它排；**未列出的也会出现在「全部产物」里**，不假装不存在）
KNOWN_ARTIFACTS: dict[str, str] = {
    "layered_eval.json": "分层评估（50 题 · 两轮）",
    "layered_eval_reverify_20261010.json": "分层评估（四臂 · 真验收）",
    "l0_report.json": "L0 切分体检",
    "pdf_numeric_eval.json": "PDF 数值题（检索）",
    "pdf_numeric_e2e.json": "PDF 数值题（端到端）",
    "excel_numeric_eval.json": "Excel 表格块",
    "shadow_bold_heading.json": "shadow：加粗标题",
}


class ArtifactError(RuntimeError):
    """产物缺失 / 读不动。

    ⛔ **显式报错，不静默跳过** —— 静默跳过会渲染成"0 题 / 空表"，
    被当成"结果就是 0"读（本项目纪律：**不做假装支持**）。
    """


def list_artifacts(logs_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """列出 `logs/*.json`（按文件名排序）。目录不存在 → 返回空表（不是异常）。"""
    d = Path(logs_dir) if logs_dir else LOGS_DIR
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(d.glob("*.json")):
        st = p.stat()
        out.append({
            "name": p.name,
            "label": KNOWN_ARTIFACTS.get(p.name, ""),
            "size_kb": round(st.st_size / 1024, 1),
            "mtime": st.st_mtime,
        })
    return out


def load(name: str, logs_dir: Path | str | None = None) -> dict[str, Any]:
    """读一个产物。缺失 / 非法 JSON → `ArtifactError`（**带路径**，便于定位）。"""
    d = Path(logs_dir) if logs_dir else LOGS_DIR
    p = d / name
    if not p.is_file():
        raise ArtifactError(f"产物不存在：{p} —— 先跑对应的评测脚本，别拿空表当结论")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ArtifactError(f"产物不是合法 JSON：{p} —— {e}") from e
    if not isinstance(data, dict):
        raise ArtifactError(f"产物顶层不是对象：{p}（拿到 {type(data).__name__}）")
    return data


def allhit_from_rows(rows: list[dict], k: int = 3) -> tuple[int, int]:
    """`AllHit@K` —— ⭐ **委托给 `eval/run_regression.py` 的唯一定义**（⛔ 不抄一份）。

    延迟 import：看板是**只读展示层**，不该在 import 期就把评测工具链拖进来。
    """
    from eval.run_regression import _allhit  # noqa: PLC0415  —— 有意延迟

    return _allhit(rows, k)


# --------------------------------------------------------------------------
# 各产物的摘要（**只做取数，不做解释** —— 解释是人的事，看板不替人下结论）
# --------------------------------------------------------------------------

def layered_summary(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """分层评估产物 → 逐臂摘要。

    形状（`eval/run_layered_eval.py` 写出的）::

        {"config": {...}, "dataset_size": 50,
         "results": {"<臂名>": {"rows": [...], "summary": {...}}}}

    ⚠️ `R@K` 的分母是**有答案题**（无答案题不算 `R@K`），这里**从行里数**，不硬编码 45。
    """
    results = data.get("results")
    if not isinstance(results, dict) or not results:
        raise ArtifactError("分层评估产物里没有 `results` —— 不是这个脚本产出的？")

    out: dict[str, dict[str, Any]] = {}
    for arm, v in results.items():
        rows = v.get("rows") or []
        s = v.get("summary") or {}
        overall = s.get("overall") or {}
        n_ans = sum(1 for r in rows if r.get("kind") != "no_answer")
        hit, n_multi = allhit_from_rows(rows, 3)

        def cnt(key: str) -> int | None:
            rate = overall.get(key)
            return None if rate is None else round(rate * n_ans)

        out[arm] = {
            "n_total": len(rows),
            "n_answerable": n_ans,
            "R@1": (cnt("R@1"), n_ans),
            "R@3": (cnt("R@3"), n_ans),
            "R@5": (cnt("R@5"), n_ans),
            # ⭐ 主指标：分母 = **多 anchor 子集**（多跳 ＋ 冲突 ＋ 消歧），不是"多跳"那 10 题
            "AllHit@3": (hit, n_multi),
            "refuse_ok": (s.get("refuse_ok"), s.get("refuse_n")),
            "false_refuse": (s.get("false_refuse"), s.get("false_n")),
            "gen_error_n": s.get("gen_error_n", 0),
            "judge_status": dict(s.get("judge_status") or {}),
            "need_clarification": s.get("need_clarification", 0),
            "per_kind": s.get("per_kind") or {},
        }
    return out


def l0_summary(data: dict[str, Any]) -> dict[str, Any]:
    """L0 切分体检 → `params` ＋ `summary`（都是既有字段，直接透出）。"""
    if "summary" not in data:
        raise ArtifactError("L0 产物里没有 `summary`")
    return {"params": data.get("params") or {}, "summary": data.get("summary") or {}}


def numeric_summary(data: dict[str, Any]) -> dict[str, Any]:
    """PDF 数值题 → 比率表 ＋ 题数（形状见 `eval/run_pdf_numeric_eval.py`）。"""
    return {
        "kb": data.get("kb"),
        "top": data.get("top"),
        "mode": data.get("mode"),
        "n": data.get("n"),
        "rates": data.get("rates") or {},
    }


def e2e_summary(data: dict[str, Any]) -> dict[str, Any]:
    """端到端（第四问）→ 三臂答对数 ＋ **`gen_error` 计数**（⚠️ 生成失败必须单列，不能混进分母）。"""
    rows = data.get("rows") or []
    arms: dict[str, dict[str, Any]] = {}
    for arm in ("exp", "ctl", "blind"):
        hit = sum(1 for r in rows if r.get(f"{arm}_has_value"))
        err = sum(1 for r in rows if r.get(f"{arm}_error"))
        arms[arm] = {"has_value": hit, "gen_error": err, "n": len(rows)}
    return {"config": data.get("config") or {}, "arms": arms}


def excel_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Excel 表格块产物 → 块长统计 ＋ 两模式对比。"""
    return {
        "params": data.get("params") or {},
        "blocks_total": data.get("blocks_total") or {},
        "modes": data.get("modes") or {},
    }
