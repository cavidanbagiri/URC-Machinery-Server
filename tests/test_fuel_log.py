"""Offline regression tests for the diesel distribution records.

Run from ``server/``:
    python -m unittest tests.test_fuel_log -v

These tests do not connect to PostgreSQL.  They cover the write schema, the
daily / weekly / monthly period helpers, the row-to-schema mapping and the
append-only table definition.
"""

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from pydantic import ValidationError

from models.fuel_log_model import MachineFuelLogModel
from repositories.fuel_log_repository import FuelLogRepository
from schemas.fuel_log_schemas import (
    FuelLogCreateSchema,
    FuelLogEntrySchema,
    FuelLogMachineSchema,
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

    def test_blank_given_by_is_rejected(self):
        with self.assertRaises(ValidationError):
            FuelLogCreateSchema(
                machine_id=1,
                fuel_date=date(2026, 11, 17),
                liters=10,
                given_by="   ",
            )

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

        daily, weekly, monthly = FuelLogRepository._period_totals(
            rows,
            target_date=date(2026, 11, 17),
            week_start=date(2026, 11, 11),
            month_start=date(2026, 11, 1),
        )

        self.assertEqual(daily, 40)
        self.assertEqual(weekly, 70)
        self.assertEqual(monthly, 100)

    def test_week_can_include_previous_month_but_month_total_cannot(self):
        rows = [
            SimpleNamespace(fuel_date=date(2026, 10, 29), liters=25),
            SimpleNamespace(fuel_date=date(2026, 11, 1), liters=5),
            SimpleNamespace(fuel_date=date(2026, 11, 3), liters=20),
        ]

        daily, weekly, monthly = FuelLogRepository._period_totals(
            rows,
            target_date=date(2026, 11, 3),
            week_start=date(2026, 10, 28),
            month_start=date(2026, 11, 1),
        )

        self.assertEqual(daily, 20)
        self.assertEqual(weekly, 50)
        self.assertEqual(monthly, 25)

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
