# repositories/meter_log_repository.py
"""Data access for the append-only machine meter readings.

There is deliberately no update or delete method here.  Every save inserts a
new row; the latest row per machine is the current KM / engine-hour value, the
rows inside the requested window feed the weekly matrix, and two derived
changes (since the previous day / since a month ago) fill the **Son Gün/KM**
and **1 Aylık Toplam** columns of the entry table.
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.machines_model import (
    AllMachineModel,
    CarMarkModel,
    CarModelModel,
    CarStatusModel,
    CompanyModel,
    SubTypeTransportModel,
    TerritoryModel,
    TypeTransportModel,
)
from models.meter_log_model import MachineMeterLogModel
from models.user_model import UserModel
from repositories.car_status_lookup import exclude_scrap_machines
from repositories.meter_log_lookup import latest_meter_log_subquery
from schemas.meter_log_schemas import MeterLogCreateSchema

MAX_OVERVIEW_DAYS = 31

#: "1 Aylık Toplam" penceresi: yeni okumadan geriye doğru bu kadar gün.
MONTH_CHANGE_DAYS = 30


class MeterLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- HELPERS ----------

    @staticmethod
    def _resolve_window(
        days: int,
        end_date: Optional[date],
    ) -> tuple[date, date]:
        """Return an inclusive ``(start, end)`` window ending on ``end_date``."""

        safe_days = max(1, min(int(days), MAX_OVERVIEW_DAYS))
        end = end_date or date.today()
        start = end - timedelta(days=safe_days - 1)
        return start, end

    @staticmethod
    def _creator_name(
        firstname: Optional[str],
        lastname: Optional[str],
    ) -> Optional[str]:
        name = " ".join(part for part in (firstname, lastname) if part).strip()
        return name or None

    @staticmethod
    def _entry(row) -> dict:
        return {
            "id": row.id,
            "machine_id": row.machine_id,
            "log_date": row.log_date,
            "km": float(row.km),
            "engine_hours": float(row.engine_hours),
            "entered_by_id": row.created_by_id,
            "entered_by_name": MeterLogRepository._creator_name(
                row.entered_by_firstname,
                row.entered_by_lastname,
            ),
            "created_at": row.created_at,
        }

    @staticmethod
    def _reading(row) -> dict:
        """One meter reading reduced to the fields the change columns need."""

        return {
            "log_date": row.log_date,
            "km": float(row.km),
            "engine_hours": float(row.engine_hours),
        }

    @staticmethod
    def _latest_per_day(rows: list[dict]) -> list[dict]:
        """Keep the **last** save of every day, oldest day first.

        Several readings can share a day (corrections are appended, never
        updated); the newest save wins, exactly like the entry table and the
        weekly matrix.
        """

        by_date: dict[date, dict] = {}
        for row in rows:
            by_date[row["log_date"]] = row

        return [by_date[key] for key in sorted(by_date)]

    @staticmethod
    def _difference(
        current: Optional[float],
        previous: Optional[float],
    ) -> Optional[float]:
        """``current - previous`` with two decimals, ``None`` when incomplete."""

        if current is None or previous is None:
            return None

        return round(float(current) - float(previous), 2)

    # ---------- READ ----------

    async def fetch_overview(
        self,
        days: int = 7,
        end_date: Optional[date] = None,
        search: Optional[str] = None,
    ) -> dict:
        start_date, window_end = self._resolve_window(days, end_date)

        # One row per machine = its newest reading across all history.  The
        # shared subquery keeps the repair/tire pickers in sync with this page.
        latest = latest_meter_log_subquery()

        filters = [exclude_scrap_machines()]

        term = (search or "").strip()
        if term:
            pattern = f"%{term}%"
            filters.append(
                or_(
                    AllMachineModel.identification_no.ilike(pattern),
                    AllMachineModel.plate_no.ilike(pattern),
                    AllMachineModel.vin_no.ilike(pattern),
                    TypeTransportModel.name.ilike(pattern),
                    SubTypeTransportModel.name.ilike(pattern),
                    CarMarkModel.name.ilike(pattern),
                    CarModelModel.name.ilike(pattern),
                    TerritoryModel.name.ilike(pattern),
                    CompanyModel.name.ilike(pattern),
                )
            )

        machine_query = (
            select(
                AllMachineModel.id.label("machine_id"),
                AllMachineModel.identification_no,
                AllMachineModel.plate_no,
                AllMachineModel.vin_no,
                TerritoryModel.name.label("territory_name"),
                TypeTransportModel.name.label("type_name"),
                SubTypeTransportModel.name.label("subtype_name"),
                CarMarkModel.name.label("car_mark_name"),
                CarModelModel.name.label("car_model_name"),
                CompanyModel.name.label("company_name"),
                CarStatusModel.name.label("status_name"),
                CarStatusModel.color.label("status_color"),
                latest.c.last_km,
                latest.c.last_engine_hours,
                latest.c.last_log_date,
                latest.c.last_logged_at,
            )
            .select_from(AllMachineModel)
            .outerjoin(
                latest,
                and_(
                    latest.c.machine_id == AllMachineModel.id,
                    latest.c.row_number == 1,
                ),
            )
            .outerjoin(
                TypeTransportModel,
                AllMachineModel.type_id == TypeTransportModel.id,
            )
            .outerjoin(
                SubTypeTransportModel,
                AllMachineModel.subtype_id == SubTypeTransportModel.id,
            )
            .outerjoin(CarMarkModel, AllMachineModel.car_mark_id == CarMarkModel.id)
            .outerjoin(CarModelModel, AllMachineModel.car_model_id == CarModelModel.id)
            .outerjoin(
                TerritoryModel,
                AllMachineModel.territory_id == TerritoryModel.id,
            )
            .outerjoin(CompanyModel, AllMachineModel.company_id == CompanyModel.id)
            .outerjoin(CarStatusModel, AllMachineModel.status_id == CarStatusModel.id)
            .where(*filters)
            .order_by(
                AllMachineModel.identification_no,
                AllMachineModel.plate_no,
                AllMachineModel.id,
            )
        )

        machine_result = await self.db.execute(machine_query)

        machines_by_id: dict[int, dict] = {}
        machines: list[dict] = []

        for row in machine_result.all():
            item = {
                "machine_id": row.machine_id,
                "identification_no": row.identification_no,
                "plate_no": row.plate_no,
                "vin_no": row.vin_no,
                "territory_name": row.territory_name,
                "type_name": row.type_name,
                "subtype_name": row.subtype_name,
                "car_mark_name": row.car_mark_name,
                "car_model_name": row.car_model_name,
                "company_name": row.company_name,
                "status_name": row.status_name,
                "status_color": row.status_color,
                "last_km": (
                    float(row.last_km) if row.last_km is not None else None
                ),
                "last_engine_hours": (
                    float(row.last_engine_hours)
                    if row.last_engine_hours is not None
                    else None
                ),
                "last_log_date": row.last_log_date,
                "last_logged_at": row.last_logged_at,
                "last_change_km": None,
                "last_change_engine_hours": None,
                "last_change_from_date": None,
                "month_change_km": None,
                "month_change_engine_hours": None,
                "month_change_from_date": None,
                "recent_logs": [],
            }
            machines_by_id[item["machine_id"]] = item
            machines.append(item)

        if not machines:
            return {
                "start_date": start_date,
                "end_date": window_end,
                "days": days,
                "total_recent_logs": 0,
                "machines": [],
            }

        # "Son Gün/KM" ve "1 Aylık Toplam" sütunları: pencere sorgusundan önce
        # hesaplanır, matris için ek sorgu maliyeti yoktur.
        await self._attach_changes(machines_by_id, window_end)

        recent_query = (
            select(
                MachineMeterLogModel.id,
                MachineMeterLogModel.machine_id,
                MachineMeterLogModel.log_date,
                MachineMeterLogModel.km,
                MachineMeterLogModel.engine_hours,
                MachineMeterLogModel.created_by_id,
                MachineMeterLogModel.created_at,
                UserModel.firstname.label("entered_by_firstname"),
                UserModel.lastname.label("entered_by_lastname"),
            )
            .select_from(MachineMeterLogModel)
            .outerjoin(UserModel, MachineMeterLogModel.created_by_id == UserModel.id)
            .where(
                MachineMeterLogModel.log_date >= start_date,
                MachineMeterLogModel.log_date <= window_end,
            )
            .order_by(
                MachineMeterLogModel.log_date,
                MachineMeterLogModel.created_at,
                MachineMeterLogModel.id,
            )
        )

        recent_result = await self.db.execute(recent_query)

        recent_by_machine: dict[int, list[dict]] = defaultdict(list)
        total_recent_logs = 0

        for row in recent_result.all():
            item = machines_by_id.get(row.machine_id)
            if item is None:
                # A scrapped machine (or one outside the filtered set) keeps its
                # history in the database but is not part of this page.
                continue
            recent_by_machine[row.machine_id].append(self._entry(row))
            total_recent_logs += 1

        for machine_id, item in machines_by_id.items():
            item["recent_logs"] = recent_by_machine.get(machine_id, [])

        return {
            "start_date": start_date,
            "end_date": window_end,
            "days": days,
            "total_recent_logs": total_recent_logs,
            "machines": machines,
        }

    async def _attach_changes(
        self,
        machines_by_id: dict[int, dict],
        window_end: date,
    ) -> None:
        """Fill the **Son Gün/KM** and **1 Aylık Toplam** columns.

        ``last_change_*`` is the newest reading minus the reading of the day
        before it; ``month_change_*`` the newest reading minus the **earliest**
        reading of the last ``MONTH_CHANGE_DAYS`` days.  The month total is
        therefore "at most a month": a machine that has been recorded for only
        five days shows the five-day total, and a machine with a single day of
        readings shows nothing (``None`` → "—") because there is nothing to
        compare.

        Newest readings are newer than ``window_end`` when the user picks a past
        day in the date box; the change columns follow the newest reading, just
        like ``last_km`` / ``last_engine_hours``, so all four agree.
        """

        if not machines_by_id:
            return

        latest_dates = [
            item["last_log_date"]
            for item in machines_by_id.values()
            if item.get("last_log_date")
        ]
        if not latest_dates:
            return

        anchor = max([window_end, *latest_dates])
        window_start = anchor - timedelta(days=MONTH_CHANGE_DAYS)
        machine_ids = list(machines_by_id)

        window_query = (
            select(
                MachineMeterLogModel.machine_id,
                MachineMeterLogModel.log_date,
                MachineMeterLogModel.km,
                MachineMeterLogModel.engine_hours,
            )
            .where(
                MachineMeterLogModel.machine_id.in_(machine_ids),
                MachineMeterLogModel.log_date >= window_start,
                MachineMeterLogModel.log_date <= anchor,
            )
            .order_by(
                MachineMeterLogModel.machine_id,
                MachineMeterLogModel.log_date,
                MachineMeterLogModel.created_at,
                MachineMeterLogModel.id,
            )
        )

        # Pencerenin hemen öncesindeki en yeni iki okuma: hem aylık taban hem de
        # pencerede tek okuması olan makinenin "önceki gün"ü buradan gelir.
        ranked = (
            select(
                MachineMeterLogModel.machine_id,
                MachineMeterLogModel.log_date,
                MachineMeterLogModel.km,
                MachineMeterLogModel.engine_hours,
                func.row_number()
                .over(
                    partition_by=MachineMeterLogModel.machine_id,
                    order_by=[
                        MachineMeterLogModel.log_date.desc(),
                        MachineMeterLogModel.created_at.desc(),
                        MachineMeterLogModel.id.desc(),
                    ],
                )
                .label("position"),
            )
            .where(
                MachineMeterLogModel.machine_id.in_(machine_ids),
                MachineMeterLogModel.log_date < window_start,
            )
            .subquery()
        )

        window_result = await self.db.execute(window_query)
        older_result = await self.db.execute(
            select(ranked).where(ranked.c.position <= 2)
        )

        window_by_machine: dict[int, list[dict]] = defaultdict(list)
        for row in window_result.all():
            if row.machine_id in machines_by_id:
                window_by_machine[row.machine_id].append(self._reading(row))

        older_by_machine: dict[int, list[dict]] = defaultdict(list)
        for row in older_result.all():
            if row.machine_id in machines_by_id:
                older_by_machine[row.machine_id].append(self._reading(row))

        for machine_id, item in machines_by_id.items():
            days = self._latest_per_day(window_by_machine.get(machine_id, []))
            history = self._latest_per_day(older_by_machine.get(machine_id, []))

            if days:
                newest = days[-1]
                previous = (
                    days[-2]
                    if len(days) > 1
                    else (history[-1] if history else None)
                )
                # "1 Aylık Toplam" = son 30 günün ilk okumasından bugüne kadar
                # olan fark.  Kısa geçmişte de çalışır (ör. 5 günlük veri);
                # tek günlük veride karşılaştırılacak ikinci okuma yoktur.
                baseline = days[0] if len(days) > 1 else None
            elif history:
                # Son bir ayda okuma yok: aylık toplam gösterilmez, "son
                # değişim" geçmişteki son iki okumadan hesaplanır.
                newest = history[-1]
                previous = history[-2] if len(history) > 1 else None
                baseline = None
            else:
                continue

            item["last_change_km"] = self._difference(
                newest["km"], previous["km"] if previous else None
            )
            item["last_change_engine_hours"] = self._difference(
                newest["engine_hours"], previous["engine_hours"] if previous else None
            )
            item["last_change_from_date"] = (
                previous["log_date"] if previous else None
            )

            item["month_change_km"] = self._difference(
                newest["km"], baseline["km"] if baseline else None
            )
            item["month_change_engine_hours"] = self._difference(
                newest["engine_hours"], baseline["engine_hours"] if baseline else None
            )
            item["month_change_from_date"] = (
                baseline["log_date"] if baseline else None
            )

    # ---------- WRITE (INSERT ONLY) ----------

    async def create_log(
        self,
        data: MeterLogCreateSchema,
        user_id: int,
    ) -> MachineMeterLogModel:
        machine = await self.db.get(AllMachineModel, data.machine_id)
        if machine is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")

        log = MachineMeterLogModel(
            machine_id=data.machine_id,
            log_date=data.log_date,
            km=float(data.km),
            engine_hours=float(data.engine_hours),
            created_by_id=user_id,
        )
        self.db.add(log)

        try:
            await self.db.commit()
            await self.db.refresh(log)
        except Exception:
            await self.db.rollback()
            raise

        return log
