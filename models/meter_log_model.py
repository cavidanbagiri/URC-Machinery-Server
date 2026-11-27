# models/meter_log_model.py
"""Machine odometer / engine-hour readings, one row per save.

The page **Güncel KM ve Motor Saatleri** appends a row for every save.  The
newest row per machine is the current KM / engine-hour value; older rows stay
available for the weekly matrix and for audit.

A row saved on the wrong day or with a wrong counter is corrected **in place**
(``PUT /meter-logs/update/{log_id}``, the page's *İşlemler → Düzenle* dialog).
The table therefore has no ``updated_at`` / ``deleted_at`` columns: the log
keeps one row per reading and nothing is versioned or removed.
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
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class MachineMeterLogModel(Base):
    __tablename__ = "machine_meter_logs"
    __table_args__ = (
        CheckConstraint(
            "km >= 0",
            name="ck_machine_meter_logs_km_non_negative",
        ),
        CheckConstraint(
            "engine_hours >= 0",
            name="ck_machine_meter_logs_engine_hours_non_negative",
        ),
        Index(
            "ix_machine_meter_logs_machine_date",
            "machine_id",
            "log_date",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The day the reading belongs to.  ``created_at`` below records the exact
    # save time, so several readings on the same day remain distinguishable.
    log_date = Column(
        Date,
        nullable=False,
        default=date.today,
        server_default=func.current_date(),
        index=True,
    )

    km = Column(Float, nullable=False)
    engine_hours = Column(Float, nullable=False)

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

    machine = relationship("AllMachineModel", back_populates="meter_logs")
    created_by = relationship("UserModel")

    def __str__(self) -> str:
        return f"{self.machine_id} - {self.log_date} - {self.km} km / {self.engine_hours} h"
