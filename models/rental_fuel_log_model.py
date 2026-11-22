# models/rental_fuel_log_model.py
"""Append-only diesel records for rented (kiralık) machines.

The rented equipment is rented from an outside company and is **not** part of
``all_machines``; the company supplies the machine but we supply the diesel, so
the fuel has to be tracked as well.  Because a rented machine has no fleet ID,
the ledger points at the ``machine_rentals`` agreement instead of a machine.

Like :class:`models.fuel_log_model.MachineFuelLogModel` the table is
append-only: every save inserts one row, a correction is another row, and the
rows are aggregated per rental for the **Mazot Dağılımı → Kiralık** tab.
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


class MachineRentalFuelLogModel(Base):
    __tablename__ = "machine_rental_fuel_logs"
    __table_args__ = (
        CheckConstraint(
            "liters > 0",
            name="ck_machine_rental_fuel_logs_liters_positive",
        ),
        Index(
            "ix_machine_rental_fuel_logs_rental_date",
            "rental_id",
            "fuel_date",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    rental_id = Column(
        Integer,
        ForeignKey("machine_rentals.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The day the fuel was handed over; ``created_at`` keeps the exact save
    #: time so several refuellings of the same day stay distinguishable.
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

    rental = relationship("MachineRentalModel")
    created_by = relationship("UserModel")

    def __str__(self) -> str:
        return f"{self.rental_id} - {self.fuel_date} - {self.liters} L"


__all__ = ["MachineRentalFuelLogModel"]
