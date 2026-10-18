"""文档上传接口。"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.auth.access import (
    AUTHORITY_LEVELS,
    STAGED_TTL_HOURS,
    commit_ttl_ok,
    document_visible,
    is_direct_uploader,
)
from src.auth.deps import User, get_current_user
from src.config.settings import get_settings
from src.db.connection import get_pool
from src.db.kb import KB_REAL, validate
from src.document_parser.routing import supported_extensions
from src.observability.tracer import audit
from src.schemas.document import DocumentStatus, UploadResponse
from src.tasks.queue import enqueue_process_document

router = APIRouter(prefix="/documents", tags=["documents"])

# ⚠️ **不要在这里另写一份格式清单** —— 它必然与解析层漂移。
# 旧版本此处写着 {"pdf","docx","doc","pptx","ppt"}，其中 `doc` / `ppt`
# **从来就读不了**（python-docx / python-pptx 都不支持旧版二进制格式）：
# 上传放行 → 进 worker 才失败。现在直接引用路由表的唯一事实源。
_ALLOWED = supported_extensions()


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    secret_level: int = Form(0),
    authority: int = Form(0),
    document_id: str | None = Form(None),
    kb: str = Form(KB_REAL),
    user: User = Depends(get_current_user),
) -> UploadResponse:
    """上传文档：落盘 -> 写 documents(pending | staged) -> 入队异步处理。

    department 取自鉴权 token（服务端身份）；secret_level 为文档密级（表单），
    校验不能超过上传者自己的密级。传 document_id 则更新已有文档（version+1 替换 chunk）。

    kb: 目标知识库（真实 / 压测），**默认真实库**——这是**唯一允许出现默认值的地方**：
        "默认写哪个库"属 API 契约，必须显式可见、可被调用方覆盖；
        库层（connection / store / worker）一律**必填无默认**（见 `src/db/kb.py`）。

    文件落盘用 UUID 名，原始文件名存 `documents.original_name`（D9-③）——
    worker 用它填 `chunks.source_file`，引用溯源与 LLM 上下文因此显示真实文件名。
    """
    kb = validate(kb)
    settings = get_settings()
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in (file.filename or "") else ""
    if ext not in _ALLOWED:
        # 报错要能自解释：告诉调用方**支持哪些**，而不是只说他传错了
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext or '(无扩展名)'}；"
                   f"支持：{'、'.join(sorted(_ALLOWED))}",
        )

    if secret_level > user.secret_level:
        raise HTTPException(
            status_code=403,
            detail=f"无权上传密级 {secret_level} 的文档（你的密级为 {user.secret_level}）",
        )
    if authority not in AUTHORITY_LEVELS:
        raise HTTPException(status_code=400,
                            detail="authority 只能是 0（普通）/ 1（正式）/ 2（制度）")

    # `2.0-71`：**直通判定看服务端角色**（⛔ 不由客户端传）——
    # `admin` / `部门负责人` 直通；其余先 `staged`，等 `/documents/{id}/commit` 确认。
    mode = "direct" if is_direct_uploader(user) else "staged"
    initial_status = "pending" if mode == "direct" else "staged"

    os.makedirs(settings.upload_dir_abs, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    # 原始文件名单独一列（D9-③）：`filename` 是 UUID 落盘名，仅供服务端定位文件，**不对外**；
    # `original_name` 才是引用溯源 / LLM 上下文里显示的名字。
    # 只取 basename：该值仅用于展示，不让调用方借它塞路径进来。
    original_name = os.path.basename(file.filename or "").strip() or filename
    dest = os.path.join(settings.upload_dir_abs, filename)

    # 流式写盘 + 大小限制（避免大文件一次性读入内存 OOM）
    written = 0
    too_large = False
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > settings.max_upload_size:
                too_large = True
                break
            f.write(chunk)
    if too_large:
        os.remove(dest)
        limit_mb = settings.max_upload_size // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"文件超过大小限制 {limit_mb}MB")

    pool = await get_pool(kb)
    if document_id:
        # `2.0-70`：**先校验归属**再 UPDATE —— 以前谁都能覆盖别人的文档。
        # ⚠️ 归属（部门 / 密级）**不由更新者改写**：换文件 ≠ 换主人（否则就成了越权的权限变更）
        existing = await pool.fetchrow(
            "SELECT department, secret_level FROM documents "
            "WHERE id=$1::uuid AND is_deleted=false",
            document_id,
        )
        if existing is None or not document_visible(
                existing["department"], existing["secret_level"], user):
            os.remove(dest)
            raise HTTPException(status_code=404, detail="文档不存在或无权修改")

        # 更新已有文档：版本号 +1，替换 chunk（worker 会删旧插新）
        updated_id = await pool.fetchval(
            "UPDATE documents SET filename=$2, original_name=$3, version=version+1, status=$4, "
            "error=NULL, updated_at=now(), uploaded_by=$5, authority=$6, ingest_mode=$7, "
            "ingested_at=NULL "
            "WHERE id=$1::uuid AND is_deleted=false RETURNING id::text",
            document_id, filename, original_name, initial_status,
            user.name, authority, mode,
        )
        if updated_id is None:
            os.remove(dest)
            raise HTTPException(status_code=404, detail="文档不存在或已删除")
        doc_id = document_id
    else:
        doc_id = await pool.fetchval(
            "INSERT INTO documents (filename, original_name, status, department, secret_level, "
            "uploaded_by, authority, ingest_mode) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id::text",
            filename, original_name, initial_status,
            user.department, secret_level, user.name, authority, mode,
        )

    audit("document_upload", document_id=doc_id, kb=kb, user=user.name,
          department=user.department, secret_level=secret_level,
          authority=authority, mode=mode, status=initial_status)
    if mode == "direct":
        await enqueue_process_document(kb, doc_id, user.department, secret_level)
    return UploadResponse(document_id=doc_id, status=initial_status)


@router.get("/{document_id}", response_model=DocumentStatus)
async def get_document_status(
    document_id: str,
    kb: str = KB_REAL,
    user: User = Depends(get_current_user),
) -> DocumentStatus:
    """查询文档处理状态（需鉴权）。

    kb: 文档所在的知识库（真实 / 压测），**默认真实库**，与上传接口一致。
        文档只存在于某一个库中，故由调用方指明；**不做跨库查找**——
        跨库查找等于隐式回退，会掩盖"传错库"这类错误。

    返回的 `filename` 是 UUID 落盘名（内部用），`original_name` 才是展示名——
    对用户/前端展示请用 `original_name`（存量行可能为 NULL，此时回落 `filename`）。
    """
    kb = validate(kb)
    pool = await get_pool(kb)
    row = await pool.fetchrow(
        "SELECT id::text AS document_id, filename, original_name, status, chunk_count, error, "
        "department, secret_level "
        "FROM documents WHERE id = $1::uuid AND is_deleted=false",
        document_id,
    )
    # `2.0-70`：**文档级权限** —— 以前这里谁都能查。
    # ⚠️ 越权一律回 **404**（⛔ 不回 403）：403 等于告诉对方"这份文档确实存在"。
    if row is None or not document_visible(row["department"], row["secret_level"], user):
        raise HTTPException(status_code=404, detail="文档不存在")
    return DocumentStatus(**{k: row[k] for k in
                             ("document_id", "filename", "original_name",
                              "status", "chunk_count", "error")})


@router.post("/{document_id}/commit", response_model=DocumentStatus)
async def commit_staged_document(
    document_id: str,
    kb: str = KB_REAL,
    user: User = Depends(get_current_user),
) -> DocumentStatus:
    """`2.0-71`：确认 `staged` 文档 → 真正入库。

    ⚠️ **嵌入与写 chunk 仍由 worker 做**（与直通同一条管道）—— 这里只负责
    「校验 ＋ 把状态推回 `pending` ＋ 入队」，⛔ 不另写一套 ingest。
    ⚠️ **过期显式报错**（410），⛔ 不静默清理、⛔ 不拿旧文件继续跑。
    """
    kb = validate(kb)
    pool = await get_pool(kb)
    row = await pool.fetchrow(
        "SELECT id::text AS document_id, filename, original_name, status, chunk_count, error, "
        "department, secret_level, created_at "
        "FROM documents WHERE id=$1::uuid AND is_deleted=false",
        document_id,
    )
    if row is None or not document_visible(row["department"], row["secret_level"], user):
        raise HTTPException(status_code=404, detail="文档不存在")
    if row["status"] == "quarantined":
        raise HTTPException(status_code=409, detail="文档已被隔离（quarantined），不能 commit")
    if row["status"] != "staged":
        raise HTTPException(status_code=409,
                            detail=f"只有 staged 文档需要 commit（当前 status={row['status']}）")
    if not commit_ttl_ok(row["created_at"]):
        raise HTTPException(
            status_code=410,
            detail=f"staged 文档已过期（超过 {STAGED_TTL_HOURS} 小时），请重新上传",
        )

    await pool.execute(
        "UPDATE documents SET status='pending', error=NULL, updated_at=now() WHERE id=$1::uuid",
        document_id,
    )
    await enqueue_process_document(kb, document_id, row["department"], row["secret_level"])
    audit("document_commit", document_id=document_id, kb=kb, user=user.name)
    return DocumentStatus(
        document_id=row["document_id"], filename=row["filename"],
        original_name=row["original_name"], status="pending",
        chunk_count=row["chunk_count"], error=None,
    )
