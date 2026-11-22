# repositories/document_tracking_repository.py
"""Data access for the Evrak Takip Tablosu."""

from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.document_tracking_model import (
    DOCUMENT_DATE_FIELDS,
    MachineDocumentTrackingModel,
)
from models.machines_model import (
    AllMachineModel,
    CarMarkModel,
    CarModelModel,
    TerritoryModel,
    TypeTransportModel,
)
from models.user_model import UserModel
from repositories.car_status_lookup import exclude_scrap_machines
from schemas.document_tracking_schemas import DocumentTrackingUpdateSchema

DEFAULT_LIMIT = 100
MAX_LIMIT = 100


class DocumentTrackingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_select(self):
        return (
            select(
                AllMachineModel,
                MachineDocumentTrackingModel,
                TerritoryModel.name.label("territory_name"),
                TypeTransportModel.name.label("type_name"),
                CarMarkModel.name.label("car_mark_name"),
                CarModelModel.name.label("car_model_name"),
                UserModel.firstname.label("updater_firstname"),
                UserModel.lastname.label("updater_lastname"),
            )
            .select_from(AllMachineModel)
            .outerjoin(
                MachineDocumentTrackingModel,
                MachineDocumentTrackingModel.machine_id == AllMachineModel.id,
            )
            .outerjoin(
                TerritoryModel,
                AllMachineModel.territory_id == TerritoryModel.id,
            )
            .outerjoin(
                TypeTransportModel,
                AllMachineModel.type_id == TypeTransportModel.id,
            )
            .outerjoin(
                CarMarkModel,
                AllMachineModel.car_mark_id == CarMarkModel.id,
            )
            .outerjoin(
                CarModelModel,
                AllMachineModel.car_model_id == CarModelModel.id,
            )
            .outerjoin(
                UserModel,
                MachineDocumentTrackingModel.updated_by_id == UserModel.id,
            )
        )

    def _row_to_item(self, row) -> dict[str, Any]:
        machine: AllMachineModel = row[0]
        tracking: Optional[MachineDocumentTrackingModel] = row[1]
        updater_name = " ".join(
            part for part in (row.updater_firstname, row.updater_lastname) if part
        ).strip()

        item: dict[str, Any] = {
            "machine_id": machine.id,
            "identification_no": machine.identification_no,
            "plate_no": machine.plate_no,
            "territory_id": machine.territory_id,
            "type_id": machine.type_id,
            "car_mark_id": machine.car_mark_id,
            "car_model_id": machine.car_model_id,
            "territory_name": row.territory_name,
            "type_name": row.type_name,
            "car_mark_name": row.car_mark_name,
            "car_model_name": row.car_model_name,
            "updated_by_id": tracking.updated_by_id if tracking else None,
            "updated_by_name": updater_name or None,
            "updated_at": tracking.updated_at if tracking else None,
        }
        for field in DOCUMENT_DATE_FIELDS:
            item[field] = getattr(tracking, field, None) if tracking else None
        return item

    def _filters(
        self,
        *,
        search: Optional[str] = None,
        territory_id: Optional[int] = None,
        type_id: Optional[int] = None,
        car_mark_id: Optional[int] = None,
        car_model_id: Optional[int] = None,
    ) -> list:
        filters = [exclude_scrap_machines()]

        if search:
            pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    AllMachineModel.identification_no.ilike(pattern),
                    AllMachineModel.plate_no.ilike(pattern),
                    AllMachineModel.vin_no.ilike(pattern),
                    TerritoryModel.name.ilike(pattern),
                    TypeTransportModel.name.ilike(pattern),
                    CarMarkModel.name.ilike(pattern),
                    CarModelModel.name.ilike(pattern),
                )
            )
        if territory_id is not None:
            filters.append(AllMachineModel.territory_id == territory_id)
        if type_id is not None:
            filters.append(AllMachineModel.type_id == type_id)
        if car_mark_id is not None:
            filters.append(AllMachineModel.car_mark_id == car_mark_id)
        if car_model_id is not None:
            filters.append(AllMachineModel.car_model_id == car_model_id)

        return filters

    def _count_select(self, filters: list):
        # The search filters may reference lookup tables, so the count query
        # joins exactly the same tables as the list query. The tracking row is
        # irrelevant for the number of machines.
        return (
            select(func.count(AllMachineModel.id))
            .select_from(AllMachineModel)
            .outerjoin(
                TerritoryModel,
                AllMachineModel.territory_id == TerritoryModel.id,
            )
            .outerjoin(
                TypeTransportModel,
                AllMachineModel.type_id == TypeTransportModel.id,
            )
            .outerjoin(
                CarMarkModel,
                AllMachineModel.car_mark_id == CarMarkModel.id,
            )
            .outerjoin(
                CarModelModel,
                AllMachineModel.car_model_id == CarModelModel.id,
            )
            .where(*filters)
        )

    async def fetch_paginated(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        territory_id: Optional[int] = None,
        type_id: Optional[int] = None,
        car_mark_id: Optional[int] = None,
        car_model_id: Optional[int] = None,
    ) -> dict[str, Any]:
        if limit < 1:
            limit = DEFAULT_LIMIT
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
        if offset < 0:
            offset = 0

        filters = self._filters(
            search=search,
            territory_id=territory_id,
            type_id=type_id,
            car_mark_id=car_mark_id,
            car_model_id=car_model_id,
        )

        total = await self.db.scalar(self._count_select(filters)) or 0

        result = await self.db.execute(
            self._base_select()
            .where(*filters)
            .order_by(
                AllMachineModel.identification_no.asc().nulls_last(),
                AllMachineModel.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )

        return {
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "items": [self._row_to_item(row) for row in result.all()],
        }

    async def upsert(
        self,
        machine_id: int,
        data: DocumentTrackingUpdateSchema,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        """Create or replace the tracking row of one machine.

        The payload is a full row update, so a ``None`` date clears the stored
        value. The machine must exist; the table itself only lists non-scrapped
        machines.
        """

        machine = await self.db.get(AllMachineModel, machine_id)
        if machine is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")

        result = await self.db.execute(
            select(MachineDocumentTrackingModel).where(
                MachineDocumentTrackingModel.machine_id == machine_id
            )
        )
        tracking = result.scalar_one_or_none()

        if tracking is None:
            tracking = MachineDocumentTrackingModel(machine_id=machine_id)
            self.db.add(tracking)

        for field in DOCUMENT_DATE_FIELDS:
            setattr(tracking, field, getattr(data, field))
        tracking.updated_by_id = user_id

        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail=(
                    "Evrak kaydı aynı anda güncellendi; sayfayı yenileyip "
                    "tekrar deneyin"
                ),
            ) from exc

        row = (
            await self.db.execute(
                self._base_select().where(AllMachineModel.id == machine_id)
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")

        return self._row_to_item(row)
