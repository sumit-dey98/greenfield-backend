"""create counts table (pre-aggregated attendance/results numbers)

Revision ID: 0008_aggregate_counts
Revises: 0007_fk_indexes
Create Date: 2026-07-13

"""
from alembic import op
import sqlalchemy as sa

revision = "0008_aggregate_counts"
down_revision = "0007_fk_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scope_type", sa.String(), nullable=False),
        sa.Column("scope_id", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("period_type", sa.String(), nullable=False),
        sa.Column("period_key", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=True),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_counts_scope_type", "counts", ["scope_type"])
    op.create_index("ix_counts_scope_id", "counts", ["scope_id"])
    op.create_index("ix_counts_metric", "counts", ["metric"])
    op.create_index("ix_counts_period_key", "counts", ["period_key"])
    # The common read pattern: "every class's numbers for this month/exam".
    op.create_index(
        "ix_counts_lookup", "counts", ["scope_type", "period_type", "period_key", "metric"]
    )


def downgrade() -> None:
    op.drop_index("ix_counts_lookup", table_name="counts")
    op.drop_index("ix_counts_period_key", table_name="counts")
    op.drop_index("ix_counts_metric", table_name="counts")
    op.drop_index("ix_counts_scope_id", table_name="counts")
    op.drop_index("ix_counts_scope_type", table_name="counts")
    op.drop_table("counts")
