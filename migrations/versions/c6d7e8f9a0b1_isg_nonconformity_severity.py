"""add ISG nonconformity severity ("Önem Derecesi")

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-11-26

Every ISG nonconformity now carries an importance next to its open/closed
status: ``kritik``, ``onemli`` or ``az_onemli``.  The column is NOT NULL with a
server default, so the existing rows are filled with ``onemli`` during the
upgrade without a separate backfill statement; the default also keeps inserts
made outside the API valid.  ``ck_isg_nonconformities_severity`` mirrors the
tuple in ``models/isg_model.py``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, Sequence[str], None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Mirrors ISG_SEVERITY_DEFAULT in models/isg_model.py.
SEVERITY_DEFAULT = "onemli"

#: Mirrors ISG_SEVERITIES in models/isg_model.py.
SEVERITY_CHECK = "severity IN ('kritik', 'onemli', 'az_onemli')"


def upgrade() -> None:
    op.add_column(
        "isg_nonconformities",
        sa.Column(
            "severity",
            sa.String(length=12),
            server_default=SEVERITY_DEFAULT,
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_isg_nonconformities_severity",
        "isg_nonconformities",
        SEVERITY_CHECK,
    )
    op.create_index(
        op.f("ix_isg_nonconformities_severity"),
        "isg_nonconformities",
        ["severity"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_isg_nonconformities_severity"),
        table_name="isg_nonconformities",
    )
    op.drop_constraint(
        "ck_isg_nonconformities_severity",
        "isg_nonconformities",
        type_="check",
    )
    op.drop_column("isg_nonconformities", "severity")
