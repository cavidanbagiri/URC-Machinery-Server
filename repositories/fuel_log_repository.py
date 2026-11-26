# repositories/fuel_log_repository.py
"""Data access for the machine diesel distribution records.

Every save inserts a new row; the selected day's rows are aggregated per
machine for the table and the daily / weekly / monthly totals are computed from
the same ledger.  A row can be **corrected** afterwards
(:meth:`FuelLogRepository.update_log`): entering the 24th's diesel on the 25th
is a common mistake, so the *İşlemler → Düzenle* dialog moves the row to the
right day (and fixes the litres) instead of appending a compensating row.

Besides the fuel ledger the overview joins:

* ``machine_meter_logs`` - the newest KM / engine-hour reading of every machine
  ("Güncel KM / Saat"), the same snapshot the **Güncel KM ve Motor Saatleri**
  page shows, and the counter movement used to calculate the average
  consumption (liters per 1 km or per 1 engine hour).
* ``machine_maintenance_settings.usage_unit`` - tells whether that machine is
  tracked on its odometer (``km``) or on its engine hour meter (``hour``).
* ``territories`` - the two main sites (SRU / DCU) get their own current-month
  summary card.
* ``machine_rental_fuel_logs`` - the diesel handed to **rented** machines.  That
  ledger points at ``machine_rentals`` instead of ``all_machines`` and is served
  by ``repositories/rental_fuel_log_repository.py`` for the *Kiralık* tab.
* ``fetch_daily_distribution`` - the dashboard's **Mazot Dağılımı** chart: the
  last 7 days with one grouped bar per day (SRU, DCU and the rented fleet).
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
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
from models.maintenance_model import MachineMaintenanceSettingModel
from models.meter_log_model import MachineMeterLogModel
from models.rental_fuel_log_model import MachineRentalFuelLogModel
from models.user_model import UserModel
from repositories.car_status_lookup import exclude_scrap_machines
from repositories.fuel_log_window import (
    DEFAULT_EDIT_WINDOW_DAYS,
    resolve_edit_window,
)
from repositories.meter_log_lookup import latest_meter_log_subquery
from repositories.rental_fuel_log_repository import RentalFuelLogRepository
from schemas.fuel_log_schemas import FuelLogCreateSchema, FuelLogUpdateSchema

#: Territory names that get a separate current-month summary card.
SRU_TERRITORY_NAME = "SRU"
DCU_TERRITORY_NAME = "DCU"

#: Not-found details shared by the create / correct endpoints.
MACHINE_NOT_FOUND_DETAIL = "Makine bulunamadı"
ENTRY_NOT_FOUND_DETAIL = "Mazot kaydı bulunamadı"

#: Dashboard diesel chart: rolling window and its hard limits.
DEFAULT_DISTRIBUTION_DAYS = 7
MAX_DISTRIBUTION_DAYS = 31

#: A consumption average needs the counter to move at least one full unit;
#: smaller movements (e.g. a forklift moving 0.2 km) would only amplify noise.
MIN_CONSUMPTION_DELTA = 1.0


class FuelLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- HELPERS ----------

    @staticmethod
    def _resolve_periods(target_date: date) -> tuple[date, date]:
        """Return the inclusive week start and the first day of the month."""

        return target_date - timedelta(days=6), target_date.replace(day=1)

    @staticmethod
    def _previous_month_bounds(month_start: date) -> tuple[date, date]:
        """Return the inclusive bounds of the month before ``month_start``."""

        previous_end = month_start - timedelta(days=1)
        return previous_end.replace(day=1), previous_end

    @staticmethod
    def _creator_name(
        firstname: Optional[str],
        lastname: Optional[str],
    ) -> Optional[str]:
        name = " ".join(part for part in (firstname, lastname) if part).strip()
        return name or None

    @staticmethod
    def _entry_query():
        """Row-level ``SELECT`` of ``machine_fuel_logs`` with the author name.

        Shared by the correction dialog list and by the single-row refresh
        after an update, so both always expose the same columns.
        """

        return (
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
        )

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
        previous_start: Optional[date] = None,
        previous_end: Optional[date] = None,
    ) -> dict:
        """Sum dated aggregate rows into daily, weekly, monthly and previous-month totals."""

        totals = {
            "daily": 0.0,
            "weekly": 0.0,
            "monthly": 0.0,
            "previous_month": 0.0,
        }

        for row in rows:
            amount = float(row.liters or 0)
            if (
                previous_start is not None
                and previous_end is not None
                and previous_start <= row.fuel_date <= previous_end
            ):
                totals["previous_month"] += amount
            if row.fuel_date >= month_start:
                totals["monthly"] += amount
            if row.fuel_date >= week_start:
                totals["weekly"] += amount
            if row.fuel_date == target_date:
                totals["daily"] += amount

        return totals

    @staticmethod
    def _territory_total(rows, territory_name: str) -> float:
        """Sum the current-month liters of one territory, matched by name."""

        wanted = (territory_name or "").strip().casefold()
        return sum(
            float(row.liters or 0)
            for row in rows
            if (row.territory_name or "").strip().casefold() == wanted
        )

    @staticmethod
    def _territory_bucket(territory_name: Optional[str]) -> Optional[str]:
        """Map a territory name onto a chart series (``"sru"`` / ``"dcu"``)."""

        wanted = (territory_name or "").strip().casefold()
        if not wanted:
            return None
        if wanted == SRU_TERRITORY_NAME.strip().casefold():
            return "sru"
        if wanted == DCU_TERRITORY_NAME.strip().casefold():
            return "dcu"
        return None

    @staticmethod
    def _build_distribution(
        start_date: date,
        end_date: date,
        sru_by_day: dict[date, float],
        dcu_by_day: dict[date, float],
        rental_by_day: dict[date, float],
    ) -> dict:
        """Assemble one item per calendar day for the dashboard diesel chart.

        Days without any row are kept (with zeros) so the bar groups always line
        up with the requested window instead of collapsing to the days that
        happen to have data.
        """

        items: list[dict] = []
        totals = {"sru": 0.0, "dcu": 0.0, "rental": 0.0}

        day = start_date
        while day <= end_date:
            sru = round(float(sru_by_day.get(day) or 0), 2)
            dcu = round(float(dcu_by_day.get(day) or 0), 2)
            rental = round(float(rental_by_day.get(day) or 0), 2)

            items.append(
                {
                    "fuel_date": day,
                    "sru_liters": sru,
                    "dcu_liters": dcu,
                    "rental_liters": rental,
                    "total_liters": round(sru + dcu + rental, 2),
                }
            )

            totals["sru"] += sru
            totals["dcu"] += dcu
            totals["rental"] += rental
            day += timedelta(days=1)

        return {
            "start_date": start_date,
            "end_date": end_date,
            "days": len(items),
            "sru_total": round(totals["sru"], 2),
            "dcu_total": round(totals["dcu"], 2),
            "rental_total": round(totals["rental"], 2),
            "total": round(
                totals["sru"] + totals["dcu"] + totals["rental"],
                2,
            ),
            "items": items,
        }

    @staticmethod
    def _consumption(
        liters: Optional[float],
        km_delta: Optional[float],
        hours_delta: Optional[float],
        usage_unit: Optional[str],
    ) -> tuple[Optional[str], Optional[float]]:
        """Return ``(unit, liters per unit)`` for the machine's average.

        The maintenance setting decides the preferred counter (``km`` machines
        use the odometer, ``hour`` machines the engine hour meter).  When that
        counter did not move - or the machine has no setting at all - the other
        counter is used instead, so an average is shown whenever the data
        allows it.  ``(None, None)`` means "not enough data".
        """

        if liters is None or float(liters) <= 0:
            return None, None

        order = ("hour", "km")
        if (usage_unit or "").strip().casefold() != "hour":
            order = ("km", "hour")

        for unit in order:
            delta = hours_delta if unit == "hour" else km_delta
            if delta is None:
                continue
            if float(delta) < MIN_CONSUMPTION_DELTA:
                continue
            return unit, round(float(liters) / float(delta), 4)

        return None, None

    # ---------- READ ----------

    async def fetch_overview(
        self,
        target_date: Optional[date] = None,
        search: Optional[str] = None,
    ) -> dict:
        target = target_date or date.today()
        week_start, month_start = self._resolve_periods(target)

        # Kiralık sekmesi (rented machines) keeps its own append-only ledger in
        # ``machine_rental_fuel_logs``; the section is merged into the same
        # payload so the page still needs a single request.
        rental_section = await RentalFuelLogRepository(self.db).fetch_section(
            target_date=target,
            search=search,
        )

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

        # Newest KM / engine-hour reading of every machine, shared with the
        # meter-log page and the repair/tire forms.
        latest = latest_meter_log_subquery()

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
                MachineMaintenanceSettingModel.usage_unit.label("usage_unit"),
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
                MachineMaintenanceSettingModel,
                MachineMaintenanceSettingModel.machine_id == AllMachineModel.id,
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
                "day_liters": 0.0,
                "day_entry_count": 0,
                "last_given_by": None,
                "last_note": None,
                "last_created_at": None,
                "last_km": (
                    float(row.last_km) if row.last_km is not None else None
                ),
                "last_engine_hours": (
                    float(row.last_engine_hours)
                    if row.last_engine_hours is not None
                    else None
                ),
                "last_log_date": row.last_log_date,
                "usage_unit": (row.usage_unit or "").strip().lower() or None,
                "consumption_unit": None,
                "avg_consumption": None,
                "consumption_liters": None,
                "consumption_distance": None,
                "consumption_start_date": None,
                "consumption_end_date": None,
            }
            machines_by_id[item["machine_id"]] = item
            machines.append(item)

        previous_start, previous_end = self._previous_month_bounds(month_start)

        if not machines:
            return {
                "fuel_date": target,
                "week_start": week_start,
                "month_start": month_start,
                "previous_month_start": previous_start,
                "previous_month_end": previous_end,
                "daily_total": 0.0,
                "weekly_total": 0.0,
                "monthly_total": 0.0,
                "previous_month_total": 0.0,
                "sru_monthly_total": 0.0,
                "dcu_monthly_total": 0.0,
                **rental_section,
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

        # One grouped row per date is enough for the daily / weekly / monthly
        # boxes and for the complete previous month.  The window starts at the
        # earliest of the rolling week, the current month and the previous
        # month, so an early-month week still includes the previous month's days.
        summary_start = min(week_start, month_start, previous_start)
        # Summary boxes describe the whole fleet: they deliberately ignore the
        # search term so a filtered table never shows partial totals.
        summary_machine_ids = select(AllMachineModel.id).where(
            exclude_scrap_machines()
        )

        summary_query = (
            select(
                MachineFuelLogModel.fuel_date.label("fuel_date"),
                func.sum(MachineFuelLogModel.liters).label("liters"),
            )
            .where(
                MachineFuelLogModel.fuel_date >= summary_start,
                MachineFuelLogModel.fuel_date <= target,
                MachineFuelLogModel.machine_id.in_(summary_machine_ids),
            )
            .group_by(MachineFuelLogModel.fuel_date)
            .order_by(MachineFuelLogModel.fuel_date)
        )

        summary_result = await self.db.execute(summary_query)
        totals = self._period_totals(
            summary_result.all(),
            target,
            week_start,
            month_start,
            previous_start,
            previous_end,
        )

        # Current-month liters of the two main sites.  The group-by runs in SQL
        # and the SRU / DCU rows are picked by name below, so adding or renaming
        # another territory never breaks the page.
        territory_query = (
            select(
                TerritoryModel.name.label("territory_name"),
                func.sum(MachineFuelLogModel.liters).label("liters"),
            )
            .select_from(MachineFuelLogModel)
            .join(
                AllMachineModel,
                AllMachineModel.id == MachineFuelLogModel.machine_id,
            )
            .outerjoin(
                TerritoryModel,
                TerritoryModel.id == AllMachineModel.territory_id,
            )
            .where(
                MachineFuelLogModel.fuel_date >= month_start,
                MachineFuelLogModel.fuel_date <= target,
                MachineFuelLogModel.machine_id.in_(summary_machine_ids),
            )
            .group_by(TerritoryModel.name)
        )

        territory_result = await self.db.execute(territory_query)
        territory_rows = territory_result.all()

        await self._attach_consumption(machines_by_id)

        return {
            "fuel_date": target,
            "week_start": week_start,
            "month_start": month_start,
            "previous_month_start": previous_start,
            "previous_month_end": previous_end,
            "daily_total": totals["daily"],
            "weekly_total": totals["weekly"],
            "monthly_total": totals["monthly"],
            "previous_month_total": totals["previous_month"],
            "sru_monthly_total": self._territory_total(
                territory_rows, SRU_TERRITORY_NAME
            ),
            "dcu_monthly_total": self._territory_total(
                territory_rows, DCU_TERRITORY_NAME
            ),
            **rental_section,
            "machines": machines,
        }

    async def fetch_entries(
        self,
        machine_id: int,
        target_date: Optional[date] = None,
        days: int = DEFAULT_EDIT_WINDOW_DAYS,
    ) -> list[dict]:
        """Recent diesel rows of one machine, newest first.

        Feeds the **İşlemler → Düzenle** dialog: the page lists the row the
        user wants to correct (typically the row saved on the wrong day) and the
        row is updated in place by :meth:`update_log`.
        """

        machine = await self.db.get(AllMachineModel, machine_id)
        if machine is None:
            raise HTTPException(status_code=404, detail=MACHINE_NOT_FOUND_DETAIL)

        start_date, end_date = resolve_edit_window(target_date, days)

        result = await self.db.execute(
            self._entry_query()
            .where(
                MachineFuelLogModel.machine_id == machine_id,
                MachineFuelLogModel.fuel_date >= start_date,
                MachineFuelLogModel.fuel_date <= end_date,
            )
            .order_by(
                MachineFuelLogModel.fuel_date.desc(),
                MachineFuelLogModel.created_at.desc(),
                MachineFuelLogModel.id.desc(),
            )
        )

        return [self._entry(row) for row in result.all()]

    async def fetch_entry(self, log_id: int) -> dict:
        """One diesel row, mapped exactly like the list items."""

        result = await self.db.execute(
            self._entry_query().where(MachineFuelLogModel.id == log_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail=ENTRY_NOT_FOUND_DETAIL)

        return self._entry(row)

    async def fetch_daily_distribution(
        self,
        days: int = DEFAULT_DISTRIBUTION_DAYS,
        end_date: Optional[date] = None,
    ) -> dict:
        """Daily diesel liters of SRU, DCU and the rented fleet.

        Used by the dashboard's **Mazot Dağılımı** chart: one bar group per day,
        three series.  SRU / DCU liters come from ``machine_fuel_logs`` joined
        with the machine's territory (scrapped machines are excluded, exactly
        like the page's summary boxes) and the rental series comes from the
        separate rented-machine ledger (``machine_rental_fuel_logs``).
        """

        end = end_date or date.today()
        span = int(days or DEFAULT_DISTRIBUTION_DAYS)
        span = max(1, min(span, MAX_DISTRIBUTION_DAYS))
        start = end - timedelta(days=span - 1)

        machine_ids = select(AllMachineModel.id).where(exclude_scrap_machines())

        # Liters per day per territory; SRU / DCU are picked by name below so an
        # extra territory never breaks the chart.
        territory_query = (
            select(
                MachineFuelLogModel.fuel_date.label("fuel_date"),
                TerritoryModel.name.label("territory_name"),
                func.sum(MachineFuelLogModel.liters).label("liters"),
            )
            .select_from(MachineFuelLogModel)
            .join(
                AllMachineModel,
                AllMachineModel.id == MachineFuelLogModel.machine_id,
            )
            .outerjoin(
                TerritoryModel,
                TerritoryModel.id == AllMachineModel.territory_id,
            )
            .where(
                MachineFuelLogModel.fuel_date >= start,
                MachineFuelLogModel.fuel_date <= end,
                MachineFuelLogModel.machine_id.in_(machine_ids),
            )
            .group_by(
                MachineFuelLogModel.fuel_date,
                TerritoryModel.name,
            )
        )

        territory_result = await self.db.execute(territory_query)

        sru_by_day: dict[date, float] = defaultdict(float)
        dcu_by_day: dict[date, float] = defaultdict(float)

        for row in territory_result.all():
            bucket = self._territory_bucket(row.territory_name)
            if bucket == "sru":
                sru_by_day[row.fuel_date] += float(row.liters or 0)
            elif bucket == "dcu":
                dcu_by_day[row.fuel_date] += float(row.liters or 0)

        # Kiralık sekmesi: diesel we handed to rented equipment.
        rental_query = (
            select(
                MachineRentalFuelLogModel.fuel_date.label("fuel_date"),
                func.sum(MachineRentalFuelLogModel.liters).label("liters"),
            )
            .where(
                MachineRentalFuelLogModel.fuel_date >= start,
                MachineRentalFuelLogModel.fuel_date <= end,
            )
            .group_by(MachineRentalFuelLogModel.fuel_date)
        )

        rental_result = await self.db.execute(rental_query)
        rental_by_day: dict[date, float] = {
            row.fuel_date: float(row.liters or 0) for row in rental_result.all()
        }

        return self._build_distribution(
            start,
            end,
            sru_by_day,
            dcu_by_day,
            rental_by_day,
        )

    async def _attach_consumption(self, machines_by_id: dict[int, dict]) -> None:
        """Fill the average consumption of every machine on the page.

        The average is ``liters / counter movement``: the liters handed over
        between the baseline reading and the newest reading, divided by the KM
        (or engine hours) the machine covered in the same window.  The baseline
        is the newest reading on/before the first fuel row of that machine, so
        the fuel and the counter cover the same period; machines that started
        recording meters after their first fuel row fall back to their oldest
        reading.
        """

        machine_ids = [
            machine_id
            for machine_id, item in machines_by_id.items()
            if item.get("last_log_date") is not None
        ]
        if not machine_ids:
            return

        first_fuel = (
            select(
                MachineFuelLogModel.machine_id.label("machine_id"),
                func.min(MachineFuelLogModel.fuel_date).label("fuel_start"),
            )
            .where(MachineFuelLogModel.machine_id.in_(machine_ids))
            .group_by(MachineFuelLogModel.machine_id)
            .subquery()
        )

        # Newest reading at/before the machine's first fuel row.
        baseline_ranked = (
            select(
                MachineMeterLogModel.machine_id.label("machine_id"),
                MachineMeterLogModel.log_date.label("log_date"),
                MachineMeterLogModel.km.label("km"),
                MachineMeterLogModel.engine_hours.label("engine_hours"),
                func.row_number()
                .over(
                    partition_by=MachineMeterLogModel.machine_id,
                    order_by=[
                        MachineMeterLogModel.log_date.desc(),
                        MachineMeterLogModel.created_at.desc(),
                        MachineMeterLogModel.id.desc(),
                    ],
                )
                .label("row_number"),
            )
            .select_from(MachineMeterLogModel)
            .join(
                first_fuel,
                first_fuel.c.machine_id == MachineMeterLogModel.machine_id,
            )
            .where(MachineMeterLogModel.log_date <= first_fuel.c.fuel_start)
            .subquery()
        )

        baseline_result = await self.db.execute(
            select(
                baseline_ranked.c.machine_id,
                baseline_ranked.c.log_date,
                baseline_ranked.c.km,
                baseline_ranked.c.engine_hours,
            ).where(baseline_ranked.c.row_number == 1)
        )
        baselines = {row.machine_id: row for row in baseline_result.all()}

        # Oldest reading of every instrumented machine (fallback baseline).
        earliest_ranked = (
            select(
                MachineMeterLogModel.machine_id.label("machine_id"),
                MachineMeterLogModel.log_date.label("log_date"),
                MachineMeterLogModel.km.label("km"),
                MachineMeterLogModel.engine_hours.label("engine_hours"),
                func.row_number()
                .over(
                    partition_by=MachineMeterLogModel.machine_id,
                    order_by=[
                        MachineMeterLogModel.log_date.asc(),
                        MachineMeterLogModel.created_at.asc(),
                        MachineMeterLogModel.id.asc(),
                    ],
                )
                .label("row_number"),
            )
            .where(MachineMeterLogModel.machine_id.in_(machine_ids))
            .subquery()
        )

        earliest_result = await self.db.execute(
            select(
                earliest_ranked.c.machine_id,
                earliest_ranked.c.log_date,
                earliest_ranked.c.km,
                earliest_ranked.c.engine_hours,
            ).where(earliest_ranked.c.row_number == 1)
        )
        for row in earliest_result.all():
            baselines.setdefault(row.machine_id, row)

        fuel_query = (
            select(
                MachineFuelLogModel.machine_id,
                MachineFuelLogModel.fuel_date,
                func.sum(MachineFuelLogModel.liters).label("liters"),
            )
            .where(MachineFuelLogModel.machine_id.in_(machine_ids))
            .group_by(
                MachineFuelLogModel.machine_id,
                MachineFuelLogModel.fuel_date,
            )
        )

        fuel_result = await self.db.execute(fuel_query)
        fuel_by_machine: dict[int, list[tuple[date, float]]] = defaultdict(list)
        for row in fuel_result.all():
            fuel_by_machine[row.machine_id].append(
                (row.fuel_date, float(row.liters or 0))
            )

        for machine_id, item in machines_by_id.items():
            baseline = baselines.get(machine_id)
            if baseline is None:
                continue

            start_date = baseline.log_date
            end_date = item.get("last_log_date")
            if start_date is None or end_date is None or end_date <= start_date:
                continue

            liters = sum(
                amount
                for day, amount in fuel_by_machine.get(machine_id, [])
                if start_date <= day <= end_date
            )

            km_delta = (item.get("last_km") or 0) - (baseline.km or 0)
            hours_delta = (item.get("last_engine_hours") or 0) - (
                baseline.engine_hours or 0
            )
            unit, value = self._consumption(
                liters,
                km_delta,
                hours_delta,
                item.get("usage_unit"),
            )

            item["consumption_unit"] = unit
            item["avg_consumption"] = value
            if unit is None:
                continue

            item["consumption_liters"] = round(liters, 2)
            item["consumption_distance"] = round(
                hours_delta if unit == "hour" else km_delta,
                2,
            )
            item["consumption_start_date"] = start_date
            item["consumption_end_date"] = end_date

    # ---------- WRITE ----------

    async def create_log(
        self,
        data: FuelLogCreateSchema,
        user_id: int,
        given_by: Optional[str] = None,
    ) -> MachineFuelLogModel:
        machine = await self.db.get(AllMachineModel, data.machine_id)
        if machine is None:
            raise HTTPException(status_code=404, detail=MACHINE_NOT_FOUND_DETAIL)

        log = MachineFuelLogModel(
            machine_id=data.machine_id,
            fuel_date=data.fuel_date,
            liters=float(data.liters),
            # The table no longer asks who handed the fuel over; the router
            # passes the signed-in user's name as the fallback.
            given_by=data.given_by or given_by or "Sistem",
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

    async def update_log(self, log_id: int, data: FuelLogUpdateSchema) -> dict:
        """Correct the date / litres / note of one saved row.

        This is the *İşlemler → Düzenle* action: the row keeps its identity, so
        the daily / weekly / monthly totals simply move with the new date.
        Fields the payload leaves ``None`` are not touched.
        """

        log = await self.db.get(MachineFuelLogModel, log_id)
        if log is None:
            raise HTTPException(status_code=404, detail=ENTRY_NOT_FOUND_DETAIL)

        if data.fuel_date is not None:
            log.fuel_date = data.fuel_date
        if data.liters is not None:
            log.liters = float(data.liters)
        if data.note is not None:
            log.note = data.note

        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return await self.fetch_entry(log_id)


__all__ = [
    "DCU_TERRITORY_NAME",
    "DEFAULT_DISTRIBUTION_DAYS",
    "ENTRY_NOT_FOUND_DETAIL",
    "FuelLogRepository",
    "MACHINE_NOT_FOUND_DETAIL",
    "MAX_DISTRIBUTION_DAYS",
    "MIN_CONSUMPTION_DELTA",
    "SRU_TERRITORY_NAME",
]
