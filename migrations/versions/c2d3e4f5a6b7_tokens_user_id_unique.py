"""make tokens.user_id unique

One refresh-token row per user. Older duplicates (if any) are collapsed to the
newest row before the constraint is created.

Revision ID: c2d3e4f5a6b7
Revises: b1a2c3d4e5f6
Create Date: 2026-10-17
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c2d3e4f5a6b7"
down_revision = "b1a2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the highest id per user; older token rows are stale.
    op.execute(
        """
        DELETE FROM tokens AS old
        USING tokens AS newer
        WHERE old.user_id = newer.user_id
          AND old.id < newer.id
        """
    )
    op.create_unique_constraint("uq_tokens_user_id", "tokens", ["user_id"])


def downgrade() -> None:
    op.drop_constraint("uq_tokens_user_id", "tokens", type_="unique")
