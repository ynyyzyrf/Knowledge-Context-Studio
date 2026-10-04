"""Opt-in automatic storage and durable extraction dispositions."""

import sqlalchemy as sa
from alembic import op

revision = "91a6d3e8c502"
down_revision = "4c2f8a10d301"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agents", sa.Column("memory_policy", sa.String(16), nullable=False, server_default="manual")
    )
    op.add_column(
        "namespace_scope_grants",
        sa.Column("auto_store", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("background_jobs", sa.Column("storage_policy", sa.String(16), nullable=True))
    for name, size in (("storage_outcome", 32), ("storage_reason", 64), ("duplicate_of", 32)):
        op.add_column("memory_candidates", sa.Column(name, sa.String(size), nullable=True))


def downgrade():
    for name in ("duplicate_of", "storage_reason", "storage_outcome"):
        op.drop_column("memory_candidates", name)
    op.drop_column("background_jobs", "storage_policy")
    op.drop_column("namespace_scope_grants", "auto_store")
    op.drop_column("agents", "memory_policy")
