# models/tire_model.py
"""Tire change records (lastik değişimi) and the papers attached to them.

A tyre is replaced on a machine at a given position (Sol Ön, Sağ Arka 1, ...).
Each change keeps who changed it, why, on which date and at which counter
reading, so the same position can be followed over time: the API exposes the
previous records of a machine + position as the "eski kayıtlar" history.

``brand_model``, ``size`` and ``change_reason`` are operator-typed free text
because every fleet buys different brands and sizes. ``km_hour`` keeps whatever
the operator wrote ("12 450 km", "350 saat", ...), exactly like daily faults.

Each change may own several PDF documents (delivery note, invoice, work order).
The bytes live in PostgreSQL because the API host (Render) has an ephemeral
filesystem; this keeps the papers available after restarts and redeploys
without extra storage configuration.
"""

from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base

#: Hard limit for one uploaded PDF (mirrored by
#: ``ck_tire_change_documents_size_limit`` and enforced by the repository).
MAX_TIRE_DOCUMENT_BYTES = 10 * 1024 * 1024


class TireChangeModel(Base):
    __tablename__ = "tire_changes"

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "Lastik konumu" — free text so a crane and a truck can both use it.
    position = Column(String(50), nullable=False, index=True)

    brand_model = Column(String(150), nullable=True)
    size = Column(String(50), nullable=True)
    change_reason = Column(Text, nullable=True)

    change_date = Column(
        Date,
        nullable=False,
        default=date.today,
        server_default=func.current_date(),
        index=True,
    )
    km_hour = Column(String(50), nullable=True)

    created_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    machine = relationship("AllMachineModel")
    created_by = relationship("UserModel")
    documents = relationship(
        "TireChangeDocumentModel",
        back_populates="tire",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TireChangeDocumentModel.created_at, TireChangeDocumentModel.id",
    )

    def __str__(self) -> str:
        return f"Lastik değişimi #{self.id} · {self.position}"


class TireChangeDocumentModel(Base):
    """A PDF evidence file (delivery note, invoice, work order) of one change."""

    __tablename__ = "tire_change_documents"

    __table_args__ = (
        CheckConstraint(
            "file_size > 0",
            name="ck_tire_change_documents_size_positive",
        ),
        CheckConstraint(
            f"file_size <= {MAX_TIRE_DOCUMENT_BYTES}",
            name="ck_tire_change_documents_size_limit",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    tire_id = Column(
        Integer,
        ForeignKey("tire_changes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_name = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False, default="application/pdf")
    file_size = Column(Integer, nullable=False)
    file_data = Column(LargeBinary, nullable=False)

    uploaded_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    tire = relationship("TireChangeModel", back_populates="documents")
    uploaded_by = relationship("UserModel")

    def __str__(self) -> str:
        return self.file_name


__all__ = [
    "MAX_TIRE_DOCUMENT_BYTES",
    "TireChangeDocumentModel",
    "TireChangeModel",
]
