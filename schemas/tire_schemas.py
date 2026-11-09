# schemas/tire_schemas.py
"""Pydantic schemas for the tire (lastik) module.

A tire change records one replacement: which machine, which position, which
brand/model and size, why it was replaced, on which date and at which counter
reading. The papers attached to the change are PDFs, so they get their own
read schema just like daily faults.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: "Lastik konumu" is free text, e.g. "Sol Ön" or "Sağ Arka 2".
MAX_POSITION_LENGTH = 50
#: "Lastik marka / model", e.g. "Michelin XZL".
MAX_BRAND_MODEL_LENGTH = 150
#: "Lastik ebadı", e.g. "315/80 R22.5" or "12.00 R20".
MAX_SIZE_LENGTH = 50
#: "Motor saati / KM" is free text, e.g. "12 450 km" or "350 saat".
MAX_KM_HOUR_LENGTH = 50
MAX_REASON_LENGTH = 1000


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_position(value: str) -> str:
    """Collapse repeated whitespace and reject a blank position."""

    value = " ".join((value or "").split())
    if not value:
        raise ValueError("Lastik konumu zorunludur")
    return value


# =========================================================
# WRITE
# =========================================================

class TireChangeCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: int = Field(..., gt=0)
    position: str = Field(..., max_length=MAX_POSITION_LENGTH)

    brand_model: Optional[str] = Field(None, max_length=MAX_BRAND_MODEL_LENGTH)
    size: Optional[str] = Field(None, max_length=MAX_SIZE_LENGTH)
    change_reason: Optional[str] = Field(None, max_length=MAX_REASON_LENGTH)
    km_hour: Optional[str] = Field(None, max_length=MAX_KM_HOUR_LENGTH)

    #: Omitted by the form -> the repository stores today.
    change_date: Optional[date] = None

    @field_validator("position")
    @classmethod
    def validate_position(cls, value: str) -> str:
        return normalize_position(value)

    @field_validator("brand_model", "size", "change_reason", "km_hour")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)

    @field_validator("change_date")
    @classmethod
    def validate_change_date(cls, value: Optional[date]) -> Optional[date]:
        # A tire cannot be changed in the future; keep the counter honest.
        if value is not None and value > date.today():
            raise ValueError("Değişim tarihi bugünden ileri olamaz")
        return value


# =========================================================
# READ
# =========================================================

class TireChangeDocumentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tire_id: int
    file_name: str
    content_type: str = "application/pdf"
    file_size: int = 0

    uploaded_by_id: Optional[int] = None
    uploaded_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class TireChangeItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int

    machine_id: int
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None
    car_mark_name: Optional[str] = None
    car_model_name: Optional[str] = None
    machine_status_name: Optional[str] = None

    position: str
    brand_model: Optional[str] = None
    size: Optional[str] = None
    change_reason: Optional[str] = None
    change_date: date
    km_hour: Optional[str] = None

    #: How many older changes exist for the same machine + position ("eski kayıtlar").
    previous_count: int = 0

    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    documents: list[TireChangeDocumentSchema] = Field(default_factory=list)


class PaginatedTireChangeSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TireChangeItemSchema]


class TireMachineOptionSchema(BaseModel):
    id: int
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None
    status_id: Optional[int] = None
    status_name: Optional[str] = None


__all__ = [
    "MAX_BRAND_MODEL_LENGTH",
    "MAX_KM_HOUR_LENGTH",
    "MAX_POSITION_LENGTH",
    "MAX_REASON_LENGTH",
    "MAX_SIZE_LENGTH",
    "PaginatedTireChangeSchema",
    "TireChangeCreateSchema",
    "TireChangeDocumentSchema",
    "TireChangeItemSchema",
    "TireMachineOptionSchema",
    "normalize_position",
]
