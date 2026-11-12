# schemas/purchase_request_schemas.py
"""Pydantic schemas for the purchase-request module.

One spare-part request may cover several machines, so the write schema nests the
part rows (``items``) inside the header. Every optional free-text value is
trimmed and an empty string becomes ``None`` so the table never shows ``""``.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.purchase_request_model import (
    DEFAULT_SPARE_PART_STATUS,
    MAX_UNIT_LENGTH,
    SPARE_PART_STATUSES,
    status_label,
)

MAX_TITLE_LENGTH = 255
MAX_REQUEST_NO_LENGTH = 100
MAX_TEXT_LENGTH = 500
MAX_DESCRIPTION_LENGTH = 4000
MAX_ITEMS = 200

#: What the request is waiting for (see ``SPARE_PART_STATUSES``).
SparePartStatus = Literal["onay_bekliyor", "odeme_bekliyor", "firma_bekleniyor"]


def _clean_required_text(value: str, label: str) -> str:
    value = " ".join((value or "").split())
    if not value:
        raise ValueError(f"{label} zorunludur")
    return value


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def normalize_unit(value: str) -> str:
    """Normalize the "Birim" label: whitespace collapsed, blanks rejected."""

    return _clean_required_text(value, "Birim")[:MAX_UNIT_LENGTH]


def normalize_status(value: str) -> str:
    value = (value or "").strip().lower()
    if value not in SPARE_PART_STATUSES:
        raise ValueError(
            "Talep durumu yalnızca "
            + ", ".join(f"'{status}'" for status in SPARE_PART_STATUSES)
            + " olabilir"
        )
    return value


def _lower_text(value: Any) -> Any:
    """Normalize a status input before the ``Literal`` check runs."""

    return value.strip().lower() if isinstance(value, str) else value


# =========================================================
# WRITE
# =========================================================

class SparePartRequestItemCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: int = Field(..., gt=0)

    garage_request_no: Optional[str] = Field(None, max_length=MAX_REQUEST_NO_LENGTH)
    part_number: Optional[str] = Field(None, max_length=MAX_REQUEST_NO_LENGTH)
    description_ru: Optional[str] = Field(None, max_length=MAX_TEXT_LENGTH)
    description_tr: Optional[str] = Field(None, max_length=MAX_TEXT_LENGTH)

    quantity: Decimal = Field(..., gt=0, max_digits=12, decimal_places=3)
    unit: str = Field(..., max_length=MAX_UNIT_LENGTH)
    supply_date: Optional[date] = None

    @field_validator("garage_request_no", "part_number", "description_ru", "description_tr")
    @classmethod
    def normalize_optional(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        return normalize_unit(value)


class SparePartRequestCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=MAX_TITLE_LENGTH)
    stf_htf_no: str = Field(..., max_length=MAX_REQUEST_NO_LENGTH)

    territory_id: int = Field(..., gt=0)
    request_type_id: int = Field(..., gt=0)
    request_date: date

    status: SparePartStatus = DEFAULT_SPARE_PART_STATUS
    items: list[SparePartRequestItemCreateSchema] = Field(
        ..., min_length=1, max_length=MAX_ITEMS
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _clean_required_text(value, "Talep başlığı")

    @field_validator("stf_htf_no")
    @classmethod
    def validate_stf_htf_no(cls, value: str) -> str:
        return _clean_required_text(value, "STF/HTF No")

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status_input(cls, value: Any) -> Any:
        return _lower_text(value)


class SparePartRequestItemUpdateSchema(SparePartRequestItemCreateSchema):
    """A create row plus the id of an existing row.

    ``id`` is sent for the rows that already exist, so editing a request keeps
    their arrival flags; rows without an id are new, and rows that are not in
    the payload are deleted.
    """

    id: Optional[int] = Field(None, gt=0)


class SparePartRequestUpdateSchema(SparePartRequestCreateSchema):
    """Same shape as the create payload; part rows may carry their id."""

    items: list[SparePartRequestItemUpdateSchema] = Field(
        ..., min_length=1, max_length=MAX_ITEMS
    )


class SparePartItemArrivalUpdateSchema(BaseModel):
    """The "geldi / gelmedi" flag of one part row of a request."""

    model_config = ConfigDict(extra="forbid")

    is_arrived: bool


class SparePartStatusUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SparePartStatus

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status_input(cls, value: Any) -> Any:
        return _lower_text(value)


class ServiceRequestCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=MAX_TITLE_LENGTH)
    service_form_no: str = Field(..., max_length=MAX_REQUEST_NO_LENGTH)
    machine_id: int = Field(..., gt=0)
    company_name: str = Field(..., max_length=MAX_TITLE_LENGTH)
    service_description: str = Field(..., max_length=MAX_DESCRIPTION_LENGTH)
    request_date: date

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _clean_required_text(value, "Servis form başlığı")

    @field_validator("service_form_no")
    @classmethod
    def validate_service_form_no(cls, value: str) -> str:
        return _clean_required_text(value, "Servis form no")

    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, value: str) -> str:
        return _clean_required_text(value, "Hizmet alınacak firma")

    @field_validator("service_description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _clean_required_text(value, "Hizmet tanımı")


# =========================================================
# READ
# =========================================================

class SparePartRequestDocumentSchema(BaseModel):
    """Metadata of one PDF stored for a request; the bytes come from
    ``GET /spare-parts/{request_id}/documents/{document_id}``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    content_type: str = "application/pdf"
    file_size: int = 0
    created_at: Optional[datetime] = None


class SparePartRequestItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    machine_id: int
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None

    garage_request_no: Optional[str] = None
    part_number: Optional[str] = None
    description_ru: Optional[str] = None
    description_tr: Optional[str] = None
    quantity: float = 0
    unit: str = ""
    supply_date: Optional[date] = None

    #: "Geldi mi?" — tracked per row, the header only says what is awaited.
    is_arrived: bool = False
    arrived_at: Optional[datetime] = None


class SparePartRequestSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    stf_htf_no: str

    territory_id: int
    territory_name: Optional[str] = None
    request_type_id: int
    request_type_name: Optional[str] = None

    request_date: date
    status: str = DEFAULT_SPARE_PART_STATUS
    status_label: str = "Onay Bekliyor"

    #: Convenience fields for the table ("ID No" may list several machines).
    machine_ids: list[int] = Field(default_factory=list)
    machine_labels: list[str] = Field(default_factory=list)
    item_count: int = 0
    #: How many of the ``item_count`` rows are already on site.
    arrived_count: int = 0

    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    items: list[SparePartRequestItemSchema] = Field(default_factory=list)
    documents: list[SparePartRequestDocumentSchema] = Field(default_factory=list)


class PaginatedSparePartRequestSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SparePartRequestSchema]


class ServiceRequestSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    service_form_no: str

    machine_id: int
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None

    company_name: str
    service_description: str
    request_date: date

    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PaginatedServiceRequestSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ServiceRequestSchema]


class RequestTypeOptionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class PurchaseMachineOptionSchema(BaseModel):
    id: int
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None


__all__ = [
    "MAX_DESCRIPTION_LENGTH",
    "MAX_ITEMS",
    "MAX_REQUEST_NO_LENGTH",
    "MAX_TEXT_LENGTH",
    "MAX_TITLE_LENGTH",
    "PaginatedServiceRequestSchema",
    "PaginatedSparePartRequestSchema",
    "PurchaseMachineOptionSchema",
    "RequestTypeOptionSchema",
    "ServiceRequestCreateSchema",
    "ServiceRequestSchema",
    "SparePartItemArrivalUpdateSchema",
    "SparePartRequestCreateSchema",
    "SparePartRequestDocumentSchema",
    "SparePartRequestItemCreateSchema",
    "SparePartRequestItemSchema",
    "SparePartRequestItemUpdateSchema",
    "SparePartRequestSchema",
    "SparePartRequestUpdateSchema",
    "SparePartStatus",
    "SparePartStatusUpdateSchema",
    "normalize_status",
    "normalize_unit",
]

