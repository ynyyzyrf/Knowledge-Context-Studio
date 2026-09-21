import time
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def identifier():
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    policy_version: Mapped[int] = mapped_column(Integer, default=1)


class Person(Base):
    __tablename__ = "people"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[float] = mapped_column(Float, default=0)


class Membership(Base):
    __tablename__ = "memberships"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id"), index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(96))
    target_id: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("tenant_id", "id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "agent_id"], ["agents.tenant_id", "agents.id"]),
        UniqueConstraint("tenant_id", "agent_id", "id"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentCredential(Base):
    __tablename__ = "agent_credentials"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "agent_id"], ["agents.tenant_id", "agents.id"]),
        UniqueConstraint("tenant_id", "agent_id", "id"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    expires_at: Mapped[float] = mapped_column(Float)
    revoked_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class CredentialSubject(Base):
    __tablename__ = "credential_subjects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id", "credential_id"],
            ["agent_credentials.tenant_id", "agent_credentials.agent_id", "agent_credentials.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_id", "subject_id"],
            ["subjects.tenant_id", "subjects.agent_id", "subjects.id"],
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    credential_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(32), primary_key=True)


class KnowledgeSpace(Base):
    __tablename__ = "knowledge_spaces"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("sync_state in ('pending','ready','failed')", name="space_sync_state"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_state: Mapped[str] = mapped_column(String(16), default="pending")


class AgentSpaceGrant(Base):
    __tablename__ = "agent_space_grants"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "agent_id"], ["agents.tenant_id", "agents.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "space_id"], ["knowledge_spaces.tenant_id", "knowledge_spaces.id"]
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PersonSpaceGrant(Base):
    __tablename__ = "person_space_grants"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]),
        ForeignKeyConstraint(
            ["tenant_id", "space_id"], ["knowledge_spaces.tenant_id", "knowledge_spaces.id"]
        ),
        CheckConstraint("level in ('editor','viewer')", name="person_space_level"),
    )
    tenant_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    person_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    level: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id", "subject_id"],
            ["subjects.tenant_id", "subjects.agent_id", "subjects.id"],
        ),
        UniqueConstraint("tenant_id", "agent_id", "idempotency_key"),
        UniqueConstraint("tenant_id", "agent_id", "subject_id", "id"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    message_count: Mapped[int] = mapped_column(Integer, default=0)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id", "subject_id", "session_id"],
            [
                "conversations.tenant_id",
                "conversations.agent_id",
                "conversations.subject_id",
                "conversations.id",
            ],
        ),
        UniqueConstraint("session_id", "message_id"),
        UniqueConstraint("session_id", "sequence"),
        CheckConstraint("role in ('user','assistant')", name="message_role"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_id: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(32))
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    message_id: Mapped[str] = mapped_column(String(128))
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(String(32000))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id", "subject_id", "session_id"],
            [
                "conversations.tenant_id",
                "conversations.agent_id",
                "conversations.subject_id",
                "conversations.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_id", "credential_id"],
            ["agent_credentials.tenant_id", "agent_credentials.agent_id", "agent_credentials.id"],
        ),
        UniqueConstraint("session_id", "through_sequence", "kind"),
        UniqueConstraint("tenant_id", "agent_id", "subject_id", "id"),
        CheckConstraint("state in ('pending','running','retry','succeeded','failed')", name="job_state"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str] = mapped_column(String(32))
    session_id: Mapped[str] = mapped_column(String(32))
    credential_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32), default="extract")
    through_sequence: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[float] = mapped_column(Float, default=time.time)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CommitReceipt(Base):
    __tablename__ = "commit_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id", "subject_id", "job_id"],
            [
                "background_jobs.tenant_id",
                "background_jobs.agent_id",
                "background_jobs.subject_id",
                "background_jobs.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_id", "subject_id", "session_id"],
            [
                "conversations.tenant_id",
                "conversations.agent_id",
                "conversations.subject_id",
                "conversations.id",
            ],
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(32))
    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(32))


class MemoryCandidate(Base):
    __tablename__ = "memory_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_id", "subject_id", "job_id"],
            [
                "background_jobs.tenant_id",
                "background_jobs.agent_id",
                "background_jobs.subject_id",
                "background_jobs.id",
            ],
        ),
        UniqueConstraint("job_id", "ordinal"),
        CheckConstraint("status in ('candidate','approved','rejected')", name="candidate_status"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_id: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(32))
    job_id: Mapped[str] = mapped_column(String(32))
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(String(4000))
    source_message_ids: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="candidate")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
