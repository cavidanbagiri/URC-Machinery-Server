# schemas/rental_machine_schemas.py
"""Pydantic schemas for the Kiralık Makine (rented machine) table."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Length limits, mirrored by the model columns and the frontend inputs.
MAX_EQUIPMENT_NAME_LENGTH = 200
MAX_COMPANY_NAME_LENGTH = 200
MAX_SITE_NAME_LENGTH = 200
MAX_PLATE_LENGTH = 50

#: Free-text fields that are trimmed / whitespace-collapsed.
NAME_FIELDS = ("equipment_name", "company_name", "site_name")

#: Structured equipment columns; at least one of them (or the legacy free-text
#: ``equipment_name``) must be filled so a row is never completely anonymous.
EQUIPMENT_ID_FIELDS = ("machine_type_id", "car_mark_id", "car_model_id")


def normalize_name(value: str) -> str:
    """Collapse repeated whitespace so "CAT   320D" and "CAT 320D" match."""

    return " ".join(value.split())


# =========================================================
# WRITE
# =========================================================

class RentalMachineWriteSchema(BaseModel):
    """Create / update payload.

    The equipment is described with ``machine_type_id`` / ``car_mark_id`` /
    ``car_model_id`` / ``plate_no``.  ``equipment_name`` stays accepted for old
    clients: the repository then uses it verbatim as the one-line label.
    """

    model_config = ConfigDict(extra="forbid")

    # ---------- structured equipment ----------
    machine_type_id: Optional[int] = Field(None, ge=1)
    car_mark_id: Optional[int] = Field(None, ge=1)
    car_model_id: Optional[int] = Field(None, ge=1)
    plate_no: Optional[str] = Field(None, max_length=MAX_PLATE_LENGTH)

    #: Legacy free-text equipment label (optional).
    equipment_name: Optional[str] = Field(
        None, min_length=1, max_length=MAX_EQUIPMENT_NAME_LENGTH
    )

    company_name: str = Field(
        ..., min_length=1, max_length=MAX_COMPANY_NAME_LENGTH
    )
    site_name: str = Field(..., min_length=1, max_length=MAX_SITE_NAME_LENGTH)

    start_date: date
    end_date: date

    @field_validator(*NAME_FIELDS)
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = normalize_name(value)
        if not cleaned:
            raise ValueError("Bu alan boş olamaz")
        return cleaned

    @field_validator("plate_no")
    @classmethod
    def validate_plate_no(cls, value: Optional[str]) -> Optional[str]:
        # A plate typed as only spaces means "no plate".
        if value is None:
            return None
        return normalize_name(value) or None

    @model_validator(mode="after")
    def validate_equipment(self):
        if not any(getattr(self, field) for field in EQUIPMENT_ID_FIELDS) and not (
            self.plate_no or self.equipment_name
        ):
            raise ValueError(
                "Ekipman bilgisi girin (makine tipi, marka, model veya plaka)"
            )
        return self

    @model_validator(mode="after")
    def validate_date_order(self):
        # The same rule is a check constraint on the table, so a bad payload
        # gets a field-level 422 instead of a database error.
        if self.end_date < self.start_date:
            raise ValueError("Bitiş tarihi başlangıç tarihinden önce olamaz")
        return self


class RentalMachineCreateSchema(RentalMachineWriteSchema):
    """POST /api/rental-machines/create."""


class RentalMachineUpdateSchema(RentalMachineWriteSchema):
    """PUT /api/rental-machines/update/{rental_id} (full row)."""


# =========================================================
# READ
# =========================================================

class RentalMachineItemSchema(BaseModel):
    id: int

    #: One-line label composed from the structured fields below.
    equipment_name: str
    machine_type_id: Optional[int] = None
    machine_type_name: Optional[str] = None
    car_mark_id: Optional[int] = None
    car_mark_name: Optional[str] = None
    car_model_id: Optional[int] = None
    car_model_name: Optional[str] = None
    plate_no: Optional[str] = None

    company_name: str
    site_name: str

    start_date: date
    end_date: date

    #: ``aktif`` / ``planlandi`` / ``suresi_doldu``, resolved from the dates.
    status: str
    status_label: str
    #: ``end_date - today`` in days (negative once the rental has ended).
    days_remaining: int
    #: Inclusive length of the rental in days (``end - start + 1``).
    duration_days: int

    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RentalMachineTypeStatSchema(BaseModel):
    """One bar of the "Makine Tipine Göre İstatistik" panel."""

    #: ``None`` for legacy rows that have no machine type yet.
    type_id: Optional[int] = None
    type_name: str
    total: int
    active_count: int
    planned_count: int
    expired_count: int


class PaginatedRentalMachinesSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[RentalMachineItemSchema] = Field(default_factory=list)
    #: Per-machine-type counts; computed with the same filters as ``items``,
    #: except the type filter itself so the panel keeps listing every type.
    type_stats: list[RentalMachineTypeStatSchema] = Field(default_factory=list)


__all__ = [
    "MAX_COMPANY_NAME_LENGTH",
    "MAX_EQUIPMENT_NAME_LENGTH",
    "MAX_PLATE_LENGTH",
    "MAX_SITE_NAME_LENGTH",
    "PaginatedRentalMachinesSchema",
    "RentalMachineCreateSchema",
    "RentalMachineItemSchema",
    "RentalMachineTypeStatSchema",
    "RentalMachineUpdateSchema",
    "RentalMachineWriteSchema",
    "normalize_name",
]

