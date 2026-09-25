"""create_table_car_status_model

Revision ID: 1c1d1ce5f54c
Revises: e48964305c51
Create Date: 2026-09-24 15:56:21.014944

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c1d1ce5f54c'
down_revision: Union[str, Sequence[str], None] = 'e48964305c51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None





def upgrade() -> None:
    # 1) car_statuses cədvəlini yarat
    op.create_table(
        'car_statuses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('color', sa.String(length=20), nullable=False, server_default='gray'),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_car_statuses_id'), 'car_statuses', ['id'], unique=False)

    # 2) Default 4 statusu əlavə et (SEED)
    op.execute("""
        INSERT INTO car_statuses (id, name, color, description) VALUES
        (1, 'Active', 'green', 'Maşın aktiv istifadədədir'),
        (2, 'Tamirde', 'yellow', 'Maşın təmirdədir'),
        (3, 'Bakimda', 'blue', 'Planlı texniki baxışdadır'),
        (4, 'Hurda', 'red', 'İstifadədən çıxarılıb')
    """)

    # 3) all_machines-ə status_id əlavə et
    op.add_column(
        'all_machines',
        sa.Column(
            'status_id',
            sa.Integer(),
            nullable=False,
            server_default='1',
        ),
    )
    op.create_index(
        op.f('ix_all_machines_status_id'),
        'all_machines',
        ['status_id'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_all_machines_status_id',
        'all_machines',
        'car_statuses',
        ['status_id'],
        ['id'],
    )


def downgrade() -> None:
    # 1) all_machines-dən status_id sil
    op.drop_constraint('fk_all_machines_status_id', 'all_machines', type_='foreignkey')
    op.drop_index(op.f('ix_all_machines_status_id'), table_name='all_machines')
    op.drop_column('all_machines', 'status_id')

    # 2) car_statuses cədvəlini sil
    op.drop_index(op.f('ix_car_statuses_id'), table_name='car_statuses')
    op.drop_table('car_statuses')
