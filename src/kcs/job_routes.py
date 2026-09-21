import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_routes import StrictModel
from .models import AuditEvent, BackgroundJob, CommitReceipt
from .policy import AgentAuth, allowed_subject_ids, locked_agent_auth
from .security import PersonAuth, get_db, person_auth, tenant_membership
from .session_routes import authorized_session

router = APIRouter(prefix="/v1")


class CommitInput(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=128)


def job_payload(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "session_id",
            "subject_id",
            "kind",
            "through_sequence",
            "state",
            "attempt",
            "error_code",
            "created_at",
            "updated_at",
            "input_tokens",
            "output_tokens",
        )
    }


@router.post("/sessions/{session_id}/commit", status_code=202)
def commit_session(
    session_id: str,
    body: CommitInput,
    request: Request,
    auth: AgentAuth = Depends(locked_agent_auth),
    db: Session = Depends(get_db),
):
    session = authorized_session(db, auth, session_id)
    receipt = db.get(CommitReceipt, (auth.tenant_id, auth.agent_id, session_id, body.idempotency_key))
    if receipt:
        return job_payload(db.get(BackgroundJob, receipt.job_id))
    if session.message_count == 0:
        raise HTTPException(409, "會話沒有可提取的訊息")
    job = db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.session_id == session_id,
            BackgroundJob.through_sequence == session.message_count,
            BackgroundJob.kind == "extract",
        )
    )
    if not job:
        job = BackgroundJob(
            tenant_id=auth.tenant_id,
            agent_id=auth.agent_id,
            subject_id=session.subject_id,
            session_id=session_id,
            credential_id=auth.credential_id,
            through_sequence=session.message_count,
            request_id=request.state.request_id,
        )
        db.add(job)
        db.flush()
        db.add(
            AuditEvent(
                tenant_id=auth.tenant_id,
                actor_id=auth.agent_id,
                action="job.submitted",
                target_id=job.id,
                request_id=request.state.request_id,
            )
        )
    db.add(
        CommitReceipt(
            tenant_id=auth.tenant_id,
            agent_id=auth.agent_id,
            subject_id=session.subject_id,
            session_id=session_id,
            idempotency_key=body.idempotency_key,
            job_id=job.id,
        )
    )
    return job_payload(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, auth: AgentAuth = Depends(locked_agent_auth), db: Session = Depends(get_db)):
    job = db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id,
            BackgroundJob.tenant_id == auth.tenant_id,
            BackgroundJob.agent_id == auth.agent_id,
        )
    )
    if not job or job.subject_id not in allowed_subject_ids(db, auth):
        raise HTTPException(404, "找不到任務")
    return job_payload(job)


@router.get("/tenants/{tenant_id}/jobs")
def tenant_jobs(
    tenant_id: str,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    rows = db.scalars(
        select(BackgroundJob)
        .where(BackgroundJob.tenant_id == tenant_id)
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id)
        .offset(offset)
        .limit(limit)
    )
    return {"items": [job_payload(row) for row in rows]}


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(
    job_id: str, request: Request, auth: AgentAuth = Depends(locked_agent_auth), db: Session = Depends(get_db)
):
    job = db.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.tenant_id == auth.tenant_id,
            BackgroundJob.agent_id == auth.agent_id,
        )
        .with_for_update()
    )
    if not job or job.subject_id not in allowed_subject_ids(db, auth):
        raise HTTPException(404, "找不到任務")
    if job.state != "failed":
        raise HTTPException(409, "只可重試失敗任務")
    job.state, job.error_code, job.available_at = "pending", None, time.time()
    job.credential_id = auth.credential_id
    job.max_attempts = job.attempt + 3
    job.updated_at = time.time()
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor_id=auth.agent_id,
            action="job.retried",
            target_id=job.id,
            request_id=request.state.request_id,
        )
    )
    return job_payload(job)
