# routers/machines_router.py
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.user_model import UserModel
from repositories.machines_repository import (
    TerritoryRepository,
    TypeTransportRepository,
    SubTypeTransportRepository,
    CarMarkRepository,
    CarModelRepository,
    CompanyRepository,
    CarStatusRepository
)
from schemas.machines_schemas import (
    CreateTerritorySchema, FetchTerritorySchema,
    CreateTypeTransportSchema, FetchTypeTransportSchema,
    CreateSubTypeTransportSchema, FetchSubTypeTransportSchema,
    CreateCarMarkSchema, FetchCarMarkSchema,
    CreateCarModelSchema, FetchCarModelSchema,
    CreateCompanySchema, FetchCompanySchema,
    CreateCarStatusSchema, UpdateCarStatusSchema,
    FetchCarStatusSchema, StatusStatisticsSchema, PivotTableSchema,

)

# Every machine/lookup endpoint requires a valid access token. Write endpoints
# additionally enforce require_write_permission below.
router = APIRouter(dependencies=[Depends(get_current_user)])


# =========================================================
# TERRITORY
# =========================================================

@router.post(
    "/create_territory",
    status_code=201,
    response_model=FetchTerritorySchema,
    dependencies=[Depends(require_write_permission)],
)
async def create_territory(
    data: CreateTerritorySchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await TerritoryRepository(db).create(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bölge oluşturulamadı: {e}")


@router.get("/fetch_territories", response_model=list[FetchTerritorySchema])
async def fetch_territories(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await TerritoryRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bölgeler getirilemedi: {e}")


@router.put(
    "/update_territory/{territory_id}",
    response_model=FetchTerritorySchema,
    dependencies=[Depends(require_write_permission)],
)
async def update_territory(
    territory_id: int,
    data: CreateTerritorySchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await TerritoryRepository(db).update(territory_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bölge güncellenemedi: {e}")


@router.delete(
    "/delete_territory/{territory_id}",
    status_code=204,
    dependencies=[Depends(require_write_permission)],
)
async def delete_territory(
    territory_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await TerritoryRepository(db).delete(territory_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bölge silinemedi: {e}")


# =========================================================
# TYPE TRANSPORT
# =========================================================

@router.post(
    "/create_type_transport",
    status_code=201,
    response_model=FetchTypeTransportSchema,
    dependencies=[Depends(require_write_permission)],
)
async def create_type_transport(
    data: CreateTypeTransportSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await TypeTransportRepository(db).create(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Taşıma tipi oluşturulamadı: {e}")


@router.get("/fetch_type_transports", response_model=list[FetchTypeTransportSchema])
async def fetch_type_transports(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await TypeTransportRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Taşıma tipleri getirilemedi: {e}")


@router.put(
    "/update_type_transport/{obj_id}",
    response_model=FetchTypeTransportSchema,
    dependencies=[Depends(require_write_permission)],
)
async def update_type_transport(
    obj_id: int,
    data: CreateTypeTransportSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await TypeTransportRepository(db).update(obj_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Taşıma tipi güncellenemedi: {e}")


@router.delete(
    "/delete_type_transport/{obj_id}",
    status_code=204,
    dependencies=[Depends(require_write_permission)],
)
async def delete_type_transport(
    obj_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await TypeTransportRepository(db).delete(obj_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Taşıma tipi silinemedi: {e}")


# =========================================================
# SUB TYPE TRANSPORT
# =========================================================

@router.post(
    "/create_sub_type_transport",
    status_code=201,
    response_model=FetchSubTypeTransportSchema,
    dependencies=[Depends(require_write_permission)],
)
async def create_sub_type_transport(
    data: CreateSubTypeTransportSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await SubTypeTransportRepository(db).create(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Alt taşıma tipi oluşturulamadı: {e}")


@router.get("/fetch_sub_type_transports", response_model=list[FetchSubTypeTransportSchema])
async def fetch_sub_type_transports(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await SubTypeTransportRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Alt taşıma tipleri getirilemedi: {e}")


@router.put(
    "/update_sub_type_transport/{obj_id}",
    response_model=FetchSubTypeTransportSchema,
    dependencies=[Depends(require_write_permission)],
)
async def update_sub_type_transport(
    obj_id: int,
    data: CreateSubTypeTransportSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await SubTypeTransportRepository(db).update(obj_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Alt taşıma tipi güncellenemedi: {e}")


@router.delete(
    "/delete_sub_type_transport/{obj_id}",
    status_code=204,
    dependencies=[Depends(require_write_permission)],
)
async def delete_sub_type_transport(
    obj_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await SubTypeTransportRepository(db).delete(obj_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Alt taşıma tipi silinemedi: {e}")


# =========================================================
# CAR MARK
# =========================================================

@router.post(
    "/create_car_mark",
    status_code=201,
    response_model=FetchCarMarkSchema,
    dependencies=[Depends(require_write_permission)],
)
async def create_car_mark(
    data: CreateCarMarkSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await CarMarkRepository(db).create(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Marka oluşturulamadı: {e}")


@router.get("/fetch_car_marks", response_model=list[FetchCarMarkSchema])
async def fetch_car_marks(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await CarMarkRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Markalar getirilemedi: {e}")


@router.put(
    "/update_car_mark/{obj_id}",
    response_model=FetchCarMarkSchema,
    dependencies=[Depends(require_write_permission)],
)
async def update_car_mark(
    obj_id: int,
    data: CreateCarMarkSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await CarMarkRepository(db).update(obj_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Marka güncellenemedi: {e}")


@router.delete(
    "/delete_car_mark/{obj_id}",
    status_code=204,
    dependencies=[Depends(require_write_permission)],
)
async def delete_car_mark(
    obj_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await CarMarkRepository(db).delete(obj_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Marka silinemedi: {e}")


# =========================================================
# CAR MODEL
# =========================================================

@router.post(
    "/create_car_model",
    status_code=201,
    response_model=FetchCarModelSchema,
    dependencies=[Depends(require_write_permission)],
)
async def create_car_model(
    data: CreateCarModelSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await CarModelRepository(db).create(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model oluşturulamadı: {e}")


@router.get("/fetch_car_models", response_model=list[FetchCarModelSchema])
async def fetch_car_models(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await CarModelRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Modeller getirilemedi: {e}")


@router.put(
    "/update_car_model/{obj_id}",
    response_model=FetchCarModelSchema,
    dependencies=[Depends(require_write_permission)],
)
async def update_car_model(
    obj_id: int,
    data: CreateCarModelSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await CarModelRepository(db).update(obj_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model güncellenemedi: {e}")


@router.delete(
    "/delete_car_model/{obj_id}",
    status_code=204,
    dependencies=[Depends(require_write_permission)],
)
async def delete_car_model(
    obj_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await CarModelRepository(db).delete(obj_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model silinemedi: {e}")


# =========================================================
# COMPANY
# =========================================================

@router.post(
    "/create_company",
    status_code=201,
    response_model=FetchCompanySchema,
    dependencies=[Depends(require_write_permission)],
)
async def create_company(
    data: CreateCompanySchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await CompanyRepository(db).create(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Şirket oluşturulamadı: {e}")


@router.get("/fetch_companies", response_model=list[FetchCompanySchema])
async def fetch_companies(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await CompanyRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Şirketler getirilemedi: {e}")


@router.put(
    "/update_company/{obj_id}",
    response_model=FetchCompanySchema,
    dependencies=[Depends(require_write_permission)],
)
async def update_company(
    obj_id: int,
    data: CreateCompanySchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await CompanyRepository(db).update(obj_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Şirket güncellenemedi: {e}")


@router.delete(
    "/delete_company/{obj_id}",
    status_code=204,
    dependencies=[Depends(require_write_permission)],
)
async def delete_company(
    obj_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await CompanyRepository(db).delete(obj_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Şirket silinemedi: {e}")




# routers/machines_router.py (əlavə)
from repositories.machines_repository import AllMachineRepository
from schemas.machines_schemas import (
    CreateAllMachineSchema,
    UpdateAllMachineSchema,
    FetchAllMachineSchema,
    PaginatedAllMachineSchema,
)


# =========================================================
# ALL MACHINE
# =========================================================

@router.post(
    "/create_machine",
    status_code=201,
    response_model=FetchAllMachineSchema,
    dependencies=[Depends(require_write_permission)],
)
async def create_machine(
    data: CreateAllMachineSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
):
    try:
        repo = AllMachineRepository(db)
        return await repo.create(data, created_by_id=current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Makine oluşturulamadı: {e}")




@router.get(
    "/fetch_machines",
    response_model=PaginatedAllMachineSchema,
)
async def fetch_machines(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
    offset: int = 0,
    identification_no: Optional[str] = None,
    vin_no: Optional[str] = None,
    plate_no: Optional[str] = None,
    territory_id: Optional[int] = None,
    type_id: Optional[int] = None,
    subtype_id: Optional[int] = None,
    car_mark_id: Optional[int] = None,
    car_model_id: Optional[int] = None,
    company_id: Optional[int] = None,
    status_id: Optional[int] = None,
    created_by_id: Optional[int] = None,
    production_year: Optional[int] = None,
):
    try:
        repo = AllMachineRepository(db)
        return await repo.fetch_paginated(
            limit=limit,
            offset=offset,
            identification_no=identification_no,
            vin_no=vin_no,
            plate_no=plate_no,
            territory_id=territory_id,
            type_id=type_id,
            subtype_id=subtype_id,
            car_mark_id=car_mark_id,
            car_model_id=car_model_id,
            company_id=company_id,
            status_id=status_id,
            created_by_id=created_by_id,
            production_year=production_year,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Makineler getirilemedi: {e}")




@router.get(
    "/fetch_machine/{machine_id}",
    response_model=FetchAllMachineSchema,
)
async def fetch_machine(
    machine_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        repo = AllMachineRepository(db)
        return await repo.fetch_by_id(machine_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Makine getirilemedi: {e}")




@router.put(
    "/update_machine/{machine_id}",
    response_model=FetchAllMachineSchema,
    dependencies=[Depends(require_write_permission)],
)
async def update_machine(
    machine_id: int,
    data: UpdateAllMachineSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        repo = AllMachineRepository(db)
        return await repo.update(machine_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Makine güncellenemedi: {e}")


@router.delete(
    "/delete_machine/{machine_id}",
    status_code=204,
    dependencies=[Depends(require_write_permission)],
)
async def delete_machine(
    machine_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        repo = AllMachineRepository(db)
        await repo.delete(machine_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Makine silinemedi: {e}")



# =========================================================
# CAR STATUS
# =========================================================

@router.post(
    "/create_car_status",
    status_code=201,
    response_model=FetchCarStatusSchema,
    dependencies=[Depends(require_write_permission)],
)
async def create_car_status(
    data: CreateCarStatusSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await CarStatusRepository(db).create(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Durum oluşturulamadı: {e}")


@router.get("/fetch_car_statuses", response_model=list[FetchCarStatusSchema])
async def fetch_car_statuses(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await CarStatusRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Durumlar getirilemedi: {e}")


@router.put(
    "/update_car_status/{obj_id}",
    response_model=FetchCarStatusSchema,
    dependencies=[Depends(require_write_permission)],
)
async def update_car_status(
    obj_id: int,
    data: UpdateCarStatusSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await CarStatusRepository(db).update(obj_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Durum güncellenemedi: {e}")


@router.delete(
    "/delete_car_status/{obj_id}",
    status_code=204,
    dependencies=[Depends(require_write_permission)],
)
async def delete_car_status(
    obj_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await CarStatusRepository(db).delete(obj_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Durum silinemedi: {e}")




@router.get(
    "/statistics/status",
    response_model=StatusStatisticsSchema,
)
async def get_status_statistics(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        repo = AllMachineRepository(db)
        return await repo.get_status_statistics()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"İstatistikler getirilemedi: {e}",
        )



@router.get(
    "/statistics/pivot",
    response_model=PivotTableSchema,
)
async def get_pivot_statistics(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        repo = AllMachineRepository(db)
        return await repo.get_type_territory_pivot()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Pivot istatistikleri getirilemedi: {e}",
        )