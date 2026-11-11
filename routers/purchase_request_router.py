# routers/purchase_request_router.py
"""API for purchase requests ("Satın Alma Talepleri").

Two resources share this router because the UI shows them as two tabs of one
page: spare-part requests (with their part rows) and service/hizmet requests.

Every endpoint requires a valid access token; writes also enforce
``require_write_permission`` exactly like the repair and maintenance modules.
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
from models.purchase_request_model import MAX_DOCUMENT_BYTES
from models.user_model import UserModel
from repositories.pdf_documents import content_disposition
from repositories.purchase_request_repository import (
    PurchaseRequestRepository,
    validate_status_filter,
)
from schemas.purchase_request_schemas import (
    PaginatedServiceRequestSchema,
    PaginatedSparePartRequestSchema,
    PurchaseMachineOptionSchema,
    RequestTypeOptionSchema,
    ServiceRequestCreateSchema,
    ServiceRequestSchema,
    SparePartRequestCreateSchema,
    SparePartRequestSchema,
    SparePartStatusUpdateSchema,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


# =========================================================
# SPARE PART REQUESTS — READ
# =========================================================

@router.get("/spare-parts", response_model=PaginatedSparePartRequestSchema)
async def fetch_spare_part_requests(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    identification_no: Optional[str] = Query(None, max_length=50),
    status: Optional[str] = Query(None, max_length=20),
    territory_id: Optional[int] = Query(None),
    request_type_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    try:
        return await PurchaseRequestRepository(db).fetch_spare_part_requests(
            limit=limit,
            offset=offset,
            search=search,
            identification_no=identification_no,
            status=validate_status_filter(status),
            territory_id=territory_id,
            request_type_id=request_type_id,
            date_from=date_from,
            date_to=date_to,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Yedek parça talepleri getirilemedi: {e}"
        )


@router.get("/spare-part-types", response_model=list[RequestTypeOptionSchema])
async def fetch_spare_part_types(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await PurchaseRequestRepository(db).list_request_types()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Talep türleri getirilemedi: {e}"
        )


@router.get("/machines", response_model=list[PurchaseMachineOptionSchema])
async def fetch_purchase_request_machines(
    db: Annotated[AsyncSession, Depends(get_db)],
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(20, ge=1, le=50),
):
    try:
        return await PurchaseRequestRepository(db).get_machine_options(
            search=search, limit=limit
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Makine listesi getirilemedi: {e}"
        )


# =========================================================
# SPARE PART REQUESTS — WRITE
# =========================================================

@router.post(
    "/spare-parts", response_model=SparePartRequestSchema, status_code=201
)
async def create_spare_part_request(
    data: SparePartRequestCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await PurchaseRequestRepository(db).create_spare_part_request(
            data, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Yedek parça talebi oluşturulamadı: {e}"
        )


@router.patch(
    "/spare-parts/{request_id}/status",
    response_model=SparePartRequestSchema,
)
async def update_spare_part_status(
    request_id: int,
    data: SparePartStatusUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await PurchaseRequestRepository(db).update_spare_status(
            request_id, data.status
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Durum güncellenemedi: {e}")


@router.delete("/spare-parts/{request_id}", status_code=204)
async def delete_spare_part_request(
    request_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        await PurchaseRequestRepository(db).delete_spare_part_request(request_id)
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Yedek parça talebi silinemedi: {e}"
        )


# =========================================================
# SPARE PART DOCUMENTS (PDF)
# =========================================================

@router.post(
    "/spare-parts/{request_id}/documents",
    response_model=SparePartRequestSchema,
    status_code=201,
)
async def upload_spare_part_document(
    request_id: int,
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

        return await PurchaseRequestRepository(db).add_document(
            request_id,
            file_name=file.filename,
            content_type=file.content_type,
            data=data,
            user_id=current_user.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evrak yüklenemedi: {e}")


@router.get("/spare-parts/{request_id}/documents/{document_id}")
async def fetch_spare_part_document(
    request_id: int,
    document_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    download: bool = Query(False),
):
    """Stream a PDF; ``download=true`` forces the browser save dialog."""

    try:
        document = await PurchaseRequestRepository(db).get_document(
            request_id, document_id
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
    "/spare-parts/{request_id}/documents/{document_id}",
    response_model=SparePartRequestSchema,
)
async def delete_spare_part_document(
    request_id: int,
    document_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await PurchaseRequestRepository(db).delete_document(
            request_id, document_id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evrak silinemedi: {e}")


# =========================================================
# SERVICE REQUESTS
# =========================================================

@router.get("/service-requests", response_model=PaginatedServiceRequestSchema)
async def fetch_service_requests(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    identification_no: Optional[str] = Query(None, max_length=50),
    company_name: Optional[str] = Query(None, max_length=255),
    service_description: Optional[str] = Query(None, max_length=100),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    try:
        return await PurchaseRequestRepository(db).fetch_service_requests(
            limit=limit,
            offset=offset,
            search=search,
            identification_no=identification_no,
            company_name=company_name,
            service_description=service_description,
            date_from=date_from,
            date_to=date_to,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Servis/hizmet talepleri getirilemedi: {e}"
        )


@router.post(
    "/service-requests", response_model=ServiceRequestSchema, status_code=201
)
async def create_service_request(
    data: ServiceRequestCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await PurchaseRequestRepository(db).create_service_request(
            data, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Servis/hizmet talebi oluşturulamadı: {e}"
        )


@router.delete("/service-requests/{request_id}", status_code=204)
async def delete_service_request(
    request_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        await PurchaseRequestRepository(db).delete_service_request(request_id)
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Servis/hizmet talebi silinemedi: {e}"
        )
