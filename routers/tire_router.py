# routers/tire_router.py
"""API for tire changes (lastik değişimi) and their PDF papers."""

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.tire_model import MAX_TIRE_DOCUMENT_BYTES
from models.user_model import UserModel
from repositories.pdf_documents import content_disposition
from repositories.tire_position_repository import TirePositionRepository
from repositories.tire_repository import TireRepository
from schemas.tire_schemas import (
    PaginatedTireChangeSchema,
    TireChangeCreateSchema,
    TireChangeItemSchema,
    TireMachineOptionSchema,
    TirePositionCreateSchema,
    TirePositionSchema,
    TireSummarySchema,
)

# Every endpoint requires a valid access token. Write endpoints also enforce
# require_write_permission, exactly like the repair and daily fault modules.
router = APIRouter(dependencies=[Depends(get_current_user)])


# =========================================================
# READ
# =========================================================

@router.get("/fetch_tires", response_model=PaginatedTireChangeSchema)
async def fetch_tires(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    position: Optional[str] = Query(None, max_length=50),
    machine_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    try:
        return await TireRepository(db).fetch_paginated(
            limit=limit,
            offset=offset,
            search=search,
            position=position,
            machine_id=machine_id,
            date_from=date_from,
            date_to=date_to,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Lastik listesi getirilemedi: {e}"
        )


@router.get("/summary", response_model=TireSummarySchema)
async def fetch_tire_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Counters for the cards above the table (total / changed today)."""

    try:
        return await TireRepository(db).get_summary()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Lastik özeti getirilemedi: {e}"
        )


@router.get("/machines", response_model=list[TireMachineOptionSchema])
async def fetch_tire_machines(
    db: Annotated[AsyncSession, Depends(get_db)],
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(20, ge=1, le=50),
):
    try:
        return await TireRepository(db).get_machine_options(
            search=search, limit=limit
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Makine listesi getirilemedi: {e}"
        )


@router.get("/{tire_id}/history", response_model=list[TireChangeItemSchema])
async def fetch_tire_history(
    tire_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=20),
):
    """Older changes of the same machine + position ("eski kayıtlar")."""

    try:
        return await TireRepository(db).get_history(tire_id, limit=limit)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Lastik geçmişi getirilemedi: {e}"
        )


# =========================================================
# WRITE
# =========================================================

@router.post("/create", response_model=TireChangeItemSchema, status_code=201)
async def create_tire_change(
    data: TireChangeCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await TireRepository(db).create_change(data, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Lastik kaydı oluşturulamadı: {e}"
        )


# =========================================================
# PDF DOCUMENTS
# =========================================================

@router.post(
    "/{tire_id}/documents",
    response_model=TireChangeItemSchema,
    status_code=201,
)
async def upload_tire_document(
    tire_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
    file: Annotated[UploadFile, File(description="PDF evrak")],
):
    try:
        try:
            # Read one byte past the limit so oversized files are detected
            # without buffering an unbounded upload in memory.
            data = await file.read(MAX_TIRE_DOCUMENT_BYTES + 1)
        finally:
            await file.close()

        return await TireRepository(db).add_document(
            tire_id,
            file_name=file.filename,
            content_type=file.content_type,
            data=data,
            user_id=current_user.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evrak yüklenemedi: {e}")


@router.get("/{tire_id}/documents/{document_id}")
async def fetch_tire_document(
    tire_id: int,
    document_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    download: bool = Query(False),
):
    """Stream a PDF; ``download=true`` forces the browser save dialog."""

    try:
        document = await TireRepository(db).get_document(tire_id, document_id)
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
    "/{tire_id}/documents/{document_id}",
    response_model=TireChangeItemSchema,
)
async def delete_tire_document(
    tire_id: int,
    document_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await TireRepository(db).delete_document(tire_id, document_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evrak silinemedi: {e}")


# =========================================================
# SETTINGS — TIRE POSITIONS (Ayarlar → Lastik Konumu)
# =========================================================

@router.get("/positions", response_model=list[TirePositionSchema])
async def fetch_tire_positions(db: Annotated[AsyncSession, Depends(get_db)]):
    """Suggestions shown in the form datalist and the column filter."""

    try:
        return await TirePositionRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Lastik konumları getirilemedi: {e}"
        )


@router.post(
    "/positions",
    status_code=201,
    response_model=TirePositionSchema,
    dependencies=[Depends(require_write_permission)],
)
async def create_tire_position(
    data: TirePositionCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await TirePositionRepository(db).create(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Lastik konumu oluşturulamadı: {e}"
        )


@router.put(
    "/positions/{position_id}",
    response_model=TirePositionSchema,
    dependencies=[Depends(require_write_permission)],
)
async def update_tire_position(
    position_id: int,
    data: TirePositionCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Rename a position; existing changes are moved to the new label."""

    try:
        return await TirePositionRepository(db).update(position_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Lastik konumu güncellenemedi: {e}"
        )


@router.delete(
    "/positions/{position_id}",
    status_code=204,
    dependencies=[Depends(require_write_permission)],
)
async def delete_tire_position(
    position_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await TirePositionRepository(db).delete(position_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Lastik konumu silinemedi: {e}"
        )
