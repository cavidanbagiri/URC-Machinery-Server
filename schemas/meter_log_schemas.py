# schemas/meter_log_schemas.py
"""Pydantic schemas for the daily KM / engine-hour readings."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =========================================================
# WRITE
# =========================================================

class MeterLogCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: int = Field(..., gt=0)
    log_date: date
    km: float = Field(..., ge=0)
    engine_hours: float = Field(..., ge=0)


def _ensure_not_future_log_date(value: Optional[date]) -> Optional[date]:
    """A correction may move a reading to an earlier day, never to the future.

    The page already refuses future dates on insert; the correction dialog has
    to enforce the same rule on the server because the reading's day is now
    editable (the classic mistake is entering today's counter tomorrow and
    fixing the date afterwards).
    """

    if value is not None and value > date.today():
        raise ValueError("Gelecek bir tarih için kayıt güncellenemez")
    return value


class MeterLogUpdateSchema(BaseModel):
    """Correction of one saved KM / engine-hour reading.

    Only the values the user actually changes are sent; every field is optional
    and ``None`` means *leave it as it is*.  ``log_date`` is the important one:
    a reading saved on the wrong day is moved to the right day instead of
    appending a second, compensating row.
    """

    model_config = ConfigDict(extra="forbid")

    log_date: Optional[date] = None
    km: Optional[float] = Field(None, ge=0, le=100_000_000)
    engine_hours: Optional[float] = Field(None, ge=0, le=1_000_000)

    @field_validator("log_date")
    @classmethod
    def validate_log_date(cls, value: Optional[date]) -> Optional[date]:
        return _ensure_not_future_log_date(value)

    @model_validator(mode="after")
    def require_a_change(self):
        if self.log_date is None and self.km is None and self.engine_hours is None:
            raise ValueError("Güncellenecek en az bir alan gönderilmelidir")
        return self


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

    # "Son Gün/KM" column: newest reading minus the reading of the day before
    # it.  ``last_change_from_date`` is the day that difference starts from.
    last_change_km: Optional[float] = None
    last_change_engine_hours: Optional[float] = None
    last_change_from_date: Optional[date] = None

    # "1 Aylık Toplam" column: newest reading minus the earliest reading of the
    # last ``MONTH_CHANGE_DAYS`` days ("at most a month").  ``None`` when the
    # machine has a single day of readings in that span.
    month_change_km: Optional[float] = None
    month_change_engine_hours: Optional[float] = None
    month_change_from_date: Optional[date] = None

    # All readings that fall inside the requested window, oldest first.
    recent_logs: list[MeterLogEntrySchema] = Field(default_factory=list)


class MeterLogOverviewSchema(BaseModel):
    start_date: date
    end_date: date
    days: int
    total_recent_logs: int
    machines: list[MeterLogMachineSchema]
