# routers/maintenance_router.py
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.maintenance_repository import MaintenanceRepository
from schemas.maintenance_schemas import (
    MaintenanceCompleteSchema,
    MaintenanceFetchItemSchema,
    MaintenanceHistoryItemSchema,
    MaintenanceReadingCreateSchema,
    MaintenanceSettingUpdateSchema,
    MaintenanceSortField,
    MaintenanceSortOrder,
    MaintenanceStatusCode,
    MaintenanceSummarySchema,
    PaginatedMaintenanceSchema,
    UsageUnit,
)

# Every maintenance endpoint requires a valid access token. Write endpoints
# additionally enforce require_write_permission.
router = APIRouter(dependencies=[Depends(get_current_user)])


# =========================================================
# READ
# =========================================================




@router.get(
    "/",
    response_model = {},
    status_code=200
)
async def fetch_dummy_data():
    try:
        return {"response":"dummy_data"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dummy Data getirilemedi: {e}")

@router.get("/fetch_maintenance", response_model=PaginatedMaintenanceSchema)
async def fetch_maintenance(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    usage_unit: Optional[UsageUnit] = Query(None),
    status: Optional[MaintenanceStatusCode] = Query(None),
    has_plan: Optional[bool] = Query(None),
    is_active: Optional[bool] = Query(None),
    include_inactive: bool = Query(False),
    territory_id: Optional[int] = Query(None),
    type_id: Optional[int] = Query(None),
    company_id: Optional[int] = Query(None),
    sort_by: Optional[MaintenanceSortField] = Query(None),
    sort_order: Optional[MaintenanceSortOrder] = Query(None),
):
    try:
        return await MaintenanceRepository(db).fetch_paginated(
            limit=limit,
            offset=offset,
            search=search,
            usage_unit=usage_unit,
            status=status,
            has_plan=has_plan,
            is_active=is_active,
            include_inactive=include_inactive,
            territory_id=territory_id,
            type_id=type_id,
            company_id=company_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bakım listesi getirilemedi: {e}")


@router.get("/summary", response_model=MaintenanceSummarySchema)
async def fetch_maintenance_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await MaintenanceRepository(db).get_summary()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bakım özeti getirilemedi: {e}")


@router.get(
    "/history/{machine_id}",
    response_model=list[MaintenanceHistoryItemSchema],
)
async def fetch_maintenance_history(
    machine_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        return await MaintenanceRepository(db).get_history(
            machine_id,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bakım geçmişi getirilemedi: {e}")


# =========================================================
# WRITE
# =========================================================

@router.put(
    "/settings/{machine_id}",
    response_model=MaintenanceFetchItemSchema,
    dependencies=[Depends(require_write_permission)],
)
async def upsert_maintenance_settings(
    machine_id: int,
    data: MaintenanceSettingUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await MaintenanceRepository(db).upsert_settings(machine_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bakım planı kaydedilemedi: {e}")


@router.post(
    "/reading/{machine_id}",
    response_model=MaintenanceFetchItemSchema,
)
async def add_maintenance_reading(
    machine_id: int,
    data: MaintenanceReadingCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await MaintenanceRepository(db).record_reading(
            machine_id,
            data,
            current_user.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sayaç kaydı eklenemedi: {e}")


@router.post(
    "/complete/{machine_id}",
    response_model=MaintenanceFetchItemSchema,
)
async def complete_maintenance(
    machine_id: int,
    data: MaintenanceCompleteSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await MaintenanceRepository(db).complete_maintenance(
            machine_id,
            data,
            current_user.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bakım tamamlanamadı: {e}")

