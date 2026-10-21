"""create machine photo table

Stores the S3 object key of every machine photo (never the URL, which is built
at response time). A PostgreSQL partial unique index keeps at most one primary
photo per machine.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_photos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_machine_photos_machine_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name="fk_machine_photos_uploaded_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_machine_photos_object_key"),
    )

    for index_name, column in (
        ("ix_machine_photos_id", "id"),
        ("ix_machine_photos_machine_id", "machine_id"),
        ("ix_machine_photos_uploaded_by_id", "uploaded_by_id"),
    ):
        op.create_index(op.f(index_name), "machine_photos", [column], unique=False)

    op.create_index(
        "uq_machine_photos_primary",
        "machine_photos",
        ["machine_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )


def downgrade() -> None:
    op.drop_index("uq_machine_photos_primary", table_name="machine_photos")
    for index_name in (
        "ix_machine_photos_uploaded_by_id",
        "ix_machine_photos_machine_id",
        "ix_machine_photos_id",
    ):
        op.drop_index(op.f(index_name), table_name="machine_photos")
    op.drop_table("machine_photos")
