"""create_table_machines_model

Revision ID: e48964305c51
Revises: 0693c29c097d
Create Date: 2026-09-24 10:09:58.912124

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e48964305c51'
down_revision: Union[str, Sequence[str], None] = '0693c29c097d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # =========================================================
    # 1. Create Lookup Tables (No Foreign Keys)
    # =========================================================

    op.create_table(
        'territories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_territories_id'), 'territories', ['id'], unique=False)

    op.create_table(
        'type_transports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_type_transports_id'), 'type_transports', ['id'], unique=False)

    op.create_table(
        'sub_type_transports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_sub_type_transports_id'), 'sub_type_transports', ['id'], unique=False)

    op.create_table(
        'car_marks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_car_marks_id'), 'car_marks', ['id'], unique=False)

    op.create_table(
        'car_models',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_car_models_id'), 'car_models', ['id'], unique=False)

    op.create_table(
        'companies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_companies_id'), 'companies', ['id'], unique=False)

    # =========================================================
    # 2. Create Main Machine Table
    # =========================================================

    op.create_table(
        'all_machines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('identification_no', sa.String(length=100), nullable=True),
        sa.Column('vin_no', sa.String(length=100), nullable=True),
        sa.Column('technical_character', sa.String(length=500), nullable=True),
        sa.Column('production_year', sa.DateTime(timezone=True), nullable=True),
        sa.Column('weight', sa.Float(), nullable=True),
        sa.Column('dimension', sa.String(length=100), nullable=True),
        sa.Column('engine_power', sa.String(length=100), nullable=True),
        sa.Column('engine_mark_model', sa.String(length=255), nullable=True),
        sa.Column('engine_identity', sa.String(length=255), nullable=True),

        # Foreign Keys
        sa.Column('territory_id', sa.Integer(), nullable=True),
        sa.Column('type_id', sa.Integer(), nullable=True),
        sa.Column('subtype_id', sa.Integer(), nullable=True),
        sa.Column('car_mark_id', sa.Integer(), nullable=True),
        sa.Column('car_model_id', sa.Integer(), nullable=True),
        sa.Column('company_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        # Constraints
        sa.ForeignKeyConstraint(['territory_id'], ['territories.id'], ),
        sa.ForeignKeyConstraint(['type_id'], ['type_transports.id'], ),
        sa.ForeignKeyConstraint(['subtype_id'], ['sub_type_transports.id'], ),
        sa.ForeignKeyConstraint(['car_mark_id'], ['car_marks.id'], ),
        sa.ForeignKeyConstraint(['car_model_id'], ['car_models.id'], ),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('vin_no')
    )

    # Indexes for All Machines
    op.create_index(op.f('ix_all_machines_id'), 'all_machines', ['id'], unique=False)
    op.create_index(op.f('ix_all_machines_identification_no'), 'all_machines', ['identification_no'], unique=False)
    op.create_index(op.f('ix_all_machines_vin_no'), 'all_machines', ['vin_no'], unique=False)

    # Indexes for Foreign Keys
    op.create_index(op.f('ix_all_machines_territory_id'), 'all_machines', ['territory_id'], unique=False)
    op.create_index(op.f('ix_all_machines_type_id'), 'all_machines', ['type_id'], unique=False)
    op.create_index(op.f('ix_all_machines_subtype_id'), 'all_machines', ['subtype_id'], unique=False)
    op.create_index(op.f('ix_all_machines_car_mark_id'), 'all_machines', ['car_mark_id'], unique=False)
    op.create_index(op.f('ix_all_machines_car_model_id'), 'all_machines', ['car_model_id'], unique=False)
    op.create_index(op.f('ix_all_machines_company_id'), 'all_machines', ['company_id'], unique=False)
    op.create_index(op.f('ix_all_machines_created_by_id'), 'all_machines', ['created_by_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""

    # Drop Main Table First (Because of Foreign Keys)
    op.drop_index(op.f('ix_all_machines_created_by_id'), table_name='all_machines')
    op.drop_index(op.f('ix_all_machines_company_id'), table_name='all_machines')
    op.drop_index(op.f('ix_all_machines_car_model_id'), table_name='all_machines')
    op.drop_index(op.f('ix_all_machines_car_mark_id'), table_name='all_machines')
    op.drop_index(op.f('ix_all_machines_subtype_id'), table_name='all_machines')
    op.drop_index(op.f('ix_all_machines_type_id'), table_name='all_machines')
    op.drop_index(op.f('ix_all_machines_territory_id'), table_name='all_machines')
    op.drop_index(op.f('ix_all_machines_vin_no'), table_name='all_machines')
    op.drop_index(op.f('ix_all_machines_identification_no'), table_name='all_machines')
    op.drop_index(op.f('ix_all_machines_id'), table_name='all_machines')
    op.drop_table('all_machines')

    # Drop Lookup Tables
    op.drop_index(op.f('ix_companies_id'), table_name='companies')
    op.drop_table('companies')

    op.drop_index(op.f('ix_car_models_id'), table_name='car_models')
    op.drop_table('car_models')

    op.drop_index(op.f('ix_car_marks_id'), table_name='car_marks')
    op.drop_table('car_marks')

    op.drop_index(op.f('ix_sub_type_transports_id'), table_name='sub_type_transports')
    op.drop_table('sub_type_transports')

    op.drop_index(op.f('ix_type_transports_id'), table_name='type_transports')
    op.drop_table('type_transports')

    op.drop_index(op.f('ix_territories_id'), table_name='territories')
    op.drop_table('territories')