"""Read current storage/publication results without persisting another content copy."""

from sqlalchemy import and_, or_, select

from .models import MemoryCandidate, MemoryProjection, MemoryRecord, MemoryRevision


def job_result(db, job):
    counts = dict.fromkeys(("created", "deduplicated", "review_required", "ignored"), 0)
    items = []
    rows = db.execute(
        select(MemoryCandidate, MemoryRecord, MemoryRevision, MemoryProjection)
        .outerjoin(
            MemoryRecord,
            and_(
                MemoryRecord.tenant_id == job.tenant_id,
                MemoryRecord.agent_id == job.agent_id,
                MemoryRecord.subject_id == job.subject_id,
                or_(
                    MemoryRecord.candidate_id == MemoryCandidate.id,
                    MemoryRecord.id == MemoryCandidate.duplicate_of,
                ),
            ),
        )
        .outerjoin(
            MemoryRevision,
            and_(
                MemoryRevision.memory_id == MemoryRecord.id,
                MemoryRevision.version == MemoryRecord.current_version,
            ),
        )
        .outerjoin(
            MemoryProjection,
            and_(
                MemoryProjection.memory_id == MemoryRecord.id,
                MemoryProjection.version == MemoryRecord.current_version,
            ),
        )
        .where(MemoryCandidate.job_id == job.id, MemoryCandidate.tenant_id == job.tenant_id)
        .order_by(MemoryCandidate.ordinal)
    )
    for candidate, memory, revision, projection in rows:
        outcome = candidate.storage_outcome or "review_required"
        reason = candidate.storage_reason or "manual_policy"
        if memory and memory.status in ("disabled", "deleted"):
            outcome, reason = "ignored", "memory_" + memory.status
        elif memory and outcome == "review_required":
            outcome, reason = "created", "human_approved"
        elif not memory and candidate.status == "rejected":
            outcome, reason = "ignored", candidate.storage_reason or "human_rejected"
        counts[outcome] += 1
        items.append(
            {
                "candidate_id": candidate.id,
                "outcome": outcome,
                "reason": reason,
                "content": revision.content if revision else candidate.content,
                "source_message_ids": candidate.source_message_ids,
                "memory_id": memory.id if memory else None,
                "memory_version": memory.current_version if memory else None,
                "memory_status": memory.status if memory else None,
                "publication": {"state": projection.state, "error_code": projection.error_code}
                if projection
                else None,
            }
        )
    publication = [i["publication"] for i in items if i["outcome"] in ("created", "deduplicated")]
    if job.state == "failed":
        state = "failed"
    elif job.state != "succeeded":
        state = "waiting" if job.state == "pending" else "processing"
    elif any(p and p["state"] == "failed" for p in publication):
        state = "failed"
    elif any(not p or p["state"] != "succeeded" for p in publication):
        state = "indexing"
    elif counts["review_required"]:
        state = "review_required"
    elif publication:
        state = "ready"
    else:
        state = "no_changes"
    return {
        "policy": job.storage_policy,
        "pipeline_state": state,
        "reason": "no_durable_facts" if job.state == "succeeded" and not items else job.error_code,
        "counts": counts,
        "items": items,
        "content_role": "untrusted_reference_data",
    }
