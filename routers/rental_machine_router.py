# routers/rental_machine_router.py
"""API for the Kiralık Makine (rented machine) agreements."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.rental_machine_repository import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    RentalMachineRepository,
)
from schemas.rental_machine_schemas import (
    PaginatedRentalMachinesSchema,
    RentalMachineCreateSchema,
    RentalMachineItemSchema,
    RentalMachineUpdateSchema,
)

# Reading needs a valid access token; create / update / delete additionally
# require write permission, exactly like the other fleet modules.
router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get(
    "/fetch_rental_machines",
    response_model=PaginatedRentalMachinesSchema,
)
async def fetch_rental_machines(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = Query(None, max_length=20),
):
    """Paged rental rows with the status derived from their dates."""

    try:
        return await RentalMachineRepository(db).fetch_paginated(
            limit=limit,
            offset=offset,
            search=search,
            status=status,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Kiralık makine listesi getirilemedi: {e}",
        )


@router.post("/create", response_model=RentalMachineItemSchema, status_code=201)
async def create_rental_machine(
    payload: RentalMachineCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Save one rental agreement (ekipman, firma, şantiye, iki tarih)."""

    try:
        return await RentalMachineRepository(db).create(
            payload,
            current_user.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Kiralık makine kaydı kaydedilemedi: {e}",
        )


@router.put("/update/{rental_id}", response_model=RentalMachineItemSchema)
async def update_rental_machine(
    rental_id: int,
    payload: RentalMachineUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Replace the five editable fields of one rental row."""

    try:
        return await RentalMachineRepository(db).update(rental_id, payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Kiralık makine kaydı güncellenemedi: {e}",
        )


@router.delete("/delete/{rental_id}", status_code=204)
async def delete_rental_machine(
    rental_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Delete one rental row.

    The diesel rows of the rental live in ``machine_rental_fuel_logs`` and are
    removed by the database (``ON DELETE CASCADE``), so deleting an agreement
    also clears its fuel ledger.
    """

    try:
        await RentalMachineRepository(db).delete(rental_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Kiralık makine kaydı silinemedi: {e}",
        )
