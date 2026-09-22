import unicodedata

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import ResourceFolder


def resource_path(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    if not value:
        return ""
    parts = value.split("/")
    if (
        len(value) > 500
        or len(parts) > 8
        or any(not p or p in (".", "..") or p != p.strip() or len(p) > 80 for p in parts)
        or any(unicodedata.category(c).startswith("C") or c in "\\:%" for c in value)
    ):
        raise HTTPException(422, "目錄須位於 resources 下，最多 8 層；不可包含空名稱、相對跳轉或特殊路徑字元")
    return value


def require_folder(db: Session, tenant_id: str, space_id: str, path: str, owner_key: str):
    if path and not db.get(ResourceFolder, (tenant_id, space_id, owner_key, path)):
        raise HTTPException(404, "目前空間沒有此目錄")


def visible_documents(person_id):
    from sqlalchemy import or_

    from .models import Document

    return or_(Document.owner_person_id.is_(None), Document.owner_person_id == person_id)


def document_location(doc):
    root = "user/default/resources" if doc.owner_person_id else "resources"
    return root + ("/" + doc.resource_path if doc.resource_path else "")
