"""create tire change tables

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-11-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tire_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.String(length=50), nullable=False),
        sa.Column("brand_model", sa.String(length=150), nullable=True),
        sa.Column("size", sa.String(length=50), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column(
            "change_date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("km_hour", sa.String(length=50), nullable=True),
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
            name="fk_tire_changes_machine_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_tire_changes_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "id",
        "machine_id",
        "position",
        "change_date",
        "created_by_id",
    ):
        op.create_index(
            op.f(f"ix_tire_changes_{column}"),
            "tire_changes",
            [column],
            unique=False,
        )

    op.create_table(
        "tire_change_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tire_id", sa.Integer(), nullable=False),
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
            name="ck_tire_change_documents_size_positive",
        ),
        sa.CheckConstraint(
            "file_size <= 10485760",
            name="ck_tire_change_documents_size_limit",
        ),
        sa.ForeignKeyConstraint(
            ["tire_id"],
            ["tire_changes.id"],
            name="fk_tire_change_documents_tire_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name="fk_tire_change_documents_uploaded_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "tire_id", "uploaded_by_id"):
        op.create_index(
            op.f(f"ix_tire_change_documents_{column}"),
            "tire_change_documents",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("uploaded_by_id", "tire_id", "id"):
        op.drop_index(
            op.f(f"ix_tire_change_documents_{column}"),
            table_name="tire_change_documents",
        )
    op.drop_table("tire_change_documents")

    for column in (
        "created_by_id",
        "change_date",
        "position",
        "machine_id",
        "id",
    ):
        op.drop_index(
            op.f(f"ix_tire_changes_{column}"),
            table_name="tire_changes",
        )
    op.drop_table("tire_changes")
