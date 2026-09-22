"""Product resource folders; paths never become host filesystem or engine paths."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent_routes import record
from .auth_routes import StrictModel
from .document_routes import lock_permission
from .models import ResourceFolder
from .policy import person_space
from .resource_folders import require_folder, resource_path
from .security import PersonAuth, get_db, person_auth

router = APIRouter(prefix="/v1/tenants/{tenant_id}/spaces/{space_id}/folders")


class FolderInput(StrictModel):
    parent: str = Field(default="", max_length=500)
    scope: Literal["private", "shared"] = "private"
    name: str = Field(min_length=1, max_length=80)


@router.get("")
def folders(
    tenant_id: str,
    space_id: str,
    scope: Literal["private", "shared"] = "private",
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    person_space(db, tenant_id, space_id, auth)
    paths = db.scalars(
        select(ResourceFolder.path)
        .where(
            ResourceFolder.tenant_id == tenant_id,
            ResourceFolder.space_id == space_id,
            ResourceFolder.owner_key == (auth.person.id if scope == "private" else ""),
        )
        .order_by(ResourceFolder.path)
    ).all()
    return {"items": [{"path": path, "name": path.rsplit("/", 1)[-1]} for path in paths]}


@router.post("", status_code=201)
def create_folder(
    tenant_id: str, space_id: str, body: FolderInput, request: Request, db: Session = Depends(get_db)
):
    auth = lock_permission(db, request, tenant_id, space_id, write=body.scope == "shared")
    owner_key = auth.person.id if body.scope == "private" else ""
    parent = resource_path(body.parent)
    name = resource_path(body.name)
    if "/" in name:
        raise HTTPException(422, "一次只能建立一層目錄")
    path = resource_path(f"{parent}/{name}" if parent else name)
    require_folder(db, tenant_id, space_id, parent, owner_key)
    if db.get(ResourceFolder, (tenant_id, space_id, owner_key, path)):
        return {"path": path, "name": name}
    count = db.scalar(
        select(func.count())
        .select_from(ResourceFolder)
        .where(
            ResourceFolder.tenant_id == tenant_id,
            ResourceFolder.space_id == space_id,
        )
    )
    if count >= 500:
        raise HTTPException(413, "每個空間最多 500 個目錄")
    db.add(ResourceFolder(tenant_id=tenant_id, space_id=space_id, owner_key=owner_key, path=path))
    record(db, request, auth, tenant_id, "folder.created", space_id, {"path": path})
    return {"path": path, "name": name}
