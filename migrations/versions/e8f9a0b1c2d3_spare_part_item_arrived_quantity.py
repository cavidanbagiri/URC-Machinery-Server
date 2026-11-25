"""spare part item arrived quantity

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-11-24

The delivery of a spare-part row is no longer a yes/no flag: ``quantity`` is
what was ordered and the new ``arrived_quantity`` is how many pieces of it are
on site, so "3 sipariş, 2 geldi, 1 kaldı" can be shown and the row counts as
*Kısmi Geldi*. ``is_arrived`` stays and is derived from the two numbers (TRUE
only when the whole ordered quantity arrived), because the warehouse "Gelen
Talepler" list filters on it.

Rows that were already ticked as arrived get their full quantity backfilled, so
no delivered row turns into "0 geldi" after the upgrade.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ARRIVED_QUANTITY_CHECK = "arrived_quantity >= 0"


def upgrade() -> None:
    op.add_column(
        "spare_part_request_items",
        sa.Column(
            "arrived_quantity",
            sa.Numeric(12, 3),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # ---------- legacy data ----------
    # Before this revision "arrived" meant the whole row is on site.
    op.execute(
        """
        UPDATE spare_part_request_items
        SET arrived_quantity = quantity
        WHERE is_arrived = TRUE
        """
    )

    op.create_check_constraint(
        "ck_spare_part_request_items_arrived_quantity_non_negative",
        "spare_part_request_items",
        ARRIVED_QUANTITY_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_spare_part_request_items_arrived_quantity_non_negative",
        "spare_part_request_items",
        type_="check",
    )
    op.drop_column("spare_part_request_items", "arrived_quantity")
