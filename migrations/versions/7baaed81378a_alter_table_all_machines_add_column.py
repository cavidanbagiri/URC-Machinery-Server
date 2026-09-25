"""alter_table_all_machines_add_column

Revision ID: 7baaed81378a
Revises: 1c1d1ce5f54c
Create Date: 2026-09-25 14:34:40.772536

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7baaed81378a'
down_revision: Union[str, Sequence[str], None] = '1c1d1ce5f54c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'all_machines',
        sa.Column('plate_no', sa.String(length=50), nullable=True),
    )
    op.create_index(
        op.f('ix_all_machines_plate_no'),
        'all_machines',
        ['plate_no'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_all_machines_plate_no'), table_name='all_machines')
    op.drop_column('all_machines', 'plate_no')