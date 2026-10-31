# repositories/machines_repository.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from models.garage_service_model import GarageServiceModel
from models.machines_model import (
    TerritoryModel,
    TypeTransportModel,
    SubTypeTransportModel,
    CarMarkModel,
    CarModelModel,
    CompanyModel,
    CarStatusModel
)
from models.repair_model import RepairRecordModel, RepairTypeModel
from schemas.machines_schemas import (
    CreateTerritorySchema,
    CreateTypeTransportSchema,
    CreateSubTypeTransportSchema,
    CreateCarMarkSchema,
    CreateCarModelSchema,
    CreateCompanySchema, CreateCarStatusSchema, UpdateCarStatusSchema,
    CreateRepairTypeSchema,
    CreateGarageServiceSchema,
)
from services.storage_service import delete_objects


# =========================================================
# BASE LOOKUP REPOSITORY (daxili köməkçi)
# =========================================================

class _BaseLookupRepository:
    """
    Lookup cədvəlləri üçün ümumi məntiq.
    Hər subclass `model` atributunu təyin edir.
    """

    model = None  # subclass override edir
    label = "Kayıt"  # hata mesajları için

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
                detail=f"Bu ada sahip {self.label} zaten mevcut",
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
                detail=f"{self.label} bulunamadı",
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
                detail=f"Bu ada sahip {self.label} zaten mevcut",
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
    label = "Bölge"

    async def create(self, territory_data: CreateTerritorySchema) -> TerritoryModel:
        return await super().create(territory_data)


class TypeTransportRepository(_BaseLookupRepository):
    model = TypeTransportModel
    label = "Taşıma Tipi"

    async def create(self, data: CreateTypeTransportSchema):
        return await super().create(data)


class SubTypeTransportRepository(_BaseLookupRepository):
    model = SubTypeTransportModel
    label = "Alt Taşıma Tipi"

    async def create(self, data: CreateSubTypeTransportSchema):
        return await super().create(data)


class CarMarkRepository(_BaseLookupRepository):
    model = CarMarkModel
    label = "Marka"

    async def create(self, data: CreateCarMarkSchema):
        return await super().create(data)


class CarModelRepository(_BaseLookupRepository):
    model = CarModelModel
    label = "Model"

    async def create(self, data: CreateCarModelSchema):
        return await super().create(data)


class CompanyRepository(_BaseLookupRepository):
    model = CompanyModel
    label = "Şirket"

    async def create(self, data: CreateCompanySchema):
        return await super().create(data)


class RepairTypeRepository(_BaseLookupRepository):
    model = RepairTypeModel
    label = "Tamir Tipi"

    async def create(self, data: CreateRepairTypeSchema):
        return await super().create(data)

    async def delete(self, obj_id: int) -> None:
        obj = await self.fetch_by_id(obj_id)
        used = await self.db.execute(
            select(RepairRecordModel.id)
            .where(RepairRecordModel.repair_type_id == obj_id)
            .limit(1)
        )
        if used.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="Bu tamir tipi kayıtlarda kullanıldığı için silinemez",
            )
        await super().delete(obj.id)


class GarageServiceRepository(_BaseLookupRepository):
    model = GarageServiceModel
    label = "Garaj Servisi"

    async def create(self, data: CreateGarageServiceSchema):
        return await super().create(data)

    async def delete(self, obj_id: int) -> None:
        obj = await self.fetch_by_id(obj_id)
        used = await self.db.execute(
            select(RepairRecordModel.id)
            .where(RepairRecordModel.garage_service_id == obj_id)
            .limit(1)
        )
        if used.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="Bu garaj servisi kayıtlarda kullanıldığı için silinemez",
            )
        await super().delete(obj.id)


# repositories/machines_repository.py (əlavə)
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

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
                detail=f"{label} (id={obj_id}) bulunamadı",
            )

    async def _validate_all_fks(self, data):
        await self._validate_fk(TerritoryModel, data.territory_id, "Bölge")
        await self._validate_fk(TypeTransportModel, data.type_id, "Taşıma Tipi")
        await self._validate_fk(SubTypeTransportModel, data.subtype_id, "Alt Taşıma Tipi")
        await self._validate_fk(CarMarkModel, data.car_mark_id, "Marka")
        await self._validate_fk(CarModelModel, data.car_model_id, "Model")
        await self._validate_fk(CompanyModel, data.company_id, "Şirket")
        await self._validate_fk(CarStatusModel, data.status_id, "Durum")  # ← YENİ

    async def _ensure_unique_fields(
        self,
        vin_no: str | None,
        plate_no: str | None,
        exclude_id: int | None = None,
    ) -> None:
        """Return a friendly 409 before the DB raises a unique violation."""
        if vin_no:
            query = select(AllMachineModel.id).where(
                AllMachineModel.vin_no == vin_no
            )
            if exclude_id is not None:
                query = query.where(AllMachineModel.id != exclude_id)
            if (await self.db.execute(query.limit(1))).scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Bu VIN numarası zaten mevcut",
                )

        if plate_no:
            query = select(AllMachineModel.id).where(
                AllMachineModel.plate_no == plate_no
            )
            if exclude_id is not None:
                query = query.where(AllMachineModel.id != exclude_id)
            if (await self.db.execute(query.limit(1))).scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Bu plaka numarası zaten mevcut",
                )

    # ---------- CREATE ----------
    async def create(
        self,
        data: CreateAllMachineSchema,
        created_by_id: int,
    ) -> AllMachineModel:
        # 1) FK-ları yoxla
        await self._validate_all_fks(data)

        # 2) VIN / plate unikal yoxla (əgər verilibsə)
        await self._ensure_unique_fields(data.vin_no, data.plate_no)

        # 3) Yarat
        machine = AllMachineModel(
            **data.model_dump(),
            created_by_id=created_by_id,
        )
        self.db.add(machine)

        try:
            await self.db.commit()
            await self.db.refresh(machine)
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Bu VIN veya plaka numarası zaten mevcut",
            )
        except Exception:
            await self.db.rollback()
            raise

        # Re-read so ``photos`` is eagerly loaded for the response model.
        return await self.fetch_by_id(machine.id)

    # ---------- FETCH (PAGINATION İLƏ) ----------
    async def fetch_paginated(
            self,
            limit: int = 20,
            offset: int = 0,
            identification_no: str | None = None,
            vin_no: str | None = None,
            plate_no: str | None = None,                                 # ← YENİ
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
        # ``photos`` is eagerly loaded: the response serializer runs outside the
        # session's greenlet context, where lazy loading would raise
        # MissingGreenlet.
        query = select(AllMachineModel).options(
            selectinload(AllMachineModel.photos)
        )
        count_query = select(func.count(AllMachineModel.id))  # ← BURADA

        # Filtrlər
        filters = []
        if identification_no:
            filters.append(
                AllMachineModel.identification_no.ilike(f"%{identification_no}%")
            )
        if vin_no:
            filters.append(AllMachineModel.vin_no.ilike(f"%{vin_no}%"))
        if plate_no:  # ← YENİ
            filters.append(AllMachineModel.plate_no.ilike(f"%{plate_no}%"))
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
            .order_by(AllMachineModel.identification_no.asc())
            .offset(offset)
            .limit(limit)
        )
        items_result = await self.db.execute(query)
        items = list(items_result.scalars().all())

        # print(items)



        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }



    async def fetch_by_id(self, machine_id: int) -> AllMachineModel:
        result = await self.db.execute(
            select(AllMachineModel)
            .options(selectinload(AllMachineModel.photos))
            .where(AllMachineModel.id == machine_id)
        )
        machine = result.scalar_one_or_none()
        if machine is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")
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

        # An open repair owns the machine status. Changing it manually would
        # leave the repair record out of sync with the machine, so require the
        # repair to be closed/cancelled first.
        if (
            "status_id" in data.model_fields_set
            and data.status_id is not None
            and data.status_id != machine.status_id
        ):
            active_repair = await self.db.execute(
                select(RepairRecordModel.id)
                .where(
                    RepairRecordModel.machine_id == machine_id,
                    RepairRecordModel.status == "tamirde",
                )
                .limit(1)
            )
            if active_repair.scalar_one_or_none() is not None:
                tamirde = await self.db.execute(
                    select(CarStatusModel.id)
                    .where(
                        func.lower(CarStatusModel.name) == "tamirde"
                    )
                    .limit(1)
                )
                if data.status_id != tamirde.scalar_one_or_none():
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Makinenin açık tamir kaydı var. Durumu değiştirmek "
                            "için önce Tamir sayfasından tamamlayın veya iptal "
                            "edin."
                        ),
                    )

        # VIN / plate unikal yoxla (özündən başqa)
        await self._ensure_unique_fields(
            data.vin_no, data.plate_no, exclude_id=machine_id
        )

        # Sahələri yenilə (yalnız göndərilənlər)
        update_data = data.model_dump(exclude_unset=True)
        if update_data.get("status_id") is None:
            update_data.pop("status_id", None)
        for field, value in update_data.items():
            setattr(machine, field, value)

        try:
            await self.db.commit()
            await self.db.refresh(machine)
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Bu VIN veya plaka numarası zaten mevcut",
            )
        except Exception:
            await self.db.rollback()
            raise

        # Re-read so ``photos`` is eagerly loaded for the response model.
        return await self.fetch_by_id(machine.id)

    # ---------- DELETE ----------
    async def delete(self, machine_id: int) -> None:
        machine = await self.fetch_by_id(machine_id)

        # Collect the S3 keys first: once the machine is gone the rows are lost.
        object_keys = [photo.object_key for photo in machine.photos]

        try:
            await self.db.delete(machine)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        # Best effort: the DB row is already deleted, so a storage failure must
        # not turn the request into an error (orphan objects are harmless).
        await delete_objects(object_keys)


    async def get_status_statistics(self) -> dict:
        """
        Hər status üçün maşın sayını qaytarır.
        LEFT JOIN — heç maşını olmayan status da görünür (count=0).
        """
        query = (
            select(
                CarStatusModel.id,
                CarStatusModel.name,
                CarStatusModel.color,
                func.count(AllMachineModel.id).label("count"),
            )
            .outerjoin(AllMachineModel, AllMachineModel.status_id == CarStatusModel.id)
            .group_by(CarStatusModel.id, CarStatusModel.name, CarStatusModel.color)
            .order_by(CarStatusModel.id)
        )

        result = await self.db.execute(query)
        rows = result.all()

        # Total
        total_query = select(func.count(AllMachineModel.id))
        total_result = await self.db.execute(total_query)
        total = total_result.scalar() or 0

        return {
            "total": total,
            "by_status": [
                {
                    "id": row.id,
                    "name": row.name,
                    "color": row.color,
                    "count": row.count,
                }
                for row in rows
            ],
        }

    async def get_type_territory_pivot(self) -> dict:
        """
        Type Transport × Territory pivot cədvəli.
        """
        # 1) Bütün territory-lər
        territories_result = await self.db.execute(
            select(TerritoryModel).order_by(TerritoryModel.id)
        )
        territories = list(territories_result.scalars().all())

        # 2) Bütün type-lar
        types_result = await self.db.execute(
            select(TypeTransportModel).order_by(TypeTransportModel.id)
        )
        types = list(types_result.scalars().all())

        # 3) Hər (type_id, territory_id) üçün say
        count_query = (
            select(
                AllMachineModel.type_id,
                AllMachineModel.territory_id,
                func.count(AllMachineModel.id).label("count"),
            )
            .where(
                AllMachineModel.type_id.isnot(None),
                AllMachineModel.territory_id.isnot(None),
            )
            .group_by(AllMachineModel.type_id, AllMachineModel.territory_id)
        )
        count_result = await self.db.execute(count_query)
        counts_map = {
            (row.type_id, row.territory_id): row.count
            for row in count_result.all()
        }

        # 4) Sətirləri hazırla
        rows = []
        grand_totals = {str(t.id): 0 for t in territories}
        grand_total = 0

        for t in types:
            counts = {}
            row_total = 0
            for territory in territories:
                c = counts_map.get((t.id, territory.id), 0)
                counts[str(territory.id)] = c
                row_total += c
                grand_totals[str(territory.id)] += c
            grand_total += row_total

            rows.append({
                "type_id": t.id,
                "type_name": t.name,
                "counts": counts,
                "total": row_total,
            })

        # 5) Toplam üzrə azalan sırala (B variantı)
        rows.sort(key=lambda r: r["total"], reverse=True)

        return {
            "territories": [
                {"id": t.id, "name": t.name} for t in territories
            ],
            "rows": rows,
            "grand_totals": grand_totals,
            "grand_total": grand_total,
        }


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
                detail="Bu ada sahip durum zaten mevcut",
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
            raise HTTPException(status_code=404, detail="Durum bulunamadı")
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
                    detail="Bu ada sahip durum zaten mevcut",
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
                detail="Bu durum makinelerde kullanıldığı için silinemez",
            )

        try:
            await self.db.delete(obj)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise