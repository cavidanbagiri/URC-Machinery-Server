"""Create Table Users

Revision ID: 0693c29c097d
Revises: 
Create Date: 2026-09-23 19:37:50.486583

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import func

# revision identifiers, used by Alembic.
revision: str = '0693c29c097d'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create statuses table
    op.create_table(
        'statuses',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('status', sa.String, nullable=False, unique=True),
    )

    # Create image table
    op.create_table(
        'images',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('url', sa.String, nullable=False),
    )

    # Create user table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, index=True),
        sa.Column('firstname', sa.String(100), nullable=False),
        sa.Column('lastname', sa.String(100), nullable=False),
        sa.Column('email', sa.String(200), nullable=False, unique=True, index=True),
        sa.Column('password', sa.String(255), nullable=False),
        sa.Column('image_id', sa.Integer, sa.ForeignKey('images.id'), nullable=True, index=True),
        sa.Column('status_id', sa.Integer, sa.ForeignKey('statuses.id'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=func.now()),
    )

    # Create tokens table
    op.create_table(
        'tokens',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, index=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('access_token', sa.String(500), nullable=False, unique=True),
        sa.Column('refresh_token', sa.String(500), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('tokens')
    op.drop_table('users')
    op.drop_table('images')
    op.drop_table('statuses')