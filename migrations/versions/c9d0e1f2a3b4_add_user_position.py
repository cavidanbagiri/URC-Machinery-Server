"""add position column to users

The dashboard header shows the signed-in user's job title next to the avatar.
The column is nullable so existing accounts keep working until an administrator
fills it in.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("position", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "position")
