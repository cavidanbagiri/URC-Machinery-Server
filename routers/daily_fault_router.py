# routers/daily_fault_router.py
"""API for daily (quick) faults and their PDF documents."""

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.daily_fault_model import MAX_DOCUMENT_BYTES
from models.user_model import UserModel
from repositories.daily_fault_repository import (
    DailyFaultRepository,
    content_disposition,
)
from schemas.daily_fault_schemas import (
    DailyFaultCreateSchema,
    DailyFaultItemSchema,
    DailyFaultMachineOptionSchema,
    PaginatedDailyFaultSchema,
)

# Every endpoint requires a valid access token. Write endpoints also enforce
# require_write_permission, exactly like the repair and maintenance modules.
router = APIRouter(dependencies=[Depends(get_current_user)])


# =========================================================
# READ
# =========================================================

@router.get("/fetch_daily_faults", response_model=PaginatedDailyFaultSchema)
async def fetch_daily_faults(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    territory_id: Optional[int] = Query(None),
    repair_type_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    try:
        return await DailyFaultRepository(db).fetch_paginated(
            limit=limit,
            offset=offset,
            search=search,
            territory_id=territory_id,
            repair_type_id=repair_type_id,
            date_from=date_from,
            date_to=date_to,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Günlük arıza listesi getirilemedi: {e}"
        )


@router.get("/machines", response_model=list[DailyFaultMachineOptionSchema])
async def fetch_daily_fault_machines(
    db: Annotated[AsyncSession, Depends(get_db)],
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(20, ge=1, le=50),
):
    try:
        return await DailyFaultRepository(db).get_machine_options(
            search=search, limit=limit
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Makine listesi getirilemedi: {e}"
        )


# =========================================================
# WRITE
# =========================================================

@router.post("/create", response_model=DailyFaultItemSchema, status_code=201)
async def create_daily_fault(
    data: DailyFaultCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await DailyFaultRepository(db).create_fault(data, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Günlük arıza kaydı oluşturulamadı: {e}"
        )


# =========================================================
# PDF DOCUMENTS
# =========================================================

@router.post(
    "/{fault_id}/documents",
    response_model=DailyFaultItemSchema,
    status_code=201,
)
async def upload_daily_fault_document(
    fault_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
    file: Annotated[UploadFile, File(description="PDF evrak")],
):
    try:
        try:
            # Read one byte past the limit so oversized files are detected
            # without buffering an unbounded upload in memory.
            data = await file.read(MAX_DOCUMENT_BYTES + 1)
        finally:
            await file.close()

        return await DailyFaultRepository(db).add_document(
            fault_id,
            file_name=file.filename,
            content_type=file.content_type,
            data=data,
            user_id=current_user.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evrak yüklenemedi: {e}")


@router.get("/{fault_id}/documents/{document_id}")
async def fetch_daily_fault_document(
    fault_id: int,
    document_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    download: bool = Query(False),
):
    """Stream a PDF; ``download=true`` forces the browser save dialog."""

    try:
        document = await DailyFaultRepository(db).get_document(
            fault_id, document_id
        )
        return Response(
            content=document.file_data,
            media_type=document.content_type or "application/pdf",
            headers={
                "Content-Disposition": content_disposition(
                    document.file_name, download=download
                ),
                "Cache-Control": "private, no-store",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evrak açılamadı: {e}")


@router.delete(
    "/{fault_id}/documents/{document_id}",
    response_model=DailyFaultItemSchema,
)
async def delete_daily_fault_document(
    fault_id: int,
    document_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await DailyFaultRepository(db).delete_document(
            fault_id, document_id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evrak silinemedi: {e}")

