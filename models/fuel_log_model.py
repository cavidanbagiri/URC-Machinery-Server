# models/fuel_log_model.py
"""Diesel distribution records for every machine.

The page **Mazot Dağılımı** writes one row each time fuel is handed to a
machine.  A row keeps its identity and can be *corrected* afterwards (the
*İşlemler → Düzenle* dialog): entering the 24th's diesel on the 25th is a common
mistake, so the date and the litres of that row are fixed instead of appending a
compensating row.  The selected day's rows are aggregated per machine for the
entry table, while the daily / weekly / monthly totals on the page come from the
same rows.
"""

from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class MachineFuelLogModel(Base):
    __tablename__ = "machine_fuel_logs"
    __table_args__ = (
        CheckConstraint(
            "liters > 0",
            name="ck_machine_fuel_logs_liters_positive",
        ),
        Index(
            "ix_machine_fuel_logs_machine_date",
            "machine_id",
            "fuel_date",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The day the fuel was handed over.  ``created_at`` records the exact save
    # time, so several refuellings on the same day stay distinguishable.
    fuel_date = Column(
        Date,
        nullable=False,
        default=date.today,
        server_default=func.current_date(),
        index=True,
    )

    liters = Column(Float, nullable=False)
    given_by = Column(String(150), nullable=False)
    note = Column(Text, nullable=True)

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

    machine = relationship("AllMachineModel", back_populates="fuel_logs")
    created_by = relationship("UserModel")

    def __str__(self) -> str:
        return f"{self.machine_id} - {self.fuel_date} - {self.liters} L"
