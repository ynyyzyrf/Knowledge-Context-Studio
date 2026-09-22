"""Resource folders and document placement within a knowledge space."""

import sqlalchemy as sa
from alembic import op

revision = "da912601af82"
down_revision = "c58d1e7a2b40"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "resource_folders",
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("owner_key", sa.String(32), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["tenant_id", "space_id"], ["knowledge_spaces.tenant_id", "knowledge_spaces.id"]
        ),
        sa.PrimaryKeyConstraint("tenant_id", "space_id", "owner_key", "path"),
    )
    op.add_column("documents", sa.Column("resource_path", sa.String(500), nullable=False, server_default=""))

    op.add_column(
        "documents", sa.Column("owner_person_id", sa.String(32), sa.ForeignKey("people.id"), nullable=True)
    )
    op.add_column(
        "agent_credentials",
        sa.Column("namespace_person_id", sa.String(32), sa.ForeignKey("people.id"), nullable=True),
    )
    op.create_table(
        "namespace_agent_grants",
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("person_id", sa.String(32), nullable=False),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "space_id"], ["knowledge_spaces.tenant_id", "knowledge_spaces.id"]
        ),
        sa.ForeignKeyConstraint(["tenant_id", "agent_id"], ["agents.tenant_id", "agents.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        sa.PrimaryKeyConstraint("tenant_id", "space_id", "person_id", "agent_id"),
    )


def downgrade():
    op.drop_table("namespace_agent_grants")
    op.drop_column("agent_credentials", "namespace_person_id")
    op.drop_column("documents", "owner_person_id")
    op.drop_column("documents", "resource_path")
    op.drop_table("resource_folders")
