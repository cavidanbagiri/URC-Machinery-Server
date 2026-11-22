# schemas/fuel_log_schemas.py
"""Pydantic schemas for the diesel distribution records."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Free-text provider length, mirrored by the model column.  The page no longer
#: asks for it: the backend stores the signed-in user's name when it is empty.
MAX_GIVEN_BY_LENGTH = 150
#: Free-text note length kept for API compatibility (the UI column was replaced
#: by the calculated average consumption).
MAX_NOTE_LENGTH = 1000


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_given_by(value: Optional[str]) -> Optional[str]:
    """Collapse repeated whitespace; a blank provider becomes ``None``.

    ``None`` tells the router to fall back to the signed-in user's name, so the
    append-only row always has a provider even though the table no longer has a
    *Yakıtı veren* input.
    """

    value = " ".join((value or "").split())
    return value or None


# =========================================================
# WRITE
# =========================================================

class FuelLogCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: int = Field(..., gt=0)
    fuel_date: date
    liters: float = Field(..., gt=0, le=1_000_000)
    #: Optional since the table no longer asks who handed the fuel over; the
    #: router fills the signed-in user's name when it is omitted.
    given_by: Optional[str] = Field(None, max_length=MAX_GIVEN_BY_LENGTH)
    note: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)

    @field_validator("given_by")
    @classmethod
    def validate_given_by(cls, value: Optional[str]) -> Optional[str]:
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

    # Newest KM / engine-hour reading ("Güncel KM / Saat"), taken from
    # ``machine_meter_logs`` exactly like the **Güncel KM ve Motor Saatleri**
    # page and the repair/tire forms.
    last_km: Optional[float] = None
    last_engine_hours: Optional[float] = None
    last_log_date: Optional[date] = None

    # Counter the machine is tracked on ("km" or "hour"), mirrored from the
    # periodic maintenance setting.  ``consumption_unit`` is the counter the
    # average below was really calculated with.
    usage_unit: Optional[str] = None
    consumption_unit: Optional[str] = None
    #: Liters per 1 km / 1 engine hour, calculated by the backend.
    avg_consumption: Optional[float] = None
    consumption_liters: Optional[float] = None
    consumption_distance: Optional[float] = None
    consumption_start_date: Optional[date] = None
    consumption_end_date: Optional[date] = None


class FuelLogOverviewSchema(BaseModel):
    fuel_date: date
    week_start: date
    month_start: date

    daily_total: float
    weekly_total: float
    monthly_total: float

    #: Previous calendar month (complete), shown as the first summary card.
    previous_month_start: date
    previous_month_end: date
    previous_month_total: float

    #: Current-month totals of the two main sites ("şantiye" = territory).
    sru_monthly_total: float
    dcu_monthly_total: float

    machines: list[FuelLogMachineSchema] = Field(default_factory=list)
