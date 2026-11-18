# schemas/fuel_log_schemas.py
"""Pydantic schemas for the diesel distribution records."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Free-text provider ("Yakıtı veren") length, mirrored by the model column.
MAX_GIVEN_BY_LENGTH = 150
#: Free-text note length shown in the inline table input.
MAX_NOTE_LENGTH = 1000


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_given_by(value: str) -> str:
    """Collapse repeated whitespace and reject a blank provider."""

    value = " ".join((value or "").split())
    if not value:
        raise ValueError("Yakıtı veren bilgisi zorunludur")
    return value


# =========================================================
# WRITE
# =========================================================

class FuelLogCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: int = Field(..., gt=0)
    fuel_date: date
    liters: float = Field(..., gt=0, le=1_000_000)
    given_by: str = Field(..., max_length=MAX_GIVEN_BY_LENGTH)
    note: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)

    @field_validator("given_by")
    @classmethod
    def validate_given_by(cls, value: str) -> str:
        return normalize_given_by(value)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)


# =========================================================
# READ
# =========================================================

class FuelLogEntrySchema(BaseModel):
    id: int
    machine_id: int
    fuel_date: date
    liters: float
    given_by: str
    note: Optional[str] = None
    entered_by_id: Optional[int] = None
    entered_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class FuelLogMachineSchema(BaseModel):
    machine_id: int

    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None

    territory_name: Optional[str] = None
    type_name: Optional[str] = None
    subtype_name: Optional[str] = None
    car_mark_name: Optional[str] = None
    car_model_name: Optional[str] = None
    company_name: Optional[str] = None

    status_name: Optional[str] = None
    status_color: Optional[str] = None

    # Aggregates for the selected day, across every refuelling row.
    day_liters: float = 0
    day_entry_count: int = 0
    last_given_by: Optional[str] = None
    last_note: Optional[str] = None
    last_created_at: Optional[datetime] = None


class FuelLogOverviewSchema(BaseModel):
    fuel_date: date
    week_start: date
    month_start: date

    daily_total: float
    weekly_total: float
    monthly_total: float

    machines: list[FuelLogMachineSchema]
