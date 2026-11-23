"""Offline regression tests for the diesel distribution records.

Run from ``server/``:
    python -m unittest tests.test_fuel_log -v

These tests do not connect to PostgreSQL.  They cover the write schema, the
daily / weekly / monthly / previous-month period helpers, the SRU / DCU
territory totals, the average-consumption calculation, the row-to-schema
mapping, the dashboard diesel distribution series and the append-only table
definition.
"""

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from pydantic import ValidationError

from models.fuel_log_model import MachineFuelLogModel
from repositories.fuel_log_repository import FuelLogRepository
from routers import fuel_log_router
from schemas.fuel_log_schemas import (
    FuelDistributionDaySchema,
    FuelDistributionSchema,
    FuelLogCreateSchema,
    FuelLogEntrySchema,
    FuelLogMachineSchema,
    FuelLogOverviewSchema,
)


class FuelLogSchemaTests(unittest.TestCase):
    def test_valid_payload_normalizes_text(self):
        payload = FuelLogCreateSchema(
            machine_id=12,
            fuel_date=date(2026, 11, 17),
            liters=150.5,
            given_by="  Ali   Veli ",
            note="  ilk dolum  ",
        )

        self.assertEqual(payload.machine_id, 12)
        self.assertEqual(payload.liters, 150.5)
        self.assertEqual(payload.given_by, "Ali Veli")
        self.assertEqual(payload.note, "ilk dolum")

    def test_blank_note_becomes_none(self):
        payload = FuelLogCreateSchema(
            machine_id=1,
            fuel_date=date(2026, 11, 17),
            liters=10,
            given_by="Depo",
            note="   ",
        )

        self.assertIsNone(payload.note)

    def test_liters_must_be_positive(self):
        for value in (0, -0.01):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    FuelLogCreateSchema(
                        machine_id=1,
                        fuel_date=date(2026, 11, 17),
                        liters=value,
                        given_by="Depo",
                    )

    def test_blank_given_by_becomes_none(self):
        """The UI has no *Yakıtı veren* input; the router fills the user name."""

        payload = FuelLogCreateSchema(
            machine_id=1,
            fuel_date=date(2026, 11, 17),
            liters=10,
            given_by="   ",
        )

        self.assertIsNone(payload.given_by)

    def test_given_by_is_optional(self):
        payload = FuelLogCreateSchema(
            machine_id=1,
            fuel_date=date(2026, 11, 17),
            liters=10,
        )

        self.assertIsNone(payload.given_by)
        self.assertIsNone(payload.note)

    def test_required_fields_and_unknown_fields(self):
        with self.assertRaises(ValidationError):
            FuelLogCreateSchema(
                fuel_date=date.today(),
                liters=10,
                given_by="Depo",
            )

        with self.assertRaises(ValidationError):
            FuelLogCreateSchema(
                machine_id=1,
                fuel_date=date.today(),
                liters=10,
                given_by="Depo",
                km=123,
            )

    def test_machine_read_schema_defaults(self):
        machine = FuelLogMachineSchema(machine_id=1)
        self.assertEqual(machine.day_liters, 0)
        self.assertEqual(machine.day_entry_count, 0)
        self.assertIsNone(machine.last_km)
        self.assertIsNone(machine.last_engine_hours)
        self.assertIsNone(machine.last_log_date)
        self.assertIsNone(machine.usage_unit)
        self.assertIsNone(machine.consumption_unit)
        self.assertIsNone(machine.avg_consumption)
        self.assertIsNone(machine.consumption_distance)

    def test_machine_read_schema_carries_meter_and_consumption(self):
        machine = FuelLogMachineSchema(
            machine_id=7,
            last_km=12_345.5,
            last_engine_hours=350,
            last_log_date=date(2026, 11, 21),
            usage_unit="km",
            consumption_unit="km",
            avg_consumption=0.2845,
            consumption_liters=700,
            consumption_distance=2_460,
            consumption_start_date=date(2026, 11, 1),
            consumption_end_date=date(2026, 11, 21),
        )

        self.assertEqual(machine.last_km, 12_345.5)
        self.assertEqual(machine.consumption_unit, "km")
        self.assertEqual(machine.avg_consumption, 0.2845)

    def test_overview_schema_carries_the_four_summary_totals(self):
        overview = FuelLogOverviewSchema(
            fuel_date=date(2026, 11, 22),
            week_start=date(2026, 11, 16),
            month_start=date(2026, 11, 1),
            daily_total=100,
            weekly_total=400,
            monthly_total=1_500,
            previous_month_start=date(2026, 10, 1),
            previous_month_end=date(2026, 10, 31),
            previous_month_total=3_200,
            sru_monthly_total=900,
            dcu_monthly_total=600,
        )

        self.assertEqual(overview.previous_month_start, date(2026, 10, 1))
        self.assertEqual(overview.previous_month_end, date(2026, 10, 31))
        self.assertEqual(overview.previous_month_total, 3_200)
        self.assertEqual(overview.sru_monthly_total, 900)
        self.assertEqual(overview.dcu_monthly_total, 600)
        self.assertEqual(overview.machines, [])


class FuelLogPeriodTests(unittest.TestCase):
    def test_periods_include_rolling_week_and_month_start(self):
        week_start, month_start = FuelLogRepository._resolve_periods(
            date(2026, 11, 17)
        )

        self.assertEqual(week_start, date(2026, 11, 11))
        self.assertEqual(month_start, date(2026, 11, 1))

    def test_periods_cross_month_boundary(self):
        week_start, month_start = FuelLogRepository._resolve_periods(
            date(2026, 11, 3)
        )

        self.assertEqual(week_start, date(2026, 10, 28))
        self.assertEqual(month_start, date(2026, 11, 1))

    def test_period_totals(self):
        rows = [
            SimpleNamespace(fuel_date=date(2026, 11, 1), liters=10),
            SimpleNamespace(fuel_date=date(2026, 11, 10), liters=20),
            SimpleNamespace(fuel_date=date(2026, 11, 11), liters=30),
            SimpleNamespace(fuel_date=date(2026, 11, 17), liters=40),
        ]

        totals = FuelLogRepository._period_totals(
            rows,
            target_date=date(2026, 11, 17),
            week_start=date(2026, 11, 11),
            month_start=date(2026, 11, 1),
        )

        self.assertEqual(totals["daily"], 40)
        self.assertEqual(totals["weekly"], 70)
        self.assertEqual(totals["monthly"], 100)
        self.assertEqual(totals["previous_month"], 0)

    def test_week_can_include_previous_month_but_month_total_cannot(self):
        rows = [
            SimpleNamespace(fuel_date=date(2026, 10, 29), liters=25),
            SimpleNamespace(fuel_date=date(2026, 11, 1), liters=5),
            SimpleNamespace(fuel_date=date(2026, 11, 3), liters=20),
        ]

        totals = FuelLogRepository._period_totals(
            rows,
            target_date=date(2026, 11, 3),
            week_start=date(2026, 10, 28),
            month_start=date(2026, 11, 1),
        )

        self.assertEqual(totals["daily"], 20)
        self.assertEqual(totals["weekly"], 50)
        self.assertEqual(totals["monthly"], 25)

    def test_previous_month_bounds(self):
        self.assertEqual(
            FuelLogRepository._previous_month_bounds(date(2026, 11, 1)),
            (date(2026, 10, 1), date(2026, 10, 31)),
        )
        # January rolls back to the previous year.
        self.assertEqual(
            FuelLogRepository._previous_month_bounds(date(2026, 1, 1)),
            (date(2025, 12, 1), date(2025, 12, 31)),
        )
        # Leap year February.
        self.assertEqual(
            FuelLogRepository._previous_month_bounds(date(2028, 3, 1)),
            (date(2028, 2, 1), date(2028, 2, 29)),
        )

    def test_previous_month_total_is_a_complete_month(self):
        rows = [
            SimpleNamespace(fuel_date=date(2026, 10, 1), liters=100),
            SimpleNamespace(fuel_date=date(2026, 10, 31), liters=50),
            SimpleNamespace(fuel_date=date(2026, 11, 1), liters=30),
        ]
        previous_start, previous_end = FuelLogRepository._previous_month_bounds(
            date(2026, 11, 1)
        )

        totals = FuelLogRepository._period_totals(
            rows,
            target_date=date(2026, 11, 22),
            week_start=date(2026, 11, 16),
            month_start=date(2026, 11, 1),
            previous_start=previous_start,
            previous_end=previous_end,
        )

        self.assertEqual(totals["previous_month"], 150)
        self.assertEqual(totals["monthly"], 30)
        self.assertEqual(totals["weekly"], 0)

    def test_territory_total_matches_name_case_insensitively(self):
        rows = [
            SimpleNamespace(territory_name="SRU", liters=120),
            SimpleNamespace(territory_name=" sru ", liters=30),
            SimpleNamespace(territory_name="DCU", liters=45),
            SimpleNamespace(territory_name=None, liters=10),
        ]

        self.assertEqual(FuelLogRepository._territory_total(rows, "SRU"), 150)
        self.assertEqual(FuelLogRepository._territory_total(rows, "dcu"), 45)
        self.assertEqual(FuelLogRepository._territory_total(rows, "Ofis"), 0)

    def test_consumption_uses_the_maintenance_unit(self):
        unit, value = FuelLogRepository._consumption(700, 2_500, 0, "km")
        self.assertEqual(unit, "km")
        self.assertAlmostEqual(value, 0.28)

        unit, value = FuelLogRepository._consumption(700, 0, 350, "hour")
        self.assertEqual(unit, "hour")
        self.assertAlmostEqual(value, 2.0)

    def test_consumption_falls_back_to_the_other_counter(self):
        """A km machine without odometer movement still shows L/saat."""

        unit, value = FuelLogRepository._consumption(120, 0, 40, "km")
        self.assertEqual(unit, "hour")
        self.assertAlmostEqual(value, 3.0)

        # No maintenance setting: km is preferred when it moved.
        unit, value = FuelLogRepository._consumption(120, 400, 40, None)
        self.assertEqual(unit, "km")
        self.assertAlmostEqual(value, 0.3)

    def test_consumption_needs_fuel_and_counter_movement(self):
        self.assertEqual(FuelLogRepository._consumption(0, 1_000, 0, "km"), (None, None))
        self.assertEqual(
            FuelLogRepository._consumption(None, 1_000, 0, "km"), (None, None)
        )
        # Fewer than one counter unit is treated as "no data".
        self.assertEqual(FuelLogRepository._consumption(10, 0.4, 0, "km"), (None, None))
        self.assertEqual(FuelLogRepository._consumption(10, 0, 0, "hour"), (None, None))

    def test_creator_name(self):
        self.assertEqual(
            FuelLogRepository._creator_name("Ali", "Veli"),
            "Ali Veli",
        )
        self.assertEqual(FuelLogRepository._creator_name("Ali", None), "Ali")
        self.assertIsNone(FuelLogRepository._creator_name(None, None))
        self.assertIsNone(FuelLogRepository._creator_name("  ", " "))

    def test_entry_mapping(self):
        row = SimpleNamespace(
            id=7,
            machine_id=3,
            fuel_date=date(2026, 11, 17),
            liters=150.25,
            given_by="Depo Sorumlusu",
            note="Sabah dolumu",
            created_by_id=9,
            entered_by_firstname="Ayşe",
            entered_by_lastname="Yılmaz",
            created_at=datetime(2026, 11, 17, 8, 30, tzinfo=timezone.utc),
        )

        entry = FuelLogRepository._entry(row)
        schema = FuelLogEntrySchema(**entry)

        self.assertEqual(schema.id, 7)
        self.assertEqual(schema.liters, 150.25)
        self.assertEqual(schema.given_by, "Depo Sorumlusu")
        self.assertEqual(schema.note, "Sabah dolumu")
        self.assertEqual(schema.entered_by_name, "Ayşe Yılmaz")


class FuelLogDistributionTests(unittest.TestCase):
    """Dashboard **Mazot Dağılımı** chart (SRU / DCU / kiralık, son 7 gün)."""

    def test_territory_bucket_matches_names_case_insensitively(self):
        self.assertEqual(FuelLogRepository._territory_bucket("SRU"), "sru")
        self.assertEqual(FuelLogRepository._territory_bucket(" sru "), "sru")
        self.assertEqual(FuelLogRepository._territory_bucket("Dcu"), "dcu")
        self.assertIsNone(FuelLogRepository._territory_bucket("Ofis"))
        self.assertIsNone(FuelLogRepository._territory_bucket(None))
        self.assertIsNone(FuelLogRepository._territory_bucket("   "))

    def test_build_distribution_keeps_every_day_of_the_window(self):
        start = date(2026, 11, 16)
        end = date(2026, 11, 22)

        series = FuelLogRepository._build_distribution(
            start,
            end,
            sru_by_day={date(2026, 11, 17): 120.5, date(2026, 11, 22): 80},
            dcu_by_day={date(2026, 11, 17): 40},
            rental_by_day={date(2026, 11, 20): 25.25},
        )

        self.assertEqual(series["start_date"], start)
        self.assertEqual(series["end_date"], end)
        self.assertEqual(series["days"], 7)
        self.assertEqual(len(series["items"]), 7)

        # Days without rows come back as zeros, not missing bar groups.
        self.assertEqual(series["items"][0]["fuel_date"], start)
        self.assertEqual(series["items"][0]["sru_liters"], 0)
        self.assertEqual(series["items"][0]["total_liters"], 0)

        second = series["items"][1]
        self.assertEqual(second["fuel_date"], date(2026, 11, 17))
        self.assertEqual(second["sru_liters"], 120.5)
        self.assertEqual(second["dcu_liters"], 40)
        self.assertEqual(second["rental_liters"], 0)
        self.assertEqual(second["total_liters"], 160.5)

        self.assertEqual(series["items"][4]["rental_liters"], 25.25)

    def test_build_distribution_totals(self):
        series = FuelLogRepository._build_distribution(
            date(2026, 11, 20),
            date(2026, 11, 22),
            sru_by_day={date(2026, 11, 20): 10, date(2026, 11, 21): 5},
            dcu_by_day={date(2026, 11, 22): 7},
            rental_by_day={date(2026, 11, 21): 3},
        )

        self.assertEqual(series["sru_total"], 15)
        self.assertEqual(series["dcu_total"], 7)
        self.assertEqual(series["rental_total"], 3)
        self.assertEqual(series["total"], 25)
        # A single day window still yields exactly one bar group.
        single = FuelLogRepository._build_distribution(
            date(2026, 11, 22),
            date(2026, 11, 22),
            {},
            {},
            {},
        )
        self.assertEqual(single["days"], 1)
        self.assertEqual(single["items"][0]["total_liters"], 0)

    def test_distribution_schema_defaults(self):
        schema = FuelDistributionSchema(
            start_date=date(2026, 11, 16),
            end_date=date(2026, 11, 22),
            days=7,
        )

        self.assertEqual(schema.total, 0)
        self.assertEqual(schema.rental_total, 0)
        self.assertEqual(schema.items, [])

        day = FuelDistributionDaySchema(fuel_date=date(2026, 11, 16))
        self.assertEqual(day.sru_liters, 0)
        self.assertEqual(day.dcu_liters, 0)
        self.assertEqual(day.rental_liters, 0)
        self.assertEqual(day.total_liters, 0)

    def test_dashboard_distribution_route_is_registered(self):
        routes = {
            (route.path, route.status_code)
            for route in fuel_log_router.router.routes
            if hasattr(route, "methods")
        }

        self.assertIn(("/statistics/daily", None), routes)


class FuelLogModelTests(unittest.TestCase):
    def test_table_is_append_only_by_contract(self):
        self.assertEqual(MachineFuelLogModel.__tablename__, "machine_fuel_logs")
        # No ``updated_at`` column: a saved row is a permanent log entry.
        self.assertNotIn("updated_at", MachineFuelLogModel.__table__.columns)
        self.assertNotIn("deleted_at", MachineFuelLogModel.__table__.columns)

    def test_required_and_optional_columns(self):
        columns = MachineFuelLogModel.__table__.columns

        self.assertFalse(columns.given_by.nullable)
        self.assertTrue(columns.note.nullable)
        self.assertFalse(columns.liters.nullable)

    def test_positive_liters_constraint_exists(self):
        constraints = {
            constraint.name
            for constraint in MachineFuelLogModel.__table__.constraints
            if constraint.name
        }

        self.assertIn("ck_machine_fuel_logs_liters_positive", constraints)

    def test_machine_date_index_exists(self):
        indexes = {index.name for index in MachineFuelLogModel.__table__.indexes}

        self.assertIn("ix_machine_fuel_logs_machine_date", indexes)


if __name__ == "__main__":
    unittest.main()
