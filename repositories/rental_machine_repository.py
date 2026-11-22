# repositories/rental_machine_repository.py
"""Data access for the Kiralık Makine (rented machine) page.

The table derives two extra values per row (``status`` and ``days_remaining``)
from the rental dates, so no stored status can fall out of date.  Paging,
searching and the status filter stay in SQL; only the derived values are
computed while the rows are mapped.
"""

from datetime import date
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.rental_machine_model import (
    RENTAL_STATUS_EXPIRED,
    RENTAL_STATUS_LABELS,
    RENTAL_STATUS_PLANNED,
    RENTAL_STATUSES,
    MachineRentalModel,
    resolve_rental_status,
)
from models.user_model import UserModel
from schemas.rental_machine_schemas import RentalMachineWriteSchema

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

NOT_FOUND_DETAIL = "Kiralık makine kaydı bulunamadı"


def rental_status_condition(status: str, today: Optional[date] = None):
    """SQL condition selecting the rows of ``status``.

    Mirrors :func:`models.rental_machine_model.resolve_rental_status`, which
    produces the badge of every row: a rental that starts today is active, one
    that ends today is still active, everything else is planned or expired.
    """

    reference = today or date.today()

    if status == RENTAL_STATUS_PLANNED:
        return MachineRentalModel.start_date > reference
    if status == RENTAL_STATUS_EXPIRED:
        return MachineRentalModel.end_date < reference
    return and_(
        MachineRentalModel.start_date <= reference,
        MachineRentalModel.end_date >= reference,
    )


class RentalMachineRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================
    # SELECT / MAPPING
    # =========================================================

    def _base_select(self):
        return (
            select(
                MachineRentalModel,
                UserModel.firstname.label("creator_firstname"),
                UserModel.lastname.label("creator_lastname"),
            )
            .select_from(MachineRentalModel)
            .outerjoin(
                UserModel,
                MachineRentalModel.created_by_id == UserModel.id,
            )
        )

    def _row_to_item(
        self,
        row,
        today: Optional[date] = None,
    ) -> dict[str, Any]:
        rental: MachineRentalModel = row[0]
        reference = today or date.today()

        status = resolve_rental_status(
            rental.start_date,
            rental.end_date,
            reference,
        )
        creator_name = " ".join(
            part
            for part in (row.creator_firstname, row.creator_lastname)
            if part
        ).strip()

        return {
            "id": rental.id,
            "equipment_name": rental.equipment_name,
            "company_name": rental.company_name,
            "site_name": rental.site_name,
            "start_date": rental.start_date,
            "end_date": rental.end_date,
            "status": status,
            "status_label": RENTAL_STATUS_LABELS.get(status, status),
            "days_remaining": (rental.end_date - reference).days,
            "duration_days": (rental.end_date - rental.start_date).days + 1,
            "created_by_id": rental.created_by_id,
            "created_by_name": creator_name or None,
            "created_at": rental.created_at,
            "updated_at": rental.updated_at,
        }

    def _filters(
        self,
        *,
        search: Optional[str] = None,
        status: Optional[str] = None,
        today: Optional[date] = None,
    ) -> list:
        filters: list = []

        term = (search or "").strip()
        if term:
            pattern = f"%{term}%"
            filters.append(
                or_(
                    MachineRentalModel.equipment_name.ilike(pattern),
                    MachineRentalModel.company_name.ilike(pattern),
                    MachineRentalModel.site_name.ilike(pattern),
                )
            )

        if status:
            if status not in RENTAL_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail="Geçersiz durum filtresi",
                )
            filters.append(rental_status_condition(status, today))

        return filters

    async def _fetch_item(
        self,
        rental_id: int,
        today: Optional[date] = None,
    ) -> dict[str, Any]:
        row = (
            await self.db.execute(
                self._base_select().where(MachineRentalModel.id == rental_id)
            )
        ).first()

        if row is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)

        return self._row_to_item(row, today)

    # =========================================================
    # LIST
    # =========================================================

    async def fetch_paginated(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict[str, Any]:
        if limit < 1:
            limit = DEFAULT_LIMIT
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
        if offset < 0:
            offset = 0

        # One reference date per request so a page never mixes two days.
        today = date.today()
        filters = self._filters(search=search, status=status, today=today)

        total = (
            await self.db.scalar(
                select(func.count(MachineRentalModel.id)).where(*filters)
            )
            or 0
        )

        result = await self.db.execute(
            self._base_select()
            .where(*filters)
            .order_by(
                MachineRentalModel.start_date.desc(),
                MachineRentalModel.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )

        return {
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "items": [self._row_to_item(row, today) for row in result.all()],
        }

    # =========================================================
    # WRITE
    # =========================================================

    async def create(
        self,
        data: RentalMachineWriteSchema,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        rental = MachineRentalModel(
            equipment_name=data.equipment_name,
            company_name=data.company_name,
            site_name=data.site_name,
            start_date=data.start_date,
            end_date=data.end_date,
            created_by_id=user_id,
        )
        self.db.add(rental)

        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail=(
                    "Kiralama kaydı kaydedilemedi; bilgileri kontrol edip "
                    "tekrar deneyin"
                ),
            ) from exc

        return await self._fetch_item(rental.id)

    async def update(
        self,
        rental_id: int,
        data: RentalMachineWriteSchema,
    ) -> dict[str, Any]:
        rental = await self.db.get(MachineRentalModel, rental_id)
        if rental is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)

        rental.equipment_name = data.equipment_name
        rental.company_name = data.company_name
        rental.site_name = data.site_name
        rental.start_date = data.start_date
        rental.end_date = data.end_date

        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail=(
                    "Kiralama kaydı güncellenemedi; bilgileri kontrol edip "
                    "tekrar deneyin"
                ),
            ) from exc

        return await self._fetch_item(rental_id)

    async def delete(self, rental_id: int) -> None:
        rental = await self.db.get(MachineRentalModel, rental_id)
        if rental is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)

        await self.db.delete(rental)
        await self.db.commit()


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "NOT_FOUND_DETAIL",
    "RentalMachineRepository",
    "rental_status_condition",
]
