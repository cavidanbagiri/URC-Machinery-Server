"""create machine meter logs table

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-11-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_meter_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column(
            "log_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column("km", sa.Float(), nullable=False),
        sa.Column("engine_hours", sa.Float(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "km >= 0",
            name="ck_machine_meter_logs_km_non_negative",
        ),
        sa.CheckConstraint(
            "engine_hours >= 0",
            name="ck_machine_meter_logs_engine_hours_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_machine_meter_logs_machine_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_machine_meter_logs_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    for column in ("id", "log_date", "created_by_id"):
        op.create_index(
            op.f(f"ix_machine_meter_logs_{column}"),
            "machine_meter_logs",
            [column],
            unique=False,
        )

    op.create_index(
        "ix_machine_meter_logs_machine_date",
        "machine_meter_logs",
        ["machine_id", "log_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_machine_meter_logs_machine_date",
        table_name="machine_meter_logs",
    )
    for column in ("created_by_id", "log_date", "id"):
        op.drop_index(
            op.f(f"ix_machine_meter_logs_{column}"),
            table_name="machine_meter_logs",
        )
    op.drop_table("machine_meter_logs")
