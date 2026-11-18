# repositories/fuel_log_repository.py
"""Data access for the append-only machine fuel distribution records.

There is deliberately no update or delete method here.  Every save inserts a
new row; the selected day's rows are aggregated per machine for the table and
the daily / weekly / monthly totals are computed from the same ledger.
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.fuel_log_model import MachineFuelLogModel
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
from models.user_model import UserModel
from repositories.car_status_lookup import exclude_scrap_machines
from schemas.fuel_log_schemas import FuelLogCreateSchema


class FuelLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- HELPERS ----------

    @staticmethod
    def _resolve_periods(target_date: date) -> tuple[date, date]:
        """Return the inclusive week start and the first day of the month."""

        return target_date - timedelta(days=6), target_date.replace(day=1)

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
            "fuel_date": row.fuel_date,
            "liters": float(row.liters),
            "given_by": row.given_by,
            "note": row.note,
            "entered_by_id": row.created_by_id,
            "entered_by_name": FuelLogRepository._creator_name(
                row.entered_by_firstname,
                row.entered_by_lastname,
            ),
            "created_at": row.created_at,
        }

    @staticmethod
    def _period_totals(
        rows,
        target_date: date,
        week_start: date,
        month_start: date,
    ) -> tuple[float, float, float]:
        """Sum dated aggregate rows into daily, weekly and monthly totals."""

        daily = weekly = monthly = 0.0

        for row in rows:
            amount = float(row.liters or 0)
            if row.fuel_date >= month_start:
                monthly += amount
            if row.fuel_date >= week_start:
                weekly += amount
            if row.fuel_date == target_date:
                daily += amount

        return daily, weekly, monthly

    # ---------- READ ----------

    async def fetch_overview(
        self,
        target_date: Optional[date] = None,
        search: Optional[str] = None,
    ) -> dict:
        target = target_date or date.today()
        week_start, month_start = self._resolve_periods(target)

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
            )
            .select_from(AllMachineModel)
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
                "day_liters": 0.0,
                "day_entry_count": 0,
                "last_given_by": None,
                "last_note": None,
                "last_created_at": None,
            }
            machines_by_id[item["machine_id"]] = item
            machines.append(item)

        if not machines:
            return {
                "fuel_date": target,
                "week_start": week_start,
                "month_start": month_start,
                "daily_total": 0.0,
                "weekly_total": 0.0,
                "monthly_total": 0.0,
                "machines": [],
            }

        day_query = (
            select(
                MachineFuelLogModel.id,
                MachineFuelLogModel.machine_id,
                MachineFuelLogModel.fuel_date,
                MachineFuelLogModel.liters,
                MachineFuelLogModel.given_by,
                MachineFuelLogModel.note,
                MachineFuelLogModel.created_by_id,
                MachineFuelLogModel.created_at,
                UserModel.firstname.label("entered_by_firstname"),
                UserModel.lastname.label("entered_by_lastname"),
            )
            .select_from(MachineFuelLogModel)
            .outerjoin(UserModel, MachineFuelLogModel.created_by_id == UserModel.id)
            .where(MachineFuelLogModel.fuel_date == target)
            .order_by(
                MachineFuelLogModel.created_at,
                MachineFuelLogModel.id,
            )
        )

        day_result = await self.db.execute(day_query)

        for row in day_result.all():
            item = machines_by_id.get(row.machine_id)
            if item is None:
                # A scrapped machine (or one outside the filtered set) keeps its
                # history but is not part of this page.
                continue

            item["day_liters"] += float(row.liters)
            item["day_entry_count"] += 1
            item["last_given_by"] = row.given_by
            item["last_note"] = row.note
            item["last_created_at"] = row.created_at

        # One grouped row per date is enough for all three summary boxes.  The
        # window starts at the earlier of the month and the rolling week so an
        # early-month week still includes the previous month's days.
        summary_start = min(week_start, month_start)
        active_machine_ids = select(AllMachineModel.id).where(*filters)

        summary_query = (
            select(
                MachineFuelLogModel.fuel_date.label("fuel_date"),
                func.sum(MachineFuelLogModel.liters).label("liters"),
            )
            .where(
                MachineFuelLogModel.fuel_date >= summary_start,
                MachineFuelLogModel.fuel_date <= target,
                MachineFuelLogModel.machine_id.in_(active_machine_ids),
            )
            .group_by(MachineFuelLogModel.fuel_date)
            .order_by(MachineFuelLogModel.fuel_date)
        )

        summary_result = await self.db.execute(summary_query)
        daily_total, weekly_total, monthly_total = self._period_totals(
            summary_result.all(),
            target,
            week_start,
            month_start,
        )

        return {
            "fuel_date": target,
            "week_start": week_start,
            "month_start": month_start,
            "daily_total": daily_total,
            "weekly_total": weekly_total,
            "monthly_total": monthly_total,
            "machines": machines,
        }

    # ---------- WRITE (INSERT ONLY) ----------

    async def create_log(
        self,
        data: FuelLogCreateSchema,
        user_id: int,
    ) -> MachineFuelLogModel:
        machine = await self.db.get(AllMachineModel, data.machine_id)
        if machine is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")

        log = MachineFuelLogModel(
            machine_id=data.machine_id,
            fuel_date=data.fuel_date,
            liters=float(data.liters),
            given_by=data.given_by,
            note=data.note,
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
