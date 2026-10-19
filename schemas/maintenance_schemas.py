# schemas/maintenance_schemas.py
"""Pydantic schemas for periodic maintenance tracking."""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

UsageUnit = Literal["km", "hour"]

MaintenanceStatusCode = Literal[
    "gecikmis",
    "yaklasiyor",
    "veri_uyarisi",
    "veri_eksik",
    "plan_yok",
    "uygun",
    "pasif",
]


# =========================================================
# SETTING / PLAN
# =========================================================

class MaintenanceSettingUpdateSchema(BaseModel):
    """Partial update. On create ``usage_unit`` and ``interval_value`` are
    required (validated by the repository because the same payload is used for
    an upsert)."""

    model_config = ConfigDict(extra="forbid")

    usage_unit: Optional[UsageUnit] = None
    interval_value: Optional[float] = Field(None, gt=0)

    last_counter: Optional[float] = Field(None, ge=0)
    last_maintenance_date: Optional[date] = None

    current_counter: Optional[float] = Field(None, ge=0)
    current_counter_date: Optional[date] = None

    warning_threshold: Optional[float] = Field(None, ge=0)
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=2000)


# =========================================================
# ACTIONS
# =========================================================

class MaintenanceReadingCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counter_value: float = Field(..., ge=0)
    reading_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=2000)


class MaintenanceCompleteSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maintenance_date: Optional[date] = None
    counter_value: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=2000)


# =========================================================
# READ MODELS
# =========================================================

class MaintenanceStatusSchema(BaseModel):
    code: str
    name: str
    color: str


class MaintenanceFetchItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    machine_id: int
    setting_id: Optional[int] = None

    identification_no: Optional[str] = None
    plate_no: Optional[str] = None

    territory_id: Optional[int] = None
    type_id: Optional[int] = None
    company_id: Optional[int] = None
    machine_status_id: Optional[int] = None

    territory_name: Optional[str] = None
    type_name: Optional[str] = None
    company_name: Optional[str] = None
    car_mark_name: Optional[str] = None
    car_model_name: Optional[str] = None

    has_plan: bool
    usage_unit: Optional[UsageUnit] = None
    interval_value: Optional[float] = None

    last_counter: Optional[float] = None
    last_maintenance_date: Optional[date] = None

    current_counter: Optional[float] = None
    current_counter_date: Optional[date] = None

    next_counter: Optional[float] = None
    remaining: Optional[float] = None

    warning_threshold: Optional[float] = None
    effective_warning_threshold: Optional[float] = None

    is_active: bool = False
    notes: Optional[str] = None

    status: MaintenanceStatusSchema


class PaginatedMaintenanceSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[MaintenanceFetchItemSchema]


class MaintenanceSummaryStatusSchema(BaseModel):
    code: str
    name: str
    color: str
    count: int


class MaintenanceUsageUnitSchema(BaseModel):
    unit: UsageUnit
    count: int


class MaintenanceSummarySchema(BaseModel):
    total: int
    planned: int
    unplanned: int
    inactive: int
    overdue: int
    due_soon: int
    needs_attention: int
    by_status: list[MaintenanceSummaryStatusSchema]
    usage_units: list[MaintenanceUsageUnitSchema]


class MaintenanceHistoryItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    machine_id: int
    record_type: Literal["reading", "maintenance"]
    record_date: date
    counter_value: Optional[float] = None
    usage_unit: Optional[UsageUnit] = None
    interval_value: Optional[float] = None
    notes: Optional[str] = None
    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
