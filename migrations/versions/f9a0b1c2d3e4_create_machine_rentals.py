"""create machine rentals table

Revision ID: f9a0b1c2d3e4
Revises: b7c8d9e0f1a3
Create Date: 2026-11-22

The Kiralık Makine page keeps one row per rental agreement: equipment,
company, site and the two dates.  The status shown in the table is derived
from the dates, so no status column is stored.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_rentals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("equipment_name", sa.String(length=200), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("site_name", sa.String(length=200), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
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
            "end_date >= start_date",
            name="ck_machine_rentals_date_order",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_machine_rentals_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    for column in ("id", "start_date", "end_date", "created_by_id"):
        op.create_index(
            op.f(f"ix_machine_rentals_{column}"),
            "machine_rentals",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("created_by_id", "end_date", "start_date", "id"):
        op.drop_index(
            op.f(f"ix_machine_rentals_{column}"),
            table_name="machine_rentals",
        )
    op.drop_table("machine_rentals")
