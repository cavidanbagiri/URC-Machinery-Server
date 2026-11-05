"""create forum tables

Revision ID: a2b3c4d5e6f7
Revises: f0a1b2c3d4e5
Create Date: 2026-11-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "forum_topics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "is_resolved",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_forum_topics_machine_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_forum_topics_created_by_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
            name="fk_forum_topics_resolved_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "id",
        "machine_id",
        "created_by_id",
        "is_resolved",
        "resolved_by_id",
    ):
        op.create_index(
            op.f(f"ix_forum_topics_{column}"),
            "forum_topics",
            [column],
            unique=False,
        )

    op.create_table(
        "forum_topic_photos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=100),
            server_default="image/jpeg",
            nullable=False,
        ),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_size > 0",
            name="ck_forum_topic_photos_size_positive",
        ),
        sa.CheckConstraint(
            "file_size <= 5242880",
            name="ck_forum_topic_photos_size_limit",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["forum_topics.id"],
            name="fk_forum_topic_photos_topic_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name="fk_forum_topic_photos_uploaded_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "topic_id", "uploaded_by_id"):
        op.create_index(
            op.f(f"ix_forum_topic_photos_{column}"),
            "forum_topic_photos",
            [column],
            unique=False,
        )

    op.create_table(
        "forum_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["forum_topics.id"],
            name="fk_forum_comments_topic_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_forum_comments_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "topic_id", "created_by_id"):
        op.create_index(
            op.f(f"ix_forum_comments_{column}"),
            "forum_comments",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("created_by_id", "topic_id", "id"):
        op.drop_index(
            op.f(f"ix_forum_comments_{column}"),
            table_name="forum_comments",
        )
    op.drop_table("forum_comments")

    for column in ("uploaded_by_id", "topic_id", "id"):
        op.drop_index(
            op.f(f"ix_forum_topic_photos_{column}"),
            table_name="forum_topic_photos",
        )
    op.drop_table("forum_topic_photos")

    for column in (
        "resolved_by_id",
        "is_resolved",
        "created_by_id",
        "machine_id",
        "id",
    ):
        op.drop_index(
            op.f(f"ix_forum_topics_{column}"),
            table_name="forum_topics",
        )
    op.drop_table("forum_topics")

