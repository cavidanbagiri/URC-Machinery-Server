"""Offline regression tests for the KM / engine-hour readings.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not connect to PostgreSQL.  They cover the request validation,
the history-window helper, the row-to-schema mapping and the immutable table
definition.
"""

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from pydantic import ValidationError

from models.meter_log_model import MachineMeterLogModel
from repositories.meter_log_lookup import latest_meter_log_subquery
from repositories.meter_log_repository import MAX_OVERVIEW_DAYS, MeterLogRepository
from schemas.meter_log_schemas import MeterLogCreateSchema, MeterLogEntrySchema
from schemas.repair_schemas import RepairMachineOptionSchema
from schemas.tire_schemas import TireMachineOptionSchema


class MeterLogSchemaTests(unittest.TestCase):
    def test_valid_payload(self):
        payload = MeterLogCreateSchema(
            machine_id=12,
            log_date=date(2026, 11, 17),
            km=12345.5,
            engine_hours=987.25,
        )

        self.assertEqual(payload.machine_id, 12)
        self.assertEqual(payload.km, 12345.5)

    def test_negative_values_are_rejected(self):
        for field in ("km", "engine_hours"):
            with self.subTest(field=field):
                values = {
                    "machine_id": 1,
                    "log_date": date(2026, 11, 17),
                    "km": 100.0,
                    "engine_hours": 10.0,
                }
                values[field] = -0.01
                with self.assertRaises(ValidationError):
                    MeterLogCreateSchema(**values)

    def test_machine_and_date_are_required(self):
        with self.assertRaises(ValidationError):
            MeterLogCreateSchema(km=10.0, engine_hours=1.0, log_date=date.today())

        with self.assertRaises(ValidationError):
            MeterLogCreateSchema(machine_id=1, km=10.0, engine_hours=1.0)

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            MeterLogCreateSchema(
                machine_id=1,
                log_date=date.today(),
                km=10.0,
                engine_hours=1.0,
                note="not part of the contract",
            )


class MeterLogWindowTests(unittest.TestCase):
    def test_latest_subquery_exposes_snapshot_columns(self):
        latest = latest_meter_log_subquery()

        self.assertEqual(
            set(latest.c.keys()),
            {
                "machine_id",
                "last_km",
                "last_engine_hours",
                "last_log_date",
                "last_logged_at",
                "row_number",
            },
        )

    def test_machine_picker_schemas_accept_snapshot(self):
        snapshot = {
            "id": 12,
            "identification_no": "1042",
            "last_km": 12345.5,
            "last_engine_hours": 987.25,
            "last_log_date": date(2026, 11, 17),
        }

        for schema in (RepairMachineOptionSchema, TireMachineOptionSchema):
            with self.subTest(schema=schema.__name__):
                parsed = schema(**snapshot)
                self.assertEqual(parsed.last_km, 12345.5)
                self.assertEqual(parsed.last_engine_hours, 987.25)
                self.assertEqual(parsed.last_log_date, date(2026, 11, 17))

    def test_window_ends_on_selected_day_and_is_inclusive(self):
        start, end = MeterLogRepository._resolve_window(
            days=7,
            end_date=date(2026, 11, 17),
        )

        self.assertEqual(end, date(2026, 11, 17))
        self.assertEqual(start, date(2026, 11, 11))
        self.assertEqual((end - start).days + 1, 7)

    def test_window_defaults_to_today(self):
        start, end = MeterLogRepository._resolve_window(days=1, end_date=None)

        self.assertEqual(end, date.today())
        self.assertEqual(start, end)

    def test_window_is_clamped(self):
        start, end = MeterLogRepository._resolve_window(
            days=0,
            end_date=date(2026, 11, 17),
        )
        self.assertEqual(start, end)

        start, end = MeterLogRepository._resolve_window(
            days=999,
            end_date=date(2026, 11, 17),
        )
        self.assertEqual((end - start).days + 1, MAX_OVERVIEW_DAYS)

    def test_creator_name(self):
        self.assertEqual(
            MeterLogRepository._creator_name("Ali", "Veli"),
            "Ali Veli",
        )
        self.assertEqual(MeterLogRepository._creator_name("Ali", None), "Ali")
        self.assertIsNone(MeterLogRepository._creator_name(None, None))
        self.assertIsNone(MeterLogRepository._creator_name("  ", " "))

    def test_entry_mapping(self):
        row = SimpleNamespace(
            id=7,
            machine_id=3,
            log_date=date(2026, 11, 17),
            km=1500,
            engine_hours=42,
            created_by_id=9,
            entered_by_firstname="Ayşe",
            entered_by_lastname="Yılmaz",
            created_at=datetime(2026, 11, 17, 8, 30, tzinfo=timezone.utc),
        )

        entry = MeterLogRepository._entry(row)
        schema = MeterLogEntrySchema(**entry)

        self.assertEqual(schema.id, 7)
        self.assertEqual(schema.km, 1500.0)
        self.assertEqual(schema.engine_hours, 42.0)
        self.assertEqual(schema.entered_by_name, "Ayşe Yılmaz")


class MeterLogModelTests(unittest.TestCase):
    def test_table_is_append_only_by_contract(self):
        self.assertEqual(MachineMeterLogModel.__tablename__, "machine_meter_logs")
        # No ``updated_at`` column: a saved row is a permanent log entry.
        self.assertNotIn("updated_at", MachineMeterLogModel.__table__.columns)
        self.assertNotIn("deleted_at", MachineMeterLogModel.__table__.columns)

    def test_non_negative_constraints_exist(self):
        constraints = {
            constraint.name
            for constraint in MachineMeterLogModel.__table__.constraints
            if constraint.name
        }

        self.assertIn("ck_machine_meter_logs_km_non_negative", constraints)
        self.assertIn(
            "ck_machine_meter_logs_engine_hours_non_negative",
            constraints,
        )

    def test_machine_date_index_exists(self):
        indexes = {index.name for index in MachineMeterLogModel.__table__.indexes}

        self.assertIn("ix_machine_meter_logs_machine_date", indexes)


if __name__ == "__main__":
    unittest.main()
