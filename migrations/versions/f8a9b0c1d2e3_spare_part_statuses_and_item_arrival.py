"""spare part request statuses and per item arrival

Revision ID: f8a9b0c1d2e3
Revises: d5e6f7a8b9c0
Create Date: 2026-11-12

Two changes on the spare-part side of the purchase-request module:

* ``spare_part_requests.status`` no longer means "geldi / bekleniyor". It is
  the state the user picks for the request — what is being waited for:
  ``onay_bekliyor`` (approval), ``odeme_bekliyor`` (payment) or
  ``firma_bekleniyor`` (delivery of the firm).
* The arrival of the parts moved to the row: ``spare_part_request_items`` gets
  ``is_arrived`` and ``arrived_at`` so a single order with six parts can have
  three arrived and three still on the way.

Legacy rows keep their meaning: a request that was ``geldi`` marks every row as
arrived (the goods are there, so what remains is the payment) and a request
that was ``bekleniyor`` becomes ``firma_bekleniyor`` (still waiting for the
firm to deliver).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUS_CHECK = "status IN ('onay_bekliyor', 'odeme_bekliyor', 'firma_bekleniyor')"


def upgrade() -> None:
    op.drop_constraint(
        "ck_spare_part_requests_status",
        "spare_part_requests",
        type_="check",
    )

    op.add_column(
        "spare_part_request_items",
        sa.Column(
            "is_arrived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "spare_part_request_items",
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_spare_part_request_items_is_arrived",
        "spare_part_request_items",
        ["is_arrived"],
    )

    # ---------- legacy data ----------
    # "geldi" meant every part of the request is on site.
    op.execute(
        """
        UPDATE spare_part_request_items
        SET is_arrived = TRUE, arrived_at = now()
        WHERE request_id IN (
            SELECT id FROM spare_part_requests WHERE status = 'geldi'
        )
        """
    )
    op.execute(
        """
        UPDATE spare_part_requests
        SET status = CASE
            WHEN status = 'geldi' THEN 'odeme_bekliyor'
            ELSE 'firma_bekleniyor'
        END
        """
    )

    op.alter_column(
        "spare_part_requests",
        "status",
        server_default="onay_bekliyor",
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_spare_part_requests_status",
        "spare_part_requests",
        STATUS_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_spare_part_requests_status",
        "spare_part_requests",
        type_="check",
    )

    # A request whose rows all arrived was "geldi"; everything else was
    # "bekleniyor" before this revision.
    op.execute(
        """
        UPDATE spare_part_requests r
        SET status = CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM spare_part_request_items i
                WHERE i.request_id = r.id AND i.is_arrived = FALSE
            ) THEN 'geldi'
            ELSE 'bekleniyor'
        END
        """
    )
    op.alter_column(
        "spare_part_requests",
        "status",
        server_default="bekleniyor",
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_spare_part_requests_status",
        "spare_part_requests",
        "status IN ('geldi', 'bekleniyor')",
    )

    op.drop_index(
        "ix_spare_part_request_items_is_arrived",
        table_name="spare_part_request_items",
    )
    op.drop_column("spare_part_request_items", "arrived_at")
    op.drop_column("spare_part_request_items", "is_arrived")
