# schemas/stock_schemas.py
"""Pydantic şemaları — basit stok modülü."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_NAME_LENGTH = 255
MAX_UNIT_LENGTH = 20
MAX_GIVEN_TO_LENGTH = 150
MAX_NOTE_LENGTH = 1000


def _clean_required_text(value: str, message: str) -> str:
    value = " ".join((value or "").split())
    if not value:
        raise ValueError(message)
    return value


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


# =========================================================
# WRITE
# =========================================================

class StockItemCreateSchema(BaseModel):
    """Yeni stok kartı.  Miktar ilk sayımda doğrudan yazılır."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=MAX_NAME_LENGTH)
    unit: str = Field(..., max_length=MAX_UNIT_LENGTH)
    quantity: Decimal = Field(
        Decimal("0"),
        ge=0,
        max_digits=12,
        decimal_places=3,
    )
    notes: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_required_text(value, "Malzeme adı zorunludur")

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        return _clean_required_text(value, "Birim zorunludur")

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)


class StockItemUpdateSchema(BaseModel):
    """Kart düzenleme; yalnızca gönderilen alanlar değişir."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=MAX_NAME_LENGTH)
    unit: Optional[str] = Field(None, max_length=MAX_UNIT_LENGTH)
    quantity: Optional[Decimal] = Field(
        None,
        ge=0,
        max_digits=12,
        decimal_places=3,
    )
    notes: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _clean_required_text(value, "Malzeme adı zorunludur")

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _clean_required_text(value, "Birim zorunludur")

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)


class StockIssueCreateSchema(BaseModel):
    """Sahaya çıkış: seçilen karttan miktar düşer."""

    model_config = ConfigDict(extra="forbid")

    stock_item_id: int = Field(..., gt=0)
    quantity: Decimal = Field(
        ...,
        gt=0,
        max_digits=12,
        decimal_places=3,
    )
    issue_date: date
    machine_id: Optional[int] = Field(None, gt=0)
    given_to: Optional[str] = Field(None, max_length=MAX_GIVEN_TO_LENGTH)
    note: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)

    @field_validator("given_to")
    @classmethod
    def normalize_given_to(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value)


# =========================================================
# READ
# =========================================================

class StockItemSchema(BaseModel):
    id: int
    name: str
    unit: str
    quantity: float
    notes: Optional[str] = None
    issue_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StockItemListSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[StockItemSchema]


class StockIssueSchema(BaseModel):
    id: int
    stock_item_id: int
    item_name: str
    unit: str
    quantity: float
    issue_date: date
    machine_id: Optional[int] = None
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None
    machine_label: Optional[str] = None
    given_to: Optional[str] = None
    note: Optional[str] = None
    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class StockIssueListSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[StockIssueSchema]


class StockIssueDeleteResultSchema(BaseModel):
    """Çıkış silindiğinde stoğa geri eklenen miktar."""

    stock_item_id: int
    quantity: float
    new_quantity: float


class StockSummarySchema(BaseModel):
    item_count: int
    total_quantity: float
    out_of_stock_items: int
    month_issue_quantity: float
    month_issue_count: int
