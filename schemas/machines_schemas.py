# schemas/machines_schemas.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# =========================================================
# TERRITORY
# =========================================================

class CreateTerritorySchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class FetchTerritorySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


# =========================================================
# TYPE TRANSPORT
# =========================================================

class CreateTypeTransportSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class FetchTypeTransportSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


# =========================================================
# SUB TYPE TRANSPORT
# =========================================================

class CreateSubTypeTransportSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class FetchSubTypeTransportSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


# =========================================================
# CAR MARK
# =========================================================

class CreateCarMarkSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class FetchCarMarkSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


# =========================================================
# CAR MODEL
# =========================================================

class CreateCarModelSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class FetchCarModelSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


# =========================================================
# COMPANY
# =========================================================

class CreateCompanySchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class FetchCompanySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


# schemas/machines_schemas.py (əlavə)

# =========================================================
# ALL MACHINE
# =========================================================

class CreateAllMachineSchema(BaseModel):
    identification_no: Optional[str] = Field(None, max_length=100)
    vin_no: Optional[str] = Field(None, max_length=100)
    technical_character: Optional[str] = Field(None, max_length=500)
    production_year: Optional[datetime] = None
    weight: Optional[float] = None
    dimension: Optional[str] = Field(None, max_length=100)
    engine_power: Optional[str] = Field(None, max_length=100)
    engine_mark_model: Optional[str] = Field(None, max_length=255)
    engine_identity: Optional[str] = Field(None, max_length=255)


    territory_id: Optional[int] = None
    type_id: Optional[int] = None
    subtype_id: Optional[int] = None
    car_mark_id: Optional[int] = None
    car_model_id: Optional[int] = None
    company_id: Optional[int] = None
    status_id: Optional[int] = 1        # ← BURADA OLmalıdır


class UpdateAllMachineSchema(CreateAllMachineSchema):
    """Update üçün eyni sahələr (hamısı optional)."""
    pass


class FetchAllMachineSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    identification_no: Optional[str]
    vin_no: Optional[str]
    technical_character: Optional[str]
    production_year: Optional[datetime]
    weight: Optional[float]
    dimension: Optional[str]
    engine_power: Optional[str]
    engine_mark_model: Optional[str]
    engine_identity: Optional[str]

    territory_id: Optional[int]
    type_id: Optional[int]
    subtype_id: Optional[int]
    car_mark_id: Optional[int]
    car_model_id: Optional[int]
    company_id: Optional[int]
    created_by_id: Optional[int]
    created_at: Optional[datetime]
    status_id: int


class PaginatedAllMachineSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[FetchAllMachineSchema]


# schemas/machines_schemas.py (əlavə)

# =========================================================
# CAR STATUS
# =========================================================

class CreateCarStatusSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str = Field("gray", max_length=20)
    description: Optional[str] = Field(None, max_length=255)


class UpdateCarStatusSchema(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    color: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = Field(None, max_length=255)


class FetchCarStatusSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str
    description: Optional[str]