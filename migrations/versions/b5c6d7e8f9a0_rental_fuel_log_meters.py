"""rental diesel ledger KM / engine-hour readings

Revision ID: b5c6d7e8f9a0
Revises: f1a2b3c4d5e6
Create Date: 2026-11-26

A rented machine is not part of ``all_machines``, so it never gets a row in
``machine_meter_logs``.  The **Mazot Dağılımı → Kiralık Makineler** tab still
needs the counter reading at the moment of refuelling, therefore the reading is
stored on the diesel row itself (same date, no extra ledger).

Both columns are nullable on purpose:

* existing rows keep ``NULL`` — nothing is guessed during the upgrade;
* a rental may expose only one counter (e.g. an excavator has engine hours but
  no KM), so KM and engine hours are filled independently.

Negative readings are rejected with check constraints, mirroring
``machine_meter_logs.km`` / ``engine_hours``.  The tab shows the newest
non-null value per column up to the selected day.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: ``(column, check constraint name)`` in the order they are added.
METER_COLUMNS = (
    ("km", "ck_machine_rental_fuel_logs_km_non_negative"),
    ("engine_hours", "ck_machine_rental_fuel_logs_engine_hours_non_negative"),
)


def upgrade() -> None:
    for column, constraint in METER_COLUMNS:
        op.add_column(
            "machine_rental_fuel_logs",
            sa.Column(column, sa.Float(), nullable=True),
        )
        op.create_check_constraint(
            constraint,
            "machine_rental_fuel_logs",
            f"{column} IS NULL OR {column} >= 0",
        )


def downgrade() -> None:
    for column, constraint in reversed(METER_COLUMNS):
        op.drop_constraint(
            constraint,
            "machine_rental_fuel_logs",
            type_="check",
        )
        op.drop_column("machine_rental_fuel_logs", column)
