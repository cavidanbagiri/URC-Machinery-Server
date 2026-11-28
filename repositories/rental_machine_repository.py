# repositories/rental_machine_repository.py
"""Data access for the Kiralık Makine (rented machine) page.

The table derives two extra values per row (``status`` and ``days_remaining``)
from the rental dates, so no stored status can fall out of date.  Paging,
searching, the per-column filters and the machine-type statistics stay in SQL;
only the derived values are computed while the rows are mapped.

The equipment columns (tip / marka) are foreign keys into the same lookup
tables the fleet uses, and the repository joins them so every row carries its
display names.  ``equipment_name`` — the label the diesel ledger shows — is
rebuilt from those names on every save.

The separate model column was dropped (the table now shows one **Marka / Model**
column fed by the brand lookup), so the repository no longer joins
``car_models``.
"""

from datetime import date
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.machines_model import CarMarkModel, TypeTransportModel
from models.rental_machine_model import (
    RENTAL_STATUS_EXPIRED,
    RENTAL_STATUS_LABELS,
    RENTAL_STATUS_PLANNED,
    RENTAL_STATUSES,
    MachineRentalModel,
    compose_equipment_name,
    resolve_rental_status,
)
from models.user_model import UserModel
from schemas.rental_machine_schemas import RentalMachineWriteSchema

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

NOT_FOUND_DETAIL = "Kiralık makine kaydı bulunamadı"

#: Bucket of the statistics panel for rows without a machine type.
UNKNOWN_TYPE_NAME = "Bilinmeyen tip"


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


def contains_condition(column, value: Optional[str]):
    """``ILIKE %value%`` for a free-text column filter, or ``None`` if empty."""

    term = (value or "").strip()
    if not term:
        return None
    return column.ilike(f"%{term}%")


def type_stats_statement(filters: list, today: Optional[date] = None):
    """Select counting the rentals of every machine type.

    One query, grouped in SQL: ``total`` plus the three date-derived statuses,
    so the statistics panel never disagrees with the badges in the table.
    """

    reference = today or date.today()

    total = func.count(MachineRentalModel.id)

    return (
        select(
            MachineRentalModel.machine_type_id.label("type_id"),
            TypeTransportModel.name.label("type_name"),
            total.label("total"),
            func.sum(
                case(
                    (
                        and_(
                            MachineRentalModel.start_date <= reference,
                            MachineRentalModel.end_date >= reference,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("active_count"),
            func.sum(
                case((MachineRentalModel.start_date > reference, 1), else_=0)
            ).label("planned_count"),
            func.sum(
                case((MachineRentalModel.end_date < reference, 1), else_=0)
            ).label("expired_count"),
        )
        .select_from(MachineRentalModel)
        .outerjoin(
            TypeTransportModel,
            MachineRentalModel.machine_type_id == TypeTransportModel.id,
        )
        .where(*filters)
        .group_by(
            MachineRentalModel.machine_type_id,
            TypeTransportModel.name,
        )
        .order_by(total.desc(), TypeTransportModel.name.asc())
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
                TypeTransportModel.name.label("machine_type_name"),
                CarMarkModel.name.label("car_mark_name"),
                UserModel.firstname.label("creator_firstname"),
                UserModel.lastname.label("creator_lastname"),
            )
            .select_from(MachineRentalModel)
            .outerjoin(
                TypeTransportModel,
                MachineRentalModel.machine_type_id == TypeTransportModel.id,
            )
            .outerjoin(
                CarMarkModel,
                MachineRentalModel.car_mark_id == CarMarkModel.id,
            )
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
            "machine_type_id": rental.machine_type_id,
            "machine_type_name": row.machine_type_name,
            "car_mark_id": rental.car_mark_id,
            "car_mark_name": row.car_mark_name,
            "plate_no": rental.plate_no,
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
        machine_type_id: Optional[int] = None,
        car_mark_id: Optional[int] = None,
        plate: Optional[str] = None,
        company: Optional[str] = None,
        site: Optional[str] = None,
        start_from: Optional[date] = None,
        start_to: Optional[date] = None,
        end_from: Optional[date] = None,
        end_to: Optional[date] = None,
        today: Optional[date] = None,
    ) -> list:
        filters: list = []

        # Search box: covers the stored label (tip + marka + plaka on new rows)
        # and the free-text columns, so old rows stay findable.
        term = (search or "").strip()
        if term:
            pattern = f"%{term}%"
            filters.append(
                or_(
                    MachineRentalModel.equipment_name.ilike(pattern),
                    MachineRentalModel.company_name.ilike(pattern),
                    MachineRentalModel.site_name.ilike(pattern),
                    MachineRentalModel.plate_no.ilike(pattern),
                )
            )

        for condition in (
            contains_condition(MachineRentalModel.plate_no, plate),
            contains_condition(MachineRentalModel.company_name, company),
            contains_condition(MachineRentalModel.site_name, site),
        ):
            if condition is not None:
                filters.append(condition)

        # Lookup ids live on this table, so the count query needs no join.
        if machine_type_id:
            filters.append(MachineRentalModel.machine_type_id == machine_type_id)
        if car_mark_id:
            filters.append(MachineRentalModel.car_mark_id == car_mark_id)

        if start_from:
            filters.append(MachineRentalModel.start_date >= start_from)
        if start_to:
            filters.append(MachineRentalModel.start_date <= start_to)
        if end_from:
            filters.append(MachineRentalModel.end_date >= end_from)
        if end_to:
            filters.append(MachineRentalModel.end_date <= end_to)

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

    async def _type_stats(
        self,
        filters: list,
        today: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        rows = (await self.db.execute(type_stats_statement(filters, today))).all()

        return [
            {
                "type_id": row.type_id,
                "type_name": row.type_name or UNKNOWN_TYPE_NAME,
                "total": int(row.total or 0),
                "active_count": int(row.active_count or 0),
                "planned_count": int(row.planned_count or 0),
                "expired_count": int(row.expired_count or 0),
            }
            for row in rows
        ]

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
        machine_type_id: Optional[int] = None,
        car_mark_id: Optional[int] = None,
        plate: Optional[str] = None,
        company: Optional[str] = None,
        site: Optional[str] = None,
        start_from: Optional[date] = None,
        start_to: Optional[date] = None,
        end_from: Optional[date] = None,
        end_to: Optional[date] = None,
    ) -> dict[str, Any]:
        if limit < 1:
            limit = DEFAULT_LIMIT
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
        if offset < 0:
            offset = 0

        # One reference date per request so a page never mixes two days.
        today = date.today()

        common = {
            "search": search,
            "status": status,
            "machine_type_id": machine_type_id,
            "car_mark_id": car_mark_id,
            "plate": plate,
            "company": company,
            "site": site,
            "start_from": start_from,
            "start_to": start_to,
            "end_from": end_from,
            "end_to": end_to,
            "today": today,
        }
        filters = self._filters(**common)

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

        # The statistics panel keeps every type visible while one is selected,
        # so its counters ignore the type filter only.
        stats_filters = self._filters(**{**common, "machine_type_id": None})

        return {
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "items": [self._row_to_item(row, today) for row in result.all()],
            "type_stats": await self._type_stats(stats_filters, today),
        }

    # =========================================================
    # WRITE
    # =========================================================

    async def _lookup_name(self, model, entity_id: Optional[int], label: str):
        """Name of one lookup row, or a friendly 400 when the id is unknown."""

        if not entity_id:
            return None

        name = await self.db.scalar(select(model.name).where(model.id == entity_id))
        if not name:
            raise HTTPException(status_code=400, detail=f"{label} bulunamadı")
        return name

    async def _equipment_label(
        self,
        data: RentalMachineWriteSchema,
    ) -> str:
        """One-line ``equipment_name`` rebuilt from tip / marka / plaka."""

        return compose_equipment_name(
            type_name=await self._lookup_name(
                TypeTransportModel, data.machine_type_id, "Makine tipi"
            ),
            mark_name=await self._lookup_name(
                CarMarkModel, data.car_mark_id, "Marka"
            ),
            plate_no=data.plate_no,
            # Old clients still send the free-text name; it is kept as-is.
            fallback=data.equipment_name,
        )

    async def create(
        self,
        data: RentalMachineWriteSchema,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        rental = MachineRentalModel(
            equipment_name=await self._equipment_label(data),
            machine_type_id=data.machine_type_id,
            car_mark_id=data.car_mark_id,
            plate_no=data.plate_no,
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

        # Rebuild the one-line label so the diesel ledger never shows a stale
        # equipment description after tip / marka / plaka is edited.
        rental.equipment_name = await self._equipment_label(data)
        rental.machine_type_id = data.machine_type_id
        rental.car_mark_id = data.car_mark_id
        rental.plate_no = data.plate_no
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
    "UNKNOWN_TYPE_NAME",
    "RentalMachineRepository",
    "contains_condition",
    "rental_status_condition",
    "type_stats_statement",
]
