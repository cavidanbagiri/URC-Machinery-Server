"""create spare part request documents

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-11-08

The signed order / invoice PDF of a spare-part request. The bytes live in
PostgreSQL (the API host has an ephemeral filesystem) and the 10 MB limit is
mirrored by ``ck_spare_part_request_documents_size_limit``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "spare_part_request_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
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
            name="ck_spare_part_request_documents_size_positive",
        ),
        sa.CheckConstraint(
            "file_size <= 10485760",
            name="ck_spare_part_request_documents_size_limit",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["spare_part_requests.id"],
            name="fk_spare_part_request_documents_request_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name="fk_spare_part_request_documents_uploaded_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "request_id", "uploaded_by_id"):
        op.create_index(
            op.f(f"ix_spare_part_request_documents_{column}"),
            "spare_part_request_documents",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("uploaded_by_id", "request_id", "id"):
        op.drop_index(
            op.f(f"ix_spare_part_request_documents_{column}"),
            table_name="spare_part_request_documents",
        )
    op.drop_table("spare_part_request_documents")
