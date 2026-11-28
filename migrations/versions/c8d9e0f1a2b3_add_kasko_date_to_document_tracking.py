"""add kasko date to machine document tracking

Revision ID: c8d9e0f1a2b3
Revises: c6d7e8f9a0b1
Create Date: 2026-11-26

The Evrak Takip Tablosu gained a **Kasko** column next to the compulsory
traffic insurance. It is a plain nullable ``date``: rows created before the
column simply show an empty cell and the value is hand-entered like every
other document date, so no backfill is needed. Frontend column order and the
``DOCUMENT_DATE_FIELDS`` tuple in ``models/document_tracking_model.py`` list
``kasko_date`` right after ``compulsory_traffic_insurance_date``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "machine_document_tracking",
        sa.Column("kasko_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("machine_document_tracking", "kasko_date")
