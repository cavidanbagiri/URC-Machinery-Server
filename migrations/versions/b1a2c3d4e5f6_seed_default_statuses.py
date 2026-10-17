"""seed default user statuses

Public registration always assigns status id 4 (read-only). A fresh database
needs the four status rows to exist before the users.status_id FK can be used.

Revision ID: b1a2c3d4e5f6
Revises: 7baaed81378a
Create Date: 2026-10-17
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b1a2c3d4e5f6"
down_revision = "7baaed81378a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ON CONFLICT keeps this migration safe for existing/production databases
    # where rows with these ids may already exist under different labels.
    op.execute(
        """
        INSERT INTO statuses (id, status) VALUES
            (1, 'Admin'),
            (2, 'Manager'),
            (3, 'Editor'),
            (4, 'Viewer')
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    # Only remove rows that still match the seeded labels exactly.
    op.execute(
        """
        DELETE FROM statuses
        WHERE (id = 1 AND status = 'Admin')
           OR (id = 2 AND status = 'Manager')
           OR (id = 3 AND status = 'Editor')
           OR (id = 4 AND status = 'Viewer')
        """
    )
