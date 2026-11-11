# models/purchase_request_model.py
"""Purchase requests ("Satın Alma Talepleri").

Two independent flows share one page:

``spare_part_requests``
    A spare-part request is written once and may cover several machines
    ("ID No"), so the header (title, STF/HTF no, territory, type, date, status)
    lives here and every requested part is a row in
    ``spare_part_request_items`` (garage request no, part number, RU/TR
    descriptions, quantity, unit, supply date).

``service_requests``
    A service/repair job done by an outside company for exactly one machine
    (service form no, company, description, date).

Spare-part status is a two-value state requested by the garage:
``bekleniyor`` (waiting) and ``geldi`` (arrived).

``spare_part_request_types`` is the "Talep Türü" lookup (``Arıza``,
``Yedek Bakım``) seeded by the migration and editable through the API.

``spare_part_request_documents`` keeps the paper (signed order, invoice,
delivery note) of a request. The bytes live in PostgreSQL because the API host
(Render) has an ephemeral filesystem, so the PDF is validated by
``repositories/pdf_documents.py`` before it is written — exactly like the daily
fault and tire documents.
"""

from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base

#: Allowed ``spare_part_requests.status`` values (mirrored by the check
#: constraint ``ck_spare_part_requests_status`` and the pydantic ``Literal``).
SPARE_PART_STATUSES = ("geldi", "bekleniyor")
DEFAULT_SPARE_PART_STATUS = "bekleniyor"
STATUS_LABELS = {"geldi": "Geldi", "bekleniyor": "Bekleniyor"}

#: "Birim" values are short free text; the UI offers Ad / LT / MT / KG ...
MAX_UNIT_LENGTH = 20

#: Hard limit for one uploaded PDF, mirrored by the ``file_size`` check
#: constraint of ``spare_part_request_documents`` and enforced by the
#: repository (``repositories/pdf_documents.py``).
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def status_label(status: str | None) -> str:
    """Human readable status used by the list and the table badge."""

    return STATUS_LABELS.get((status or "").strip().lower(), "Bekleniyor")


class SparePartRequestTypeModel(Base):
    """Lookup for "Talep Türü" (Arıza, Yedek Bakım, ...)."""

    __tablename__ = "spare_part_request_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)

    requests = relationship("SparePartRequestModel", back_populates="request_type")

    def __str__(self) -> str:
        return f"{self.name}"


class SparePartRequestModel(Base):
    """Header of a spare-part request; parts are the child rows."""

    __tablename__ = "spare_part_requests"

    __table_args__ = (
        CheckConstraint(
            "status IN ('geldi', 'bekleniyor')",
            name="ck_spare_part_requests_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(255), nullable=False)
    #: "STF/HTF No" — the paper reference of the request.
    stf_htf_no = Column(String(100), nullable=False, index=True)

    territory_id = Column(
        Integer,
        ForeignKey("territories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    request_type_id = Column(
        Integer,
        ForeignKey("spare_part_request_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    request_date = Column(
        Date,
        nullable=False,
        default=date.today,
        server_default=func.current_date(),
        index=True,
    )
    status = Column(
        String(20),
        nullable=False,
        default=DEFAULT_SPARE_PART_STATUS,
        server_default=DEFAULT_SPARE_PART_STATUS,
        index=True,
    )

    created_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    territory = relationship("TerritoryModel")
    request_type = relationship(
        "SparePartRequestTypeModel", back_populates="requests"
    )
    created_by = relationship("UserModel")
    items = relationship(
        "SparePartRequestItemModel",
        back_populates="request",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SparePartRequestItemModel.id",
    )
    documents = relationship(
        "SparePartRequestDocumentModel",
        back_populates="request",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SparePartRequestDocumentModel.id",
    )

    def __str__(self) -> str:
        return f"{self.stf_htf_no} - {self.title}"


class SparePartRequestItemModel(Base):
    """One requested part ("ID No" + part details) of a spare-part request."""

    __tablename__ = "spare_part_request_items"

    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_spare_part_request_items_quantity_positive",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(
        Integer,
        ForeignKey("spare_part_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Every machine has its own garage request number.
    garage_request_no = Column(String(100), nullable=True)
    part_number = Column(String(100), nullable=True)
    description_ru = Column(String(500), nullable=True)
    description_tr = Column(String(500), nullable=True)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit = Column(String(MAX_UNIT_LENGTH), nullable=False)
    supply_date = Column(Date, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    request = relationship("SparePartRequestModel", back_populates="items")
    machine = relationship(
        "AllMachineModel", back_populates="spare_part_request_items"
    )

    def __str__(self) -> str:
        return self.part_number or f"Kalem #{self.id}"


class SparePartRequestDocumentModel(Base):
    """A PDF evidence file (signed order, invoice, delivery note) of a request."""

    __tablename__ = "spare_part_request_documents"

    __table_args__ = (
        CheckConstraint(
            "file_size > 0",
            name="ck_spare_part_request_documents_size_positive",
        ),
        CheckConstraint(
            f"file_size <= {MAX_DOCUMENT_BYTES}",
            name="ck_spare_part_request_documents_size_limit",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(
        Integer,
        ForeignKey("spare_part_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_name = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False, default="application/pdf")
    file_size = Column(Integer, nullable=False)
    file_data = Column(LargeBinary, nullable=False)

    uploaded_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    request = relationship("SparePartRequestModel", back_populates="documents")
    uploaded_by = relationship("UserModel")

    def __str__(self) -> str:
        return self.file_name


class ServiceRequestModel(Base):
    """A service / repair job given to an outside company."""

    __tablename__ = "service_requests"

    id = Column(Integer, primary_key=True, index=True)

    #: "Servis Form Başlığı"
    title = Column(String(255), nullable=False)
    #: "Servis Form No"
    service_form_no = Column(String(100), nullable=False, index=True)

    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: "Hizmet Alınacak Firma"
    company_name = Column(String(255), nullable=False)
    #: "Hizmet Tanımı"
    service_description = Column(Text, nullable=False)

    request_date = Column(
        Date,
        nullable=False,
        default=date.today,
        server_default=func.current_date(),
        index=True,
    )

    created_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    machine = relationship("AllMachineModel", back_populates="service_requests")
    created_by = relationship("UserModel")

    def __str__(self) -> str:
        return f"{self.service_form_no} - {self.title}"


__all__ = [
    "DEFAULT_SPARE_PART_STATUS",
    "MAX_DOCUMENT_BYTES",
    "MAX_UNIT_LENGTH",
    "SPARE_PART_STATUSES",
    "STATUS_LABELS",
    "ServiceRequestModel",
    "SparePartRequestDocumentModel",
    "SparePartRequestItemModel",
    "SparePartRequestModel",
    "SparePartRequestTypeModel",
    "status_label",
]
