# routers/repair_router.py
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.repair_repository import RepairRepository
from schemas.repair_schemas import (
    PaginatedRepairSchema,
    RepairCancelSchema,
    RepairCloseSchema,
    RepairCreateSchema,
    RepairEstimateSchema,
    RepairFetchItemSchema,
    RepairMachineOptionSchema,
    RepairNoteCreateSchema,
    RepairReopenSchema,
    RepairStatusCode,
    RepairSummarySchema,
    RepairTypeItemSchema,
    RepairUpdateSchema,
)

# Every repair endpoint requires a valid access token. Write endpoints also
# enforce require_write_permission.
router = APIRouter(dependencies=[Depends(get_current_user)])


# =========================================================
# READ
# =========================================================

@router.get("/fetch_repairs", response_model=PaginatedRepairSchema)
async def fetch_repairs(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    status: Optional[RepairStatusCode] = Query(None),
    repair_type_id: Optional[int] = Query(None),
    garage_service_id: Optional[int] = Query(None),
    territory_id: Optional[int] = Query(None),
    type_id: Optional[int] = Query(None),
    company_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    overdue: Optional[bool] = Query(None),
    due_soon: Optional[bool] = Query(None),
):
    try:
        return await RepairRepository(db).fetch_paginated(
            limit=limit,
            offset=offset,
            search=search,
            status=status,
            repair_type_id=repair_type_id,
            garage_service_id=garage_service_id,
            territory_id=territory_id,
            type_id=type_id,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            overdue=overdue,
            due_soon=due_soon,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tamir listesi getirilemedi: {e}")


@router.get("/summary", response_model=RepairSummarySchema)
async def fetch_repair_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await RepairRepository(db).get_summary()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tamir özeti getirilemedi: {e}")


@router.get("/repair_types", response_model=list[RepairTypeItemSchema])
async def fetch_repair_types(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await RepairRepository(db).get_repair_types()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Tamir tipleri getirilemedi: {e}"
        )


@router.get("/machines", response_model=list[RepairMachineOptionSchema])
async def fetch_repair_machine_options(
    db: Annotated[AsyncSession, Depends(get_db)],
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(20, ge=1, le=50),
):
    try:
        return await RepairRepository(db).get_machine_options(
            search=search,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Makine listesi getirilemedi: {e}"
        )


@router.get("/estimate/{repair_type_id}", response_model=RepairEstimateSchema)
async def fetch_repair_estimate(
    repair_type_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await RepairRepository(db).get_estimate(repair_type_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Tahmini çıkış tarihi hesaplanamadı: {e}"
        )


@router.get(
    "/history/{machine_id}",
    response_model=list[RepairFetchItemSchema],
)
async def fetch_repair_history(
    machine_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await RepairRepository(db).get_history(machine_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tamir geçmişi getirilemedi: {e}")


@router.get("/{repair_id}", response_model=RepairFetchItemSchema)
async def fetch_repair_detail(
    repair_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await RepairRepository(db).get_detail(repair_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tamir kaydı getirilemedi: {e}")


# =========================================================
# WRITE
# =========================================================

@router.post(
    "/quick_open/{machine_id}",
    response_model=RepairFetchItemSchema,
)
async def quick_open_repair(
    machine_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await RepairRepository(db).quick_open_repair(
            machine_id, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Makine tamire alınamadı: {e}"
        )


@router.post("/create", response_model=RepairFetchItemSchema, status_code=201)
async def create_repair(
    data: RepairCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await RepairRepository(db).create_repair(data, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tamir kaydı oluşturulamadı: {e}")


@router.put("/{repair_id}", response_model=RepairFetchItemSchema)
async def update_repair(
    repair_id: int,
    data: RepairUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await RepairRepository(db).update_repair(
            repair_id, data, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tamir kaydı güncellenemedi: {e}")


@router.post("/{repair_id}/close", response_model=RepairFetchItemSchema)
async def close_repair(
    repair_id: int,
    data: RepairCloseSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await RepairRepository(db).close_repair(
            repair_id, data, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tamir tamamlanamadı: {e}")


@router.post("/{repair_id}/cancel", response_model=RepairFetchItemSchema)
async def cancel_repair(
    repair_id: int,
    data: RepairCancelSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await RepairRepository(db).cancel_repair(
            repair_id, data, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tamir iptal edilemedi: {e}")


@router.post("/{repair_id}/reopen", response_model=RepairFetchItemSchema)
async def reopen_repair(
    repair_id: int,
    data: RepairReopenSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await RepairRepository(db).reopen_repair(
            repair_id, data, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tamir yeniden açılamadı: {e}")


@router.post("/{repair_id}/notes", response_model=RepairFetchItemSchema)
async def add_repair_note(
    repair_id: int,
    data: RepairNoteCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await RepairRepository(db).add_note(
            repair_id, data, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Not eklenemedi: {e}")
