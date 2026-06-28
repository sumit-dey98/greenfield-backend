"""testimonials: drop redundant child_class text column

Revision ID: 0004_drop_child_class
Revises: 0003_testimonials_class_id
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_drop_child_class"
down_revision = "0003_testimonials_class_id"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("testimonials", "child_class")


def downgrade():
    op.add_column("testimonials", sa.Column("child_class", sa.String(), nullable=True))
    # Note: this does NOT restore the original text values - they're gone once dropped.
    # Re-derive from the class join if you ever need to roll back:
    # UPDATE testimonials t SET child_class = c.name FROM classes c WHERE c.id = t.class_id;