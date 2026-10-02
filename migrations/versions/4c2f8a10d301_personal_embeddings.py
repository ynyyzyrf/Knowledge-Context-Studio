"""Versioned personal embeddings and durable worker lease.

Revision ID: 4c2f8a10d301
Revises: 7f4198c4b3cb
"""

import sqlalchemy as sa
from alembic import op

revision = "4c2f8a10d301"
down_revision = "7f4198c4b3cb"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("namespace_entries", sa.Column("embedding_vectors", sa.JSON(), nullable=True))
    op.add_column(
        "namespace_entries", sa.Column("embedding_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "namespace_entries",
        sa.Column("embedding_model_key", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "namespace_entries", sa.Column("embedding_attempt", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "namespace_entries",
        sa.Column("embedding_available_at", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column("namespace_entries", sa.Column("embedding_lease_token", sa.String(32), nullable=True))
    op.add_column(
        "namespace_entries",
        sa.Column("embedding_lease_until", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column("namespace_entries", sa.Column("embedding_error", sa.String(64), nullable=True))


def downgrade():
    for name in (
        "embedding_error",
        "embedding_lease_until",
        "embedding_lease_token",
        "embedding_available_at",
        "embedding_attempt",
        "embedding_model_key",
        "embedding_version",
        "embedding_vectors",
    ):
        op.drop_column("namespace_entries", name)
