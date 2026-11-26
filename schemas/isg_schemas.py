# schemas/isg_schemas.py
"""Pydantic schemas for the ISG (occupational safety) nonconformity page."""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.isg_model import (
    ISG_RESPONSIBLES,
    ISG_SEVERITY_DEFAULT,
    ISG_STATUS_OPEN,
    MAX_DESCRIPTION_LENGTH,
    MAX_RESPONSIBLE_LENGTH,
)

#: Stored state codes; a check constraint on the table enforces the same two.
IsgStatus = Literal["acik", "kapali"]

#: Importance codes; a check constraint on the table enforces the same three.
IsgSeverity = Literal["kritik", "onemli", "az_onemli"]


def canonical_responsible(value: str) -> str:
    """Trim + match one of :data:`ISG_RESPONSIBLES` case-insensitively.

    The stored value is always the canonical spelling from the tuple, so the
    table and the dropdown never disagree about "ramiz  khayramov" vs
    "Ramiz Khayramov".
    """

    cleaned = " ".join((value or "").split())
    if not cleaned:
        raise ValueError("Sorumlu seçin")

    lookup = {name.casefold(): name for name in ISG_RESPONSIBLES}
    canonical = lookup.get(cleaned.casefold())
    if canonical is None:
        raise ValueError(
            "Sorumlu listede bulunmuyor: " + ", ".join(ISG_RESPONSIBLES)
        )
    return canonical


# =========================================================
# WRITE
# =========================================================

class IsgNonconformityWriteSchema(BaseModel):
    """Create / update payload — the six fields of the form."""

    model_config = ConfigDict(extra="forbid")

    record_date: date
    description: str = Field(..., min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    status: IsgStatus = ISG_STATUS_OPEN
    severity: IsgSeverity = ISG_SEVERITY_DEFAULT
    territory_id: int = Field(..., gt=0)
    responsible_name: str = Field(
        ..., min_length=1, max_length=MAX_RESPONSIBLE_LENGTH
    )

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        # Keep the internal line breaks of a long report; only trim the ends.
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Açıklama boş olamaz")
        return cleaned

    @field_validator("responsible_name")
    @classmethod
    def validate_responsible(cls, value: str) -> str:
        return canonical_responsible(value)


class IsgNonconformityCreateSchema(IsgNonconformityWriteSchema):
    """POST /api/isg/create."""


class IsgNonconformityUpdateSchema(IsgNonconformityWriteSchema):
    """PUT /api/isg/update/{item_id} (full row)."""


class IsgStatusUpdateSchema(BaseModel):
    """PATCH /api/isg/{item_id}/status — the table's status dropdown."""

    model_config = ConfigDict(extra="forbid")

    status: IsgStatus


# =========================================================
# READ
# =========================================================

class IsgAttachmentSchema(BaseModel):
    id: int
    file_name: str
    content_type: str
    file_size: int
    #: ``True`` when the browser can show the file inline (photo).
    is_image: bool = False
    uploaded_by_id: Optional[int] = None
    created_at: Optional[datetime] = None


class IsgNonconformityItemSchema(BaseModel):
    id: int

    record_date: date
    description: str

    #: ``acik`` / ``kapali``.
    status: str
    status_label: str

    #: ``kritik`` / ``onemli`` / ``az_onemli`` and its Turkish label.
    severity: str
    severity_label: str

    territory_id: int
    territory_name: Optional[str] = None

    responsible_name: str

    closed_at: Optional[datetime] = None
    closed_by_id: Optional[int] = None
    closed_by_name: Optional[str] = None

    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    #: Metadata of the PDF/photo evidence; the bytes are streamed separately.
    attachment_count: int = 0
    attachments: list[IsgAttachmentSchema] = Field(default_factory=list)


class PaginatedIsgSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[IsgNonconformityItemSchema] = Field(default_factory=list)


class IsgOverviewSchema(BaseModel):
    """The five stat cards of the page (11.1).

    ``sru_*`` / ``dcu_*`` count the rows whose site name is SRU / DCU; a row on
    any other site only contributes to the totals.
    """

    total: int = 0
    open_total: int = 0
    closed_total: int = 0

    sru_opened: int = 0
    sru_open: int = 0
    sru_closed: int = 0

    dcu_opened: int = 0
    dcu_open: int = 0
    dcu_closed: int = 0

    #: ``sru_closed + dcu_closed`` — the "Toplam kapatılan (SRU+DCU)" card.
    sites_closed_total: int = 0


class IsgProjectSummaryItemSchema(BaseModel):
    """One line of the dashboard table: a project (site) and its counts.

    ``open`` + ``closed`` is always ``total``; a site is listed only while it
    owns at least one record.
    """

    territory_id: int
    territory_name: str
    open: int = 0
    closed: int = 0
    total: int = 0


class IsgProjectSeverityItemSchema(BaseModel):
    """One importance line under the dashboard table (Önem Derecesi).

    All three codes always come back, in Kritik → Önemli → Az Önemli order,
    even when a severity has no records yet (``total`` 0).  ``open`` +
    ``closed`` is always ``total``, like the project items above it.
    """

    severity: str
    severity_label: str
    open: int = 0
    closed: int = 0
    total: int = 0


class IsgProjectSummarySchema(BaseModel):
    """``GET /api/isg/project_summary`` — open/closed counts per project.

    ``severities`` is the same data split by **Önem Derecesi** instead of by
    project; the dashboard card shows it under the project table.
    """

    project_count: int = 0
    total: int = 0
    open_total: int = 0
    closed_total: int = 0
    items: list[IsgProjectSummaryItemSchema] = Field(default_factory=list)
    severities: list[IsgProjectSeverityItemSchema] = Field(default_factory=list)


class IsgResponsiblesSchema(BaseModel):
    items: list[str] = Field(default_factory=list)


__all__ = [
    "IsgAttachmentSchema",
    "IsgNonconformityCreateSchema",
    "IsgNonconformityItemSchema",
    "IsgNonconformityUpdateSchema",
    "IsgNonconformityWriteSchema",
    "IsgOverviewSchema",
    "IsgProjectSeverityItemSchema",
    "IsgProjectSummaryItemSchema",
    "IsgProjectSummarySchema",
    "IsgResponsiblesSchema",
    "IsgSeverity",
    "IsgStatus",
    "IsgStatusUpdateSchema",
    "PaginatedIsgSchema",
    "canonical_responsible",
]
