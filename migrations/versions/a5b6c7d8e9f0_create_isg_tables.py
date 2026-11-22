"""create ISG nonconformity tables

Revision ID: a5b6c7d8e9f0
Revises: f9a0b1c2d3e4
Create Date: 2026-11-22

The ISG page keeps one row per nonconformity (date, description, status, site,
responsible) and the PDF/photo evidence attached to it.  The SRU/DCU stat cards
are derived from ``territories.name``, so no site code is stored here.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, Sequence[str], None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Mirrors MAX_EVIDENCE_BYTES in models/isg_model.py.
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


def upgrade() -> None:
    op.create_table(
        "isg_nonconformities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=10),
            server_default="acik",
            nullable=False,
        ),
        sa.Column("territory_id", sa.Integer(), nullable=False),
        sa.Column("responsible_name", sa.String(length=100), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_id", sa.Integer(), nullable=True),
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
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('acik', 'kapali')",
            name="ck_isg_nonconformities_status",
        ),
        sa.ForeignKeyConstraint(
            ["territory_id"],
            ["territories.id"],
            name="fk_isg_nonconformities_territory_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["closed_by_id"],
            ["users.id"],
            name="fk_isg_nonconformities_closed_by_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_isg_nonconformities_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    for column in (
        "id",
        "record_date",
        "status",
        "territory_id",
        "responsible_name",
        "closed_by_id",
        "created_by_id",
    ):
        op.create_index(
            op.f(f"ix_isg_nonconformities_{column}"),
            "isg_nonconformities",
            [column],
            unique=False,
        )

    op.create_table(
        "isg_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nonconformity_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
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
            name="ck_isg_attachments_size_positive",
        ),
        sa.CheckConstraint(
            f"file_size <= {MAX_EVIDENCE_BYTES}",
            name="ck_isg_attachments_size_limit",
        ),
        sa.ForeignKeyConstraint(
            ["nonconformity_id"],
            ["isg_nonconformities.id"],
            name="fk_isg_attachments_nonconformity_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name="fk_isg_attachments_uploaded_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    for column in ("id", "nonconformity_id", "uploaded_by_id"):
        op.create_index(
            op.f(f"ix_isg_attachments_{column}"),
            "isg_attachments",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("uploaded_by_id", "nonconformity_id", "id"):
        op.drop_index(
            op.f(f"ix_isg_attachments_{column}"),
            table_name="isg_attachments",
        )
    op.drop_table("isg_attachments")

    for column in (
        "created_by_id",
        "closed_by_id",
        "responsible_name",
        "territory_id",
        "status",
        "record_date",
        "id",
    ):
        op.drop_index(
            op.f(f"ix_isg_nonconformities_{column}"),
            table_name="isg_nonconformities",
        )
    op.drop_table("isg_nonconformities")
