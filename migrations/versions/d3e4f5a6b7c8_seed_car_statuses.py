"""seed default machine statuses

Keeps a fresh database usable and matches the status choices used by the UI.
``ON CONFLICT DO NOTHING`` preserves any existing status rows.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-10-17
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO car_statuses (id, name, color, description) VALUES
            (1, 'Aktif', 'green', 'Makine aktif kullanımda'),
            (2, 'Tamirde', 'yellow', 'Makine tamirde / onarımda'),
            (3, 'Bakımda', 'blue', 'Makine planlı teknik bakımda'),
            (4, 'Hurda', 'red', 'Makine kullanım dışı (hurdaya ayrılmış)')
        ON CONFLICT DO NOTHING
        """
    )
    # Explicit ids must not leave the serial sequence behind; the Settings page
    # can create new car statuses.
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('car_statuses', 'id'),
            GREATEST((SELECT COALESCE(MAX(id), 1) FROM car_statuses), 1),
            true
        )
        """
    )


def downgrade() -> None:
    # Remove only rows that still match the seeded defaults exactly.
    op.execute(
        """
        DELETE FROM car_statuses
        WHERE (id = 1 AND name = 'Aktif')
           OR (id = 2 AND name = 'Tamirde')
           OR (id = 3 AND name = 'Bakımda')
           OR (id = 4 AND name = 'Hurda')
        """
    )
