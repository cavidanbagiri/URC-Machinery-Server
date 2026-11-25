"""machine rental equipment fields

Revision ID: f1a2b3c4d5e6
Revises: e8f9a0b1c2d3
Create Date: 2026-11-24

A rented machine is no longer one free-text line: the Kiralık Makineler table
now describes it with the fleet vocabulary — makine tipi (``type_transports``),
marka (``car_marks``), model (``car_models``) and ``plate_no`` — so rows can be
filtered per column and grouped by machine type in the statistics panel.

``equipment_name`` is kept: the diesel ledger label / search still reads it and
the repository rewrites it from the structured fields on every save.  Old rows
keep their typed text until they are edited, so nothing is lost or guessed at
during the upgrade.

Linked lookups are ``ON DELETE SET NULL``: deleting a type or brand from the
settings page must not delete rental agreements.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: ``(column, lookup table, lookup column)`` in the order they are added.
LOOKUP_COLUMNS = (
    ("machine_type_id", "type_transports"),
    ("car_mark_id", "car_marks"),
    ("car_model_id", "car_models"),
)


def upgrade() -> None:
    op.add_column(
        "machine_rentals",
        sa.Column("machine_type_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "machine_rentals",
        sa.Column("car_mark_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "machine_rentals",
        sa.Column("car_model_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "machine_rentals",
        sa.Column("plate_no", sa.String(length=50), nullable=True),
    )

    for column, lookup_table in LOOKUP_COLUMNS:
        op.create_index(
            op.f(f"ix_machine_rentals_{column}"),
            "machine_rentals",
            [column],
            unique=False,
        )
        op.create_foreign_key(
            f"fk_machine_rentals_{column}",
            "machine_rentals",
            lookup_table,
            [column],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index(
        op.f("ix_machine_rentals_plate_no"),
        "machine_rentals",
        ["plate_no"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_machine_rentals_plate_no"),
        table_name="machine_rentals",
    )

    for column, _lookup_table in reversed(LOOKUP_COLUMNS):
        op.drop_constraint(
            f"fk_machine_rentals_{column}",
            "machine_rentals",
            type_="foreignkey",
        )
        op.drop_index(
            op.f(f"ix_machine_rentals_{column}"),
            table_name="machine_rentals",
        )

    for column in ("car_model_id", "car_mark_id", "machine_type_id"):
        op.drop_column("machine_rentals", column)
