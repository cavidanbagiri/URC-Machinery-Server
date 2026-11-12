"""add daily fault changed part fields

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-11-12

The "Değişen Parça" block of a daily fault kept only the free-text note. Three
nullable columns now record the part itself (number, quantity, unit); the note
stays untouched, so existing rows keep working without a backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "daily_faults",
        sa.Column("changed_part_no", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "daily_faults",
        sa.Column(
            "changed_part_quantity",
            sa.Numeric(precision=12, scale=3),
            nullable=True,
        ),
    )
    op.add_column(
        "daily_faults",
        sa.Column("changed_part_unit", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_daily_faults_changed_part_quantity_positive",
        "daily_faults",
        "changed_part_quantity IS NULL OR changed_part_quantity > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_daily_faults_changed_part_quantity_positive",
        "daily_faults",
        type_="check",
    )
    op.drop_column("daily_faults", "changed_part_unit")
    op.drop_column("daily_faults", "changed_part_quantity")
    op.drop_column("daily_faults", "changed_part_no")
