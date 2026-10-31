# models/garage_service_model.py
"""Garage service (garaj servisi) lookup used by repair records.

The list is maintained from Settings (``Merkez Garaj``, ``Dış Servis``...).
Every repair record points at the garage service that handles the machine; the
column on ``repair_records`` is nullable because repairs opened with the
quick-open flow (machine status modal) only carry the machine and a date.
"""

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from db.base import Base


class GarageServiceModel(Base):
    """Lookup managed from Settings (which garage repairs the machine)."""

    __tablename__ = "garage_services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)

    repair_records = relationship(
        "RepairRecordModel", back_populates="garage_service"
    )

    def __str__(self) -> str:
        return f"{self.name}"


__all__ = ["GarageServiceModel"]
