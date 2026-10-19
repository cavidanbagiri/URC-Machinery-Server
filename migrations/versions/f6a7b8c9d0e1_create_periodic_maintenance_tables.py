"""create periodic maintenance tables

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-19

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_maintenance_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("usage_unit", sa.String(length=20), nullable=False),
        sa.Column("interval_value", sa.Float(), nullable=False),
        sa.Column("last_counter", sa.Float(), nullable=True),
        sa.Column("last_maintenance_date", sa.Date(), nullable=True),
        sa.Column("current_counter", sa.Float(), nullable=True),
        sa.Column("current_counter_date", sa.Date(), nullable=True),
        sa.Column("warning_threshold", sa.Float(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "usage_unit IN ('km', 'hour')",
            name="ck_machine_maintenance_settings_usage_unit",
        ),
        sa.CheckConstraint(
            "interval_value > 0",
            name="ck_machine_maintenance_settings_interval_positive",
        ),
        sa.CheckConstraint(
            "last_counter IS NULL OR last_counter >= 0",
            name="ck_machine_maintenance_settings_last_counter_non_negative",
        ),
        sa.CheckConstraint(
            "current_counter IS NULL OR current_counter >= 0",
            name="ck_machine_maintenance_settings_current_counter_non_negative",
        ),
        sa.CheckConstraint(
            "warning_threshold IS NULL OR warning_threshold >= 0",
            name="ck_machine_maintenance_settings_warning_threshold_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_machine_maintenance_settings_machine_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_machine_maintenance_settings_id"),
        "machine_maintenance_settings",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_machine_maintenance_settings_machine_id"),
        "machine_maintenance_settings",
        ["machine_id"],
        unique=True,
    )

    op.create_table(
        "maintenance_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column(
            "record_type",
            sa.String(length=20),
            nullable=False,
            server_default="maintenance",
        ),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("counter_value", sa.Float(), nullable=True),
        sa.Column("usage_unit", sa.String(length=20), nullable=True),
        sa.Column("interval_value", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "record_type IN ('reading', 'maintenance')",
            name="ck_maintenance_records_record_type",
        ),
        sa.CheckConstraint(
            "counter_value IS NULL OR counter_value >= 0",
            name="ck_maintenance_records_counter_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_maintenance_records_machine_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_maintenance_records_created_by_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_maintenance_records_id"),
        "maintenance_records",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_records_machine_id"),
        "maintenance_records",
        ["machine_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_records_created_by_id"),
        "maintenance_records",
        ["created_by_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_maintenance_records_created_by_id"),
        table_name="maintenance_records",
    )
    op.drop_index(
        op.f("ix_maintenance_records_machine_id"),
        table_name="maintenance_records",
    )
    op.drop_index(op.f("ix_maintenance_records_id"), table_name="maintenance_records")
    op.drop_table("maintenance_records")

    op.drop_index(
        op.f("ix_machine_maintenance_settings_machine_id"),
        table_name="machine_maintenance_settings",
    )
    op.drop_index(
        op.f("ix_machine_maintenance_settings_id"),
        table_name="machine_maintenance_settings",
    )
    op.drop_table("machine_maintenance_settings")
