"""清洗规则（`2.0-5`）：**先出报告，再决定动不动库**。

取向（`改进计划.md` → `2.0-5`）：漏洗 → 噪声进库（**可发现**）；误洗 → **静默丢信息**（不可发现）
⇒ **宁可少洗，不可错洗**。所以本模块的产物是 `CleanReport`（每条规则命中多少、样例是什么），
由 `eval/run_clean_shadow.py` 出 shadow 报告；⛔ **解析 / 入库路径不会自动删文本**。

⚠️ **与解析器的分工**：HTML 的「去标签 / 去导航」已由 `trafilatura`（`favor_precision`）在**解析层**完成
—— 这里**不重复**（`CLN-001/002/008`）。本模块只管**解析后仍留在文本里**的东西。

⚠️ **只 `flag` 不删的三类**（判据有假阳性，删了 = 静默丢信息）：
`CLN-009` 去广告 · `CLN-022` 去乱码 · `INJ-002` 注入短语 · **`CLN-036` 疑似孤立页码**。
⚠️ **`INJ-001` 零宽字符归「删」类**（2026-10-17 文档侧改判：只 flag **不提供任何防护** —— LLM 仍看得见它）。

📌 **源码里一律写 `\\uXXXX` 转义，⛔ 不放不可见的字面字符** —— 不可见字符改不动、也审不出来。
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from src.document_parser.blocks import Block, ParsedDoc

_SAMPLE = 120


@dataclass(frozen=True)
class RuleHit:
    rule: str
    """规则号（`CLN-xxx` / `INJ-xxx`）—— 与规划表同名，方便对账。"""
    action: str
    """`remove` / `normalize` / `flag`。⚠️ `flag` 恒不改文本。"""
    where: str
    """`doc` / `block[i]`。"""
    count: int
    """命中次数（按规则定义：行 / 字符 / 处）。"""
    removed: int
    """被删改的字符数（`flag` 恒 0）。"""
    before: str
    after: str = ""

    def clipped(self) -> "RuleHit":
        return RuleHit(self.rule, self.action, self.where, self.count, self.removed,
                       self.before[:_SAMPLE], self.after[:_SAMPLE])


@dataclass
class CleanReport:
    path: str
    hits: list[RuleHit] = field(default_factory=list)

    def add(self, **kw) -> None:
        if kw.get("count", 0):
            self.hits.append(RuleHit(**kw).clipped())

    def summary(self) -> dict[str, dict[str, int | str]]:
        """按规则聚合（**汇总表**用；样例留在 `hits` 里，写文件）。"""
        out: dict[str, dict[str, int | str]] = {}
        for h in self.hits:
            s = out.setdefault(h.rule, {"action": h.action, "blocks": 0, "hits": 0, "removed": 0})
            s["hits"] += h.count          # type: ignore[operator]
            s["removed"] += h.removed     # type: ignore[operator]
            s["blocks"] += 1              # type: ignore[operator]
        return out


# ---------------------------------------------------------------- 字符层

_BOM = "\ufeff"
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
"""`Cc` 控制字符 —— **保留 `\\n` `\\t`**。
⚠️ **零宽字符（`Cf`）不在这里删** —— 它们是注入信号，按 `INJ-001` **只标记不删除**。"""

_ZW = re.compile(r"[\u200b\u200c\u200d\u2060\u2061\u2062\u2063\ufeff]")
"""零宽 / 方向控制类（`Cf`）。⚠️ `\\ufeff`（BOM）在**块中间**出现才算可疑（开头的归 `CLN-015`）。"""

_FW = re.compile(r"[\uff01-\uff5e\u3000]")
"""全角 ASCII 区（U+FF01–U+FF5E）＋ 全角空格（U+3000）。"""

_PAGE_LINE = re.compile(r"^\s*第?\s*\d+\s*页\s*$")
_BARE_NUM = re.compile(r"^\s*\d{1,4}\s*$")
"""疑似孤立页码（`CLN-036`）—— **只 flag**。⚠️ 裸整数行也可能是列表序号 / 金额 / 年份，所以永不删。"""
_GARBLED = re.compile(r"[\ufffd\ue000-\uf8ff]")
"""替换符（U+FFFD）＋ 私用区（U+E000–U+F8FF）—— 这两类基本只出现在乱码里。"""

_CONTROL_CHARS = "\x00-\x08\x0b\x0c\x0e-\x1f\x7f"  # 仅为可读性保留说明用

_AD_WORDS = ("广告", "推广", "赞助", "扫码关注", "点击购买", "限时优惠", "加微信", "关注公众号")
"""`CLN-009` 的关键词判据。⚠️ **只标记不删除**（关键词假阳性 = 静默丢信息）。"""

_INJ_PATTERNS = (
    r"忽略(之前|以上|前面|上述|先前)?.{0,6}(指令|提示|规则|要求)",
    r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions",
    r"(你现在是|从现在起你是|你不再是)",
    r"system\s*prompt",
    r"<\s*/?\s*system\s*>",
    r"(开发者模式|越狱|jailbreak)",
)
"""`INJ-002` 注入短语。⚠️ **只标记不删除** —— 判据是关键词，中文场景的区分度未标定。"""


def _sub_count(pattern: re.Pattern[str], repl, text: str) -> tuple[str, int, int]:
    count = len(pattern.findall(text))
    if not count:
        return text, 0, 0
    new = pattern.sub(repl, text)
    return new, count, len(text) - len(new)


def run_text_rules(text: str, *, is_code: bool = False, first_block: bool = False,
                   where: str = "block") -> tuple[str, list[RuleHit]]:
    """对一段文本依次跑规则；返回 (新文本, 命中列表)。⛔ 不落库、不写文件。"""
    hits: list[RuleHit] = []

    def emit(rule: str, action: str, count: int, removed: int,
             before: str, after: str = "") -> None:
        if count:
            hits.append(RuleHit(rule, action, where, count, removed,
                                before[:_SAMPLE], after[:_SAMPLE]))

    # CLN-015 去 BOM —— **只认文档开头**（块中间的 BOM 归 INJ-001）
    if first_block and text.startswith(_BOM):
        emit("CLN-015", "remove", 1, 1, text[:40])
        text = text[len(_BOM):]

    # CLN-017 统一换行
    if "\r" in text:
        before_text = text
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        emit("CLN-017", "normalize", before_text.count("\r"),
             len(before_text) - len(text), before_text)

    # CLN-016 去控制字符（Cf / 零宽不在此列）
    before_text = text
    text, n, removed = _sub_count(_CTRL, "", text)
    emit("CLN-016", "remove", n, removed, before_text)

    # CLN-018 去多余空行 —— ⚠️ **代码块跳过**：PEP8 的"两层空行"是语义，压了就是改代码
    if not is_code:
        before_text = text
        text, n, removed = _sub_count(re.compile(r"\n{3,}"), "\n\n", text)
        emit("CLN-018", "normalize", n, removed, before_text, text)

    # CLN-020 全角字母 / 数字 / 空格 → 半角（**中文标点保留**）
    # ⚠️ **必须排在 CLN-019 之前**：全角空格转半角后才被 019 的「多空格」规则看见
    #    （顺序反了会留下 `财务部　　编制日期` → `财务部  编制日期` 这种双空格）
    before_text = text

    def _half(m: re.Match[str]) -> str:
        ch = m.group(0)
        if ch == "\u3000":
            return " "
        return chr(ord(ch) - 0xFEE0) if ch.isalnum() else ch

    converted = _FW.sub(_half, text)
    # \u26a0\ufe0f \u547d\u4e2d\u7684 `_FW` \u5305\u542b**\u5168\u90e8**\u5168\u89d2\u6807\u70b9\uff0c\u4f46\u5176\u4e2d\u53ea\u6709\u5b57\u6bcd/\u6570\u5b57/\u7a7a\u683c**\u771f\u88ab\u8f6c\u6362**
    #    \u21d2 \u8ba1\u6570\u53ea\u7b97"\u771f\u53d8\u4e86"\u7684\u5b57\u7b26\uff08\u5426\u5219\u62a5\u51fa 2150 \u6b21\u547d\u4e2d\u5374 0 \u5b57\u7b26\u6539\u52a8\uff0c\u8bef\u5bfc\u8bef\u4f24\u5224\u65ad\uff09
    changed = sum(1 for a, b in zip(text, converted) if a != b)
    if changed:
        emit("CLN-020", "normalize", changed, 0, before_text, converted)
    text = converted

    # CLN-019 去多余空格 —— ⚠️ **代码块跳过**（缩进是语义）
    if not is_code:
        before_text = text
        text, n, removed = _sub_count(re.compile(r"[ \t]{2,}"), " ", text)
        emit("CLN-019", "normalize", n, removed, before_text, text)

    # CLN-007 去页码行（**保留正文数字** —— 只认"整行就是页码"）
    lines = text.split("\n")
    page_lines = [ln for ln in lines if _PAGE_LINE.match(ln)]
    if page_lines:
        kept = [ln for ln in lines if not _PAGE_LINE.match(ln)]
        emit("CLN-007", "remove", len(page_lines),
             len(text) - len("\n".join(kept)), page_lines[0])
        text = "\n".join(kept)

    # INJ-001 零宽字符 → **删**（2026-10-17 文档侧改判：只 flag 不提供任何防护 —— LLM 仍看得见它）
    before_text = text
    text, n, removed = _sub_count(_ZW, "", text)
    emit("INJ-001", "remove", n, removed, before_text)

    # ---- 以下**只 flag** ----

    for pat in _INJ_PATTERNS:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            emit("INJ-002", "flag", 1, 0, text[max(0, m.start() - 20): m.end() + 20])

    for word in _AD_WORDS:
        n = text.count(word)
        if n:
            i = text.find(word)
            emit("CLN-009", "flag", n, 0, text[max(0, i - 20): i + 40])

    bad = _GARBLED.findall(text)
    if bad:
        i = _GARBLED.search(text)
        assert i is not None
        emit("CLN-022", "flag", len(bad), 0, text[max(0, i.start() - 20): i.end() + 20])

    # CLN-036 疑似孤立页码 —— **只 flag**（2026-10-17 文档侧裁定：不放宽 CLN-007 的删除判据）
    # 判据写细：整行仅数字 **且** 位于块首/块尾 **且** 相邻是空行 ⇒ 裸整数行在正文里很常见，宁可少删
    lines = text.split("\n")
    for idx, ln in enumerate(lines):
        if not _BARE_NUM.match(ln):
            continue
        at_edge = idx == 0 or idx == len(lines) - 1
        blank_around = ((idx == 0 or not lines[idx - 1].strip())
                        and (idx == len(lines) - 1 or not lines[idx + 1].strip()))
        if at_edge and blank_around:
            emit("CLN-036", "flag", 1, 0, ln.strip())

    return text, hits


# ---------------------------------------------------------------- 文档级


def _header_footer(blocks: list[Block]) -> list[RuleHit]:
    """`CLN-005/006`：按**页**统计重复的首 / 尾行。

    ⚠️ 只在**有页码**（PDF）时成立；Word/Excel 的 `page` 是 `None`（不编造页码）。
    ⚠️ 阈值保守（至少出现在「一半以上页」且 ≥3 页）—— 宁可漏洗，不可错洗。
    """
    pages: dict[int, list[list[str]]] = defaultdict(list)
    for b in blocks:
        if b.page is not None and b.text.strip():
            pages[b.page].append(b.text.splitlines())
    if len(pages) < 3:
        return []
    heads: Counter[str] = Counter()
    tails: Counter[str] = Counter()
    for linesets in pages.values():
        first = linesets[0][0].strip()
        last = linesets[-1][-1].strip()
        if first:
            heads[first] += 1
        if last:
            tails[last] += 1
    threshold = max(3, len(pages) // 2 + 1)
    out: list[RuleHit] = []
    for line, n in heads.items():
        if n >= threshold:
            out.append(RuleHit("CLN-005", "remove", "doc", n, len(line), line[:_SAMPLE]))
    for line, n in tails.items():
        if n >= threshold:
            out.append(RuleHit("CLN-006", "remove", "doc", n, len(line), line[:_SAMPLE]))
    return out


def apply_rules(doc: ParsedDoc, path: str = "") -> CleanReport:
    """跑整份文档（**只报告**）。返回的 `hits` 里带样例，供人工判误伤。"""
    report = CleanReport(path=path)
    for i, block in enumerate(doc.blocks):
        if not block.text:
            continue
        _, hits = run_text_rules(
            block.text,
            is_code=block.kind == "code",
            first_block=(i == 0),
            where=f"block[{i}]",
        )
        report.hits.extend(hits)
    report.hits.extend(_header_footer(doc.blocks))
    return report
