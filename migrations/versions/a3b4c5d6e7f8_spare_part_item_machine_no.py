"""spare part item machine no

Revision ID: a3b4c5d6e7f8
Revises: f8a9b0c1d2e3
Create Date: 2026-11-12

One part row often covers several machines ("ID No"), so the buyer now types
the machine numbers by hand instead of picking exactly one machine:

* ``spare_part_request_items.machine_no`` keeps the typed numbers
  ("1042, 1043").
* ``machine_id`` becomes nullable: a row no longer has to point at a single
  ``all_machines`` row. Existing rows keep their link, and their
  ``identification_no`` is copied into ``machine_no`` so the edit form still
  shows the number the old picker had selected.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "spare_part_request_items",
        sa.Column("machine_no", sa.String(length=255), nullable=True),
    )

    # The machine the old picker had selected becomes the typed number.
    op.execute(
        """
        UPDATE spare_part_request_items AS i
        SET machine_no = btrim(m.identification_no)
        FROM all_machines AS m
        WHERE i.machine_id = m.id
          AND m.identification_no IS NOT NULL
          AND btrim(m.identification_no) <> ''
        """
    )

    op.alter_column(
        "spare_part_request_items",
        "machine_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # The old schema required exactly one machine per row; rows that only carry
    # typed numbers cannot be expressed there and are dropped.
    op.execute("DELETE FROM spare_part_request_items WHERE machine_id IS NULL")

    op.alter_column(
        "spare_part_request_items",
        "machine_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("spare_part_request_items", "machine_no")
