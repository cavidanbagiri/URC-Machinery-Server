# routers/warehouse_router.py
"""API for the warehouse ("Ambar / Depo") module.

The page has three tabs and so does this router:

* ``/stock`` — stock cards (create / edit / delete; the balance is read-only)
* ``/pending-receipts`` + ``/receipts`` — arrived purchasing rows and the
  "Depoya Al" action that turns them into ``giris`` movements
* ``/movements`` — the ledger, including the ``cikis`` (issue) lines

Every endpoint requires a valid access token; writes also enforce
``require_write_permission`` exactly like the repair and purchasing modules.
"""

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.warehouse_repository import (
    WarehouseRepository,
    validate_movement_type,
)
from schemas.warehouse_schemas import (
    PaginatedPendingReceiptSchema,
    PaginatedWarehouseItemSchema,
    PaginatedWarehouseMovementSchema,
    WarehouseItemCreateSchema,
    WarehouseItemSchema,
    WarehouseItemUpdateSchema,
    WarehouseMovementCreateSchema,
    WarehouseMovementSchema,
    WarehouseReceiptCreateSchema,
    WarehouseReceiptResultSchema,
    WarehouseSummarySchema,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


# =========================================================
# SUMMARY
# =========================================================

@router.get("/summary", response_model=WarehouseSummarySchema)
async def fetch_summary(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await WarehouseRepository(db).summary()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Depo özeti getirilemedi: {e}"
        )


# =========================================================
# STOCK CARDS
# =========================================================

@router.get("/stock", response_model=PaginatedWarehouseItemSchema)
async def fetch_stock(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    territory_id: Optional[int] = Query(None),
    low_stock: bool = Query(False),
):
    try:
        return await WarehouseRepository(db).fetch_stock(
            limit=limit,
            offset=offset,
            search=search,
            territory_id=territory_id,
            low_stock=low_stock,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok listesi getirilemedi: {e}"
        )


@router.get("/stock/{item_id}", response_model=WarehouseItemSchema)
async def fetch_stock_item(
    item_id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    try:
        return await WarehouseRepository(db).get_stock(item_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok kartı getirilemedi: {e}"
        )


@router.post("/stock", response_model=WarehouseItemSchema, status_code=201)
async def create_stock_item(
    data: WarehouseItemCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await WarehouseRepository(db).create_stock(data, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok kartı oluşturulamadı: {e}"
        )


@router.patch("/stock/{item_id}", response_model=WarehouseItemSchema)
async def update_stock_item(
    item_id: int,
    data: WarehouseItemUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await WarehouseRepository(db).update_stock(item_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok kartı güncellenemedi: {e}"
        )


@router.delete("/stock/{item_id}", status_code=204)
async def delete_stock_item(
    item_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        await WarehouseRepository(db).delete_stock(item_id)
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok kartı silinemedi: {e}"
        )


# =========================================================
# MOVEMENTS (giriş / çıkış)
# =========================================================

@router.get("/movements", response_model=PaginatedWarehouseMovementSchema)
async def fetch_movements(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    movement_type: Optional[str] = Query(None, max_length=10),
    item_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    try:
        return await WarehouseRepository(db).fetch_movements(
            limit=limit,
            offset=offset,
            search=search,
            movement_type=(
                validate_movement_type(movement_type) if movement_type else None
            ),
            item_id=item_id,
            date_from=date_from,
            date_to=date_to,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Hareketler getirilemedi: {e}"
        )


@router.post(
    "/movements", response_model=WarehouseMovementSchema, status_code=201
)
async def create_movement(
    data: WarehouseMovementCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await WarehouseRepository(db).create_movement(
            data, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Hareket kaydedilemedi: {e}"
        )


# =========================================================
# RECEIPTS (satın alma -> depo)
# =========================================================

@router.get(
    "/pending-receipts", response_model=PaginatedPendingReceiptSchema
)
async def fetch_pending_receipts(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
):
    try:
        return await WarehouseRepository(db).fetch_pending_receipts(
            limit=limit, offset=offset, search=search
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Depoya alınacak kalemler getirilemedi: {e}",
        )


@router.post(
    "/receipts", response_model=WarehouseReceiptResultSchema, status_code=201
)
async def receive_items(
    data: WarehouseReceiptCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await WarehouseRepository(db).receive_items(
            data, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Kalemler depoya alınamadı: {e}"
        )
