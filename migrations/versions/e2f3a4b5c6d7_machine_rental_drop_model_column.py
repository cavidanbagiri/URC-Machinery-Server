"""machine rental drops the separate model column

Revision ID: e2f3a4b5c6d7
Revises: c8d9e0f1a2b3
Create Date: 2026-11-28

The Kiralık Makineler table now shows a single **Marka / Model** column, so the
separate model link is no longer tracked: ``machine_rentals.car_model_id``
(foreign key + index into ``car_models``) is dropped.  The brand
(``car_mark_id``) stays and is what the merged column displays.

Nothing is lost for rows saved through the API: their one-line label
(``equipment_name``) was composed from tip / marka / model / plaka, so the model
text they carried stays inside it — and that label is not rewritten until the
row is edited.  Rows edited after this migration simply get the label without a
model part.

``downgrade()`` restores the column, its index and its ``ON DELETE SET NULL``
foreign key so the previous revision can run again, but the dropped ids cannot
be recovered: the column comes back empty.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "machine_rentals"
COLUMN = "car_model_id"
FK_NAME = "fk_machine_rentals_car_model_id"


def upgrade() -> None:
    op.drop_constraint(FK_NAME, TABLE, type_="foreignkey")
    op.drop_index(op.f(f"ix_{TABLE}_{COLUMN}"), table_name=TABLE)
    op.drop_column(TABLE, COLUMN)


def downgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
    op.create_index(
        op.f(f"ix_{TABLE}_{COLUMN}"),
        TABLE,
        [COLUMN],
        unique=False,
    )
    op.create_foreign_key(
        FK_NAME,
        TABLE,
        "car_models",
        [COLUMN],
        ["id"],
        ondelete="SET NULL",
    )
