"""add garage service lookup to repair records

Adds the ``garage_services`` lookup maintained from Settings and points every
repair record at the garage that handles the machine. Two defaults are seeded
so the selection works on a fresh database. The column is nullable because
quick-open repairs (machine status modal) and legacy rows have no garage yet.

Revision ID: d4e5f6a7b8c9
Revises: c9d0e1f2a3b4
Create Date: 2026-10-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_GARAGE_SERVICES = ("Merkez Garaj", "Dış Servis")


def upgrade() -> None:
    op.create_table(
        "garage_services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_garage_services_id"), "garage_services", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_garage_services_name"),
        "garage_services",
        ["name"],
        unique=True,
    )

    garage_services = sa.table(
        "garage_services", sa.column("name", sa.String)
    )
    op.bulk_insert(
        garage_services,
        [{"name": name} for name in DEFAULT_GARAGE_SERVICES],
    )

    op.add_column(
        "repair_records",
        sa.Column("garage_service_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_repair_records_garage_service_id"),
        "repair_records",
        ["garage_service_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_repair_records_garage_service_id",
        "repair_records",
        "garage_services",
        ["garage_service_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_repair_records_garage_service_id",
        "repair_records",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_repair_records_garage_service_id"), table_name="repair_records"
    )
    op.drop_column("repair_records", "garage_service_id")

    op.drop_index(op.f("ix_garage_services_name"), table_name="garage_services")
    op.drop_index(op.f("ix_garage_services_id"), table_name="garage_services")
    op.drop_table("garage_services")
