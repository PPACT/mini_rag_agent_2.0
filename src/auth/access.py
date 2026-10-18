"""文档级访问判定（`2.0-70`）＋ 直通判定（`2.0-71`）。

⚠️ **口径与检索侧同一套**：部门 ∈ {本人部门, 公司级} ＋ 密级 ≤ 本人密级
（`chat_api` 里就是 `departments = {user.department, settings.company_scope}`）。

⚠️ 为什么要有这个模块：`2.0-70` 之前**权限只建在 `chunks` 上**，
`/documents/{id}` 谁都能查、能覆盖 —— 文档这一层是**没有建模**的。
把判定抽成纯函数，是为了能**单测反向用例**（拿 A 的身份查/覆盖 B 的文档必须失败），
而不是只在端点里写一段没人能独立验证的 if。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.auth.deps import User
from src.config.settings import get_settings

DIRECT_ROLES = frozenset({"admin", "部门负责人"})
"""`2.0-71`：这两类角色上传**直通**；其余进 `staged` 等确认。"""

AUTHORITY_LEVELS = (0, 1, 2)
"""`2.0-72`：普通 / 正式 / 制度。⚠️ **人声明**，⛔ 不自动推断。"""

STAGED_TTL_HOURS = 24
"""`2.0-71`：`staged` 文档的 commit 时限。⚠️ 过期**显式报错**，⛔ 不静默清理。"""


def document_visible(department: str | None, secret_level: int, user: User) -> bool:
    """这份文档对 `user` 可见吗（与检索侧同一口径）。"""
    if secret_level > user.secret_level:
        return False
    if department is None:
        return True      # 未标注 ⇒ 公司级（与评测灌库 `_scope_of` 的默认同口径）
    return department in (user.department, get_settings().company_scope)


def is_direct_uploader(user: User) -> bool:
    """`2.0-71`：`admin` / `部门负责人` 直通；其余先 `staged`。"""
    return user.role in DIRECT_ROLES


def commit_ttl_ok(created_at: datetime, *, ttl_hours: int = STAGED_TTL_HOURS,
                  now: datetime | None = None) -> bool:
    """`staged` 文档还在 commit 时限内吗。⚠️ 过期由调用方**显式报错**。"""
    now = now or datetime.now(timezone.utc)
    return (now - created_at) <= timedelta(hours=ttl_hours)
