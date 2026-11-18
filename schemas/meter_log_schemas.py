# schemas/meter_log_schemas.py
"""Pydantic schemas for the daily KM / engine-hour readings."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# =========================================================
# WRITE
# =========================================================

class MeterLogCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: int = Field(..., gt=0)
    log_date: date
    km: float = Field(..., ge=0)
    engine_hours: float = Field(..., ge=0)


# =========================================================
# READ
# =========================================================

class MeterLogEntrySchema(BaseModel):
    id: int
    machine_id: int
    log_date: date
    km: float
    engine_hours: float
    entered_by_id: Optional[int] = None
    entered_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class MeterLogMachineSchema(BaseModel):
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

    # Newest reading of the machine across its whole history.  It is not
    # limited to the seven-day window shown in the matrix.
    last_km: Optional[float] = None
    last_engine_hours: Optional[float] = None
    last_log_date: Optional[date] = None
    last_logged_at: Optional[datetime] = None

    # All readings that fall inside the requested window, oldest first.
    recent_logs: list[MeterLogEntrySchema] = Field(default_factory=list)


class MeterLogOverviewSchema(BaseModel):
    start_date: date
    end_date: date
    days: int
    total_recent_logs: int
    machines: list[MeterLogMachineSchema]
