"""create simple stock tables

Revision ID: e8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-11-17

The simple stock module is independent from the older warehouse (ambar)
tables. ``stock_items`` keeps the current quantity on the card and
``stock_issues`` records every "Sahaya Çıkar" action that decrements it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- stock cards ----------
    op.create_table(
        "stock_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column(
            "quantity",
            sa.Numeric(precision=12, scale=3),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "quantity >= 0",
            name="ck_stock_items_quantity_not_negative",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_stock_items_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "name", "created_by_id"):
        op.create_index(
            f"ix_stock_items_{column}",
            "stock_items",
            [column],
        )

    # ---------- field issues ----------
    op.create_table(
        "stock_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_item_id", sa.Integer(), nullable=False),
        sa.Column(
            "quantity",
            sa.Numeric(precision=12, scale=3),
            nullable=False,
        ),
        sa.Column(
            "issue_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column("machine_id", sa.Integer(), nullable=True),
        sa.Column("given_to", sa.String(length=150), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_stock_issues_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["stock_item_id"],
            ["stock_items.id"],
            name="fk_stock_issues_stock_item_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_stock_issues_machine_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_stock_issues_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "id",
        "stock_item_id",
        "issue_date",
        "machine_id",
        "created_by_id",
    ):
        op.create_index(
            f"ix_stock_issues_{column}",
            "stock_issues",
            [column],
        )
    op.create_index(
        "ix_stock_issues_date_item",
        "stock_issues",
        ["issue_date", "stock_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_stock_issues_date_item", table_name="stock_issues")
    for column in (
        "created_by_id",
        "machine_id",
        "issue_date",
        "stock_item_id",
        "id",
    ):
        op.drop_index(f"ix_stock_issues_{column}", table_name="stock_issues")
    op.drop_table("stock_issues")
    op.drop_table("stock_items")
