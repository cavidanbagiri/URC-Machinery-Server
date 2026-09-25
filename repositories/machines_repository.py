# repositories/machines_repository.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from models.machines_model import (
    TerritoryModel,
    TypeTransportModel,
    SubTypeTransportModel,
    CarMarkModel,
    CarModelModel,
    CompanyModel,
    CarStatusModel
)
from schemas.machines_schemas import (
    CreateTerritorySchema,
    CreateTypeTransportSchema,
    CreateSubTypeTransportSchema,
    CreateCarMarkSchema,
    CreateCarModelSchema,
    CreateCompanySchema, CreateCarStatusSchema, UpdateCarStatusSchema,
)


# =========================================================
# BASE LOOKUP REPOSITORY (daxili köməkçi)
# =========================================================

class _BaseLookupRepository:
    """
    Lookup cədvəlləri üçün ümumi məntiq.
    Hər subclass `model` atributunu təyin edir.
    """

    model = None  # subclass override edir
    label = "Entity"  # xəta mesajları üçün

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data):
        # 1) Eyni adlı mövcuddursa → 409
        existing = await self.db.execute(
            select(self.model).where(self.model.name == data.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Bu adda {self.label} artıq mövcuddur",
            )

        # 2) Yarat
        obj = self.model(name=data.name)
        self.db.add(obj)

        try:
            await self.db.commit()
            await self.db.refresh(obj)
        except Exception:
            await self.db.rollback()
            raise

        return obj

    async def fetch_all(self) -> list:
        result = await self.db.execute(
            select(self.model).order_by(self.model.id)
        )
        return list(result.scalars().all())

    async def fetch_by_id(self, obj_id: int):
        result = await self.db.execute(
            select(self.model).where(self.model.id == obj_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            raise HTTPException(
                status_code=404,
                detail=f"{self.label} tapılmadı",
            )
        return obj

    async def update(self, obj_id: int, data):
        obj = await self.fetch_by_id(obj_id)

        # Eyni adlı başqa bir obj varsa → 409
        existing = await self.db.execute(
            select(self.model).where(
                self.model.name == data.name,
                self.model.id != obj_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Bu adda {self.label} artıq mövcuddur",
            )

        obj.name = data.name

        try:
            await self.db.commit()
            await self.db.refresh(obj)
        except Exception:
            await self.db.rollback()
            raise

        return obj

    async def delete(self, obj_id: int) -> None:
        obj = await self.fetch_by_id(obj_id)

        try:
            await self.db.delete(obj)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise


# =========================================================
# CONCRETE REPOSITORIES
# =========================================================

class TerritoryRepository(_BaseLookupRepository):
    model = TerritoryModel
    label = "Territory"

    async def create(self, territory_data: CreateTerritorySchema) -> TerritoryModel:
        return await super().create(territory_data)


class TypeTransportRepository(_BaseLookupRepository):
    model = TypeTransportModel
    label = "Type Transport"

    async def create(self, data: CreateTypeTransportSchema):
        return await super().create(data)


class SubTypeTransportRepository(_BaseLookupRepository):
    model = SubTypeTransportModel
    label = "SubType Transport"

    async def create(self, data: CreateSubTypeTransportSchema):
        return await super().create(data)


class CarMarkRepository(_BaseLookupRepository):
    model = CarMarkModel
    label = "Car Mark"

    async def create(self, data: CreateCarMarkSchema):
        return await super().create(data)


class CarModelRepository(_BaseLookupRepository):
    model = CarModelModel
    label = "Car Model"

    async def create(self, data: CreateCarModelSchema):
        return await super().create(data)


class CompanyRepository(_BaseLookupRepository):
    model = CompanyModel
    label = "Company"

    async def create(self, data: CreateCompanySchema):
        return await super().create(data)


# repositories/machines_repository.py (əlavə)
import math

from sqlalchemy import select, func

from models.machines_model import AllMachineModel
from schemas.machines_schemas import (
    CreateAllMachineSchema,
    UpdateAllMachineSchema,
)


class AllMachineRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- Köməkçi: FK-ları yoxla ----------
    async def _validate_fk(self, model, obj_id: int, label: str):
        if obj_id is None:
            return
        result = await self.db.execute(
            select(model).where(model.id == obj_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=404,
                detail=f"{label} (id={obj_id}) tapılmadı",
            )

    async def _validate_all_fks(self, data):
        await self._validate_fk(TerritoryModel, data.territory_id, "Territory")
        await self._validate_fk(TypeTransportModel, data.type_id, "Type Transport")
        await self._validate_fk(SubTypeTransportModel, data.subtype_id, "SubType Transport")
        await self._validate_fk(CarMarkModel, data.car_mark_id, "Car Mark")
        await self._validate_fk(CarModelModel, data.car_model_id, "Car Model")
        await self._validate_fk(CompanyModel, data.company_id, "Company")
        await self._validate_fk(CarStatusModel, data.status_id, "Status")  # ← YENİ

    # ---------- CREATE ----------
    async def create(
        self,
        data: CreateAllMachineSchema,
        created_by_id: int,
    ) -> AllMachineModel:
        # 1) FK-ları yoxla
        await self._validate_all_fks(data)

        # 2) VIN unikal yoxla (əgər verilibsə)
        if data.vin_no:
            existing = await self.db.execute(
                select(AllMachineModel).where(AllMachineModel.vin_no == data.vin_no)
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail="Bu VIN nömrəsi artıq mövcuddur",
                )

        # 3) Yarat
        machine = AllMachineModel(
            **data.model_dump(),
            created_by_id=created_by_id,
        )
        self.db.add(machine)

        try:
            await self.db.commit()
            await self.db.refresh(machine)
        except Exception:
            await self.db.rollback()
            raise

        return machine

    # ---------- FETCH (PAGINATION İLƏ) ----------
        # repositories/machines_repository.py (dəyişdir)

        # repositories/machines_repository.py (dəyişdir)

        async def fetch_paginated(
                self,
                limit: int = 20,
                offset: int = 0,
                # Filterlər
                identification_no: str | None = None,
                vin_no: str | None = None,
                territory_id: int | None = None,
                type_id: int | None = None,
                subtype_id: int | None = None,
                car_mark_id: int | None = None,
                car_model_id: int | None = None,
                company_id: int | None = None,
                created_by_id: int | None = None,
                production_year: int | None = None,
        ) -> dict:
            # Limit / offset yoxlama
            if limit < 1:
                limit = 20
            if limit > 100:
                limit = 100
            if offset < 0:
                offset = 0

            # Base query
            query = select(AllMachineModel)

            # Filtrlər
            filters = []

            if identification_no:
                filters.append(
                    AllMachineModel.identification_no.ilike(f"%{identification_no}%")
                )
            if vin_no:
                filters.append(
                    AllMachineModel.vin_no.ilike(f"%{vin_no}%")
                )
            if territory_id is not None:
                filters.append(AllMachineModel.territory_id == territory_id)
            if type_id is not None:
                filters.append(AllMachineModel.type_id == type_id)
            if subtype_id is not None:
                filters.append(AllMachineModel.subtype_id == subtype_id)
            if car_mark_id is not None:
                filters.append(AllMachineModel.car_mark_id == car_mark_id)
            if car_model_id is not None:
                filters.append(AllMachineModel.car_model_id == car_model_id)
            if company_id is not None:
                filters.append(AllMachineModel.company_id == company_id)
            if created_by_id is not None:
                filters.append(AllMachineModel.created_by_id == created_by_id)
            if production_year is not None:
                # production_year DateTime-dır, ona görə il aralığını yoxlayırıq
                year_start = datetime(production_year, 1, 1, tzinfo=timezone.utc)
                year_end = datetime(production_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
                filters.append(AllMachineModel.production_year >= year_start)
                filters.append(AllMachineModel.production_year <= year_end)

            if filters:
                query = query.where(*filters)

            # Items (desc by id, limit + offset)
            query = (
                query
                .order_by(AllMachineModel.id.desc())
                .offset(offset)
                .limit(limit)
            )
            items_result = await self.db.execute(query)
            items = list(items_result.scalars().all())

            return {
                "limit": limit,
                "offset": offset,
                "items": items,
            }

    async def fetch_paginated(
            self,
            limit: int = 20,
            offset: int = 0,
            identification_no: str | None = None,
            vin_no: str | None = None,
            territory_id: int | None = None,
            type_id: int | None = None,
            subtype_id: int | None = None,
            car_mark_id: int | None = None,
            car_model_id: int | None = None,
            company_id: int | None = None,
            status_id: int | None = None,  # ← YENİ
            created_by_id: int | None = None,
            production_year: int | None = None,
    ) -> dict:
        # Limit / offset yoxlama
        if limit < 1:
            limit = 20
        if limit > 100:
            limit = 100
        if offset < 0:
            offset = 0

        # Base queries
        query = select(AllMachineModel)
        count_query = select(func.count(AllMachineModel.id))  # ← BURADA

        # Filtrlər
        filters = []
        if identification_no:
            filters.append(
                AllMachineModel.identification_no.ilike(f"%{identification_no}%")
            )
        if vin_no:
            filters.append(AllMachineModel.vin_no.ilike(f"%{vin_no}%"))
        if territory_id is not None:
            filters.append(AllMachineModel.territory_id == territory_id)
        if type_id is not None:
            filters.append(AllMachineModel.type_id == type_id)
        if subtype_id is not None:
            filters.append(AllMachineModel.subtype_id == subtype_id)
        if car_mark_id is not None:
            filters.append(AllMachineModel.car_mark_id == car_mark_id)
        if car_model_id is not None:
            filters.append(AllMachineModel.car_model_id == car_model_id)
        if company_id is not None:
            filters.append(AllMachineModel.company_id == company_id)
        if status_id is not None:  # ← YENİ
            filters.append(AllMachineModel.status_id == status_id)
        if created_by_id is not None:
            filters.append(AllMachineModel.created_by_id == created_by_id)
        if production_year is not None:
            year_start = datetime(production_year, 1, 1, tzinfo=timezone.utc)
            year_end = datetime(production_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            filters.append(AllMachineModel.production_year >= year_start)
            filters.append(AllMachineModel.production_year <= year_end)

        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)  # ← BURADA

        # Total
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Items
        query = (
            query
            .order_by(AllMachineModel.id.desc())
            .offset(offset)
            .limit(limit)
        )
        items_result = await self.db.execute(query)
        items = list(items_result.scalars().all())

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }



    # ---------- FETCH BY ID ----------
    # async def fetch_by_id(self, machine_id: int) -> AllMachineModel:
    #     result = await self.db.execute(
    #         select(AllMachineModel).where(AllMachineModel.id == machine_id)
    #     )
    #     machine = result.scalar_one_or_none()
    #     if machine is None:
    #         raise HTTPException(status_code=404, detail="Machine tapılmadı")
    #     return machine
    async def fetch_by_id(self, machine_id: int) -> AllMachineModel:
        result = await self.db.execute(
            select(AllMachineModel).where(AllMachineModel.id == machine_id)
        )
        machine = result.scalar_one_or_none()
        if machine is None:
            raise HTTPException(status_code=404, detail="Machine tapılmadı")
        return machine

    # ---------- UPDATE ----------
    async def update(
        self,
        machine_id: int,
        data: UpdateAllMachineSchema,
    ) -> AllMachineModel:
        machine = await self.fetch_by_id(machine_id)

        # FK-ları yoxla
        await self._validate_all_fks(data)

        # VIN unikal yoxla (özündən başqa)
        if data.vin_no:
            existing = await self.db.execute(
                select(AllMachineModel).where(
                    AllMachineModel.vin_no == data.vin_no,
                    AllMachineModel.id != machine_id,
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail="Bu VIN nömrəsi artıq mövcuddur",
                )

        # Sahələri yenilə
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(machine, field, value)

        try:
            await self.db.commit()
            await self.db.refresh(machine)
        except Exception:
            await self.db.rollback()
            raise

        return machine

    # ---------- DELETE ----------
    async def delete(self, machine_id: int) -> None:
        machine = await self.fetch_by_id(machine_id)

        try:
            await self.db.delete(machine)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise





class CarStatusRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: CreateCarStatusSchema) -> CarStatusModel:
        # Eyni adlı varsa → 409
        existing = await self.db.execute(
            select(CarStatusModel).where(CarStatusModel.name == data.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="Bu adda status artıq mövcuddur",
            )

        obj = CarStatusModel(
            name=data.name,
            color=data.color,
            description=data.description,
        )
        self.db.add(obj)

        try:
            await self.db.commit()
            await self.db.refresh(obj)
        except Exception:
            await self.db.rollback()
            raise

        return obj

    async def fetch_all(self) -> list[CarStatusModel]:
        result = await self.db.execute(
            select(CarStatusModel).order_by(CarStatusModel.id)
        )
        return list(result.scalars().all())

    async def fetch_by_id(self, obj_id: int) -> CarStatusModel:
        result = await self.db.execute(
            select(CarStatusModel).where(CarStatusModel.id == obj_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            raise HTTPException(status_code=404, detail="Status tapılmadı")
        return obj

    async def update(self, obj_id: int, data: UpdateCarStatusSchema) -> CarStatusModel:
        obj = await self.fetch_by_id(obj_id)

        # Eyni adlı başqa varsa → 409
        if data.name:
            existing = await self.db.execute(
                select(CarStatusModel).where(
                    CarStatusModel.name == data.name,
                    CarStatusModel.id != obj_id,
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail="Bu adda status artıq mövcuddur",
                )

        # Yalnız göndərilən sahələri yenilə
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)

        try:
            await self.db.commit()
            await self.db.refresh(obj)
        except Exception:
            await self.db.rollback()
            raise

        return obj

    async def delete(self, obj_id: int) -> None:
        obj = await self.fetch_by_id(obj_id)

        # İstifadədə olub-olmadığını yoxla
        in_use = await self.db.execute(
            select(AllMachineModel).where(AllMachineModel.status_id == obj_id).limit(1)
        )
        if in_use.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="Bu status maşınlarda istifadə olunur, silinə bilməz",
            )

        try:
            await self.db.delete(obj)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise