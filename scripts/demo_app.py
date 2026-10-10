"""`2.0-54` 演示界面（Streamlit）—— **只读 · 不改管道 · 保留链路透视**。

跑法::

    streamlit run scripts/demo_app.py

⛔ 三条硬约束（`2.0-54`）：
1. **只读** —— 不改数据 / 配置；
2. **不改管道** —— 只调既有 `POST /chat` 与 `POST /demo/ask`；
3. ⭐ **必须保留链路透视** —— 候选池 vs 精排结果并排 ＋「提权 / 下移」＋ 耗时分解 ＋ `judge_status` ＋ 引用。

📌 看板**直接读 `logs/*.json`**，⛔ 不动 `eval/**`（约束 4）。
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

# ⚠️ `streamlit run` 只把**脚本所在目录**加进 sys.path（那是 `scripts/`），
#    项目根要自己加 —— 否则 `import src.*` 直接 ImportError。
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from src.ui import api_client, logs_reader  # noqa: E402

st.set_page_config(page_title="mini RAG 2.0 演示", layout="wide")


# --------------------------------------------------------------------------
# 📊 评测看板
# --------------------------------------------------------------------------

def _fmt(pair) -> str:
    """`(命中, 总数)` → `"34/45"`；`None` 侧 → `"—"`。"""
    if not pair:
        return "—"
    a, b = pair
    return "—" if a is None or b in (None, 0) else f"{a}/{b}"


def _render_layered(name: str, data: dict) -> None:
    cfg = data.get("config") or {}
    st.caption(f"题数 **{data.get('dataset_size')}** ｜ kb=`{cfg.get('kb')}` ｜ top={cfg.get('top')} "
               f"｜ 模型 `{cfg.get('model')}`")
    try:
        arms = logs_reader.layered_summary(data)
    except logs_reader.ArtifactError as e:
        st.error(str(e))
        return

    rows = []
    for arm, s in arms.items():
        rows.append({
            "臂": arm,
            "R@1": _fmt(s["R@1"]), "R@3": _fmt(s["R@3"]), "R@5": _fmt(s["R@5"]),
            # ⭐ 主指标（分母 = 多 anchor 子集）
            "AllHit@3": _fmt(s["AllHit@3"]),
            "拒答": _fmt(s["refuse_ok"]),
            "误拒": _fmt(s["false_refuse"]),
            "gen_error": s["gen_error_n"],
            "judge_status": ", ".join(f"{k}:{v}" for k, v in s["judge_status"].items()) or "—",
        })
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption("⭐ **主指标 = `AllHit@3`**（每份出处都进 top-3；分母 = **多 anchor 子集**，"
               "不是「多跳」那 10 题的子集）。判红看 L1/L2/L3 三档（`regression_spec`）。")

    arm = st.selectbox("分层明细（选一个臂）", list(arms))
    pk = arms[arm]["per_kind"]
    if pk:
        st.dataframe(
            [{"类": k,
              "R@1": f"{v['R@1']:.3f}",
              "R@3": f"{v['R@3']:.3f}", "R@5": f"{v['R@5']:.3f}"} for k, v in pk.items()],
            hide_index=True, use_container_width=True,
        )


def _render_l0(data: dict) -> None:
    d = logs_reader.l0_summary(data)
    st.caption("参数：" + " ｜ ".join(f"{k}={v}" for k, v in d["params"].items()))
    st.dataframe([d["summary"]], hide_index=True, use_container_width=True)


def _render_kv(data: dict, title: str) -> None:
    st.caption(title)
    st.json(data, expanded=False)


def dashboard() -> None:
    st.subheader("📊 评测看板")
    st.caption("⛔ 只读 `logs/*.json` —— 数字**不在这里重算**（除了 `AllHit@3`，它调用 `eval/` 的唯一定义）。")

    arts = logs_reader.list_artifacts()
    if not arts:
        st.warning(f"`{logs_reader.LOGS_DIR}` 下没有 `*.json` —— 先跑评测脚本。")
        return

    labels = [f"{a['name']}  · {a['label']}" if a["label"] else a["name"] for a in arts]
    idx = st.selectbox("产物", range(len(arts)), format_func=lambda i: labels[i])
    art = arts[idx]
    ts = _dt.datetime.fromtimestamp(art["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
    st.caption(f"📄 `logs/{art['name']}` ｜ {art['size_kb']} KB ｜ 改于 {ts}")

    try:
        data = logs_reader.load(art["name"])
    except logs_reader.ArtifactError as e:
        st.error(str(e))
        return

    n = art["name"]
    try:
        if n.startswith("layered_eval"):
            _render_layered(n, data)
        elif n.startswith("l0_report"):
            _render_l0(data)
        elif n.startswith("pdf_numeric_e2e"):
            _render_kv(logs_reader.e2e_summary(data), "三臂答对数 ＋ `gen_error`（⚠️ 生成失败单列，不混进分母）")
        elif n.startswith("pdf_numeric_eval"):
            _render_kv(logs_reader.numeric_summary(data), "检索侧比率")
        elif n.startswith("excel_numeric"):
            _render_kv(logs_reader.excel_summary(data), "块长统计 ＋ 两模式对比")
        else:
            st.info("没有专用视图 → 直接看原始 JSON（**不假装解读**）。")
            st.json(data, expanded=False)
    except logs_reader.ArtifactError as e:
        st.error(str(e))


# --------------------------------------------------------------------------
# 💬 对话
# --------------------------------------------------------------------------

def chat_tab(base_url: str, token: str) -> None:
    st.subheader("💬 对话")
    st.caption("走 `POST /chat`（**与线上同一条路**）。")
    q = st.text_input("问题", key="chat_q")
    if st.button("提问", key="chat_go") and q.strip():
        with st.spinner("跑链路中…（开精排约 5~15 秒）"):
            try:
                r = api_client.ask_chat(q, base_url=base_url, token=token)
            except api_client.ApiError as e:
                st.error(str(e))
                return
        st.markdown(r.get("answer") or "_（空答案）_")
        if r.get("need_clarification"):
            st.warning("**需要澄清**：" + "；".join(
                f"{o.get('source')} — {o.get('summary')}" for o in r.get("clarify_options") or []))
        # ⚠️ `unknown` 与 `ambiguous` 必须分开显示（P0-1）—— 否则"没判定"和"判定了：不歧义"长得一样
        js = r.get("judge_status", "clear")
        st.caption(f"判定三态：`{js}`" + ("  ⚠️ **判定器没给出有效结论**" if js == "unknown" else ""))
        srcs = r.get("sources") or []
        if srcs:
            st.dataframe([{"文件": s.get("source_file"), "块": s.get("chunk_index"),
                           "页": s.get("page"), "分": round(s.get("score") or 0, 4)} for s in srcs],
                         hide_index=True, use_container_width=True)


# --------------------------------------------------------------------------
# 🔍 链路透视（⭐ 约束 3：这个不能丢）
# --------------------------------------------------------------------------

def trace_tab(base_url: str, token: str) -> None:
    st.subheader("🔍 链路透视")
    st.caption("候选池 vs 精排结果并排 ＋「提权/下移」＋ 耗时分解 ＋ 判定三态 ＋ 引用校验。")

    c1, c2, c3, c4 = st.columns(4)
    kb = c1.selectbox("知识库", ["real", "stress"])
    hy = c2.checkbox("混合检索", value=True)
    rr = c3.checkbox("精排", value=True)
    backend = c4.selectbox("精排后端", [None, "local", "llm"], format_func=lambda x: x or "（用配置）")
    withans = st.checkbox("生成答案（关掉更快，只看检索）", value=True)
    q = st.text_input("问题", key="trace_q")

    if st.button("跑一次", key="trace_go") and q.strip():
        with st.spinner("跑链路中…"):
            try:
                r = api_client.ask_demo(q, base_url=base_url, token=token, kb=kb,
                                        use_hybrid=hy, use_rerank=rr,
                                        rerank_backend=backend, with_answer=withans)
            except api_client.ApiError as e:
                st.error(str(e))
                return
        st.session_state["trace"] = r

    r = st.session_state.get("trace")
    if not r:
        return

    # ---- 本次实际生效的配置（P-2：回显**实际**值，不是配置里的值）----
    m = r.get("mode") or {}
    rer = r.get("rerank") or {}
    st.caption(
        f"库=`{r.get('kb')}` ｜ 用户=`{(r.get('user') or {}).get('name')}` "
        f"｜ 模式：混合=`{m.get('hybrid')}` 精排=`{m.get('rerank')}` 改写=`{m.get('rewrite')}` "
        f"｜ ⭐ **精排后端实际生效 = `{rer.get('backend')}`**（enabled={rer.get('enabled')}, model=`{rer.get('model')}`）"
    )

    t = r.get("timings") or {}
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("检索（含精排）", f"{t.get('retrieve_ms', 0)} ms")
    k2.metric("生成", f"{t.get('generate_ms', 0)} ms")
    k3.metric("歧义判定", f"{t.get('ambiguity_ms', 0)} ms")
    k4.metric("合计", f"{t.get('total_ms', 0)} ms")

    js = r.get("judge_status", "clear")
    (st.warning if js == "unknown" else st.info)(
        f"判定三态：`{js}`" + (f" ｜ 理由：{r.get('ambiguity_reason')}" if r.get("ambiguity_reason") else ""))

    if r.get("answer") is not None:
        st.markdown(r["answer"])

    cands, final = r.get("candidates") or [], r.get("final") or []
    moves = api_client.rank_moves(cands, final)

    def table(items, title, marks=None):
        st.markdown(f"**{title}**（{len(items)} 条）")
        if not items:
            st.caption("_空_")
            return
        st.dataframe([{
            "#": x.get("rank"),
            "文件": x.get("source"),
            "块": x.get("chunk_index"),
            "分": x.get("score"),
            "": ({"up": "⬆ 精排提权", "down": "⬇ 精排下移"}.get((marks or {}).get(
                api_client.rank_key(x)), "")),
            "片段": (x.get("snippet") or "")[:80],
        } for x in items], hide_index=True, use_container_width=True)

    left, right = st.columns(2)
    with left:
        table(cands, "候选池（粗排）", moves)
    with right:
        table(final, "精排结果")

    cited = r.get("cited") or []
    if cited:
        st.markdown("**⭐ 引用校验**（答案里真引到、且能在精排结果里对上的块）")
        st.dataframe([{"#": x.get("rank"), "文件": x.get("source"),
                       "块": x.get("chunk_index"), "分": x.get("score")} for x in cited],
                     hide_index=True, use_container_width=True)
    elif r.get("answer") is not None:
        st.caption("⚠️ 没有引用命中 —— 生成没按 `[来源N]` 引，或引用对不上任何块。")


# --------------------------------------------------------------------------

def main() -> None:
    st.title("mini RAG 2.0 · 演示")
    st.caption("**只读演示界面** —— 不改管道、不改数据；数字来自 `logs/*.json`。")

    with st.sidebar:
        st.header("连接")
        base_url = st.text_input("后端地址", value=api_client.DEFAULT_BASE_URL)
        token = st.text_input("Token", value=api_client.DEFAULT_TOKEN, type="password")
        st.caption("默认 `demo-it-token`（演示账号，见 `src/auth/demo_users`）。")

    tab_dash, tab_chat, tab_trace = st.tabs(["📊 评测看板", "💬 对话", "🔍 链路透视"])
    with tab_dash:
        dashboard()
    with tab_chat:
        chat_tab(base_url, token)
    with tab_trace:
        trace_tab(base_url, token)


main()
