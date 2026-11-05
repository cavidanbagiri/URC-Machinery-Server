"""rename the legacy repair machine status to its Turkish label

Machine statuses are kept in Turkish: *Aktif*, *Bakımda*, *Hurda*, *Arızalı*.
Databases seeded before the rename still carry *Tamirde* for the status that
marks a machine as under repair. The application accepts both spellings (see
``repositories/car_status_lookup.py``), but aligning the data keeps the Settings
page and the machine list consistent. Only the untouched seed row is renamed, so
customised labels are preserved. ``NOT EXISTS`` guards the unique name index.

Revision ID: f0a1b2c3d4e5
Revises: a9b0c1d2e3f4
Create Date: 2026-11-05
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f0a1b2c3d4e5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE car_statuses AS s
        SET name = 'Arızalı'
        WHERE s.name = 'Tamirde'
          AND NOT EXISTS (
              SELECT 1 FROM car_statuses AS x
              WHERE x.name = 'Arızalı' AND x.id <> s.id
          )
        """
    )
    # Keep the seeded description in sync with the new label ("Arızalı").
    op.execute(
        """
        UPDATE car_statuses
        SET description = 'Makine arızalı / onarımda'
        WHERE id = 2
          AND name = 'Arızalı'
          AND description IN (
              'Makine tamirde / onarımda',
              'Araç tamirde / onarımda',
              'Maşın təmirdədir'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE car_statuses
        SET description = 'Makine tamirde / onarımda'
        WHERE id = 2
          AND name = 'Arızalı'
          AND description = 'Makine arızalı / onarımda'
        """
    )
    # Restore the seeded label only on the original repair row (id 2).
    op.execute(
        """
        UPDATE car_statuses AS s
        SET name = 'Tamirde'
        WHERE s.id = 2
          AND s.name = 'Arızalı'
          AND NOT EXISTS (
              SELECT 1 FROM car_statuses AS x
              WHERE x.name = 'Tamirde' AND x.id <> s.id
          )
        """
    )
