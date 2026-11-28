# models/document_tracking_model.py
"""Per-machine document expiry dates for the Evrak Takip Tablosu.

One row belongs to one machine. Every date is nullable so the table can be
filled in gradually; the values are hand-entered and never affect maintenance,
repair or machine status.
"""

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base

#: Date columns updated from the table. Keep this tuple in sync with the
#: Pydantic schema and the frontend form.
DOCUMENT_DATE_FIELDS = (
    "compulsory_traffic_insurance_date",
    "kasko_date",
    "inspection_end_date",
    "passenger_transport_license_date",
    "partial_technical_inspection_date",
    "full_technical_inspection_date",
    "hazardous_production_facility_date",
    "leasing_date",
    "equipment_control_date",
)


class MachineDocumentTrackingModel(Base):
    __tablename__ = "machine_document_tracking"

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Zorunlu Trafik
    compulsory_traffic_insurance_date = Column(Date, nullable=True)
    # Kasko
    kasko_date = Column(Date, nullable=True)
    # Muayene (Bitiş Tarihi)
    inspection_end_date = Column(Date, nullable=True)
    # Yolcu Taşıma Lisansı
    passenger_transport_license_date = Column(Date, nullable=True)
    # Kısmi Teknik Muayene
    partial_technical_inspection_date = Column(Date, nullable=True)
    # Tam Teknik Muayene
    full_technical_inspection_date = Column(Date, nullable=True)
    # Tehlikeli Üretim Tesisi
    hazardous_production_facility_date = Column(Date, nullable=True)
    # Lizing
    leasing_date = Column(Date, nullable=True)
    # Ekipman Kontrolü
    equipment_control_date = Column(Date, nullable=True)

    updated_by_id = Column(
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
        nullable=False,
    )

    machine = relationship("AllMachineModel", back_populates="document_tracking")
    updated_by = relationship("UserModel")

    def __str__(self) -> str:
        return f"Evrak takibi - makine {self.machine_id}"


__all__ = ["DOCUMENT_DATE_FIELDS", "MachineDocumentTrackingModel"]
