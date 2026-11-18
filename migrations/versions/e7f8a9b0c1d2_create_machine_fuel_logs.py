"""create machine fuel logs table

Revision ID: e7f8a9b0c1d2
Revises: c1d2e3f4a5b6
Create Date: 2026-11-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_fuel_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column(
            "fuel_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column("liters", sa.Float(), nullable=False),
        sa.Column("given_by", sa.String(length=150), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "liters > 0",
            name="ck_machine_fuel_logs_liters_positive",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_machine_fuel_logs_machine_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_machine_fuel_logs_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    for column in ("id", "fuel_date", "created_by_id"):
        op.create_index(
            op.f(f"ix_machine_fuel_logs_{column}"),
            "machine_fuel_logs",
            [column],
            unique=False,
        )

    op.create_index(
        "ix_machine_fuel_logs_machine_date",
        "machine_fuel_logs",
        ["machine_id", "fuel_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_machine_fuel_logs_machine_date",
        table_name="machine_fuel_logs",
    )
    for column in ("created_by_id", "fuel_date", "id"):
        op.drop_index(
            op.f(f"ix_machine_fuel_logs_{column}"),
            table_name="machine_fuel_logs",
        )
    op.drop_table("machine_fuel_logs")
