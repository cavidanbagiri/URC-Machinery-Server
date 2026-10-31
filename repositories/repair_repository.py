# repositories/repair_repository.py
"""Data access and business rules for machine repair (tamir) records."""

from datetime import date, timedelta
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.garage_service_model import GarageServiceModel
from models.machines_model import (
    AllMachineModel,
    CarMarkModel,
    CarModelModel,
    CarStatusModel,
    CompanyModel,
    TerritoryModel,
    TypeTransportModel,
)
from models.repair_model import RepairLogModel, RepairRecordModel, RepairTypeModel
from models.user_model import UserModel
from schemas.repair_schemas import (
    RepairCancelSchema,
    RepairCloseSchema,
    RepairCreateSchema,
    RepairNoteCreateSchema,
    RepairReopenSchema,
    RepairUpdateSchema,
)


# =========================================================
# STATUS DEFINITIONS
# =========================================================

REPAIR_STATUS_DEFINITIONS: dict[str, dict[str, str]] = {
    "tamirde": {"code": "tamirde", "name": "Tamirde", "color": "blue"},
    "tamamlandi": {"code": "tamamlandi", "name": "Tamamlandı", "color": "green"},
    "iptal": {"code": "iptal", "name": "İptal edildi", "color": "slate"},
}

REPAIR_STATUS_ORDER = ["tamirde", "tamamlandi", "iptal"]

# Quick open (from the machine status modal) creates an open repair without
# asking the user for any values. The details are filled in on the Repair page.
QUICK_OPEN_REPAIR_TYPE_NAME = "Diğer"


def repair_status(code: str) -> dict[str, str]:
    return dict(REPAIR_STATUS_DEFINITIONS[code])


def compute_repair_timing(
    status: str,
    entry_date: date,
    estimated_exit_date: Optional[date] = None,
    exit_date: Optional[date] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Return duration/remaining values used by the list and detail views."""

    current_day = today or date.today()
    duration_days = None
    if exit_date is not None:
        duration_days = max((exit_date - entry_date).days, 0)
    elif status == "tamirde":
        duration_days = max((current_day - entry_date).days, 0)

    days_remaining = None
    is_overdue = False
    if status == "tamirde" and estimated_exit_date is not None:
        days_remaining = (estimated_exit_date - current_day).days
        is_overdue = days_remaining < 0

    return {
        "duration_days": duration_days,
        "days_remaining": days_remaining,
        "is_overdue": is_overdue,
    }


def format_date_tr(value: Optional[date]) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def build_created_message(
    repair_type_name: str,
    fault_location: Optional[str],
    garage_service_name: Optional[str] = None,
) -> str:
    message = f"Tamir kaydı oluşturuldu. Tip: {repair_type_name}."
    if garage_service_name:
        message += f" Garaj servisi: {garage_service_name}."
    if fault_location:
        message += f" Arıza yeri: {fault_location}."
    return message


def build_quick_open_message() -> str:
    return (
        "Makine tamire alındı. Giriş/çıkış tarihleri ve detaylar "
        "Tamir sayfasından girilecek."
    )


def build_updated_message(changed_labels: list[str]) -> str:
    return "Tamir kaydı güncellendi: " + ", ".join(changed_labels) + "."


def suggest_exit_date(average_days: float, today: Optional[date] = None) -> date:
    days = max(int(round(average_days)), 1)
    return (today or date.today()) + timedelta(days=days)


# =========================================================
# REPOSITORY
# =========================================================

class RepairRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- HELPERS ----------

    def _base_select(self):
        return (
            select(
                RepairRecordModel,
                AllMachineModel,
                RepairTypeModel.name.label("repair_type_name"),
                GarageServiceModel.name.label("garage_service_name"),
                TerritoryModel.name.label("territory_name"),
                TypeTransportModel.name.label("type_name"),
                CompanyModel.name.label("company_name"),
                CarMarkModel.name.label("car_mark_name"),
                CarModelModel.name.label("car_model_name"),
                CarStatusModel.name.label("previous_machine_status_name"),
                UserModel.firstname.label("creator_firstname"),
                UserModel.lastname.label("creator_lastname"),
            )
            .select_from(RepairRecordModel)
            .join(AllMachineModel, RepairRecordModel.machine_id == AllMachineModel.id)
            .join(RepairTypeModel, RepairRecordModel.repair_type_id == RepairTypeModel.id)
            .outerjoin(
                GarageServiceModel,
                RepairRecordModel.garage_service_id == GarageServiceModel.id,
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
                CompanyModel,
                AllMachineModel.company_id == CompanyModel.id,
            )
            .outerjoin(CarMarkModel, AllMachineModel.car_mark_id == CarMarkModel.id)
            .outerjoin(CarModelModel, AllMachineModel.car_model_id == CarModelModel.id)
            .outerjoin(
                CarStatusModel,
                RepairRecordModel.previous_machine_status_id == CarStatusModel.id,
            )
            .outerjoin(UserModel, RepairRecordModel.created_by_id == UserModel.id)
        )

    def _row_to_item(
        self, row, logs: Optional[list[dict[str, Any]]] = None
    ) -> dict[str, Any]:
        record: RepairRecordModel = row[0]
        machine: AllMachineModel = row[1]
        timing = compute_repair_timing(
            record.status,
            record.entry_date,
            record.estimated_exit_date,
            record.exit_date,
        )
        creator_name = " ".join(
            part
            for part in (row.creator_firstname, row.creator_lastname)
            if part
        ).strip()

        return {
            "id": record.id,
            "machine_id": machine.id,
            "repair_type_id": record.repair_type_id,
            "repair_type_name": row.repair_type_name,
            "garage_service_id": record.garage_service_id,
            "garage_service_name": row.garage_service_name,
            "identification_no": machine.identification_no,
            "plate_no": machine.plate_no,
            "vin_no": machine.vin_no,
            "territory_id": machine.territory_id,
            "type_id": machine.type_id,
            "company_id": machine.company_id,
            "territory_name": row.territory_name,
            "type_name": row.type_name,
            "company_name": row.company_name,
            "car_mark_name": row.car_mark_name,
            "car_model_name": row.car_model_name,
            "fault_location": record.fault_location,
            "notes": record.notes,
            "entry_date": record.entry_date,
            "estimated_exit_date": record.estimated_exit_date,
            "exit_date": record.exit_date,
            "status": record.status,
            "status_detail": repair_status(record.status),
            "previous_machine_status_id": record.previous_machine_status_id,
            "previous_machine_status_name": row.previous_machine_status_name,
            "duration_days": timing["duration_days"],
            "days_remaining": timing["days_remaining"],
            "is_overdue": timing["is_overdue"],
            "created_by_id": record.created_by_id,
            "created_by_name": creator_name or None,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "logs": logs or [],
        }

    async def _logs_for_records(
        self, repair_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = {
            repair_id: [] for repair_id in repair_ids
        }
        if not repair_ids:
            return grouped

        result = await self.db.execute(
            select(
                RepairLogModel,
                UserModel.firstname,
                UserModel.lastname,
            )
            .outerjoin(UserModel, RepairLogModel.created_by_id == UserModel.id)
            .where(RepairLogModel.repair_id.in_(repair_ids))
            .order_by(RepairLogModel.created_at.asc(), RepairLogModel.id.asc())
        )
        for log, firstname, lastname in result.all():
            name = " ".join(part for part in (firstname, lastname) if part).strip()
            grouped.setdefault(log.repair_id, []).append(
                {
                    "id": log.id,
                    "repair_id": log.repair_id,
                    "event_type": log.event_type,
                    "message": log.message,
                    "created_by_id": log.created_by_id,
                    "created_by_name": name or None,
                    "created_at": log.created_at,
                }
            )
        return grouped

    async def _get_machine(self, machine_id: int) -> AllMachineModel:
        machine = await self.db.get(AllMachineModel, machine_id)
        if machine is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")
        return machine

    async def _get_repair_type(self, repair_type_id: int) -> RepairTypeModel:
        repair_type = await self.db.get(RepairTypeModel, repair_type_id)
        if repair_type is None:
            raise HTTPException(status_code=404, detail="Tamir tipi bulunamadı")
        return repair_type

    async def _get_garage_service(
        self, garage_service_id: int
    ) -> GarageServiceModel:
        garage_service = await self.db.get(GarageServiceModel, garage_service_id)
        if garage_service is None:
            raise HTTPException(status_code=404, detail="Garaj servisi bulunamadı")
        return garage_service

    async def _get_quick_open_repair_type(self) -> RepairTypeModel:
        """Prefer the catch-all "Diğer" type, then fall back to the first one."""
        result = await self.db.execute(
            select(RepairTypeModel)
            .where(
                func.lower(RepairTypeModel.name)
                == QUICK_OPEN_REPAIR_TYPE_NAME.lower()
            )
            .limit(1)
        )
        repair_type = result.scalars().first()
        if repair_type is not None:
            return repair_type

        result = await self.db.execute(
            select(RepairTypeModel).order_by(RepairTypeModel.id.asc()).limit(1)
        )
        repair_type = result.scalars().first()
        if repair_type is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Tamir tipi tanımlı değil. Ayarlar'dan en az bir tamir tipi "
                    "ekleyin."
                ),
            )
        return repair_type

    async def _get_record(self, repair_id: int) -> RepairRecordModel:
        record = await self.db.get(RepairRecordModel, repair_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Tamir kaydı bulunamadı")
        return record

    async def _get_tamirde_status(self) -> CarStatusModel:
        result = await self.db.execute(
            select(CarStatusModel).where(
                func.lower(CarStatusModel.name) == "tamirde"
            )
        )
        status = result.scalars().first()
        if status is None:
            raise HTTPException(
                status_code=500,
                detail="Tamirde makine durumu tanımlı değil",
            )
        return status

    async def _ensure_no_active_repair(
        self, machine_id: int, exclude_id: Optional[int] = None
    ) -> None:
        query = select(RepairRecordModel.id).where(
            RepairRecordModel.machine_id == machine_id,
            RepairRecordModel.status == "tamirde",
        )
        if exclude_id is not None:
            query = query.where(RepairRecordModel.id != exclude_id)
        if (await self.db.execute(query.limit(1))).scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="Bu makinenin aktif bir tamir kaydı zaten var",
            )

    async def _restore_machine_status(self, record: RepairRecordModel) -> None:
        machine = await self._get_machine(record.machine_id)
        tamirde = await self._get_tamirde_status()

        target_id = record.previous_machine_status_id
        if target_id is None or target_id == tamirde.id:
            result = await self.db.execute(
                select(CarStatusModel.id)
                .where(CarStatusModel.id != tamirde.id)
                .order_by(CarStatusModel.id.asc())
                .limit(1)
            )
            target_id = result.scalar_one_or_none()

        if target_id is not None:
            machine.status_id = target_id

    def _add_log(
        self,
        repair_id: int,
        event_type: str,
        message: str,
        created_by_id: Optional[int],
    ) -> None:
        self.db.add(
            RepairLogModel(
                repair_id=repair_id,
                event_type=event_type,
                message=message,
                created_by_id=created_by_id,
            )
        )

    # ---------- READ ----------

    async def _fetch_items(
        self,
        *,
        search: Optional[str] = None,
        status: Optional[str] = None,
        repair_type_id: Optional[int] = None,
        garage_service_id: Optional[int] = None,
        territory_id: Optional[int] = None,
        type_id: Optional[int] = None,
        company_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        overdue: Optional[bool] = None,
        due_soon: Optional[bool] = None,
    ) -> list[dict[str, Any]]:
        query = self._base_select()
        filters = []

        if search:
            pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    AllMachineModel.identification_no.ilike(pattern),
                    AllMachineModel.plate_no.ilike(pattern),
                    AllMachineModel.vin_no.ilike(pattern),
                    RepairRecordModel.fault_location.ilike(pattern),
                    RepairRecordModel.notes.ilike(pattern),
                    RepairTypeModel.name.ilike(pattern),
                )
            )
        if status:
            filters.append(RepairRecordModel.status == status)
        if repair_type_id is not None:
            filters.append(RepairRecordModel.repair_type_id == repair_type_id)
        if garage_service_id is not None:
            filters.append(
                RepairRecordModel.garage_service_id == garage_service_id
            )
        if territory_id is not None:
            filters.append(AllMachineModel.territory_id == territory_id)
        if type_id is not None:
            filters.append(AllMachineModel.type_id == type_id)
        if company_id is not None:
            filters.append(AllMachineModel.company_id == company_id)
        if date_from is not None:
            filters.append(RepairRecordModel.entry_date >= date_from)
        if date_to is not None:
            filters.append(RepairRecordModel.entry_date <= date_to)

        if filters:
            query = query.where(*filters)

        # Active repairs first, then newest entry date.
        query = query.order_by(
            case((RepairRecordModel.status == "tamirde", 0), else_=1),
            RepairRecordModel.entry_date.desc(),
            RepairRecordModel.id.desc(),
        )
        result = await self.db.execute(query)
        items = [self._row_to_item(row) for row in result.all()]

        if overdue is True:
            items = [item for item in items if item["is_overdue"]]
        if due_soon is True:
            items = [
                item
                for item in items
                if item["status"] == "tamirde"
                and item["days_remaining"] is not None
                and 0 <= item["days_remaining"] <= 3
            ]
        return items

    async def fetch_paginated(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        search: Optional[str] = None,
        status: Optional[str] = None,
        repair_type_id: Optional[int] = None,
        garage_service_id: Optional[int] = None,
        territory_id: Optional[int] = None,
        type_id: Optional[int] = None,
        company_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        overdue: Optional[bool] = None,
        due_soon: Optional[bool] = None,
    ) -> dict[str, Any]:
        if limit < 1:
            limit = 20
        if limit > 100:
            limit = 100
        if offset < 0:
            offset = 0

        items = await self._fetch_items(
            search=search,
            status=status,
            repair_type_id=repair_type_id,
            garage_service_id=garage_service_id,
            territory_id=territory_id,
            type_id=type_id,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            overdue=overdue,
            due_soon=due_soon,
        )
        return {
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "items": items[offset : offset + limit],
        }

    async def get_summary(self) -> dict[str, Any]:
        items = await self._fetch_items()
        today = date.today()

        counts = {code: 0 for code in REPAIR_STATUS_ORDER}
        for item in items:
            counts[item["status"]] = counts.get(item["status"], 0) + 1

        completed_durations = [
            item["duration_days"]
            for item in items
            if item["status"] == "tamamlandi"
            and item["duration_days"] is not None
        ]

        type_result = await self.db.execute(
            select(RepairTypeModel).order_by(RepairTypeModel.name.asc())
        )
        type_rows = list(type_result.scalars().all())
        by_type = []
        for repair_type in type_rows:
            type_items = [
                item for item in items if item["repair_type_id"] == repair_type.id
            ]
            by_type.append(
                {
                    "repair_type_id": repair_type.id,
                    "name": repair_type.name,
                    "count": len(type_items),
                    "active_count": sum(
                        1 for item in type_items if item["status"] == "tamirde"
                    ),
                }
            )

        return {
            "total": len(items),
            "active": counts["tamirde"],
            "completed": counts["tamamlandi"],
            "cancelled": counts["iptal"],
            "overdue": sum(1 for item in items if item["is_overdue"]),
            "due_soon": sum(
                1
                for item in items
                if item["status"] == "tamirde"
                and item["days_remaining"] is not None
                and 0 <= item["days_remaining"] <= 3
            ),
            "completed_this_month": sum(
                1
                for item in items
                if item["status"] == "tamamlandi"
                and item["exit_date"] is not None
                and item["exit_date"].year == today.year
                and item["exit_date"].month == today.month
            ),
            "average_repair_days": (
                round(sum(completed_durations) / len(completed_durations), 1)
                if completed_durations
                else None
            ),
            "by_status": [
                {**REPAIR_STATUS_DEFINITIONS[code], "count": counts[code]}
                for code in REPAIR_STATUS_ORDER
            ],
            "by_type": by_type,
        }

    async def get_machine_options(
        self, *, search: Optional[str] = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        if limit < 1:
            limit = 20
        if limit > 50:
            limit = 50

        active_machine_ids = select(RepairRecordModel.machine_id).where(
            RepairRecordModel.status == "tamirde"
        )
        query = (
            select(AllMachineModel, CarStatusModel.name.label("status_name"))
            .outerjoin(CarStatusModel, AllMachineModel.status_id == CarStatusModel.id)
            .where(AllMachineModel.id.not_in(active_machine_ids))
        )
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    AllMachineModel.identification_no.ilike(pattern),
                    AllMachineModel.plate_no.ilike(pattern),
                    AllMachineModel.vin_no.ilike(pattern),
                )
            )

        result = await self.db.execute(
            query.order_by(AllMachineModel.identification_no.asc()).limit(limit)
        )
        return [
            {
                "id": machine.id,
                "identification_no": machine.identification_no,
                "plate_no": machine.plate_no,
                "vin_no": machine.vin_no,
                "status_id": machine.status_id,
                "status_name": status_name,
            }
            for machine, status_name in result.all()
        ]

    async def get_estimate(self, repair_type_id: int) -> dict[str, Any]:
        repair_type = await self._get_repair_type(repair_type_id)

        async def durations_for(query_filter) -> list[int]:
            result = await self.db.execute(
                select(
                    RepairRecordModel.entry_date,
                    RepairRecordModel.exit_date,
                )
                .where(
                    RepairRecordModel.status == "tamamlandi",
                    RepairRecordModel.exit_date.is_not(None),
                    query_filter,
                )
                .order_by(RepairRecordModel.entry_date.desc())
                .limit(20)
            )
            return [
                max((exit_date - entry_date).days, 0)
                for entry_date, exit_date in result.all()
            ]

        type_durations = await durations_for(
            RepairRecordModel.repair_type_id == repair_type_id
        )
        if type_durations:
            durations = type_durations
            based_on = "repair_type"
        else:
            durations = await durations_for(RepairRecordModel.id.is_not(None))
            based_on = "all_repairs" if durations else "default"

        average_days = (
            round(sum(durations) / len(durations), 1) if durations else 7.0
        )
        return {
            "repair_type_id": repair_type.id,
            "repair_type_name": repair_type.name,
            "sample_size": len(durations),
            "average_days": average_days,
            "suggested_exit_date": suggest_exit_date(average_days),
            "based_on": based_on,
        }

    async def get_repair_types(self) -> list[RepairTypeModel]:
        result = await self.db.execute(
            select(RepairTypeModel).order_by(RepairTypeModel.name.asc())
        )
        return list(result.scalars().all())

    async def get_history(self, machine_id: int) -> list[dict[str, Any]]:
        await self._get_machine(machine_id)
        result = await self.db.execute(
            self._base_select()
            .where(RepairRecordModel.machine_id == machine_id)
            .order_by(
                RepairRecordModel.entry_date.desc(),
                RepairRecordModel.id.desc(),
            )
        )
        rows = result.all()
        records = [self._row_to_item(row) for row in rows]
        logs = await self._logs_for_records([record["id"] for record in records])
        for record in records:
            record["logs"] = logs.get(record["id"], [])
        return records

    async def get_detail(self, repair_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            self._base_select().where(RepairRecordModel.id == repair_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Tamir kaydı bulunamadı")

        logs = await self._logs_for_records([repair_id])
        return self._row_to_item(row, logs.get(repair_id, []))

    # ---------- WRITE ----------

    async def create_repair(
        self,
        data: RepairCreateSchema,
        created_by_id: Optional[int],
    ) -> dict[str, Any]:
        machine = await self._get_machine(data.machine_id)
        await self._ensure_no_active_repair(data.machine_id)
        repair_type = await self._get_repair_type(data.repair_type_id)
        garage_service = (
            await self._get_garage_service(data.garage_service_id)
            if data.garage_service_id is not None
            else None
        )
        tamirde = await self._get_tamirde_status()

        previous_status_id = (
            machine.status_id if machine.status_id != tamirde.id else None
        )
        record = RepairRecordModel(
            machine_id=data.machine_id,
            repair_type_id=data.repair_type_id,
            garage_service_id=(
                garage_service.id if garage_service is not None else None
            ),
            fault_location=data.fault_location,
            notes=data.notes,
            entry_date=data.entry_date,
            estimated_exit_date=data.estimated_exit_date,
            status="tamirde",
            previous_machine_status_id=previous_status_id,
            created_by_id=created_by_id,
        )

        try:
            self.db.add(record)
            await self.db.flush()
            repair_id = record.id
            self._add_log(
                repair_id,
                "created",
                build_created_message(
                    repair_type.name,
                    data.fault_location,
                    garage_service.name if garage_service is not None else None,
                ),
                created_by_id,
            )
            machine.status_id = tamirde.id
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Bu makinenin aktif bir tamir kaydı zaten var",
            )
        except Exception:
            await self.db.rollback()
            raise

        return await self.get_detail(repair_id)

    async def quick_open_repair(
        self,
        machine_id: int,
        created_by_id: Optional[int],
    ) -> dict[str, Any]:
        """Open a repair from the machine status modal without extra input.

        The machine is switched to ``Tamirde`` and an open repair is created with
        the catch-all type and today's entry date. Dates, type and notes are
        edited later on the Repair page. If an open repair already exists, it is
        returned unchanged so the operation is idempotent.
        """
        machine = await self._get_machine(machine_id)
        tamirde = await self._get_tamirde_status()

        result = await self.db.execute(
            select(RepairRecordModel.id)
            .where(
                RepairRecordModel.machine_id == machine_id,
                RepairRecordModel.status == "tamirde",
            )
            .limit(1)
        )
        existing_id = result.scalar_one_or_none()
        if existing_id is not None:
            if machine.status_id != tamirde.id:
                machine.status_id = tamirde.id
                try:
                    await self.db.commit()
                except Exception:
                    await self.db.rollback()
                    raise
            return await self.get_detail(existing_id)

        repair_type = await self._get_quick_open_repair_type()
        previous_status_id = (
            machine.status_id if machine.status_id != tamirde.id else None
        )
        record = RepairRecordModel(
            machine_id=machine_id,
            repair_type_id=repair_type.id,
            entry_date=date.today(),
            status="tamirde",
            previous_machine_status_id=previous_status_id,
            created_by_id=created_by_id,
        )

        try:
            self.db.add(record)
            await self.db.flush()
            repair_id = record.id
            self._add_log(
                repair_id,
                "created",
                build_quick_open_message(),
                created_by_id,
            )
            machine.status_id = tamirde.id
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            result = await self.db.execute(
                select(RepairRecordModel.id)
                .where(
                    RepairRecordModel.machine_id == machine_id,
                    RepairRecordModel.status == "tamirde",
                )
                .limit(1)
            )
            existing_id = result.scalar_one_or_none()
            if existing_id is not None:
                return await self.get_detail(existing_id)
            raise HTTPException(
                status_code=409,
                detail="Bu makinenin aktif bir tamir kaydı zaten var",
            )
        except Exception:
            await self.db.rollback()
            raise

        return await self.get_detail(repair_id)

    async def update_repair(
        self,
        repair_id: int,
        data: RepairUpdateSchema,
        updated_by_id: Optional[int],
    ) -> dict[str, Any]:
        record = await self._get_record(repair_id)
        if record.status != "tamirde":
            raise HTTPException(
                status_code=400,
                detail="Yalnızca aktif tamir kayıtları düzenlenebilir",
            )

        payload = data.model_dump(exclude_unset=True)
        if not payload:
            raise HTTPException(
                status_code=400,
                detail="Güncellenecek alan belirtilmedi",
            )
        if "repair_type_id" in payload and payload["repair_type_id"] is None:
            raise HTTPException(status_code=400, detail="Tamir tipi boş olamaz")
        if "entry_date" in payload and payload["entry_date"] is None:
            raise HTTPException(status_code=400, detail="Giriş tarihi boş olamaz")
        if (
            "garage_service_id" in payload
            and payload["garage_service_id"] is not None
        ):
            await self._get_garage_service(payload["garage_service_id"])

        new_entry = payload.get("entry_date", record.entry_date)
        new_estimated = (
            payload["estimated_exit_date"]
            if "estimated_exit_date" in payload
            else record.estimated_exit_date
        )
        if new_estimated is not None and new_estimated < new_entry:
            raise HTTPException(
                status_code=400,
                detail="Tahmini çıkış tarihi giriş tarihinden önce olamaz",
            )
        if record.exit_date is not None and record.exit_date < new_entry:
            raise HTTPException(
                status_code=400,
                detail="Giriş tarihi çıkış tarihinden sonra olamaz",
            )

        changed_labels = []
        label_map = {
            "repair_type_id": "tamir tipi",
            "fault_location": "arıza yeri",
            "notes": "notlar",
            "entry_date": "giriş tarihi",
            "estimated_exit_date": "tahmini çıkış tarihi",
        }

        if (
            "repair_type_id" in payload
            and payload["repair_type_id"] != record.repair_type_id
        ):
            new_type = await self._get_repair_type(payload["repair_type_id"])
            changed_labels.append(f"tamir tipi ({new_type.name})")
        if (
            "garage_service_id" in payload
            and payload["garage_service_id"] != record.garage_service_id
        ):
            if payload["garage_service_id"] is None:
                changed_labels.append("garaj servisi (kaldırıldı)")
            else:
                new_service = await self._get_garage_service(
                    payload["garage_service_id"]
                )
                changed_labels.append(f"garaj servisi ({new_service.name})")
        for field, label in label_map.items():
            if field == "repair_type_id":
                continue
            if field in payload and payload[field] != getattr(record, field):
                changed_labels.append(label)

        if not changed_labels:
            return await self.get_detail(repair_id)

        for field, value in payload.items():
            setattr(record, field, value)

        self._add_log(
            repair_id,
            "updated",
            build_updated_message(changed_labels),
            updated_by_id,
        )

        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return await self.get_detail(repair_id)

    async def close_repair(
        self,
        repair_id: int,
        data: RepairCloseSchema,
        updated_by_id: Optional[int],
    ) -> dict[str, Any]:
        record = await self._get_record(repair_id)
        if record.status != "tamirde":
            raise HTTPException(
                status_code=400,
                detail="Yalnızca aktif tamir kaydı tamamlanabilir",
            )
        if data.exit_date < record.entry_date:
            raise HTTPException(
                status_code=400,
                detail="Çıkış tarihi giriş tarihinden önce olamaz",
            )

        record.status = "tamamlandi"
        record.exit_date = data.exit_date
        await self._restore_machine_status(record)

        message = f"Tamir tamamlandı. Çıkış tarihi: {format_date_tr(data.exit_date)}."
        if data.notes:
            message += f" Not: {data.notes}"
        self._add_log(repair_id, "closed", message, updated_by_id)

        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return await self.get_detail(repair_id)

    async def cancel_repair(
        self,
        repair_id: int,
        data: RepairCancelSchema,
        updated_by_id: Optional[int],
    ) -> dict[str, Any]:
        record = await self._get_record(repair_id)
        if record.status != "tamirde":
            raise HTTPException(
                status_code=400,
                detail="Yalnızca aktif tamir kaydı iptal edilebilir",
            )

        record.status = "iptal"
        await self._restore_machine_status(record)
        self._add_log(
            repair_id,
            "cancelled",
            f"Tamir iptal edildi. Neden: {data.reason}",
            updated_by_id,
        )

        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return await self.get_detail(repair_id)

    async def reopen_repair(
        self,
        repair_id: int,
        data: RepairReopenSchema,
        updated_by_id: Optional[int],
    ) -> dict[str, Any]:
        record = await self._get_record(repair_id)
        if record.status == "tamirde":
            raise HTTPException(
                status_code=400,
                detail="Tamir kaydı zaten aktif",
            )

        await self._ensure_no_active_repair(record.machine_id, exclude_id=repair_id)
        machine = await self._get_machine(record.machine_id)
        tamirde = await self._get_tamirde_status()

        if machine.status_id != tamirde.id:
            record.previous_machine_status_id = machine.status_id
        record.status = "tamirde"
        record.exit_date = None
        machine.status_id = tamirde.id

        message = "Tamir kaydı yeniden açıldı."
        if data.notes:
            message += f" Not: {data.notes}"
        self._add_log(repair_id, "reopened", message, updated_by_id)

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Bu makinenin aktif bir tamir kaydı zaten var",
            )
        except Exception:
            await self.db.rollback()
            raise

        return await self.get_detail(repair_id)

    async def add_note(
        self,
        repair_id: int,
        data: RepairNoteCreateSchema,
        created_by_id: Optional[int],
    ) -> dict[str, Any]:
        await self._get_record(repair_id)
        self._add_log(
            repair_id,
            "note_added",
            f"Not eklendi: {data.note}",
            created_by_id,
        )

        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return await self.get_detail(repair_id)
