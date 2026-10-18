"""`2.0-70 / 71 / 72` 合成一批：`documents` 加文档级安全列 ＋ 状态机扩两个状态。

| 列 | 服务于 | 说明 |
|---|---|---|
| `department` / `secret_level` | `2.0-70` | 文档级权限 —— 以前**只建在 `chunks` 上**，文档这层没建模 |
| `uploaded_by` | `2.0-71` | 谁传的（以前查不到） |
| `ingested_at` | `2.0-71` | ⚠️ **只在 `completed` 时写**；`staged` / `failed` 为 `NULL`（⛔ 不拿 `created_at` 冒充） |
| `authority` | `2.0-72` | 0 普通 / 1 正式 / 2 制度 —— **人声明**，默认 0，⛔ 不自动推断 |
| `ingest_mode` | `2.0-71` | `direct` / `staged` |
| `content_hash` | `2.0-71` | 文档级源内容哈希（供重复上传识别；⚠️ 块级哈希在 `chunks`，`0006` 已有） |

状态机：`documents.status` 增加 **`staged`**（等确认）与 **`quarantined`**（隔离，⛔ 不进检索）。

⚠️ **存量行不回填假数据**：`ingested_at` 留 `NULL`（历史上没人记过"什么时候真的灌完"）；
`department` / `secret_level` 也留空 —— 存量文档的归属**没人声明过**，编一个就是伪造。
"""
from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 状态 CHECK 是 0001 里**内联**建的（名字由 PG 自动生成）—— 先按惯例名删、再加具名约束
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check")

    op.execute(
        """
        ALTER TABLE documents
          ADD COLUMN IF NOT EXISTS department    TEXT,
          ADD COLUMN IF NOT EXISTS secret_level  INTEGER NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS uploaded_by   TEXT,
          ADD COLUMN IF NOT EXISTS ingested_at   TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS authority     SMALLINT NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS ingest_mode   TEXT NOT NULL DEFAULT 'direct',
          ADD COLUMN IF NOT EXISTS content_hash  TEXT
        """
    )
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT documents_status_check "
        "CHECK (status IN ('pending','processing','completed','failed','deleted',"
        "'staged','quarantined'))"
    )
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT documents_authority_check "
        "CHECK (authority IN (0, 1, 2))"
    )
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT documents_ingest_mode_check "
        "CHECK (ingest_mode IN ('direct', 'staged'))"
    )
    # 文档级过滤（部门 ＋ 密级）会按这两列查
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_scope "
               "ON documents (department, secret_level)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_scope")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_ingest_mode_check")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_authority_check")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check")
    op.execute(
        """
        ALTER TABLE documents
          DROP COLUMN IF EXISTS content_hash,
          DROP COLUMN IF EXISTS ingest_mode,
          DROP COLUMN IF EXISTS authority,
          DROP COLUMN IF EXISTS ingested_at,
          DROP COLUMN IF EXISTS uploaded_by,
          DROP COLUMN IF EXISTS secret_level,
          DROP COLUMN IF EXISTS department
        """
    )
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT documents_status_check "
        "CHECK (status IN ('pending','processing','completed','failed','deleted'))"
    )
