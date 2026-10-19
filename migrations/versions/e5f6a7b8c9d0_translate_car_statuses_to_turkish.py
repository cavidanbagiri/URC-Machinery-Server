"""translate default machine statuses to Turkish

Renames the legacy ``Active`` / ``Bakimda`` status names and translates the
default descriptions. Only rows that still contain the known seed values are
touched, so user-customised status names and descriptions are preserved.

Revision ID: e5f6a7b8c9d0
Revises: d3e4f5a6b7c8
Create Date: 2026-10-19
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guard against a unique-name conflict when a translated row already exists
    # under a different id.
    op.execute(
        """
        UPDATE car_statuses AS s
        SET name = 'Aktif'
        WHERE s.id = 1
          AND s.name = 'Active'
          AND NOT EXISTS (
              SELECT 1 FROM car_statuses AS x
              WHERE x.name = 'Aktif' AND x.id <> s.id
          )
        """
    )
    op.execute(
        """
        UPDATE car_statuses AS s
        SET name = 'Bakımda'
        WHERE s.id = 3
          AND s.name = 'Bakimda'
          AND NOT EXISTS (
              SELECT 1 FROM car_statuses AS x
              WHERE x.name = 'Bakımda' AND x.id <> s.id
          )
        """
    )

    # Translate only the descriptions that came from the original seed files.
    op.execute(
        """
        UPDATE car_statuses
        SET description = 'Makine aktif kullanımda'
        WHERE id = 1
          AND description IN ('Araç aktif kullanımda', 'Maşın aktiv istifadədədir')
        """
    )
    op.execute(
        """
        UPDATE car_statuses
        SET description = 'Makine tamirde / onarımda'
        WHERE id = 2
          AND description IN ('Araç tamirde / onarımda', 'Maşın təmirdədir')
        """
    )
    op.execute(
        """
        UPDATE car_statuses
        SET description = 'Makine planlı teknik bakımda'
        WHERE id = 3
          AND description IN ('Araç planlı teknik bakımda', 'Planlı texniki baxışdadır')
        """
    )
    op.execute(
        """
        UPDATE car_statuses
        SET description = 'Makine kullanım dışı (hurdaya ayrılmış)'
        WHERE id = 4
          AND description IN (
              'Araç kullanım dışı (hurdaya ayrılmış)',
              'İstifadədən çıxarılıb'
          )
        """
    )


def downgrade() -> None:
    # Restore the values seeded by d3e4f5a6b7c8 when they are still unchanged.
    op.execute(
        """
        UPDATE car_statuses
        SET description = 'Araç aktif kullanımda'
        WHERE id = 1 AND description = 'Makine aktif kullanımda'
        """
    )
    op.execute(
        """
        UPDATE car_statuses
        SET description = 'Araç tamirde / onarımda'
        WHERE id = 2 AND description = 'Makine tamirde / onarımda'
        """
    )
    op.execute(
        """
        UPDATE car_statuses
        SET description = 'Araç planlı teknik bakımda'
        WHERE id = 3 AND description = 'Makine planlı teknik bakımda'
        """
    )
    op.execute(
        """
        UPDATE car_statuses
        SET description = 'Araç kullanım dışı (hurdaya ayrılmış)'
        WHERE id = 4 AND description = 'Makine kullanım dışı (hurdaya ayrılmış)'
        """
    )
    op.execute(
        """
        UPDATE car_statuses
        SET name = 'Active'
        WHERE id = 1 AND name = 'Aktif'
        """
    )
    op.execute(
        """
        UPDATE car_statuses
        SET name = 'Bakimda'
        WHERE id = 3 AND name = 'Bakımda'
        """
    )
