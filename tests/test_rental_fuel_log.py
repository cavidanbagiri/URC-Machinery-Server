"""Offline regression tests for the **Kiralık** diesel ledger.

Run from ``server/``:
    python -m unittest tests.test_rental_fuel_log -v

These tests never touch PostgreSQL.  They cover the write schema, the overview
fields the Kiralık tab reads, the append-only table definition, the rental
search / ordering helpers, the optional KM / engine-hour readings stored on the
diesel row and the *rental does not exist* guard of ``create_log``.
"""

import unittest
from collections import namedtuple
from datetime import date, datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Date
from sqlalchemy.dialects import postgresql

from models.rental_fuel_log_model import MachineRentalFuelLogModel
from repositories import rental_fuel_log_repository
from repositories.rental_fuel_log_repository import (
    NOT_FOUND_DETAIL,
    RentalFuelLogRepository,
)
from routers import fuel_log_router
from schemas.fuel_log_schemas import (
    FuelLogOverviewSchema,
    FuelLogRentalMachineSchema,
    RentalFuelLogCreateSchema,
    RentalFuelLogEntrySchema,
)


def compile_sql(expression):
    return str(
        expression.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def rental(**overrides):
    data = {
        "id": 7,
        "equipment_name": "CAT 320D Ekskavatör",
        "company_name": "Ustay Kiralama A.Ş.",
        "site_name": "Merkez Şantiye",
        "start_date": date(2026, 11, 1),
        "end_date": date(2026, 12, 31),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class RentalFuelLogSchemaTests(unittest.TestCase):
    def test_valid_payload_normalizes_text(self):
        payload = RentalFuelLogCreateSchema(
            rental_id=7,
            fuel_date=date(2026, 11, 22),
            liters=180.75,
            given_by="  Ali   Veli ",
            note="  kepçe  ",
        )

        self.assertEqual(payload.rental_id, 7)
        self.assertEqual(payload.liters, 180.75)
        self.assertEqual(payload.given_by, "Ali Veli")
        self.assertEqual(payload.note, "kepçe")

    def test_given_by_and_note_are_optional(self):
        payload = RentalFuelLogCreateSchema(
            rental_id=7,
            fuel_date=date(2026, 11, 22),
            liters=10,
        )

        self.assertIsNone(payload.given_by)
        self.assertIsNone(payload.note)

    def test_blank_given_by_becomes_none(self):
        """The Kiralık tab also has no *Yakıtı veren* input."""

        payload = RentalFuelLogCreateSchema(
            rental_id=7,
            fuel_date=date(2026, 11, 22),
            liters=10,
            given_by="   ",
        )

        self.assertIsNone(payload.given_by)

    def test_meter_readings_are_optional(self):
        """Eski istemciler KM / saat göndermeden litre kaydedebilir."""

        payload = RentalFuelLogCreateSchema(
            rental_id=7,
            fuel_date=date(2026, 11, 22),
            liters=10,
        )

        self.assertIsNone(payload.km)
        self.assertIsNone(payload.engine_hours)

    def test_meter_readings_are_kept_on_the_diesel_row(self):
        payload = RentalFuelLogCreateSchema(
            rental_id=7,
            fuel_date=date(2026, 11, 22),
            liters=120.5,
            km=15_420,
            engine_hours=0,
        )

        self.assertEqual(payload.km, 15_420)
        # Sıfır geçerli bir okumadır (ör. yeni saat sayacı).
        self.assertEqual(payload.engine_hours, 0)

    def test_meter_readings_must_be_non_negative(self):
        for field in ("km", "engine_hours"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    RentalFuelLogCreateSchema(
                        rental_id=7,
                        fuel_date=date(2026, 11, 22),
                        liters=10,
                        **{field: -1},
                    )

    def test_rental_id_must_be_positive(self):
        for value in (0, -3):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    RentalFuelLogCreateSchema(
                        rental_id=value,
                        fuel_date=date(2026, 11, 22),
                        liters=10,
                    )

    def test_liters_must_be_positive(self):
        for value in (0, -0.5):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    RentalFuelLogCreateSchema(
                        rental_id=7,
                        fuel_date=date(2026, 11, 22),
                        liters=value,
                    )

    def test_machine_id_is_not_accepted(self):
        """Kiralık ekipmanın filo ID'si yok; payload rental_id taşır."""

        with self.assertRaises(ValidationError):
            RentalFuelLogCreateSchema(
                machine_id=5,
                fuel_date=date(2026, 11, 22),
                liters=10,
            )

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            RentalFuelLogCreateSchema(
                rental_id=7,
                fuel_date=date(2026, 11, 22),
                liters=10,
                odometer=123,
            )

    def test_entry_schema_accepts_the_saved_row(self):
        entry = RentalFuelLogEntrySchema(
            id=3,
            rental_id=7,
            fuel_date=date(2026, 11, 22),
            liters=55.5,
            km=9_840.5,
            engine_hours=None,
            given_by="Depo Sorumlusu",
            note=None,
            entered_by_id=1,
            entered_by_name="Ayşe Yılmaz",
            created_at=datetime(2026, 11, 22, 8, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(entry.rental_id, 7)
        self.assertEqual(entry.liters, 55.5)
        self.assertEqual(entry.km, 9_840.5)
        self.assertIsNone(entry.engine_hours)
        self.assertEqual(entry.entered_by_name, "Ayşe Yılmaz")


class RentalFuelLogReadSchemaTests(unittest.TestCase):
    def test_rental_row_defaults(self):
        row = FuelLogRentalMachineSchema(
            rental_id=7,
            equipment_name="CAT 320D Ekskavatör",
            company_name="Ustay Kiralama A.Ş.",
            site_name="Merkez Şantiye",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 12, 31),
            status="aktif",
            status_label="Aktif",
        )

        self.assertEqual(row.day_liters, 0)
        self.assertEqual(row.day_entry_count, 0)
        self.assertEqual(row.monthly_liters, 0)
        self.assertEqual(row.total_liters, 0)
        self.assertEqual(row.total_entry_count, 0)
        self.assertIsNone(row.last_given_by)
        self.assertIsNone(row.last_created_at)
        self.assertIsNone(row.last_km)
        self.assertIsNone(row.last_engine_hours)
        self.assertIsNone(row.last_meter_date)

    def test_rental_row_carries_the_day_and_totals(self):
        row = FuelLogRentalMachineSchema(
            rental_id=7,
            equipment_name="CAT 320D Ekskavatör",
            company_name="Ustay Kiralama A.Ş.",
            site_name="Merkez Şantiye",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 12, 31),
            status="aktif",
            status_label="Aktif",
            day_liters=120.5,
            day_entry_count=2,
            last_given_by="Ali Veli",
            last_note="kepçe",
            monthly_liters=980,
            total_liters=2_400,
            total_entry_count=9,
            last_km=15_420,
            last_engine_hours=3_210.5,
            last_meter_date=date(2026, 11, 22),
        )

        self.assertEqual(row.day_liters, 120.5)
        self.assertEqual(row.day_entry_count, 2)
        self.assertEqual(row.last_given_by, "Ali Veli")
        self.assertEqual(row.last_note, "kepçe")
        self.assertEqual(row.monthly_liters, 980)
        self.assertEqual(row.total_liters, 2_400)
        self.assertEqual(row.total_entry_count, 9)
        self.assertEqual(row.last_km, 15_420)
        self.assertEqual(row.last_engine_hours, 3_210.5)
        self.assertEqual(row.last_meter_date, date(2026, 11, 22))

    def test_overview_defaults_rental_fields(self):
        """Eski istemciler için kiralık alanları varsayılanla gelir."""

        overview = FuelLogOverviewSchema(
            fuel_date=date(2026, 11, 22),
            week_start=date(2026, 11, 16),
            month_start=date(2026, 11, 1),
            daily_total=0,
            weekly_total=0,
            monthly_total=1_500,
            previous_month_start=date(2026, 10, 1),
            previous_month_end=date(2026, 10, 31),
            previous_month_total=3_200,
            sru_monthly_total=900,
            dcu_monthly_total=600,
        )

        self.assertEqual(overview.rental_total, 0)
        self.assertEqual(overview.rental_daily_total, 0)
        self.assertEqual(overview.rental_monthly_total, 0)
        self.assertEqual(overview.rental_machines, [])

    def test_overview_accepts_the_rental_section(self):
        overview = FuelLogOverviewSchema(
            fuel_date=date(2026, 11, 22),
            week_start=date(2026, 11, 16),
            month_start=date(2026, 11, 1),
            daily_total=50,
            weekly_total=200,
            monthly_total=1_500,
            previous_month_start=date(2026, 10, 1),
            previous_month_end=date(2026, 10, 31),
            previous_month_total=3_200,
            sru_monthly_total=900,
            dcu_monthly_total=600,
            rental_total=2_400,
            rental_daily_total=120.5,
            rental_monthly_total=980,
            rental_machines=[
                {
                    "rental_id": 7,
                    "equipment_name": "CAT 320D Ekskavatör",
                    "company_name": "Ustay Kiralama A.Ş.",
                    "site_name": "Merkez Şantiye",
                    "start_date": date(2026, 11, 1),
                    "end_date": date(2026, 12, 31),
                    "status": "aktif",
                    "status_label": "Aktif",
                    "day_liters": 120.5,
                    "day_entry_count": 2,
                    "monthly_liters": 980,
                    "total_liters": 2_400,
                    "total_entry_count": 9,
                }
            ],
        )

        self.assertEqual(overview.rental_total, 2_400)
        self.assertEqual(overview.rental_monthly_total, 980)
        self.assertEqual(overview.rental_daily_total, 120.5)
        self.assertEqual(overview.rental_machines[0].rental_id, 7)
        self.assertEqual(overview.rental_machines[0].day_entry_count, 2)

class RentalFuelLogModelTests(unittest.TestCase):
    def test_table_name(self):
        self.assertEqual(
            MachineRentalFuelLogModel.__tablename__,
            "machine_rental_fuel_logs",
        )

    def test_table_is_append_only_by_contract(self):
        # Güncelleme/silme yok: her kayıt kalıcı bir satırdır.
        self.assertNotIn("updated_at", MachineRentalFuelLogModel.__table__.columns)
        self.assertNotIn("deleted_at", MachineRentalFuelLogModel.__table__.columns)

    def test_required_and_optional_columns(self):
        columns = MachineRentalFuelLogModel.__table__.columns

        for field in ("rental_id", "fuel_date", "liters", "given_by", "created_at"):
            with self.subTest(field=field):
                self.assertFalse(columns[field].nullable)

        self.assertTrue(columns.note.nullable)
        self.assertTrue(columns.created_by_id.nullable)
        # Sayaç okumaları isteğe bağlıdır: eski satırlar NULL kalır.
        self.assertTrue(columns.km.nullable)
        self.assertTrue(columns.engine_hours.nullable)

    def test_fuel_date_uses_the_date_type(self):
        self.assertIsInstance(
            MachineRentalFuelLogModel.__table__.columns.fuel_date.type,
            Date,
        )

    def test_positive_liters_constraint_exists(self):
        names = {
            constraint.name
            for constraint in MachineRentalFuelLogModel.__table__.constraints
            if constraint.name
        }

        self.assertIn(
            "ck_machine_rental_fuel_logs_liters_positive",
            names,
        )
        self.assertIn(
            "ck_machine_rental_fuel_logs_km_non_negative",
            names,
        )
        self.assertIn(
            "ck_machine_rental_fuel_logs_engine_hours_non_negative",
            names,
        )

    def test_rental_delete_removes_its_fuel_rows(self):
        foreign_key = next(
            iter(MachineRentalFuelLogModel.__table__.c.rental_id.foreign_keys)
        )

        self.assertEqual(foreign_key.column.table.name, "machine_rentals")
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    def test_creator_is_cleared_with_the_user(self):
        foreign_key = next(
            iter(MachineRentalFuelLogModel.__table__.c.created_by_id.foreign_keys)
        )

        self.assertEqual(foreign_key.column.table.name, "users")
        self.assertEqual(foreign_key.ondelete, "SET NULL")

    def test_rental_date_index_exists(self):
        indexes = {
            index.name for index in MachineRentalFuelLogModel.__table__.indexes
        }

        self.assertIn("ix_machine_rental_fuel_logs_rental_date", indexes)


class RentalFuelLogRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repository = RentalFuelLogRepository(db=None)

    def test_search_matches_all_three_rental_columns(self):
        filters = self.repository._filters(search="  cat ")

        self.assertEqual(len(filters), 1)
        sql = compile_sql(filters[0])

        for column in ("equipment_name", "company_name", "site_name"):
            self.assertIn(column, sql)
        self.assertIn("%cat%", sql)

    def test_empty_search_adds_no_filter(self):
        self.assertEqual(self.repository._filters(search="   "), [])
        self.assertEqual(self.repository._filters(search=None), [])

    def test_status_order_puts_active_rentals_first(self):
        sql = compile_sql(self.repository._status_order(date(2026, 11, 22)))

        self.assertIn("CASE", sql)
        self.assertIn("end_date <", sql)
        self.assertIn("start_date >", sql)

    def test_not_found_message_is_turkish(self):
        self.assertEqual(NOT_FOUND_DETAIL, "Kiralık makine kaydı bulunamadı")
        # Router da aynı mesajı kullanır.
        self.assertIs(rental_fuel_log_repository.NOT_FOUND_DETAIL, NOT_FOUND_DETAIL)

class FakeDb:
    """Minimal stand-in for ``AsyncSession`` used by ``create_log``."""

    def __init__(self, stored_rental=None):
        self.stored_rental = stored_rental
        self.added = []
        self.committed = False
        self.refreshed = None
        self.rolled_back = False

    async def get(self, model, primary_key):
        return self.stored_rental

    def add(self, instance):
        self.added.append(instance)

    async def commit(self):
        self.committed = True

    async def refresh(self, instance):
        self.refreshed = instance

    async def rollback(self):
        self.rolled_back = True


class RentalFuelLogCreateTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_rental_raises_404(self):
        repository = RentalFuelLogRepository(db=FakeDb(stored_rental=None))

        with self.assertRaises(HTTPException) as raised:
            await repository.create_log(
                RentalFuelLogCreateSchema(
                    rental_id=99,
                    fuel_date=date(2026, 11, 22),
                    liters=10,
                ),
                user_id=1,
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, NOT_FOUND_DETAIL)

    async def test_log_is_appended_with_the_signed_in_user_name(self):
        db = FakeDb(stored_rental=rental())
        repository = RentalFuelLogRepository(db=db)

        log = await repository.create_log(
            RentalFuelLogCreateSchema(
                rental_id=7,
                fuel_date=date(2026, 11, 22),
                liters=120.5,
            ),
            user_id=3,
            given_by="Ayşe Yılmaz",
        )

        self.assertTrue(db.committed)
        self.assertEqual(db.added, [log])
        self.assertEqual(log.rental_id, 7)
        self.assertEqual(log.liters, 120.5)
        self.assertEqual(log.given_by, "Ayşe Yılmaz")
        self.assertEqual(log.created_by_id, 3)
        self.assertIs(db.refreshed, log)

    async def test_meter_readings_are_stored_with_the_diesel_row(self):
        db = FakeDb(stored_rental=rental())
        repository = RentalFuelLogRepository(db=db)

        log = await repository.create_log(
            RentalFuelLogCreateSchema(
                rental_id=7,
                fuel_date=date(2026, 11, 22),
                liters=120.5,
                km=15_420,
                engine_hours=3_210.5,
            ),
            user_id=3,
            given_by="Ayşe Yılmaz",
        )

        self.assertEqual(log.km, 15_420)
        self.assertEqual(log.engine_hours, 3_210.5)

    async def test_missing_meter_readings_stay_null(self):
        db = FakeDb(stored_rental=rental())
        repository = RentalFuelLogRepository(db=db)

        log = await repository.create_log(
            RentalFuelLogCreateSchema(
                rental_id=7,
                fuel_date=date(2026, 11, 22),
                liters=40,
            ),
            user_id=3,
        )

        self.assertIsNone(log.km)
        self.assertIsNone(log.engine_hours)

    async def test_explicit_given_by_wins_over_the_fallback(self):
        db = FakeDb(stored_rental=rental())
        repository = RentalFuelLogRepository(db=db)

        log = await repository.create_log(
            RentalFuelLogCreateSchema(
                rental_id=7,
                fuel_date=date(2026, 11, 22),
                liters=40,
                given_by="Depo Sorumlusu",
            ),
            user_id=3,
            given_by="Ayşe Yılmaz",
        )

        self.assertEqual(log.given_by, "Depo Sorumlusu")


class FuelLogRouterRentalRouteTests(unittest.TestCase):
    def test_rental_create_route_is_registered(self):
        routes = {
            (route.path, route.status_code)
            for route in fuel_log_router.router.routes
            if hasattr(route, "methods")
        }

        self.assertIn(("/rental/create", 201), routes)

    def test_machine_create_route_is_untouched(self):
        routes = {
            (route.path, route.status_code)
            for route in fuel_log_router.router.routes
            if hasattr(route, "methods")
        }

        self.assertIn(("/create", 201), routes)



class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class ScriptedDb:
    """Returns prepared results in order so ``fetch_section`` runs offline."""

    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.results.pop(0))


RENTAL_AGG_ROW = namedtuple(
    "RENTAL_AGG_ROW",
    [
        "rental",
        "rental_id",
        "total_liters",
        "total_entry_count",
        "monthly_liters",
        "day_liters",
        "day_entry_count",
    ],
)

LAST_ENTRY_ROW = namedtuple(
    "LAST_ENTRY_ROW",
    ["rental_id", "given_by", "note", "created_at"],
)

#: One ranked reading from ``_attach_latest_meters`` (newest first).
METER_ROW = namedtuple(
    "METER_ROW",
    ["rental_id", "km", "engine_hours", "fuel_date"],
)


class RentalFuelLogSectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_section_maps_rows_and_totals(self):
        db = ScriptedDb(
            [
                [SimpleNamespace(total=2_400.0, monthly=980.0, daily=120.5)],
                [
                    RENTAL_AGG_ROW(
                        rental(),
                        7,
                        2_400.0,
                        9,
                        980.0,
                        120.5,
                        2,
                    )
                ],
                [
                    LAST_ENTRY_ROW(
                        7,
                        "Ayşe Yılmaz",
                        "akşam dolumu",
                        datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc),
                    )
                ],
                [
                    METER_ROW(7, 15_420.0, 3_210.5, date(2026, 11, 22)),
                ],
            ]
        )

        section = await RentalFuelLogRepository(db=db).fetch_section(
            target_date=date(2026, 11, 22)
        )

        self.assertEqual(section["rental_total"], 2_400.0)
        self.assertEqual(section["rental_monthly_total"], 980.0)
        self.assertEqual(section["rental_daily_total"], 120.5)

        item = section["rental_machines"][0]
        self.assertEqual(item["rental_id"], 7)
        self.assertEqual(item["equipment_name"], "CAT 320D Ekskavatör")
        self.assertEqual(item["status"], "aktif")
        self.assertEqual(item["status_label"], "Aktif")
        self.assertEqual(item["day_liters"], 120.5)
        self.assertEqual(item["day_entry_count"], 2)
        self.assertEqual(item["monthly_liters"], 980.0)
        self.assertEqual(item["total_liters"], 2_400.0)
        self.assertEqual(item["total_entry_count"], 9)
        self.assertEqual(item["last_given_by"], "Ayşe Yılmaz")
        self.assertEqual(item["last_note"], "akşam dolumu")
        self.assertEqual(item["last_km"], 15_420.0)
        self.assertEqual(item["last_engine_hours"], 3_210.5)
        self.assertEqual(item["last_meter_date"], date(2026, 11, 22))
        # Dört sorgu: toplamlar, satırlar, "son kayıt" ve sayaç penceresi.
        self.assertEqual(len(db.statements), 4)
        meter_sql = compile_sql(db.statements[3])
        self.assertIn("row_number", meter_sql)
        self.assertIn("engine_hours", meter_sql)

    async def test_rental_without_fuel_rows_still_appears(self):
        db = ScriptedDb(
            [
                [SimpleNamespace(total=0, monthly=0, daily=0)],
                [
                    RENTAL_AGG_ROW(
                        rental(start_date=date(2026, 12, 1), end_date=date(2026, 12, 10)),
                        7,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                ],
                [],
                [],
            ]
        )

        section = await RentalFuelLogRepository(db=db).fetch_section(
            target_date=date(2026, 11, 22)
        )

        item = section["rental_machines"][0]
        self.assertEqual(item["status"], "planlandi")
        self.assertEqual(item["status_label"], "Planlandı")
        self.assertEqual(item["day_liters"], 0.0)
        self.assertEqual(item["day_entry_count"], 0)
        self.assertEqual(item["monthly_liters"], 0.0)
        self.assertEqual(item["total_liters"], 0.0)
        self.assertEqual(item["total_entry_count"], 0)
        self.assertIsNone(item["last_given_by"])
        self.assertIsNone(item["last_km"])
        self.assertIsNone(item["last_engine_hours"])
        self.assertIsNone(item["last_meter_date"])
        # Dört sorgu: toplamlar, satırlar, "son kayıt" ve sayaç penceresi.
        self.assertEqual(len(db.statements), 4)

    async def test_latest_meter_readings_keep_km_and_hours_independent(self):
        """Yalnız KM içeren yeni satır, önceki motor saatini silmez."""

        db = ScriptedDb(
            [
                [SimpleNamespace(total=0, monthly=0, daily=0)],
                [
                    RENTAL_AGG_ROW(
                        rental(),
                        7,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                ],
                [],
                [
                    METER_ROW(7, 15_420.0, None, date(2026, 11, 22)),
                    METER_ROW(7, None, 3_210.5, date(2026, 11, 20)),
                ],
            ]
        )

        section = await RentalFuelLogRepository(db=db).fetch_section(
            target_date=date(2026, 11, 22)
        )

        item = section["rental_machines"][0]
        self.assertEqual(item["last_km"], 15_420.0)
        self.assertEqual(item["last_engine_hours"], 3_210.5)
        # Tarih, en yeni okumanın (KM) günüdür.
        self.assertEqual(item["last_meter_date"], date(2026, 11, 22))

    async def test_empty_fleet_returns_zeroed_totals(self):
        db = ScriptedDb([[SimpleNamespace(total=None, monthly=None, daily=None)], []])

        section = await RentalFuelLogRepository(db=db).fetch_section(
            target_date=date(2026, 11, 22)
        )

        self.assertEqual(section["rental_total"], 0.0)
        self.assertEqual(section["rental_monthly_total"], 0.0)
        self.assertEqual(section["rental_daily_total"], 0.0)
        self.assertEqual(section["rental_machines"], [])

    async def test_no_totals_row_is_treated_as_zero(self):
        db = ScriptedDb([[], []])

        section = await RentalFuelLogRepository(db=db).fetch_section(
            target_date=date(2026, 11, 22)
        )

        self.assertEqual(section["rental_total"], 0.0)
        self.assertEqual(section["rental_machines"], [])




if __name__ == "__main__":
    unittest.main()

