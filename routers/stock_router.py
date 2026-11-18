# routers/stock_router.py
"""Basit stok modülü API'si.

Sayfa iki sekmeden oluşur ve router da aynı şekilde ikiye ayrılır:

* ``/items`` — elle girilen malzeme kartları (ad, birim, miktar, not)
* ``/issues`` — "Sahaya Çıkanlar"; her çıkış karttan miktar düşer

Tüm uçlar geçerli bir erişim anahtarı ister; yazma işlemleri ayrıca
``require_write_permission`` ile korunur.
"""

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.stock_repository import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    StockRepository,
)
from schemas.stock_schemas import (
    StockIssueCreateSchema,
    StockIssueDeleteResultSchema,
    StockIssueListSchema,
    StockIssueSchema,
    StockItemCreateSchema,
    StockItemListSchema,
    StockItemSchema,
    StockItemUpdateSchema,
    StockSummarySchema,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


# =========================================================
# SUMMARY
# =========================================================

@router.get("/summary", response_model=StockSummarySchema)
async def fetch_summary(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await StockRepository(db).summary()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok özeti getirilemedi: {e}"
        )


# =========================================================
# STOCK ITEMS
# =========================================================

@router.get("/items", response_model=StockItemListSchema)
async def fetch_items(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
):
    try:
        return await StockRepository(db).fetch_items(
            limit=limit,
            offset=offset,
            search=search,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok listesi getirilemedi: {e}"
        )


@router.get("/items/{item_id}", response_model=StockItemSchema)
async def fetch_item(
    item_id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    try:
        return await StockRepository(db).get_item(item_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok kalemi getirilemedi: {e}"
        )


@router.post("/items", response_model=StockItemSchema, status_code=201)
async def create_item(
    data: StockItemCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await StockRepository(db).create_item(data, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok kalemi kaydedilemedi: {e}"
        )


@router.patch("/items/{item_id}", response_model=StockItemSchema)
async def update_item(
    item_id: int,
    data: StockItemUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[
        UserModel, Depends(require_write_permission)
    ],
):
    try:
        return await StockRepository(db).update_item(item_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok kalemi güncellenemedi: {e}"
        )


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[
        UserModel, Depends(require_write_permission)
    ],
):
    try:
        await StockRepository(db).delete_item(item_id)
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok kalemi silinemedi: {e}"
        )


# =========================================================
# ISSUES (SAHAYA ÇIKANLAR)
# =========================================================

@router.get("/issues", response_model=StockIssueListSchema)
async def fetch_issues(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    stock_item_id: Optional[int] = Query(None, gt=0),
    machine_id: Optional[int] = Query(None, gt=0),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    try:
        return await StockRepository(db).fetch_issues(
            limit=limit,
            offset=offset,
            search=search,
            stock_item_id=stock_item_id,
            machine_id=machine_id,
            date_from=date_from,
            date_to=date_to,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok çıkışları getirilemedi: {e}"
        )


@router.post("/issues", response_model=StockIssueSchema, status_code=201)
async def create_issue(
    data: StockIssueCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await StockRepository(db).create_issue(data, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok çıkışı kaydedilemedi: {e}"
        )


@router.delete(
    "/issues/{issue_id}", response_model=StockIssueDeleteResultSchema
)
async def delete_issue(
    issue_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[
        UserModel, Depends(require_write_permission)
    ],
):
    try:
        return await StockRepository(db).delete_issue(issue_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stok çıkışı silinemedi: {e}"
        )
