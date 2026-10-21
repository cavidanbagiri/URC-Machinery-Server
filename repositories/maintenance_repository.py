# repositories/maintenance_repository.py
"""Data access for periodic maintenance plans, readings and history."""

from datetime import date
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.machines_model import (
    AllMachineModel,
    CarMarkModel,
    CarModelModel,
    CompanyModel,
    TerritoryModel,
    TypeTransportModel,
)
from models.maintenance_model import (
    MachineMaintenanceSettingModel,
    MaintenanceRecordModel,
)
from models.user_model import UserModel
from schemas.maintenance_schemas import (
    MaintenanceCompleteSchema,
    MaintenanceReadingCreateSchema,
    MaintenanceSettingUpdateSchema,
)


# =========================================================
# STATUS DEFINITIONS
# =========================================================

STATUS_DEFINITIONS: dict[str, dict[str, str]] = {
    "gecikmis": {"code": "gecikmis", "name": "Gecikmiş", "color": "red"},
    "yaklasiyor": {"code": "yaklasiyor", "name": "Yaklaşıyor", "color": "yellow"},
    "veri_uyarisi": {
        "code": "veri_uyarisi",
        "name": "Veri uyarısı",
        "color": "orange",
    },
    "veri_eksik": {"code": "veri_eksik", "name": "Veri eksik", "color": "gray"},
    "plan_yok": {"code": "plan_yok", "name": "Plan yok", "color": "gray"},
    "uygun": {"code": "uygun", "name": "Uygun", "color": "green"},
    "pasif": {"code": "pasif", "name": "Pasif", "color": "slate"},
}

STATUS_ORDER = [
    "gecikmis",
    "yaklasiyor",
    "veri_uyarisi",
    "veri_eksik",
    "plan_yok",
    "uygun",
    "pasif",
]

STATUS_PRIORITY = {code: index for index, code in enumerate(STATUS_ORDER)}


def _status(code: str) -> dict[str, str]:
    return dict(STATUS_DEFINITIONS[code])


def compute_maintenance_status(
    setting: MachineMaintenanceSettingModel | None,
) -> dict[str, Any]:
    """Return the calculated status and plan numbers for one setting.

    The function intentionally never clamps a negative remaining value; the UI
    needs to show how far past the interval the machine is.
    """

    if setting is None:
        return {
            "status": _status("plan_yok"),
            "remaining": None,
            "next_counter": None,
            "effective_warning_threshold": None,
            "is_active": False,
            "has_plan": False,
        }

    has_plan = True
    is_active = bool(setting.is_active)

    interval = setting.interval_value
    effective_threshold = None
    next_counter = None
    remaining = None

    if interval is not None:
        effective_threshold = (
            float(setting.warning_threshold)
            if setting.warning_threshold is not None
            else float(interval) * 0.1
        )
        if setting.last_counter is not None:
            next_counter = float(setting.last_counter) + float(interval)
            if setting.current_counter is not None:
                remaining = next_counter - float(setting.current_counter)

    if not is_active:
        status_code = "pasif"
    elif (
        setting.usage_unit not in ("km", "hour")
        or interval is None
        or float(interval) <= 0
        or setting.last_counter is None
        or setting.current_counter is None
    ):
        status_code = "veri_eksik"
    elif float(setting.current_counter) < float(setting.last_counter):
        status_code = "veri_uyarisi"
    elif remaining is not None and remaining <= 0:
        status_code = "gecikmis"
    elif (
        remaining is not None
        and effective_threshold is not None
        and remaining <= effective_threshold
    ):
        status_code = "yaklasiyor"
    else:
        status_code = "uygun"

    return {
        "status": _status(status_code),
        "remaining": remaining,
        "next_counter": next_counter,
        "effective_warning_threshold": effective_threshold,
        "is_active": is_active,
        "has_plan": has_plan,
    }


def _row_status_priority(item: dict[str, Any]) -> int:
    status = item.get("status") or {}
    return STATUS_PRIORITY.get(status.get("code"), len(STATUS_ORDER))


def _row_identity(item: dict[str, Any]) -> str:
    return str(item.get("identification_no") or "").upper()


def sort_maintenance_items(
    items: list[dict[str, Any]],
    *,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Sort maintenance rows in place and return the same list.

    The default order keeps the most urgent status groups on top. With
    ``sort_by="remaining"`` the rows are ordered by their remaining counter
    value instead. Rows without a computable remaining value (no plan, missing
    counters...) always stay at the end so they never push real work down the
    list — this holds for both directions.
    """

    if sort_by != "remaining":
        items.sort(
            key=lambda item: (
                _row_status_priority(item),
                (
                    item["remaining"]
                    if item["remaining"] is not None
                    else float("inf")
                ),
                _row_identity(item),
            )
        )
        return items

    planned = [item for item in items if item["remaining"] is not None]
    unplanned = [item for item in items if item["remaining"] is None]

    def tie_breaker(item: dict[str, Any]) -> tuple[int, str]:
        return (_row_status_priority(item), _row_identity(item))

    # Python's sort is stable: the first pass orders ties, the second pass
    # orders by the remaining value without disturbing the tie-breakers.
    planned.sort(key=tie_breaker)
    planned.sort(key=lambda item: item["remaining"], reverse=sort_order == "desc")
    unplanned.sort(key=tie_breaker)

    items[:] = [*planned, *unplanned]
    return items


class MaintenanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- HELPERS ----------

    def _base_select(self):
        return (
            select(
                AllMachineModel,
                MachineMaintenanceSettingModel,
                TerritoryModel.name.label("territory_name"),
                TypeTransportModel.name.label("type_name"),
                CompanyModel.name.label("company_name"),
                CarMarkModel.name.label("car_mark_name"),
                CarModelModel.name.label("car_model_name"),
            )
            .select_from(AllMachineModel)
            .outerjoin(
                MachineMaintenanceSettingModel,
                MachineMaintenanceSettingModel.machine_id == AllMachineModel.id,
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
        )

    def _row_to_item(self, row) -> dict[str, Any]:
        machine: AllMachineModel = row[0]
        setting: MachineMaintenanceSettingModel | None = row[1]
        calculated = compute_maintenance_status(setting)

        return {
            "machine_id": machine.id,
            "setting_id": setting.id if setting is not None else None,
            "identification_no": machine.identification_no,
            "plate_no": machine.plate_no,
            "territory_id": machine.territory_id,
            "type_id": machine.type_id,
            "company_id": machine.company_id,
            "machine_status_id": machine.status_id,
            "territory_name": row.territory_name,
            "type_name": row.type_name,
            "company_name": row.company_name,
            "car_mark_name": row.car_mark_name,
            "car_model_name": row.car_model_name,
            "has_plan": calculated["has_plan"],
            "usage_unit": setting.usage_unit if setting is not None else None,
            "interval_value": (
                float(setting.interval_value)
                if setting is not None and setting.interval_value is not None
                else None
            ),
            "last_counter": (
                float(setting.last_counter)
                if setting is not None and setting.last_counter is not None
                else None
            ),
            "last_maintenance_date": (
                setting.last_maintenance_date if setting is not None else None
            ),
            "current_counter": (
                float(setting.current_counter)
                if setting is not None and setting.current_counter is not None
                else None
            ),
            "current_counter_date": (
                setting.current_counter_date if setting is not None else None
            ),
            "next_counter": calculated["next_counter"],
            "remaining": calculated["remaining"],
            "warning_threshold": (
                float(setting.warning_threshold)
                if setting is not None and setting.warning_threshold is not None
                else None
            ),
            "effective_warning_threshold": calculated["effective_warning_threshold"],
            "is_active": calculated["is_active"],
            "notes": setting.notes if setting is not None else None,
            "status": calculated["status"],
        }

    async def _fetch_items(
        self,
        *,
        search: Optional[str] = None,
        usage_unit: Optional[str] = None,
        status: Optional[str] = None,
        has_plan: Optional[bool] = None,
        is_active: Optional[bool] = None,
        include_inactive: bool = False,
        territory_id: Optional[int] = None,
        type_id: Optional[int] = None,
        company_id: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
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
                )
            )
        if usage_unit:
            filters.append(MachineMaintenanceSettingModel.usage_unit == usage_unit)
        if territory_id is not None:
            filters.append(AllMachineModel.territory_id == territory_id)
        if type_id is not None:
            filters.append(AllMachineModel.type_id == type_id)
        if company_id is not None:
            filters.append(AllMachineModel.company_id == company_id)
        if has_plan is True:
            filters.append(MachineMaintenanceSettingModel.id.is_not(None))
        elif has_plan is False:
            filters.append(MachineMaintenanceSettingModel.id.is_(None))
        if is_active is True:
            filters.append(MachineMaintenanceSettingModel.is_active.is_(True))
        elif is_active is False:
            filters.append(MachineMaintenanceSettingModel.is_active.is_(False))
        elif not include_inactive:
            # Machines without a plan stay visible; explicitly deactivated
            # (e.g. "Pert") plans are hidden unless requested.
            filters.append(
                or_(
                    MachineMaintenanceSettingModel.id.is_(None),
                    MachineMaintenanceSettingModel.is_active.is_(True),
                )
            )

        if filters:
            query = query.where(*filters)

        result = await self.db.execute(query)
        items = [self._row_to_item(row) for row in result.all()]

        if status:
            items = [item for item in items if item["status"]["code"] == status]

        return sort_maintenance_items(items, sort_by=sort_by, sort_order=sort_order)

    async def _get_machine(self, machine_id: int) -> AllMachineModel:
        machine = await self.db.get(AllMachineModel, machine_id)
        if machine is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")
        return machine

    async def _get_setting(
        self, machine_id: int
    ) -> MachineMaintenanceSettingModel | None:
        result = await self.db.execute(
            select(MachineMaintenanceSettingModel).where(
                MachineMaintenanceSettingModel.machine_id == machine_id
            )
        )
        return result.scalar_one_or_none()

    async def _require_setting(self, machine_id: int) -> MachineMaintenanceSettingModel:
        await self._get_machine(machine_id)
        setting = await self._get_setting(machine_id)
        if setting is None:
            raise HTTPException(
                status_code=400,
                detail="Bu makine için bakım planı tanımlı değil",
            )
        return setting

    async def _get_item(self, machine_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            self._base_select().where(AllMachineModel.id == machine_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")
        return self._row_to_item(row)

    # ---------- READ ----------

    async def fetch_paginated(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        search: Optional[str] = None,
        usage_unit: Optional[str] = None,
        status: Optional[str] = None,
        has_plan: Optional[bool] = None,
        is_active: Optional[bool] = None,
        include_inactive: bool = False,
        territory_id: Optional[int] = None,
        type_id: Optional[int] = None,
        company_id: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> dict[str, Any]:
        if limit < 1:
            limit = 20
        if limit > 100:
            limit = 100
        if offset < 0:
            offset = 0

        items = await self._fetch_items(
            search=search,
            usage_unit=usage_unit,
            status=status,
            has_plan=has_plan,
            is_active=is_active,
            include_inactive=include_inactive,
            territory_id=territory_id,
            type_id=type_id,
            company_id=company_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = len(items)
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items[offset : offset + limit],
        }

    async def get_summary(self) -> dict[str, Any]:
        items = await self._fetch_items(include_inactive=True)

        counts = {code: 0 for code in STATUS_ORDER}
        for item in items:
            counts[item["status"]["code"]] = counts.get(item["status"]["code"], 0) + 1

        unit_counts: dict[str, int] = {}
        for item in items:
            if (
                item["has_plan"]
                and item["is_active"]
                and item["usage_unit"] in ("km", "hour")
            ):
                unit_counts[item["usage_unit"]] = (
                    unit_counts.get(item["usage_unit"], 0) + 1
                )

        return {
            "total": len(items),
            "planned": sum(
                1 for item in items if item["has_plan"] and item["is_active"]
            ),
            "unplanned": sum(1 for item in items if not item["has_plan"]),
            "inactive": sum(
                1 for item in items if item["has_plan"] and not item["is_active"]
            ),
            "overdue": counts["gecikmis"],
            "due_soon": counts["yaklasiyor"],
            "needs_attention": (
                counts["gecikmis"]
                + counts["yaklasiyor"]
                + counts["veri_uyarisi"]
                + counts["veri_eksik"]
            ),
            "by_status": [
                {**STATUS_DEFINITIONS[code], "count": counts[code]}
                for code in STATUS_ORDER
            ],
            "usage_units": [
                {"unit": "km", "count": unit_counts.get("km", 0)},
                {"unit": "hour", "count": unit_counts.get("hour", 0)},
            ],
        }

    async def get_history(
        self,
        machine_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        await self._get_machine(machine_id)

        if limit < 1:
            limit = 50
        if limit > 200:
            limit = 200
        if offset < 0:
            offset = 0

        result = await self.db.execute(
            select(
                MaintenanceRecordModel,
                UserModel.firstname,
                UserModel.lastname,
            )
            .outerjoin(UserModel, MaintenanceRecordModel.created_by_id == UserModel.id)
            .where(MaintenanceRecordModel.machine_id == machine_id)
            .order_by(
                MaintenanceRecordModel.record_date.desc(),
                MaintenanceRecordModel.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )

        records = []
        for record, firstname, lastname in result.all():
            name = " ".join(part for part in (firstname, lastname) if part).strip()
            records.append(
                {
                    "id": record.id,
                    "machine_id": record.machine_id,
                    "record_type": record.record_type,
                    "record_date": record.record_date,
                    "counter_value": record.counter_value,
                    "usage_unit": record.usage_unit,
                    "interval_value": record.interval_value,
                    "notes": record.notes,
                    "created_by_id": record.created_by_id,
                    "created_by_name": name or None,
                    "created_at": record.created_at,
                }
            )
        return records

    # ---------- WRITE ----------

    async def upsert_settings(
        self,
        machine_id: int,
        data: MaintenanceSettingUpdateSchema,
    ) -> dict[str, Any]:
        await self._get_machine(machine_id)
        setting = await self._get_setting(machine_id)
        payload = data.model_dump(exclude_unset=True)

        if setting is None:
            if data.usage_unit is None or data.interval_value is None:
                raise HTTPException(
                    status_code=400,
                    detail="Bakım planı için kullanım birimi ve periyot zorunludur",
                )
            setting = MachineMaintenanceSettingModel(
                machine_id=machine_id,
                usage_unit=data.usage_unit,
                interval_value=data.interval_value,
                is_active=True,
            )
            self.db.add(setting)

        if "usage_unit" in payload and payload["usage_unit"] is None:
            raise HTTPException(
                status_code=400, detail="Kullanım birimi boş olamaz"
            )
        if "interval_value" in payload and payload["interval_value"] is None:
            raise HTTPException(status_code=400, detail="Bakım periyodu boş olamaz")

        for field, value in payload.items():
            setattr(setting, field, value)

        # A counter edit without an explicit date is treated as "today".
        if "current_counter" in payload and "current_counter_date" not in payload:
            setting.current_counter_date = date.today()
        if "last_counter" in payload and "last_maintenance_date" not in payload:
            setting.last_maintenance_date = date.today()

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Bakım planı kaydedilemedi (çakışan kayıt)",
            )
        except Exception:
            await self.db.rollback()
            raise

        return await self._get_item(machine_id)

    async def record_reading(
        self,
        machine_id: int,
        data: MaintenanceReadingCreateSchema,
        created_by_id: int | None,
    ) -> dict[str, Any]:
        setting = await self._require_setting(machine_id)
        if not setting.is_active:
            raise HTTPException(
                status_code=400,
                detail="Pasif bakım planına sayaç kaydı eklenemez",
            )

        if (
            setting.current_counter is not None
            and data.counter_value < float(setting.current_counter)
        ):
            raise HTTPException(
                status_code=400,
                detail="Yeni sayaç değeri mevcut değerden küçük olamaz",
            )

        reading_date = data.reading_date or date.today()
        setting.current_counter = data.counter_value
        setting.current_counter_date = reading_date

        self.db.add(
            MaintenanceRecordModel(
                machine_id=machine_id,
                record_type="reading",
                record_date=reading_date,
                counter_value=data.counter_value,
                usage_unit=setting.usage_unit,
                interval_value=setting.interval_value,
                notes=data.notes,
                created_by_id=created_by_id,
            )
        )

        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return await self._get_item(machine_id)

    async def complete_maintenance(
        self,
        machine_id: int,
        data: MaintenanceCompleteSchema,
        created_by_id: int | None,
    ) -> dict[str, Any]:
        setting = await self._require_setting(machine_id)
        if not setting.is_active:
            raise HTTPException(
                status_code=400,
                detail="Pasif bakım planı tamamlanamaz",
            )

        counter = (
            data.counter_value
            if data.counter_value is not None
            else setting.current_counter
        )
        if counter is None:
            raise HTTPException(
                status_code=400,
                detail="Bakımı tamamlamak için sayaç değeri gerekli",
            )

        if (
            setting.current_counter is not None
            and float(counter) < float(setting.current_counter)
        ):
            raise HTTPException(
                status_code=400,
                detail="Bakım sayaç değeri mevcut değerden küçük olamaz",
            )

        maintenance_date = data.maintenance_date or date.today()
        setting.last_counter = counter
        setting.last_maintenance_date = maintenance_date
        setting.current_counter = counter
        setting.current_counter_date = maintenance_date

        self.db.add(
            MaintenanceRecordModel(
                machine_id=machine_id,
                record_type="maintenance",
                record_date=maintenance_date,
                counter_value=counter,
                usage_unit=setting.usage_unit,
                interval_value=setting.interval_value,
                notes=data.notes,
                created_by_id=created_by_id,
            )
        )

        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return await self._get_item(machine_id)
