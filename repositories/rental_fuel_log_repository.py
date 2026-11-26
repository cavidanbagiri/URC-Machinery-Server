# repositories/rental_fuel_log_repository.py
"""Data access for the diesel handed to **rented** machines (Kiralık sekmesi).

Rented equipment is not part of ``all_machines`` (see
``models/rental_machine_model.py``), so its fuel ledger points at the rental
agreement instead of a machine ID.  The tab on the **Mazot Dağılımı** page needs
three things from this module:

* the rentals with their **selected day** fuel totals (the editable table),
* the per-rental current-month and all-time totals (row subtitles),
* the whole rented fleet's totals for the summary cards.

The ledger keeps one row per refuelling; a wrong row (for example the 24th's
diesel saved on the 25th) is corrected in place through
:meth:`RentalFuelLogRepository.update_log`, and
:meth:`RentalFuelLogRepository.fetch_entries` lists the recent rows for the
**İşlemler → Düzenle** dialog.  The status of each rental is derived from its
dates on the **selected day**, so the badge of the tab always matches the day
whose rows are shown.

A diesel row may also carry the rental's **KM / engine-hour** reading at the
moment of refuelling (``machine_rental_fuel_logs.km`` / ``engine_hours``).
:meth:`fetch_section` exposes the newest non-null value per column up to the
selected day so the tab can show the current counter without a second ledger.
"""

from datetime import date
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.rental_fuel_log_model import MachineRentalFuelLogModel
from models.rental_machine_model import (
    RENTAL_STATUS_LABELS,
    MachineRentalModel,
    resolve_rental_status,
)
from models.user_model import UserModel
from repositories.fuel_log_window import (
    DEFAULT_EDIT_WINDOW_DAYS,
    resolve_edit_window,
)
from schemas.fuel_log_schemas import (
    RentalFuelLogCreateSchema,
    RentalFuelLogUpdateSchema,
)

NOT_FOUND_DETAIL = "Kiralık makine kaydı bulunamadı"
#: A diesel row of the Kiralık ledger was not found (deleted / wrong id).
ENTITY_NOT_FOUND_DETAIL = "Kiralık makine mazot kaydı bulunamadı"

#: How many recent readings per rental are inspected when looking for the
#: newest KM and engine-hour values.  Looking at a handful of rows (instead of
#: only the newest one) keeps the two counters independent: a row that records
#: only KM must not hide the engine hour entered the day before.
METER_HISTORY_DEPTH = 12


class RentalFuelLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- HELPERS ----------

    @staticmethod
    def _filters(search: Optional[str] = None) -> list:
        """Free-text filter over the rental's three hand-typed fields."""

        term = (search or "").strip()
        if not term:
            return []

        pattern = f"%{term}%"
        return [
            or_(
                MachineRentalModel.equipment_name.ilike(pattern),
                MachineRentalModel.company_name.ilike(pattern),
                MachineRentalModel.site_name.ilike(pattern),
            )
        ]

    @staticmethod
    def _status_order(target_date: date):
        """Sort active rentals first, planned next, expired last."""

        return case(
            (MachineRentalModel.end_date < target_date, 2),
            (MachineRentalModel.start_date > target_date, 1),
            else_=0,
        )

    @staticmethod
    def _entry_query():
        """Row-level ``SELECT`` of the Kiralık ledger with the author name.

        Shared by the correction dialog list and by the single-row refresh
        after an update, so both always expose the same columns.
        """

        return (
            select(
                MachineRentalFuelLogModel.id,
                MachineRentalFuelLogModel.rental_id,
                MachineRentalFuelLogModel.fuel_date,
                MachineRentalFuelLogModel.liters,
                MachineRentalFuelLogModel.km,
                MachineRentalFuelLogModel.engine_hours,
                MachineRentalFuelLogModel.given_by,
                MachineRentalFuelLogModel.note,
                MachineRentalFuelLogModel.created_by_id,
                MachineRentalFuelLogModel.created_at,
                UserModel.firstname.label("entered_by_firstname"),
                UserModel.lastname.label("entered_by_lastname"),
            )
            .select_from(MachineRentalFuelLogModel)
            .outerjoin(
                UserModel,
                MachineRentalFuelLogModel.created_by_id == UserModel.id,
            )
        )

    @staticmethod
    def _entry(row) -> dict[str, Any]:
        """Map one ledger row onto :class:`RentalFuelLogEntrySchema`."""

        name = " ".join(
            part
            for part in (row.entered_by_firstname, row.entered_by_lastname)
            if part
        ).strip()

        return {
            "id": row.id,
            "rental_id": row.rental_id,
            "fuel_date": row.fuel_date,
            "liters": float(row.liters),
            "km": float(row.km) if row.km is not None else None,
            "engine_hours": (
                float(row.engine_hours) if row.engine_hours is not None else None
            ),
            "given_by": row.given_by,
            "note": row.note,
            "entered_by_id": row.created_by_id,
            "entered_by_name": name or None,
            "created_at": row.created_at,
        }

    # ---------- READ ----------

    async def fetch_section(
        self,
        target_date: Optional[date] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return the Kiralık tab: fleet totals + one row per rental."""

        target = target_date or date.today()
        month_start = target.replace(day=1)

        # Summary cards describe the whole rented fleet, so the search term is
        # deliberately ignored here - exactly like the machine summary boxes.
        totals_row = (
            await self.db.execute(
                select(
                    func.coalesce(
                        func.sum(MachineRentalFuelLogModel.liters), 0.0
                    ).label("total"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    MachineRentalFuelLogModel.fuel_date
                                    >= month_start,
                                    MachineRentalFuelLogModel.liters,
                                ),
                                else_=0.0,
                            )
                        ),
                        0.0,
                    ).label("monthly"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    MachineRentalFuelLogModel.fuel_date
                                    == target,
                                    MachineRentalFuelLogModel.liters,
                                ),
                                else_=0.0,
                            )
                        ),
                        0.0,
                    ).label("daily"),
                ).where(MachineRentalFuelLogModel.fuel_date <= target)
            )
        ).first()

        # One grouped row per rental; the outer join keeps rentals that never
        # received fuel so the litre input is available for them too.
        summary = (
            select(
                MachineRentalFuelLogModel.rental_id.label("rental_id"),
                func.sum(MachineRentalFuelLogModel.liters).label("total_liters"),
                func.count(MachineRentalFuelLogModel.id).label("total_entry_count"),
                func.sum(
                    case(
                        (
                            MachineRentalFuelLogModel.fuel_date >= month_start,
                            MachineRentalFuelLogModel.liters,
                        ),
                        else_=0.0,
                    )
                ).label("monthly_liters"),
                func.sum(
                    case(
                        (
                            MachineRentalFuelLogModel.fuel_date == target,
                            MachineRentalFuelLogModel.liters,
                        ),
                        else_=0.0,
                    )
                ).label("day_liters"),
                func.sum(
                    case(
                        (MachineRentalFuelLogModel.fuel_date == target, 1),
                        else_=0,
                    )
                ).label("day_entry_count"),
            )
            .where(MachineRentalFuelLogModel.fuel_date <= target)
            .group_by(MachineRentalFuelLogModel.rental_id)
            .subquery()
        )

        rental_query = (
            select(MachineRentalModel, summary)
            .outerjoin(summary, summary.c.rental_id == MachineRentalModel.id)
            .where(*self._filters(search))
            .order_by(
                self._status_order(target),
                MachineRentalModel.start_date.desc(),
                MachineRentalModel.id.desc(),
            )
        )

        result = await self.db.execute(rental_query)

        items: list[dict[str, Any]] = []
        for row in result.all():
            rental: MachineRentalModel = row[0]
            status = resolve_rental_status(
                rental.start_date,
                rental.end_date,
                target,
            )

            items.append(
                {
                    "rental_id": rental.id,
                    "equipment_name": rental.equipment_name,
                    "company_name": rental.company_name,
                    "site_name": rental.site_name,
                    "start_date": rental.start_date,
                    "end_date": rental.end_date,
                    "status": status,
                    "status_label": RENTAL_STATUS_LABELS.get(status, status),
                    "day_liters": float(row.day_liters or 0),
                    "day_entry_count": int(row.day_entry_count or 0),
                    "last_given_by": None,
                    "last_note": None,
                    "last_created_at": None,
                    "monthly_liters": float(row.monthly_liters or 0),
                    "total_liters": float(row.total_liters or 0),
                    "total_entry_count": int(row.total_entry_count or 0),
                    # Filled by ``_attach_latest_meters`` below.
                    "last_km": None,
                    "last_engine_hours": None,
                    "last_meter_date": None,
                }
            )

        await self._attach_last_entries(items, target)
        await self._attach_latest_meters(items, target)

        return {
            "rental_total": float(totals_row.total or 0) if totals_row else 0.0,
            "rental_daily_total": (
                float(totals_row.daily or 0) if totals_row else 0.0
            ),
            "rental_monthly_total": (
                float(totals_row.monthly or 0) if totals_row else 0.0
            ),
            "rental_machines": items,
        }

    async def _attach_last_entries(
        self,
        items: list[dict[str, Any]],
        target_date: date,
    ) -> None:
        """Fill "Son: <kişi>" of every row from that day's newest row."""

        if not items:
            return

        ranked = (
            select(
                MachineRentalFuelLogModel.rental_id.label("rental_id"),
                MachineRentalFuelLogModel.given_by.label("given_by"),
                MachineRentalFuelLogModel.note.label("note"),
                MachineRentalFuelLogModel.created_at.label("created_at"),
                func.row_number()
                .over(
                    partition_by=MachineRentalFuelLogModel.rental_id,
                    order_by=[
                        MachineRentalFuelLogModel.created_at.desc(),
                        MachineRentalFuelLogModel.id.desc(),
                    ],
                )
                .label("row_number"),
            )
            .where(
                MachineRentalFuelLogModel.rental_id.in_(
                    [item["rental_id"] for item in items]
                ),
                MachineRentalFuelLogModel.fuel_date == target_date,
            )
            .subquery()
        )

        result = await self.db.execute(
            select(ranked).where(ranked.c.row_number == 1)
        )

        by_rental = {item["rental_id"]: item for item in items}
        for row in result.all():
            item = by_rental.get(row.rental_id)
            if item is None:
                continue
            item["last_given_by"] = row.given_by
            item["last_note"] = row.note
            item["last_created_at"] = row.created_at

    async def _attach_latest_meters(
        self,
        items: list[dict[str, Any]],
        target_date: date,
    ) -> None:
        """Fill the newest KM / engine-hour reading up to ``target_date``.

        The two counters are handled independently: an excavator may only have
        engine hours, a truck only KM.  Recent readings are ranked newest-first
        per rental and the first non-null value of each column wins, so a row
        that stores just one counter never erases the other one.
        """

        if not items:
            return

        ranked = (
            select(
                MachineRentalFuelLogModel.rental_id.label("rental_id"),
                MachineRentalFuelLogModel.km.label("km"),
                MachineRentalFuelLogModel.engine_hours.label("engine_hours"),
                MachineRentalFuelLogModel.fuel_date.label("fuel_date"),
                func.row_number()
                .over(
                    partition_by=MachineRentalFuelLogModel.rental_id,
                    order_by=[
                        MachineRentalFuelLogModel.fuel_date.desc(),
                        MachineRentalFuelLogModel.created_at.desc(),
                        MachineRentalFuelLogModel.id.desc(),
                    ],
                )
                .label("row_number"),
            )
            .where(
                MachineRentalFuelLogModel.rental_id.in_(
                    [item["rental_id"] for item in items]
                ),
                MachineRentalFuelLogModel.fuel_date <= target_date,
                or_(
                    MachineRentalFuelLogModel.km.isnot(None),
                    MachineRentalFuelLogModel.engine_hours.isnot(None),
                ),
            )
            .subquery()
        )

        result = await self.db.execute(
            select(ranked)
            .where(ranked.c.row_number <= METER_HISTORY_DEPTH)
            .order_by(ranked.c.row_number)
        )

        by_rental = {item["rental_id"]: item for item in items}
        for row in result.all():
            item = by_rental.get(row.rental_id)
            if item is None:
                continue
            if item["last_km"] is None and row.km is not None:
                item["last_km"] = float(row.km)
            if (
                item["last_engine_hours"] is None
                and row.engine_hours is not None
            ):
                item["last_engine_hours"] = float(row.engine_hours)
            if item["last_meter_date"] is None:
                item["last_meter_date"] = row.fuel_date

    # ---------- WRITE ----------

    async def create_log(
        self,
        data: RentalFuelLogCreateSchema,
        user_id: Optional[int],
        given_by: Optional[str] = None,
    ) -> MachineRentalFuelLogModel:
        rental = await self.db.get(MachineRentalModel, data.rental_id)
        if rental is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)

        log = MachineRentalFuelLogModel(
            rental_id=data.rental_id,
            fuel_date=data.fuel_date,
            liters=float(data.liters),
            # Counter readings captured with the same save; the form leaves
            # them empty for equipment without a KM / hour meter.
            km=float(data.km) if data.km is not None else None,
            engine_hours=(
                float(data.engine_hours)
                if data.engine_hours is not None
                else None
            ),
            # The table has no *Yakıtı veren* input; the router passes the
            # signed-in user's name as the fallback.
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

    async def fetch_entries(
        self,
        rental_id: int,
        target_date: Optional[date] = None,
        days: int = DEFAULT_EDIT_WINDOW_DAYS,
    ) -> list[dict[str, Any]]:
        """Recent diesel rows of one rental, newest first.

        Feeds the **İşlemler → Düzenle** dialog of the Kiralık tab; the row the
        user wants to correct (usually a wrong day) is listed with its litres
        and the KM / engine-hour reading captured at that moment.
        """

        rental = await self.db.get(MachineRentalModel, rental_id)
        if rental is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)

        start_date, end_date = resolve_edit_window(target_date, days)

        result = await self.db.execute(
            self._entry_query()
            .where(
                MachineRentalFuelLogModel.rental_id == rental_id,
                MachineRentalFuelLogModel.fuel_date >= start_date,
                MachineRentalFuelLogModel.fuel_date <= end_date,
            )
            .order_by(
                MachineRentalFuelLogModel.fuel_date.desc(),
                MachineRentalFuelLogModel.created_at.desc(),
                MachineRentalFuelLogModel.id.desc(),
            )
        )

        return [self._entry(row) for row in result.all()]

    async def fetch_entry(self, log_id: int) -> dict[str, Any]:
        """One diesel row of the Kiralık ledger."""

        result = await self.db.execute(
            self._entry_query().where(MachineRentalFuelLogModel.id == log_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=ENTITY_NOT_FOUND_DETAIL,
            )

        return self._entry(row)

    async def update_log(
        self,
        log_id: int,
        data: RentalFuelLogUpdateSchema,
    ) -> dict[str, Any]:
        """Correct the date / litres / counters of one saved Kiralık row.

        The counter readings live on the diesel row, so moving the row to the
        right day also moves its KM / engine-hour value.  Fields the payload
        leaves ``None`` are not touched.
        """

        log = await self.db.get(MachineRentalFuelLogModel, log_id)
        if log is None:
            raise HTTPException(
                status_code=404,
                detail=ENTITY_NOT_FOUND_DETAIL,
            )

        if data.fuel_date is not None:
            log.fuel_date = data.fuel_date
        if data.liters is not None:
            log.liters = float(data.liters)
        if data.km is not None:
            log.km = float(data.km)
        if data.engine_hours is not None:
            log.engine_hours = float(data.engine_hours)
        if data.note is not None:
            log.note = data.note

        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return await self.fetch_entry(log_id)


__all__ = [
    "ENTITY_NOT_FOUND_DETAIL",
    "METER_HISTORY_DEPTH",
    "NOT_FOUND_DETAIL",
    "RentalFuelLogRepository",
]
