# schemas/document_tracking_schemas.py
"""Pydantic schemas for the document tracking table."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DocumentTrackingUpdateSchema(BaseModel):
    """Full row update. Every date may be cleared by sending ``null``."""

    model_config = ConfigDict(extra="forbid")

    compulsory_traffic_insurance_date: Optional[date] = None
    kasko_date: Optional[date] = None
    inspection_end_date: Optional[date] = None
    passenger_transport_license_date: Optional[date] = None
    partial_technical_inspection_date: Optional[date] = None
    full_technical_inspection_date: Optional[date] = None
    hazardous_production_facility_date: Optional[date] = None
    leasing_date: Optional[date] = None
    equipment_control_date: Optional[date] = None


class DocumentTrackingItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    machine_id: int
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None

    territory_id: Optional[int] = None
    type_id: Optional[int] = None
    car_mark_id: Optional[int] = None
    car_model_id: Optional[int] = None

    territory_name: Optional[str] = None
    type_name: Optional[str] = None
    car_mark_name: Optional[str] = None
    car_model_name: Optional[str] = None

    compulsory_traffic_insurance_date: Optional[date] = None
    kasko_date: Optional[date] = None
    inspection_end_date: Optional[date] = None
    passenger_transport_license_date: Optional[date] = None
    partial_technical_inspection_date: Optional[date] = None
    full_technical_inspection_date: Optional[date] = None
    hazardous_production_facility_date: Optional[date] = None
    leasing_date: Optional[date] = None
    equipment_control_date: Optional[date] = None

    updated_by_id: Optional[int] = None
    updated_by_name: Optional[str] = None
    updated_at: Optional[datetime] = None


class PaginatedDocumentTrackingSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[DocumentTrackingItemSchema]


__all__ = [
    "DocumentTrackingItemSchema",
    "DocumentTrackingUpdateSchema",
    "PaginatedDocumentTrackingSchema",
]
