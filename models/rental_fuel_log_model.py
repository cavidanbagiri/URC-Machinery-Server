# models/rental_fuel_log_model.py
"""Diesel records for rented (kiralık) machines.

The rented equipment is rented from an outside company and is **not** part of
``all_machines``; the company supplies the machine but we supply the diesel, so
the fuel has to be tracked as well.  Because a rented machine has no fleet ID,
the ledger points at the ``machine_rentals`` agreement instead of a machine.

Like :class:`models.fuel_log_model.MachineFuelLogModel` every save inserts one
row, and a wrong row (e.g. the 24th's diesel saved on the 25th) is corrected in
place through the **İşlemler → Düzenle** dialog.  The rows are aggregated per
rental for the **Mazot Dağılımı → Kiralık** tab.

Rented equipment has no row in ``machine_meter_logs`` (it is not part of
``all_machines``), yet the site still needs the counter reading at the moment
of refuelling.  ``km`` and ``engine_hours`` are therefore optional columns of
the diesel row itself: both stay ``NULL`` for old rows, and a rental may track
only one of the two counters.  The newest non-null value per column is the
rental's current KM / engine hour on the tab.
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
        CheckConstraint(
            "km IS NULL OR km >= 0",
            name="ck_machine_rental_fuel_logs_km_non_negative",
        ),
        CheckConstraint(
            "engine_hours IS NULL OR engine_hours >= 0",
            name="ck_machine_rental_fuel_logs_engine_hours_non_negative",
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

    #: Counter readings at the moment the diesel was handed over.  Optional:
    #: old rows (and clients that only track litres) leave them ``NULL``, and a
    #: rental may have only a KM or only an engine-hour meter.
    km = Column(Float, nullable=True)
    engine_hours = Column(Float, nullable=True)

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
        meter = ""
        if self.km is not None:
            meter += f" - {self.km} km"
        if self.engine_hours is not None:
            meter += f" - {self.engine_hours} h"
        return f"{self.rental_id} - {self.fuel_date} - {self.liters} L{meter}"


__all__ = ["MachineRentalFuelLogModel"]
