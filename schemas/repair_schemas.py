# schemas/repair_schemas.py
"""Pydantic schemas for the machine repair (tamir) module."""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RepairStatusCode = Literal["tamirde", "tamamlandi", "iptal"]


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


# =========================================================
# WRITE
# =========================================================

class RepairCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: int = Field(..., gt=0)
    repair_type_id: int = Field(..., gt=0)

    fault_location: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=4000)

    entry_date: date = Field(default_factory=date.today)
    estimated_exit_date: Optional[date] = None

    @field_validator("fault_location", "notes")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.estimated_exit_date is not None
            and self.estimated_exit_date < self.entry_date
        ):
            raise ValueError("Tahmini çıkış tarihi giriş tarihinden önce olamaz")
        return self


class RepairUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repair_type_id: Optional[int] = Field(None, gt=0)
    fault_location: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=4000)
    entry_date: Optional[date] = None
    estimated_exit_date: Optional[date] = None

    @field_validator("fault_location", "notes")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.entry_date is not None
            and self.estimated_exit_date is not None
            and self.estimated_exit_date < self.entry_date
        ):
            raise ValueError("Tahmini çıkış tarihi giriş tarihinden önce olamaz")
        return self


class RepairCloseSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_date: date
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)


class RepairCancelSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("İptal nedeni zorunludur")
        return value


class RepairReopenSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)


class RepairNoteCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(..., min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Not metni zorunludur")
        return value


# =========================================================
# READ
# =========================================================

class RepairStatusSchema(BaseModel):
    code: str
    name: str
    color: str


class RepairTypeItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class RepairLogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repair_id: int
    event_type: str
    message: str
    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class RepairFetchItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    machine_id: int
    repair_type_id: int
    repair_type_name: Optional[str] = None

    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None

    territory_id: Optional[int] = None
    type_id: Optional[int] = None
    company_id: Optional[int] = None
    territory_name: Optional[str] = None
    type_name: Optional[str] = None
    company_name: Optional[str] = None
    car_mark_name: Optional[str] = None
    car_model_name: Optional[str] = None

    fault_location: Optional[str] = None
    notes: Optional[str] = None
    entry_date: date
    estimated_exit_date: Optional[date] = None
    exit_date: Optional[date] = None
    status: RepairStatusCode
    status_detail: RepairStatusSchema

    previous_machine_status_id: Optional[int] = None
    previous_machine_status_name: Optional[str] = None

    duration_days: Optional[int] = None
    days_remaining: Optional[int] = None
    is_overdue: bool = False

    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    logs: list[RepairLogSchema] = Field(default_factory=list)


class PaginatedRepairSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[RepairFetchItemSchema]


class RepairSummaryStatusSchema(BaseModel):
    code: RepairStatusCode
    name: str
    color: str
    count: int


class RepairSummaryTypeSchema(BaseModel):
    repair_type_id: int
    name: str
    count: int
    active_count: int


class RepairSummarySchema(BaseModel):
    total: int
    active: int
    completed: int
    cancelled: int
    overdue: int
    due_soon: int
    completed_this_month: int
    average_repair_days: Optional[float] = None
    by_status: list[RepairSummaryStatusSchema]
    by_type: list[RepairSummaryTypeSchema]


class RepairMachineOptionSchema(BaseModel):
    id: int
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None
    status_id: Optional[int] = None
    status_name: Optional[str] = None


class RepairEstimateSchema(BaseModel):
    repair_type_id: int
    repair_type_name: str
    sample_size: int
    average_days: float
    suggested_exit_date: date
    based_on: Literal["repair_type", "all_repairs", "default"]
