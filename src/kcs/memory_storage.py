"""Shared transactional memory revision and publication creation."""

import time

from sqlalchemy import update

from .models import MemoryProjection, MemoryRevision


def create_revision(db, memory, *, actor_id, request_id, content, sources, status, reason):
    # Mark pending older operations obsolete. Running operations require completion fencing in the publisher.
    db.execute(
        update(MemoryProjection)
        .where(
            MemoryProjection.memory_id == memory.id,
            MemoryProjection.kind == "upsert",
            MemoryProjection.state.in_(["pending", "retry", "succeeded", "failed"]),
        )
        .values(state="obsolete")
    )
    revision = MemoryRevision(
        memory_id=memory.id,
        version=memory.current_version,
        tenant_id=memory.tenant_id,
        agent_id=memory.agent_id,
        subject_id=memory.subject_id,
        content=content,
        source_message_ids=sources,
        status=status,
        reason=reason,
        actor_id=actor_id,
    )
    db.add(revision)
    db.flush()
    db.add(
        MemoryProjection(
            tenant_id=memory.tenant_id,
            agent_id=memory.agent_id,
            subject_id=memory.subject_id,
            memory_id=memory.id,
            version=memory.current_version,
            kind="upsert" if status == "pending" else "delete",
            request_id=request_id,
        )
    )
    memory.status, memory.updated_at = status, time.time()
    db.flush()
