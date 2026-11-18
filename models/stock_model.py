# models/stock_model.py
"""Basit stok modülü.

Bu modül eski **Ambar** (``warehouse_items`` / ``warehouse_movements``)
tablolarından bağımsızdır.  Mekanik ekibi malzemeyi (filtre, yağ, ...) elle
tanımlar; stok miktarı kart üzerinde tutulur ve "Sahaya Çıkar" işlemi her
seferinde bir ``stock_issues`` satırı yazıp miktarı düşer.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from db.base import Base

#: Miktarlar üç ondalık basamağa kadar tutulur (2.5 litre, 0.250 kg, ...).
QUANTITY_SCALE = Decimal("0.001")


def quantize_quantity(value) -> Decimal:
    """Round any numeric input to the database's three-decimal scale."""

    return Decimal(str(value or 0)).quantize(QUANTITY_SCALE)


class StockModel(Base):
    """Elle tutulan stok kartı (malzeme + kalan miktar)."""

    __tablename__ = "stock_items"
    __table_args__ = (
        CheckConstraint(
            "quantity >= 0",
            name="ck_stock_items_quantity_not_negative",
        ),
        Index("ix_stock_items_name", "name"),
    )

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(255), nullable=False)
    unit = Column(String(20), nullable=False)

    #: Kart üzerindeki güncel miktar.  Çıkışlarda düşer, düzenlemede
    #: kullanıcı sayım sonucunu doğrudan yazabilir.
    quantity = Column(
        Numeric(precision=12, scale=3),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
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
        nullable=True,
    )

    issues = relationship(
        "StockIssueModel",
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    created_by = relationship("UserModel")

    def __str__(self) -> str:
        return f"{self.name} ({self.quantity} {self.unit})"


class StockIssueModel(Base):
    """Sahaya çıkan (stoktan düşülen) malzeme kaydı."""

    __tablename__ = "stock_issues"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_stock_issues_quantity_positive",
        ),
        Index("ix_stock_issues_date_item", "issue_date", "stock_item_id"),
    )

    id = Column(Integer, primary_key=True, index=True)

    stock_item_id = Column(
        Integer,
        ForeignKey("stock_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    quantity = Column(Numeric(precision=12, scale=3), nullable=False)

    issue_date = Column(
        Date,
        nullable=False,
        default=date.today,
        server_default=func.current_date(),
        index=True,
    )

    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: Malzemeyi teslim alan kişi (mekanik, operatör, ...).
    given_to = Column(String(150), nullable=True)

    note = Column(Text, nullable=True)

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

    item = relationship("StockModel", back_populates="issues")
    machine = relationship("AllMachineModel")
    created_by = relationship("UserModel")

    def __str__(self) -> str:
        return f"{self.stock_item_id} - {self.issue_date} - {self.quantity}"
