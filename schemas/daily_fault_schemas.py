# schemas/daily_fault_schemas.py
"""Pydantic schemas for the daily (quick) fault module.

Daily faults are small on-site interventions (a burst tyre, a loose hose) that
are finished within the day, so unlike repair records they never change the
machine status. The form keeps two free-text notes and a hand-typed counter.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: "KM / Saat" is free text, e.g. "12 450 km" or "350 saat".
MAX_KM_HOUR_LENGTH = 50
MAX_NOTE_LENGTH = 4000


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_km_hour(value: str) -> str:
    """Collapse repeated whitespace and reject a blank counter."""

    value = " ".join((value or "").split())
    if not value:
        raise ValueError("KM / Saat değeri zorunludur")
    return value


# =========================================================
# WRITE
# =========================================================

class DailyFaultCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: int = Field(..., gt=0)
    territory_id: int = Field(..., gt=0)
    repair_type_id: int = Field(..., gt=0)

    km_hour: str = Field(..., max_length=MAX_KM_HOUR_LENGTH)
    fault_assignment: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)
    changed_parts: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)

    @field_validator("km_hour")
    @classmethod
    def validate_km_hour(cls, value: str) -> str:
        return normalize_km_hour(value)

    @field_validator("fault_assignment", "changed_parts")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)


# =========================================================
# READ
# =========================================================

class DailyFaultDocumentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fault_id: int
    file_name: str
    content_type: str = "application/pdf"
    file_size: int = 0

    uploaded_by_id: Optional[int] = None
    uploaded_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class DailyFaultItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int

    machine_id: int
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None
    car_mark_name: Optional[str] = None
    car_model_name: Optional[str] = None
    machine_status_name: Optional[str] = None

    territory_id: int
    territory_name: Optional[str] = None
    repair_type_id: int
    repair_type_name: Optional[str] = None

    km_hour: str
    fault_assignment: Optional[str] = None
    changed_parts: Optional[str] = None

    fault_date: date

    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    documents: list[DailyFaultDocumentSchema] = Field(default_factory=list)


class PaginatedDailyFaultSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[DailyFaultItemSchema]


class DailyFaultMachineOptionSchema(BaseModel):
    id: int
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None
    status_id: Optional[int] = None
    status_name: Optional[str] = None


__all__ = [
    "MAX_KM_HOUR_LENGTH",
    "MAX_NOTE_LENGTH",
    "DailyFaultCreateSchema",
    "DailyFaultDocumentSchema",
    "DailyFaultItemSchema",
    "DailyFaultMachineOptionSchema",
    "PaginatedDailyFaultSchema",
    "normalize_km_hour",
]
