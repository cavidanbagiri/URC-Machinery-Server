"""create purchase request tables

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-10-31

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- "Talep Türü" lookup ----------
    op.create_table(
        "spare_part_request_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_spare_part_request_types_name"),
    )
    op.create_index(
        "ix_spare_part_request_types_id",
        "spare_part_request_types",
        ["id"],
    )
    op.create_index(
        "ix_spare_part_request_types_name",
        "spare_part_request_types",
        ["name"],
    )

    request_types = sa.table(
        "spare_part_request_types",
        sa.column("name", sa.String),
    )
    op.bulk_insert(
        request_types,
        [{"name": "Arıza"}, {"name": "Yedek Bakım"}],
    )

    # ---------- spare part requests (header) ----------
    op.create_table(
        "spare_part_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("stf_htf_no", sa.String(length=100), nullable=False),
        sa.Column("territory_id", sa.Integer(), nullable=False),
        sa.Column("request_type_id", sa.Integer(), nullable=False),
        sa.Column(
            "request_date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="bekleniyor",
        ),
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
            "status IN ('geldi', 'bekleniyor')",
            name="ck_spare_part_requests_status",
        ),
        sa.ForeignKeyConstraint(
            ["territory_id"],
            ["territories.id"],
            name="fk_spare_part_requests_territory_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_type_id"],
            ["spare_part_request_types.id"],
            name="fk_spare_part_requests_request_type_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_spare_part_requests_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "id",
        "stf_htf_no",
        "territory_id",
        "request_type_id",
        "request_date",
        "status",
        "created_by_id",
    ):
        op.create_index(
            f"ix_spare_part_requests_{column}",
            "spare_part_requests",
            [column],
        )

    # ---------- spare part request items ("ID No" rows) ----------
    op.create_table(
        "spare_part_request_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("garage_request_no", sa.String(length=100), nullable=True),
        sa.Column("part_number", sa.String(length=100), nullable=True),
        sa.Column("description_ru", sa.String(length=500), nullable=True),
        sa.Column("description_tr", sa.String(length=500), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("supply_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_spare_part_request_items_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["spare_part_requests.id"],
            name="fk_spare_part_request_items_request_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_spare_part_request_items_machine_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "request_id", "machine_id"):
        op.create_index(
            f"ix_spare_part_request_items_{column}",
            "spare_part_request_items",
            [column],
        )

    # ---------- service requests ----------
    op.create_table(
        "service_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("service_form_no", sa.String(length=100), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("service_description", sa.Text(), nullable=False),
        sa.Column(
            "request_date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
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
            ["machine_id"],
            ["all_machines.id"],
            name="fk_service_requests_machine_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_service_requests_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "id",
        "service_form_no",
        "machine_id",
        "request_date",
        "created_by_id",
    ):
        op.create_index(
            f"ix_service_requests_{column}",
            "service_requests",
            [column],
        )


def downgrade() -> None:
    op.drop_table("service_requests")
    op.drop_table("spare_part_request_items")
    op.drop_table("spare_part_requests")
    op.drop_table("spare_part_request_types")
