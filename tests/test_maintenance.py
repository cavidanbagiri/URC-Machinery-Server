"""Offline regression tests for periodic maintenance.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests exercise the pure status calculation and request validation. They
do not connect to PostgreSQL.
"""

import unittest
from datetime import date
from inspect import signature

from fastapi import HTTPException
from pydantic import ValidationError

from models.maintenance_model import MachineMaintenanceSettingModel
from repositories.maintenance_repository import (
    MAINTENANCE_INTERVAL_OPTIONS,
    STATUS_DEFINITIONS,
    STATUS_ORDER,
    MaintenanceRepository,
    compute_maintenance_status,
    resolve_current_counter,
    sort_maintenance_items,
    validate_maintenance_interval,
)
from schemas.maintenance_schemas import (
    MaintenanceCompleteSchema,
    MaintenanceDocumentSchema,
    MaintenanceFetchItemSchema,
    MaintenanceHistoryItemSchema,
    MaintenanceReadingCreateSchema,
    MaintenanceSettingUpdateSchema,
    MaintenanceSummarySchema,
)


def make_setting(**overrides):
    """Build an in-memory setting without touching the database."""

    values = {
        "machine_id": 1,
        "usage_unit": "km",
        "interval_value": 10_000.0,
        "last_counter": 10_000.0,
        "current_counter": 15_000.0,
        "is_active": True,
    }
    values.update(overrides)
    return MachineMaintenanceSettingModel(**values)


class MaintenanceStatusTests(unittest.TestCase):
    def test_missing_plan(self):
        result = compute_maintenance_status(None)

        self.assertEqual(result["status"]["code"], "plan_yok")
        self.assertFalse(result["has_plan"])
        self.assertFalse(result["is_active"])
        self.assertIsNone(result["remaining"])
        self.assertIsNone(result["next_counter"])
        self.assertIsNone(result["effective_warning_threshold"])

    def test_default_threshold_is_ten_percent_of_interval(self):
        result = compute_maintenance_status(make_setting())

        self.assertEqual(result["status"]["code"], "uygun")
        self.assertEqual(result["next_counter"], 20_000.0)
        self.assertEqual(result["remaining"], 5_000.0)
        self.assertEqual(result["effective_warning_threshold"], 1_000.0)

    def test_remaining_at_threshold_is_approaching(self):
        result = compute_maintenance_status(make_setting(current_counter=19_000.0))

        self.assertEqual(result["status"]["code"], "yaklasiyor")
        self.assertEqual(result["remaining"], 1_000.0)

        just_outside = compute_maintenance_status(
            make_setting(current_counter=18_999.99)
        )
        self.assertEqual(just_outside["status"]["code"], "uygun")

    def test_explicit_warning_threshold_wins(self):
        approaching = compute_maintenance_status(
            make_setting(current_counter=15_000.0, warning_threshold=6_000.0)
        )
        self.assertEqual(approaching["status"]["code"], "yaklasiyor")
        self.assertEqual(approaching["effective_warning_threshold"], 6_000.0)

        outside = compute_maintenance_status(
            make_setting(current_counter=15_000.0, warning_threshold=500.0)
        )
        self.assertEqual(outside["status"]["code"], "uygun")

    def test_zero_warning_threshold_never_warns_early(self):
        result = compute_maintenance_status(
            make_setting(current_counter=19_999.0, warning_threshold=0.0)
        )

        self.assertEqual(result["status"]["code"], "uygun")
        self.assertEqual(result["effective_warning_threshold"], 0.0)

    def test_reaching_next_counter_is_overdue(self):
        result = compute_maintenance_status(make_setting(current_counter=20_000.0))

        self.assertEqual(result["status"]["code"], "gecikmis")
        self.assertEqual(result["remaining"], 0.0)

    def test_overdue_remaining_is_not_clamped(self):
        result = compute_maintenance_status(make_setting(current_counter=20_500.0))

        self.assertEqual(result["status"]["code"], "gecikmis")
        self.assertEqual(result["remaining"], -500.0)

    def test_counter_below_last_is_data_warning(self):
        result = compute_maintenance_status(make_setting(current_counter=9_000.0))

        self.assertEqual(result["status"]["code"], "veri_uyarisi")
        self.assertEqual(result["remaining"], 11_000.0)

    def test_missing_counters_is_data_missing(self):
        missing_current = compute_maintenance_status(
            make_setting(current_counter=None)
        )
        self.assertEqual(missing_current["status"]["code"], "veri_eksik")
        self.assertEqual(missing_current["next_counter"], 20_000.0)
        self.assertIsNone(missing_current["remaining"])

        missing_last = compute_maintenance_status(make_setting(last_counter=None))
        self.assertEqual(missing_last["status"]["code"], "veri_eksik")
        self.assertIsNone(missing_last["next_counter"])

    def test_invalid_plan_data_is_data_missing(self):
        for setting in (
            make_setting(usage_unit="mile"),
            make_setting(interval_value=0.0),
        ):
            with self.subTest(setting=setting):
                result = compute_maintenance_status(setting)
                self.assertEqual(result["status"]["code"], "veri_eksik")
                self.assertTrue(result["has_plan"])

    def test_inactive_plan_has_priority(self):
        result = compute_maintenance_status(
            make_setting(is_active=False, current_counter=25_000.0)
        )

        self.assertEqual(result["status"]["code"], "pasif")
        self.assertFalse(result["is_active"])
        self.assertTrue(result["has_plan"])
        self.assertEqual(result["remaining"], -5_000.0)

    def test_status_definitions_are_consistent(self):
        self.assertEqual(set(STATUS_ORDER), set(STATUS_DEFINITIONS))
        self.assertEqual(len(STATUS_ORDER), len(STATUS_DEFINITIONS))
        for code in STATUS_ORDER:
            definition = STATUS_DEFINITIONS[code]
            self.assertEqual(definition["code"], code)
            self.assertTrue(definition["name"])
            self.assertTrue(definition["color"])

    def test_live_counter_overrides_the_plan_counter(self):
        result = compute_maintenance_status(
            make_setting(current_counter=15_000.0),
            live_counter=20_400.0,
        )

        self.assertEqual(result["status"]["code"], "gecikmis")
        self.assertEqual(result["remaining"], -400.0)
        self.assertEqual(result["next_counter"], 20_000.0)

    def test_live_counter_can_clear_a_data_warning(self):
        # KM / saat kaydı plan sayacından yeni: sayaç artık geriye gitmiyor.
        result = compute_maintenance_status(
            make_setting(current_counter=9_000.0),
            live_counter=12_000.0,
        )

        self.assertEqual(result["status"]["code"], "uygun")
        self.assertEqual(result["remaining"], 8_000.0)

    def test_missing_live_counter_falls_back_to_the_plan_counter(self):
        result = compute_maintenance_status(make_setting(), live_counter=None)

        self.assertEqual(result["remaining"], 5_000.0)


class MaintenanceCurrentCounterTests(unittest.TestCase):
    """The newest ``machine_meter_logs`` row feeds the "Güncel KM / Saat" cell."""

    def test_missing_plan_has_no_counter(self):
        self.assertEqual(
            resolve_current_counter(
                None,
                meter_km=1_000.0,
                meter_engine_hours=10.0,
                meter_log_date=date(2026, 11, 20),
            ),
            (None, None, None),
        )

    def test_newer_meter_reading_wins(self):
        value, value_date, source = resolve_current_counter(
            make_setting(current_counter=15_000.0),
            meter_km=17_250.0,
            meter_engine_hours=900.0,
            meter_log_date=date(2026, 11, 22),
        )

        self.assertEqual(value, 17_250.0)
        self.assertEqual(value_date, date(2026, 11, 22))
        self.assertEqual(source, "meter")

    def test_newer_plan_counter_keeps_the_counter_from_going_backwards(self):
        setting = make_setting(
            current_counter=15_000.0,
            current_counter_date=date(2026, 11, 21),
        )

        value, value_date, source = resolve_current_counter(
            setting,
            meter_km=12_000.0,
            meter_engine_hours=900.0,
            meter_log_date=date(2026, 11, 10),
        )

        self.assertEqual(value, 15_000.0)
        self.assertEqual(value_date, date(2026, 11, 21))
        self.assertEqual(source, "plan")

    def test_meter_wins_a_date_tie(self):
        setting = make_setting(
            current_counter=15_000.0,
            current_counter_date=date(2026, 11, 22),
        )

        value, _, source = resolve_current_counter(
            setting,
            meter_km=16_000.0,
            meter_engine_hours=900.0,
            meter_log_date=date(2026, 11, 22),
        )

        self.assertEqual(value, 16_000.0)
        self.assertEqual(source, "meter")

    def test_plan_counter_is_the_fallback_without_a_reading(self):
        setting = make_setting(
            current_counter=15_000.0,
            current_counter_date=date(2026, 11, 1),
        )

        value, value_date, source = resolve_current_counter(setting)

        self.assertEqual(value, 15_000.0)
        self.assertEqual(value_date, date(2026, 11, 1))
        self.assertEqual(source, "plan")

    def test_reading_is_used_when_the_plan_has_no_counter(self):
        value, value_date, source = resolve_current_counter(
            make_setting(current_counter=None),
            meter_km=8_000.0,
            meter_engine_hours=100.0,
            meter_log_date=date(2026, 11, 20),
        )

        self.assertEqual(value, 8_000.0)
        self.assertEqual(value_date, date(2026, 11, 20))
        self.assertEqual(source, "meter")

    def test_hour_unit_reads_the_engine_hours_column(self):
        value, _, source = resolve_current_counter(
            make_setting(
                usage_unit="hour",
                interval_value=500.0,
                last_counter=4_000.0,
                current_counter=None,
            ),
            meter_km=99_000.0,
            meter_engine_hours=4_250.25,
            meter_log_date=date(2026, 11, 22),
        )

        self.assertEqual(value, 4_250.25)
        self.assertEqual(source, "meter")

    def test_unknown_unit_ignores_the_meter_reading(self):
        value, _, source = resolve_current_counter(
            make_setting(usage_unit="mile", current_counter=15_000.0),
            meter_km=17_000.0,
            meter_engine_hours=900.0,
            meter_log_date=date(2026, 11, 22),
        )

        self.assertEqual(value, 15_000.0)
        self.assertEqual(source, "plan")


def make_sort_item(
    machine_id: int,
    remaining,
    status_code: str = "uygun",
    identification_no: str | None = None,
) -> dict:
    """Build the minimal item shape that ``sort_maintenance_items`` reads."""

    return {
        "machine_id": machine_id,
        "identification_no": identification_no or f"M-{machine_id:03d}",
        "remaining": remaining,
        "status": {"code": status_code},
    }


class MaintenanceSortTests(unittest.TestCase):
    def test_default_order_keeps_status_priority(self):
        items = [
            make_sort_item(1, 5_000.0, "uygun"),
            make_sort_item(2, None, "plan_yok"),
            make_sort_item(3, -500.0, "gecikmis"),
            make_sort_item(4, 200.0, "yaklasiyor"),
        ]

        sorted_items = sort_maintenance_items(items)

        self.assertEqual(
            [item["machine_id"] for item in sorted_items],
            # STATUS_ORDER: gecikmis, yaklasiyor, plan_yok, uygun
            [3, 4, 2, 1],
        )

    def test_remaining_asc_puts_most_overdue_first(self):
        items = [
            make_sort_item(1, 5_000.0),
            make_sort_item(2, None, "plan_yok"),
            make_sort_item(3, -500.0, "gecikmis"),
            make_sort_item(4, 0.0, "gecikmis"),
        ]

        sorted_items = sort_maintenance_items(
            items, sort_by="remaining", sort_order="asc"
        )

        self.assertEqual(
            [item["remaining"] for item in sorted_items],
            [-500.0, 0.0, 5_000.0, None],
        )

    def test_remaining_desc_keeps_rows_without_plan_last(self):
        items = [
            make_sort_item(1, 5_000.0),
            make_sort_item(2, None, "plan_yok"),
            make_sort_item(3, -500.0, "gecikmis"),
            make_sort_item(4, 0.0, "gecikmis"),
        ]

        sorted_items = sort_maintenance_items(
            items, sort_by="remaining", sort_order="desc"
        )

        self.assertEqual(
            [item["remaining"] for item in sorted_items],
            [5_000.0, 0.0, -500.0, None],
        )
        self.assertEqual(sorted_items[-1]["machine_id"], 2)

    def test_remaining_sort_uses_machine_no_as_tie_breaker(self):
        items = [
            make_sort_item(1, 1_000.0, identification_no="M-200"),
            make_sort_item(2, 1_000.0, identification_no="M-100"),
        ]

        ascending = sort_maintenance_items(
            list(items), sort_by="remaining", sort_order="asc"
        )
        descending = sort_maintenance_items(
            list(items), sort_by="remaining", sort_order="desc"
        )

        self.assertEqual(
            [item["identification_no"] for item in ascending], ["M-100", "M-200"]
        )
        self.assertEqual(
            [item["identification_no"] for item in descending], ["M-100", "M-200"]
        )


class MaintenanceSchemaTests(unittest.TestCase):
    def test_setting_rejects_invalid_values(self):
        invalid_payloads = (
            {"usage_unit": "mile"},
            {"interval_value": 0},
            {"interval_value": -1},
            {"last_counter": -1},
            {"current_counter": -0.01},
            {"warning_threshold": -1},
            {"unknown_field": 1},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    MaintenanceSettingUpdateSchema(**payload)

    def test_setting_accepts_partial_payload(self):
        data = MaintenanceSettingUpdateSchema(current_counter=12_345.0)

        self.assertEqual(data.current_counter, 12_345.0)
        self.assertIsNone(data.usage_unit)
        self.assertIsNone(data.interval_value)

    def test_reading_requires_non_negative_counter(self):
        with self.assertRaises(ValidationError):
            MaintenanceReadingCreateSchema(counter_value=-1)

        data = MaintenanceReadingCreateSchema(counter_value=0)
        self.assertEqual(data.counter_value, 0)

    def test_complete_accepts_optional_counter(self):
        data = MaintenanceCompleteSchema(
            notes="Filtre değişti",
            interval_value=500,
        )

        self.assertIsNone(data.counter_value)
        self.assertEqual(data.notes, "Filtre değişti")
        self.assertEqual(data.interval_value, 500)

        with self.assertRaises(ValidationError):
            MaintenanceCompleteSchema(counter_value=-1, interval_value=500)

    def test_complete_requires_a_positive_interval(self):
        with self.assertRaises(ValidationError):
            MaintenanceCompleteSchema(notes="Filtre değişti")

        with self.assertRaises(ValidationError):
            MaintenanceCompleteSchema(interval_value=0)

    def test_history_item_defaults_to_empty_documents(self):
        item = MaintenanceHistoryItemSchema(
            id=1,
            machine_id=2,
            record_type="maintenance",
            record_date=date(2026, 11, 17),
        )

        self.assertEqual(item.documents, [])

    def test_document_schema_exposes_metadata_only(self):
        document = MaintenanceDocumentSchema(
            id=5,
            record_id=10,
            file_name="bakim.pdf",
            file_size=2048,
        )

        self.assertEqual(document.content_type, "application/pdf")
        self.assertEqual(document.file_size, 2048)
        self.assertNotIn("file_data", MaintenanceDocumentSchema.model_fields)

    def test_complete_requires_a_pdf_document(self):
        from inspect import signature

        from repositories.maintenance_repository import MaintenanceRepository

        parameters = signature(
            MaintenanceRepository.complete_maintenance
        ).parameters
        self.assertIn("document", parameters)
        self.assertIsNone(parameters["document"].default)


class MaintenanceIntervalPresetTests(unittest.TestCase):
    """Completion packages are fixed per usage unit."""

    def test_presets_match_the_business_rules(self):
        self.assertEqual(
            MAINTENANCE_INTERVAL_OPTIONS["hour"],
            (500.0, 1_000.0, 2_000.0, 4_000.0),
        )
        self.assertEqual(
            MAINTENANCE_INTERVAL_OPTIONS["km"],
            (10_000.0, 20_000.0, 30_000.0, 40_000.0),
        )

    def test_accepts_only_the_matching_unit_preset(self):
        for value in (500, 1_000, 2_000, 4_000):
            with self.subTest(unit="hour", value=value):
                self.assertEqual(
                    validate_maintenance_interval("hour", value),
                    float(value),
                )

        for value in (10_000, 20_000, 30_000, 40_000):
            with self.subTest(unit="km", value=value):
                self.assertEqual(
                    validate_maintenance_interval("km", value),
                    float(value),
                )

        with self.assertRaises(HTTPException) as hour_error:
            validate_maintenance_interval("hour", 10_000)
        self.assertEqual(hour_error.exception.status_code, 400)

        with self.assertRaises(HTTPException) as km_error:
            validate_maintenance_interval("km", 500)
        self.assertEqual(km_error.exception.status_code, 400)

        with self.assertRaises(HTTPException) as retired_km_error:
            validate_maintenance_interval("km", 80_000)
        self.assertEqual(retired_km_error.exception.status_code, 400)

    def test_requires_a_package(self):
        with self.assertRaises(HTTPException) as error:
            validate_maintenance_interval("hour", None)
        self.assertEqual(error.exception.status_code, 400)

    def test_complete_endpoint_exposes_interval_field(self):
        from routers.maintenance_router import complete_maintenance

        params = signature(complete_maintenance).parameters
        self.assertIn("interval_value", params)


class MaintenanceColumnFilterTests(unittest.TestCase):
    """Marka/Model columns are filtered server-side, like the repair table."""

    COLUMN_FILTERS = ("car_mark_id", "car_model_id")

    def test_repository_accepts_mark_and_model_filters(self):
        from inspect import signature

        from repositories.maintenance_repository import MaintenanceRepository

        for method_name in ("_fetch_items", "fetch_paginated"):
            params = signature(
                getattr(MaintenanceRepository, method_name)
            ).parameters
            for filter_name in self.COLUMN_FILTERS:
                with self.subTest(method=method_name, filter=filter_name):
                    self.assertIn(filter_name, params)
                    self.assertIsNone(params[filter_name].default)

    def test_fetch_maintenance_endpoint_exposes_column_filters(self):
        from inspect import signature

        from routers.maintenance_router import fetch_maintenance

        params = signature(fetch_maintenance).parameters

        for filter_name in self.COLUMN_FILTERS:
            with self.subTest(filter=filter_name):
                self.assertIn(filter_name, params)
                # FastAPI wraps the default in Query(...)
                default = params[filter_name].default
                self.assertIsNone(getattr(default, "default", default))


class MaintenanceUpdateDateFilterTests(unittest.TestCase):
    """The page can list only the machines that were updated on one day."""

    def test_repository_accepts_the_update_date(self):
        for method_name in ("_fetch_items", "fetch_paginated"):
            params = signature(
                getattr(MaintenanceRepository, method_name)
            ).parameters
            with self.subTest(method=method_name):
                self.assertIn("updated_on", params)
                self.assertIsNone(params["updated_on"].default)

    def test_fetch_maintenance_endpoint_exposes_the_update_date(self):
        from routers.maintenance_router import fetch_maintenance

        params = signature(fetch_maintenance).parameters
        self.assertIn("updated_on", params)
        default = params["updated_on"].default
        self.assertIsNone(getattr(default, "default", default))


class MaintenanceMeterSnapshotSchemaTests(unittest.TestCase):
    """The list item carries the newest KM / motor saati reading."""

    def make_item(self, **overrides):
        values = {
            "machine_id": 1,
            "has_plan": True,
            "status": {"code": "uygun", "name": "Uygun", "color": "green"},
        }
        values.update(overrides)
        return MaintenanceFetchItemSchema(**values)

    def test_meter_fields_default_to_none(self):
        item = self.make_item()

        self.assertIsNone(item.meter_km)
        self.assertIsNone(item.meter_engine_hours)
        self.assertIsNone(item.meter_log_date)
        self.assertIsNone(item.counter_source)
        self.assertIsNone(item.plan_counter)
        self.assertIsNone(item.plan_counter_date)

    def test_meter_snapshot_is_accepted(self):
        item = self.make_item(
            current_counter=17_250.0,
            current_counter_date=date(2026, 11, 22),
            counter_source="meter",
            plan_counter=15_000.0,
            plan_counter_date=date(2026, 11, 1),
            meter_km=17_250.0,
            meter_engine_hours=1_234.0,
            meter_log_date=date(2026, 11, 22),
        )

        self.assertEqual(item.counter_source, "meter")
        self.assertEqual(item.meter_km, 17_250.0)
        self.assertEqual(item.meter_engine_hours, 1_234.0)
        self.assertEqual(item.plan_counter, 15_000.0)

    def test_summary_no_longer_counts_the_daily_maintenance(self):
        # "Günlük Bakım" kartı kaldırıldı: alan ne şemada ne de yanıtta var.
        self.assertNotIn("completed_today", MaintenanceSummarySchema.model_fields)


class MachineHistoryTypeFilterTests(unittest.TestCase):
    """The Bakım Geçmişi tab must not be filled with counter readings."""

    def test_history_repository_accepts_record_type_filter(self):
        params = signature(MaintenanceRepository.get_history).parameters
        self.assertIn("record_type", params)
        self.assertIsNone(params["record_type"].default)

    def test_history_endpoint_exposes_record_type_filter(self):
        from routers.maintenance_router import fetch_maintenance_history

        params = signature(fetch_maintenance_history).parameters
        self.assertIn("record_type", params)
        default = params["record_type"].default
        self.assertIsNone(getattr(default, "default", default))


if __name__ == "__main__":
    unittest.main()
