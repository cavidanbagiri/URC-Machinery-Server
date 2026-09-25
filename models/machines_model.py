# models.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from db.base import Base


# =========================================================
# LOOKUP TABLES
# =========================================================

class TerritoryModel(Base):
    __tablename__ = "territories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)

    # Relationship to machines
    machines = relationship("AllMachineModel", back_populates="territory")

    def __str__(self):
        return f"{self.name}"


class TypeTransportModel(Base):
    __tablename__ = "type_transports"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)

    # Relationship to machines
    machines = relationship("AllMachineModel", back_populates="type_transport")

    def __str__(self):
        return f"{self.name}"


class SubTypeTransportModel(Base):
    __tablename__ = "sub_type_transports"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)

    # Relationship to machines
    machines = relationship("AllMachineModel", back_populates="sub_type_transport")

    def __str__(self):
        return f"{self.name}"


class CarMarkModel(Base):
    __tablename__ = "car_marks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)

    # Relationship to machines
    machines = relationship("AllMachineModel", back_populates="car_mark")

    def __str__(self):
        return f"{self.name}"


class CarModelModel(Base):
    __tablename__ = "car_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)

    # Relationship to machines
    machines = relationship("AllMachineModel", back_populates="car_model")

    def __str__(self):
        return f"{self.name}"


class CompanyModel(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)

    # Relationship to machines
    machines = relationship("AllMachineModel", back_populates="company")

    def __str__(self):
        return f"{self.name}"


# =========================================================
# MAIN MACHINE TABLE
# =========================================================

class AllMachineModel(Base):
    __tablename__ = "all_machines"

    id = Column(Integer, primary_key=True, index=True)

    # Basic Info
    identification_no = Column(String(100), nullable=True, index=True)
    vin_no = Column(String(100), nullable=True, unique=True, index=True)
    plate_no = Column(String(50), nullable=True, unique=True, index=True)  # ← YENİ
    technical_character = Column(String(500), nullable=True)

    # Production Year is mapped as DateTime per diagram, but usually Integer is better for Year.
    # Keeping DateTime as requested.
    production_year = Column(DateTime(timezone=True), nullable=True)

    # Technical Specs (Using Float for numeric values like weight/dimensions)
    weight = Column(Float, nullable=True)
    dimension = Column(String(100), nullable=True)  # Could be JSON or separate fields
    engine_power = Column(String(100), nullable=True)
    engine_mark_model = Column(String(255), nullable=True)
    engine_identity = Column(String(255), nullable=True)

    # Foreign Keys (Lookups)
    territory_id = Column(Integer, ForeignKey("territories.id"), nullable=True, index=True)
    type_id = Column(Integer, ForeignKey("type_transports.id"), nullable=True, index=True)
    subtype_id = Column(Integer, ForeignKey("sub_type_transports.id"), nullable=True, index=True)
    car_mark_id = Column(Integer, ForeignKey("car_marks.id"), nullable=True, index=True)
    car_model_id = Column(Integer, ForeignKey("car_models.id"), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)

    # YENİ — Status
    status_id = Column(
        Integer,
        ForeignKey("car_statuses.id"),
        nullable=False,
        default=1,
        server_default="1",
        index=True,
    )

    # Audit / User Link
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # =========================================================
    # RELATIONSHIPS
    # =========================================================

    territory = relationship("TerritoryModel", back_populates="machines")
    type_transport = relationship("TypeTransportModel", back_populates="machines")
    sub_type_transport = relationship("SubTypeTransportModel", back_populates="machines")
    car_mark = relationship("CarMarkModel", back_populates="machines")
    car_model = relationship("CarModelModel", back_populates="machines")
    company = relationship("CompanyModel", back_populates="machines")

    # YENİ — Status relationship
    status = relationship("CarStatusModel", back_populates="machines")

    # Relationship to User (assuming UserModel is defined in the same file or imported)
    creator = relationship("UserModel")

    def __str__(self):
        return f"{self.identification_no} - {self.vin_no}"




class CarStatusModel(Base):
    __tablename__ = "car_statuses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)
    color = Column(String(20), nullable=False, default="gray")
    description = Column(String(255), nullable=True)

    # Relationship
    machines = relationship("AllMachineModel", back_populates="status")

    def __str__(self):
        return f"{self.name}"