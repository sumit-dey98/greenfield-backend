"""create admission_cycles and applications tables

Revision ID: 0011_admission_cycles
Revises: 0010_backfill_student_counts
Create Date: 2026-07-15

"""
from alembic import op
import sqlalchemy as sa

revision = "0011_admission_cycles"
down_revision = "0010_backfill_student_counts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admission_cycles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("academic_year", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("seats_available", sa.Integer(), nullable=True),
        sa.Column("results_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("reference_number", sa.String(), nullable=False),
        sa.Column("cycle_id", sa.String(), sa.ForeignKey("admission_cycles.id"), nullable=True),
        sa.Column("student_name", sa.String(), nullable=False),
        sa.Column("dob", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(), nullable=True),
        sa.Column("applying_class", sa.String(), nullable=True),
        sa.Column("blood_group", sa.String(), nullable=True),
        sa.Column("previous_school", sa.String(), nullable=True),
        sa.Column("contact_method", sa.String(), nullable=False),
        sa.Column("contact_email", sa.String(), nullable=True),
        sa.Column("contact_phone", sa.String(), nullable=True),
        sa.Column("guardian_name", sa.String(), nullable=True),
        sa.Column("guardian_relationship", sa.String(), nullable=True),
        sa.Column("guardian_phone", sa.String(), nullable=True),
        sa.Column("guardian_email", sa.String(), nullable=True),
        sa.Column("guardian_occupation", sa.String(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("medical_conditions", sa.Text(), nullable=True),
        sa.Column("extracurricular", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="submitted"),
        sa.Column("entrance_score", sa.Integer(), nullable=True),
        sa.Column("interview_outcome", sa.String(), nullable=True),
        sa.Column("interview_notes", sa.Text(), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("submitted_ip", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_applications_reference_number", "applications", ["reference_number"], unique=True
    )
    op.create_index("ix_applications_cycle_id", "applications", ["cycle_id"])
    op.create_index("ix_applications_contact_email", "applications", ["contact_email"])
    op.create_index("ix_applications_contact_phone", "applications", ["contact_phone"])
    op.create_index("ix_applications_status", "applications", ["status"])

    # Seed exactly one default admission cycle so the public apply endpoint has something to
    # attach applications to out of the box.
    op.execute(
        """
        INSERT INTO admission_cycles (id, name, academic_year, is_active, results_published)
        VALUES ('cyc_default', 'General Admissions', NULL, true, false)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_applications_status", table_name="applications")
    op.drop_index("ix_applications_contact_phone", table_name="applications")
    op.drop_index("ix_applications_contact_email", table_name="applications")
    op.drop_index("ix_applications_cycle_id", table_name="applications")
    op.drop_index("ix_applications_reference_number", table_name="applications")
    op.drop_table("applications")
    op.drop_table("admission_cycles")
