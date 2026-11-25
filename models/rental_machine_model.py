# models/rental_machine_model.py
"""Rented machine (Kiralık Makine) agreements.

One row is one rental: which equipment was rented, from which company, at
which site and between which dates.  The rented equipment is *not* part of
``all_machines`` (it is not our fleet), so it is described with the same
vocabulary as the fleet — makine tipi (``type_transports``), marka
(``car_marks``), model (``car_models``) and a free-text ``plate_no`` — plus the
free-text company and site.  The row never affects maintenance, repair or
machine status.

``equipment_name`` is still stored: it is the one-line label the diesel ledger
(``machine_rental_fuel_logs``) shows and searches.  The repository rebuilds it
from the structured fields on every create / update with
:func:`compose_equipment_name`, so the label can never contradict the columns.

The table derives a status from the two dates instead of storing it, so a
rental cannot get stuck in a stale state:

* ``planlandi``  – the start date is in the future,
* ``aktif``      – today is inside ``start_date..end_date`` (both inclusive),
* ``suresi_doldu`` – the end date is before today.

:func:`resolve_rental_status` is the Python form of that rule;
``rental_status_condition`` in ``repositories/rental_machine_repository.py`` is
the SQL form used by the status filter.  Keep the two in sync.
"""

from datetime import date
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base

#: Status codes shared with the frontend (``stores/rental_machine_slice.js``).
RENTAL_STATUS_ACTIVE = "aktif"
RENTAL_STATUS_PLANNED = "planlandi"
RENTAL_STATUS_EXPIRED = "suresi_doldu"

#: Human labels for the table badge.
RENTAL_STATUS_LABELS = {
    RENTAL_STATUS_ACTIVE: "Aktif",
    RENTAL_STATUS_PLANNED: "Planlandı",
    RENTAL_STATUS_EXPIRED: "Süresi doldu",
}

#: Every accepted status code, in table order.
RENTAL_STATUSES = tuple(RENTAL_STATUS_LABELS)

#: Separator used when the stored ``equipment_name`` label is rebuilt.
EQUIPMENT_LABEL_SEPARATOR = " · "


def clean_label_part(value: Optional[str]) -> str:
    """Trim and collapse repeated whitespace of one equipment label part."""

    return " ".join((value or "").split())


def compose_equipment_name(
    *,
    type_name: Optional[str] = None,
    mark_name: Optional[str] = None,
    model_name: Optional[str] = None,
    plate_no: Optional[str] = None,
    fallback: Optional[str] = None,
) -> str:
    """Build the one-line equipment label from the structured fields.

    ``"Ekskavatör · CAT · 320D · 34 ABC 123"`` — empty parts are skipped, so a
    rental that only has a type reads just ``"Ekskavatör"``.  When no structured
    field is set, ``fallback`` (the legacy free-text name) is returned instead;
    this keeps old rows and old API clients working.
    """

    parts = [
        part
        for part in (
            clean_label_part(type_name),
            clean_label_part(mark_name),
            clean_label_part(model_name),
            clean_label_part(plate_no),
        )
        if part
    ]

    if parts:
        return EQUIPMENT_LABEL_SEPARATOR.join(parts)

    return clean_label_part(fallback)


def resolve_rental_status(
    start_date: date,
    end_date: date,
    today: Optional[date] = None,
) -> str:
    """Return the status code for one rental on ``today``.

    A rental that starts today is already active; one that ends today is still
    active until the day is over.  ``end_date`` before ``start_date`` is not a
    valid rental (the schema and the table check constraint reject it), so the
    function never needs to handle it.
    """

    reference = today or date.today()

    if start_date > reference:
        return RENTAL_STATUS_PLANNED
    if end_date < reference:
        return RENTAL_STATUS_EXPIRED
    return RENTAL_STATUS_ACTIVE


class MachineRentalModel(Base):
    __tablename__ = "machine_rentals"
    __table_args__ = (
        # One inclusive range per row: the end can equal the start (one day)
        # but can never be earlier.
        CheckConstraint(
            "end_date >= start_date",
            name="ck_machine_rentals_date_order",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    #: Ekipman tanımı — one-line label rebuilt by the repository from the
    #: structured fields below (kept for the diesel ledger label / search).
    equipment_name = Column(String(200), nullable=False)

    #: Makine tipi — same lookup table as the fleet (``type_transports``).
    machine_type_id = Column(
        Integer,
        ForeignKey("type_transports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Marka — ``car_marks`` lookup.
    car_mark_id = Column(
        Integer,
        ForeignKey("car_marks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Model — ``car_models`` lookup.
    car_model_id = Column(
        Integer,
        ForeignKey("car_models.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Plaka — free text, rented equipment may have no plate at all.
    plate_no = Column(String(50), nullable=True, index=True)

    #: Firma — the company the equipment is rented from.
    company_name = Column(String(200), nullable=False)
    #: Şantiye — the site the equipment is working at.
    site_name = Column(String(200), nullable=False)

    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)

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
        nullable=False,
    )

    created_by = relationship("UserModel")

    def __str__(self) -> str:
        return f"{self.equipment_name} - {self.company_name} ({self.start_date}..{self.end_date})"


__all__ = [
    "EQUIPMENT_LABEL_SEPARATOR",
    "RENTAL_STATUSES",
    "RENTAL_STATUS_ACTIVE",
    "RENTAL_STATUS_EXPIRED",
    "RENTAL_STATUS_LABELS",
    "RENTAL_STATUS_PLANNED",
    "MachineRentalModel",
    "clean_label_part",
    "compose_equipment_name",
    "resolve_rental_status",
]
