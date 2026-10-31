# models/daily_fault_model.py
"""Daily (quick) faults and the PDF documents attached to them.

A machine can break down briefly: a tyre bursts, a hose leaks, a mirror breaks.
Such events are fixed on site within the day and must not open a repair record
or change the machine status, so they are stored separately here.

``fault_assignment`` and ``changed_parts`` are operator-typed free text and
``km_hour`` keeps whatever the operator wrote ("12 450 km", "350 saat", ...).

Each fault may own several PDF documents. The bytes live in PostgreSQL because
the API host (Render) has an ephemeral filesystem; this keeps the papers
available after restarts and redeploys without extra storage configuration.
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
#: ``ck_daily_fault_documents_size_limit`` and enforced by the repository).
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class DailyFaultModel(Base):
    __tablename__ = "daily_faults"

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "Şantiye" in the UI; kept separate from the machine's own territory so a
    # machine moved between sites keeps the site where the fault happened.
    territory_id = Column(
        Integer,
        ForeignKey("territories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    repair_type_id = Column(
        Integer,
        ForeignKey("repair_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    km_hour = Column(String(50), nullable=False)
    fault_assignment = Column(Text, nullable=True)
    changed_parts = Column(Text, nullable=True)

    fault_date = Column(
        Date,
        nullable=False,
        default=date.today,
        server_default=func.current_date(),
        index=True,
    )

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

    machine = relationship("AllMachineModel", back_populates="daily_faults")
    territory = relationship("TerritoryModel")
    repair_type = relationship("RepairTypeModel")
    created_by = relationship("UserModel")
    documents = relationship(
        "DailyFaultDocumentModel",
        back_populates="fault",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DailyFaultDocumentModel.created_at, DailyFaultDocumentModel.id",
    )

    def __str__(self) -> str:
        return f"Günlük arıza #{self.id}"


class DailyFaultDocumentModel(Base):
    """A PDF evidence file (work order, invoice, photo sheet...) of one fault."""

    __tablename__ = "daily_fault_documents"

    __table_args__ = (
        CheckConstraint(
            "file_size > 0",
            name="ck_daily_fault_documents_size_positive",
        ),
        CheckConstraint(
            f"file_size <= {MAX_DOCUMENT_BYTES}",
            name="ck_daily_fault_documents_size_limit",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    fault_id = Column(
        Integer,
        ForeignKey("daily_faults.id", ondelete="CASCADE"),
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

    fault = relationship("DailyFaultModel", back_populates="documents")
    uploaded_by = relationship("UserModel")

    def __str__(self) -> str:
        return self.file_name


__all__ = [
    "MAX_DOCUMENT_BYTES",
    "DailyFaultModel",
    "DailyFaultDocumentModel",
]
