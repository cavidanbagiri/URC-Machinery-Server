# routers/isg_router.py
"""API for the ISG (İş Sağlığı ve Güvenliği) nonconformity page.

Read endpoints only need a valid access token; every write endpoint requires
write permission, exactly like the other fleet modules.  The stat cards are one
extra read endpoint (``GET /overview``) so the list request stays cheap.
"""

from datetime import date
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.isg_model import ISG_RESPONSIBLES, MAX_EVIDENCE_BYTES
from models.user_model import UserModel
from repositories.isg_repository import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    IsgRepository,
)
from repositories.pdf_documents import content_disposition
from schemas.isg_schemas import (
    IsgNonconformityCreateSchema,
    IsgNonconformityItemSchema,
    IsgNonconformityUpdateSchema,
    IsgOverviewSchema,
    IsgResponsiblesSchema,
    IsgStatusUpdateSchema,
    PaginatedIsgSchema,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


# =========================================================
# READ
# =========================================================

@router.get("/fetch_nonconformities", response_model=PaginatedIsgSchema)
async def fetch_isg_items(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = Query(None, max_length=20),
    severity: Optional[str] = Query(None, max_length=20),
    territory_id: Optional[int] = Query(None, gt=0),
    responsible_name: Optional[str] = Query(None, max_length=100),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    """Paged nonconformities with their evidence metadata."""

    try:
        return await IsgRepository(db).fetch_paginated(
            limit=limit,
            offset=offset,
            search=search,
            status=status,
            severity=severity,
            territory_id=territory_id,
            responsible_name=responsible_name,
            date_from=date_from,
            date_to=date_to,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ISG listesi getirilemedi: {e}",
        )


@router.get("/overview", response_model=IsgOverviewSchema)
async def fetch_isg_overview(db: Annotated[AsyncSession, Depends(get_db)]):
    """SRU/DCU opened + closed totals (the five stat cards)."""

    try:
        return await IsgRepository(db).fetch_overview()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ISG istatistikleri getirilemedi: {e}",
        )


@router.get("/responsibles", response_model=IsgResponsiblesSchema)
async def fetch_isg_responsibles():
    """The fixed "Sorumlu" list; the schema validates against the same tuple."""

    return {"items": list(ISG_RESPONSIBLES)}


# =========================================================
# WRITE
# =========================================================

@router.post("/create", response_model=IsgNonconformityItemSchema, status_code=201)
async def create_isg_item(
    payload: IsgNonconformityCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Open one nonconformity (tarih, açıklama, önem, durum, şantiye, sorumlu)."""

    try:
        return await IsgRepository(db).create(payload, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ISG kaydı oluşturulamadı: {e}",
        )


@router.put("/update/{item_id}", response_model=IsgNonconformityItemSchema)
async def update_isg_item(
    item_id: int,
    payload: IsgNonconformityUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Replace the six editable fields of one row."""

    try:
        return await IsgRepository(db).update(item_id, payload, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ISG kaydı güncellenemedi: {e}",
        )


@router.patch("/{item_id}/status", response_model=IsgNonconformityItemSchema)
async def update_isg_status(
    item_id: int,
    payload: IsgStatusUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Status dropdown of the table: ``acik`` <-> ``kapali``."""

    try:
        return await IsgRepository(db).set_status(
            item_id, payload.status, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ISG durumu güncellenemedi: {e}",
        )


@router.delete("/delete/{item_id}", status_code=204)
async def delete_isg_item(
    item_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Delete one row; its evidence files are dropped by ``ON DELETE CASCADE``."""

    try:
        await IsgRepository(db).delete(item_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ISG kaydı silinemedi: {e}",
        )


# =========================================================
# EVIDENCE (PDF / photo)
# =========================================================

@router.post(
    "/{item_id}/attachments",
    response_model=IsgNonconformityItemSchema,
    status_code=201,
)
async def upload_isg_attachment(
    item_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
    file: Annotated[UploadFile, File(description="PDF veya fotoğraf")],
):
    try:
        try:
            # Read one byte past the limit so an oversized upload is detected
            # without buffering an unbounded file in memory.
            data = await file.read(MAX_EVIDENCE_BYTES + 1)
        finally:
            await file.close()

        return await IsgRepository(db).add_attachment(
            item_id,
            file_name=file.filename,
            content_type=file.content_type,
            data=data,
            user_id=current_user.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Kanıt yüklenemedi: {e}")


@router.get("/{item_id}/attachments/{attachment_id}")
async def fetch_isg_attachment(
    item_id: int,
    attachment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    download: bool = Query(False),
):
    """Stream the PDF/photo; ``download=true`` forces the save dialog."""

    try:
        attachment = await IsgRepository(db).get_attachment(
            item_id, attachment_id
        )
        return Response(
            content=attachment.file_data,
            media_type=attachment.content_type or "application/pdf",
            headers={
                "Content-Disposition": content_disposition(
                    attachment.file_name, download=download
                ),
                "Cache-Control": "private, no-store",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Kanıt açılamadı: {e}")


@router.delete(
    "/{item_id}/attachments/{attachment_id}",
    response_model=IsgNonconformityItemSchema,
)
async def delete_isg_attachment(
    item_id: int,
    attachment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await IsgRepository(db).delete_attachment(item_id, attachment_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Kanıt silinemedi: {e}")
