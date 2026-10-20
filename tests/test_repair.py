"""Offline regression tests for machine repair (tamir) rules.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL. They cover the pure timing/suggestion
helpers, backend log messages and request validation.
"""

import unittest
from datetime import date, timedelta

from pydantic import ValidationError

from repositories.repair_repository import (
    QUICK_OPEN_REPAIR_TYPE_NAME,
    REPAIR_STATUS_DEFINITIONS,
    REPAIR_STATUS_ORDER,
    build_created_message,
    build_quick_open_message,
    build_updated_message,
    compute_repair_timing,
    suggest_exit_date,
)
from schemas.repair_schemas import (
    RepairCancelSchema,
    RepairCloseSchema,
    RepairCreateSchema,
    RepairNoteCreateSchema,
    RepairUpdateSchema,
)


class RepairTimingTests(unittest.TestCase):
    def test_active_repair_duration_and_remaining(self):
        entry = date(2026, 10, 1)
        result = compute_repair_timing(
            "tamirde",
            entry,
            estimated_exit_date=date(2026, 10, 10),
            today=date(2026, 10, 5),
        )

        self.assertEqual(result["duration_days"], 4)
        self.assertEqual(result["days_remaining"], 5)
        self.assertFalse(result["is_overdue"])

    def test_active_repair_can_be_overdue(self):
        result = compute_repair_timing(
            "tamirde",
            date(2026, 10, 1),
            estimated_exit_date=date(2026, 10, 3),
            today=date(2026, 10, 6),
        )

        self.assertEqual(result["days_remaining"], -3)
        self.assertTrue(result["is_overdue"])
        self.assertEqual(result["duration_days"], 5)

    def test_completed_duration_uses_exit_date(self):
        result = compute_repair_timing(
            "tamamlandi",
            date(2026, 10, 1),
            estimated_exit_date=date(2026, 10, 4),
            exit_date=date(2026, 10, 6),
            today=date(2026, 10, 20),
        )

        self.assertEqual(result["duration_days"], 5)
        self.assertIsNone(result["days_remaining"])
        self.assertFalse(result["is_overdue"])

    def test_cancelled_without_exit_has_no_duration(self):
        result = compute_repair_timing("iptal", date(2026, 10, 1))

        self.assertIsNone(result["duration_days"])
        self.assertIsNone(result["days_remaining"])
        self.assertFalse(result["is_overdue"])

    def test_missing_estimate_has_no_remaining(self):
        result = compute_repair_timing(
            "tamirde",
            date(2026, 10, 1),
            today=date(2026, 10, 20),
        )

        self.assertEqual(result["duration_days"], 19)
        self.assertIsNone(result["days_remaining"])
        self.assertFalse(result["is_overdue"])


class RepairEstimateTests(unittest.TestCase):
    def test_suggestion_rounds_and_never_returns_today(self):
        today = date(2026, 10, 20)

        self.assertEqual(
            suggest_exit_date(4.4, today=today),
            today + timedelta(days=4),
        )
        self.assertEqual(
            suggest_exit_date(4.6, today=today),
            today + timedelta(days=5),
        )
        self.assertEqual(
            suggest_exit_date(0, today=today),
            today + timedelta(days=1),
        )

    def test_status_definitions_are_consistent(self):
        self.assertEqual(set(REPAIR_STATUS_ORDER), set(REPAIR_STATUS_DEFINITIONS))
        for code in REPAIR_STATUS_ORDER:
            definition = REPAIR_STATUS_DEFINITIONS[code]
            self.assertEqual(definition["code"], code)
            self.assertTrue(definition["name"])
            self.assertTrue(definition["color"])


class RepairMessageTests(unittest.TestCase):
    def test_created_message_includes_type_and_fault(self):
        message = build_created_message("Mekanik", "Motor bölmesi")

        self.assertIn("Mekanik", message)
        self.assertIn("Motor bölmesi", message)

    def test_created_message_without_fault_is_still_complete(self):
        message = build_created_message("Hidrolik", None)

        self.assertIn("Hidrolik", message)
        self.assertNotIn("Arıza yeri", message)

    def test_updated_message_lists_changes(self):
        message = build_updated_message(["tamir tipi (Elektrik)", "notlar"])

        self.assertEqual(
            message,
            "Tamir kaydı güncellendi: tamir tipi (Elektrik), notlar.",
        )

    def test_quick_open_message_points_to_repair_page(self):
        message = build_quick_open_message()

        self.assertIn("tamire alındı", message)
        self.assertIn("Tamir sayfasından", message)
        self.assertEqual(QUICK_OPEN_REPAIR_TYPE_NAME, "Diğer")


class RepairSchemaTests(unittest.TestCase):
    def test_create_defaults_entry_date_to_today(self):
        data = RepairCreateSchema(machine_id=1, repair_type_id=2)

        self.assertEqual(data.entry_date, date.today())
        self.assertIsNone(data.estimated_exit_date)

    def test_create_rejects_invalid_ids_and_unknown_fields(self):
        invalid_payloads = (
            {"machine_id": 0, "repair_type_id": 1},
            {"machine_id": 1, "repair_type_id": 0},
            {"machine_id": 1, "repair_type_id": 1, "status": "tamamlandi"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    RepairCreateSchema(**payload)

    def test_create_rejects_estimate_before_entry(self):
        with self.assertRaises(ValidationError):
            RepairCreateSchema(
                machine_id=1,
                repair_type_id=1,
                entry_date=date(2026, 10, 10),
                estimated_exit_date=date(2026, 10, 9),
            )

    def test_update_rejects_status_and_empty_type(self):
        with self.assertRaises(ValidationError):
            RepairUpdateSchema(status="tamamlandi")

        with self.assertRaises(ValidationError):
            RepairUpdateSchema(repair_type_id=0)

    def test_update_allows_clearing_optional_fields(self):
        data = RepairUpdateSchema(fault_location=None, notes="")

        payload = data.model_dump(exclude_unset=True)
        self.assertIn("fault_location", payload)
        self.assertIn("notes", payload)
        self.assertIsNone(data.fault_location)
        self.assertIsNone(data.notes)

    def test_close_requires_exit_date(self):
        with self.assertRaises(ValidationError):
            RepairCloseSchema(notes="Bitti")

        data = RepairCloseSchema(exit_date=date(2026, 10, 20))
        self.assertEqual(data.exit_date, date(2026, 10, 20))

    def test_cancel_requires_a_non_blank_reason(self):
        for reason in ("", "   "):
            with self.subTest(reason=reason):
                with self.assertRaises(ValidationError):
                    RepairCancelSchema(reason=reason)

        self.assertEqual(
            RepairCancelSchema(reason="  Parça temin edilemedi  ").reason,
            "Parça temin edilemedi",
        )

    def test_note_requires_content_and_trims(self):
        with self.assertRaises(ValidationError):
            RepairNoteCreateSchema(note="  ")

        self.assertEqual(
            RepairNoteCreateSchema(note="  Parça bekleniyor  ").note,
            "Parça bekleniyor",
        )


if __name__ == "__main__":
    unittest.main()
