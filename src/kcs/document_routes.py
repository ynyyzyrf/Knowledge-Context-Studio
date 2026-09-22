"""Bounded raw uploads; metadata and original bytes commit atomically."""

import hashlib
import time
from pathlib import PurePosixPath
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .agent_routes import record
from .document_reader import complete_text, summarize
from .model_service import ModelServiceError
from .models import Document, DocumentChunk, PersonSpaceGrant, Tenant
from .policy import person_space
from .resource_folders import document_location, require_folder, resource_path, visible_documents
from .security import PersonAuth, get_db, person_auth, tenant_membership

router = APIRouter(prefix="/v1/tenants/{tenant_id}/spaces/{space_id}/documents")
MAX_UPLOAD = 10 * 1024 * 1024


def payload(doc):
    return {
        "id": doc.id,
        "filename": doc.filename,
        "resource_path": doc.resource_path,
        "scope": "private" if doc.owner_person_id else "shared",
        "location": document_location(doc),
        "checksum": doc.checksum,
        "byte_size": doc.byte_size,
        "version": 1,
        "deleted": doc.deleted,
        "state": doc.state,
        "attempt": doc.attempt,
        "chunk_count": doc.chunk_count,
        "error_code": doc.error_code,
        "created_at": doc.created_at,
    }


def lock_permission(db, request, tenant_id, space_id, *, write=True):
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    db.expire_all()
    auth = person_auth(request, db)
    person_space(db, tenant_id, space_id, auth, write=write)
    return auth


def document(db, tenant_id, space_id, document_id, auth):
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.tenant_id == tenant_id, Document.space_id == space_id
        )
    )
    if not doc or (doc.owner_person_id and doc.owner_person_id != auth.person.id):
        raise HTTPException(404, "找不到文件")
    return doc


@router.post("", status_code=202)
async def upload(
    tenant_id: str,
    space_id: str,
    request: Request,
    filename: str = Query(max_length=200),
    folder: str = Query(default="", max_length=500),
    scope: Literal["private", "shared"] = Query(default="private"),
):
    folder = resource_path(folder)
    # Authenticate before consuming a potentially large body. Never hold a policy lock while streaming.
    database = request.app.state.database
    with database.sessions.begin() as db:
        auth = person_auth(request, db)
        person_space(db, tenant_id, space_id, auth, write=scope == "shared")
        owner_key = auth.person.id if scope == "private" else ""
        require_folder(db, tenant_id, space_id, folder, owner_key)
    if not filename.strip() or any(ord(c) < 32 for c in filename) or "/" in filename or "\\" in filename:
        raise HTTPException(422, "檔名不合法")
    if PurePosixPath(filename).suffix.lower() not in (".md", ".txt", ".pdf"):
        raise HTTPException(415, "僅支援 Markdown、UTF-8 文字及文字型 PDF")
    data = bytearray()
    async for block in request.stream():
        if len(data) + len(block) > MAX_UPLOAD:
            raise HTTPException(413, "單一文件上限為 10 MB")
        data.extend(block)
    if not data:
        raise HTTPException(422, "文件不能為空")
    checksum = hashlib.sha256(data).hexdigest()
    with database.sessions.begin() as db:
        auth = lock_permission(db, request, tenant_id, space_id, write=scope == "shared")
        require_folder(db, tenant_id, space_id, folder, owner_key)
        matches = db.scalars(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.space_id == space_id,
                Document.checksum == checksum,
                Document.resource_path == folder,
                Document.owner_person_id == (owner_key or None),
                Document.deleted.is_(False),
            )
        )
        for same in matches:
            # A corrected parser type must not reuse an earlier invalid-format task.
            if (PurePosixPath(same.filename).suffix.lower() == ".pdf") == (
                PurePosixPath(filename).suffix.lower() == ".pdf"
            ):
                return payload(same)
        size, count = db.execute(
            select(func.coalesce(func.sum(Document.byte_size), 0), func.count()).where(
                Document.tenant_id == tenant_id, Document.space_id == space_id, Document.deleted.is_(False)
            )
        ).one()
        if size + len(data) > 100 * 1024 * 1024 or count >= 1000:
            raise HTTPException(413, "空間上限為 100 MB 或 1,000 份文件")
        doc = Document(
            tenant_id=tenant_id,
            space_id=space_id,
            filename=filename.strip(),
            resource_path=folder,
            owner_person_id=owner_key or None,
            checksum=checksum,
            byte_size=len(data),
            source=bytes(data),
            uploaded_by=auth.person.id,
            request_id=request.state.request_id,
        )
        db.add(doc)
        db.flush()
        record(
            db,
            request,
            auth,
            tenant_id,
            "document.uploaded",
            doc.id,
            {"space_id": space_id, "checksum": checksum, "bytes": len(data)},
        )
        return payload(doc)


@router.get("")
def documents(
    tenant_id: str,
    space_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    person_space(db, tenant_id, space_id, auth)
    member = tenant_membership(db, tenant_id, auth)
    grant = db.get(PersonSpaceGrant, (tenant_id, space_id, auth.person.id))
    can_share = member.role == "tenant_admin" or (
        member.role == "editor" and grant and grant.level == "editor"
    )
    rows = list(
        db.scalars(
            select(Document)
            .where(
                Document.tenant_id == tenant_id,
                Document.space_id == space_id,
                visible_documents(auth.person.id),
            )
            .order_by(Document.created_at.desc(), Document.id)
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return {
        "items": [payload(d) for d in rows[:limit]],
        "has_more": len(rows) > limit,
        "can_edit": True,
        "can_share": bool(can_share),
    }


@router.get("/{document_id}")
def preview(
    tenant_id: str,
    space_id: str,
    document_id: str,
    offset: int = Query(0, ge=0),
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    person_space(db, tenant_id, space_id, auth)
    doc = document(db, tenant_id, space_id, document_id, auth)
    rows = (
        list(
            db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc.id)
                .order_by(DocumentChunk.number)
                .offset(offset)
                .limit(11)
            )
        )
        if not doc.deleted
        else []
    )
    return {
        **payload(doc),
        "chunks": [{"number": c.number, "page": c.page, "content": c.content} for c in rows[:10]],
        "has_more": len(rows) > 10,
    }


@router.get("/{document_id}/content")
def full_content(
    tenant_id: str,
    space_id: str,
    document_id: str,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    person_space(db, tenant_id, space_id, auth)
    doc = document(db, tenant_id, space_id, document_id, auth)
    return {"pages": complete_text(db, doc), "checksum": doc.checksum}


@router.post("/{document_id}/summary")
def document_summary(tenant_id: str, space_id: str, document_id: str, request: Request):
    database = request.app.state.database
    with database.sessions.begin() as db:
        auth = person_auth(request, db)
        person_space(db, tenant_id, space_id, auth)
        doc = document(db, tenant_id, space_id, document_id, auth)
        pages = complete_text(db, doc)
        checksum = doc.checksum
    # Do not keep a transaction open during external model calls.
    try:
        summary = summarize(request.app.state.settings, pages)
    except ModelServiceError:
        raise HTTPException(503, "摘要生成失敗，請檢查模型設定或稍後重試") from None
    with database.sessions.begin() as db:
        auth = person_auth(request, db)
        person_space(db, tenant_id, space_id, auth)
        doc = document(db, tenant_id, space_id, document_id, auth)
        if doc.deleted or doc.checksum != checksum:
            raise HTTPException(409, "文件已變更或刪除，請重新載入")
        record(db, request, auth, tenant_id, "document.summarized", doc.id)
    return {"summary": summary, "checksum": checksum}


@router.post("/{document_id}/retry", status_code=202)
def retry(tenant_id: str, space_id: str, document_id: str, request: Request, db: Session = Depends(get_db)):
    auth = lock_permission(db, request, tenant_id, space_id, write=False)
    doc = document(db, tenant_id, space_id, document_id, auth)
    if not doc.owner_person_id:
        person_space(db, tenant_id, space_id, auth, write=True)
    if doc.state != "failed":
        raise HTTPException(409, "只有失敗任務可以重試")
    doc.state, doc.attempt, doc.available_at, doc.error_code = "pending", 0, time.time(), None
    record(db, request, auth, tenant_id, "document.retried", doc.id)
    return payload(doc)


@router.delete("/{document_id}", status_code=202)
def remove(tenant_id: str, space_id: str, document_id: str, request: Request, db: Session = Depends(get_db)):
    auth = lock_permission(db, request, tenant_id, space_id, write=False)
    doc = document(db, tenant_id, space_id, document_id, auth)
    if not doc.owner_person_id:
        person_space(db, tenant_id, space_id, auth, write=True)
    if not doc.deleted:
        doc.deleted, doc.source = True, None
        db.execute(update(DocumentChunk).where(DocumentChunk.document_id == doc.id).values(content=None))
        # An in-flight writer retains its lease; its completion schedules cleanup.
        if doc.state != "running":
            doc.state, doc.attempt, doc.available_at = "pending", 0, time.time()
        record(db, request, auth, tenant_id, "document.deleted", doc.id)
    return payload(doc)
