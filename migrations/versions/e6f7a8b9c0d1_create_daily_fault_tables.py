"""create daily fault tables

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-10-31

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_faults",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("territory_id", sa.Integer(), nullable=False),
        sa.Column("repair_type_id", sa.Integer(), nullable=False),
        sa.Column("km_hour", sa.String(length=50), nullable=False),
        sa.Column("fault_assignment", sa.Text(), nullable=True),
        sa.Column("changed_parts", sa.Text(), nullable=True),
        sa.Column(
            "fault_date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_daily_faults_machine_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["territory_id"],
            ["territories.id"],
            name="fk_daily_faults_territory_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["repair_type_id"],
            ["repair_types.id"],
            name="fk_daily_faults_repair_type_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_daily_faults_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "id",
        "machine_id",
        "territory_id",
        "repair_type_id",
        "fault_date",
        "created_by_id",
    ):
        op.create_index(
            op.f(f"ix_daily_faults_{column}"),
            "daily_faults",
            [column],
            unique=False,
        )

    op.create_table(
        "daily_fault_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fault_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=100),
            nullable=False,
            server_default="application/pdf",
        ),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_size > 0",
            name="ck_daily_fault_documents_size_positive",
        ),
        sa.CheckConstraint(
            "file_size <= 10485760",
            name="ck_daily_fault_documents_size_limit",
        ),
        sa.ForeignKeyConstraint(
            ["fault_id"],
            ["daily_faults.id"],
            name="fk_daily_fault_documents_fault_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name="fk_daily_fault_documents_uploaded_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "fault_id", "uploaded_by_id"):
        op.create_index(
            op.f(f"ix_daily_fault_documents_{column}"),
            "daily_fault_documents",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("uploaded_by_id", "fault_id", "id"):
        op.drop_index(
            op.f(f"ix_daily_fault_documents_{column}"),
            table_name="daily_fault_documents",
        )
    op.drop_table("daily_fault_documents")

    for column in (
        "created_by_id",
        "fault_date",
        "repair_type_id",
        "territory_id",
        "machine_id",
        "id",
    ):
        op.drop_index(
            op.f(f"ix_daily_faults_{column}"),
            table_name="daily_faults",
        )
    op.drop_table("daily_faults")
