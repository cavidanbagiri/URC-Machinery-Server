# routers/fuel_log_router.py
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.fuel_log_repository import FuelLogRepository
from schemas.fuel_log_schemas import (
    FuelLogCreateSchema,
    FuelLogEntrySchema,
    FuelLogOverviewSchema,
)

# Every fuel-log endpoint requires a valid access token.  Writes additionally
# require the create/update permission value.
router = APIRouter(
    dependencies=[Depends(get_current_user)],
)


# =========================================================
# READ
# =========================================================


@router.get("/overview", response_model=FuelLogOverviewSchema)
async def fetch_fuel_log_overview(
    db: Annotated[AsyncSession, Depends(get_db)],
    fuel_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None, max_length=100),
):
    """Machines with the selected day's fuel totals and period summaries."""
    try:
        repository = FuelLogRepository(db)
        return await repository.fetch_overview(
            target_date=fuel_date,
            search=search,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Mazot dağılımı kayıtları getirilemedi: {e}",
        )


# =========================================================
# WRITE (INSERT ONLY)
# =========================================================


@router.post("/create", response_model=FuelLogEntrySchema, status_code=201)
async def create_fuel_log(
    payload: FuelLogCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Append a fuel distribution row.  Existing rows are never changed."""
    try:
        repository = FuelLogRepository(db)
        log = await repository.create_log(payload, current_user.id)

        name = " ".join(
            part for part in (current_user.firstname, current_user.lastname) if part
        ).strip()

        return FuelLogEntrySchema(
            id=log.id,
            machine_id=log.machine_id,
            fuel_date=log.fuel_date,
            liters=float(log.liters),
            given_by=log.given_by,
            note=log.note,
            entered_by_id=log.created_by_id,
            entered_by_name=name or None,
            created_at=log.created_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Mazot kaydı kaydedilemedi: {e}",
        )
