"""Offline regression tests for periodic maintenance.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests exercise the pure status calculation and request validation. They
do not connect to PostgreSQL.
"""

import unittest

from pydantic import ValidationError

from models.maintenance_model import MachineMaintenanceSettingModel
from repositories.maintenance_repository import (
    STATUS_DEFINITIONS,
    STATUS_ORDER,
    compute_maintenance_status,
    sort_maintenance_items,
)
from schemas.maintenance_schemas import (
    MaintenanceCompleteSchema,
    MaintenanceReadingCreateSchema,
    MaintenanceSettingUpdateSchema,
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
        data = MaintenanceCompleteSchema(notes="Filtre değişti")

        self.assertIsNone(data.counter_value)
        self.assertEqual(data.notes, "Filtre değişti")

        with self.assertRaises(ValidationError):
            MaintenanceCompleteSchema(counter_value=-1)


if __name__ == "__main__":
    unittest.main()
