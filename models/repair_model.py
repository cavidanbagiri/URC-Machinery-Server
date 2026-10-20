# models/repair_model.py
"""Tamir (repair) records, repair-type lookup and audit timeline.

A machine can have at most one open repair (``status = 'tamirde'``). Closed and
cancelled records are retained for history; every state change is written to
``repair_logs`` with a Turkish, backend-generated message.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class RepairTypeModel(Base):
    """Lookup managed from Settings (Mekanik, Elektrik, Hidrolik...)."""

    __tablename__ = "repair_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)

    repair_records = relationship("RepairRecordModel", back_populates="repair_type")

    def __str__(self) -> str:
        return f"{self.name}"


class RepairRecordModel(Base):
    __tablename__ = "repair_records"

    __table_args__ = (
        CheckConstraint(
            "status IN ('tamirde', 'tamamlandi', 'iptal')",
            name="ck_repair_records_status",
        ),
        CheckConstraint(
            "estimated_exit_date IS NULL OR estimated_exit_date >= entry_date",
            name="ck_repair_records_estimate_after_entry",
        ),
        CheckConstraint(
            "exit_date IS NULL OR exit_date >= entry_date",
            name="ck_repair_records_exit_after_entry",
        ),
        CheckConstraint(
            "status <> 'tamamlandi' OR exit_date IS NOT NULL",
            name="ck_repair_records_completed_requires_exit_date",
        ),
        # PostgreSQL partial unique index: one open repair per machine.
        Index(
            "uq_repair_records_active_machine",
            "machine_id",
            unique=True,
            postgresql_where=text("status = 'tamirde'"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repair_type_id = Column(
        Integer,
        ForeignKey("repair_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    fault_location = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    entry_date = Column(Date, nullable=False, index=True)
    estimated_exit_date = Column(Date, nullable=True)
    exit_date = Column(Date, nullable=True)

    status = Column(
        String(20),
        nullable=False,
        default="tamirde",
        server_default="tamirde",
        index=True,
    )

    # Snapshot of the machine status before the repair opened. It is used to
    # restore the machine when the repair is closed, cancelled or reopened.
    previous_machine_status_id = Column(
        Integer,
        ForeignKey("car_statuses.id"),
        nullable=True,
        index=True,
    )

    created_by_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    machine = relationship("AllMachineModel", back_populates="repair_records")
    repair_type = relationship("RepairTypeModel", back_populates="repair_records")
    previous_machine_status = relationship("CarStatusModel")
    created_by = relationship("UserModel")
    logs = relationship(
        "RepairLogModel",
        back_populates="repair",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RepairLogModel.created_at, RepairLogModel.id",
    )


class RepairLogModel(Base):
    __tablename__ = "repair_logs"

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'updated', 'note_added', 'closed', "
            "'cancelled', 'reopened')",
            name="ck_repair_logs_event_type",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    repair_id = Column(
        Integer,
        ForeignKey("repair_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(30), nullable=False)
    message = Column(Text, nullable=False)
    created_by_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    repair = relationship("RepairRecordModel", back_populates="logs")
    created_by = relationship("UserModel")


__all__ = [
    "RepairTypeModel",
    "RepairRecordModel",
    "RepairLogModel",
]
