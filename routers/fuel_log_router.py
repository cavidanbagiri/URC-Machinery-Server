# routers/fuel_log_router.py
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.fuel_log_repository import (
    DEFAULT_DISTRIBUTION_DAYS,
    MAX_DISTRIBUTION_DAYS,
    FuelLogRepository,
)
from repositories.fuel_log_window import (
    DEFAULT_EDIT_WINDOW_DAYS,
    MAX_EDIT_WINDOW_DAYS,
)
from repositories.rental_fuel_log_repository import RentalFuelLogRepository
from schemas.fuel_log_schemas import (
    FuelDistributionSchema,
    FuelLogCreateSchema,
    FuelLogEntrySchema,
    FuelLogOverviewSchema,
    FuelLogUpdateSchema,
    RentalFuelLogCreateSchema,
    RentalFuelLogEntrySchema,
    RentalFuelLogUpdateSchema,
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
    """Machines with the selected day's fuel totals and period summaries.

    The response also carries the **Kiralık** tab (rented machines): the
    ``rental_*`` totals and ``rental_machines`` rows come from
    ``machine_rental_fuel_logs``, which points at the rental agreement instead
    of a fleet machine.
    """
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


@router.get("/statistics/daily", response_model=FuelDistributionSchema)
async def fetch_fuel_distribution(
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(
        DEFAULT_DISTRIBUTION_DAYS,
        ge=1,
        le=MAX_DISTRIBUTION_DAYS,
        description="Rolling window length in days (dashboard chart requests 10).",
    ),
    end_date: Optional[date] = Query(
        None,
        description="Last day of the window; defaults to today.",
    ),
):
    """Dashboard **Mazot Dağılımı** chart: SRU / DCU / kiralık per day.

    One item per calendar day (days without rows come back as zeros) so the
    grouped bar chart always has ``days`` bar groups.
    """
    try:
        repository = FuelLogRepository(db)
        return await repository.fetch_daily_distribution(
            days=days,
            end_date=end_date,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Mazot dağılım istatistikleri getirilemedi: {e}",
        )


@router.get("/entries", response_model=list[FuelLogEntrySchema])
async def fetch_fuel_log_entries(
    db: Annotated[AsyncSession, Depends(get_db)],
    machine_id: int = Query(
        ...,
        gt=0,
        description="Fleet machine whose rows are listed.",
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
    """Recent diesel rows of one machine, newest first.

    Feeds the **İşlemler → Düzenle** dialog: a row entered on the wrong day is
    found here and corrected with ``PUT /fuel-logs/update/{log_id}``.
    """
    try:
        repository = FuelLogRepository(db)
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
            detail=f"Mazot kayıtları getirilemedi: {e}",
        )


@router.get("/rental/entries", response_model=list[RentalFuelLogEntrySchema])
async def fetch_rental_fuel_log_entries(
    db: Annotated[AsyncSession, Depends(get_db)],
    rental_id: int = Query(
        ...,
        gt=0,
        description="Rental agreement whose rows are listed.",
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
    """Recent diesel rows of one **rented** machine (Kiralık tab)."""
    try:
        repository = RentalFuelLogRepository(db)
        return await repository.fetch_entries(
            rental_id,
            target_date=end_date,
            days=days,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Kiralık makine mazot kayıtları getirilemedi: {e}",
        )


# =========================================================
# WRITE
# =========================================================


@router.post("/create", response_model=FuelLogEntrySchema, status_code=201)
async def create_fuel_log(
    payload: FuelLogCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Append a fuel distribution row.

    A row saved on the wrong day is corrected later with
    ``PUT /fuel-logs/update/{log_id}`` instead of being compensated by a second
    row.
    """
    try:
        repository = FuelLogRepository(db)

        # The table no longer has a *Yakıtı veren* column, so the person who
        # saved the row becomes the provider unless the payload names one.
        name = " ".join(
            part for part in (current_user.firstname, current_user.lastname) if part
        ).strip()

        log = await repository.create_log(
            payload,
            current_user.id,
            given_by=name or None,
        )

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


@router.post(
    "/rental/create",
    response_model=RentalFuelLogEntrySchema,
    status_code=201,
)
async def create_rental_fuel_log(
    payload: RentalFuelLogCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Append a diesel row for a **rented** machine (Kiralık sekmesi).

    Rented equipment has no fleet ID, so the row references the rental
    agreement.  The optional ``km`` / ``engine_hours`` values are stored on the
    same row, i.e. the counter reading is timestamped by the diesel date itself.
    A wrong row is corrected with ``PUT /fuel-logs/rental/update/{log_id}``.
    """
    try:
        repository = RentalFuelLogRepository(db)

        name = " ".join(
            part for part in (current_user.firstname, current_user.lastname) if part
        ).strip()

        log = await repository.create_log(
            payload,
            current_user.id,
            given_by=name or None,
        )

        return RentalFuelLogEntrySchema(
            id=log.id,
            rental_id=log.rental_id,
            fuel_date=log.fuel_date,
            liters=float(log.liters),
            km=float(log.km) if log.km is not None else None,
            engine_hours=(
                float(log.engine_hours)
                if log.engine_hours is not None
                else None
            ),
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
            detail=f"Kiralık makine mazot kaydı kaydedilemedi: {e}",
        )


# =========================================================
# CORRECT (UPDATE)
# =========================================================


@router.put("/update/{log_id}", response_model=FuelLogEntrySchema)
async def update_fuel_log(
    log_id: int,
    payload: FuelLogUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Correct the date / litres / note of one saved diesel row.

    The page's **İşlemler → Düzenle** button lists the recent rows of a machine;
    saving one of them fixes the common mistake where the 24th's diesel was
    entered on the 25th.  The daily / weekly / monthly totals move with the
    corrected date because they are always calculated from the ledger itself.
    """
    try:
        repository = FuelLogRepository(db)
        return await repository.update_log(log_id, payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Mazot kaydı güncellenemedi: {e}",
        )


@router.put("/rental/update/{log_id}", response_model=RentalFuelLogEntrySchema)
async def update_rental_fuel_log(
    log_id: int,
    payload: RentalFuelLogUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    """Correct one row of the **Kiralık** diesel ledger.

    Besides the date and the litres, the KM / engine-hour readings stored on the
    row can be fixed as well; they belong to the same refuelling.
    """
    try:
        repository = RentalFuelLogRepository(db)
        return await repository.update_log(log_id, payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Kiralık makine mazot kaydı güncellenemedi: {e}",
        )
