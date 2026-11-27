# routers/meter_log_router.py
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.fuel_log_window import (
    DEFAULT_EDIT_WINDOW_DAYS,
    MAX_EDIT_WINDOW_DAYS,
)
from repositories.meter_log_repository import MeterLogRepository
from schemas.meter_log_schemas import (
    MeterLogCreateSchema,
    MeterLogEntrySchema,
    MeterLogOverviewSchema,
    MeterLogUpdateSchema,
)

# Every meter-log endpoint requires a valid access token.  Writes (new reading /
# correction) additionally require the create/update permission value.
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


@router.get("/entries", response_model=list[MeterLogEntrySchema])
async def fetch_meter_log_entries(
    db: Annotated[AsyncSession, Depends(get_db)],
    machine_id: int = Query(
        ...,
        gt=0,
        description="Machine whose readings are listed.",
    ),
    end_date: Optional[date] = Query(
        None,
        description="Last day of the window (the page's selected day).",
    ),
    days: int = Query(
        DEFAULT_EDIT_WINDOW_DAYS,
        ge=1,
        le=MAX_EDIT_WINDOW_DAYS,
        description="How many days back the list reaches.",
    ),
):
    """Recent KM / engine-hour readings of one machine, newest first.

    Feeds the **İşlemler → Düzenle** dialog: a reading entered on the wrong day
    (or with a wrong counter) is found here and corrected with
    ``PUT /meter-logs/update/{log_id}``.
    """
    try:
        repository = MeterLogRepository(db)
        return await repository.fetch_entries(
            machine_id,
            target_date=end_date,
            days=days,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"KM / motor saati kayıtları getirilemedi: {e}",
        )


# =========================================================
# WRITE (INSERT + CORRECT)
# =========================================================


@router.post("/create", response_model=MeterLogEntrySchema, status_code=201)
async def create_meter_log(
    payload: MeterLogCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Append a reading.  Saved rows are corrected, never deleted."""
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


@router.put("/update/{log_id}", response_model=MeterLogEntrySchema)
async def update_meter_log(
    log_id: int,
    payload: MeterLogUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Correct the day / KM / engine hours of one saved reading.

    The page's **İşlemler → Düzenle** button lists the recent readings of a
    machine; saving one of them fixes the common mistake where a counter was
    entered on the wrong day or with a typing error.  The row is rewritten in
    place — the 7-day matrix, the "latest reading" columns and the
    *Son Gün/KM* / *1 Aylık Toplam* differences follow the corrected values, so
    no compensating row is appended.
    """
    try:
        repository = MeterLogRepository(db)
        return await repository.update_log(log_id, payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"KM / motor saati kaydı güncellenemedi: {e}",
        )
