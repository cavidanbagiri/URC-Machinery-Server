"""create repair documents table

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-11-16

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repair_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repair_id", sa.Integer(), nullable=False),
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
            name="ck_repair_documents_size_positive",
        ),
        sa.CheckConstraint(
            "file_size <= 10485760",
            name="ck_repair_documents_size_limit",
        ),
        sa.ForeignKeyConstraint(
            ["repair_id"],
            ["repair_records.id"],
            name="fk_repair_documents_repair_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name="fk_repair_documents_uploaded_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "repair_id", "uploaded_by_id"):
        op.create_index(
            op.f(f"ix_repair_documents_{column}"),
            "repair_documents",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("uploaded_by_id", "repair_id", "id"):
        op.drop_index(
            op.f(f"ix_repair_documents_{column}"),
            table_name="repair_documents",
        )
    op.drop_table("repair_documents")
