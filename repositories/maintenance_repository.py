# repositories/maintenance_repository.py
"""Data access for periodic maintenance plans, readings and history."""

from datetime import date
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
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
    MAX_MAINTENANCE_DOCUMENT_BYTES,
    MachineMaintenanceSettingModel,
    MaintenanceDocumentModel,
    MaintenanceRecordModel,
)
from models.meter_log_model import MachineMeterLogModel
from models.user_model import UserModel
from repositories.car_status_lookup import exclude_scrap_machines
from repositories.machine_kind_lookup import exclude_trailer_machines
from repositories.meter_log_lookup import latest_meter_log_subquery
from repositories.pdf_documents import validate_document
from schemas.maintenance_schemas import (
    MaintenanceCompleteSchema,
    MaintenanceReadingCreateSchema,
    MaintenanceRecordType,
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

#: Maintenance packages offered when a maintenance is completed. These are
#: intentionally fixed per usage unit so the history stays comparable.
MAINTENANCE_INTERVAL_OPTIONS: dict[str, tuple[float, ...]] = {
    "km": (10_000.0, 20_000.0, 30_000.0, 40_000.0),
    "hour": (500.0, 1_000.0, 2_000.0, 4_000.0),
}


def validate_maintenance_interval(
    usage_unit: str | None,
    interval_value: float | None,
) -> float:
    """Return the selected package if it is valid for the machine unit."""

    allowed = MAINTENANCE_INTERVAL_OPTIONS.get(usage_unit or "", ())
    if interval_value is None:
        raise HTTPException(
            status_code=400,
            detail="Bakımı tamamlamak için bakım paketi seçmelisiniz",
        )

    value = float(interval_value)
    if value not in allowed:
        if allowed:
            allowed_text = ", ".join(f"{item:g}" for item in allowed)
            detail = f"Bu makine için geçerli bir bakım paketi seçin ({allowed_text})"
        else:
            detail = "Makinenin bakım birimi tanımlı olmadığı için bakım paketi seçilemez"
        raise HTTPException(status_code=400, detail=detail)

    return value


def _status(code: str) -> dict[str, str]:
    return dict(STATUS_DEFINITIONS[code])


def resolve_current_counter(
    setting: MachineMaintenanceSettingModel | None,
    *,
    meter_km: float | None = None,
    meter_engine_hours: float | None = None,
    meter_log_date: date | None = None,
) -> tuple[float | None, date | None, str | None]:
    """Return ``(value, date, source)`` of the machine's current counter.

    **Güncel KM ve Motor Saatleri** writes a ``machine_meter_logs`` row every
    day, so its newest row is the freshest truth for KM / engine hours on a
    planned machine.  The plan keeps its own ``current_counter`` (written by the
    readings / completions of this page) and remains the fallback.

    When both sources carry a value the newer date wins, and the meter row wins
    a tie (or when a date is missing), so an old meter reading can never make
    the counter jump backwards.
    """

    if setting is None:
        return None, None, None

    if setting.usage_unit == "km":
        meter_value = meter_km
    elif setting.usage_unit == "hour":
        meter_value = meter_engine_hours
    else:
        # An unknown unit cannot be compared with either meter column.
        meter_value = None

    plan_value = (
        float(setting.current_counter)
        if setting.current_counter is not None
        else None
    )
    plan_date = setting.current_counter_date

    if meter_value is None:
        if plan_value is None:
            return None, None, None
        return plan_value, plan_date, "plan"

    if plan_value is None:
        return float(meter_value), meter_log_date, "meter"

    if plan_date is not None and (
        meter_log_date is None or plan_date > meter_log_date
    ):
        return plan_value, plan_date, "plan"

    return float(meter_value), meter_log_date, "meter"


def compute_maintenance_status(
    setting: MachineMaintenanceSettingModel | None,
    *,
    live_counter: float | None = None,
) -> dict[str, Any]:
    """Return the calculated status and plan numbers for one setting.

    ``live_counter`` overrides ``setting.current_counter`` with the machine's
    freshest counter (see :func:`resolve_current_counter`).  The function
    intentionally never clamps a negative remaining value; the UI needs to show
    how far past the interval the machine is.
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

    current_counter = (
        live_counter if live_counter is not None else setting.current_counter
    )

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
            if current_counter is not None:
                remaining = next_counter - float(current_counter)

    if not is_active:
        status_code = "pasif"
    elif (
        setting.usage_unit not in ("km", "hour")
        or interval is None
        or float(interval) <= 0
        or setting.last_counter is None
        or current_counter is None
    ):
        status_code = "veri_eksik"
    elif float(current_counter) < float(setting.last_counter):
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
        # One row per machine = its newest KM / engine-hour reading.  The shared
        # subquery keeps this page and **Güncel KM ve Motor Saatleri** on the
        # same "latest" rule.
        latest_meter = latest_meter_log_subquery()

        return (
            select(
                AllMachineModel,
                MachineMaintenanceSettingModel,
                TerritoryModel.name.label("territory_name"),
                TypeTransportModel.name.label("type_name"),
                CompanyModel.name.label("company_name"),
                CarMarkModel.name.label("car_mark_name"),
                CarModelModel.name.label("car_model_name"),
                latest_meter.c.last_km.label("meter_km"),
                latest_meter.c.last_engine_hours.label("meter_engine_hours"),
                latest_meter.c.last_log_date.label("meter_log_date"),
            )
            .select_from(AllMachineModel)
            .outerjoin(
                MachineMaintenanceSettingModel,
                MachineMaintenanceSettingModel.machine_id == AllMachineModel.id,
            )
            .outerjoin(
                latest_meter,
                and_(
                    latest_meter.c.machine_id == AllMachineModel.id,
                    latest_meter.c.row_number == 1,
                ),
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

        meter_km = float(row.meter_km) if row.meter_km is not None else None
        meter_engine_hours = (
            float(row.meter_engine_hours)
            if row.meter_engine_hours is not None
            else None
        )
        meter_log_date = row.meter_log_date

        # The table shows (and the status uses) the freshest counter: the daily
        # KM / engine-hour reading when it is newer than the plan's own counter.
        current_counter, current_counter_date, counter_source = (
            resolve_current_counter(
                setting,
                meter_km=meter_km,
                meter_engine_hours=meter_engine_hours,
                meter_log_date=meter_log_date,
            )
        )
        calculated = compute_maintenance_status(
            setting,
            live_counter=current_counter,
        )

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
            # Effective counter (fresh meter reading or plan counter).
            "current_counter": current_counter,
            "current_counter_date": current_counter_date,
            "counter_source": counter_source,
            # The plan's own stored values stay editable in the plan modal.
            "plan_counter": (
                float(setting.current_counter)
                if setting is not None and setting.current_counter is not None
                else None
            ),
            "plan_counter_date": (
                setting.current_counter_date if setting is not None else None
            ),
            # Raw snapshot of the newest machine_meter_logs row.
            "meter_km": meter_km,
            "meter_engine_hours": meter_engine_hours,
            "meter_log_date": meter_log_date,
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
        car_mark_id: Optional[int] = None,
        car_model_id: Optional[int] = None,
        company_id: Optional[int] = None,
        updated_on: Optional[date] = None,
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
        if car_mark_id is not None:
            filters.append(AllMachineModel.car_mark_id == car_mark_id)
        if car_model_id is not None:
            filters.append(AllMachineModel.car_model_id == car_model_id)
        if company_id is not None:
            filters.append(AllMachineModel.company_id == company_id)
        if updated_on is not None:
            # "Güncelleme tarihi": machines touched on that day — a KM / motor
            # saati row from **Güncel KM ve Motor Saatleri** or a reading /
            # maintenance record created on this page.
            meter_update = (
                select(MachineMeterLogModel.id)
                .where(
                    MachineMeterLogModel.machine_id == AllMachineModel.id,
                    MachineMeterLogModel.log_date == updated_on,
                )
                .exists()
            )
            record_update = (
                select(MaintenanceRecordModel.id)
                .where(
                    MaintenanceRecordModel.machine_id == AllMachineModel.id,
                    MaintenanceRecordModel.record_date == updated_on,
                )
                .exists()
            )
            filters.append(or_(meter_update, record_update))
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

        # "Hurda" (scrapped) machines stay in the database but are never listed,
        # so they neither appear in the table nor in its summary counters.
        filters.append(exclude_scrap_machines())

        # TIR dorseleri (Tır Dorse tipi / TD-... kodlu) çekilen ekipmandır, kendi
        # motor saati / KM sayacı yoktur: Bakım listesinde ve özet kartlarında
        # görünmezler. Arıza, lastik, evrak gibi diğer modüllerde kalırlar.
        filters.append(exclude_trailer_machines())

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
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        usage_unit: Optional[str] = None,
        status: Optional[str] = None,
        has_plan: Optional[bool] = None,
        is_active: Optional[bool] = None,
        include_inactive: bool = False,
        territory_id: Optional[int] = None,
        type_id: Optional[int] = None,
        car_mark_id: Optional[int] = None,
        car_model_id: Optional[int] = None,
        company_id: Optional[int] = None,
        updated_on: Optional[date] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> dict[str, Any]:
        if limit < 1:
            limit = 100
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
            car_mark_id=car_mark_id,
            car_model_id=car_model_id,
            company_id=company_id,
            updated_on=updated_on,
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

        # Completed maintenance history: readings are ignored.  ("Günlük
        # Bakım" used to live on the summary cards; the date filter of the page
        # now drills into a single day instead of only counting it.)
        completed = (
            await self.db.scalar(
                select(func.count())
                .select_from(MaintenanceRecordModel)
                .where(MaintenanceRecordModel.record_type == "maintenance")
            )
        ) or 0

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
            "completed": int(completed),
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
        record_type: Optional[MaintenanceRecordType] = None,
    ) -> list[dict[str, Any]]:
        await self._get_machine(machine_id)

        if limit < 1:
            limit = 50
        if limit > 200:
            limit = 200
        if offset < 0:
            offset = 0

        query = (
            select(
                MaintenanceRecordModel,
                UserModel.firstname,
                UserModel.lastname,
            )
            .outerjoin(UserModel, MaintenanceRecordModel.created_by_id == UserModel.id)
            .where(MaintenanceRecordModel.machine_id == machine_id)
        )
        # The drawer used to show readings and maintenance events together.
        # Machine detail tabs ask for one kind only ("Bakım Geçmişi" must not
        # be filled with counter readings).
        if record_type is not None:
            query = query.where(MaintenanceRecordModel.record_type == record_type)

        result = await self.db.execute(
            query.order_by(
                MaintenanceRecordModel.record_date.desc(),
                MaintenanceRecordModel.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )

        rows = result.all()
        documents_by_record = await self._get_documents_by_record(
            [record.id for record, _, _ in rows]
        )

        records = []
        for record, firstname, lastname in rows:
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
                    "documents": documents_by_record.get(record.id, []),
                }
            )
        return records

    async def _get_documents_by_record(
        self, record_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        """Load the PDF metadata of the history rows in one query (no bytes)."""

        if not record_ids:
            return {}

        result = await self.db.execute(
            select(
                MaintenanceDocumentModel,
                UserModel.firstname,
                UserModel.lastname,
            )
            .outerjoin(
                UserModel,
                MaintenanceDocumentModel.uploaded_by_id == UserModel.id,
            )
            .where(MaintenanceDocumentModel.record_id.in_(record_ids))
            .order_by(
                MaintenanceDocumentModel.record_id.asc(),
                MaintenanceDocumentModel.id.asc(),
            )
        )

        grouped: dict[int, list[dict[str, Any]]] = {}
        for document, firstname, lastname in result.all():
            name = " ".join(part for part in (firstname, lastname) if part).strip()
            grouped.setdefault(document.record_id, []).append(
                {
                    "id": document.id,
                    "record_id": document.record_id,
                    "file_name": document.file_name,
                    "content_type": document.content_type,
                    "file_size": document.file_size,
                    "uploaded_by_id": document.uploaded_by_id,
                    "uploaded_by_name": name or None,
                    "created_at": document.created_at,
                }
            )
        return grouped

    async def get_document(self, document_id: int) -> MaintenanceDocumentModel:
        document = await self.db.get(MaintenanceDocumentModel, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Evrak bulunamadı")
        return document

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
        *,
        document: tuple[Optional[str], Optional[str], bytes] | None = None,
    ) -> dict[str, Any]:
        # Every completed maintenance must carry its PDF paper. The file is
        # validated before the plan/record are touched and stored in the same
        # transaction, so a rejected upload cannot complete the maintenance.
        if document is None:
            raise HTTPException(
                status_code=400,
                detail="Bakımı tamamlamak için PDF evrak yüklemelisiniz",
            )

        try:
            file_info = validate_document(
                document[0],
                document[1],
                document[2],
                max_bytes=MAX_MAINTENANCE_DOCUMENT_BYTES,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        setting = await self._require_setting(machine_id)
        if not setting.is_active:
            raise HTTPException(
                status_code=400,
                detail="Pasif bakım planı tamamlanamaz",
            )

        interval_value = validate_maintenance_interval(
            setting.usage_unit,
            data.interval_value,
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

        record = MaintenanceRecordModel(
            machine_id=machine_id,
            record_type="maintenance",
            record_date=maintenance_date,
            counter_value=counter,
            usage_unit=setting.usage_unit,
            # Snapshot the package performed in this service. The plan's own
            # interval stays untouched and continues to drive the next due.
            interval_value=interval_value,
            notes=data.notes,
            created_by_id=created_by_id,
        )

        try:
            self.db.add(record)
            # Flush first so the document can reference the new record id.
            await self.db.flush()
            self.db.add(
                MaintenanceDocumentModel(
                    record_id=record.id,
                    file_name=file_info["file_name"],
                    content_type=file_info["content_type"],
                    file_size=file_info["file_size"],
                    file_data=document[2],
                    uploaded_by_id=created_by_id,
                )
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return await self._get_item(machine_id)
