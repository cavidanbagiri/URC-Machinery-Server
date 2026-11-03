"""create warehouse tables

Revision ID: a9b0c1d2e3f4
Revises: f7a8b9c0d1e2
Create Date: 2026-10-31

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- stock cards ----------
    op.create_table(
        "warehouse_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("part_number", sa.String(length=100), nullable=True),
        sa.Column("description_tr", sa.String(length=500), nullable=True),
        sa.Column("description_ru", sa.String(length=500), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("territory_id", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(length=100), nullable=True),
        sa.Column(
            "min_quantity",
            sa.Numeric(precision=12, scale=3),
            server_default=sa.text("0"),
            nullable=False,
        ),
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
            name="ck_warehouse_items_quantity_not_negative",
        ),
        sa.CheckConstraint(
            "min_quantity >= 0",
            name="ck_warehouse_items_min_quantity_not_negative",
        ),
        sa.ForeignKeyConstraint(
            ["territory_id"],
            ["territories.id"],
            name="fk_warehouse_items_territory_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_warehouse_items_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "name", "part_number", "territory_id", "created_by_id"):
        op.create_index(
            f"ix_warehouse_items_{column}",
            "warehouse_items",
            [column],
        )

    # ---------- in/out ledger ----------
    op.create_table(
        "warehouse_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("movement_type", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column(
            "movement_date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("machine_id", sa.Integer(), nullable=True),
        sa.Column("territory_id", sa.Integer(), nullable=True),
        sa.Column("document_no", sa.String(length=100), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("source_request_item_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "movement_type IN ('giris', 'cikis')",
            name="ck_warehouse_movements_type",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_warehouse_movements_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["warehouse_items.id"],
            name="fk_warehouse_movements_item_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_warehouse_movements_machine_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["territory_id"],
            ["territories.id"],
            name="fk_warehouse_movements_territory_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_request_item_id"],
            ["spare_part_request_items.id"],
            name="fk_warehouse_movements_source_request_item_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_warehouse_movements_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_request_item_id",
            name="uq_warehouse_movements_source_request_item_id",
        ),
    )
    for column in (
        "id",
        "item_id",
        "movement_type",
        "movement_date",
        "machine_id",
        "source_request_item_id",
        "created_by_id",
    ):
        op.create_index(
            f"ix_warehouse_movements_{column}",
            "warehouse_movements",
            [column],
        )


def downgrade() -> None:
    op.drop_table("warehouse_movements")
    op.drop_table("warehouse_items")
