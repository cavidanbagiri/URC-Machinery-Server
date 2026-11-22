# schemas/rental_machine_schemas.py
"""Pydantic schemas for the Kiralık Makine (rented machine) table."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Length limits, mirrored by the model columns and the frontend inputs.
MAX_EQUIPMENT_NAME_LENGTH = 200
MAX_COMPANY_NAME_LENGTH = 200
MAX_SITE_NAME_LENGTH = 200

NAME_FIELDS = ("equipment_name", "company_name", "site_name")


def normalize_name(value: str) -> str:
    """Collapse repeated whitespace so "CAT   320D" and "CAT 320D" match."""

    return " ".join(value.split())


# =========================================================
# WRITE
# =========================================================

class RentalMachineWriteSchema(BaseModel):
    """Create / update payload — the five fields of the page."""

    model_config = ConfigDict(extra="forbid")

    equipment_name: str = Field(
        ..., min_length=1, max_length=MAX_EQUIPMENT_NAME_LENGTH
    )
    company_name: str = Field(
        ..., min_length=1, max_length=MAX_COMPANY_NAME_LENGTH
    )
    site_name: str = Field(..., min_length=1, max_length=MAX_SITE_NAME_LENGTH)

    start_date: date
    end_date: date

    @field_validator(*NAME_FIELDS)
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = normalize_name(value)
        if not cleaned:
            raise ValueError("Bu alan boş olamaz")
        return cleaned

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

    equipment_name: str
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


class PaginatedRentalMachinesSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[RentalMachineItemSchema] = Field(default_factory=list)


__all__ = [
    "MAX_COMPANY_NAME_LENGTH",
    "MAX_EQUIPMENT_NAME_LENGTH",
    "MAX_SITE_NAME_LENGTH",
    "PaginatedRentalMachinesSchema",
    "RentalMachineCreateSchema",
    "RentalMachineItemSchema",
    "RentalMachineUpdateSchema",
    "RentalMachineWriteSchema",
    "normalize_name",
]
