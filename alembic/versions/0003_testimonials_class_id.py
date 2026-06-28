"""testimonials: add class_id FK to classes

Revision ID: 0003_testimonials_class_id
Revises: 0002_subjects_is_active
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_testimonials_class_id"
down_revision = "0002_subjects_is_active"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("testimonials", sa.Column("class_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "testimonials_class_id_fkey", "testimonials", "classes", ["class_id"], ["id"], ondelete="SET NULL"
    )


def downgrade():
    op.drop_constraint("testimonials_class_id_fkey", "testimonials", type_="foreignkey")
    op.drop_column("testimonials", "class_id")