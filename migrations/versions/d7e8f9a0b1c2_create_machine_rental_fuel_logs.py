"""create machine rental fuel logs table

Revision ID: d7e8f9a0b1c2
Revises: a5b6c7d8e9f0
Create Date: 2026-11-22

The diesel we hand to rented machines is tracked per rental agreement, because
the rented equipment is not part of ``all_machines`` and therefore has no
machine ID.  The table is append-only, exactly like ``machine_fuel_logs``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_rental_fuel_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rental_id", sa.Integer(), nullable=False),
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
            name="ck_machine_rental_fuel_logs_liters_positive",
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"],
            ["machine_rentals.id"],
            name="fk_machine_rental_fuel_logs_rental_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_machine_rental_fuel_logs_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    for column in ("id", "fuel_date", "created_by_id"):
        op.create_index(
            op.f(f"ix_machine_rental_fuel_logs_{column}"),
            "machine_rental_fuel_logs",
            [column],
            unique=False,
        )

    op.create_index(
        "ix_machine_rental_fuel_logs_rental_date",
        "machine_rental_fuel_logs",
        ["rental_id", "fuel_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_machine_rental_fuel_logs_rental_date",
        table_name="machine_rental_fuel_logs",
    )
    for column in ("created_by_id", "fuel_date", "id"):
        op.drop_index(
            op.f(f"ix_machine_rental_fuel_logs_{column}"),
            table_name="machine_rental_fuel_logs",
        )
    op.drop_table("machine_rental_fuel_logs")
