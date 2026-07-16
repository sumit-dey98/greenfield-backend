"""create application_documents table

Revision ID: 0012_app_documents
Revises: 0011_admission_cycles
Create Date: 2026-07-15

"""
from alembic import op
import sqlalchemy as sa

revision = "0012_app_documents"
down_revision = "0011_admission_cycles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "application_id",
            sa.String(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("public_id", sa.String(), nullable=True),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("doc_type", sa.String(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_application_documents_application_id", "application_documents", ["application_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_application_documents_application_id", table_name="application_documents")
    op.drop_table("application_documents")
