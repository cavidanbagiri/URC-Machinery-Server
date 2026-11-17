"""add tire serial number

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-11-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable on purpose: changes created before the field existed stay NULL.
    op.add_column(
        "tire_changes",
        sa.Column("serial_no", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tire_changes", "serial_no")
