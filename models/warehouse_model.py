# models/warehouse_model.py
"""Warehouse (ambar) stock cards and the in/out ledger.

The flow implemented here completes the purchasing module:

1. The garage opens a spare-part request (``spare_part_requests``) and the
   purchasing side flips it to ``geldi`` when the material arrives.
2. The warehouse takes those arrived rows into stock: one ``giris`` movement per
   ``spare_part_request_items`` row, linked through ``source_request_item_id`` so
   the same row can never be received twice.
3. The part leaves the warehouse again as a ``cikis`` movement, optionally tied
   to the machine the part was fitted to.

``warehouse_items`` keeps the stock card (part number, name, unit, location,
critical level) and a cached balance in ``quantity``. The balance is only ever
changed by the movements below; ``warehouse_movements`` is the ledger the UI
lists, so the card and the ledger always agree.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base

#: ``warehouse_movements.movement_type`` values.
MOVEMENT_IN = "giris"
MOVEMENT_OUT = "cikis"
MOVEMENT_TYPES = (MOVEMENT_IN, MOVEMENT_OUT)
MOVEMENT_TYPE_LABELS = {MOVEMENT_IN: "Giriş", MOVEMENT_OUT: "Çıkış"}

#: Stock card states derived from ``quantity`` and ``min_quantity``.
STOCK_STATUS_OK = "yeterli"
STOCK_STATUS_LOW = "az"
STOCK_STATUS_OUT = "tukendi"
STOCK_STATUSES = (STOCK_STATUS_OK, STOCK_STATUS_LOW, STOCK_STATUS_OUT)
STOCK_STATUS_LABELS = {
    STOCK_STATUS_OK: "Yeterli",
    STOCK_STATUS_LOW: "Kritik Seviye",
    STOCK_STATUS_OUT: "Stokta Yok",
}

#: "Birim" mirrors the purchase-request module (Ad / Kg / Metre ...).
MAX_UNIT_LENGTH = 20

#: ``Decimal("0.001")`` — balances are quantized to the ``Numeric(12, 3)``
#: precision of the columns below so the ledger and the card never drift.
QUANTITY_STEP = Decimal("0.001")


def movement_type_label(movement_type: str | None) -> str:
    """Human readable movement type used by the ledger badge."""

    return MOVEMENT_TYPE_LABELS.get(
        (movement_type or "").strip().lower(), "Hareket"
    )


def stock_status(quantity, min_quantity) -> str:
    """Classify a stock card: empty, at/below the critical level, or healthy."""

    quantity = float(quantity or 0)
    min_quantity = float(min_quantity or 0)

    if quantity <= 0:
        return STOCK_STATUS_OUT
    if quantity <= min_quantity:
        return STOCK_STATUS_LOW
    return STOCK_STATUS_OK


def stock_status_label(status: str | None) -> str:
    return STOCK_STATUS_LABELS.get(status or "", "Bilinmiyor")


def quantize_quantity(value) -> Decimal:
    """Round a quantity to the column precision without leaving ``Decimal``."""

    return Decimal(str(value or 0)).quantize(QUANTITY_STEP)


class WarehouseItemModel(Base):
    """One stock card (a part number or a generic material)."""

    __tablename__ = "warehouse_items"

    __table_args__ = (
        CheckConstraint(
            "quantity >= 0",
            name="ck_warehouse_items_quantity_not_negative",
        ),
        CheckConstraint(
            "min_quantity >= 0",
            name="ck_warehouse_items_min_quantity_not_negative",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    #: "Malzeme Adı" — always required, also the key when there is no part no.
    name = Column(String(255), nullable=False, index=True)
    #: "Parça No" — optional because some consumables arrive without one.
    part_number = Column(String(100), nullable=True, index=True)

    description_tr = Column(String(500), nullable=True)
    description_ru = Column(String(500), nullable=True)

    unit = Column(String(MAX_UNIT_LENGTH), nullable=False)

    territory_id = Column(
        Integer,
        ForeignKey("territories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: "Raf / Göz" — free text shelf reference.
    location = Column(String(100), nullable=True)

    #: Critical level: the card turns "Kritik Seviye" at or below this value.
    min_quantity = Column(
        Numeric(12, 3), nullable=False, default=0, server_default=text("0")
    )
    #: Cached balance maintained by the movements.
    quantity = Column(
        Numeric(12, 3), nullable=False, default=0, server_default=text("0")
    )

    notes = Column(Text, nullable=True)

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
    created_by = relationship("UserModel")
    movements = relationship(
        "WarehouseMovementModel",
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WarehouseMovementModel.movement_date.desc()",
    )

    def __str__(self) -> str:
        return self.part_number or self.name


class WarehouseMovementModel(Base):
    """One in/out line of the warehouse ledger."""

    __tablename__ = "warehouse_movements"

    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('giris', 'cikis')",
            name="ck_warehouse_movements_type",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_warehouse_movements_quantity_positive",
        ),
        # A spare-part request row may enter the warehouse exactly once.
        # PostgreSQL treats NULLs as distinct, so manual movements stay free.
        UniqueConstraint(
            "source_request_item_id",
            name="uq_warehouse_movements_source_request_item_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    item_id = Column(
        Integer,
        ForeignKey("warehouse_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    movement_type = Column(String(10), nullable=False, index=True)
    quantity = Column(Numeric(12, 3), nullable=False)

    movement_date = Column(
        Date,
        nullable=False,
        default=date.today,
        server_default=func.current_date(),
        index=True,
    )

    #: Which machine the part was taken for ("ID No"); optional for entries.
    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    territory_id = Column(
        Integer,
        ForeignKey("territories.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: "Belge No" — STF/HTF number, invoice or waybill reference.
    document_no = Column(String(100), nullable=True)
    note = Column(String(500), nullable=True)

    #: Set when the line came from an arrived spare-part request row.
    source_request_item_id = Column(
        Integer,
        ForeignKey("spare_part_request_items.id", ondelete="SET NULL"),
        nullable=True,
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

    item = relationship("WarehouseItemModel", back_populates="movements")
    machine = relationship("AllMachineModel")
    territory = relationship("TerritoryModel")
    source_request_item = relationship("SparePartRequestItemModel")
    created_by = relationship("UserModel")

    def __str__(self) -> str:
        return (
            f"{movement_type_label(self.movement_type)} "
            f"{self.quantity} (#{self.item_id})"
        )


__all__ = [
    "MAX_UNIT_LENGTH",
    "MOVEMENT_IN",
    "MOVEMENT_OUT",
    "MOVEMENT_TYPES",
    "MOVEMENT_TYPE_LABELS",
    "QUANTITY_STEP",
    "STOCK_STATUSES",
    "STOCK_STATUS_LABELS",
    "STOCK_STATUS_LOW",
    "STOCK_STATUS_OK",
    "STOCK_STATUS_OUT",
    "WarehouseItemModel",
    "WarehouseMovementModel",
    "movement_type_label",
    "quantize_quantity",
    "stock_status",
    "stock_status_label",
]
