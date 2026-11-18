# routers/meter_log_router.py
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.meter_log_repository import MeterLogRepository
from schemas.meter_log_schemas import (
    MeterLogCreateSchema,
    MeterLogEntrySchema,
    MeterLogOverviewSchema,
)

# Every meter-log endpoint requires a valid access token.  Writes additionally
# require the create/update permission value.
router = APIRouter(
    dependencies=[Depends(get_current_user)],
)


# =========================================================
# READ
# =========================================================


@router.get("/overview", response_model=MeterLogOverviewSchema)
async def fetch_meter_log_overview(
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(7, ge=1, le=31),
    end_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None, max_length=100),
):
    """Machines with their newest KM/hour reading plus a dated log window."""
    try:
        repository = MeterLogRepository(db)
        return await repository.fetch_overview(
            days=days,
            end_date=end_date,
            search=search,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"KM / motor saati kayıtları getirilemedi: {e}",
        )


# =========================================================
# WRITE (INSERT ONLY)
# =========================================================


@router.post("/create", response_model=MeterLogEntrySchema, status_code=201)
async def create_meter_log(
    payload: MeterLogCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Append a reading.  Existing rows are never updated or deleted."""
    try:
        repository = MeterLogRepository(db)
        log = await repository.create_log(payload, current_user.id)

        name = " ".join(
            part for part in (current_user.firstname, current_user.lastname) if part
        ).strip()

        return MeterLogEntrySchema(
            id=log.id,
            machine_id=log.machine_id,
            log_date=log.log_date,
            km=float(log.km),
            engine_hours=float(log.engine_hours),
            entered_by_id=log.created_by_id,
            entered_by_name=name or None,
            created_at=log.created_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"KM / motor saati kaydedilemedi: {e}",
        )
