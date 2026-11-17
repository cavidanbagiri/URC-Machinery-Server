"""create tire positions lookup

Adds the ``tire_positions`` list maintained from Settings (Ayarlar → Lastik
Konumu). The previous suggestions lived in ``frontend-web/src/utils/tire.js``;
they are seeded here so a fresh and an existing database start with the same
choices. Positions already typed into ``tire_changes`` are copied as well, so
the operator sees the fleet's custom names (crane outriggers, truck axles, ...)
in Settings instead of only the defaults.

``tire_changes.position`` remains free text (no FK): historical rows stay valid
and the form still accepts a value that is not in the list.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-11-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Same list as the former ``TIRE_POSITIONS`` constant in ``utils/tire.js``.
DEFAULT_TIRE_POSITIONS = (
    "Sol Ön",
    "Sağ Ön",
    "Sol Arka 1",
    "Sağ Arka 1",
    "Sol Arka 2",
    "Sağ Arka 2",
    "Sol Orta",
    "Sağ Orta",
    "Yedek Lastik",
)


def upgrade() -> None:
    op.create_table(
        "tire_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tire_positions_id"), "tire_positions", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_tire_positions_name"),
        "tire_positions",
        ["name"],
        unique=True,
    )

    tire_positions = sa.table(
        "tire_positions", sa.column("name", sa.String)
    )
    op.bulk_insert(
        tire_positions,
        [{"name": name} for name in DEFAULT_TIRE_POSITIONS],
    )

    # Keep whatever the fleet already typed; ON CONFLICT ignores the defaults.
    # DISTINCT ON + NOT EXISTS also skip case variants ("sol ön" for "Sol Ön"),
    # because the duplicate guard of the repository is case-insensitive.
    op.execute(
        """
        INSERT INTO tire_positions (name)
        SELECT DISTINCT ON (lower(BTRIM(tc.position))) BTRIM(tc.position)
        FROM tire_changes tc
        WHERE tc.position IS NOT NULL AND BTRIM(tc.position) <> ''
          AND NOT EXISTS (
              SELECT 1 FROM tire_positions tp
              WHERE lower(tp.name) = lower(BTRIM(tc.position))
          )
        ORDER BY lower(BTRIM(tc.position)), BTRIM(tc.position)
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tire_positions_name"), table_name="tire_positions")
    op.drop_index(op.f("ix_tire_positions_id"), table_name="tire_positions")
    op.drop_table("tire_positions")
