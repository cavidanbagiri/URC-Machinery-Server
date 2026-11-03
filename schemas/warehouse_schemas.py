# schemas/warehouse_schemas.py
"""Pydantic schemas for the warehouse (ambar) module.

Write schemas trim every free-text value and turn blank strings into ``None`` so
the tables never render ``""``. ``quantity`` is deliberately *not* writable on a
stock card: the balance only moves through ``warehouse_movements``.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.warehouse_model import MAX_UNIT_LENGTH, quantize_quantity

MAX_NAME_LENGTH = 255
MAX_PART_NUMBER_LENGTH = 100
MAX_TEXT_LENGTH = 500
MAX_LOCATION_LENGTH = 100
MAX_DOCUMENT_LENGTH = 100
MAX_NOTE_LENGTH = 500
MAX_ITEMS = 200


def _clean_required_text(value: str, label: str, limit: int) -> str:
    value = " ".join((value or "").split())
    if not value:
        raise ValueError(f"{label} zorunludur")
    return value[:limit]


def _clean_optional_text(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    value = " ".join(str(value).split())
    return value[:limit] or None


def normalize_unit(value: str) -> str:
    """Normalize the "Birim" label: whitespace collapsed, blanks rejected."""

    return _clean_required_text(value, "Birim", MAX_UNIT_LENGTH)


def _lower_text(value):
    """Normalize a movement type before the ``Literal`` check runs."""

    return value.strip().lower() if isinstance(value, str) else value


# =========================================================
# STOCK CARDS
# =========================================================

class WarehouseItemCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=MAX_NAME_LENGTH)
    part_number: Optional[str] = Field(None, max_length=MAX_PART_NUMBER_LENGTH)
    description_tr: Optional[str] = Field(None, max_length=MAX_TEXT_LENGTH)
    description_ru: Optional[str] = Field(None, max_length=MAX_TEXT_LENGTH)

    unit: str = Field(..., max_length=MAX_UNIT_LENGTH)
    territory_id: Optional[int] = Field(None, gt=0)

    location: Optional[str] = Field(None, max_length=MAX_LOCATION_LENGTH)
    min_quantity: Decimal = Field(
        Decimal("0"), ge=0, max_digits=12, decimal_places=3
    )
    notes: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH * 4)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_required_text(value, "Malzeme adı", MAX_NAME_LENGTH)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        return normalize_unit(value)

    @field_validator("part_number")
    @classmethod
    def normalize_part_number(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_PART_NUMBER_LENGTH)

    @field_validator("description_tr", "description_ru")
    @classmethod
    def normalize_descriptions(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_TEXT_LENGTH)

    @field_validator("location")
    @classmethod
    def normalize_location(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_LOCATION_LENGTH)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_NOTE_LENGTH * 4)


class WarehouseItemUpdateSchema(BaseModel):
    """Partial update; ``quantity`` stays read-only (movements own it)."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=MAX_NAME_LENGTH)
    part_number: Optional[str] = Field(None, max_length=MAX_PART_NUMBER_LENGTH)
    description_tr: Optional[str] = Field(None, max_length=MAX_TEXT_LENGTH)
    description_ru: Optional[str] = Field(None, max_length=MAX_TEXT_LENGTH)

    unit: Optional[str] = Field(None, max_length=MAX_UNIT_LENGTH)
    territory_id: Optional[int] = Field(None, gt=0)

    location: Optional[str] = Field(None, max_length=MAX_LOCATION_LENGTH)
    min_quantity: Optional[Decimal] = Field(
        None, ge=0, max_digits=12, decimal_places=3
    )
    notes: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH * 4)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        return _clean_required_text(value, "Malzeme adı", MAX_NAME_LENGTH)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else normalize_unit(value)

    @field_validator("part_number")
    @classmethod
    def normalize_part_number(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_PART_NUMBER_LENGTH)

    @field_validator("description_tr", "description_ru")
    @classmethod
    def normalize_descriptions(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_TEXT_LENGTH)

    @field_validator("location")
    @classmethod
    def normalize_location(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_LOCATION_LENGTH)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_NOTE_LENGTH * 4)

# =========================================================
# MOVEMENTS
# =========================================================

class WarehouseMovementCreateSchema(BaseModel):
    """A manual in/out line ("giriş" / "çıkış")."""

    model_config = ConfigDict(extra="forbid")

    item_id: int = Field(..., gt=0)
    movement_type: Literal["giris", "cikis"]
    quantity: Decimal = Field(..., gt=0, max_digits=12, decimal_places=3)

    movement_date: date
    machine_id: Optional[int] = Field(None, gt=0)
    territory_id: Optional[int] = Field(None, gt=0)

    document_no: Optional[str] = Field(None, max_length=MAX_DOCUMENT_LENGTH)
    note: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)

    @field_validator("movement_type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        return _lower_text(value)

    @field_validator("quantity")
    @classmethod
    def normalize_quantity(cls, value: Decimal) -> Decimal:
        return quantize_quantity(value)

    @field_validator("document_no")
    @classmethod
    def normalize_document_no(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_DOCUMENT_LENGTH)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_NOTE_LENGTH)


# =========================================================
# RECEIPTS ("Depoya Al" — arrived spare-part rows)
# =========================================================

class WarehouseReceiptItemSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_item_id: int = Field(..., gt=0)
    #: ``None`` means "receive exactly the requested quantity".
    quantity: Optional[Decimal] = Field(
        None, gt=0, max_digits=12, decimal_places=3
    )

    @field_validator("quantity")
    @classmethod
    def normalize_quantity(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        return None if value is None else quantize_quantity(value)


class WarehouseReceiptCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WarehouseReceiptItemSchema] = Field(
        ..., min_length=1, max_length=MAX_ITEMS
    )
    movement_date: date = Field(default_factory=date.today)
    note: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, MAX_NOTE_LENGTH)


# =========================================================
# READ
# =========================================================

class WarehouseItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    part_number: Optional[str] = None
    description_tr: Optional[str] = None
    description_ru: Optional[str] = None

    unit: str = ""
    territory_id: Optional[int] = None
    territory_name: Optional[str] = None
    location: Optional[str] = None

    min_quantity: float = 0
    quantity: float = 0

    #: ``yeterli`` / ``az`` / ``tukendi`` — derived from the two values above.
    stock_status: str = "tukendi"
    stock_status_label: str = "Stokta Yok"
    movement_count: int = 0

    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PaginatedWarehouseItemSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[WarehouseItemSchema]


class WarehouseMovementSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    item_name: Optional[str] = None
    item_part_number: Optional[str] = None
    unit: Optional[str] = None

    movement_type: str
    movement_type_label: str = "Hareket"
    quantity: float = 0
    movement_date: date

    machine_id: Optional[int] = None
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None
    machine_label: Optional[str] = None

    document_no: Optional[str] = None
    note: Optional[str] = None

    source_request_item_id: Optional[int] = None
    source_request_no: Optional[str] = None

    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class PaginatedWarehouseMovementSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[WarehouseMovementSchema]


class PendingReceiptSchema(BaseModel):
    """An arrived spare-part row that is not in the warehouse yet."""

    request_item_id: int
    request_id: int
    request_title: str
    stf_htf_no: str
    request_date: date
    territory_name: Optional[str] = None
    request_type_name: Optional[str] = None

    machine_id: int
    machine_label: str
    garage_request_no: Optional[str] = None

    part_number: Optional[str] = None
    description_tr: Optional[str] = None
    description_ru: Optional[str] = None
    quantity: float = 0
    unit: str = ""
    supply_date: Optional[date] = None

    #: Existing stock card that will receive the quantity (``None`` = new card).
    stock_item_id: Optional[int] = None
    stock_item_name: Optional[str] = None
    stock_item_quantity: float = 0


class PaginatedPendingReceiptSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PendingReceiptSchema]


class WarehouseReceiptResultSchema(BaseModel):
    received: int = 0
    created_items: int = 0
    movements: list[WarehouseMovementSchema] = Field(default_factory=list)


class WarehouseSummarySchema(BaseModel):
    stock_items: int = 0
    critical_items: int = 0
    pending_receipts: int = 0
    total_quantity: float = 0
    month_in_quantity: float = 0
    month_out_quantity: float = 0


__all__ = [
    "MAX_DOCUMENT_LENGTH",
    "MAX_ITEMS",
    "MAX_LOCATION_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_NOTE_LENGTH",
    "MAX_PART_NUMBER_LENGTH",
    "MAX_TEXT_LENGTH",
    "PaginatedPendingReceiptSchema",
    "PaginatedWarehouseItemSchema",
    "PaginatedWarehouseMovementSchema",
    "PendingReceiptSchema",
    "WarehouseItemCreateSchema",
    "WarehouseItemSchema",
    "WarehouseItemUpdateSchema",
    "WarehouseMovementCreateSchema",
    "WarehouseMovementSchema",
    "WarehouseReceiptCreateSchema",
    "WarehouseReceiptItemSchema",
    "WarehouseReceiptResultSchema",
    "WarehouseSummarySchema",
    "normalize_unit",
]

