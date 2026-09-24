# routers/machines_router.py
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.permissions import require_write_permission
from repositories.machines_repository import (
    TerritoryRepository,
    TypeTransportRepository,
    SubTypeTransportRepository,
    CarMarkRepository,
    CarModelRepository,
    CompanyRepository,
)
from schemas.machines_schemas import (
    CreateTerritorySchema, FetchTerritorySchema,
    CreateTypeTransportSchema, FetchTypeTransportSchema,
    CreateSubTypeTransportSchema, FetchSubTypeTransportSchema,
    CreateCarMarkSchema, FetchCarMarkSchema,
    CreateCarModelSchema, FetchCarModelSchema,
    CreateCompanySchema, FetchCompanySchema,
)

router = APIRouter()


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
        raise HTTPException(status_code=500, detail=f"Territory yaradıla bilmədi: {e}")


@router.get("/fetch_territories", response_model=list[FetchTerritorySchema])
async def fetch_territories(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await TerritoryRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Territory-lər gətirilə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Territory yenilənə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Territory silinə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Type Transport yaradıla bilmədi: {e}")


@router.get("/fetch_type_transports", response_model=list[FetchTypeTransportSchema])
async def fetch_type_transports(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await TypeTransportRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Type Transport-lar gətirilə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Type Transport yenilənə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Type Transport silinə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"SubType Transport yaradıla bilmədi: {e}")


@router.get("/fetch_sub_type_transports", response_model=list[FetchSubTypeTransportSchema])
async def fetch_sub_type_transports(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await SubTypeTransportRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SubType Transport-lar gətirilə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"SubType Transport yenilənə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"SubType Transport silinə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Car Mark yaradıla bilmədi: {e}")


@router.get("/fetch_car_marks", response_model=list[FetchCarMarkSchema])
async def fetch_car_marks(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await CarMarkRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Car Mark-lar gətirilə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Car Mark yenilənə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Car Mark silinə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Car Model yaradıla bilmədi: {e}")


@router.get("/fetch_car_models", response_model=list[FetchCarModelSchema])
async def fetch_car_models(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await CarModelRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Car Model-lar gətirilə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Car Model yenilənə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Car Model silinə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Company yaradıla bilmədi: {e}")


@router.get("/fetch_companies", response_model=list[FetchCompanySchema])
async def fetch_companies(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        return await CompanyRepository(db).fetch_all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Company-lər gətirilə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Company yenilənə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Company silinə bilmədi: {e}")




# routers/machines_router.py (əlavə)
from typing import Optional

from dependencies.auth import get_current_user
from models.user_model import UserModel
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
        raise HTTPException(status_code=500, detail=f"Machine yaradıla bilmədi: {e}")


# @router.get(
#     "/fetch_machines",
#     response_model=PaginatedAllMachineSchema,
# )
# async def fetch_machines(
#     db: Annotated[AsyncSession, Depends(get_db)],
#     page: int = 1,
#     page_size: int = 20,
#     territory_id: Optional[int] = None,
#     type_id: Optional[int] = None,
#     company_id: Optional[int] = None,
# ):
#     try:
#         repo = AllMachineRepository(db)
#         return await repo.fetch_paginated(
#             page=page,
#             page_size=page_size,
#             territory_id=territory_id,
#             type_id=type_id,
#             company_id=company_id,
#         )
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Machine-lar gətirilə bilmədi: {e}")






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
    territory_id: Optional[int] = None,
    type_id: Optional[int] = None,
    subtype_id: Optional[int] = None,
    car_mark_id: Optional[int] = None,
    car_model_id: Optional[int] = None,
    company_id: Optional[int] = None,
    created_by_id: Optional[int] = None,
    production_year: Optional[int] = None,
):
    print("DEBUG — fetch_machines çağırıldı")
    print(f"DEBUG — limit={limit}, offset={offset}")
    try:
        repo = AllMachineRepository(db)
        return await repo.fetch_paginated(
            limit=limit,
            offset=offset,
            identification_no=identification_no,
            vin_no=vin_no,
            territory_id=territory_id,
            type_id=type_id,
            subtype_id=subtype_id,
            car_mark_id=car_mark_id,
            car_model_id=car_model_id,
            company_id=company_id,
            created_by_id=created_by_id,
            production_year=production_year,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Machine-lar gətirilə bilmədi: {e}")





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
        raise HTTPException(status_code=500, detail=f"Machine yenilənə bilmədi: {e}")


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
        raise HTTPException(status_code=500, detail=f"Machine silinə bilmədi: {e}")