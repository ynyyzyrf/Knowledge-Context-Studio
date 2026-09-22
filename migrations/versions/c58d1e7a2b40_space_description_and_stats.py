"""space description

Revision ID: c58d1e7a2b40
Revises: 1db99657541c
Create Date: 2026-09-22 09:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c58d1e7a2b40"
down_revision: str | Sequence[str] | None = "1db99657541c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a human-readable description to knowledge spaces."""
    op.add_column(
        "knowledge_spaces",
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    """Remove the description column."""
    op.drop_column("knowledge_spaces", "description")
