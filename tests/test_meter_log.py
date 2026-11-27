"""Offline regression tests for the KM / engine-hour readings.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not connect to PostgreSQL.  They cover the request validation,
the history-window helper, the row-to-schema mapping, the correction payload of
the **İşlemler → Düzenle** dialog and the table definition.
"""

import unittest
from collections import namedtuple
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from models.meter_log_model import MachineMeterLogModel
from repositories.fuel_log_window import DEFAULT_EDIT_WINDOW_DAYS
from repositories.meter_log_lookup import latest_meter_log_subquery
from repositories.meter_log_repository import (
    MAX_OVERVIEW_DAYS,
    MONTH_CHANGE_DAYS,
    MeterLogRepository,
)
from routers import meter_log_router
from schemas.meter_log_schemas import (
    MeterLogCreateSchema,
    MeterLogEntrySchema,
    MeterLogMachineSchema,
    MeterLogUpdateSchema,
)
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

    def test_machine_schema_carries_change_columns(self):
        empty = MeterLogMachineSchema(machine_id=5)

        self.assertIsNone(empty.last_change_km)
        self.assertIsNone(empty.month_change_from_date)

        parsed = MeterLogMachineSchema(
            machine_id=5,
            last_km=1500.0,
            last_log_date=date(2026, 11, 22),
            last_change_km=25.5,
            last_change_engine_hours=2.0,
            last_change_from_date=date(2026, 11, 21),
            month_change_km=640.0,
            month_change_engine_hours=48.0,
            month_change_from_date=date(2026, 10, 23),
        )

        self.assertEqual(parsed.last_change_km, 25.5)
        self.assertEqual(parsed.last_change_from_date, date(2026, 11, 21))
        self.assertEqual(parsed.month_change_engine_hours, 48.0)
        self.assertEqual(parsed.month_change_from_date, date(2026, 10, 23))

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
    def test_correction_keeps_the_row_identity(self):
        self.assertEqual(MachineMeterLogModel.__tablename__, "machine_meter_logs")
        # A correction rewrites the existing row: no audit / soft-delete columns
        # are added to the reading log.
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


class MeterLogCorrectionTests(unittest.TestCase):
    """``PUT /meter-logs/update/{log_id}``: fixing a saved reading in place."""

    def test_single_field_correction_is_enough(self):
        payload = MeterLogUpdateSchema(km=12345.5)

        self.assertEqual(payload.km, 12345.5)
        # Omitted fields keep their stored value (None = "do not touch").
        self.assertIsNone(payload.log_date)
        self.assertIsNone(payload.engine_hours)

    def test_date_can_be_corrected_alone(self):
        payload = MeterLogUpdateSchema(log_date=date(2026, 11, 24))

        self.assertEqual(payload.log_date, date(2026, 11, 24))
        self.assertIsNone(payload.km)

    def test_engine_hours_can_be_corrected_alone(self):
        payload = MeterLogUpdateSchema(engine_hours=987.25)

        self.assertEqual(payload.engine_hours, 987.25)

    def test_empty_payload_is_rejected(self):
        with self.assertRaises(ValidationError):
            MeterLogUpdateSchema()

    def test_future_date_is_rejected(self):
        with self.assertRaises(ValidationError):
            MeterLogUpdateSchema(log_date=date.today() + timedelta(days=1))

    def test_today_is_accepted(self):
        payload = MeterLogUpdateSchema(log_date=date.today())

        self.assertEqual(payload.log_date, date.today())

    def test_counters_must_stay_non_negative(self):
        for field in ("km", "engine_hours"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    MeterLogUpdateSchema(**{field: -0.01})

    def test_unknown_field_is_rejected(self):
        # The machine of a reading never changes: only its day and counters do.
        with self.assertRaises(ValidationError):
            MeterLogUpdateSchema(machine_id=3, km=10)

    def test_correction_routes_are_registered(self):
        routes: dict[str, set] = {}
        for route in meter_log_router.router.routes:
            if not hasattr(route, "methods"):
                continue
            routes.setdefault(route.path, set()).update(route.methods)

        self.assertIn("GET", routes["/overview"])
        self.assertIn("GET", routes["/entries"])
        self.assertIn("POST", routes["/create"])
        self.assertIn("PUT", routes["/update/{log_id}"])

    def test_dialog_lists_the_same_window_as_the_fuel_dialogs(self):
        default_days = (
            MeterLogRepository.fetch_entries.__defaults__[-1]
        )

        self.assertEqual(default_days, DEFAULT_EDIT_WINDOW_DAYS)


class MeterLogChangeHelperTests(unittest.TestCase):
    def test_difference_requires_both_values(self):
        self.assertIsNone(MeterLogRepository._difference(1500.0, None))
        self.assertIsNone(MeterLogRepository._difference(None, 1400.0))
        self.assertEqual(MeterLogRepository._difference(1500.0, 1400.0), 100.0)
        self.assertEqual(MeterLogRepository._difference(10, 2.555), 7.45)

    def test_latest_per_day_keeps_newest_save_and_sorts_by_day(self):
        rows = [
            {"log_date": date(2026, 11, 16), "km": 100.0, "engine_hours": 10.0},
            {"log_date": date(2026, 11, 17), "km": 150.0, "engine_hours": 12.0},
            {"log_date": date(2026, 11, 17), "km": 160.0, "engine_hours": 13.0},
        ]

        days = MeterLogRepository._latest_per_day(rows)

        self.assertEqual(
            [day["log_date"] for day in days],
            [date(2026, 11, 16), date(2026, 11, 17)],
        )
        self.assertEqual(days[-1]["km"], 160.0)
        self.assertEqual(days[-1]["engine_hours"], 13.0)

    def test_latest_per_day_of_empty_history(self):
        self.assertEqual(MeterLogRepository._latest_per_day([]), [])

    def test_reading_mapping(self):
        row = SimpleNamespace(
            log_date=date(2026, 11, 17),
            km=1500,
            engine_hours=42,
        )

        self.assertEqual(
            MeterLogRepository._reading(row),
            {
                "log_date": date(2026, 11, 17),
                "km": 1500.0,
                "engine_hours": 42.0,
            },
        )

    def test_month_window_is_thirty_days(self):
        self.assertEqual(MONTH_CHANGE_DAYS, 30)


READING_ROW = namedtuple(
    "READING_ROW",
    ["machine_id", "log_date", "km", "engine_hours"],
)

WINDOW_END = date(2026, 11, 22)


def reading(machine_id, log_date, km, engine_hours):
    return READING_ROW(machine_id, log_date, km, engine_hours)


def machine_item(machine_id, last_log_date):
    """Machine row as ``fetch_overview`` builds it before the changes are set."""

    return {
        "machine_id": machine_id,
        "last_log_date": last_log_date,
        "last_km": None,
        "last_engine_hours": None,
        "last_change_km": None,
        "last_change_engine_hours": None,
        "last_change_from_date": None,
        "month_change_km": None,
        "month_change_engine_hours": None,
        "month_change_from_date": None,
        "recent_logs": [],
    }


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class ScriptedDb:
    """Returns prepared rows in order so ``_attach_changes`` runs offline.

    ``_attach_changes`` issues exactly two selects: the readings inside the
    month window, then the newest readings before it.
    """

    def __init__(self, window_rows, older_rows):
        self.results = [list(window_rows), list(older_rows)]
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.results.pop(0))


class MeterLogChangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_changes_between_readings(self):
        machines = {
            1: machine_item(1, date(2026, 11, 22)),
            2: machine_item(2, date(2026, 11, 22)),
            3: machine_item(3, date(2026, 11, 22)),
            4: machine_item(4, None),
        }

        db = ScriptedDb(
            window_rows=[
                # Aynı gün iki kayıt: son kayıt geçerlidir (1235 / 156).
                reading(1, date(2026, 11, 20), 1200, 150),
                reading(1, date(2026, 11, 21), 1230, 155),
                reading(1, date(2026, 11, 21), 1235, 156),
                reading(1, date(2026, 11, 22), 1250, 160),
                # Tek okuma: karşılaştırılacak gün yok.
                reading(2, date(2026, 11, 22), 500, 20),
                # Pencerede tek gün, tabanı bir aydan eski.
                reading(3, date(2026, 11, 22), 300, 10),
            ],
            older_rows=[
                reading(1, date(2026, 10, 10), 1000, 120),
                reading(3, date(2026, 9, 1), 250, 8),
            ],
        )

        repository = MeterLogRepository(db)
        await repository._attach_changes(machines, WINDOW_END)

        self.assertEqual(machines[1]["last_change_km"], 15.0)
        self.assertEqual(machines[1]["last_change_engine_hours"], 4.0)
        self.assertEqual(
            machines[1]["last_change_from_date"], date(2026, 11, 21)
        )
        # Aylık toplam pencerenin ilk gününden (20 Kasım) hesaplanır; bir aydan
        # eski okuma (10 Ekim) artık taban değildir.
        self.assertEqual(machines[1]["month_change_km"], 50.0)
        self.assertEqual(machines[1]["month_change_engine_hours"], 10.0)
        self.assertEqual(
            machines[1]["month_change_from_date"], date(2026, 11, 20)
        )

        self.assertIsNone(machines[2]["last_change_km"])
        self.assertIsNone(machines[2]["last_change_from_date"])
        self.assertIsNone(machines[2]["month_change_km"])

        self.assertEqual(machines[3]["last_change_km"], 50.0)
        self.assertEqual(machines[3]["last_change_from_date"], date(2026, 9, 1))
        # Pencerede tek gün var: bir aylık toplam için ikinci okuma yok.
        self.assertIsNone(machines[3]["month_change_km"])
        self.assertIsNone(machines[3]["month_change_engine_hours"])
        self.assertIsNone(machines[3]["month_change_from_date"])

        self.assertIsNone(machines[4]["last_change_km"])
        self.assertIsNone(machines[4]["month_change_km"])

        # Sorgular PostgreSQL lehçesinde derlenebilmeli (canlı DB'de koşacak).
        window_sql = str(
            db.statements[0].compile(dialect=postgresql.dialect())
        )
        history_sql = str(
            db.statements[1].compile(dialect=postgresql.dialect())
        )
        self.assertIn("machine_meter_logs", window_sql)
        self.assertIn("row_number", history_sql)

    async def test_changes_ignore_machines_outside_the_page(self):
        machines = {1: machine_item(1, date(2026, 11, 22))}

        db = ScriptedDb(
            window_rows=[
                reading(1, date(2026, 11, 18), 100, 5),
                reading(1, date(2026, 11, 22), 180, 9),
                reading(99, date(2026, 11, 22), 900, 90),
            ],
            older_rows=[reading(99, date(2026, 8, 1), 800, 80)],
        )

        await MeterLogRepository(db)._attach_changes(machines, WINDOW_END)

        self.assertEqual(machines[1]["last_change_km"], 80.0)
        # Geçmişi pencereye sığan makinede aylık taban ilk okumadır.
        self.assertEqual(machines[1]["month_change_km"], 80.0)
        self.assertEqual(
            machines[1]["month_change_from_date"], date(2026, 11, 18)
        )
        self.assertNotIn(99, machines)

    async def test_month_total_uses_available_days_not_only_a_full_month(self):
        """Kısa geçmişte de dolmalı: 5 günlük veri → 5 günlük toplam."""

        machines = {1: machine_item(1, date(2026, 11, 22))}

        db = ScriptedDb(
            window_rows=[
                reading(1, date(2026, 11, 18), 1000, 100),
                reading(1, date(2026, 11, 19), 1010, 101),
                reading(1, date(2026, 11, 20), 1025, 102.5),
                reading(1, date(2026, 11, 21), 1040, 104),
                reading(1, date(2026, 11, 22), 1060, 106),
            ],
            # Bir aydan eski okuma aylık toplama katılmaz.
            older_rows=[reading(1, date(2026, 8, 1), 900, 90)],
        )

        await MeterLogRepository(db)._attach_changes(machines, WINDOW_END)

        self.assertEqual(machines[1]["month_change_km"], 60.0)
        self.assertEqual(machines[1]["month_change_engine_hours"], 6.0)
        self.assertEqual(
            machines[1]["month_change_from_date"], date(2026, 11, 18)
        )
        # "Son Gün/KM" yine önceki güne göre hesaplanır.
        self.assertEqual(machines[1]["last_change_km"], 20.0)
        self.assertEqual(
            machines[1]["last_change_from_date"], date(2026, 11, 21)
        )

    async def test_no_readings_leaves_changes_empty(self):
        machines = {1: machine_item(1, None)}

        db = ScriptedDb(window_rows=[], older_rows=[])
        await MeterLogRepository(db)._attach_changes(machines, WINDOW_END)

        self.assertEqual(db.statements, [])
        self.assertIsNone(machines[1]["last_change_km"])


if __name__ == "__main__":
    unittest.main()
