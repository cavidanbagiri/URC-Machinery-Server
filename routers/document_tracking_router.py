# routers/document_tracking_router.py
"""API for the Evrak Takip Tablosu (per-machine document dates)."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.document_tracking_repository import DocumentTrackingRepository
from schemas.document_tracking_schemas import (
    DocumentTrackingItemSchema,
    DocumentTrackingUpdateSchema,
    PaginatedDocumentTrackingSchema,
)

# Every endpoint requires a valid access token; the update additionally needs
# write permission, exactly like the maintenance and repair modules.
router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get(
    "/fetch_document_tracking",
    response_model=PaginatedDocumentTrackingSchema,
)
async def fetch_document_tracking(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    territory_id: Optional[int] = Query(None),
    type_id: Optional[int] = Query(None),
    car_mark_id: Optional[int] = Query(None),
    car_model_id: Optional[int] = Query(None),
):
    try:
        return await DocumentTrackingRepository(db).fetch_paginated(
            limit=limit,
            offset=offset,
            search=search,
            territory_id=territory_id,
            type_id=type_id,
            car_mark_id=car_mark_id,
            car_model_id=car_model_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Evrak takip listesi getirilemedi: {e}",
        )


@router.put("/update/{machine_id}", response_model=DocumentTrackingItemSchema)
async def update_document_tracking(
    machine_id: int,
    data: DocumentTrackingUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await DocumentTrackingRepository(db).upsert(
            machine_id,
            data,
            current_user.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Evrak bilgileri güncellenemedi: {e}",
        )
