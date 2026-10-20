"""create machine repair module tables

Adds the repair-type lookup, repair records and their audit timeline. A
PostgreSQL partial unique index guarantees at most one open repair per machine.
Default repair types are seeded so the Settings list is usable immediately.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_REPAIR_TYPES = (
    "Mekanik",
    "Elektrik / Elektronik",
    "Hidrolik",
    "Kaporta / Boya",
    "Lastik",
    "Diğer",
)


def upgrade() -> None:
    # The module opens repairs by switching the machine to this status. Keep
    # the migration safe on databases where the default statuses were edited.
    op.execute(
        """
        INSERT INTO car_statuses (name, color, description)
        VALUES ('Tamirde', 'yellow', 'Makine tamirde / onarımda')
        ON CONFLICT (name) DO NOTHING
        """
    )

    op.create_table(
        "repair_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_repair_types_id"), "repair_types", ["id"], unique=False)
    op.create_index(
        op.f("ix_repair_types_name"), "repair_types", ["name"], unique=True
    )

    op.create_table(
        "repair_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("repair_type_id", sa.Integer(), nullable=False),
        sa.Column("fault_location", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("estimated_exit_date", sa.Date(), nullable=True),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="tamirde",
        ),
        sa.Column("previous_machine_status_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('tamirde', 'tamamlandi', 'iptal')",
            name="ck_repair_records_status",
        ),
        sa.CheckConstraint(
            "estimated_exit_date IS NULL OR estimated_exit_date >= entry_date",
            name="ck_repair_records_estimate_after_entry",
        ),
        sa.CheckConstraint(
            "exit_date IS NULL OR exit_date >= entry_date",
            name="ck_repair_records_exit_after_entry",
        ),
        sa.CheckConstraint(
            "status <> 'tamamlandi' OR exit_date IS NOT NULL",
            name="ck_repair_records_completed_requires_exit_date",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_repair_records_created_by_id",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["all_machines.id"],
            name="fk_repair_records_machine_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["previous_machine_status_id"],
            ["car_statuses.id"],
            name="fk_repair_records_previous_machine_status_id",
        ),
        sa.ForeignKeyConstraint(
            ["repair_type_id"],
            ["repair_types.id"],
            name="fk_repair_records_repair_type_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for index_name, column in (
        ("ix_repair_records_id", "id"),
        ("ix_repair_records_machine_id", "machine_id"),
        ("ix_repair_records_repair_type_id", "repair_type_id"),
        ("ix_repair_records_entry_date", "entry_date"),
        ("ix_repair_records_status", "status"),
        ("ix_repair_records_previous_machine_status_id", "previous_machine_status_id"),
        ("ix_repair_records_created_by_id", "created_by_id"),
    ):
        op.create_index(op.f(index_name), "repair_records", [column], unique=False)
    op.create_index(
        "uq_repair_records_active_machine",
        "repair_records",
        ["machine_id"],
        unique=True,
        postgresql_where=sa.text("status = 'tamirde'"),
    )

    op.create_table(
        "repair_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repair_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "event_type IN ('created', 'updated', 'note_added', 'closed', "
            "'cancelled', 'reopened')",
            name="ck_repair_logs_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_repair_logs_created_by_id",
        ),
        sa.ForeignKeyConstraint(
            ["repair_id"],
            ["repair_records.id"],
            name="fk_repair_logs_repair_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_repair_logs_id"), "repair_logs", ["id"], unique=False)
    op.create_index(
        op.f("ix_repair_logs_repair_id"), "repair_logs", ["repair_id"], unique=False
    )
    op.create_index(
        op.f("ix_repair_logs_created_by_id"),
        "repair_logs",
        ["created_by_id"],
        unique=False,
    )

    repair_types = sa.table("repair_types", sa.column("name", sa.String))
    op.bulk_insert(
        repair_types,
        [{"name": name} for name in DEFAULT_REPAIR_TYPES],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_repair_logs_created_by_id"), table_name="repair_logs"
    )
    op.drop_index(op.f("ix_repair_logs_repair_id"), table_name="repair_logs")
    op.drop_index(op.f("ix_repair_logs_id"), table_name="repair_logs")
    op.drop_table("repair_logs")

    op.drop_index("uq_repair_records_active_machine", table_name="repair_records")
    for index_name in (
        "ix_repair_records_created_by_id",
        "ix_repair_records_previous_machine_status_id",
        "ix_repair_records_status",
        "ix_repair_records_entry_date",
        "ix_repair_records_repair_type_id",
        "ix_repair_records_machine_id",
        "ix_repair_records_id",
    ):
        op.drop_index(op.f(index_name), table_name="repair_records")
    op.drop_table("repair_records")

    op.drop_index(op.f("ix_repair_types_name"), table_name="repair_types")
    op.drop_index(op.f("ix_repair_types_id"), table_name="repair_types")
    op.drop_table("repair_types")
