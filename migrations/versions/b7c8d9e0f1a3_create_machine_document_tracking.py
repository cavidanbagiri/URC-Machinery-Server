"""create machine document tracking table

Revision ID: b7c8d9e0f1a3
Revises: e8a9b0c1d2e3
Create Date: 2026-11-17

The Evrak Takip Tablosu keeps one row per machine with hand-entered document
expiry dates. All dates are nullable so existing machines need no backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a3"
down_revision: Union[str, Sequence[str], None] = "e8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_document_tracking",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column(
            "compulsory_traffic_insurance_date", sa.Date(), nullable=True
        ),
        sa.Column("inspection_end_date", sa.Date(), nullable=True),
        sa.Column(
            "passenger_transport_license_date", sa.Date(), nullable=True
        ),
        sa.Column(
            "partial_technical_inspection_date", sa.Date(), nullable=True
        ),
        sa.Column(
            "full_technical_inspection_date", sa.Date(), nullable=True
        ),
        sa.Column(
            "hazardous_production_facility_date", sa.Date(), nullable=True
        ),
        sa.Column("leasing_date", sa.Date(), nullable=True),
        sa.Column("equipment_control_date", sa.Date(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_machine_document_tracking_machine_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_machine_document_tracking_updated_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_machine_document_tracking_id"),
        "machine_document_tracking",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_machine_document_tracking_machine_id"),
        "machine_document_tracking",
        ["machine_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_machine_document_tracking_updated_by_id"),
        "machine_document_tracking",
        ["updated_by_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_machine_document_tracking_updated_by_id"),
        table_name="machine_document_tracking",
    )
    op.drop_index(
        op.f("ix_machine_document_tracking_machine_id"),
        table_name="machine_document_tracking",
    )
    op.drop_index(
        op.f("ix_machine_document_tracking_id"),
        table_name="machine_document_tracking",
    )
    op.drop_table("machine_document_tracking")
